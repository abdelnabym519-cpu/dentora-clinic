"""PostgreSQL advisory-lock adapter for scheduler leader election."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = logging.getLogger(__name__)

# Stable application-scoped lock key. This is not a tuning threshold; it only
# names Dentora's scheduler leadership mutex inside PostgreSQL.
DENTORA_SCHEDULER_LOCK_ID = 5_382_202_608_26


class PostgresAdvisorySchedulerLease:
    """Hold a session-level PostgreSQL advisory lock for scheduler leadership."""

    def __init__(self, engine: AsyncEngine, lock_id: int = DENTORA_SCHEDULER_LOCK_ID) -> None:
        self._engine = engine
        self._lock_id = lock_id
        self._connection: AsyncConnection | None = None

    async def acquire(self) -> bool:
        if self._connection is not None:
            return True

        connection = await self._engine.connect()
        try:
            acquired = bool(
                (
                    await connection.execute(
                        text("SELECT pg_try_advisory_lock(:lock_id)"),
                        {"lock_id": self._lock_id},
                    )
                ).scalar_one()
            )
        except Exception:
            await connection.close()
            raise

        if not acquired:
            await connection.close()
            return False

        self._connection = connection
        logger.info("Acquired scheduler leader advisory lock %s", self._lock_id)
        return True

    async def healthy(self) -> bool:
        connection = self._connection
        if connection is None:
            return False
        try:
            await connection.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("Scheduler leader database lease became unhealthy")
            try:
                await connection.close()
            finally:
                self._connection = None
            return False

    async def release(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": self._lock_id},
            )
        except Exception:
            logger.exception("Failed to explicitly release scheduler advisory lock")
        finally:
            await connection.close()
            logger.info("Released scheduler leader advisory lock %s", self._lock_id)
