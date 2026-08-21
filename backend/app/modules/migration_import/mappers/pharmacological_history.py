"""Map ``pharmacological_history`` → :class:`patients_clinical.Medication`.

Gesdén's ``TTratamientos`` row records a drug the patient is taking,
which dental-bridge exports as ``CanonicalPharmacologicalHistory``.
Dentora keeps these on the patient profile under
:class:`patients_clinical.Medication`. Without this mapper the rows
fell into ``RawEntity`` audit-only — the patient's clinical sidebar
opened blank even when the source had a full medication list.

We write directly to the model (no service layer in
``patients_clinical``) and stamp ``notes`` with the source observation
plus the drug-administration metadata that Medication doesn't have a
column for (dose, route, frequency, record_kind).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.modules.patients_clinical.models import Medication

from ..models import ImportWarning
from .base import MapperContext


class PharmacologicalHistoryMapper:
    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        existing = await ctx.resolver.get("pharmacological_history", canonical_uuid)
        if existing is not None:
            return existing
        if await ctx.resolver.was_skipped("pharmacological_history", canonical_uuid):
            return None

        patient_uuid = payload.get("patient_uuid")
        if not patient_uuid:
            await _warn(
                ctx,
                source_id,
                "pharm.no_patient",
                "Historial farmacológico omitido: sin paciente en origen.",
            )
            await ctx.resolver.mark_skipped(
                "pharmacological_history", canonical_uuid, source_system
            )
            return None
        patient_id = await ctx.resolver.get("patient", str(patient_uuid))
        if patient_id is None:
            await _warn(
                ctx,
                source_id,
                "pharm.unmapped_patient",
                "Historial farmacológico omitido: paciente no mapeado previamente.",
            )
            await ctx.resolver.mark_skipped(
                "pharmacological_history", canonical_uuid, source_system
            )
            return None

        drug_name = (payload.get("drug_description") or "").strip()
        if not drug_name:
            # Without a drug name the row is just an empty placeholder —
            # nothing actionable to render in the clinical sidebar.
            await _warn(
                ctx,
                source_id,
                "pharm.no_drug_name",
                "Historial farmacológico omitido: sin nombre de fármaco en origen.",
            )
            await ctx.resolver.mark_skipped(
                "pharmacological_history", canonical_uuid, source_system
            )
            return None

        # Combine dose + dosage into Medication.dosage, falling back to
        # whichever the source filled. Both columns are 100-char so we
        # trim safely.
        dose = (payload.get("dose") or "").strip()
        dosage = (payload.get("dosage") or "").strip()
        combined_dose = " · ".join(p for p in (dose, dosage) if p) or None
        if combined_dose:
            combined_dose = combined_dose[:100]

        frequency = (payload.get("frequency") or "").strip() or None
        if frequency:
            frequency = frequency[:100]

        # Stash administration_route + observations + record_kind in
        # notes since Medication has no dedicated columns.
        notes_bits: list[str] = []
        observations = (payload.get("observations") or "").strip()
        if observations:
            notes_bits.append(observations)
        route = (payload.get("administration_route") or "").strip()
        if route:
            notes_bits.append(f"Vía: {route}")
        record_kind = payload.get("record_kind")
        if record_kind is not None:
            notes_bits.append(f"Migrado dental-bridge — record_kind={record_kind}")
        else:
            notes_bits.append("Migrado dental-bridge.")
        notes = "\n".join(notes_bits) or None

        med = Medication(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            name=drug_name[:100],
            dosage=combined_dose,
            frequency=frequency,
            start_date=_parse_date(payload.get("start_date")),
            notes=notes,
        )
        ctx.db.add(med)
        await ctx.db.flush()

        await ctx.resolver.set(
            entity_type="pharmacological_history",
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dentora_table="patients_clinical_medication",
            dentora_id=med.id,
        )
        return med.id


async def _warn(ctx: MapperContext, source_id: str, code: str, message: str) -> None:
    ctx.db.add(
        ImportWarning(
            job_id=ctx.job_id,
            entity_type="pharmacological_history",
            source_id=source_id,
            severity="warn",
            code=code,
            message=message,
        )
    )


def _parse_date(value: Any):
    from datetime import date

    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
