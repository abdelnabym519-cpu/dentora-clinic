"""Versioned contracts for deterministic Treatment Simulation.

Treatment Simulation is a visualization/orchestration layer over already accepted
clinical evidence.  It never predicts biological response, fabricates geometry, or
selects a treatment option autonomously.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.risk_engine.contracts import RiskMap

TREATMENT_SIMULATION_CONTRACT_VERSION = "1.0"
TREATMENT_SIMULATION_ENGINE_VERSION = "1.0.0"
TREATMENT_SIMULATION_SCENE_VERSION = "dental-digital-twin.scene/1.0"


class SimulationRequest(BaseModel):
    """Explicit dentist-selected planning artifact and option to visualize."""

    model_config = ConfigDict(extra="forbid")

    planning_id: UUID
    option_id: str = Field(min_length=1, max_length=40)


class SimulationCheckpoint(BaseModel):
    """One non-predictive stage copied from a reviewed treatment-planning step."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(min_length=1, max_length=100)
    sequence: int = Field(ge=0)
    kind: Literal["baseline", "planned_step"]
    label: str = Field(min_length=1, max_length=1000)
    purpose: str | None = Field(default=None, max_length=800)
    source_step_id: str | None = Field(default=None, max_length=40)
    evidence_ids: list[str] = Field(default_factory=list)
    risk_factor_ids: list[str] = Field(default_factory=list)
    geometry_operation: Literal["none"] = "none"
    predicted_outcome: Literal[False] = False


class DigitalTwinScene(BaseModel):
    """Viewer payload in the existing accepted DICOM patient-space reference frame."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = TREATMENT_SIMULATION_SCENE_VERSION
    renderer: Literal["dental_3d.digital_twin"] = "dental_3d.digital_twin"
    coordinate_space: Literal["dicom_patient_mm"] = "dicom_patient_mm"
    reference_frame: dict[str, Any]
    source_sections: list[str]
    risk_map: RiskMap
    checkpoints: list[SimulationCheckpoint] = Field(min_length=1)
    selected_checkpoint_id: str
    synthetic_geometry: Literal[False] = False
    mutates_source_geometry: Literal[False] = False

    @model_validator(mode="after")
    def _coherent_checkpoint_selection(self) -> DigitalTwinScene:
        ids = [item.checkpoint_id for item in self.checkpoints]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_checkpoint_id")
        if self.selected_checkpoint_id not in set(ids):
            raise ValueError("selected_checkpoint_not_found")
        if self.checkpoints[0].kind != "baseline" or self.checkpoints[0].sequence != 0:
            raise ValueError("baseline_checkpoint_required")
        return self


class SimulationProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_snapshot_version: int = Field(ge=1)
    case_snapshot_contract_version: str
    case_source_digest: str
    risk_engine_version: str
    risk_policy_version: str
    risk_input_digest: str
    risk_result_digest: str
    planning_id: UUID
    planning_version: int = Field(ge=1)
    planning_output_digest: str
    planning_review_status: Literal["accepted"] = "accepted"
    planning_reviewed_at: datetime
    planning_reviewed_by: UUID
    option_id: str
    input_digest: str
    output_digest: str
    simulation_engine_version: str = TREATMENT_SIMULATION_ENGINE_VERSION


class TreatmentSimulationResult(BaseModel):
    """Append-only advisory visualization tied to one accepted planning option."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    patient_id: UUID
    simulation_version: int = Field(ge=1)
    contract_version: str = TREATMENT_SIMULATION_CONTRACT_VERSION
    scene: DigitalTwinScene
    provenance: SimulationProvenance
    generated_at: datetime
    generated_by: UUID | None = None
    advisory_only: Literal[True] = True
    requires_accepted_plan: Literal[True] = True
    predicts_biological_outcome: Literal[False] = False
    creates_or_updates_treatment_plan: Literal[False] = False
    disclaimer: Literal[
        "Visualization of an accepted advisory plan in existing patient-space evidence only; no biological outcome or geometric treatment result is predicted."
    ] = (
        "Visualization of an accepted advisory plan in existing patient-space evidence only; "
        "no biological outcome or geometric treatment result is predicted."
    )
