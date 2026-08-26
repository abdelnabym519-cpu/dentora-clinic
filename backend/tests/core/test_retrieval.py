"""Database-backed tests for pgvector retrieval safety and lifecycle."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.retrieval import (
    VECTOR_DIMENSIONS,
    EmbeddingPrivacyError,
    EmbeddingSource,
    RetrievalService,
    SqlAlchemyRetrievalRepository,
)
from app.core.retrieval.models import RetrievalEmbedding, RetrievalQueryAudit
from app.modules.patients.models import Patient


def _vector(index: int) -> list[float]:
    values = [0.0] * VECTOR_DIMENSIONS
    values[index] = 1.0
    return values


class FakeProvider:
    name = "fake-local"
    is_external = False

    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors
        self.calls = 0

    async def embed(self, texts: list[str], *, model: str, dimensions: int) -> list[list[float]]:
        assert dimensions == VECTOR_DIMENSIONS
        self.calls += 1
        return self.vectors[: len(texts)]


class ExternalProvider(FakeProvider):
    name = "fake-external"
    is_external = True


@pytest.mark.asyncio
async def test_embedding_is_idempotent_and_reembeds_when_source_changes(
    db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    repository = SqlAlchemyRetrievalRepository(db_session)
    service = RetrievalService(repository)
    provider = FakeProvider([_vector(0)])
    source = EmbeddingSource(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        source_type="clinical_note",
        source_id=str(uuid4()),
        text="stable clinical source",
    )

    assert await service.embed_source(source, provider) is True
    assert await service.embed_source(source, provider) is False
    assert provider.calls == 1

    changed = EmbeddingSource(
        clinic_id=source.clinic_id,
        patient_id=source.patient_id,
        source_type=source.source_type,
        source_id=source.source_id,
        text="changed clinical source",
    )
    assert await service.embed_source(changed, provider) is True
    assert provider.calls == 2

    rows = list((await db_session.scalars(select(RetrievalEmbedding))).all())
    assert len(rows) == 1
    assert rows[0].status == "ready"
    assert rows[0].source_digest == service.digest_text(changed.text)


@pytest.mark.asyncio
async def test_external_embedding_fails_closed_without_privacy_permission(
    db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    provider = ExternalProvider([_vector(0)])
    service = RetrievalService(SqlAlchemyRetrievalRepository(db_session))
    source = EmbeddingSource(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        source_type="clinical_note",
        source_id=str(uuid4()),
        text="private note",
    )

    with pytest.raises(EmbeddingPrivacyError):
        await service.embed_source(source, provider)
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_vector_dimension_mismatch_is_rejected(
    db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    service = RetrievalService(SqlAlchemyRetrievalRepository(db_session))
    provider = FakeProvider([[0.0, 1.0]])
    source = EmbeddingSource(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        source_type="case_snapshot",
        source_id=str(uuid4()),
        text="case",
    )

    with pytest.raises(ValueError, match="1536"):
        await service.embed_source(source, provider)


@pytest.mark.asyncio
async def test_semantic_search_is_hard_scoped_to_clinic_and_audited(
    db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    other_clinic = Clinic(id=uuid4(), name="Other", tax_id="B99999999", address={}, settings={})
    db_session.add(other_clinic)
    await db_session.flush()
    other_patient = Patient(
        id=uuid4(),
        clinic_id=other_clinic.id,
        first_name="Other",
        last_name="Patient",
    )
    db_session.add(other_patient)
    await db_session.flush()

    repository = SqlAlchemyRetrievalRepository(db_session)
    service = RetrievalService(repository)
    provider = FakeProvider([_vector(0)])

    own_source = EmbeddingSource(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        source_type="case_snapshot",
        source_id="own-case",
        text="own",
    )
    other_source = EmbeddingSource(
        clinic_id=other_clinic.id,
        patient_id=other_patient.id,
        source_type="case_snapshot",
        source_id="other-case",
        text="other",
    )
    await service.embed_source(own_source, provider)
    await service.embed_source(other_source, provider)

    provider.calls = 0
    hits = await service.semantic_search(
        clinic_id=test_clinic.id,
        query_text="query",
        provider=provider,
    )
    assert [hit.source_id for hit in hits] == ["own-case"]
    assert all(hit.clinic_id == test_clinic.id for hit in hits)

    audits = list((await db_session.scalars(select(RetrievalQueryAudit))).all())
    assert len(audits) == 1
    assert audits[0].clinic_id == test_clinic.id
    assert audits[0].query_digest == service.digest_text("query")
    assert audits[0].result_count == 1


@pytest.mark.asyncio
async def test_database_rejects_cross_clinic_patient_vector_reference(
    db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    other_clinic = Clinic(id=uuid4(), name="Other", tax_id="B88888888", address={}, settings={})
    db_session.add(other_clinic)
    await db_session.flush()

    row = RetrievalEmbedding(
        clinic_id=other_clinic.id,
        patient_id=test_patient.id,
        source_type="clinical_note",
        source_id="cross-tenant",
        chunk_key="full",
        source_digest="a" * 64,
        embedding_provider="fake-local",
        embedding_model="text-embedding-3-small",
        embedding_version="v1",
        embedding_dimensions=VECTOR_DIMENSIONS,
        distance_metric="cosine",
        status="pending",
        attempt_count=0,
    )
    db_session.add(row)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_ready_filter_excludes_stale_and_failed_embeddings(
    db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    repository = SqlAlchemyRetrievalRepository(db_session)
    service = RetrievalService(repository)
    provider = FakeProvider([_vector(0)])

    ready = EmbeddingSource(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        source_type="clinical_note",
        source_id="ready",
        text="ready",
    )
    stale = EmbeddingSource(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        source_type="clinical_note",
        source_id="stale",
        text="stale",
    )
    await service.embed_source(ready, provider)
    await service.embed_source(stale, provider)
    stale_row = (
        await db_session.scalars(
            select(RetrievalEmbedding).where(RetrievalEmbedding.source_id == "stale")
        )
    ).one()
    await repository.mark_stale(stale_row)

    hits = await service.semantic_search(
        clinic_id=test_clinic.id,
        query_text="query",
        provider=provider,
    )
    assert [hit.source_id for hit in hits] == ["ready"]
