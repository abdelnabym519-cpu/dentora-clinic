"""Provider-neutral contracts for embedding and retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class RetrievalPurpose(StrEnum):
    """Auditable reason for executing a similarity query."""

    SEMANTIC_SEARCH = "semantic_search"
    SIMILAR_CASES = "similar_cases"
    RAG = "rag"
    CLINICAL_KNOWLEDGE = "clinical_knowledge"


@dataclass(frozen=True, slots=True)
class EmbeddingSource:
    """Ephemeral source text used to derive an embedding.

    ``text`` is never persisted by the retrieval index. The authoritative
    clinical row remains in its owning module and only its digest/reference is
    recorded here.
    """

    clinic_id: UUID
    source_type: str
    source_id: str
    text: str
    patient_id: UUID | None = None
    chunk_key: str = "full"
    source_updated_at: datetime | None = None
    external_embedding_allowed: bool = False


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """Reference-only result. Callers must reload source data tenant-safely."""

    embedding_id: UUID
    clinic_id: UUID
    patient_id: UUID | None
    source_type: str
    source_id: str
    chunk_key: str
    source_digest: str
    embedding_model: str
    embedding_version: str
    distance: float


@dataclass(frozen=True, slots=True)
class RetrievalWorkItem:
    """Claimed background embedding work without source plaintext."""

    embedding_id: UUID
    clinic_id: UUID
    patient_id: UUID | None
    source_type: str
    source_id: str
    chunk_key: str
    source_digest: str
    embedding_model: str
    embedding_version: str
    attempt_count: int


class EmbeddingProvider(Protocol):
    """Separate from the chat LLM contract: embeddings are a distinct concern."""

    @property
    def name(self) -> str: ...

    @property
    def is_external(self) -> bool: ...

    async def embed(
        self,
        texts: list[str],
        *,
        model: str,
        dimensions: int,
    ) -> list[list[float]]: ...


class EmbeddingSourceLoader(Protocol):
    """Loads current source text for a claimed work item from its owning module."""

    async def load(self, item: RetrievalWorkItem) -> EmbeddingSource | None: ...
