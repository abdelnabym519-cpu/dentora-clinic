"""Stable vector-space defaults for the first retrieval schema version."""

VECTOR_DIMENSIONS = 1536
DEFAULT_DISTANCE_METRIC = "cosine"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_VERSION = "v1"
MAX_RETRIEVAL_LIMIT = 50
DEFAULT_LEASE_SECONDS = 300

RETRIEVAL_STATUSES = frozenset(
    {"pending", "processing", "ready", "stale", "failed", "deleted"}
)

# Source categories are intentionally broader than today's modules so future
# clinical adapters do not require a schema rewrite. They identify derived
# index entries, never authoritative records.
SOURCE_CLINICAL_NOTE = "clinical_note"
SOURCE_AI_CASE_SUMMARY = "ai_case_summary"
SOURCE_CASE_SNAPSHOT = "case_snapshot"
SOURCE_DENTAL_3D = "dental_3d"
SOURCE_CLINICAL_KNOWLEDGE = "clinical_knowledge"
SIMILAR_CASE_SOURCE_TYPES = (SOURCE_CASE_SNAPSHOT, SOURCE_AI_CASE_SUMMARY)
