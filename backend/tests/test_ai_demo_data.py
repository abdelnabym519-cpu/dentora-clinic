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
                "MV",
                "V",
                "DV",
                "ML",
                "L",
                "DL",
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
        (await db_session.execute(select(Patient).where(Patient.id.in_(AI_DEMO_PATIENT_IDS))))
        .scalars()
        .all()
    )
    assert len(first) == 5

    # Second run: sentinel short-circuits, zero duplicates.
    await seed_ai_demo_cases(db_session, dentist_id=USER_DENTIST_ID)
    await db_session.commit()
    second = (
        (await db_session.execute(select(Patient).where(Patient.id.in_(AI_DEMO_PATIENT_IDS))))
        .scalars()
        .all()
    )
    assert len(second) == 5
    assert {p.id for p in second} == {p.id for p in first}


# --- Demo-user authentication reconciliation --------------------------------


@pytest.mark.asyncio
async def test_seeder_reconciles_stale_demo_credentials(db_session) -> None:
    """A pre-existing demo database whose users kept stale passwords must
    be repaired to the documented credential through the real bcrypt
    mechanism — preserving id, membership and role."""
    from sqlalchemy import select

    from app.core.auth.models import ClinicMembership, User
    from app.core.auth.service import hash_password, verify_password
    from app.seeds.demo_data import CLINIC_ID, USER_DENTIST_ID
    from scripts.seed_demo import DEMO_PASSWORD, _ensure_module_registry, reconcile_demo_users

    await _seed_pre_ai_demo_base(db_session)
    # stale credential on the existing dentist
    found = await db_session.execute(select(User).where(User.id == USER_DENTIST_ID))
    dentist = found.scalar_one()
    dentist.password_hash = hash_password("StaleLegacyPass1!")
    dentist.is_active = True
    await db_session.commit()
    original_id = dentist.id

    _ensure_module_registry()
    created, repaired = await reconcile_demo_users(db_session)
    await db_session.commit()

    assert created >= 1  # the other four demo users were missing
    assert any("credentials" in r for r in repaired)
    refreshed = (await db_session.execute(select(User).where(User.id == original_id))).scalar_one()
    assert verify_password(DEMO_PASSWORD, refreshed.password_hash)
    assert not verify_password("StaleLegacyPass1!", refreshed.password_hash)
    membership = (
        await db_session.execute(
            select(ClinicMembership).where(
                ClinicMembership.user_id == original_id,
                ClinicMembership.clinic_id == CLINIC_ID,
            )
        )
    ).scalar_one()
    assert membership.role == "dentist"


@pytest.mark.asyncio
async def test_seeder_user_reconciliation_is_idempotent_and_preserves_valid_hash(
    db_session,
) -> None:
    """When credentials already verify, reconcile must not rewrite the
    bcrypt hash (bcrypt salts differ per call — a rewrite is observable)."""
    from sqlalchemy import select

    from app.core.auth.models import User
    from app.core.auth.service import verify_password
    from app.seeds.demo_data import USER_DENTIST_ID
    from scripts.seed_demo import DEMO_PASSWORD, _ensure_module_registry, reconcile_demo_users

    await _seed_pre_ai_demo_base(db_session)
    _ensure_module_registry()
    created, repaired = await reconcile_demo_users(db_session)
    await db_session.commit()
    assert created >= 1  # first pass creates the missing demo users

    dentist = (
        await db_session.execute(select(User).where(User.id == USER_DENTIST_ID))
    ).scalar_one()
    assert verify_password(DEMO_PASSWORD, dentist.password_hash)
    stable_hash = dentist.password_hash

    created2, repaired2 = await reconcile_demo_users(db_session)
    await db_session.commit()
    assert created2 == 0 and repaired2 == []
    refreshed = (
        await db_session.execute(select(User).where(User.id == USER_DENTIST_ID))
    ).scalar_one()
    assert refreshed.password_hash == stable_hash, "valid hash must not be rewritten"


# --- Case Intelligence lock-release regression -------------------------------


@pytest.mark.asyncio
async def test_case_intelligence_fast_path_releases_patient_lock(db_session) -> None:
    """The unchanged-snapshot fast path must commit (release the patient
    FOR UPDATE lock) before returning: AI generators continue using the
    same session for unbounded LLM calls, and every concurrent Case
    Intelligence GET takes the same patient lock. Regression for the
    browser TimeoutError on GET /case_intelligence/patients/{id}."""
    import importlib
    import pathlib

    from sqlalchemy import text

    from app.core.plugins.service import ModuleService
    from app.database import async_session_maker
    from app.modules.case_intelligence.service import CaseIntelligenceService
    from app.seeds.demo_data import CLINIC_ID
    from scripts.seed_demo import _ensure_module_registry

    for path in sorted(pathlib.Path("app/modules").glob("*/models.py")):
        importlib.import_module(".".join(path.with_suffix("").parts))
    _ensure_module_registry()
    await ModuleService(db_session).reconcile_with_db()
    await _seed_pre_ai_demo_base(db_session)

    patient_id = "f4eebc99-9c0b-4ef8-bb6d-6bb9bd380a64"
    from uuid import UUID

    from app.modules.patients.models import Patient

    db_session.add(
        Patient(
            id=UUID(patient_id),
            clinic_id=CLINIC_ID,
            first_name="Amina",
            last_name="Hassan (SYNTHETIC)",
            status="active",
        )
    )
    await db_session.commit()

    # 1st call materializes (slow path commits by design); 2nd call is the
    # unchanged-snapshot fast path — the defect left its lock open here.
    first = await CaseIntelligenceService.get_current(
        db_session, clinic_id=CLINIC_ID, patient_id=UUID(patient_id), user_id=None
    )
    second = await CaseIntelligenceService.get_current(
        db_session, clinic_id=CLINIC_ID, patient_id=UUID(patient_id), user_id=None
    )
    assert second.case_snapshot_version == first.case_snapshot_version

    # A second session must be able to take the same patient row lock
    # immediately (NOWAIT fails loudly while the first session holds it).
    async with async_session_maker() as other:
        row = await other.execute(
            text("SELECT id FROM patients WHERE id = :pid FOR UPDATE NOWAIT"),
            {"pid": patient_id},
        )
        assert row.scalar_one() is not None
