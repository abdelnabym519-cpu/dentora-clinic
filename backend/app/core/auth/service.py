"""Authentication service for JWT and password handling."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import bcrypt
from jose import jwt

from app.config import settings


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# ---------------------------------------------------------------------------
# Login online-guessing throttle (GAP G1)
# ---------------------------------------------------------------------------
# IP rate limits alone cannot stop distributed credential stuffing (every
# bot gets its own 5/minute bucket). The per-account throttle below counts
# consecutive failures on the user row: after ``LOGIN_FREE_ATTEMPTS`` the
# account demands an exponentially growing wait (capped), enforced with
# HTTP 429 + ``Retry-After`` — never by sleeping a worker. Success resets
# the counters; failures older than a day decay so ancient attempts do not
# haunt the account forever.
LOGIN_FREE_ATTEMPTS = 5
LOGIN_ATTEMPT_DECAY = timedelta(days=1)
LOGIN_MAX_BACKOFF = timedelta(minutes=15)

# Fixed hash used to burn the same bcrypt cost when the email does not
# exist, so "unknown email" answers take as long as "wrong password" and
# timing alone cannot enumerate accounts. Computed once at import.
_DUMMY_PASSWORD_HASH: str = hash_password("dummy-password-for-timing-equality-000")


def verify_password_constant_time(plain_password: str, hashed_password: str | None) -> bool:
    """Verify a password, equalizing timing for unknown accounts.

    When ``hashed_password`` is ``None`` (no such user) the candidate is
    still checked against a fixed dummy hash so the response costs one
    bcrypt verification either way. Always returns ``False`` then.
    """
    if hashed_password is None:
        bcrypt.checkpw(plain_password.encode("utf-8"), _DUMMY_PASSWORD_HASH.encode("utf-8"))
        return False
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def login_backoff_remaining(
    attempts: int, last_failure_at: datetime | None, now: datetime
) -> timedelta:
    """Return how much longer a login must wait, or zero if allowed."""
    if attempts < LOGIN_FREE_ATTEMPTS or last_failure_at is None:
        return timedelta(0)
    if last_failure_at.tzinfo is None:
        last_failure_at = last_failure_at.replace(tzinfo=UTC)
    if now - last_failure_at >= LOGIN_ATTEMPT_DECAY:
        return timedelta(0)
    backoff = min(
        timedelta(minutes=1) * (2 ** (attempts - LOGIN_FREE_ATTEMPTS)),
        LOGIN_MAX_BACKOFF,
    )
    remaining = (last_failure_at + backoff) - now
    return remaining if remaining > timedelta(0) else timedelta(0)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password meets minimum requirements.

    Returns (is_valid, error_message).
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"

    has_letter = any(c.isalpha() for c in password)
    has_number = any(c.isdigit() for c in password)

    if not has_letter or not has_number:
        return False, "Password must contain at least one letter and one number"

    return True, ""


def create_access_token(
    user_id: UUID,
    clinic_id: UUID | None = None,
    token_version: int = 0,
) -> str:
    """Create a JWT access token."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "access",
        "token_version": token_version,
    }
    if clinic_id:
        payload["clinic_id"] = str(clinic_id)

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(user_id: UUID, token_version: int = 0, jti: str | None = None) -> str:
    """Create a JWT refresh token.

    ``jti`` binds the token to a server-side rotation chain (see
    ``app.core.auth.refresh_chains``). Tokens minted without one predate
    the hardening and are adopted into a fresh chain on first use.
    """
    expire = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
        "token_version": token_version,
        "jti": jti or uuid4().hex,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token.

    Raises JWTError if token is invalid or expired.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
