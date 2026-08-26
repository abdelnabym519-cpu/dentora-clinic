"""Dental3D native-source, alignment, anatomy, nerve and prosthetic adapters."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dental_3d.implant_models import DentalProstheticTarget
from app.modules.dental_3d.models import DentalAlignmentResult, DentalNerveAnalysis
from app.modules.dental_3d.service import DentalSceneService

from .contracts import AvailabilityStatus
from .source_common import data, evidence, section


async def collect_dental3d_sources(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> tuple[dict[str, dict[str, Any]], UUID | None]:
    sections: dict[str, dict[str, Any]] = {}
    scene = await DentalSceneService.get_for_patient(db, clinic_id, patient_id)
    _native_sources(scene, sections)

    alignment = await _latest_alignment(db, clinic_id, patient_id)
    accepted_alignment_id = _alignment_sections(alignment, sections)
    sections["nerve"] = await _nerve(db, clinic_id, patient_id, alignment)
    sections["prosthetic"] = await _prosthetic(
        db,
        clinic_id,
        patient_id,
        accepted_alignment_id,
    )
    return sections, accepted_alignment_id


def _native_sources(scene: Any, sections: dict[str, dict[str, Any]]) -> None:
    meshes = sorted(scene.meshes, key=lambda item: str(item.document_id))
    mesh_payloads = [item.model_dump(mode="json") for item in meshes]
    sections["ios"] = (
        section(
            AvailabilityStatus.AVAILABLE,
            data_value={"meshes": mesh_payloads},
            evidence_value=[
                evidence(
                    "dental_3d",
                    "DentalMesh",
                    item.document_id,
                    payload,
                    version=item.uploaded_at.isoformat(),
                    validation_state="media_validated_mesh",
                )
                for item, payload in zip(meshes, mesh_payloads, strict=True)
            ],
        )
        if mesh_payloads
        else section(AvailabilityStatus.NOT_AVAILABLE, reason="ios_not_available")
    )

    cbct = sorted(scene.cbct_series, key=lambda item: item.series_instance_uid)
    cbct_payloads = [item.model_dump(mode="json") for item in cbct]
    sections["cbct"] = (
        section(
            AvailabilityStatus.AVAILABLE,
            data_value={"series": cbct_payloads},
            evidence_value=[
                evidence(
                    "dental_3d",
                    "CbctSeriesDescriptor",
                    item.series_instance_uid,
                    payload,
                    version=item.latest_uploaded_at.isoformat(),
                    validation_state="validated_dicom_metadata",
                )
                for item, payload in zip(cbct, cbct_payloads, strict=True)
            ],
        )
        if cbct_payloads
        else section(AvailabilityStatus.NOT_AVAILABLE, reason="cbct_not_available")
    )


async def _latest_alignment(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> DentalAlignmentResult | None:
    return await db.scalar(
        select(DentalAlignmentResult)
        .where(
            DentalAlignmentResult.clinic_id == clinic_id,
            DentalAlignmentResult.patient_id == patient_id,
        )
        .order_by(desc(DentalAlignmentResult.created_at), desc(DentalAlignmentResult.id))
        .limit(1)
    )


def _alignment_sections(
    alignment: DentalAlignmentResult | None,
    sections: dict[str, dict[str, Any]],
) -> UUID | None:
    if alignment is None:
        sections["alignment"] = section(
            AvailabilityStatus.NOT_AVAILABLE,
            reason="alignment_not_available",
        )
        sections["anatomy"] = section(
            AvailabilityStatus.NOT_AVAILABLE,
            reason="validated_cbct_anatomy_not_available",
        )
        return None

    payload = {
        "id": alignment.id,
        **data(
            alignment,
            "status",
            "algorithm",
            "algorithm_version",
            "provenance",
            "performed_at",
            "reviewed_at",
        ),
        "patient_space": {
            "source_frame": alignment.source_frame,
            "target_frame": alignment.target_frame,
            "transform": alignment.transform,
        },
    }
    ref = evidence(
        "dental_3d",
        "DentalAlignmentResult",
        alignment.id,
        payload,
        version=alignment.updated_at.isoformat(),
        validation_state=alignment.status,
    )
    target = alignment.target_frame or {}
    accepted = (
        alignment.status == "accepted"
        and alignment.transform is not None
        and alignment.source_frame is not None
        and target.get("kind") == "dicom_patient"
        and target.get("unit") == "mm"
        and bool(target.get("frame_of_reference_uid"))
    )
    sections["alignment"] = section(
        AvailabilityStatus.AVAILABLE if accepted else AvailabilityStatus.INVALID_OR_STALE,
        data_value=payload,
        evidence_value=[ref],
        reason=None if accepted else "latest_alignment_not_accepted_or_patient_space_invalid",
    )

    provenance = alignment.provenance or {}
    anatomy_id = provenance.get("anatomy_model_id")
    anatomy_version = provenance.get("anatomy_model_version")
    if accepted and anatomy_id and anatomy_version and provenance.get("cbct"):
        sections["anatomy"] = section(
            AvailabilityStatus.AVAILABLE,
            data_value={
                "model_id": anatomy_id,
                "model_version": anatomy_version,
                "cbct_source": provenance["cbct"],
            },
            evidence_value=[ref],
        )
    else:
        sections["anatomy"] = section(
            AvailabilityStatus.NOT_AVAILABLE if accepted else AvailabilityStatus.INVALID_OR_STALE,
            evidence_value=[ref],
            reason=(
                "explicit_validated_cbct_anatomy_provenance_not_available"
                if accepted
                else "cbct_anatomy_not_bound_to_accepted_alignment"
            ),
        )
    return alignment.id if accepted else None


async def _nerve(
    db: AsyncSession,
    clinic_id: UUID,
    patient_id: UUID,
    alignment: DentalAlignmentResult | None,
) -> dict[str, Any]:
    nerve = await db.scalar(
        select(DentalNerveAnalysis)
        .where(
            DentalNerveAnalysis.clinic_id == clinic_id,
            DentalNerveAnalysis.patient_id == patient_id,
        )
        .order_by(desc(DentalNerveAnalysis.created_at), desc(DentalNerveAnalysis.id))
        .limit(1)
    )
    if nerve is None:
        return section(AvailabilityStatus.NOT_AVAILABLE, reason="validated_nerve_not_available")

    payload = data(
        nerve,
        "id",
        "provider",
        "method",
        "performed_at",
        "pathways",
        "proximities",
        "detection_status",
        "input_kind",
        "analysis_metadata",
        "review_status",
        "reviewed_at",
    )
    pathways = nerve.pathways or []
    spaces = [item.get("reference_space") or {} for item in pathways]
    native = bool(pathways) and all(
        space.get("kind") == "dicom_patient"
        and space.get("unit") == "mm"
        and bool(space.get("frame_of_reference_uid"))
        for space in spaces
    )
    expected_frame = None
    if alignment is not None and alignment.status == "accepted":
        expected_frame = (alignment.target_frame or {}).get("frame_of_reference_uid")
    frames = {space.get("frame_of_reference_uid") for space in spaces}
    compatible = expected_frame is None or frames == {expected_frame}
    valid = (
        nerve.review_status == "accepted"
        and nerve.detection_status == "detected"
        and nerve.input_kind == "cbct_series"
        and native
        and compatible
    )
    if valid:
        reason = None
    elif expected_frame is not None and native and not compatible:
        reason = "nerve_frame_mismatch_with_current_accepted_alignment"
    elif nerve.review_status != "accepted" or nerve.detection_status != "detected":
        reason = "latest_nerve_pathway_not_validated"
    else:
        reason = "latest_nerve_pathway_not_validated_patient_space_cbct_geometry"
    return section(
        AvailabilityStatus.AVAILABLE if valid else AvailabilityStatus.INVALID_OR_STALE,
        data_value=payload,
        evidence_value=[
            evidence(
                "dental_3d",
                "DentalNerveAnalysis",
                nerve.id,
                payload,
                version=nerve.updated_at.isoformat(),
                validation_state=f"{nerve.detection_status}:{nerve.review_status}",
            )
        ],
        reason=reason,
    )


async def _prosthetic(
    db: AsyncSession,
    clinic_id: UUID,
    patient_id: UUID,
    accepted_alignment_id: UUID | None,
) -> dict[str, Any]:
    target = await db.scalar(
        select(DentalProstheticTarget)
        .where(
            DentalProstheticTarget.clinic_id == clinic_id,
            DentalProstheticTarget.patient_id == patient_id,
        )
        .order_by(desc(DentalProstheticTarget.created_at), desc(DentalProstheticTarget.id))
        .limit(1)
    )
    if target is None:
        return section(AvailabilityStatus.NOT_AVAILABLE, reason="prosthetic_target_not_available")

    payload = data(
        target,
        "id",
        "alignment_id",
        "platform_center",
        "axis",
        "frame_of_reference_uid",
        "source_type",
        "source_reference_space",
        "source_frame_of_reference_uid",
        "source_method",
        "source_identifier",
        "source_digest",
        "source_document_ids",
        "review_status",
        "reviewed_at",
    )
    valid = (
        target.review_status == "accepted"
        and accepted_alignment_id is not None
        and target.alignment_id == accepted_alignment_id
    )
    reason = None
    if not valid:
        reason = (
            "latest_prosthetic_target_not_accepted"
            if target.review_status != "accepted"
            else "prosthetic_target_not_bound_to_current_accepted_alignment"
        )
    return section(
        AvailabilityStatus.AVAILABLE if valid else AvailabilityStatus.INVALID_OR_STALE,
        data_value=payload,
        evidence_value=[
            evidence(
                "dental_3d",
                "DentalProstheticTarget",
                target.id,
                payload,
                version=target.updated_at.isoformat(),
                validation_state=target.review_status,
            )
        ],
        reason=reason,
    )
