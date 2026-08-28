"""Evolution API WhatsApp provider persistence.

Provider credentials are encrypted at rest. Generic delivery/outbox state remains
owned by the notifications module; this module stores only per-clinic Evolution
connection settings and replay/idempotency receipts for public webhooks.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic


class WhatsappEvolutionSettings(Base, TimestampMixin):
    """One tenant-safe Evolution API instance binding per clinic."""

    __tablename__ = "whatsapp_evolution_settings"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), unique=True, index=True)

    base_url: Mapped[str] = mapped_column(String(500))
    instance_name: Mapped[str] = mapped_column(String(120), index=True)
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    webhook_token_encrypted: Mapped[str] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    connection_state: Mapped[str | None] = mapped_column(String(32), default=None)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    webhook_configured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])

    __table_args__ = (
        UniqueConstraint("base_url", "instance_name", name="uq_whatsapp_evolution_instance"),
        Index("idx_whatsapp_evolution_settings_clinic", "clinic_id"),
        Index("idx_whatsapp_evolution_settings_instance", "instance_name"),
    )


class WhatsappEvolutionWebhookReceipt(Base, TimestampMixin):
    """Deduplicates exact Evolution webhook deliveries per clinic.

    The hash contains no PHI and lets repeated provider retries become safe
    no-ops while the actual message/delivery state stays in notifications.
    """

    __tablename__ = "whatsapp_evolution_webhook_receipts"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    event_hash: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64))
    provider_message_id: Mapped[str | None] = mapped_column(String(255), default=None)

    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])

    __table_args__ = (
        UniqueConstraint("clinic_id", "event_hash", name="uq_whatsapp_evolution_webhook_hash"),
        Index("idx_whatsapp_evolution_webhook_clinic", "clinic_id"),
    )
