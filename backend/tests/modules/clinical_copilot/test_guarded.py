from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.llm.base import Done, ProviderEvent, ProviderMessage, TextDelta
from app.modules.clinical_copilot.contracts import (
    ClinicalCopilotContext,
    ClinicalCopilotFocus,
    ClinicalStageStatus,
    StageName,
    StageState,
)
from app.modules.clinical_copilot.guarded import (
    ClinicalCopilotGuardedService,
    ClinicalCopilotInputError,
    _enforce_cross_stage_readiness,
)
from app.modules.clinical_copilot.service import _digest


class RecordingProvider:
    def __init__(self) -> None:
        self.called = False
        self.last_user_text = ""
        self.tools = None

    def complete(
        self,
        *,
        system: str,
        messages: list[ProviderMessage],
        tools: list[dict],
        model: str,
        max_tokens: int,
    ) -> AsyncIterator[ProviderEvent]:
        self.called = True
        self.last_user_text = messages[0].content[0].text
        self.tools = tools
        payload = json.loads(self.last_user_text)
        evidence_alias = payload["allowed_evidence_ids"][0]

        async def stream() -> AsyncIterator[ProviderEvent]:
            yield TextDelta(
                text=json.dumps(
                    {
                        "claims": [
                            {
                                "text": "Review the evidence-linked option.",
                                "evidence_ids": [evidence_alias],
                            }
                        ],
                        "limitations": [],
                    }
                )
            )
            yield Done(stop_reason="stop")

        return stream()


class ReadyGuardedService(ClinicalCopilotGuardedService):
    def __init__(self, context: ClinicalCopilotContext) -> None:
        super().__init__(db=None)
        self.context = context
        self.context_called = False

    async def build_context(self, **kwargs) -> ClinicalCopilotContext:
        self.context_called = True
        return self.context.model_copy(deep=True)


def _ready_context() -> ClinicalCopilotContext:
    clinic_id = uuid4()
    patient_id = uuid4()
    now = datetime.now(UTC)
    stages = [
        ClinicalStageStatus(
            stage=stage,
            state=StageState.READY,
            artifact_id=f"internal-{stage.value}",
            artifact_version=1,
            generated_at=now,
            source_digest=f"sha256:{stage.value}",
            evidence_refs=["RAW-EVIDENCE-1"],
        )
        for stage in StageName
    ]
    return ClinicalCopilotContext(
        clinic_id=clinic_id,
        patient_id=patient_id,
        stages=stages,
        missing_or_stale=[],
        evidence_catalog={
            "case_intelligence": {
                "artifact_id": "INTERNAL-ARTIFACT-42",
                "source_record_id": "SOURCE-RECORD-42",
                "source_digest": "sha256:INTERNAL-DIGEST",
                "patient_id": str(patient_id),
                "option_id": "OPTION-INTERNAL-42",
                "evidence": [{"evidence_id": "RAW-EVIDENCE-1"}],
            }
        },
        input_digest="sha256:internal-context-digest",
        ready_for_advice=True,
    )


def test_risk_unavailable_cascades_fail_closed_to_planning_and_simulation() -> None:
    context = _ready_context()
    by_stage = {stage.stage: stage for stage in context.stages}
    by_stage[StageName.RISK_ENGINE].state = StageState.UNAVAILABLE
    by_stage[StageName.RISK_ENGINE].reason = "risk_context_unavailable"

    hardened = _enforce_cross_stage_readiness(context)
    by_stage = {stage.stage: stage for stage in hardened.stages}

    assert by_stage[StageName.TREATMENT_PLANNING].state is StageState.STALE
    assert by_stage[StageName.TREATMENT_PLANNING].reason == "treatment_planning_risk_not_ready"
    assert by_stage[StageName.TREATMENT_SIMULATION].state is StageState.STALE
    assert (
        by_stage[StageName.TREATMENT_SIMULATION].reason
        == "treatment_simulation_planning_not_ready"
    )
    assert hardened.ready_for_advice is False


@pytest.mark.parametrize("risk_state", [StageState.UNAVAILABLE, StageState.STALE])
def test_risk_unusable_state_never_leaves_planning_ready(risk_state: StageState) -> None:
    context = _ready_context()
    by_stage = {stage.stage: stage for stage in context.stages}
    by_stage[StageName.RISK_ENGINE].state = risk_state
    by_stage[StageName.RISK_ENGINE].reason = "risk_not_ready"

    hardened = _enforce_cross_stage_readiness(context)
    planning = next(
        stage for stage in hardened.stages if stage.stage is StageName.TREATMENT_PLANNING
    )
    assert planning.state is not StageState.READY
    assert hardened.ready_for_advice is False


@pytest.mark.asyncio
async def test_internal_free_text_focus_is_rejected_before_context_or_provider() -> None:
    context = _ready_context()
    service = ReadyGuardedService(context)
    provider = RecordingProvider()

    with pytest.raises(ClinicalCopilotInputError, match="focus_invalid"):
        await service.advise(
            clinic_id=context.clinic_id,
            patient_id=context.patient_id,
            focus="patient free text",
            provider=provider,
            provider_name="fake",
            model="fake-model",
            user_id=uuid4(),
            user_role="dentist",
        )

    assert service.context_called is False
    assert provider.called is False


@pytest.mark.asyncio
async def test_provider_boundary_uses_only_opaque_ids_and_exact_input_digest() -> None:
    context = _ready_context()
    provider = RecordingProvider()
    user_id = uuid4()

    result = await ReadyGuardedService(context).advise(
        clinic_id=context.clinic_id,
        patient_id=context.patient_id,
        focus=ClinicalCopilotFocus.CASE_REVIEW,
        provider=provider,
        provider_name="fake",
        model="fake-model",
        user_id=user_id,
        user_role="dentist",
    )

    payload = json.loads(provider.last_user_text)
    serialized = provider.last_user_text
    assert payload["allowed_evidence_ids"] == ["E001"]
    assert "RAW-EVIDENCE-1" not in serialized
    assert "SOURCE-RECORD-42" not in serialized
    assert "INTERNAL-ARTIFACT-42" not in serialized
    assert "INTERNAL-DIGEST" not in serialized
    assert "OPTION-INTERNAL-42" not in serialized
    assert str(context.patient_id) not in serialized
    assert str(context.clinic_id) not in serialized
    assert payload["evidence_chain"]["case_intelligence"]["evidence"] == [{"evidence_id": "E001"}]
    assert payload["evidence_chain"]["case_intelligence"]["option_id"] == "I001"
    assert provider.tools == []

    assert result.claims[0].evidence_ids == ["RAW-EVIDENCE-1"]
    assert result.provenance.input_digest == _digest(payload)
    assert result.provenance.input_digest != context.input_digest
    assert result.provenance.generated_by == user_id
    assert result.dentist_review_required is True
    assert result.canonical_record_mutation is False
