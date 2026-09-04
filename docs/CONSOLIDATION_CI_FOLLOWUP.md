# Required CI follow-up: pgvector image

## One-line change that must be applied manually

`.github/workflows/ci.yml`, `backend-test` job, `services.postgres.image`:

```diff
-        image: postgres:15-alpine
+        image: pgvector/pgvector:0.8.6-pg15-bookworm
```

## Why this is required

The vector/AI retrieval integration (`backend/app/core/retrieval/`) uses
pgvector. `RetrievalRepository` issues:

```sql
SET LOCAL hnsw.iterative_scan = strict_order
```

`hnsw.iterative_scan` was introduced in **pgvector 0.8.0**. On any image
without pgvector >= 0.8 the statement fails with:

```
asyncpg.exceptions.InvalidNameError: invalid configuration parameter name
"hnsw.iterative_scan"
DETAIL: "hnsw" is a reserved prefix.
```

which makes these two tests fail:

- `tests/core/test_retrieval.py::test_semantic_search_is_hard_scoped_to_clinic_and_audited`
- `tests/core/test_retrieval.py::test_ready_filter_excludes_stale_and_failed_embeddings`

The stock `postgres:15-alpine` image ships no pgvector at all, so the
`0010_vector_retrieval_foundation` migration cannot even run
(`CREATE EXTENSION vector`).

## Why it is not already committed

The agent's GitHub App lacks the `workflows` permission, so any push
touching `.github/workflows/**` is rejected by the remote:

```
refusing to allow a GitHub App to create or update workflow
`.github/workflows/ci.yml` without `workflows` permission
```

The change was therefore reverted from the pushed branch so the remaining
176 files could be preserved. **Apply it by hand before relying on CI.**

## Verification status of the retrieval feature

Validated in the sandbox against a real PostgreSQL 16.2 with pgvector:

- migration graph: no duplicate revision ids, 30 heads, fresh-DB
  `alembic upgrade heads` reaches `0010`
- alembic round-trip gate: 8 passed
- 4 of 6 retrieval tests pass

The 2 failures above are attributable **solely** to the sandbox's bundled
pgvector being **0.6.2**. They are expected to pass on
`pgvector/pgvector:0.8.6-pg15-bookworm`. Until a CI run on that image is
green, the retrieval feature is **NOT** fully verified.
