"""Server-side refresh-token rotation chains (GAP G5).

Before this module, ``/auth/refresh`` minted a new refresh token while the
presented one stayed valid until its 7-day expiry: a stolen refresh token
was usable for a week with no signal. Rotation chains close that hole:

* every login creates one chain row holding the live token id (``jti``);
* every refresh rotates ``current_jti`` and remembers the superseded id
  for ``REPLAY_GRACE`` so racing clients (two tabs, SSR + browser) that
  retry with the just-rotated token still succeed idempotently;
* presenting any *other* previously-seen-or-unknown id proves the chain
  forked — i.e. a stolen token is in play — so **all** chains of the user
  are wiped (every session revoked) and the caller gets 401;
* tokens minted before this hardening carry no ``jti`` and are adopted
  into a fresh chain on first use (rolling deploys keep working).

Table growth is bounded: chains expire with the refresh TTL and each
login/refresh prunes expired rows plus anything beyond ``MAX_CHAINS``
live chains per user.
"""

import logging
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .models import RefreshTokenChain

logger = logging.getLogger(__name__)

REPLAY_GRACE = timedelta(seconds=60)
MAX_CHAINS = 20

ConsumeOutcome = Literal["rotated", "replayed", "adopted", "revoked"]


def _refresh_expiry(now: datetime) -> datetime:
    return now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


async def prune_chains(db: AsyncSession, user_id: UUID, now: datetime) -> None:
    """Drop expired chains and cap live chains per user (no commit)."""
    await db.execute(
        delete(RefreshTokenChain).where(
            RefreshTokenChain.user_id == user_id,
            RefreshTokenChain.expires_at <= now,
        )
    )
    live_ids = (
        (
            await db.execute(
                select(RefreshTokenChain.id)
                .where(RefreshTokenChain.user_id == user_id)
                .order_by(RefreshTokenChain.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    for stale_id in live_ids[MAX_CHAINS:]:
        await db.execute(delete(RefreshTokenChain).where(RefreshTokenChain.id == stale_id))


async def create_chain(db: AsyncSession, user_id: UUID, now: datetime) -> RefreshTokenChain:
    """Open a new rotation chain for a fresh login (no commit)."""
    await prune_chains(db, user_id, now)
    chain = RefreshTokenChain(
        id=uuid4(),
        user_id=user_id,
        current_jti=uuid4().hex,
        expires_at=_refresh_expiry(now),
    )
    db.add(chain)
    return chain


async def consume_chain(
    db: AsyncSession, user_id: UUID, jti: str | None, now: datetime
) -> tuple[ConsumeOutcome, RefreshTokenChain | None]:
    """Validate a presented refresh ``jti`` against the user's chains.

    Returns ``(outcome, chain)``; the caller commits. On ``"revoked"``
    every chain of the user has been deleted and ``chain`` is ``None``.
    """
    if jti is None:
        # Pre-hardening token: adopt it into a fresh chain. The caller
        # mints the replacement refresh token with the new chain's jti.
        chain = await create_chain(db, user_id, now)
        return "adopted", chain

    current = (
        await db.execute(
            select(RefreshTokenChain).where(
                RefreshTokenChain.user_id == user_id,
                RefreshTokenChain.current_jti == jti,
                RefreshTokenChain.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if current is not None:
        previous = current.current_jti
        current.previous_jti = previous
        current.current_jti = uuid4().hex
        current.rotated_at = now
        return "rotated", current

    replay = (
        await db.execute(
            select(RefreshTokenChain).where(
                RefreshTokenChain.user_id == user_id,
                RefreshTokenChain.previous_jti == jti,
                RefreshTokenChain.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if (
        replay is not None
        and replay.rotated_at is not None
        and now - replay.rotated_at <= REPLAY_GRACE
    ):
        # Raced retry with the just-superseded token: hand back the live
        # pair without rotating again (idempotent, no false alarm).
        return "replayed", replay

    # Unknown or long-superseded token id: the chain forked, treat as
    # theft and revoke every session of this user.
    await db.execute(delete(RefreshTokenChain).where(RefreshTokenChain.user_id == user_id))
    logger.warning("Refresh token reuse detected for user %s; all sessions revoked", user_id)
    return "revoked", None
