"""HTTP surface for the optional Evolution API WhatsApp provider.

Administrative routes use Dentora RBAC. The provider webhook is public but is
bound to one opaque settings UUID, authenticated with a per-clinic secret
header, instance-validated, rate-limited, and idempotent on exact payload bytes.
"""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.auth.router import limiter
from app.core.schemas import ApiResponse
from app.database import get_db
from app.modules.notifications.gateway import NotificationGateway

from . import client, webhooks
from .schemas import (
    EvolutionConnectionResponse,
    EvolutionSettingsResponse,
    EvolutionSettingsUpdate,
    EvolutionWebhookConfigureRequest,
)
from .service import EvolutionService

router = APIRouter()


def _settings_response(settings) -> EvolutionSettingsResponse:
    return EvolutionSettingsResponse(
        base_url=settings.base_url if settings else None,
        instance_name=settings.instance_name if settings else None,
        has_api_key=bool(settings and settings.api_key_encrypted),
        has_webhook_token=bool(settings and settings.webhook_token_encrypted),
        is_active=bool(settings and settings.is_active),
        is_verified=bool(settings and settings.is_verified),
        connection_state=settings.connection_state if settings else None,
        last_verified_at=settings.last_verified_at if settings else None,
        webhook_configured_at=settings.webhook_configured_at if settings else None,
    )


@router.get("/settings", response_model=ApiResponse[EvolutionSettingsResponse])
async def get_settings(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("whatsapp_evolution.settings.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[EvolutionSettingsResponse]:
    settings = await EvolutionService.get_settings(db, ctx.clinic_id)
    return ApiResponse(data=_settings_response(settings))


@router.put("/settings", response_model=ApiResponse[EvolutionSettingsResponse])
async def update_settings(
    data: EvolutionSettingsUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("whatsapp_evolution.settings.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[EvolutionSettingsResponse]:
    try:
        settings = await EvolutionService.upsert_settings(
            db, ctx.clinic_id, data.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=_settings_response(settings))


@router.post("/test", response_model=ApiResponse[EvolutionConnectionResponse])
async def test_connection(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("whatsapp_evolution.settings.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[EvolutionConnectionResponse]:
    try:
        connected, state_value = await EvolutionService.test_connection(db, ctx.clinic_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except client.EvolutionApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Evolution connection check failed: {exc.code}",
        ) from exc
    return ApiResponse(data=EvolutionConnectionResponse(connected=connected, state=state_value))


@router.post("/webhook/configure", response_model=ApiResponse[dict])
async def configure_webhook(
    data: EvolutionWebhookConfigureRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("whatsapp_evolution.settings.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict]:
    try:
        webhook_url = await EvolutionService.configure_webhook(
            db, ctx.clinic_id, str(data.dentora_public_base_url)
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except client.EvolutionApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Evolution webhook configuration failed: {exc.code}",
        ) from exc
    return ApiResponse(data={"configured": True, "webhook_url": webhook_url})


@router.post("/webhook/{settings_id}")
@limiter.limit("120/minute")
async def webhook(
    settings_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid payload")

    settings = await EvolutionService.get_settings_by_webhook_id(db, settings_id)
    if settings is None:
        # Accept-and-ignore unknown/disabled bindings: avoids turning the route
        # into an instance enumeration oracle and avoids provider retry storms.
        return {"ok": True}

    token = request.headers.get("X-Dentora-Webhook-Token")
    if not EvolutionService.verify_webhook_token(settings, token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook token")

    payload_instance = webhooks.payload_instance(payload)
    if payload_instance and payload_instance != settings.instance_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="instance mismatch")

    event_name = webhooks.normalize_event_name(payload.get("event"))
    if not event_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing event")

    first_provider_id: str | None = None
    if event_name == "messages.update":
        updates = webhooks.delivery_updates(payload)
        first_provider_id = updates[0].message_id if updates else None
    elif event_name == "messages.upsert":
        inbound = webhooks.inbound_texts(payload)
        first_provider_id = inbound[0].message_id if inbound else None

    claimed = await EvolutionService.claim_webhook(
        db,
        settings,
        raw,
        event_name,
        provider_message_id=first_provider_id,
    )
    if not claimed:
        await db.rollback()
        return {"ok": True, "duplicate": True}

    if event_name == "messages.update":
        for update in webhooks.delivery_updates(payload):
            await NotificationGateway.record_delivery_status(
                db,
                settings.clinic_id,
                update.message_id,
                update.status,
            )
    elif event_name == "messages.upsert":
        for inbound in webhooks.inbound_texts(payload):
            patient = await NotificationGateway.resolve_patient_by_phone(
                db, settings.clinic_id, inbound.phone
            )
            await NotificationGateway.record_inbound_reply(
                db,
                settings.clinic_id,
                channel="whatsapp",
                from_address=inbound.phone,
                body=inbound.body,
                patient_id=patient.id if patient else None,
                provider_message_id=inbound.message_id,
            )
    elif event_name == "connection.update":
        await EvolutionService.update_connection_state(
            db, settings, webhooks.connection_update_state(payload)
        )

    # Gateway helpers commit their own state. This final commit covers receipt
    # claims for ignored/unknown events and connection-only updates.
    await db.commit()
    return {"ok": True}
