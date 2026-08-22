"""Composition helpers for the patients application service.

This module is the outer wiring boundary: SQLAlchemy and the concrete event-bus
adapter are assembled here so the application service remains infrastructure-
agnostic.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from .event_publisher import EventBusPatientEventPublisher
from .repository import SqlAlchemyPatientRepository
from .service import PatientService


def build_patient_service(db: AsyncSession) -> PatientService:
    """Build a patient service bound to the request/session infrastructure."""
    return PatientService(
        repository=SqlAlchemyPatientRepository(db),
        events=EventBusPatientEventPublisher(),
    )
