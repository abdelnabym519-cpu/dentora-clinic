"""Periodontogram, timeline and media source adapters."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.models import Document
from app.modules.patient_timeline.models import PatientTimeline
from app.modules.periodontogram.models import (
    PeriodontogramSite,
    PeriodontogramSnapshot,
    PeriodontogramTooth,
)

from .contracts import AvailabilityStatus
from .source_common import data, evidence, section


async def collect_record_sources(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> dict[str, dict[str, Any]]:
    periodontogram = await _periodontogram(db, clinic_id, patient_id)
    timeline, media = await _timeline_media(db, clinic_id, patient_id)
    return {
        "periodontogram": periodontogram,
        "timeline": timeline,
        "media": media,
    }


async def _periodontogram(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> dict[str, Any]:
    latest = await db.scalar(
        select(PeriodontogramSnapshot)
        .where(
            PeriodontogramSnapshot.clinic_id == clinic_id,
            PeriodontogramSnapshot.patient_id == patient_id,
        )
        .order_by(desc(PeriodontogramSnapshot.recorded_at), desc(PeriodontogramSnapshot.id))
        .limit(1)
    )
    if latest is None:
        return section(
            AvailabilityStatus.NOT_AVAILABLE,
            reason="periodontogram_not_available",
        )

    base = data(latest, "id", "status", "recorded_at", "closed_at", "notes", "indices")
    base_ref = evidence(
        "periodontogram",
        "PeriodontogramSnapshot",
        latest.id,
        base,
        version=latest.updated_at.isoformat(),
        validation_state=latest.status,
    )
    if latest.status != "closed":
        return section(
            AvailabilityStatus.INVALID_OR_STALE,
            data_value=base,
            evidence_value=[base_ref],
            reason="latest_periodontogram_not_closed",
        )

    teeth = (
        await db.scalars(
            select(PeriodontogramTooth)
            .where(PeriodontogramTooth.snapshot_id == latest.id)
            .order_by(PeriodontogramTooth.tooth_number)
        )
    ).all()
    sites = (
        await db.scalars(
            select(PeriodontogramSite)
            .where(PeriodontogramSite.snapshot_id == latest.id)
            .order_by(PeriodontogramSite.tooth_number, PeriodontogramSite.site_code)
        )
    ).all()
    payload = {
        **base,
        "teeth": [
            data(
                row,
                "tooth_number",
                "is_present",
                "is_implant",
                "mobility",
                "prognosis",
                "furcation_buccal",
                "furcation_lingual",
                "keratinized_gingiva_mm",
            )
            for row in teeth
        ],
        "sites": [
            data(
                row,
                "tooth_number",
                "site_code",
                "probing_depth_mm",
                "gingival_margin_mm",
                "bleeding_on_probing",
                "plaque",
                "suppuration",
            )
            for row in sites
        ],
    }
    return section(
        AvailabilityStatus.AVAILABLE,
        data_value=payload,
        evidence_value=[
            evidence(
                "periodontogram",
                "PeriodontogramSnapshot",
                latest.id,
                payload,
                version=latest.updated_at.isoformat(),
                validation_state="closed",
            )
        ],
    )


async def _timeline_media(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> tuple[dict[str, Any], dict[str, Any]]:
    timeline = (
        await db.scalars(
            select(PatientTimeline)
            .where(PatientTimeline.clinic_id == clinic_id, PatientTimeline.patient_id == patient_id)
            .order_by(PatientTimeline.occurred_at, PatientTimeline.id)
        )
    ).all()
    timeline_payloads = [
        data(
            row,
            "id",
            "event_type",
            "event_category",
            "source_table",
            "source_id",
            "title",
            "description",
            "event_data",
            "occurred_at",
        )
        for row in timeline
    ]
    timeline_section = (
        section(
            AvailabilityStatus.AVAILABLE,
            data_value={"events": timeline_payloads},
            evidence_value=[
                evidence(
                    "patient_timeline",
                    "PatientTimeline",
                    row.id,
                    payload,
                    version=row.occurred_at.isoformat(),
                )
                for row, payload in zip(timeline, timeline_payloads, strict=True)
            ],
        )
        if timeline
        else section(AvailabilityStatus.NOT_AVAILABLE, reason="timeline_not_available")
    )

    documents = (
        await db.scalars(
            select(Document)
            .where(
                Document.clinic_id == clinic_id,
                Document.patient_id == patient_id,
                Document.status == "active",
            )
            .order_by(Document.created_at, Document.id)
        )
    ).all()
    document_payloads = [
        data(
            row,
            "id",
            "document_type",
            "title",
            "mime_type",
            "file_size",
            "media_kind",
            "media_category",
            "media_subtype",
            "captured_at",
            "tags",
            "extra_data",
            "created_at",
            "updated_at",
        )
        for row in documents
    ]
    media_section = (
        section(
            AvailabilityStatus.AVAILABLE,
            data_value={"documents": document_payloads},
            evidence_value=[
                evidence(
                    "media",
                    "Document",
                    row.id,
                    payload,
                    version=row.updated_at.isoformat(),
                )
                for row, payload in zip(documents, document_payloads, strict=True)
            ],
        )
        if documents
        else section(AvailabilityStatus.NOT_AVAILABLE, reason="media_not_available")
    )
    return timeline_section, media_section
