"""PostgreSQL/pgvector persistence for the derived retrieval index."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import VECTOR
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

from .constants import DEFAULT_DISTANCE_METRIC, VECTOR_DIMENSIONS


class RetrievalEmbedding(Base, TimestampMixin):
    """Rebuildable embedding record; never the clinical source of truth."""

    __tablename__ = "retrieval_embeddings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False
    )
    patient_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    chunk_key: Mapped[str] = mapped_column(String(128), nullable=False, default="full")
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=VECTOR_DIMENSIONS
    )
    distance_metric: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DEFAULT_DISTANCE_METRIC
    )
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(VECTOR_DIMENSIONS), nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "clinic_id"],
            ["patients.id", "patients.clinic_id"],
            name="fk_retrieval_embeddings_patient_clinic",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "clinic_id",
            "source_type",
            "source_id",
            "chunk_key",
            "embedding_model",
            "embedding_version",
            name="uq_retrieval_embeddings_source_space",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'stale', 'failed', 'deleted')",
            name="ck_retrieval_embeddings_status",
        ),
        CheckConstraint(
            f"embedding_dimensions = {VECTOR_DIMENSIONS}",
            name="ck_retrieval_embeddings_dimensions",
        ),
        CheckConstraint(
            "distance_metric = 'cosine'",
            name="ck_retrieval_embeddings_metric",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_retrieval_embeddings_attempt_count"),
        Index(
            "ix_retrieval_embeddings_tenant_ready",
            "clinic_id",
            "status",
            "embedding_model",
            "embedding_version",
            "patient_id",
            "source_type",
        ),
        Index(
            "ix_retrieval_embeddings_hnsw_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("status = 'ready' AND embedding IS NOT NULL"),
        ),
    )


class RetrievalQueryAudit(Base):
    """Privacy-minimized audit row for retrieval activity."""

    __tablename__ = "retrieval_query_audit"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    patient_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    query_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_types: Mapped[list[str] | None] = mapped_column(JSONB)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "clinic_id"],
            ["patients.id", "patients.clinic_id"],
            name="fk_retrieval_query_audit_patient_clinic",
            ondelete="CASCADE",
        ),
        CheckConstraint("result_count >= 0", name="ck_retrieval_query_audit_result_count"),
        Index("ix_retrieval_query_audit_clinic_created", "clinic_id", "created_at"),
    )
