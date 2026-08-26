"""APScheduler configuration for background jobs.

Provides one periodic scheduler across horizontally scaled API replicas.
Leadership is delegated through a port so scheduler policy stays independent
from the PostgreSQL advisory-lock implementation used by the composition root.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.core.plugins.registry import module_registry
from app.core.scheduler_leadership import SchedulerLeaderLease
from app.core.scheduling import ScheduledJob

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None
_leader_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Get the scheduler instance, creating it if needed."""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    return scheduler


def _build_trigger(job: ScheduledJob) -> CronTrigger | IntervalTrigger:
    if job.trigger == "cron":
        return CronTrigger(**job.trigger_args)
    if job.trigger == "interval":
        return IntervalTrigger(**job.trigger_args)
    raise ValueError(f"Unknown trigger '{job.trigger}' for job '{job.id}'")


def _start_scheduler_jobs() -> None:
    """Register module jobs and start the process-local scheduler."""
    local_scheduler = get_scheduler()

    for module in module_registry.list_modules():
        for job in module.get_scheduled_jobs():
            if local_scheduler.get_job(job.id):
                logger.info("Scheduler job '%s' already exists, skipping", job.id)
                continue
            local_scheduler.add_job(
                job.func,
                _build_trigger(job),
                id=job.id,
                name=job.name,
                max_instances=job.max_instances,
                replace_existing=True,
            )
            logger.info("Registered job '%s' from module '%s'", job.id, module.name)

    if not local_scheduler.running:
        local_scheduler.start()
        logger.info("Scheduler started on elected leader")


def _stop_scheduler_jobs() -> None:
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped on this replica")
    scheduler = None


async def _leadership_loop(
    lease: SchedulerLeaderLease,
    retry_seconds: float,
    leader: bool,
) -> None:
    """Renew leader health and let followers take over after leader loss."""
    assert _stop_event is not None

    try:
        while not _stop_event.is_set():
            try:
                if leader:
                    if not await lease.healthy():
                        _stop_scheduler_jobs()
                        await lease.release()
                        leader = False
                        logger.warning("Lost scheduler leadership; entering follower mode")
                elif await lease.acquire():
                    try:
                        _start_scheduler_jobs()
                    except Exception:
                        await lease.release()
                        raise
                    leader = True
                    logger.info("Replica elected as scheduler leader")
            except Exception:
                logger.exception("Scheduler leader-election iteration failed")

            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=retry_seconds)
            except TimeoutError:
                pass
    finally:
        _stop_scheduler_jobs()
        if leader:
            await lease.release()


async def init_scheduler(
    lease: SchedulerLeaderLease | None = None,
    *,
    retry_seconds: float = 15.0,
) -> None:
    """Initialize periodic jobs safely for one or many API replicas.

    Tests keep the historical no-scheduler behavior. A caller may omit a
    lease for single-process/dev use, but production composition supplies a
    PostgreSQL-backed lease so only one replica runs periodic jobs at a time.
    """
    global _leader_task, _stop_event

    if settings.TESTING:
        logger.info("Skipping scheduler initialization in test mode")
        return

    if lease is None:
        _start_scheduler_jobs()
        return

    if retry_seconds <= 0:
        raise ValueError("scheduler leader retry interval must be positive")

    _stop_event = asyncio.Event()
    leader = False
    try:
        if await lease.acquire():
            _start_scheduler_jobs()
            leader = True
            logger.info("Replica elected as scheduler leader")
        else:
            logger.info("Scheduler leadership held by another API replica")
    except Exception:
        logger.exception("Initial scheduler leader-election attempt failed; will retry")

    _leader_task = asyncio.create_task(
        _leadership_loop(lease, retry_seconds, leader),
        name="dentora-scheduler-leader-election",
    )


async def shutdown_scheduler() -> None:
    """Stop leader election, release leadership, and shut down jobs."""
    global _leader_task, _stop_event

    if _stop_event is not None:
        _stop_event.set()
    if _leader_task is not None:
        await _leader_task

    _leader_task = None
    _stop_event = None
    _stop_scheduler_jobs()
