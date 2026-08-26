"""Add tenant-safe pgvector retrieval foundation.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-26

The vector tables are rebuildable derived indexes. Authoritative clinical data
remains in its owning PostgreSQL tables. The pgvector extension is intentionally
left installed on downgrade: removing a shared database capability can destroy
objects owned by later/parallel application revisions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VECTOR_DIMENSIONS = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "retrieval_embeddings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("chunk_key", sa.String(length=128), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding_provider", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_version", sa.String(length=64), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("distance_metric", sa.String(length=16), nullable=False),
        sa.Column("embedding", VECTOR(VECTOR_DIMENSIONS), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'stale', 'failed', 'deleted')",
            name="ck_retrieval_embeddings_status",
        ),
        sa.CheckConstraint(
            f"embedding_dimensions = {VECTOR_DIMENSIONS}",
            name="ck_retrieval_embeddings_dimensions",
        ),
        sa.CheckConstraint("distance_metric = 'cosine'", name="ck_retrieval_embeddings_metric"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_retrieval_embeddings_attempt_count"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["patient_id", "clinic_id"],
            ["patients.id", "patients.clinic_id"],
            name="fk_retrieval_embeddings_patient_clinic",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "clinic_id",
            "source_type",
            "source_id",
            "chunk_key",
            "embedding_model",
            "embedding_version",
            name="uq_retrieval_embeddings_source_space",
        ),
    )
    op.create_index(
        "ix_retrieval_embeddings_tenant_ready",
        "retrieval_embeddings",
        ["clinic_id", "status", "embedding_model", "embedding_version", "patient_id", "source_type"],
    )
    op.create_index(
        "ix_retrieval_embeddings_hnsw_cosine",
        "retrieval_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_where=sa.text("status = 'ready' AND embedding IS NOT NULL"),
    )

    op.create_table(
        "retrieval_query_audit",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("query_digest", sa.String(length=64), nullable=False),
        sa.Column("embedding_provider", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_version", sa.String(length=64), nullable=False),
        sa.Column("source_types", sa.JSON(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("result_count >= 0", name="ck_retrieval_query_audit_result_count"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["patient_id", "clinic_id"],
            ["patients.id", "patients.clinic_id"],
            name="fk_retrieval_query_audit_patient_clinic",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_retrieval_query_audit_clinic_created",
        "retrieval_query_audit",
        ["clinic_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_query_audit_clinic_created", table_name="retrieval_query_audit")
    op.drop_table("retrieval_query_audit")
    op.drop_index("ix_retrieval_embeddings_hnsw_cosine", table_name="retrieval_embeddings")
    op.drop_index("ix_retrieval_embeddings_tenant_ready", table_name="retrieval_embeddings")
    op.drop_table("retrieval_embeddings")
