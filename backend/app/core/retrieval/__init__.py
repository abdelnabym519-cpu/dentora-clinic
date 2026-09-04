"""Tenant-safe vector retrieval foundation.

Clinical PostgreSQL rows remain the source of truth. This package owns only
rebuildable embedding/index metadata and retrieval orchestration.
"""

from .constants import (
    DEFAULT_DISTANCE_METRIC,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_VERSION,
    VECTOR_DIMENSIONS,
)
from .contracts import (
    EmbeddingProvider,
    EmbeddingSource,
    EmbeddingSourceLoader,
    RetrievalHit,
    RetrievalPurpose,
    RetrievalWorkItem,
)
from .repository import SqlAlchemyRetrievalRepository
from .service import EmbeddingPrivacyError, RetrievalService

__all__ = [
    "DEFAULT_DISTANCE_METRIC",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_VERSION",
    "VECTOR_DIMENSIONS",
    "EmbeddingPrivacyError",
    "EmbeddingProvider",
    "EmbeddingSource",
    "EmbeddingSourceLoader",
    "RetrievalHit",
    "RetrievalPurpose",
    "RetrievalService",
    "RetrievalWorkItem",
    "SqlAlchemyRetrievalRepository",
]
