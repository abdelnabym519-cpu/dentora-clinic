"""Read-only Dental3D adapter and deterministic simulator orchestration."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dental_3d.registration_service import DentalAlignmentService
from app.modules.dental_3d.schemas import DentalSceneResponse
from app.modules.dental_3d.service import DentalSceneService

from .domain import (
    CoordinateFrame,
    FdiToothId,
    MovementCaps,
    SimulationPlan,
    SimulationResult,
    ToothDelta,
    ToothGeometryRef,
    simulate,
    stage_movements,
)


class SimulatorSafetyError(RuntimeError):
    """A fail-closed eligibility boundary rejected patient movement."""


class CapabilityReason(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: Literal[
        "no-real-mesh",
        "whole-arch-only",
        "per-tooth-review-unproven",
        "scale-frame-untrusted",
        "tooth-local-frame-unavailable",
    ]
    message: str


class SimulatorCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    patient_id: UUID
    whole_arch_mesh_count: int = Field(ge=0)
    per_tooth_mesh_count: int = Field(ge=0)
    reviewed_per_tooth_mesh_count: int = Field(ge=0)
    accepted_alignment: bool = False
    translation_eligible: bool = False
    rotation_eligible: bool = False
    reasons: tuple[CapabilityReason, ...] = ()
    clinical_prediction: Literal[False] = False
    treatment_approval: Literal[False] = False


class AuthoredMovement(BaseModel):
    """Client-authored target only. Geometry/frame/provenance stay server-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    tooth: FdiToothId
    translate_x_mm: float = Field(default=0.0, ge=-20.0, le=20.0)
    translate_y_mm: float = Field(default=0.0, ge=-20.0, le=20.0)
    translate_z_mm: float = Field(default=0.0, ge=-20.0, le=20.0)
    rotate_tip_deg: float = Field(default=0.0, ge=-90.0, le=90.0)
    rotate_torque_deg: float = Field(default=0.0, ge=-90.0, le=90.0)
    rotate_rotation_deg: float = Field(default=0.0, ge=-180.0, le=180.0)

    @property
    def has_rotation(self) -> bool:
        return any((self.rotate_tip_deg, self.rotate_torque_deg, self.rotate_rotation_deg))


class SimulationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    movements: tuple[AuthoredMovement, ...] = Field(min_length=1, max_length=32)
    caps: MovementCaps = Field(default_factory=MovementCaps)


class SimulationResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: SimulatorCapability
    result: SimulationResult


def _per_tooth_meshes(scene: DentalSceneResponse):
    return [
        tooth
        for tooth in scene.teeth
        if tooth.present
        and tooth.mesh.source != "synthetic"
        and tooth.mesh.document_id is not None
        and tooth.mesh.format != "procedural"
    ]


