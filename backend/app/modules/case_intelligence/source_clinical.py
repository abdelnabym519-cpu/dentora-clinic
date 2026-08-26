"""Patient, medical, odontogram and treatment-history source adapters."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.odontogram.models import ToothRecord, Treatment, TreatmentTooth
from app.modules.patients.models import Patient
from app.modules.patients_clinical.models import (
    Allergy,
    MedicalContext,
    Medication,
    SurgicalHistory,
    SystemicDisease,
)

from .contracts import AvailabilityStatus
from .source_common import data, evidence, section


async def collect_clinical_sources(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> dict[str, dict[str, Any]]:
    patient = await db.scalar(
        select(Patient).where(
            Patient.id == patient_id,
            Patient.clinic_id == clinic_id,
            Patient.status != "archived",
        )
    )
    if patient is None:
        raise KeyError("patient_not_found")

    patient_data = data(
        patient,
        "id",
        "status",
        "date_of_birth",
        "gender",
        "preferred_language",
        "created_at",
        "updated_at",
    )
    sections: dict[str, dict[str, Any]] = {
        "patient": section(
            AvailabilityStatus.AVAILABLE,
            data_value=patient_data,
            evidence_value=[
                evidence(
                    "patients",
                    "Patient",
                    patient.id,
                    patient_data,
                    version=patient.updated_at.isoformat(),
                )
            ],
        )
    }
    sections["medical_context"] = await _medical(db, clinic_id, patient_id)
    odontogram, history = await _odontogram(db, clinic_id, patient_id)
    sections["odontogram"] = odontogram
    sections["treatment_history"] = history
    return sections


async def _medical(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> dict[str, Any]:
    context = await db.scalar(
        select(MedicalContext).where(
            MedicalContext.clinic_id == clinic_id,
            MedicalContext.patient_id == patient_id,
        )
    )
    specs = (
        (Allergy, "Allergy", ("name", "type", "severity", "reaction", "notes")),
        (Medication, "Medication", ("name", "dosage", "frequency", "start_date", "notes")),
        (
            SystemicDisease,
            "SystemicDisease",
            ("name", "type", "diagnosis_date", "is_controlled", "is_critical", "notes"),
        ),
        (
            SurgicalHistory,
            "SurgicalHistory",
            ("procedure", "surgery_date", "complications", "notes"),
        ),
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    refs: list[dict[str, Any]] = []
    for model, entity, fields in specs:
        rows = (
            await db.scalars(
                select(model)
                .where(model.clinic_id == clinic_id, model.patient_id == patient_id)
                .order_by(model.created_at, model.id)
            )
        ).all()
        payloads = [
            {"id": row.id, **data(row, *fields), "updated_at": row.updated_at} for row in rows
        ]
        grouped[entity] = payloads
        refs.extend(
            evidence(
                "patients_clinical",
                entity,
                row.id,
                payload,
                version=row.updated_at.isoformat(),
            )
            for row, payload in zip(rows, payloads, strict=True)
        )

    context_data = None
    if context is not None:
        context_data = data(
            context,
            "is_pregnant",
            "pregnancy_week",
            "is_lactating",
            "is_on_anticoagulants",
            "anticoagulant_medication",
            "inr_value",
            "last_inr_date",
            "is_smoker",
            "smoking_frequency",
            "alcohol_consumption",
            "bruxism",
            "adverse_reactions_to_anesthesia",
            "anesthesia_reaction_details",
            "last_updated_at",
        )
        refs.append(
            evidence(
                "patients_clinical",
                "MedicalContext",
                context.patient_id,
                context_data,
                version=context.updated_at.isoformat(),
            )
        )
    if context is None and not any(grouped.values()):
        return section(
            AvailabilityStatus.NOT_AVAILABLE,
            reason="clinical_history_not_available",
        )
    return section(
        AvailabilityStatus.AVAILABLE,
        data_value={"context": context_data, **grouped},
        evidence_value=refs,
    )


async def _odontogram(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> tuple[dict[str, Any], dict[str, Any]]:
    teeth = (
        await db.scalars(
            select(ToothRecord)
            .where(ToothRecord.clinic_id == clinic_id, ToothRecord.patient_id == patient_id)
            .order_by(ToothRecord.tooth_number)
        )
    ).all()
    tooth_payloads = [
        {
            "id": row.id,
            **data(
                row,
                "tooth_number",
                "tooth_type",
                "general_condition",
                "surfaces",
                "notes",
                "is_displaced",
                "is_rotated",
                "displacement_notes",
                "updated_at",
            ),
        }
        for row in teeth
    ]
    odontogram = (
        section(
            AvailabilityStatus.AVAILABLE,
            data_value={"teeth": tooth_payloads},
            evidence_value=[
                evidence(
                    "odontogram",
                    "ToothRecord",
                    row.id,
                    payload,
                    version=row.updated_at.isoformat(),
                )
                for row, payload in zip(teeth, tooth_payloads, strict=True)
            ],
        )
        if teeth
        else section(AvailabilityStatus.NOT_AVAILABLE, reason="odontogram_not_available")
    )

    treatments = (
        await db.scalars(
            select(Treatment)
            .where(
                Treatment.clinic_id == clinic_id,
                Treatment.patient_id == patient_id,
                Treatment.deleted_at.is_(None),
            )
            .order_by(Treatment.recorded_at, Treatment.id)
        )
    ).all()
    payloads: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    for row in treatments:
        links = (
            await db.scalars(
                select(TreatmentTooth)
                .where(TreatmentTooth.treatment_id == row.id)
                .order_by(TreatmentTooth.tooth_number)
            )
        ).all()
        payload = {
            "id": row.id,
            **data(
                row,
                "clinical_type",
                "scope",
                "arch",
                "status",
                "recorded_at",
                "performed_at",
                "source_module",
                "notes",
                "updated_at",
            ),
            "teeth": [data(link, "tooth_number", "role", "surfaces") for link in links],
        }
        payloads.append(payload)
        refs.append(
            evidence(
                "odontogram",
                "Treatment",
                row.id,
                payload,
                version=row.updated_at.isoformat(),
            )
        )
    history = (
        section(
            AvailabilityStatus.AVAILABLE,
            data_value={"treatments": payloads},
            evidence_value=refs,
        )
        if payloads
        else section(
            AvailabilityStatus.NOT_AVAILABLE,
            reason="treatment_history_not_available",
        )
    )
    return odontogram, history
