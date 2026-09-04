"""Orthodontic planning FastAPI router.

Mounted at ``/api/v1/orthodontic_planning/`` by the module loader.

Endpoints (all gated by module RBAC):

* ``GET    /capabilities``                          — provider + safety-envelope info
* ``POST   /patients/{patient_id}/assessments``     — record measurements
* ``GET    /patients/{patient_id}/assessments``     — history
* ``GET    /assessments/{assessment_id}``           — detail incl. snapshot/sufficiency
* ``POST   /assessments/{assessment_id}/plan``      — run planner → draft proposal
* ``GET    /patients/{patient_id}/proposals``       — history
* ``GET    /proposals/{proposal_id}``               — detail incl. safety report
* ``POST   /proposals/{proposal_id}/review``        — clinician approve/reject
* ``DELETE /proposals/{proposal_id}``               — remove a proposal

Error contract: 404 unknown/unscoped entities · 409 already reviewed ·
422 insufficient case data OR safety refusal (refusal body carries the
deterministic report) · 503 provider unavailable.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .constants import CONSTRAINTS_VERSION, REQUIRED_MEASUREMENTS, STAGE_INTERVAL_WEEKS
from .domain import InsufficientDataError
from .planner import get_provider
from .planner.base import ProviderUnavailableError
from .schemas import (
    CAPABILITIES_ENVELOPES,
    MIN_CHARTED_PERMANENT_TEETH,
    MOVEMENT_LIMITS,
    AssessmentCreate,
    AssessmentDetail,
    AssessmentSummary,
    CapabilitiesResponse,
    ConstraintReportDTO,
    ConstraintViolationDTO,
    MovementDTO,
    PlanCreate,
    ProposalDetail,
    ProposalReview,
    ProposalReviewResponse,
    ProposalSummary,
    StageDTO,
    assessment_detail,
    assessment_summary,
)
from .service import (
    OrthodonticPlanningService,
    PlanningRefusedError,
    ProviderFailureError,
)

router = APIRouter()


def _proposal_detail(p) -> ProposalDetail:
    stages_payload = (p.stages or {}).get("stages", [])
    report = p.constraint_report or {}
    return ProposalDetail(
        id=p.id,
        patient_id=p.patient_id,
        assessment_id=p.assessment_id,
        provider=p.provider,
        provider_version=p.provider_version,
        constraints_version=p.constraints_version,
        status=p.status,
        stage_count=p.stage_count,
        planned_months=p.planned_months,
        score=p.score,
        confidence=p.confidence,
        hard_violation_count=int(report.get("hard_count", 0)),
        soft_finding_count=int(report.get("soft_count", 0)),
        created_at=p.created_at,
        stages=[
            StageDTO(
                label=s.get("label", ""),
                movements=[MovementDTO(**m) for m in s.get("movements", [])],
            )
            for s in stages_payload
        ],
        constraint_report=ConstraintReportDTO(
            is_valid=bool(report.get("is_valid", False)),
            hard_count=int(report.get("hard_count", 0)),
            soft_count=int(report.get("soft_count", 0)),
            violations=[ConstraintViolationDTO(**v) for v in report.get("violations", [])],
        ),
        uncertainty=p.uncertainty or [],
        rationale=p.rationale,
        reviewed_by=p.reviewed_by,
        reviewed_at=p.reviewed_at,
        review_note=p.review_note,
        created_by=p.created_by,
    )


@router.get("/capabilities", response_model=ApiResponse[CapabilitiesResponse])
async def get_capabilities(
    _ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    __: Annotated[None, Depends(require_permission("orthodontic_planning.read"))],
) -> ApiResponse[CapabilitiesResponse]:
    """Advertise the planning provider and the deterministic envelope."""
    try:
        provider = get_provider()
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return ApiResponse(
        data=CapabilitiesResponse(
            provider=provider.name,
            provider_version=provider.version,
            constraints_version=CONSTRAINTS_VERSION,
            decision_support_only=True,
            deterministic=True,
            approval_required=True,
            planned_months_per_stage_weeks=STAGE_INTERVAL_WEEKS,
            required_measurements=list(REQUIRED_MEASUREMENTS),
            min_charted_permanent_teeth=MIN_CHARTED_PERMANENT_TEETH,
            movement_limits=MOVEMENT_LIMITS,
            envelopes=CAPABILITIES_ENVELOPES,
        )
    )


@router.post(
    "/patients/{patient_id}/assessments",
    response_model=ApiResponse[AssessmentDetail],
    status_code=status.HTTP_201_CREATED,
)
async def create_assessment(
    patient_id: UUID,
    payload: AssessmentCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("orthodontic_planning.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AssessmentDetail]:
    service = OrthodonticPlanningService(db)
    if not await service.get_patient(ctx.clinic_id, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    assessment = await service.create_assessment(
        clinic_id=ctx.clinic_id,
        patient_id=patient_id,
        created_by=ctx.user_id,
        payload=payload,
    )
    return ApiResponse(data=assessment_detail(assessment))


@router.get(
    "/patients/{patient_id}/assessments",
    response_model=ApiResponse[list[AssessmentSummary]],
)
async def list_assessments(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("orthodontic_planning.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[AssessmentSummary]]:
    service = OrthodonticPlanningService(db)
    if not await service.get_patient(ctx.clinic_id, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    assessments = await service.list_assessments(ctx.clinic_id, patient_id)
    return ApiResponse(data=[assessment_summary(a) for a in assessments])


@router.get("/assessments/{assessment_id}", response_model=ApiResponse[AssessmentDetail])
async def get_assessment(
    assessment_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("orthodontic_planning.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AssessmentDetail]:
    service = OrthodonticPlanningService(db)
    assessment = await service.get_assessment(ctx.clinic_id, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return ApiResponse(data=assessment_detail(assessment))


@router.post(
    "/assessments/{assessment_id}/plan",
    response_model=ApiResponse[ProposalDetail],
    status_code=status.HTTP_201_CREATED,
)
async def generate_plan(
    assessment_id: UUID,
    payload: PlanCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("orthodontic_planning.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ProposalDetail]:
    service = OrthodonticPlanningService(db)
    assessment = await service.get_assessment(ctx.clinic_id, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    try:
        proposal = await service.generate_proposal(
            clinic_id=ctx.clinic_id,
            patient_id=assessment.patient_id,
            assessment_id=assessment_id,
            created_by=ctx.user_id,
        )
    except InsufficientDataError as exc:
        raise HTTPException(
            status_code=422,
            detail=("Case data insufficient for planning — missing: " + ", ".join(exc.missing)),
        )
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ProviderFailureError as exc:
        raise HTTPException(status_code=503, detail=f"Planning provider failed: {exc}")
    except PlanningRefusedError as exc:
        findings = "; ".join(f"{v.code}: {v.message}" for v in exc.report.hard)
        raise HTTPException(
            status_code=422,
            detail=(
                "Planner output refused by the deterministic safety gate "
                f"({findings}). The refused plan was not saved."
            ),
        )
    return ApiResponse(data=_proposal_detail(proposal))


@router.get(
    "/patients/{patient_id}/proposals",
    response_model=ApiResponse[list[ProposalSummary]],
)
async def list_proposals(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("orthodontic_planning.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[ProposalSummary]]:
    service = OrthodonticPlanningService(db)
    if not await service.get_patient(ctx.clinic_id, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    proposals = await service.list_proposals(ctx.clinic_id, patient_id)
    summaries = []
    for p in proposals:
        report = p.constraint_report or {}
        summaries.append(
            ProposalSummary(
                id=p.id,
                patient_id=p.patient_id,
                assessment_id=p.assessment_id,
                provider=p.provider,
                provider_version=p.provider_version,
                constraints_version=p.constraints_version,
                status=p.status,
                stage_count=p.stage_count,
                planned_months=p.planned_months,
                score=p.score,
                confidence=p.confidence,
                hard_violation_count=int(report.get("hard_count", 0)),
                soft_finding_count=int(report.get("soft_count", 0)),
                created_at=p.created_at,
            )
        )
    return ApiResponse(data=summaries)


@router.get("/proposals/{proposal_id}", response_model=ApiResponse[ProposalDetail])
async def get_proposal(
    proposal_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("orthodontic_planning.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ProposalDetail]:
    service = OrthodonticPlanningService(db)
    proposal = await service.get_proposal(ctx.clinic_id, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return ApiResponse(data=_proposal_detail(proposal))


@router.post("/proposals/{proposal_id}/review", response_model=ApiResponse[ProposalReviewResponse])
async def review_proposal(
    proposal_id: UUID,
    payload: ProposalReview,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("orthodontic_planning.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ProposalReviewResponse]:
    service = OrthodonticPlanningService(db)
    try:
        proposal = await service.review_proposal(
            clinic_id=ctx.clinic_id,
            proposal_id=proposal_id,
            reviewed_by=ctx.user_id,
            decision=payload.decision,
            note=payload.note,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Proposal not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return ApiResponse(
        data=ProposalReviewResponse(
            id=proposal.id,
            status=proposal.status,
            reviewed_by=proposal.reviewed_by,
            reviewed_at=proposal.reviewed_at,
            review_note=proposal.review_note,
        )
    )


@router.delete("/proposals/{proposal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proposal(
    proposal_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("orthodontic_planning.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    service = OrthodonticPlanningService(db)
    try:
        await service.delete_proposal(ctx.clinic_id, proposal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Proposal not found")
