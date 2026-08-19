from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.schemas import ApiResponse

from .service import (
    LicenseError,
    LicenseRejectedError,
    LicenseUnavailableError,
    license_manager,
)

router = APIRouter(prefix="/license", tags=["license"])


class LicenseStatus(BaseModel):
    enforced: bool
    installation_id: str
    active: bool
    state: str
    reason: str | None = None
    customer_name: str | None = None
    plan: str | None = None
    features: list[str] = Field(default_factory=list)
    license_expires_at: str | None = None
    refresh_after: str | None = None
    valid_until: str | None = None
    needs_refresh: bool = False


class ActivateLicense(BaseModel):
    license_key: str = Field(min_length=8, max_length=100)


@router.get("/status", response_model=ApiResponse[LicenseStatus])
async def license_status() -> ApiResponse[LicenseStatus]:
    data = await license_manager.get_status(allow_refresh=True)
    return ApiResponse(data=LicenseStatus(**data))


@router.post("/activate", response_model=ApiResponse[LicenseStatus])
async def activate_license(data: ActivateLicense) -> ApiResponse[LicenseStatus]:
    try:
        result = await license_manager.activate(data.license_key)
    except LicenseRejectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (LicenseUnavailableError, LicenseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return ApiResponse(data=LicenseStatus(**result))


@router.post("/refresh", response_model=ApiResponse[LicenseStatus])
async def refresh_license() -> ApiResponse[LicenseStatus]:
    try:
        result = await license_manager.refresh()
    except LicenseRejectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc
    except (LicenseUnavailableError, LicenseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return ApiResponse(data=LicenseStatus(**result))
