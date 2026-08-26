"""Application service for embedding lifecycle and retrieval."""

from __future__ import annotations

import hashlib
from uuid import UUID

from .constants import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_VERSION,
    SIMILAR_CASE_SOURCE_TYPES,
    SOURCE_CLINICAL_KNOWLEDGE,
    VECTOR_DIMENSIONS,
)
from .contracts import (
    EmbeddingProvider,
    EmbeddingSource,
    EmbeddingSourceLoader,
    RetrievalHit,
    RetrievalPurpose,
)
from .repository import SqlAlchemyRetrievalRepository


class EmbeddingPrivacyError(PermissionError):
    """Raised before plaintext can leave Dentora without explicit permission."""


class RetrievalService:
    """Coordinates derived embeddings without mutating clinical source rows."""

    def __init__(self, repository: SqlAlchemyRetrievalRepository) -> None:
        self._repository = repository

    async def embed_source(
        self,
        source: EmbeddingSource,
        provider: EmbeddingProvider,
        *,
        model: str = DEFAULT_EMBEDDING_MODEL,
        version: str = DEFAULT_EMBEDDING_VERSION,
    ) -> bool:
        self._validate_source(source)
        digest = self.digest_text(source.text)
        row, needs_embedding = await self._repository.register_source(
            source,
            source_digest=digest,
            provider=provider.name,
            model=model,
            version=version,
        )
        if not needs_embedding and row.status == "ready":
            return False

        try:
            self._enforce_privacy(source.external_embedding_allowed, provider)
            vectors = await provider.embed([source.text], model=model, dimensions=VECTOR_DIMENSIONS)
            vector = self._single_valid_vector(vectors)
            await self._repository.mark_ready(row, vector)
        except Exception as exc:
            await self._repository.mark_failed(row, str(exc))
            raise
        return True

    async def semantic_search(
        self,
        *,
        clinic_id: UUID,
        query_text: str,
        provider: EmbeddingProvider,
        model: str = DEFAULT_EMBEDDING_MODEL,
        version: str = DEFAULT_EMBEDDING_VERSION,
        limit: int = 10,
        patient_id: UUID | None = None,
        source_types: tuple[str, ...] | None = None,
        purpose: RetrievalPurpose = RetrievalPurpose.SEMANTIC_SEARCH,
        external_embedding_allowed: bool = False,
    ) -> list[RetrievalHit]:
        if not query_text.strip():
            raise ValueError("query text must not be empty")
        self._enforce_privacy(external_embedding_allowed, provider)
        vectors = await provider.embed([query_text], model=model, dimensions=VECTOR_DIMENSIONS)
        query_vector = self._single_valid_vector(vectors)
        hits = await self._repository.search(
            clinic_id=clinic_id,
            query_vector=query_vector,
            model=model,
            version=version,
            limit=limit,
            patient_id=patient_id,
            source_types=source_types,
        )
        await self._repository.audit_query(
            clinic_id=clinic_id,
            patient_id=patient_id,
            purpose=purpose,
            query_digest=self.digest_text(query_text),
            provider=provider.name,
            model=model,
            version=version,
            source_types=source_types,
            result_count=len(hits),
        )
        return hits

    async def similar_cases(
        self,
        *,
        clinic_id: UUID,
        query_text: str,
        provider: EmbeddingProvider,
        model: str = DEFAULT_EMBEDDING_MODEL,
        version: str = DEFAULT_EMBEDDING_VERSION,
        limit: int = 10,
        external_embedding_allowed: bool = False,
    ) -> list[RetrievalHit]:
        return await self.semantic_search(
            clinic_id=clinic_id,
            query_text=query_text,
            provider=provider,
            model=model,
            version=version,
            limit=limit,
            source_types=SIMILAR_CASE_SOURCE_TYPES,
            purpose=RetrievalPurpose.SIMILAR_CASES,
            external_embedding_allowed=external_embedding_allowed,
        )

    async def retrieve_for_rag(
        self,
        *,
        clinic_id: UUID,
        query_text: str,
        provider: EmbeddingProvider,
        source_types: tuple[str, ...],
        model: str = DEFAULT_EMBEDDING_MODEL,
        version: str = DEFAULT_EMBEDDING_VERSION,
        limit: int = 10,
        patient_id: UUID | None = None,
        external_embedding_allowed: bool = False,
    ) -> list[RetrievalHit]:
        if not source_types:
            raise ValueError("RAG retrieval requires explicit source types")
        return await self.semantic_search(
            clinic_id=clinic_id,
            query_text=query_text,
            provider=provider,
            model=model,
            version=version,
            limit=limit,
            patient_id=patient_id,
            source_types=source_types,
            purpose=RetrievalPurpose.RAG,
            external_embedding_allowed=external_embedding_allowed,
        )

    async def retrieve_clinical_knowledge(
        self,
        *,
        clinic_id: UUID,
        query_text: str,
        provider: EmbeddingProvider,
        model: str = DEFAULT_EMBEDDING_MODEL,
        version: str = DEFAULT_EMBEDDING_VERSION,
        limit: int = 10,
        external_embedding_allowed: bool = False,
    ) -> list[RetrievalHit]:
        return await self.semantic_search(
            clinic_id=clinic_id,
            query_text=query_text,
            provider=provider,
            model=model,
            version=version,
            limit=limit,
            source_types=(SOURCE_CLINICAL_KNOWLEDGE,),
            purpose=RetrievalPurpose.CLINICAL_KNOWLEDGE,
            external_embedding_allowed=external_embedding_allowed,
        )

    async def process_pending(
        self,
        loader: EmbeddingSourceLoader,
        provider: EmbeddingProvider,
        *,
        limit: int = 10,
    ) -> int:
        """Claim and process background work with retry-safe leases."""
        processed = 0
        for item in await self._repository.claim_work(limit=limit):
            row = await self._repository.get_claimed(item)
            if row is None:
                continue
            source = await loader.load(item)
            if source is None:
                await self._repository.mark_stale(row)
                continue
            if (
                source.clinic_id != item.clinic_id
                or source.patient_id != item.patient_id
                or source.source_type != item.source_type
                or source.source_id != item.source_id
                or source.chunk_key != item.chunk_key
            ):
                await self._repository.mark_failed(row, "source loader ownership/reference mismatch")
                continue
            try:
                self._validate_source(source)
                self._enforce_privacy(source.external_embedding_allowed, provider)
                current_digest = self.digest_text(source.text)
                if current_digest != item.source_digest:
                    row, _ = await self._repository.register_source(
                        source,
                        source_digest=current_digest,
                        provider=provider.name,
                        model=item.embedding_model,
                        version=item.embedding_version,
                    )
                vectors = await provider.embed(
                    [source.text], model=item.embedding_model, dimensions=VECTOR_DIMENSIONS
                )
                await self._repository.mark_ready(row, self._single_valid_vector(vectors))
                processed += 1
            except Exception as exc:
                await self._repository.mark_failed(row, str(exc))
        return processed

    @staticmethod
    def digest_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_source(source: EmbeddingSource) -> None:
        if not source.text.strip():
            raise ValueError("embedding source text must not be empty")
        if not source.source_type.strip() or not source.source_id.strip() or not source.chunk_key.strip():
            raise ValueError("embedding source reference fields must not be empty")

    @staticmethod
    def _enforce_privacy(allowed: bool, provider: EmbeddingProvider) -> None:
        if provider.is_external and not allowed:
            raise EmbeddingPrivacyError(
                "external embedding is denied until the source/query privacy contract explicitly allows it"
            )

    @staticmethod
    def _single_valid_vector(vectors: list[list[float]]) -> list[float]:
        if len(vectors) != 1:
            raise ValueError("embedding provider must return exactly one vector per input")
        vector = vectors[0]
        if len(vector) != VECTOR_DIMENSIONS:
            raise ValueError(f"embedding must have exactly {VECTOR_DIMENSIONS} dimensions")
        return vector
