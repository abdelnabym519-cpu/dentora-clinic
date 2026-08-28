"""Application service for patient-specific rigid registration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DentalAlignmentResult as AlignmentRow
from .registration import (
    AlignmentFailure,
    AlignmentFailureCode,
    AlignmentResult,
    AlignmentReviewUpdate,
    AlignmentRunRequest,
    CoordinateFrame,
    DentalAnatomyPort,
    RegistrationGeometry,
    RegistrationInputPort,
    RegistrationMetrics,
    RegistrationPort,
    RegistrationProvenance,
    RigidTransform,
)


class AlignmentError(Exception):
    """Application conflict mapped by the presentation layer."""


class DentalAlignmentService:
    @staticmethod
    async def _latest_row(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> AlignmentRow | None:
        stmt = (
            select(AlignmentRow)
            .where(
                AlignmentRow.clinic_id == clinic_id,
                AlignmentRow.patient_id == patient_id,
            )
            .order_by(AlignmentRow.created_at.desc(), AlignmentRow.id.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _to_response(row: AlignmentRow) -> AlignmentResult:
        return AlignmentResult(
            id=row.id,
            patient_id=row.patient_id,
            status=row.status,
            transform=(RigidTransform.model_validate(row.transform) if row.transform else None),
            source_frame=(
                CoordinateFrame.model_validate(row.source_frame) if row.source_frame else None
            ),
            target_frame=(
                CoordinateFrame.model_validate(row.target_frame) if row.target_frame else None
            ),
            algorithm=row.algorithm,
            algorithm_version=row.algorithm_version,
            provenance=(
                RegistrationProvenance.model_validate(row.provenance) if row.provenance else None
            ),
            metrics=(RegistrationMetrics.model_validate(row.metrics) if row.metrics else None),
            failure=(
                AlignmentFailure(code=row.failure_code, message=row.failure_message)
                if row.failure_code and row.failure_message
                else None
            ),
            performed_at=row.performed_at,
            created_at=row.created_at,
            reviewed_by=row.reviewed_by,
            reviewed_at=row.reviewed_at,
            review_note=row.review_note,
            requires_review=row.status != "failed",
        )

    @staticmethod
    async def _persist(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
        result: AlignmentResult,
    ) -> AlignmentResult:
        row = AlignmentRow(
            clinic_id=clinic_id,
            patient_id=patient_id,
            performed_by=user_id,
            status=result.status,
            algorithm=result.algorithm,
            algorithm_version=result.algorithm_version,
            transform=result.transform.model_dump(mode="json") if result.transform else None,
            source_frame=(
                result.source_frame.model_dump(mode="json") if result.source_frame else None
            ),
            target_frame=(
                result.target_frame.model_dump(mode="json") if result.target_frame else None
            ),
            provenance=(result.provenance.model_dump(mode="json") if result.provenance else None),
            metrics=result.metrics.model_dump(mode="json") if result.metrics else None,
            failure_code=result.failure.code.value if result.failure else None,
            failure_message=result.failure.message if result.failure else None,
            performed_at=result.performed_at,
        )
        db.add(row)
        await db.commit()
        return DentalAlignmentService._to_response(row)

    @staticmethod
    async def run_alignment(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
        request: AlignmentRunRequest,
        input_port: RegistrationInputPort | None = None,
        anatomy_port: DentalAnatomyPort | None = None,
        registration_port: RegistrationPort | None = None,
    ) -> AlignmentResult:
        performed_at = datetime.now(UTC)
        if input_port is None or anatomy_port is None or registration_port is None:
            from .registration_infrastructure import default_registration_components

            defaults = default_registration_components(db)
            input_port = input_port or defaults[0]
            anatomy_port = anatomy_port or defaults[1]
            registration_port = registration_port or defaults[2]

        try:
            prepared = await input_port.prepare(
                clinic_id=clinic_id,
                patient_id=patient_id,
                request=request,
            )
            anatomy = await anatomy_port.extract(prepared.cbct)
            geometry = RegistrationGeometry(
                patient_id=patient_id,
                mesh_document_id=prepared.mesh_document_id,
                mesh_format=prepared.mesh_format,
                mesh_bytes=prepared.mesh_bytes,
                ios_units=prepared.ios_units,
                ios_digest=prepared.ios_digest,
                cbct=prepared.cbct,
                anatomy=anatomy,
            )
            result = await asyncio.to_thread(registration_port.register, geometry, performed_at)
        except Exception as exc:
            from .registration_infrastructure import (
                RegistrationAdapterError,
                failed_alignment,
            )

            if isinstance(exc, RegistrationAdapterError):
                code, message = exc.code, exc.safe_message
            elif isinstance(exc, ValidationError):
                code, message = (
                    AlignmentFailureCode.INVALID_GEOMETRY,
                    "Patient registration geometry or transform is invalid",
                )
            else:
                code, message = (
                    AlignmentFailureCode.REGISTRATION_FAILED,
                    "Patient-specific registration failed unexpectedly",
                )
            result = failed_alignment(
                patient_id=patient_id,
                performed_at=performed_at,
                code=code,
                message=message,
            )
        return await DentalAlignmentService._persist(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
            result=result,
        )

    @staticmethod
    async def latest_alignment(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> AlignmentResult | None:
        row = await DentalAlignmentService._latest_row(db, clinic_id, patient_id)
        return None if row is None else DentalAlignmentService._to_response(row)

    @staticmethod
    async def review_alignment(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        alignment_id: UUID,
        reviewer_id: UUID | None,
        payload: AlignmentReviewUpdate,
    ) -> AlignmentResult:
        stmt = select(AlignmentRow).where(
            AlignmentRow.id == alignment_id,
            AlignmentRow.clinic_id == clinic_id,
            AlignmentRow.patient_id == patient_id,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise KeyError(alignment_id)
        if row.status not in {"pending_review", "uncertain"}:
            raise AlignmentError("alignment is not pending dentist review")
        if not row.transform:
            raise AlignmentError("alignment has no transform to review")
        row.status = payload.decision
        row.reviewed_by = reviewer_id
        row.reviewed_at = datetime.now(UTC)
        row.review_note = payload.note
        await db.commit()
        return DentalAlignmentService._to_response(row)


__all__ = ["AlignmentError", "DentalAlignmentService"]
