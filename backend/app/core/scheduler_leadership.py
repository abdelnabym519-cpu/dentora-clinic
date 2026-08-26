"""Port for electing exactly one periodic-job scheduler across API replicas."""

from __future__ import annotations

from typing import Protocol


class SchedulerLeaderLease(Protocol):
    """Exclusive renewable lease used by the scheduler control loop."""

    async def acquire(self) -> bool:
        """Try to acquire leadership without blocking."""

    async def healthy(self) -> bool:
        """Return whether the held lease is still alive."""

    async def release(self) -> None:
        """Release leadership and associated infrastructure resources."""
