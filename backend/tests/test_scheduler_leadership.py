"""Scaling safety tests for periodic scheduler leader election."""

import pytest

from app.database import engine
from app.infrastructure.scheduler_leadership import PostgresAdvisorySchedulerLease


@pytest.mark.asyncio
async def test_postgres_scheduler_lease_allows_exactly_one_leader() -> None:
    first = PostgresAdvisorySchedulerLease(engine, lock_id=8_260_202_601)
    second = PostgresAdvisorySchedulerLease(engine, lock_id=8_260_202_601)

    try:
        assert await first.acquire() is True
        assert await first.healthy() is True
        assert await second.acquire() is False

        await first.release()
        assert await second.acquire() is True
        assert await second.healthy() is True
    finally:
        await first.release()
        await second.release()
