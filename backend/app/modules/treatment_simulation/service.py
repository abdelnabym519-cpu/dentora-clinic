"""Treatment Simulation application service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_treatment_planning.contracts import ReviewStatus
from app.modules.ai_treatment_planning.service import AITreatmentPlanningService
from app.modules.case_intelligence.contracts import digest_value
from app.modules.case_intelligence.service import CaseIntelligenceService
from app.modules.risk_engine.contracts import RISK_ENGINE_VERSION, RISK_POLICY_VERSION
from app.modules.risk_engine.engine import evaluate_snapshot

from .contracts import (
    TREATMENT_SIMULATION_CONTRACT_VERSION,
    TREATMENT_SIMULATION_ENGINE_VERSION,
    DigitalTwinScene,
    SimulationProvenance,
    TreatmentSimulationResult,
)
from .models import TreatmentSimulationRecord
from .ports import PlanningArtifactReaderPort, SimulationRepositoryPort
from .repository import SqlAlchemyPlanningArtifactReader, SqlAlchemySimulationRepository
from .simulator import SimulationBuildError, build_digital_twin_scene


class TreatmentSimulationService:
    @classmethod
    async def generate(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        planning_id: UUID,
        option_id: str,
        user_id: UUID | None,
        repository: SimulationRepositoryPort | None = None,
        planning_reader: PlanningArtifactReaderPort | None = None,
    ) -> TreatmentSimulationResult:
        repository = repository or SqlAlchemySimulationRepository(db)
        planning_reader = planning_reader or SqlAlchemyPlanningArtifactReader(db)

        plan_row = await planning_reader.get(
            clinic_id=clinic_id,
            patient_id=patient_id,
            planning_id=planning_id,
        )
        if plan_row is None:
            raise KeyError("planning_not_found")
        if plan_row.review_status != ReviewStatus.ACCEPTED.value:
            raise PermissionError("accepted_treatment_planning_required")
        if plan_row.reviewed_at is None or plan_row.reviewed_by is None:
            raise ValueError("accepted_planning_missing_review_provenance")

        snapshot = await CaseIntelligenceService.get_current(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
        )
        risk_evaluation = evaluate_snapshot(snapshot)
        cls._assert_current_evidence(
            plan_row=plan_row, snapshot=snapshot, risk_evaluation=risk_evaluation
        )

        planning = AITreatmentPlanningService._to_contract(plan_row)
        scene = build_digital_twin_scene(
            snapshot=snapshot,
            risk_evaluation=risk_evaluation,
            planning=planning,
            option_id=option_id,
        )
        input_digest = digest_value(
            {
                "contract_version": TREATMENT_SIMULATION_CONTRACT_VERSION,
                "engine_version": TREATMENT_SIMULATION_ENGINE_VERSION,
                "patient_id": str(patient_id),
                "planning_id": str(plan_row.id),
                "planning_version": plan_row.planning_version,
                "planning_output_digest": plan_row.output_digest,
                "planning_review_status": plan_row.review_status,
                "planning_reviewed_at": plan_row.reviewed_at,
                "planning_reviewed_by": str(plan_row.reviewed_by),
                "option_id": option_id,
                "case_snapshot_version": snapshot.case_snapshot_version,
                "case_source_digest": snapshot.source_digest,
                "risk_input_digest": risk_evaluation.input_digest,
                "risk_result_digest": risk_evaluation.result_digest,
                "reference_frame": snapshot.reference_frame.model_dump(mode="json"),
            }
        )
        cached = await repository.get_by_input_digest(
            clinic_id=clinic_id,
            patient_id=patient_id,
            input_digest=input_digest,
        )
        if cached is not None:
            return cls._to_contract(cached)

        output_digest = digest_value(scene.model_dump(mode="json"))
        version = await repository.reserve_next_version(
            clinic_id=clinic_id,
            patient_id=patient_id,
        )
        if version is None:
            raise KeyError("patient_not_found")
        row = TreatmentSimulationRecord(
            clinic_id=clinic_id,
            patient_id=patient_id,
            simulation_version=version,
            contract_version=TREATMENT_SIMULATION_CONTRACT_VERSION,
            engine_version=TREATMENT_SIMULATION_ENGINE_VERSION,
            planning_id=plan_row.id,
            planning_version=plan_row.planning_version,
            planning_output_digest=plan_row.output_digest,
            planning_reviewed_at=plan_row.reviewed_at,
            planning_reviewed_by=plan_row.reviewed_by,
            option_id=option_id,
            case_snapshot_version=snapshot.case_snapshot_version,
            case_snapshot_contract_version=snapshot.contract_version,
            case_source_digest=snapshot.source_digest,
            risk_engine_version=RISK_ENGINE_VERSION,
            risk_policy_version=RISK_POLICY_VERSION,
            risk_input_digest=risk_evaluation.input_digest,
            risk_result_digest=risk_evaluation.result_digest,
            input_digest=input_digest,
            output_digest=output_digest,
            scene_data=scene.model_dump(mode="json"),
            generated_at=datetime.now(UTC),
            generated_by=user_id,
        )
        return cls._to_contract(await repository.save(row))

    @staticmethod
    def _assert_current_evidence(*, plan_row, snapshot, risk_evaluation) -> None:
        checks = (
            (snapshot.source_digest, plan_row.case_source_digest),
            (snapshot.case_snapshot_version, plan_row.case_snapshot_version),
            (snapshot.contract_version, plan_row.case_snapshot_contract_version),
            (RISK_ENGINE_VERSION, plan_row.risk_engine_version),
            (RISK_POLICY_VERSION, plan_row.risk_policy_version),
            (risk_evaluation.input_digest, plan_row.risk_input_digest),
            (risk_evaluation.result_digest, plan_row.risk_result_digest),
        )
        if any(current != reviewed for current, reviewed in checks):
            raise ValueError("accepted_treatment_planning_is_stale")

    @classmethod
    async def get_latest(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        repository: SimulationRepositoryPort | None = None,
    ) -> TreatmentSimulationResult:
        repository = repository or SqlAlchemySimulationRepository(db)
        row = await repository.get_latest(clinic_id=clinic_id, patient_id=patient_id)
        if row is None:
            raise KeyError("simulation_not_found")
        return cls._to_contract(row)

    @classmethod
    async def get_history(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        repository: SimulationRepositoryPort | None = None,
    ) -> list[TreatmentSimulationResult]:
        repository = repository or SqlAlchemySimulationRepository(db)
        rows = await repository.get_history(clinic_id=clinic_id, patient_id=patient_id)
        return [cls._to_contract(row) for row in rows]

    @staticmethod
    def _to_contract(row: TreatmentSimulationRecord) -> TreatmentSimulationResult:
        return TreatmentSimulationResult(
            id=row.id,
            patient_id=row.patient_id,
            simulation_version=row.simulation_version,
            contract_version=row.contract_version,
            scene=DigitalTwinScene.model_validate(row.scene_data),
            provenance=SimulationProvenance(
                case_snapshot_version=row.case_snapshot_version,
                case_snapshot_contract_version=row.case_snapshot_contract_version,
                case_source_digest=row.case_source_digest,
                risk_engine_version=row.risk_engine_version,
                risk_policy_version=row.risk_policy_version,
                risk_input_digest=row.risk_input_digest,
                risk_result_digest=row.risk_result_digest,
                planning_id=row.planning_id,
                planning_version=row.planning_version,
                planning_output_digest=row.planning_output_digest,
                planning_reviewed_at=row.planning_reviewed_at,
                planning_reviewed_by=row.planning_reviewed_by,
                option_id=row.option_id,
                input_digest=row.input_digest,
                output_digest=row.output_digest,
                simulation_engine_version=row.engine_version,
            ),
            generated_at=row.generated_at,
            generated_by=row.generated_by,
        )


__all__ = ["SimulationBuildError", "TreatmentSimulationService"]
