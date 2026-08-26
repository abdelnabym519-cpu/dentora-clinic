"""Safety and assembly tests for AI Clinical Report."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.ai_clinical_report import AIClinicalReportModule
from app.modules.ai_clinical_report.contracts import ReportSectionName
from app.modules.ai_clinical_report.service import (
    AIClinicalReportService,
    ClinicalReportAssemblyError,
    assemble_report,
)
from app.modules.clinical_copilot.contracts import (
    AdvisoryClaim,
    ClinicalCopilotAdvisory,
    ClinicalCopilotProvenance,
    ClinicalStageStatus,
    StageName,
    StageState,
)


def _stage(stage: StageName, evidence: str) -> ClinicalStageStatus:
    return ClinicalStageStatus(
        stage=stage,
        state=StageState.READY,
        artifact_id=f"artifact-{stage.value}",
        artifact_version=1,
        generated_at=datetime.now(UTC),
        source_digest=f"sha256:{stage.value}",
        evidence_refs=[evidence],
    )


def _advisory(*, unsupported: bool = False) -> ClinicalCopilotAdvisory:
    patient_id = uuid4()
    user_id = uuid4()
    stages = [
        _stage(StageName.CASE_INTELLIGENCE, "E-CASE"),
        _stage(StageName.RISK_ENGINE, "E-RISK"),
        _stage(StageName.TREATMENT_PLANNING, "E-PLAN"),
        _stage(StageName.TREATMENT_SIMULATION, "E-SIM"),
        _stage(StageName.AI_SECOND_REVIEW, "E-REVIEW"),
    ]
    claims = [
        AdvisoryClaim(
            text="Case evidence remains available for clinician review.",
            evidence_ids=["E-UNKNOWN" if unsupported else "E-CASE"],
        ),
        AdvisoryClaim(
            text="Risk and planning evidence should be considered together.",
            evidence_ids=["E-RISK", "E-PLAN"],
        ),
    ]
    return ClinicalCopilotAdvisory(
        patient_id=patient_id,
        claims=claims,
        limitations=["Draft for dentist review only."],
        provenance=ClinicalCopilotProvenance(
            provider="fake",
            model="fake-model",
            input_digest="sha256:input",
            output_digest="sha256:output",
            upstream=stages,
            generated_at=datetime.now(UTC),
            generated_by=user_id,
        ),
    )


def test_manifest_declares_read_and_dentist_generation() -> None:
    module = AIClinicalReportModule()
    manifest = module.get_manifest()
    assert module.get_permissions() == ["read", "generate"]
    assert manifest.role_permissions["dentist"] == ("read", "generate")
    assert manifest.role_permissions["hygienist"] == ("read",)
    assert manifest.auto_install is False
    assert manifest.removable is False


def test_assemble_report_preserves_evidence_and_is_non_canonical() -> None:
    report = assemble_report(_advisory())
    by_section = {section.section: section for section in report.sections}

    assert len(report.sections) == 6
    assert by_section[ReportSectionName.CASE_INTELLIGENCE].claims[0].evidence_ids == ["E-CASE"]
    assert by_section[ReportSectionName.CROSS_STAGE].claims[0].evidence_ids == [
        "E-RISK",
        "E-PLAN",
    ]
    assert report.status.value == "draft"
    assert report.advisory_only is True
    assert report.dentist_review_required is True
    assert report.autonomous_diagnosis is False
    assert report.autonomous_treatment_decision is False
    assert report.canonical_record_mutation is False
    assert report.provenance.report_output_digest.startswith("sha256:")


def test_assemble_report_rejects_ungrounded_claim() -> None:
    with pytest.raises(ClinicalReportAssemblyError, match="ungrounded_claim"):
        assemble_report(_advisory(unsupported=True))


@pytest.mark.asyncio
async def test_service_rejects_non_dentist_before_db_or_provider_access() -> None:
    service = AIClinicalReportService(None)  # type: ignore[arg-type]
    with pytest.raises(PermissionError, match="dentist_control_required"):
        await service.generate(
            clinic_id=uuid4(),
            patient_id=uuid4(),
            provider=object(),  # type: ignore[arg-type]
            provider_name="fake",
            model="fake-model",
            user_id=uuid4(),
            user_role="assistant",
        )
