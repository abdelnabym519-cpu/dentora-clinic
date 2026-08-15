"""Time-limited demo/trial helpers.

Trial mode is deployment-scoped and opt-in. Offline/paid installations keep
``TRIAL_MODE=false`` (the default) and are never time-limited.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status

from app.config import settings


@dataclass(frozen=True)
class TrialStatus:
    """Current deployment trial state."""

    enabled: bool
    started_at: datetime | None
    expires_at: datetime | None
    expired: bool
    remaining_seconds: int | None


def _parse_started_at(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None

    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def get_trial_status(*, now: datetime | None = None) -> TrialStatus:
    """Return trial state from deployment settings.

    A trial only becomes active when both ``TRIAL_MODE`` is enabled and a
    fixed ``TRIAL_STARTED_AT`` timestamp is provided. Keeping the start time
    in deployment configuration means container restarts cannot reset the
    three-day clock.
    """
    if not settings.TRIAL_MODE:
        return TrialStatus(False, None, None, False, None)

    started_at = _parse_started_at(settings.TRIAL_STARTED_AT)
    if started_at is None:
        return TrialStatus(False, None, None, False, None)

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)

    expires_at = started_at + timedelta(days=settings.TRIAL_DAYS)
    remaining = max(0, int((expires_at - current).total_seconds()))

    return TrialStatus(
        enabled=True,
        started_at=started_at,
        expires_at=expires_at,
        expired=current >= expires_at,
        remaining_seconds=remaining,
    )


def ensure_trial_active() -> None:
    """Reject clinic operations after an enabled trial expires."""
    trial = get_trial_status()
    if not trial.enabled or not trial.expired:
        return

    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "code": "trial_expired",
            "message": "The 3-day trial period has ended.",
            "expires_at": trial.expires_at.isoformat() if trial.expires_at else None,
        },
    )
