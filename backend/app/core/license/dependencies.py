"""FastAPI dependencies for commercial license features."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, status

from app.config import settings

from .service import license_manager


def require_license_feature(
    feature: str,
) -> Callable[[], Coroutine[Any, Any, None]]:
    """Require a feature from the signed Dentora license lease."""

    wanted = feature.strip().lower()

    async def dependency() -> None:
        # Development/hosted deployments keep licensing disabled.
        if not settings.LICENSE_ENFORCEMENT:
            return

        license_status = await license_manager.get_status(allow_refresh=True)

        if not license_status.get("active"):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "license_inactive",
                    "message": "Dentora license is not active.",
                },
            )

        features = {
            str(item).strip().lower()
            for item in (license_status.get("features") or [])
            if str(item).strip()
        }

        if wanted not in features:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "feature_not_enabled",
                    "feature": wanted,
                    "message": f"The {wanted} feature is not enabled for this license.",
                },
            )

    return dependency
