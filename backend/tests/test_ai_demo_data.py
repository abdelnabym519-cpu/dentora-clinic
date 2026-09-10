"""Regression: the synthetic AI-demo dataset stays valid and honest.

Locks the invariants the AI-activation demo relies on: unique fixed IDs,
clear SYNTHETIC marking on every case, medically coherent completeness for
the "complete" case, a closed periodontogram payload with the module's
site codes, and a deterministic STL fixture that passes the dental_3d
mesh content validation.
"""

import pytest  # noqa: E402

from app.seeds.ai_demo_data import (  # noqa: E402
    AI_COMPLETE_ID,
    AI_DEMO_CASES,
    AI_DEMO_PATIENT_IDS,
    MESH_FILENAME,
    build_demo_arch_stl,
    build_tooth_records,
)


def _case(key: str) -> dict:
    return next(case for case in AI_DEMO_CASES if case["key"] == key)


def test_five_unique_fixed_ids_with_synthetic_marking() -> None:
    assert len(AI_DEMO_CASES) == 5
    assert len({case["id"] for case in AI_DEMO_CASES}) == 5
    assert AI_DEMO_PATIENT_IDS == [case["id"] for case in AI_DEMO_CASES]
    for case in AI_DEMO_CASES:
        assert "SYNTHETIC" in case["last_name"], case["key"]
        assert "SYNTHETIC DEMO PATIENT" in case["notes"], case["key"]
        assert case["email"].endswith("@example.com"), case["key"]


def test_complete_case_exercises_the_full_pipeline() -> None:
    case = _case("complete")
    assert case["id"] == AI_COMPLETE_ID
    context = case["medical_history"]
    assert context["is_on_anticoagulants"] is True
    assert context["adverse_reactions_to_anesthesia"] is True
    assert context["is_smoker"] is True
    assert context["bruxism"] is True
    assert context["allergies"], "complete case needs an allergy"
    assert context["medications"], "complete case needs medications"
    assert any(t["status"] == "planned" for t in case["treatments"])
    assert case.get("mesh") is True
    # perio observations that feed the deterministic risk factors
    sites = [site for tooth in case["perio"]["teeth"] for site in tooth["sites"]]
    assert any(site["bleeding_on_probing"] for site in sites)
    assert any(site["suppuration"] for site in sites)
    assert any(site["probing_depth_mm"] and site["probing_depth_mm"] >= 4 for site in sites)


def test_perio_payloads_are_closed_snapshot_shaped() -> None:
    for case in AI_DEMO_CASES:
        teeth = case["perio"]["teeth"]
        assert len(teeth) == 32
        for tooth in teeth:
            assert len(tooth["sites"]) == 6
            assert {site["site_code"] for site in tooth["sites"]} == {
                "MV", "V", "DV", "ML", "L", "DL"
            }
            for site in tooth["sites"]:
                assert isinstance(site["bleeding_on_probing"], bool)
                assert isinstance(site["plaque"], bool)


def test_tooth_records_cover_full_permanent_dentition_with_overrides() -> None:
    records = build_tooth_records(_case("complete")["tooth_specs"])
    assert len(records) == 32
    by_number = {r["tooth_number"]: r for r in records}
    assert by_number[36]["general_condition"] == "missing"
    assert by_number[16]["general_condition"] == "carious"
    assert by_number[11]["general_condition"] == "healthy"


def test_demo_mesh_is_deterministic_and_passes_stl_validation() -> None:
    from app.modules.dental_3d.meshfiles import detect_mesh_format

    data = build_demo_arch_stl()
    again = build_demo_arch_stl()
    assert data == again, "fixture must be deterministic"
    assert detect_mesh_format(MESH_FILENAME, "model/stl", data) == "stl"


def test_implant_case_stays_external_service_gated() -> None:
    """The implant case ships geometry but never fabricated nerve/alignment
    evidence — those sections remain explicit external-service gates."""
    case = _case("implant")
    assert case.get("mesh") is True
    assert case["tooth_specs"][36]["condition"] == "missing"
    # No fabricated CBCT/nerve/alignment payloads anywhere in the dataset.
    raw = repr(AI_DEMO_CASES)
    for forbidden in ("nerve_pathway", "alignment_matrix", "dicom", "centerline"):
        assert forbidden not in raw.lower()


# --- Reconciling-seed regression (existing demo database) -------------------

async def _seed_pre_ai_demo_base(db) -> None:
    """Mimic a database created by a pre-AI revision: the demo clinic and
    its users exist, but none of the synthetic AI patients do."""
    from uuid import UUID, uuid4

    from app.core.auth.models import Clinic, ClinicMembership, User
    from app.seeds.demo_data import CLINIC_ID, USER_DENTIST_ID

    db.add(
        Clinic(
            id=CLINIC_ID,
            name="Demo Dental Clinic",
            tax_id="B12345678",
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            is_active=True,
        )
    )
    db.add(
        User(
            id=USER_DENTIST_ID,
            email="dentist@demo.clinic",
            password_hash="test",
            first_name="Sofia",
            last_name="Dentist",
            is_active=True,
            token_version=0,
        )
    )
    db.add(
        ClinicMembership(
            id=uuid4(),
            user_id=USER_DENTIST_ID,
            clinic_id=CLINIC_ID,
            role="dentist",
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_seeder_reconciles_ai_cases_into_existing_demo_database(
    db_session,
) -> None:
    """CASE 2 (pre-AI demo DB): running the seeder must NOT stop at
    "clinic exists" — it must create the missing synthetic AI patients,
    preserve everything else, and stay idempotent on the second run."""
    from sqlalchemy import select

    from app.core.plugins.service import ModuleService
    from app.modules.patients.models import Patient
    from app.seeds.ai_demo_data import AI_DEMO_PATIENT_IDS
    from app.seeds.demo_data import USER_DENTIST_ID
    from scripts.seed_demo import _ensure_module_registry, seed_ai_demo_cases

    _ensure_module_registry()
    await ModuleService(db_session).reconcile_with_db()
    await _seed_pre_ai_demo_base(db_session)

    await seed_ai_demo_cases(db_session, dentist_id=USER_DENTIST_ID)
    await db_session.commit()

    first = (
        await db_session.execute(
            select(Patient).where(Patient.id.in_(AI_DEMO_PATIENT_IDS))
        )
    ).scalars().all()
    assert len(first) == 5

    # Second run: sentinel short-circuits, zero duplicates.
    await seed_ai_demo_cases(db_session, dentist_id=USER_DENTIST_ID)
    await db_session.commit()
    second = (
        await db_session.execute(
            select(Patient).where(Patient.id.in_(AI_DEMO_PATIENT_IDS))
        )
    ).scalars().all()
    assert len(second) == 5
    assert {p.id for p in second} == {p.id for p in first}
