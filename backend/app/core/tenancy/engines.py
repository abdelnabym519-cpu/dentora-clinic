"""Engine registry keyed by database URL.

In shared-PostgreSQL mode every tenant shares :data:`app.database.engine`
(``settings.DATABASE_URL``). A tenant row may set ``db_url`` to point at
a **dedicated** database; this registry lazily builds and caches an
async engine per distinct URL so the future database-per-clinic /
database-per-tenant deployment is a data change, not a code change.

Engines are created with conservative pool settings and disposed on
application shutdown.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)


class TenantEngineRegistry:
    """Lazily create / cache async engines by URL."""

    def __init__(self, default_engine: AsyncEngine) -> None:
        self._default_engine = default_engine
        self._engines: dict[str, AsyncEngine] = {}

    def get(self, db_url: str | None) -> AsyncEngine:
        """Return the engine for ``db_url`` (or the shared default)."""
        if not db_url or db_url == self._default_engine.url.render_as_string(hide_password=False):
            return self._default_engine
        existing = self._engines.get(db_url)
        if existing is not None:
            return existing
        logger.info("Creating dedicated tenant engine for %s", db_url.split("@")[-1])
        engine = create_async_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=5,
            max_overflow=10,
        )
        self._engines[db_url] = engine
        return engine

    async def dispose_all(self) -> None:
        """Dispose every dedicated engine (the default is owned by app)."""
        for url, engine in list(self._engines.items()):
            try:
                await engine.dispose()
            except Exception:  # noqa: BLE001 - best-effort shutdown
                logger.exception("Failed disposing tenant engine for %s", url)
            self._engines.pop(url, None)
