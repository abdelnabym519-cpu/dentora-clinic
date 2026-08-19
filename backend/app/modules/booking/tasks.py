"""Background synchronization for public booking cloud requests."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.config import settings
from app.core.license.service import LicenseError
from app.database import async_session_maker

from .cloud_client import (
    BookingCloudError,
    build_booking_cloud_client,
)
from .cloud_processor import BookingCloudProcessor
from .models import BookingSettings

logger = logging.getLogger(__name__)


async def _resolve_local_booking_clinic(
    db: Any,
) -> UUID | None:
    """Return the unambiguous local clinic used by this installation."""

    result = await db.execute(select(BookingSettings.clinic_id).limit(2))

    clinic_ids = list(dict.fromkeys(result.scalars().all()))

    if len(clinic_ids) != 1:
        return None

    return clinic_ids[0]


async def sync_cloud_booking_requests(
    *,
    client_factory: Callable[[], Any] = build_booking_cloud_client,
    session_factory: Callable[[], Any] = async_session_maker,
    processor_factory: Callable[..., Any] = BookingCloudProcessor,
) -> None:
    """Pull and process delivered booking requests using outbound HTTPS only."""

    # Cloud booking is opt-in. A normal local installation with no cloud URL
    # must not make any outbound request or even touch the sync database path.
    if not settings.BOOKING_CLOUD_BASE_URL.strip():
        return

    # Resolve local authority BEFORE pulling. The cloud payload is never
    # allowed to choose an arbitrary local clinic.
    try:
        async with session_factory() as db:
            clinic_id = await _resolve_local_booking_clinic(db)
    except Exception:
        # Do not include exception details: database errors can contain
        # values that should not enter booking synchronization logs.
        logger.error("Booking cloud sync local clinic lookup failed; will retry")
        return

    if clinic_id is None:
        logger.warning("Booking cloud sync requires exactly one local booking clinic")
        return

    try:
        client = client_factory()
        requests = await client.pull_requests()
    except (LicenseError, BookingCloudError, ValueError):
        # Never log lease credentials or remote response bodies here.
        logger.warning("Booking cloud pull unavailable; will retry")
        return

    if not requests:
        return

    processor = processor_factory(
        cloud_client=client,
    )

    for request in requests:
        try:
            # One session/transaction scope per cloud request. A failure in
            # one booking cannot poison another booking's transaction.
            async with session_factory() as db:
                await processor.process_request(
                    db,
                    clinic_id=clinic_id,
                    request=request,
                )

        except (LicenseError, BookingCloudError):
            # The processor commits terminal local state before result sync.
            # A later pull safely replays that durable result.
            logger.warning("Booking cloud result synchronization failed; will retry")

        except Exception:
            # Unexpected local/database failures remain retryable and must
            # never be translated into a false patient rejection.
            logger.error("Booking cloud request processing failed; will retry")
