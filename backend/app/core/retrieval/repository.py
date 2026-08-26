"""SQLAlchemy adapter for tenant-safe pgvector retrieval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .constants import DEFAULT_LEASE_SECONDS, MAX_RETRIEVAL_LIMIT, VECTOR_DIMENSIONS
from .contracts import EmbeddingSource, RetrievalHit, RetrievalPurpose, RetrievalWorkItem
from .models import RetrievalEmbedding, RetrievalQueryAudit


class SqlAlchemyRetrievalRepository:
    """Persistence adapter. Every read path requires an explicit clinic id."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_source(
        self,
        source: EmbeddingSource,
        *,
        source_digest: str,
        provider: str,
        model: str,
        version: str,
    ) -> tuple[RetrievalEmbedding, bool]:
        stmt = (
            select(RetrievalEmbedding)
            .where(
                RetrievalEmbedding.clinic_id == source.clinic_id,
                RetrievalEmbedding.source_type == source.source_type,
                RetrievalEmbedding.source_id == source.source_id,
                RetrievalEmbedding.chunk_key == source.chunk_key,
                RetrievalEmbedding.embedding_model == model,
                RetrievalEmbedding.embedding_version == version,
            )
            .with_for_update()
        )
        existing = (await self._session.scalars(stmt)).one_or_none()
        if existing is None:
            row = RetrievalEmbedding(
                clinic_id=source.clinic_id,
                patient_id=source.patient_id,
                source_type=source.source_type,
                source_id=source.source_id,
                chunk_key=source.chunk_key,
                source_digest=source_digest,
                source_updated_at=source.source_updated_at,
                embedding_provider=provider,
                embedding_model=model,
                embedding_version=version,
                embedding_dimensions=VECTOR_DIMENSIONS,
                status="pending",
            )
            self._session.add(row)
            await self._session.flush()
            return row, True

        if (
            existing.source_digest == source_digest
            and existing.patient_id == source.patient_id
            and existing.embedding_provider == provider
        ):
            return existing, False

        existing.patient_id = source.patient_id
        existing.source_digest = source_digest
        existing.source_updated_at = source.source_updated_at
        existing.embedding_provider = provider
        existing.embedding = None
        existing.status = "pending"
        existing.last_error = None
        existing.next_attempt_at = None
        existing.lease_expires_at = None
        existing.embedded_at = None
        await self._session.flush()
        return existing, True

    async def mark_ready(self, row: RetrievalEmbedding, vector: list[float]) -> None:
        row.embedding = vector
        row.embedding_dimensions = len(vector)
        row.status = "ready"
        row.last_error = None
        row.next_attempt_at = None
        row.lease_expires_at = None
        row.embedded_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_failed(self, row: RetrievalEmbedding, error: str) -> None:
        row.status = "failed"
        row.last_error = error[:4000]
        row.lease_expires_at = None
        # Bounded linear backoff keeps retries predictable and auditable.
        delay_seconds = 60 * max(1, min(row.attempt_count or 1, 10))
        row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        await self._session.flush()

    async def mark_stale(self, row: RetrievalEmbedding) -> None:
        row.status = "stale"
        row.embedding = None
        row.lease_expires_at = None
        await self._session.flush()

    async def mark_deleted(self, row: RetrievalEmbedding) -> None:
        row.status = "deleted"
        row.embedding = None
        row.lease_expires_at = None
        await self._session.flush()

    async def claim_work(
        self,
        *,
        limit: int = 10,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> list[RetrievalWorkItem]:
        now = datetime.now(UTC)
        eligible = or_(
            RetrievalEmbedding.status == "pending",
            and_(
                RetrievalEmbedding.status == "failed",
                or_(
                    RetrievalEmbedding.next_attempt_at.is_(None),
                    RetrievalEmbedding.next_attempt_at <= now,
                ),
            ),
            and_(
                RetrievalEmbedding.status == "processing",
                RetrievalEmbedding.lease_expires_at.is_not(None),
                RetrievalEmbedding.lease_expires_at <= now,
            ),
        )
        stmt = (
            select(RetrievalEmbedding)
            .where(eligible)
            .order_by(RetrievalEmbedding.created_at, RetrievalEmbedding.id)
            .with_for_update(skip_locked=True)
            .limit(max(1, min(limit, 100)))
        )
        rows = list((await self._session.scalars(stmt)).all())
        lease_until = now + timedelta(seconds=max(30, lease_seconds))
        work: list[RetrievalWorkItem] = []
        for row in rows:
            row.status = "processing"
            row.attempt_count += 1
            row.last_attempt_at = now
            row.lease_expires_at = lease_until
            work.append(
                RetrievalWorkItem(
                    embedding_id=row.id,
                    clinic_id=row.clinic_id,
                    patient_id=row.patient_id,
                    source_type=row.source_type,
                    source_id=row.source_id,
                    chunk_key=row.chunk_key,
                    source_digest=row.source_digest,
                    embedding_model=row.embedding_model,
                    embedding_version=row.embedding_version,
                    attempt_count=row.attempt_count,
                )
            )
        await self._session.flush()
        return work

    async def get_claimed(self, item: RetrievalWorkItem) -> RetrievalEmbedding | None:
        stmt = select(RetrievalEmbedding).where(
            RetrievalEmbedding.id == item.embedding_id,
            RetrievalEmbedding.clinic_id == item.clinic_id,
            RetrievalEmbedding.status == "processing",
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def search(
        self,
        *,
        clinic_id: UUID,
        query_vector: list[float],
        model: str,
        version: str,
        limit: int,
        patient_id: UUID | None = None,
        source_types: tuple[str, ...] | None = None,
    ) -> list[RetrievalHit]:
        if len(query_vector) != VECTOR_DIMENSIONS:
            raise ValueError(f"query embedding must have {VECTOR_DIMENSIONS} dimensions")

        # pgvector >= 0.8 iterative scans improve filtered HNSW recall while
        # the hard SQL tenant predicate remains the security boundary.
        await self._session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        distance = RetrievalEmbedding.embedding.cosine_distance(query_vector)
        stmt = select(RetrievalEmbedding, distance.label("distance")).where(
            RetrievalEmbedding.clinic_id == clinic_id,
            RetrievalEmbedding.status == "ready",
            RetrievalEmbedding.embedding.is_not(None),
            RetrievalEmbedding.embedding_model == model,
            RetrievalEmbedding.embedding_version == version,
        )
        if patient_id is not None:
            stmt = stmt.where(RetrievalEmbedding.patient_id == patient_id)
        if source_types:
            stmt = stmt.where(RetrievalEmbedding.source_type.in_(source_types))
        stmt = stmt.order_by(distance).limit(max(1, min(limit, MAX_RETRIEVAL_LIMIT)))

        rows = (await self._session.execute(stmt)).all()
        return [
            RetrievalHit(
                embedding_id=row.id,
                clinic_id=row.clinic_id,
                patient_id=row.patient_id,
                source_type=row.source_type,
                source_id=row.source_id,
                chunk_key=row.chunk_key,
                source_digest=row.source_digest,
                embedding_model=row.embedding_model,
                embedding_version=row.embedding_version,
                distance=float(distance_value),
            )
            for row, distance_value in rows
        ]

    async def audit_query(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID | None,
        purpose: RetrievalPurpose,
        query_digest: str,
        provider: str,
        model: str,
        version: str,
        source_types: tuple[str, ...] | None,
        result_count: int,
    ) -> None:
        self._session.add(
            RetrievalQueryAudit(
                clinic_id=clinic_id,
                patient_id=patient_id,
                purpose=purpose.value,
                query_digest=query_digest,
                embedding_provider=provider,
                embedding_model=model,
                embedding_version=version,
                source_types=list(source_types) if source_types else None,
                result_count=result_count,
            )
        )
        await self._session.flush()
