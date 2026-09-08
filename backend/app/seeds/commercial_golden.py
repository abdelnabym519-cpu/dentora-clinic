"""Dentora Commercial Demo — Golden Demo Patient seed (focused, idempotent).

This is the first slice of the Dentora Commercial Sales Demo seed. It is a
*directed* add-on on top of the broad demo cascade (``scripts/seed-demo.sh``):

    ./scripts/seed-commercial-demo.sh      # base seed (no-op if present) + this module

Why only a "focused" slice?
    The full commercial dataset spans every one of the 39 modules, and most of
    the breadth is already produced by the proven base seed (clinic, users,
    15 patients, catalog, odontogram, treatment plans, budgets, invoices,
    agenda, clinical notes, timeline, schedules, recalls). The genuinely
    missing piece for an AI sales demo is a clearly-marked **Golden Demo
    Patient** whose source clinical state is rich, coherent and *feeds* the AI
    engines:

        case_intelligence ─→ reads odontogram + periodontogram + notes + medical
        risk_engine        ─→ derives risk from the same source state
        ai_treatment_planning / ai_case_summary / ai_clinical_report /
        ai_second_review / clinical_copilot / patient_presentation_mode
                           ─→ all consume the patient's clinical context

    ``case_intelligence`` and ``risk_engine`` do **not** have seedable "input"
    tables — they persist append-only *engine outputs* (``CaseSnapshotRecord``,
    ``RiskResultRecord``). Their inputs are exactly the source rows this module
    creates, so the seed only ever writes *inputs*, never AI results. That keeps
    the "no fake AI / no hardcoded results" rule intact.

Guarantees
    * Deterministic — every entity uses a fixed UUID from the DEMO namespace.
    * Idempotent    — each entity is upserted by id (create-or-repair, no dupes).
    * Synthetic     — all data is fictional and de-identified; the patient is
      explicitly tagged ``DEMO`` in its notes and e-mail domain.
    * Demo-scoped   — writes only to the single demo clinic and its own ids.
    * No destructive reset, no schema drop, no AI output fabrication.

Modules created data for (input side):
    patients, patients_clinical, odontogram, periodontogram (when installed),
    patient_timeline (when installed). Other modules are fed transitively when
    their AI engines run on this patient's source state.

Usage (inside the backend container):
    PYTHONPATH=/app python -m app.seeds.commercial_golden
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.database import async_session_maker
from app.modules.odontogram.models import ToothRecord
from app.modules.patients.models import Patient
from app.modules.patients_clinical.models import (
    Allergy,
    EmergencyContact,
    MedicalContext,
    Medication,
    SurgicalHistory,
    SystemicDisease,
)
from app.modules.patient_timeline.models import PatientTimeline
from app.seeds.demo_data import (
    CLINIC_ID,
    USER_ADMIN_ID,
    USER_DENTIST_ID,
    USER_HYGIENIST_ID,
)

# ---------------------------------------------------------------------------
# DEMO namespace (fixed, deterministic ids — all fictional)
# ---------------------------------------------------------------------------
# The Golden patient is a 47-year-old adult presenting a coherent story that an
# AI case demo can reason about: generalized chronic periodontitis, missing #36,
# a type-2 diabetes co-morbidity and a treated carious quadrant.
GOLDEN_PATIENT_ID = UUID("d4eebc99-9c0b-4ef8-1001-6bb9bd380a99")
GOLDEN_EMAIL = "golden.demo.patient@demo.clinic"
GOLDEN_DOB = date(1978, 4, 12)
GOLDEN_GENDER = "female"

# Id ranges used to derive per-child uuids deterministically.
_BASE = UUID("e5eebc99-9c0b-4ef8-2001-6bb9bd380a00")


def _uuid(offset: int) -> UUID:
    """Deterministic uuid in the golden demo namespace (low 32 bits = offset)."""
    return UUID(int=_BASE.int + offset)


# ---------------------------------------------------------------------------
# Demo marker helpers
# ---------------------------------------------------------------------------
GOLDEN_DEMO_NOTE = (
    "DEMO — synthetic, de-identified commercial-sales patient. "
    "Do not treat as a real medical record."
)


async def _module_is_installed(db: AsyncSession, name: str) -> bool:
    """True when ``core_module`` has the module in the ``installed`` state."""
    from app.core.plugins.db_models import ModuleRecord
    from app.core.plugins.state import ModuleState

    result = await db.execute(select(ModuleRecord).where(ModuleRecord.name == name))
    record = result.scalar_one_or_none()
    return record is not None and record.state == ModuleState.INSTALLED.value


async def _require_demo_clinic_and_users(db: AsyncSession) -> dict[str, User]:
    """Return the demo clinic + core users; raise an actionable error if absent."""
    clinic = await db.get(Clinic, CLINIC_ID)
    if clinic is None:
        raise RuntimeError(
            "Demo clinic not found. Run `./scripts/seed-demo.sh` first (the "
            "commercial golden seed builds on the base demo clinic)."
        )

    users: dict[str, User] = {}
    for key, uid in (
        ("admin", USER_ADMIN_ID),
        ("dentist", USER_DENTIST_ID),
        ("hygienist", USER_HYGIENIST_ID),
    ):
        user = await db.get(User, uid)
        if user is None:
            raise RuntimeError(
                f"Demo user '{key}' ({uid}) not found. Run "
                "`./scripts/seed-demo.sh` first so the demo users exist."
            )
        users[key] = user
    return users


# ---------------------------------------------------------------------------
# Patient + normalized clinical rows
# ---------------------------------------------------------------------------
async def _ensure_patient(db: AsyncSession) -> tuple[Patient, bool]:
    """Upsert the Golden Demo Patient (create-or-repair by fixed id)."""
    patient = await db.get(Patient, GOLDEN_PATIENT_ID)
    created = patient is None
    if patient is None:
        patient = Patient(id=GOLDEN_PATIENT_ID, clinic_id=CLINIC_ID)
        db.add(patient)

    patient.first_name = "Golden"
    patient.last_name = "Demo Patient"
    patient.phone = "+34 600 000 000"
    patient.email = GOLDEN_EMAIL
    patient.date_of_birth = GOLDEN_DOB
    patient.gender = GOLDEN_GENDER
    patient.status = "active"
    patient.preferred_language = "en"
    patient.profession = "Teacher"
    patient.workplace = "Synthetic Public School"
    patient.do_not_contact = False
    patient.notes = GOLDEN_DEMO_NOTE
    return patient, created


async def _ensure_patients_clinical(db: AsyncSession) -> int:
    """Upsert the normalized patients_clinical rows (medical + emergency)."""
    made = 0

    mc = await db.get(MedicalContext, _uuid(10))
    if mc is None:
        mc = MedicalContext(id=_uuid(10), patient_id=GOLDEN_PATIENT_ID, clinic_id=CLINIC_ID)
        db.add(mc)
        made += 1
    mc.is_pregnant = False
    mc.pregnancy_week = None
    mc.is_lactating = False
    mc.is_on_anticoagulants = False
    mc.anticoagulant_medication = None
    mc.inr_value = None
    mc.last_inr_date = None
    mc.is_smoker = True
    mc.smoking_frequency = "daily (10-15/day)"
    mc.alcohol_consumption = "occasional"
    mc.bruxism = True
    mc.adverse_reactions_to_anesthesia = False
    mc.anesthesia_reaction_details = None

    def _upsert(model, offset: int, **fields) -> None:
        nonlocal made
        row = db.get(model, _uuid(offset))
        if row is None:
            row = model(id=_uuid(offset), patient_id=GOLDEN_PATIENT_ID, clinic_id=CLINIC_ID)
            db.add(row)
            made += 1
        for k, v in fields.items():
            setattr(row, k, v)

    _upsert(
        SystemicDisease,
        11,
        name="Diabetes mellitus type 2",
        type="metabolic",
        diagnosis_date=date(2019, 9, 1),
        is_controlled=True,
        is_critical=False,
        medications="Metformin 850 mg",
        notes="Controlled T2DM; relevant to implant and periodontal planning.",
    )
    _upsert(
        Allergy,
        12,
        name="Penicillin",
        type="medication",
        severity="moderate",
        reaction="Skin rash",
        notes="Avoid beta-lactam antibiotics.",
    )
    _upsert(
        Medication,
        13,
        name="Metformin",
        dosage="850 mg",
        frequency="twice daily",
        start_date=date(2019, 9, 1),
        notes="For type 2 diabetes.",
    )
    _upsert(
        SurgicalHistory,
        14,
        procedure="Extraction of lower right first molar (#46 site, history)",
        surgery_date=date(2015, 3, 20),
        complications=None,
        notes="Uneventful healing.",
    )
    _upsert(
        EmergencyContact,
        15,
        name="Jordan Demo",
        relationship="spouse",
        phone="+34 600 000 001",
        email="jordan.demo@demo.clinic",
        is_legal_guardian=False,
    )
    return made


# ---------------------------------------------------------------------------
# Odontogram (tooth source state, mirrors base-seed vocabulary)
# ---------------------------------------------------------------------------
_PERMANENT_FDI = [
    18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28,
    38, 37, 36, 35, 34, 33, 32, 31, 41, 42, 43, 44, 45, 46, 47, 48,
]
_MISSING_TOOTH = 36  # extracted due to advanced periodontitis
_SURFACES_HEALTHY = {"M": "healthy", "D": "healthy", "O": "healthy", "V": "healthy", "L": "healthy"}


async def _ensure_odontogram(db: AsyncSession) -> int:
    """Upsert one ToothRecord per present tooth (healthy / missing semantics)."""
    made = 0
    for i, tooth_number in enumerate(_PERMANENT_FDI):
        row = await db.get(ToothRecord, _uuid(100 + i))
        if row is None:
            row = ToothRecord(
                id=_uuid(100 + i), patient_id=GOLDEN_PATIENT_ID, clinic_id=CLINIC_ID
            )
            db.add(row)
            made += 1
        row.tooth_number = tooth_number
        row.tooth_type = "permanent"
        row.is_displaced = False
        row.is_rotated = False
        row.displacement_notes = None
        row.notes = None
        if tooth_number == _MISSING_TOOTH:
            row.general_condition = "missing"
            row.surfaces = {s: "missing" for s in _SURFACES_HEALTHY}
        else:
            row.general_condition = "healthy"
            row.surfaces = dict(_SURFACES_HEALTHY)
    return made


# ---------------------------------------------------------------------------
# Periodontogram — the case_intelligence dependency (closed SEPA snapshot)
# ---------------------------------------------------------------------------
_SITES = ["MV", "V", "DV", "ML", "L", "DL"]

# Per-tooth 6-site probing depths (mm). Only teeth listed here get site rows;
# the rest are simply unrecorded in this exam (mirrors "sites created lazily").
# Story: generalized moderate periodontitis; deep pockets on upper molars and
# lower incisors; #36 already lost; #46 is an implant.
_PERIO_MM: dict[int, list[int]] = {
    16: [6, 5, 5, 7, 6, 6],  # upper-right first molar — deep
    26: [7, 6, 6, 6, 5, 5],  # upper-left first molar — deep
    46: [3, 3, 3, 3, 3, 3],  # implant — healthy, no pockets
    31: [5, 4, 4, 5, 4, 4],  # lower central incisor
    41: [4, 4, 3, 4, 4, 4],
    17: [4, 4, 3, 4, 3, 3],
    27: [4, 3, 3, 4, 4, 4],
    36: None,  # missing — no tooth row
}


async def _ensure_periodontogram(db: AsyncSession, dentist_id: UUID) -> int:
    """Create/repair one *closed* periodontogram snapshot for the golden patient."""
    from app.modules.periodontogram.models import (
        PeriodontogramSnapshot,
        PeriodontogramSite,
        PeriodontogramTooth,
    )

    made = 0
    recorded_at = datetime(2026, 5, 20, 10, 30, tzinfo=UTC)

    snap = await db.get(PeriodontogramSnapshot, _uuid(200))
    if snap is None:
        snap = PeriodontogramSnapshot(
            id=_uuid(200), clinic_id=CLINIC_ID, patient_id=GOLDEN_PATIENT_ID
        )
        db.add(snap)
        made += 1
    snap.status = "closed"
    snap.recorded_at = recorded_at
    snap.recorded_by = dentist_id
    snap.closed_at = recorded_at
    snap.closed_by = dentist_id
    snap.notes = "DEMO synthetic full-mouth periodontal chart (closed SEPA exam)."
    # indices are normally frozen by the module on close; leaving the snapshot
    # with default None is schema-valid (JSONB nullable). We do not fabricate
    # aggregates here — that is the engine's job.
    snap.indices = None

    # One tooth row per present tooth.
    tooth_by_number: dict[int, PeriodontogramTooth] = {}
    present = [n for n in _PERMANENT_FDI if n != _MISSING_TOOTH]
    for i, tooth_number in enumerate(present):
        tooth = await db.get(PeriodontogramTooth, _uuid(300 + i))
        if tooth is None:
            tooth = PeriodontogramTooth(
                id=_uuid(300 + i), snapshot_id=snap.id, tooth_number=tooth_number
            )
            db.add(tooth)
            made += 1
        tooth.is_present = True
        tooth.is_implant = tooth_number == 46
        tooth.mobility = 0 if tooth_number in (16, 26, 31, 41) else None
        tooth.prognosis = "fair" if tooth_number in (16, 26) else (
            "good" if tooth_number == 46 else None
        )
        tooth.furcation_buccal = "II" if tooth_number in (16, 26) else None
        tooth.furcation_lingual = "I" if tooth_number in (16, 26) else None
        tooth.keratinized_gingiva_mm = 3 if tooth_number in (31, 41) else None
        tooth_by_number[tooth_number] = tooth

    # Site rows only for teeth with recorded probing.
    site_i = 0
    for tooth_number, depths in _PERIO_MM.items():
        if depths is None:
            continue
        tooth = tooth_by_number.get(tooth_number)
        if tooth is None:
            continue
        for code, pd in zip(_SITES, depths):
            site = await db.get(PeriodontogramSite, _uuid(500 + site_i))
            if site is None:
                site = PeriodontogramSite(id=_uuid(500 + site_i), snapshot_id=snap.id)
                db.add(site)
                made += 1
            site.tooth_id = tooth.id
            site.tooth_number = tooth_number
            site.site_code = code
            site.probing_depth_mm = pd
            # Clinical sign: bleeding on probing on the deep-pockets teeth.
            site.bleeding_on_probing = pd >= 4 and tooth_number in (16, 26, 31, 41)
            site.plaque = pd >= 4
            site.suppuration = pd >= 6
            site_i += 1

    return made


# ---------------------------------------------------------------------------
# Patient timeline (manual, deterministic events feeding the Activity tab)
# ---------------------------------------------------------------------------
async def _ensure_timeline(db: AsyncSession) -> int:
    """Create a few coherent timeline entries for the golden patient."""
    made = 0
    events = [
        (
            600,
            "visit",
            "appointment.completed",
            "Completed periodontal exam",
            "Full-mouth periodontal charting (SEPA protocol).",
            datetime(2026, 5, 20, 11, 0, tzinfo=UTC),
        ),
        (
            601,
            "clinical",
            "clinical.note.created",
            "Initial periodontal diagnosis",
            "Generalized chronic periodontitis stage III, grade B.",
            datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
        ),
        (
            602,
            "treatment",
            "treatment.planned",
            "Periodontal treatment plan proposed",
            "Scaling & root planing quadrants, review, implant assessment #46.",
            datetime(2026, 5, 21, 9, 0, tzinfo=UTC),
        ),
    ]
    for offset, category, etype, title, desc, occurred in events:
        row = await db.get(PatientTimeline, _uuid(offset))
        if row is None:
            row = PatientTimeline(
                id=_uuid(offset),
                clinic_id=CLINIC_ID,
                patient_id=GOLDEN_PATIENT_ID,
                event_category=category,
                event_type=etype,
                title=title,
                description=desc,
                occurred_at=occurred,
            )
            db.add(row)
            made += 1
    return made


# ---------------------------------------------------------------------------
# Model registration (root-cause fix)
# ---------------------------------------------------------------------------
def _register_all_models() -> None:
    """Register every ORM model before the first mapper configuration.

    Core mappers declare string ``relationship()`` to models that live in other
    modules — e.g. ``Clinic.appointments`` → ``agenda.Appointment``,
    ``Clinic.cabinets`` → ``agenda.Cabinet``, ``TreatmentPlan`` → ``budget``.
    SQLAlchemy resolves those names from the global class registry when mappers
    are configured, which happens automatically on the first DB call.

    In the running app every module is imported by ``load_modules()``
    (``app/core/plugins/loader.py``) so the registry is complete. Alembic and
    the test suite guarantee the same for their standalone processes by
    importing all module models in ``alembic/env.py`` / ``tests/conftest.py``.
    A standalone seed (``python -m app.seeds.commercial_golden``) runs in a
    fresh process that performs none of that, so it must import the module
    models itself. Without this the very first ``db.get``/``select`` triggers
    ``configure_mappers()`` on a partial registry and fails with e.g.
    ``InvalidRequestError: expression 'Appointment' failed to locate a name``.
    """
    import importlib
    import logging
    import pkgutil
    from pathlib import Path

    logger = logging.getLogger(__name__)

    # Core model modules referenced by core mappers (mirror alembic/env.py).
    for mod in (
        "app.core.agents.models",
        "app.core.auth.models",
        "app.core.plugins.db_models",
        "app.core.retrieval.models",
        "app.core.tenancy.models",
    ):
        importlib.import_module(mod)

    modules_dir = Path(__file__).resolve().parents[1] / "modules"
    for info in pkgutil.iter_modules([str(modules_dir)]):
        if not info.ispkg:
            continue
        try:
            importlib.import_module(f"app.modules.{info.name}.models")
        except ModuleNotFoundError as exc:
            # No ``models`` module for this package (logic-only) — skip it.
            if exc.name == f"app.modules.{info.name}.models":
                continue
            logger.warning("Could not import %s.models: %s", info.name, exc)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not import %s.models: %s", info.name, exc)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
async def run(db: AsyncSession) -> dict:
    """Run the idempotent golden-patient seed. Returns per-step created counts.

    ``db`` must be an active session (commit is left to the caller). The
    standalone ``main`` opens + commits a session and calls this.
    """
    # Register every ORM model before the first query so mapper configuration
    # succeeds (see _register_all_models docstring). Idempotent — importing an
    # already-imported module is a no-op.
    _register_all_models()

    users = await _require_demo_clinic_and_users(db)

    counts: dict[str, int] = {"patient": 0, "patients_clinical": 0, "odontogram": 0,
                              "periodontogram": 0, "patient_timeline": 0}

    _, counts["patient"] = await _ensure_patient(db)
    counts["patients_clinical"] = await _ensure_patients_clinical(db)
    counts["odontogram"] = await _ensure_odontogram(db)

    if await _module_is_installed(db, "periodontogram"):
        counts["periodontogram"] = await _ensure_periodontogram(db, users["dentist"].id)
    else:
        counts["periodontogram"] = -1  # module not installed → skipped

    if await _module_is_installed(db, "patient_timeline"):
        counts["patient_timeline"] = await _ensure_timeline(db)
    else:
        counts["patient_timeline"] = -1

    return counts


async def main() -> None:
    """Standalone CLI entry point (runs inside the backend container)."""
    async with async_session_maker() as db:
        counts = await run(db)
        await db.commit()
    _print_summary(counts)


def _print_summary(counts: dict[str, int]) -> None:
    print("\n" + "=" * 60)
    print("Dentora Commercial Demo — Golden Demo Patient")
    print("=" * 60)
    labels = {
        "patient": "Golden patient",
        "patients_clinical": "Patients_clinical rows",
        "odontogram": "Odontogram tooth records",
        "periodontogram": "Periodontogram rows (teeth+sites)",
        "patient_timeline": "Patient timeline events",
    }
    for key, label in labels.items():
        n = counts.get(key, 0)
        state = f"{n} created" if n >= 0 else "module not installed — skipped"
        print(f"  {label:<38} {state}")
    print("-" * 60)
    print(f"  Patient : {GOLDEN_PATIENT_ID}")
    print(f"  Email   : {GOLDEN_EMAIL}  (password: n/a — login via demo users)")
    print("=" * 60)
    print("Re-run is safe: every row is upserted by its fixed id (no duplicates).\n")


if __name__ == "__main__":
    asyncio.run(main())
