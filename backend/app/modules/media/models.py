"""Media module database models."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User
    from app.modules.patients.models import Patient


class Document(Base, TimestampMixin):
    """Document entity for patient files."""

    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)

    document_type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    original_filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)

    media_kind: Mapped[str] = mapped_column(
        String(20), default="document", server_default="document"
    )
    media_category: Mapped[str | None] = mapped_column(String(20))
    media_subtype: Mapped[str | None] = mapped_column(String(40))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    paired_document_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
    )

    tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    extra_data: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="active")

    clinic: Mapped["Clinic"] = relationship()
    patient: Mapped["Patient"] = relationship()
    uploader: Mapped["User"] = relationship()
    paired_document: Mapped["Document | None"] = relationship(
        "Document",
        remote_side="Document.id",
        foreign_keys=[paired_document_id],
        post_update=True,
    )

    __table_args__ = (
        UniqueConstraint("id", "clinic_id", name="uq_documents_id_clinic"),
        ForeignKeyConstraint(
            ["patient_id", "clinic_id"],
            ["patients.id", "patients.clinic_id"],
            name="fk_documents_patient_clinic",
        ),
        Index("idx_documents_clinic_patient", "clinic_id", "patient_id"),
        Index("idx_documents_type", "clinic_id", "document_type"),
        Index(
            "idx_documents_clinic_patient_kind_captured",
            "clinic_id",
            "patient_id",
            "media_kind",
            "captured_at",
        ),
        CheckConstraint(
            "paired_document_id IS NULL OR paired_document_id <> id",
            name="ck_documents_pair_not_self",
        ),
    )


class MediaAttachment(Base, TimestampMixin):
    """Polymorphic link between a ``Document`` and an arbitrary owner."""

    __tablename__ = "media_attachments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    owner_type: Mapped[str] = mapped_column(String(40))
    owner_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped["Document"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "owner_type",
            "owner_id",
            name="uq_media_attachments_doc_owner",
        ),
        ForeignKeyConstraint(
            ["document_id", "clinic_id"],
            ["documents.id", "documents.clinic_id"],
            ondelete="CASCADE",
            name="fk_media_attachments_document_clinic",
        ),
        Index(
            "idx_media_attachments_owner",
            "clinic_id",
            "owner_type",
            "owner_id",
        ),
    )
