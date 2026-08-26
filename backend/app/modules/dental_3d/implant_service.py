"""Application service for deterministic patient-space implant planning."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .implant_models import (
    DentalImplantPlan as ImplantPlanRow,
)
from .implant_models import (
    DentalImplantPlanRevision as ImplantRevisionRow,
)
from .implant_models import (
    DentalProstheticTarget as ProstheticTargetRow,
)
from .implant_planning import (
    DentalImplantPlanResponse,
    ImplantAssessment,
    ImplantCandidate,
    ImplantPlanCreate,
    ImplantPlanEdit,
    ImplantPlanningSnapshot,
    ImplantPlanRevisionResponse,
    ImplantProposalRequest,
    PlanningCase,
    PlanningPolicy,
    ProstheticPlanning,
    ProstheticTargetCreate,
    ProstheticTargetResponse,
    ProstheticTargetReviewUpdate,
    assess_candidate,
    candidate_from_target,
    rank_candidates,
)
from .models import DentalNerveAnalysis as NerveRow
from .nerve import NervePathway
from .registration import AlignmentResult, Point3D
from .registration_service import DentalAlignmentService


class ImplantPlanningError(Exception):
    """Application conflict mapped to a safe HTTP 409/422 by the router."""


class DentalImplantPlanningService:
    @staticmethod
    async def _accepted_alignment(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> AlignmentResult:
        alignment = await DentalAlignmentService.latest_alignment(db, clinic_id, patient_id)
        if (
            alignment is None
            or alignment.status != "accepted"
            or alignment.id is None
            or alignment.target_frame is None
            or alignment.target_frame.kind != "dicom_patient"
            or alignment.target_frame.unit != "mm"
            or not alignment.target_frame.frame_of_reference_uid
        ):
            raise ImplantPlanningError(
                "accepted patient-specific IOS-to-CBCT alignment is required"
            )
        return alignment

    @staticmethod
    async def _latest_target_row(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> ProstheticTargetRow | None:
        stmt = (
            select(ProstheticTargetRow)
            .where(
                ProstheticTargetRow.clinic_id == clinic_id,
                ProstheticTargetRow.patient_id == patient_id,
            )
            .order_by(ProstheticTargetRow.created_at.desc(), ProstheticTargetRow.id.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _target_response(row: ProstheticTargetRow) -> ProstheticTargetResponse:
        return ProstheticTargetResponse(
            id=row.id,
            patient_id=row.patient_id,
            alignment_id=row.alignment_id,
            platform_center=row.platform_center,
            axis=row.axis,
            frame_of_reference_uid=row.frame_of_reference_uid,
            source_type=row.source_type,
            source_reference_space=row.source_reference_space,
            source_frame_of_reference_uid=row.source_frame_of_reference_uid,
            source_method=row.source_method,
            source_identifier=row.source_identifier,
            source_digest=row.source_digest,
            source_document_ids=row.source_document_ids or [],
            review_status=row.review_status,
            created_by=row.created_by,
            created_at=row.created_at,
            reviewed_by=row.reviewed_by,
            reviewed_at=row.reviewed_at,
            review_note=row.review_note,
        )

    @staticmethod
    def _validate_target_against_alignment(
        payload: ProstheticTargetCreate,
        alignment: AlignmentResult,
    ) -> None:
        assert alignment.id is not None
        assert alignment.target_frame is not None
        frame_uid = alignment.target_frame.frame_of_reference_uid
        if payload.alignment_id != alignment.id:
            raise ImplantPlanningError("prosthetic target is tied to a stale alignment")
        if payload.frame_of_reference_uid != frame_uid:
            raise ImplantPlanningError(
                "prosthetic target does not match the accepted patient frame"
            )

        if payload.source_reference_space == "ios_mesh":
            ios = alignment.provenance.ios if alignment.provenance else None
            if ios is None:
                raise ImplantPlanningError("accepted alignment has no IOS provenance")
            if payload.source_digest != ios.digest:
                raise ImplantPlanningError("prosthetic IOS source digest does not match alignment")
            covered = set(ios.document_ids)
            if not payload.source_document_ids or not set(payload.source_document_ids).issubset(
                covered
            ):
                raise ImplantPlanningError(
                    "prosthetic IOS source documents are not covered by accepted alignment"
                )
        elif (
            payload.source_type != "dentist_defined"
            and payload.source_frame_of_reference_uid != frame_uid
        ):
            raise ImplantPlanningError("prosthetic DICOM source frame does not match alignment")

    @staticmethod
    async def create_prosthetic_target(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
        payload: ProstheticTargetCreate,
    ) -> ProstheticTargetResponse:
        alignment = await DentalImplantPlanningService._accepted_alignment(
            db, clinic_id, patient_id
        )
        DentalImplantPlanningService._validate_target_against_alignment(payload, alignment)
        row = ProstheticTargetRow(
            clinic_id=clinic_id,
            patient_id=patient_id,
            alignment_id=payload.alignment_id,
            created_by=user_id,
            platform_center=payload.platform_center.model_dump(mode="json"),
            axis=payload.axis.model_dump(mode="json"),
            frame_of_reference_uid=payload.frame_of_reference_uid,
            source_type=payload.source_type,
            source_reference_space=payload.source_reference_space,
            source_frame_of_reference_uid=payload.source_frame_of_reference_uid,
            source_method=payload.source_method,
            source_identifier=payload.source_identifier,
            source_digest=payload.source_digest,
            source_document_ids=[str(value) for value in payload.source_document_ids],
            review_status="pending_review",
        )
        db.add(row)
        await db.commit()
        return DentalImplantPlanningService._target_response(row)

    @staticmethod
    async def review_prosthetic_target(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        target_id: UUID,
        reviewer_id: UUID | None,
        payload: ProstheticTargetReviewUpdate,
    ) -> ProstheticTargetResponse:
        stmt = select(ProstheticTargetRow).where(
            ProstheticTargetRow.id == target_id,
            ProstheticTargetRow.clinic_id == clinic_id,
            ProstheticTargetRow.patient_id == patient_id,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise KeyError(target_id)
        if row.review_status != "pending_review":
            raise ImplantPlanningError("prosthetic target is not pending dentist review")

        alignment = await DentalImplantPlanningService._accepted_alignment(
            db, clinic_id, patient_id
        )
        if row.alignment_id != alignment.id:
            raise ImplantPlanningError("prosthetic target is tied to a stale alignment")

        row.review_status = payload.decision
        row.reviewed_by = reviewer_id
        row.reviewed_at = datetime.now(UTC)
        row.review_note = payload.note
        await db.commit()
        return DentalImplantPlanningService._target_response(row)

    @staticmethod
    async def prosthetic_planning(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> ProstheticPlanning:
        row = await DentalImplantPlanningService._latest_target_row(db, clinic_id, patient_id)
        if row is None or row.review_status != "accepted":
            return ProstheticPlanning(
                status="unavailable",
                reason="No accepted prosthetic target is available",
            )
        try:
            alignment = await DentalImplantPlanningService._accepted_alignment(
                db, clinic_id, patient_id
            )
        except ImplantPlanningError:
            return ProstheticPlanning(
                status="unavailable",
                reason="Accepted prosthetic target is stale because patient alignment changed",
            )
        if row.alignment_id != alignment.id:
            return ProstheticPlanning(
                status="unavailable",
                reason="Accepted prosthetic target is stale because patient alignment changed",
            )
        return ProstheticPlanning(
            status="available",
            target=DentalImplantPlanningService._target_response(row),
        )

    @staticmethod
    async def _accepted_nerve(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        frame_uid: str,
    ) -> tuple[UUID | None, list[list[Point3D]]]:
        stmt = (
            select(NerveRow)
            .where(
                NerveRow.clinic_id == clinic_id,
                NerveRow.patient_id == patient_id,
                NerveRow.review_status == "accepted",
                NerveRow.detection_status.in_(("detected", "uncertain")),
                NerveRow.input_kind == "cbct_series",
            )
            .order_by(NerveRow.created_at.desc(), NerveRow.id.desc())
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None, []

        pathways: list[list[Point3D]] = []
        for raw in row.pathways or []:
            try:
                pathway = NervePathway.model_validate(raw)
            except ValueError:
                continue
            reference = pathway.reference_space
            if (
                pathway.source != "model_inference"
                or reference.kind != "dicom_patient"
                or reference.unit != "mm"
                or reference.frame_of_reference_uid != frame_uid
            ):
                continue
            pathways.append([Point3D(x=point.x, y=point.y, z=point.z) for point in pathway.points])
        return (row.id if pathways else None), pathways

    @staticmethod
    async def _case_and_assessment(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        candidate: ImplantCandidate,
    ) -> tuple[PlanningCase, ImplantAssessment]:
        alignment = await DentalImplantPlanningService._accepted_alignment(
            db, clinic_id, patient_id
        )
        assert alignment.id is not None
        assert alignment.target_frame is not None
        frame_uid = alignment.target_frame.frame_of_reference_uid
        assert frame_uid is not None
        if candidate.frame_of_reference_uid != frame_uid:
            raise ImplantPlanningError("implant candidate does not match accepted patient frame")

        prosthetic = await DentalImplantPlanningService.prosthetic_planning(
            db, clinic_id, patient_id
        )
        target = prosthetic.target if prosthetic.status == "available" else None
        nerve_id, pathways = await DentalImplantPlanningService._accepted_nerve(
            db, clinic_id, patient_id, frame_uid
        )
        assessment = assess_candidate(candidate, target=target, nerve_pathways=pathways)
        planning_case = PlanningCase(
            frame_of_reference_uid=frame_uid,
            alignment_id=alignment.id,
            prosthetic_target_id=target.id if target else None,
            prosthetic_status="accepted" if target else "unavailable",
            nerve_analysis_id=nerve_id,
            bone_volume_status="UNAVAILABLE",
        )
        return planning_case, assessment

    @staticmethod
    async def _revision_row(
        db: AsyncSession,
        plan: ImplantPlanRow,
    ) -> ImplantRevisionRow:
        stmt = select(ImplantRevisionRow).where(
            ImplantRevisionRow.plan_id == plan.id,
            ImplantRevisionRow.revision_number == plan.current_revision_number,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ImplantPlanningError("implant plan revision is missing")
        return row

    @staticmethod
    def _revision_response(row: ImplantRevisionRow) -> ImplantPlanRevisionResponse:
        return ImplantPlanRevisionResponse(
            id=row.id,
            plan_id=row.plan_id,
            revision_number=row.revision_number,
            candidate=ImplantCandidate.model_validate(row.candidate),
            assessment=ImplantAssessment.model_validate(row.assessment),
            planning_case=PlanningCase.model_validate(row.planning_case),
            policy=PlanningPolicy.model_validate(row.policy) if row.policy else None,
            created_by=row.created_by,
            created_at=row.created_at,
        )

    @staticmethod
    async def _plan_response(
        db: AsyncSession,
        row: ImplantPlanRow,
    ) -> DentalImplantPlanResponse:
        revision = await DentalImplantPlanningService._revision_row(db, row)
        return DentalImplantPlanResponse(
            id=row.id,
            patient_id=row.patient_id,
            status=row.status,
            current_revision=DentalImplantPlanningService._revision_response(revision),
            created_by=row.created_by,
            created_at=row.created_at,
            reviewed_by=row.reviewed_by,
            reviewed_at=row.reviewed_at,
            review_note=row.review_note,
        )

    @staticmethod
    async def _insert_plan(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
        candidate: ImplantCandidate,
        status: str,
        policy: PlanningPolicy | None,
    ) -> DentalImplantPlanResponse:
        planning_case, assessment = await DentalImplantPlanningService._case_and_assessment(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            candidate=candidate,
        )
        plan = ImplantPlanRow(
            clinic_id=clinic_id,
            patient_id=patient_id,
            created_by=user_id,
            status=status,
            current_revision_number=1,
        )
        db.add(plan)
        await db.flush()
        revision = ImplantRevisionRow(
            plan_id=plan.id,
            clinic_id=clinic_id,
            patient_id=patient_id,
            revision_number=1,
            candidate=candidate.model_dump(mode="json"),
            assessment=assessment.model_dump(mode="json"),
            planning_case=planning_case.model_dump(mode="json"),
            policy=policy.model_dump(mode="json") if policy else None,
            created_by=user_id,
            created_at=datetime.now(UTC),
        )
        db.add(revision)
        await db.commit()
        return await DentalImplantPlanningService._plan_response(db, plan)

    @staticmethod
    async def create_manual_plan(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
        payload: ImplantPlanCreate,
    ) -> DentalImplantPlanResponse:
        return await DentalImplantPlanningService._insert_plan(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
            candidate=payload.candidate,
            status="draft",
            policy=None,
        )

    @staticmethod
    async def create_proposal(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
        payload: ImplantProposalRequest,
    ) -> DentalImplantPlanResponse:
        prosthetic = await DentalImplantPlanningService.prosthetic_planning(
            db, clinic_id, patient_id
        )
        if prosthetic.status != "available" or prosthetic.target is None:
            raise ImplantPlanningError(
                "deterministic proposal generation requires an accepted prosthetic target"
            )

        candidates: list[tuple[ImplantCandidate, ImplantAssessment]] = []
        for entry in payload.catalog:
            candidate = candidate_from_target(prosthetic.target, entry)
            _, assessment = await DentalImplantPlanningService._case_and_assessment(
                db,
                clinic_id=clinic_id,
                patient_id=patient_id,
                candidate=candidate,
            )
            candidates.append((candidate, assessment))
        ranked = rank_candidates(candidates, payload.policy)
        candidate, _ = ranked[0]
        return await DentalImplantPlanningService._insert_plan(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
            candidate=candidate,
            status="proposed",
            policy=payload.policy,
        )

    @staticmethod
    async def _plan_row(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        plan_id: UUID,
    ) -> ImplantPlanRow:
        stmt = select(ImplantPlanRow).where(
            ImplantPlanRow.id == plan_id,
            ImplantPlanRow.clinic_id == clinic_id,
            ImplantPlanRow.patient_id == patient_id,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise KeyError(plan_id)
        return row

    @staticmethod
    async def edit_plan(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        plan_id: UUID,
        user_id: UUID | None,
        payload: ImplantPlanEdit,
    ) -> DentalImplantPlanResponse:
        plan = await DentalImplantPlanningService._plan_row(db, clinic_id, patient_id, plan_id)
        planning_case, assessment = await DentalImplantPlanningService._case_and_assessment(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            candidate=payload.candidate,
        )
        next_revision = plan.current_revision_number + 1
        db.add(
            ImplantRevisionRow(
                plan_id=plan.id,
                clinic_id=clinic_id,
                patient_id=patient_id,
                revision_number=next_revision,
                candidate=payload.candidate.model_dump(mode="json"),
                assessment=assessment.model_dump(mode="json"),
                planning_case=planning_case.model_dump(mode="json"),
                policy=None,
                created_by=user_id,
                created_at=datetime.now(UTC),
            )
        )
        plan.current_revision_number = next_revision
        plan.status = "draft"
        plan.reviewed_by = None
        plan.reviewed_at = None
        plan.review_note = None
        await db.commit()
        return await DentalImplantPlanningService._plan_response(db, plan)

    @staticmethod
    async def review_plan(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        plan_id: UUID,
        reviewer_id: UUID | None,
        decision: str,
        note: str | None,
    ) -> DentalImplantPlanResponse:
        plan = await DentalImplantPlanningService._plan_row(db, clinic_id, patient_id, plan_id)
        if plan.status not in {"draft", "proposed"}:
            raise ImplantPlanningError("implant plan is not pending dentist review")
        if decision == "accepted":
            prosthetic = await DentalImplantPlanningService.prosthetic_planning(
                db, clinic_id, patient_id
            )
            if prosthetic.status != "available" or prosthetic.target is None:
                raise ImplantPlanningError(
                    "plan acceptance requires a current accepted prosthetic target"
                )
            revision = await DentalImplantPlanningService._revision_row(db, plan)
            case = PlanningCase.model_validate(revision.planning_case)
            if case.prosthetic_target_id != prosthetic.target.id:
                raise ImplantPlanningError(
                    "plan revision is stale because the accepted prosthetic target changed"
                )
        plan.status = decision
        plan.reviewed_by = reviewer_id
        plan.reviewed_at = datetime.now(UTC)
        plan.review_note = note
        await db.commit()
        return await DentalImplantPlanningService._plan_response(db, plan)

    @staticmethod
    async def list_plans(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> list[DentalImplantPlanResponse]:
        stmt = (
            select(ImplantPlanRow)
            .where(
                ImplantPlanRow.clinic_id == clinic_id,
                ImplantPlanRow.patient_id == patient_id,
            )
            .order_by(ImplantPlanRow.created_at.desc(), ImplantPlanRow.id.desc())
        )
        rows = list((await db.execute(stmt)).scalars().all())
        return [await DentalImplantPlanningService._plan_response(db, row) for row in rows]

    @staticmethod
    async def snapshot(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> ImplantPlanningSnapshot:
        target_row = await DentalImplantPlanningService._latest_target_row(
            db, clinic_id, patient_id
        )
        return ImplantPlanningSnapshot(
            prosthetic=await DentalImplantPlanningService.prosthetic_planning(
                db, clinic_id, patient_id
            ),
            latest_target=(
                DentalImplantPlanningService._target_response(target_row)
                if target_row is not None
                else None
            ),
            plans=await DentalImplantPlanningService.list_plans(db, clinic_id, patient_id),
        )


__all__ = ["DentalImplantPlanningService", "ImplantPlanningError"]
