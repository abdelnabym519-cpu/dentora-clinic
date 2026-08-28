"""Tenant-safe Evolution provider configuration and webhook idempotency."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email.encryption import decrypt_password, encrypt_password
from app.modules.notifications.models import ClinicChannelSettings

from . import client
from .models import WhatsappEvolutionSettings, WhatsappEvolutionWebhookReceipt

ADAPTER_NAME = "whatsapp_evolution"
CHANNEL = "whatsapp"


class EvolutionService:
    @staticmethod
    async def get_settings(
        db: AsyncSession, clinic_id: UUID
    ) -> WhatsappEvolutionSettings | None:
        return (
            await db.execute(
                select(WhatsappEvolutionSettings).where(
                    WhatsappEvolutionSettings.clinic_id == clinic_id
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_settings_by_webhook_id(
        db: AsyncSession, settings_id: UUID
    ) -> WhatsappEvolutionSettings | None:
        return (
            await db.execute(
                select(WhatsappEvolutionSettings).where(
                    WhatsappEvolutionSettings.id == settings_id,
                    WhatsappEvolutionSettings.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _channel_row(
        db: AsyncSession, clinic_id: UUID
    ) -> ClinicChannelSettings | None:
        return (
            await db.execute(
                select(ClinicChannelSettings).where(
                    ClinicChannelSettings.clinic_id == clinic_id,
                    ClinicChannelSettings.channel == CHANNEL,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _sync_channel_selector(
        db: AsyncSession, settings: WhatsappEvolutionSettings
    ) -> None:
        row = await EvolutionService._channel_row(db, settings.clinic_id)
        if row is None:
            if not settings.is_active:
                return
            row = ClinicChannelSettings(
                clinic_id=settings.clinic_id,
                channel=CHANNEL,
                adapter_name=ADAPTER_NAME,
                is_enabled=True,
                is_verified=settings.is_verified,
            )
            db.add(row)
        elif settings.is_active:
            # Explicitly enabling Evolution selects it for this clinic. This is
            # the seam that lets Kapso and Evolution coexist without a global
            # last-registered-wins decision.
            row.adapter_name = ADAPTER_NAME
            row.is_enabled = True
            row.is_verified = settings.is_verified
        elif row.adapter_name == ADAPTER_NAME:
            # Disabling this provider relinquishes its selector instead of
            # leaving a disabled row that would block a previously configured
            # legacy provider such as Kapso from being discovered.
            await db.delete(row)
            return

        if row.adapter_name == ADAPTER_NAME:
            row.config = {
                "base_url": settings.base_url,
                "instance_name": settings.instance_name,
            }

    @staticmethod
    async def upsert_settings(
        db: AsyncSession, clinic_id: UUID, data: dict
    ) -> WhatsappEvolutionSettings:
        base_url = client.normalize_base_url(data["base_url"])
        instance_name = str(data["instance_name"]).strip()
        if not instance_name:
            raise ValueError("Evolution instance name is required")

        settings = await EvolutionService.get_settings(db, clinic_id)
        creating = settings is None
        api_key = data.get("api_key")
        webhook_token = data.get("webhook_token")

        if creating and not api_key:
            raise ValueError("Evolution API key is required for initial configuration")

        if settings is None:
            settings = WhatsappEvolutionSettings(
                clinic_id=clinic_id,
                base_url=base_url,
                instance_name=instance_name,
                api_key_encrypted=encrypt_password(str(api_key)),
                webhook_token_encrypted=encrypt_password(
                    str(webhook_token or secrets.token_urlsafe(32))
                ),
                is_active=bool(data.get("is_active", True)),
                is_verified=False,
            )
            db.add(settings)
        else:
            connection_changed = (
                settings.base_url != base_url
                or settings.instance_name != instance_name
                or bool(api_key)
            )
            settings.base_url = base_url
            settings.instance_name = instance_name
            settings.is_active = bool(data.get("is_active", settings.is_active))
            if api_key:
                settings.api_key_encrypted = encrypt_password(str(api_key))
            if webhook_token:
                settings.webhook_token_encrypted = encrypt_password(str(webhook_token))
            if connection_changed:
                settings.is_verified = False
                settings.connection_state = None
                settings.last_verified_at = None

        await db.flush()
        await EvolutionService._sync_channel_selector(db, settings)
        await db.commit()
        await db.refresh(settings)
        return settings

    @staticmethod
    async def test_connection(
        db: AsyncSession, clinic_id: UUID
    ) -> tuple[bool, str | None]:
        settings = await EvolutionService.get_settings(db, clinic_id)
        if settings is None or not settings.api_key_encrypted:
            raise ValueError("Evolution API is not configured")
        api_key = decrypt_password(settings.api_key_encrypted)
        try:
            response = await client.get_connection_state(
                settings.base_url, api_key, settings.instance_name
            )
        except client.EvolutionApiError:
            settings.is_verified = False
            settings.connection_state = "error"
            await EvolutionService._sync_channel_selector(db, settings)
            await db.commit()
            raise

        state = client.connection_state(response)
        connected = state == "open"
        settings.connection_state = state
        settings.is_verified = connected
        settings.last_verified_at = datetime.now(UTC)
        await EvolutionService._sync_channel_selector(db, settings)
        await db.commit()
        return connected, state

    @staticmethod
    async def configure_webhook(
        db: AsyncSession, clinic_id: UUID, dentora_public_base_url: str
    ) -> str:
        settings = await EvolutionService.get_settings(db, clinic_id)
        if settings is None:
            raise ValueError("Evolution API is not configured")
        public_base = client.normalize_base_url(dentora_public_base_url)
        webhook_url = (
            f"{public_base}/api/v1/whatsapp_evolution/webhook/"
            f"{quote(str(settings.id), safe='')}"
        )
        api_key = decrypt_password(settings.api_key_encrypted)
        token = decrypt_password(settings.webhook_token_encrypted)
        await client.set_webhook(
            settings.base_url,
            api_key,
            settings.instance_name,
            webhook_url=webhook_url,
            webhook_token=token,
        )
        settings.webhook_configured_at = datetime.now(UTC)
        await db.commit()
        return webhook_url

    @staticmethod
    def verify_webhook_token(settings: WhatsappEvolutionSettings, candidate: str | None) -> bool:
        if not candidate:
            return False
        expected = decrypt_password(settings.webhook_token_encrypted)
        return hmac.compare_digest(expected, candidate)

    @staticmethod
    async def claim_webhook(
        db: AsyncSession,
        settings: WhatsappEvolutionSettings,
        raw_body: bytes,
        event_type: str,
        provider_message_id: str | None = None,
    ) -> bool:
        """Atomically claim an exact payload; False means provider replay/duplicate."""
        digest = hashlib.sha256(raw_body).hexdigest()
        statement = (
            insert(WhatsappEvolutionWebhookReceipt)
            .values(
                clinic_id=settings.clinic_id,
                event_hash=digest,
                event_type=event_type[:64],
                provider_message_id=provider_message_id,
            )
            .on_conflict_do_nothing(
                constraint="uq_whatsapp_evolution_webhook_hash"
            )
            .returning(WhatsappEvolutionWebhookReceipt.id)
        )
        return (await db.execute(statement)).scalar_one_or_none() is not None

    @staticmethod
    async def update_connection_state(
        db: AsyncSession, settings: WhatsappEvolutionSettings, state: str | None
    ) -> None:
        if not state:
            return
        settings.connection_state = state[:32]
        settings.is_verified = state == "open"
        if settings.is_verified:
            settings.last_verified_at = datetime.now(UTC)
        await EvolutionService._sync_channel_selector(db, settings)
