from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.config import settings

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class LicenseError(RuntimeError):
    pass


class LicenseUnavailableError(LicenseError):
    """The license service could not be reached or returned a transient 5xx."""


class LicenseRejectedError(LicenseError):
    """The license service explicitly rejected this license/activation."""

    def __init__(self, message: str, status_code: int = 403) -> None:
        super().__init__(message)
        self.status_code = status_code


class LicenseManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def license_dir(self) -> Path:
        return Path(settings.STORAGE_LOCAL_PATH) / "license"

    @property
    def installation_file(self) -> Path:
        return self.license_dir / "installation_id.txt"

    @property
    def state_file(self) -> Path:
        return self.license_dir / "lease.json"

    def _ensure_dir(self) -> None:
        self.license_dir.mkdir(parents=True, exist_ok=True)

    def installation_id(self) -> str:
        self._ensure_dir()
        if self.installation_file.exists():
            value = self.installation_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        value = str(uuid4())
        self.installation_file.write_text(value, encoding="utf-8")
        return value

    def _load_state(self) -> dict:
        if not self.state_file.exists():
            return {}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Could not read local license state")
            return {}

    def _save_state(self, state: dict) -> None:
        self._ensure_dir()
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.state_file)

    def _public_key(self) -> Ed25519PublicKey:
        if not settings.LICENSE_PUBLIC_KEY_B64:
            raise LicenseError("License public key is not configured")
        try:
            pem = base64.b64decode(settings.LICENSE_PUBLIC_KEY_B64)
            key = serialization.load_pem_public_key(pem)
        except Exception as exc:
            raise LicenseError("License public key is invalid") from exc
        if not isinstance(key, Ed25519PublicKey):
            raise LicenseError("License public key must be Ed25519")
        return key

    def _verify_token(self, token: str) -> dict:
        try:
            payload_part, signature_part = token.split(".", 1)
            raw = b64url_decode(payload_part)
            signature = b64url_decode(signature_part)
            self._public_key().verify(signature, raw)
            payload = json.loads(raw)
        except (ValueError, InvalidSignature, json.JSONDecodeError) as exc:
            raise LicenseError("License lease signature is invalid") from exc
        if not isinstance(payload, dict):
            raise LicenseError("License lease payload is invalid")
        if payload.get("product") != "dentora" or payload.get("v") != 1:
            raise LicenseError("License lease is for another product or version")
        return payload

    def _status_from_state(self, state: dict) -> dict:
        installation_id = self.installation_id()
        base = {
            "enforced": settings.LICENSE_ENFORCEMENT,
            "installation_id": installation_id,
            "active": False,
            "state": "unlicensed",
            "reason": None,
            "customer_name": None,
            "plan": None,
            "features": [],
            "license_expires_at": None,
            "refresh_after": None,
            "valid_until": None,
            "needs_refresh": False,
        }
        if not settings.LICENSE_ENFORCEMENT:
            return {**base, "active": True, "state": "disabled"}
        if (
            not settings.LICENSE_SERVER_URL
            or not settings.LICENSE_PUBLIC_KEY_B64
            or not settings.LICENSE_MACHINE_FINGERPRINT
        ):
            return {
                **base,
                "state": "misconfigured",
                "reason": "License service is not configured",
            }

        token = state.get("lease_token")
        if not token:
            return base
        try:
            payload = self._verify_token(token)
        except LicenseError as exc:
            return {**base, "state": "invalid", "reason": str(exc)}

        if payload.get("installation_id") != installation_id:
            return {**base, "state": "invalid", "reason": "License installation mismatch"}
        if payload.get("fingerprint") != settings.LICENSE_MACHINE_FINGERPRINT:
            return {**base, "state": "invalid", "reason": "License machine mismatch"}

        now = utcnow()
        try:
            refresh_after = parse_dt(payload.get("refresh_after"))
            valid_until = parse_dt(payload.get("valid_until"))
            license_expires_at = parse_dt(payload.get("license_expires_at"))
        except (AttributeError, TypeError, ValueError):
            return {
                **base,
                "state": "invalid",
                "reason": "License lease timestamps are invalid",
            }
        if not valid_until:
            return {**base, "state": "invalid", "reason": "License lease has no expiry"}

        features = payload.get("features") or []
        if not isinstance(features, list) or not all(
            isinstance(feature, str) for feature in features
        ):
            return {
                **base,
                "state": "invalid",
                "reason": "License lease features are invalid",
            }

        common = {
            **base,
            "customer_name": payload.get("customer_name"),
            "plan": payload.get("plan"),
            "features": features,
            "license_expires_at": license_expires_at.isoformat() if license_expires_at else None,
            "refresh_after": refresh_after.isoformat() if refresh_after else None,
            "valid_until": valid_until.isoformat(),
            "needs_refresh": bool(refresh_after and now >= refresh_after),
        }

        blocked_reason = state.get("server_blocked_reason")
        if blocked_reason:
            return {
                **common,
                "active": False,
                "state": "blocked",
                "reason": blocked_reason,
                "needs_refresh": True,
            }

        if license_expires_at and now >= license_expires_at:
            return {**common, "state": "expired", "reason": "License subscription has expired"}
        if now >= valid_until:
            return {
                **common,
                "state": "lease_expired",
                "reason": "License lease needs online refresh",
            }
        return {**common, "active": True, "state": "active"}

    def _refresh_attempt_due(self, state: dict) -> bool:
        raw = state.get("last_refresh_attempt_at")
        try:
            last = parse_dt(raw)
        except (AttributeError, TypeError, ValueError):
            return True
        if not last:
            return True
        return utcnow() - last >= timedelta(minutes=settings.LICENSE_REFRESH_RETRY_MINUTES)

    def _validate_server_lease(self, state: dict) -> dict:
        status = self._status_from_state(state)
        if not status.get("active"):
            raise LicenseUnavailableError(
                status.get("reason") or "License server returned an invalid lease"
            )
        return status

    async def _server_post(self, path: str, payload: dict) -> dict:
        url = settings.LICENSE_SERVER_URL.rstrip("/") + path
        timeout = httpx.Timeout(settings.LICENSE_HTTP_TIMEOUT_SECONDS)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.RequestError as exc:
            raise LicenseUnavailableError("License server is temporarily unavailable") from exc

        if response.status_code >= 400:
            detail = None
            try:
                body = response.json()
                detail = body.get("detail") if isinstance(body, dict) else None
            except Exception:
                pass
            message = detail or f"License server returned HTTP {response.status_code}"
            if 400 <= response.status_code < 500:
                raise LicenseRejectedError(message, response.status_code)
            raise LicenseUnavailableError(message)

        try:
            data = response.json()
        except Exception as exc:
            raise LicenseUnavailableError("License server returned invalid JSON") from exc
        if not isinstance(data, dict) or not data.get("lease_token"):
            raise LicenseUnavailableError("License server returned an invalid response")
        return data

    async def activate(self, license_key: str) -> dict:
        async with self._lock:
            data = await self._server_post(
                "/v1/activate",
                {
                    "license_key": license_key.strip(),
                    "installation_id": self.installation_id(),
                    "fingerprint": settings.LICENSE_MACHINE_FINGERPRINT,
                    "app_version": "2.0.0",
                },
            )
            now = utcnow().isoformat()
            state = {
                "lease_token": data["lease_token"],
                "activated_at": now,
                "last_refresh_attempt_at": now,
                "last_refresh_success_at": now,
            }
            status = self._validate_server_lease(state)
            self._save_state(state)
            return status

    async def refresh(self, state: dict | None = None) -> dict:
        async with self._lock:
            state = dict(state or self._load_state())
            token = state.get("lease_token")
            if not token:
                raise LicenseError("No license lease is installed")
            state["last_refresh_attempt_at"] = utcnow().isoformat()
            self._save_state(state)
            try:
                data = await self._server_post(
                    "/v1/refresh",
                    {
                        "lease_token": token,
                        "installation_id": self.installation_id(),
                        "fingerprint": settings.LICENSE_MACHINE_FINGERPRINT,
                    },
                )
            except LicenseRejectedError as exc:
                state["server_blocked_reason"] = str(exc)
                state["server_blocked_status_code"] = exc.status_code
                state["server_blocked_at"] = utcnow().isoformat()
                self._save_state(state)
                raise

            candidate = dict(state)
            candidate["lease_token"] = data["lease_token"]
            candidate["last_refresh_success_at"] = utcnow().isoformat()
            candidate.pop("server_blocked_reason", None)
            candidate.pop("server_blocked_status_code", None)
            candidate.pop("server_blocked_at", None)
            status = self._validate_server_lease(candidate)
            self._save_state(candidate)
            return status

    async def get_status(self, *, allow_refresh: bool = True) -> dict:
        state = self._load_state()
        status = self._status_from_state(state)
        if not settings.LICENSE_ENFORCEMENT or not allow_refresh:
            return status

        should_refresh = (
            status.get("needs_refresh")
            or status.get("state") == "lease_expired"
            or bool(state.get("server_blocked_reason"))
        )
        if should_refresh and state.get("lease_token") and self._refresh_attempt_due(state):
            try:
                return await self.refresh(state)
            except LicenseRejectedError as exc:
                logger.warning("License server rejected refresh: %s", exc)
                return self._status_from_state(self._load_state())
            except LicenseUnavailableError as exc:
                logger.warning("License refresh unavailable: %s", exc)
                status = self._status_from_state(self._load_state())
                if status.get("active"):
                    status["reason"] = "Offline grace period"
                return status
            except LicenseError as exc:
                logger.warning("License refresh failed: %s", exc)
                return self._status_from_state(self._load_state())
        return status

    async def get_booking_sync_credential(self) -> str:
        """Return the current signed lease for authenticated booking sync."""
        if not settings.LICENSE_ENFORCEMENT:
            raise LicenseError("Booking sync credential is only available for licensed clients")

        status = await self.get_status(allow_refresh=True)

        if not status.get("active"):
            raise LicenseRejectedError(
                status.get("reason") or "License is not active",
                403,
            )

        features = {
            str(feature).strip().lower()
            for feature in (status.get("features") or [])
            if str(feature).strip()
        }

        if "booking" not in features:
            raise LicenseRejectedError(
                "Booking feature is not enabled for this license",
                403,
            )

        state = self._load_state()
        token = state.get("lease_token")

        if not token:
            raise LicenseError("No license lease is installed")

        payload = self._verify_token(token)

        if payload.get("installation_id") != self.installation_id():
            raise LicenseError("License installation mismatch")

        if payload.get("fingerprint") != settings.LICENSE_MACHINE_FINGERPRINT:
            raise LicenseError("License machine mismatch")

        return token

    async def get_ai_gateway_credential(self) -> str:
        """Return the current signed lease for internal AI gateway auth only."""
        if not settings.LICENSE_ENFORCEMENT:
            raise LicenseError("AI gateway credential is only available for licensed clients")

        status = await self.get_status(allow_refresh=True)

        if not status.get("active"):
            raise LicenseRejectedError(
                status.get("reason") or "License is not active",
                403,
            )

        features = {
            str(feature).strip().lower()
            for feature in (status.get("features") or [])
            if str(feature).strip()
        }

        if "ai" not in features:
            raise LicenseRejectedError(
                "AI feature is not enabled for this license",
                403,
            )

        state = self._load_state()
        token = state.get("lease_token")

        if not token:
            raise LicenseError("No license lease is installed")

        payload = self._verify_token(token)

        if payload.get("installation_id") != self.installation_id():
            raise LicenseError("License installation mismatch")

        if payload.get("fingerprint") != settings.LICENSE_MACHINE_FINGERPRINT:
            raise LicenseError("License machine mismatch")

        return token


license_manager = LicenseManager()
