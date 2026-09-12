"""GOLDEN-PATH E2E — one deterministic run of the full AI-activation chain.

Mission-23 stages, executed through the REAL application services only:

  A. the deterministic SYNTHETIC CBCT/DICOM development fixture builds from
     the patient's own seeded IOS mesh and loads as valid DICOM
  B. ingestion runs through the real Pydicom adapter; alignment runs the
     real Open3D registration ports against a deterministic anatomy stand-in
  C. the dentist-accepted alignment makes the patient-space reference frame
     legitimately available (CI reference_frame = available, nothing missing)
  D. Dental 3D prosthetic target + implant plan consume the accepted frame
  E. a deterministic dev nerve provider detects mandibular canals
  F. the Risk Engine generates on real upstream data (10/10, "available")
  G. dentist acceptance works for nerve, plan, risk, summary and planning
  H. Case Intelligence stays lock-free while AI generation is in flight
  I. AI Summary generates and persists
  J. the Treatment Plan generates and is dentist-accepted
  K. Treatment Simulation runs on the accepted plan + accepted frame
  L. AI Second Review runs on the simulation and is marked reviewed
  M. AI Clinical Report readiness is TRUE only because every real
     prerequisite is satisfied
  N. the Clinical Report generates (advisory draft, dentist review required)
  O. the Clinical Copilot answers with grounded claims under the governor

Isolated test doubles (never production replacements):
- FixtureAnatomyPort / FixtureNerveProvider: deterministic stand-ins for
  the operator-managed DentalSegmentator/nerve model services, derived
  from the same synthetic fixture (mirrors
  scripts.build_cbct_development_fixture).
- ScriptedProvider: an LLM provider that parses the actual canonical-JSON
  llm_input it receives and answers the prompt's own contract with
  grounded references — nothing is hard-coded against fixture IDs.

No gate is bypassed: alignment, prosthetic target, nerve, implant plan,
risk, summary and planning all go through their real dentist-review
steps; simulation/second-review/report/copilot prerequisites are
satisfied by those reviewed artifacts only.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import pathlib
import zipfile
from io import BytesIO

import pytest
from pydicom import dcmread

from scripts.build_cbct_development_fixture import (
    FIXTURE_FRAME_OF_REFERENCE_UID,
    FIXTURE_SERIES_UID,
    build_series_bytes,
)
from scripts.seed_demo import _ensure_module_registry

for _path in sorted(pathlib.Path("app/modules").glob("*/models.py")):
    importlib.import_module(".".join(_path.with_suffix("").parts))


def _scalar_paths(facts: object, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(facts, dict):
        for key, value in facts.items():
            path = f"{prefix}{key}"
            if isinstance(value, dict):
                paths.extend(_scalar_paths(value, f"{path}."))
            elif not isinstance(value, list):
                paths.append(path)
    return paths


class ScriptedProvider:
    """LLM double that answers each prompt from the input it receives."""

    def __init__(self, delay_s: float = 0.0):
        self.delay_s = delay_s
        self.calls: list[dict] = []

    async def complete(self, **kwargs):
        from app.core.llm.base import Done, TextBlock, TextDelta, Usage

        self.calls.append(kwargs)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        system = kwargs["system"]
        user_text = "".join(
            block.text for block in kwargs["messages"][0].content if isinstance(block, TextBlock)
        )
        user = json.loads(user_text)

        if "dental case facts" in system:
            evidence = user["evidence"]
            claims = []
            claim_id = 0
            for eid in sorted(evidence):
                facts = evidence[eid].get("facts") or {}
                section = evidence[eid].get("section") or "case"
                if section in ("medical_context", "periodontogram") and facts:
                    usable = [
                        p
                        for p in _scalar_paths(facts)
                        if p in ("type", "severity", "status", "closed_at")
                    ]
                    if usable:
                        claim_id += 1
                        claims.append(
                            {
                                "claim_id": f"C{claim_id}",
                                "evidence_id": eid,
                                "fact_paths": usable[:6],
                            }
                        )
                if claim_id >= 2:
                    break
            payload = json.dumps({"claims": claims})

        elif "treatment-planning strategies" in system:
            case = user["case"]
            evidence = case["evidence"]
            factors = [f["factor_id"] for f in user["risk_context"]["factors"]]
            allergy = next(
                eid
                for eid, rec in evidence.items()
                if rec.get("section") == "medical_context"
                and (rec.get("facts") or {}).get("type") == "drug"
            )
            perio = next(
                eid for eid, rec in evidence.items() if rec.get("section") == "periodontogram"
            )
            allergy_paths = [
                p for p in _scalar_paths(evidence[allergy]["facts"]) if p in ("type", "severity")
            ]
            perio_paths = [
                p for p in _scalar_paths(evidence[perio]["facts"]) if p in ("status", "closed_at")
            ]
            payload = json.dumps(
                {
                    "options": [
                        {
                            "option_id": "OPT-1",
                            "strategy": "review_documented_findings",
                            "evidence": [
                                {"evidence_id": allergy, "fact_paths": allergy_paths},
                                {"evidence_id": perio, "fact_paths": perio_paths},
                            ],
                            "risk_factor_ids": factors[:2],
                            "steps": [
                                {
                                    "step_id": "S1",
                                    "strategy": "review_documented_findings",
                                    "evidence": [
                                        {"evidence_id": perio, "fact_paths": perio_paths[:1]}
                                    ],
                                    "risk_factor_ids": factors[:1],
                                },
                                {
                                    "step_id": "S2",
                                    "strategy": "review_documented_findings",
                                    "evidence": [
                                        {"evidence_id": allergy, "fact_paths": allergy_paths[:1]}
                                    ],
                                    "risk_factor_ids": factors[1:2],
                                },
                            ],
                        }
                    ]
                }
            )

        elif "second review" in system:
            gaps = sorted(
                {
                    item["section"]
                    for item in (user.get("case", {}).get("sections", {}).values() or [])
                    if isinstance(item, dict) and item.get("status") not in (None, "available")
                }
            )
            payload = json.dumps({"findings": [], "data_gaps": gaps})

        elif "Clinical Copilot" in system:
            allowed = user["allowed_evidence_ids"]
            chain_ids = sorted(user.get("evidence_chain", {}).keys())
            preferred = [eid for eid in chain_ids if eid in allowed][:1] or allowed[:1]
            payload = json.dumps(
                {
                    "claims": [
                        {
                            "text": "Documented facts below are drawn from allowed evidence only.",
                            "evidence_ids": preferred,
                        }
                    ],
                    "limitations": [
                        "Output is advisory only and requires dentist review.",
                    ],
                }
            )

        else:  # pragma: no cover - unknown prompt in this suite
            raise AssertionError(f"ScriptedProvider: unknown system prompt: {system[:80]}")

        for chunk in (payload[i : i + 32] for i in range(0, len(payload), 32)):
            yield TextDelta(chunk)
        yield Usage(input_tokens=64, output_tokens=32)
        yield Done("stop")


class FixtureAnatomyPort:
    """Deterministic stand-in for the DentalSegmentator anatomy service:
    threshold-extracts the fixture voxels to DICOM LPS millimetres."""

    name = "dev-fixture-threshold-extract"

    async def extract(self, prepared):
        import numpy as np

        from app.modules.dental_3d.registration import ExtractedDentalAnatomy

        points = []
        frame_uid = None
        with zipfile.ZipFile(BytesIO(prepared.archive)) as archive:
            for name in sorted(n for n in archive.namelist() if n.endswith(".dcm")):
                dataset = dcmread(BytesIO(archive.read(name)))
                frame_uid = str(dataset.FrameOfReferenceUID)
                ipp = [float(v) for v in dataset.ImagePositionPatient]
                iop = [float(v) for v in dataset.ImageOrientationPatient]
                ps = [float(v) for v in dataset.PixelSpacing]
                grid = np.frombuffer(dataset.PixelData, dtype=np.uint16).reshape(
                    int(dataset.Rows), int(dataset.Columns)
                )
                for row, col in zip(*np.nonzero(grid == 1000)):
                    x = ipp[0] + iop[0] * col * ps[1] + iop[3] * row * ps[0]
                    y = ipp[1] + iop[1] * col * ps[1] + iop[4] * row * ps[0]
                    z = ipp[2] + iop[2] * col * ps[1] + iop[5] * row * ps[0]
                    points.append((x, y, z))
        cloud = np.unique(np.round(np.array(points), 2), axis=0)
        assert len(cloud) >= 3
        return ExtractedDentalAnatomy(
            points_mm=[{"x": float(x), "y": float(y), "z": float(z)} for x, y, z in cloud],
            frame_of_reference_uid=frame_uid,
            model_id="dev-fixture-threshold-extract",
            model_version="0.1.0",
        )


class FixtureNerveProvider:
    """Deterministic stand-in for the nerve model service: derives bilateral
    canal arcs in the fixture frame, DICOM patient millimetres."""

    name = "dev-fixture-canal"
    input_kind = "cbct_series"

    async def detect(self, request):
        import hashlib
        from datetime import UTC, datetime

        from app.modules.dental_3d.nerve import (
            NerveConfidenceSummary,
            NerveDetectionResult,
            NerveEvidence,
            NerveModelProvenance,
            NervePathPoint,
            NervePathway,
            NerveReferenceSpace,
        )

        digest = hashlib.sha256(request.patient_id.bytes).hexdigest()
        pathways = []
        for side, sign in (("left", -1.0), ("right", 1.0)):
            pathways.append(
                NervePathway(
                    finding_id=f"golden-path-{side}-mandibular-canal",
                    side=side,
                    region="mandibular_canal",
                    source="model_inference",
                    status="detected",
                    confidence=0.9,
                    uncertainty=None,
                    reference_space=NerveReferenceSpace(
                        kind="dicom_patient",
                        unit="mm",
                        frame_of_reference_uid=FIXTURE_FRAME_OF_REFERENCE_UID,
                    ),
                    points=[
                        NervePathPoint(x=sign * 12.0 + t, y=6.0 + t, z=0.5)
                        for t in (0.0, 2.0, 4.0, 6.0, 8.0)
                    ],
                    evidence=NerveEvidence(
                        basis="cbct_inference",
                        note="deterministic development fixture",
                    ),
                )
            )
        return NerveDetectionResult(
            status="detected",
            provider=self.name,
            method="deterministic-fixture-canal-v0",
            input_kind="cbct_series",
            requires_review=True,
            pathways=pathways,
            confidence_summary=NerveConfidenceSummary(count=2, minimum=0.9, maximum=0.9, mean=0.9),
            provenance=NerveModelProvenance(
                model_id="dev-fixture-canal",
                model_version="0.1.0",
                adapter="test-double",
                input_digest=f"sha256:{digest}",
                study_instance_uid="1.2.826.0.1.3680043.10.1337.9001",
                series_instance_uid=FIXTURE_SERIES_UID,
                frame_of_reference_uid=FIXTURE_FRAME_OF_REFERENCE_UID,
            ),
            performed_at=request.performed_at or datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_golden_path_full_ai_activation_chain(db_session) -> None:
    from sqlalchemy import select

    from app.config import settings
    from app.core.plugins.service import ModuleService
    from app.modules.ai_case_summary.service import AICaseSummaryService
    from app.modules.ai_clinical_report.service import AIClinicalReportService
    from app.modules.ai_second_review.service import AISecondReviewService
    from app.modules.ai_treatment_planning.service import AITreatmentPlanningService
    from app.modules.case_intelligence.contracts import AvailabilityStatus
    from app.modules.case_intelligence.service import CaseIntelligenceService
    from app.modules.clinical_copilot.guarded import ClinicalCopilotGuardedService
    from app.modules.dental_3d.cbct import DicomIngestionRequest
    from app.modules.dental_3d.implant_models import DentalProstheticTarget
    from app.modules.dental_3d.implant_planning import (
        ImplantCatalogEntry,
        ImplantProposalRequest,
        PlanningCriterion,
        PlanningPolicy,
        ProstheticTargetCreate,
        ProstheticTargetReviewUpdate,
    )
    from app.modules.dental_3d.implant_service import DentalImplantPlanningService
    from app.modules.dental_3d.infrastructure import PydicomMediaCbctAdapter
    from app.modules.dental_3d.nerve import NerveReviewUpdate
    from app.modules.dental_3d.registration import (
        AlignmentReviewUpdate,
        AlignmentRunRequest,
    )
    from app.modules.dental_3d.registration_service import DentalAlignmentService
    from app.modules.dental_3d.service import DentalNerveService
    from app.modules.media.models import Document as MediaDocument
    from app.modules.media.storage import get_storage_backend
    from app.modules.patients.models import Patient
    from app.modules.risk_engine.contracts import ReviewStatus as RiskReviewStatus
    from app.modules.risk_engine.service import RiskEngineService
    from app.modules.treatment_simulation.service import TreatmentSimulationService
    from app.seeds.ai_demo_data import AI_COMPLETE_ID
    from app.seeds.demo_data import USER_DENTIST_ID
    from scripts.seed_demo import seed_ai_demo_cases

    # ---- composition root --------------------------------------------------
    from tests.test_ai_demo_data import _seed_pre_ai_demo_base

    _ensure_module_registry()
    await ModuleService(db_session).reconcile_with_db()
    await _seed_pre_ai_demo_base(db_session)
    await seed_ai_demo_cases(db_session, USER_DENTIST_ID)
    # The mission E2E ran on the COMPLETE demo archetype — the only case
    # whose structured evidence populates every risk factor.
    patient_id = AI_COMPLETE_ID
    clinic_id = (
        await db_session.execute(select(Patient.clinic_id).where(Patient.id == patient_id))
    ).scalar_one()

    # ---- Stage A: synthetic CBCT fixture built from the patient's mesh -----
    mesh_document = (
        (
            await db_session.execute(
                select(MediaDocument).where(
                    MediaDocument.patient_id == patient_id,
                    MediaDocument.mime_type == "model/stl",
                    MediaDocument.status == "active",
                )
            )
        )
        .scalars()
        .first()
    )
    assert mesh_document is not None, "seeder must provide the patient's IOS mesh"

    # The document.uploaded event handlers run in their own DB session and
    # cannot see this test's still-open seed transaction, so record the same
    # timeline entry through the module's real service — the exact call the
    # event bus makes in production (patient_timeline.events._record).
    from app.modules.patient_timeline.service import TimelineService

    await TimelineService.add_entry(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        event_type="document.uploaded",
        event_category="document",
        source_table="documents",
        source_id=mesh_document.id,
        title=f"Documento: {mesh_document.title or 'SYNTHETIC DEMO SCAN'}",
        event_data={"document_type": "other"},
    )
    await db_session.commit()
    mesh_bytes = await get_storage_backend().retrieve(mesh_document.storage_path)
    tmp_mesh = pathlib.Path("/tmp") / f"golden_mesh_{patient_id.hex[:8]}.stl"
    tmp_mesh.write_bytes(mesh_bytes)
    instances = build_series_bytes(mesh_path=tmp_mesh, slices=12)
    tmp_mesh.unlink(missing_ok=True)
    assert len(instances) == 12

    # ---- Stage B: real ingestion + real alignment ports ---------------------
    for filename, payload, _header in instances:
        receipt = await PydicomMediaCbctAdapter(db_session, settings.STORAGE_MAX_FILE_SIZE).ingest(
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=USER_DENTIST_ID,
            request=DicomIngestionRequest(
                filename=filename,
                content_type="application/dicom",
                data=payload,
                title=None,
            ),
        )
        assert receipt.metadata.series_instance_uid == FIXTURE_SERIES_UID

    alignment = await DentalAlignmentService.run_alignment(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        user_id=USER_DENTIST_ID,
        request=AlignmentRunRequest(
            mesh_document_id=mesh_document.id,
            series_instance_uid=FIXTURE_SERIES_UID,
            ios_units="mm",
        ),
        anatomy_port=FixtureAnatomyPort(),
    )
    assert alignment.id is not None
    assert alignment.status == "pending_review", alignment
    assert alignment.transform is not None
    assert alignment.metrics.icp_converged is True
    assert alignment.target_frame.kind == "dicom_patient"
    assert alignment.target_frame.frame_of_reference_uid == FIXTURE_FRAME_OF_REFERENCE_UID

    accepted_alignment = await DentalAlignmentService.review_alignment(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        alignment_id=alignment.id,
        reviewer_id=USER_DENTIST_ID,
        payload=AlignmentReviewUpdate(decision="accepted", note="golden path"),
    )
    assert accepted_alignment.status == "accepted"

    # ---- Stage C: reference frame legitimately available --------------------
    snapshot = await CaseIntelligenceService.get_current(
        db_session, clinic_id=clinic_id, patient_id=patient_id, user_id=USER_DENTIST_ID
    )
    assert snapshot.reference_frame.status == AvailabilityStatus.AVAILABLE
    # Nerve/implant sections are legitimately absent until Stages D/E run.

    # ---- Stage E: deterministic nerve detection + dentist acceptance --------
    nerve = await DentalNerveService.run_detection(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        user_id=USER_DENTIST_ID,
        provider=FixtureNerveProvider(),
        requested_series_instance_uid=FIXTURE_SERIES_UID,
    )
    assert nerve.status == "detected", nerve.failure
    await DentalNerveService.review_analysis(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        analysis_id=nerve.id,
        reviewer_id=USER_DENTIST_ID,
        payload=NerveReviewUpdate(decision="accepted", note="golden path"),
    )

    # ---- Stage D: prosthetic target + implant plan on the accepted frame ----
    target = await DentalImplantPlanningService.create_prosthetic_target(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        user_id=USER_DENTIST_ID,
        payload=ProstheticTargetCreate(
            alignment_id=alignment.id,
            platform_center={"x": 0.0, "y": 13.0, "z": 3.0},
            axis={"x": 0.0, "y": 0.0, "z": -1.0},
            frame_of_reference_uid=FIXTURE_FRAME_OF_REFERENCE_UID,
            source_type="dentist_defined",
            source_reference_space="dicom_patient",
            source_frame_of_reference_uid=FIXTURE_FRAME_OF_REFERENCE_UID,
            source_method="golden-path-dev-fixture",
            source_identifier="golden-path-target",
        ),
    )
    accepted_target = await DentalImplantPlanningService.review_prosthetic_target(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        target_id=target.id,
        reviewer_id=USER_DENTIST_ID,
        payload=ProstheticTargetReviewUpdate(decision="accepted", note="golden path"),
    )
    assert accepted_target.review_status == "accepted"

    proposal = await DentalImplantPlanningService.create_proposal(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        user_id=USER_DENTIST_ID,
        payload=ImplantProposalRequest(
            catalog=[
                ImplantCatalogEntry(
                    id="golden-fixture-implant",
                    label="SYNTHETIC dev fixture implant 4.0x10",
                    diameter_mm=4.0,
                    length_mm=10.0,
                    dimension_source="golden-path-dev-fixture-catalog",
                )
            ],
            policy=PlanningPolicy(
                criteria=[
                    PlanningCriterion(name="nerve_surface_to_centerline_mm", direction="desc")
                ]
            ),
        ),
    )
    assert proposal.status == "proposed"
    assert proposal.requires_review is True
    accepted_plan_3d = await DentalImplantPlanningService.review_plan(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        plan_id=proposal.id,
        reviewer_id=USER_DENTIST_ID,
        decision="accepted",
        note="golden path",
    )
    assert accepted_plan_3d.status == "accepted"
    target_row = (
        (
            await db_session.execute(
                select(DentalProstheticTarget).where(
                    DentalProstheticTarget.patient_id == patient_id
                )
            )
        )
        .scalars()
        .first()
    )
    assert target_row is not None and target_row.review_status == "accepted"

    # ---- Stage F/G: risk on the complete upstream state + acceptance --------
    snapshot = await CaseIntelligenceService.get_current(
        db_session, clinic_id=clinic_id, patient_id=patient_id, user_id=USER_DENTIST_ID
    )
    assert snapshot.missing_data_report == [], snapshot.missing_data_report
    risk = await RiskEngineService.generate(
        db_session, clinic_id=clinic_id, patient_id=patient_id, user_id=USER_DENTIST_ID
    )
    not_available = {
        key: str(status)
        for key, status in snapshot.availability.items()
        if status != AvailabilityStatus.AVAILABLE
    }
    assert risk.provenance.availability_state == "available", {
        "sections": not_available,
        "factors": [
            (f.factor_id, str(f.state))
            for f in risk.factors
            if str(f.state) != "present" and str(f.state) != "absent"
        ],
    }
    nerve_factor = next(f for f in risk.factors if f.factor_id == "accepted_nerve_pathway_present")
    assert nerve_factor.state == "present"
    plan_factor = next(
        f for f in risk.factors if f.factor_id == "current_accepted_implant_plan_present"
    )
    assert plan_factor.state == "present"

    accepted_risk = await RiskEngineService.review(
        db_session,
        clinic_id=clinic_id,
        result_id=risk.id,
        reviewer_id=USER_DENTIST_ID,
        reviewer_role="dentist",
        decision="accepted",
    )
    assert accepted_risk.review_status == RiskReviewStatus.ACCEPTED

    # ---- Stage H: CI stays lock-free while AI generation is in flight -------
    # A second session mirrors the real app: two requests never share one
    # AsyncSession/connection. The concurrent read proves Case Intelligence
    # is readable while a summary generation is in flight (no DB lock or
    # transaction is held across the provider call).
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    slow_provider = ScriptedProvider(delay_s=0.3)
    generate_task = asyncio.create_task(
        AICaseSummaryService.generate(
            db_session,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=USER_DENTIST_ID,
            provider=slow_provider,
        )
    )
    concurrent_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    concurrent_session_maker = async_sessionmaker(concurrent_engine, expire_on_commit=False)
    async with concurrent_session_maker() as concurrent_session:
        concurrent_snapshot = await CaseIntelligenceService.get_current(
            concurrent_session,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=USER_DENTIST_ID,
        )
    await concurrent_engine.dispose()
    summary = await generate_task
    assert concurrent_snapshot.case_snapshot_version >= 1
    assert slow_provider.calls, "summary generation must reach the provider"

    # ---- Stage I: summary dentist acceptance --------------------------------
    assert summary.review_status == "pending_review"
    assert summary.content.claims, "grounded claims must render"
    accepted_summary = await AICaseSummaryService.review(
        db_session,
        clinic_id=clinic_id,
        summary_id=summary.id,
        reviewer_id=USER_DENTIST_ID,
        reviewer_role="dentist",
        decision="accepted",
    )
    assert accepted_summary.review_status == "accepted"

    # ---- Stage J: planning on the accepted risk + dentist acceptance --------
    plan = await AITreatmentPlanningService.generate(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        user_id=USER_DENTIST_ID,
        provider=ScriptedProvider(),
    )
    assert plan.content.options, "planning options must render"
    accepted_plan = await AITreatmentPlanningService.review(
        db_session,
        clinic_id=clinic_id,
        planning_id=plan.id,
        reviewer_id=USER_DENTIST_ID,
        reviewer_role="dentist",
        decision="accepted",
    )
    assert accepted_plan.review_status == "accepted"

    # ---- Stage K: simulation on the accepted plan + accepted frame ----------
    simulation = await TreatmentSimulationService.generate(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        planning_id=plan.id,
        option_id=plan.content.options[0].option_id,
        user_id=USER_DENTIST_ID,
    )
    assert simulation.scene is not None
    assert simulation.advisory_only is True
    assert simulation.requires_accepted_plan is True

    # ---- Stage L: second review on the simulation ---------------------------
    second_review = await AISecondReviewService.generate(
        db_session,
        clinic_id=clinic_id,
        patient_id=patient_id,
        simulation_id=simulation.id,
        user_id=USER_DENTIST_ID,
        provider=ScriptedProvider(),
    )
    marked = await AISecondReviewService.mark_reviewed(
        db_session,
        clinic_id=clinic_id,
        review_id=second_review.id,
        reviewer_id=USER_DENTIST_ID,
        reviewer_role="dentist",
    )
    assert marked.review_status == "reviewed"

    # ---- Stage M/N: readiness TRUE + advisory report draft ------------------
    report_service = AIClinicalReportService(db_session)
    readiness = await report_service.readiness(clinic_id=clinic_id, patient_id=patient_id)
    assert readiness.ready_for_report is True
    report = await report_service.generate(
        clinic_id=clinic_id,
        patient_id=patient_id,
        provider=ScriptedProvider(),
        provider_name="scripted",
        model="scripted-golden",
        user_id=USER_DENTIST_ID,
        user_role="dentist",
    )
    assert report.status == "draft"
    assert report.advisory_only is True
    assert report.dentist_review_required is True
    assert report.autonomous_diagnosis is False
    assert report.autonomous_treatment_decision is False
    assert report.canonical_record_mutation is False
    assert report.sections, "per-stage report sections must render"

    # ---- Stage O: copilot grounded advisory under the governor --------------
    # Composition identical to the router: the second-review downstream
    # reader is injected so the cross-stage contract is real, not assumed.
    from app.modules.ai_clinical_report.service import DatabaseSecondReviewReader
    from app.modules.clinical_copilot.service import ClinicalContextInsufficientError

    try:
        advisory = await ClinicalCopilotGuardedService(
            db_session, second_review_reader=DatabaseSecondReviewReader(db_session)
        ).advise(
            clinic_id=clinic_id,
            patient_id=patient_id,
            focus="case_review",
            provider=ScriptedProvider(),
            provider_name="scripted",
            model="scripted-golden",
            user_id=USER_DENTIST_ID,
            user_role="dentist",
        )
    except ClinicalContextInsufficientError as exc:
        stages = {stage.stage: (str(stage.state), stage.reason) for stage in exc.context.stages}
        raise AssertionError(
            {
                "missing_or_stale": exc.context.missing_or_stale,
                "stages": stages,
            }
        ) from exc
    assert advisory.advisory_only is True
    assert advisory.dentist_review_required is True
    assert advisory.claims and advisory.claims[0].evidence_ids
