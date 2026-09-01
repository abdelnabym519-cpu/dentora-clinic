"""EvolutionApiAdapter — delivers Dentora's WhatsApp channel via Evolution API.

The notifications module owns consent, tenant routing, outbox/idempotency and
retry policy. This adapter is provider-only infrastructure: it loads the
clinic's encrypted Evolution credentials, performs one wire call, and maps the
provider response into the stable ChannelAdapter result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.core.email.encryption import decrypt_password
from app.modules.notifications.channels import (
    AdapterResult,
    Channel,
    OutboundMessage,
    SendStatus,
)

from . import client
from .models import WhatsappEvolutionSettings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _active_settings(db: AsyncSession, clinic_id: UUID) -> WhatsappEvolutionSettings | None:
    return (
        await db.execute(
            select(WhatsappEvolutionSettings).where(
                WhatsappEvolutionSettings.clinic_id == clinic_id,
                WhatsappEvolutionSettings.is_active.is_(True),
                WhatsappEvolutionSettings.is_verified.is_(True),
            )
        )
    ).scalar_one_or_none()


class EvolutionApiAdapter:
    """WhatsApp delivery via a tenant-selected, self-hosted Evolution instance."""

    channel = Channel.WHATSAPP
    adapter_name = "whatsapp_evolution"
    # Unlike Meta Cloud/Kapso, Evolution's Baileys transport has no approved
    # HSM-template contract. The gateway still requires patient WhatsApp opt-in.
    requires_proactive_template = False

    async def supports(self, db: AsyncSession, clinic_id: UUID) -> bool:
        return await _active_settings(db, clinic_id) is not None

    async def send(self, db: AsyncSession, msg: OutboundMessage) -> AdapterResult:
        settings = await _active_settings(db, msg.clinic_id)
        if settings is None:
            return AdapterResult(
                status=SendStatus.FAILED,
                provider=self.adapter_name,
                error_message="whatsapp_evolution is not active and verified for this clinic",
                retryable=False,
            )

        api_key = decrypt_password(settings.api_key_encrypted)
        if not api_key:
            return AdapterResult(
                status=SendStatus.FAILED,
                provider=self.adapter_name,
                error_message="Evolution API credential is unavailable",
                retryable=False,
            )

        body = msg.body_text or ""
        if not body.strip():
            return AdapterResult(
                status=SendStatus.FAILED,
                provider=self.adapter_name,
                error_message="WhatsApp message body is empty",
                retryable=False,
            )

        try:
            data = await client.send_text(
                settings.base_url,
                api_key,
                settings.instance_name,
                msg.to_address,
                body,
            )
        except ValueError as exc:
            return AdapterResult(
                status=SendStatus.FAILED,
                provider=self.adapter_name,
                error_message=str(exc)[:500],
                retryable=False,
            )
        except client.EvolutionApiError as exc:
            return AdapterResult(
                status=SendStatus.FAILED,
                provider=self.adapter_name,
                error_message=str(exc)[:500],
                retryable=exc.retryable,
            )

        return AdapterResult(
            status=SendStatus.SENT,
            provider=self.adapter_name,
            provider_message_id=client.provider_message_id(data),
        )
