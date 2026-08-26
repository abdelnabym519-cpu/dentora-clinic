"""Event-bus adapter for patient application events."""

from app.core.events import EventType, event_bus

from .domain import PatientEntity
from .ports import PatientEventPublisher


class EventBusPatientEventPublisher(PatientEventPublisher):
    """Translate patient use-case events into the existing Dentora event bus."""

    async def patient_created(self, patient: PatientEntity) -> None:
        await event_bus.publish(
            EventType.PATIENT_CREATED,
            {
                "patient_id": str(patient.id),
                "clinic_id": str(patient.clinic_id),
            },
        )

    async def patient_updated(
        self,
        patient: PatientEntity,
        changed_fields: tuple[str, ...],
    ) -> None:
        await event_bus.publish(
            EventType.PATIENT_UPDATED,
            {
                "patient_id": str(patient.id),
                "clinic_id": str(patient.clinic_id),
                "changes": list(changed_fields),
            },
        )

    async def patient_archived(self, patient: PatientEntity) -> None:
        await event_bus.publish(
            EventType.PATIENT_ARCHIVED,
            {
                "patient_id": str(patient.id),
                "clinic_id": str(patient.clinic_id),
            },
        )