class OrthodonticSimulatorService:
    """Simulator facade. Dental3D is read-only and source geometry is never copied/mutated."""

    @staticmethod
    async def capability(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> SimulatorCapability:
        scene = await DentalSceneService.get_for_patient(db, clinic_id, patient_id)
        alignment = await DentalAlignmentService.latest_alignment(db, clinic_id, patient_id)
        per_tooth = _per_tooth_meshes(scene)

        # The current Dental3D contract exposes dentist review for the latest
        # segmentation analysis, but not a review flag on arbitrary tooth-level
        # mesh descriptors. We only treat a per-tooth mapping as reviewed when
        # the segmentation projection itself is accepted.
        segmentation_accepted = scene.segmentation.review_status == "accepted"
        reviewed_count = len(per_tooth) if segmentation_accepted else 0

        accepted_alignment = bool(
            alignment
            and alignment.status == "accepted"
            and alignment.source_frame is not None
            and alignment.source_frame.unit == "mm"
            and alignment.provenance is not None
        )
        translation_eligible = bool(per_tooth) and reviewed_count == len(per_tooth) and accepted_alignment

        # Dental3D currently has no trusted per-tooth local-frame field. Never
        # infer one from crown shape, PCA or a whole-arch registration.
        rotation_eligible = False

        reasons: list[CapabilityReason] = []
        if not scene.meshes and not per_tooth:
            reasons.append(
                CapabilityReason(
                    code="no-real-mesh",
                    message="No patient-derived dental mesh is available for simulation.",
                )
            )
        if scene.meshes and not per_tooth:
            reasons.append(
                CapabilityReason(
                    code="whole-arch-only",
                    message=(
                        "Dental3D currently exposes whole-arch scan geometry without a reviewed "
                        "per-tooth mesh mapping; patient-specific tooth movement is disabled."
                    ),
                )
            )
        if per_tooth and not segmentation_accepted:
            reasons.append(
                CapabilityReason(
                    code="per-tooth-review-unproven",
                    message="Per-tooth geometry exists but dentist review provenance is not accepted.",
                )
            )
        if per_tooth and not accepted_alignment:
            reasons.append(
                CapabilityReason(
                    code="scale-frame-untrusted",
                    message="An accepted millimetre patient-space alignment is required for translation.",
                )
            )
        reasons.append(
            CapabilityReason(
                code="tooth-local-frame-unavailable",
                message=(
                    "Trusted tooth-local frames are not available in the current Dental3D contract; "
                    "tip, torque and long-axis rotation are not rendered."
                ),
            )
        )

        return SimulatorCapability(
            patient_id=patient_id,
            whole_arch_mesh_count=len(scene.meshes),
            per_tooth_mesh_count=len(per_tooth),
            reviewed_per_tooth_mesh_count=reviewed_count,
            accepted_alignment=accepted_alignment,
            translation_eligible=translation_eligible,
            rotation_eligible=rotation_eligible,
            reasons=tuple(reasons),
        )

    @staticmethod
    async def simulate(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        request: SimulationRequest,
    ) -> SimulationResponse:
        scene = await DentalSceneService.get_for_patient(db, clinic_id, patient_id)
        alignment = await DentalAlignmentService.latest_alignment(db, clinic_id, patient_id)
        capability = await OrthodonticSimulatorService.capability(db, clinic_id, patient_id)

        if not capability.translation_eligible:
            raise SimulatorSafetyError(
                "Patient-specific translation is unavailable until reviewed per-tooth geometry "
                "and an accepted millimetre coordinate frame are present."
            )
        if any(item.has_rotation for item in request.movements) and not capability.rotation_eligible:
            raise SimulatorSafetyError(
                "Tip, torque and rotation require a trusted tooth-local frame; none is available."
            )
        if alignment is None or alignment.source_frame is None or alignment.provenance is None:
            raise SimulatorSafetyError("Accepted source frame provenance is unavailable.")

        per_tooth = {tooth.tooth_number: tooth for tooth in _per_tooth_meshes(scene)}
        source_frame = CoordinateFrame(
            id=alignment.source_frame.id,
            unit="mm",
            scale_verified=True,
            trusted=True,
        )
        source_digest = alignment.provenance.ios.digest

        geometry: list[ToothGeometryRef] = []
        authored: list[ToothDelta] = []
        for movement in request.movements:
            number = int(movement.tooth.value)
            tooth = per_tooth.get(number)
            if tooth is None or tooth.mesh.document_id is None:
                raise SimulatorSafetyError(
                    f"FDI {movement.tooth.value} has no reviewed per-tooth patient geometry."
                )
            geometry.append(
                ToothGeometryRef(
                    tooth=movement.tooth,
                    document_id=str(tooth.mesh.document_id),
                    source_digest=source_digest,
                    frame=source_frame,
                    reviewed=True,
                    per_tooth=True,
                    trusted_tooth_local_frame=False,
                )
            )
            authored.append(
                ToothDelta(
                    tooth=movement.tooth,
                    translate_x_mm=movement.translate_x_mm,
                    translate_y_mm=movement.translate_y_mm,
                    translate_z_mm=movement.translate_z_mm,
                    rotate_tip_deg=movement.rotate_tip_deg,
                    rotate_torque_deg=movement.rotate_torque_deg,
                    rotate_rotation_deg=movement.rotate_rotation_deg,
                    coordinate_frame=source_frame.id,
                )
            )

        stages = stage_movements(tuple(authored), request.caps)
        plan = SimulationPlan(geometry=tuple(geometry), stages=stages, caps=request.caps)
        return SimulationResponse(capability=capability, result=simulate(plan))
