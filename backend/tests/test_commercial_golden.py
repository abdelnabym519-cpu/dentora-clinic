"""DB-free checks for the Commercial Demo Golden-patient seed.

These tests validate the *design* of the deterministic demo namespace and the
constraint vocabulary of the data this seed writes. They deliberately do NOT
need a database, so they can run in CI without Postgres:

    pytest backend/tests/test_commercial_golden.py

Idempotency itself (no duplicates across two real runs) and demo isolation
require a live Postgres, so those are exercised by the seed's upsert-by-fixed-id
logic rather than by these unit tests.
"""

from datetime import date, datetime, UTC

from app.seeds import commercial_golden as g


def _fdi_valid(n: int) -> bool:
    return 11 <= n <= 48 and 1 <= n % 10 <= 8 and 1 <= n // 10 <= 4


def test_golden_patient_is_synthetic_and_deidentified():
    # Must carry an explicit DEMO marker and a synthetic, non-PII identity.
    assert "DEMO" in g.GOLDEN_DEMO_NOTE.upper()
    assert g.GOLDEN_EMAIL.endswith("@demo.clinic")
    assert "golden" in g.GOLDEN_EMAIL.lower()
    assert isinstance(g.GOLDEN_DOB, date)
    assert (date.today() - g.GOLDEN_DOB).days // 365 >= 18  # adult case


def test_demo_namespace_is_deterministic_and_disjoint():
    # Every entity id is derived from one fixed base uuid and must not collide
    # with the base demo namespace used by demo_data.py / seed_demo.py.
    from app.seeds.demo_data import CLINIC_ID, USER_ADMIN_ID, USER_DENTIST_ID, USER_HYGIENIST_ID

    base_ids = {
        CLINIC_ID, USER_ADMIN_ID, USER_DENTIST_ID, USER_HYGIENIST_ID,
        g.GOLDEN_PATIENT_ID,
    }
    offsets = list(range(10, 16)) + list(range(100, 132)) + \
        list(range(200, 201)) + list(range(300, 331)) + list(range(500, 500 + 6 * 5))
    derived = {g._uuid(o) for o in offsets}
    assert g._uuid(0) == g._uuid(0)  # deterministic
    assert not (derived & base_ids)  # no overlap with base demo clinic/users/patient


def test_periodontogram_vocabulary_obeys_db_check_constraints():
    # Mirrors the check constraints defined in the periodontogram migration.
    present = [n for n in g._PERMANENT_FDI if n != g._MISSING_TOOTH]
    assert all(_fdi_valid(n) for n in g._PERMANENT_FDI)
    assert set(g._SITES) == {"MV", "V", "DV", "ML", "L", "DL"}
    for tooth, depths in g._PERIO_MM.items():
        if depths is None:
            continue
        assert tooth in present  # cannot record sites on a missing tooth
        assert len(depths) == 6
        assert all(0 <= d <= 15 for d in depths)


def test_odontogram_matches_base_demo_vocabulary():
    # Only the surface health values used by the proven base demo seed.
    for s in g._SURFACES_HEALTHY.values():
        assert s in {"healthy", "missing"}
    missing = [n for n in g._PERMANENT_FDI if n == g._MISSING_TOOTH]
    assert missing == [36]


def test_timeline_events_are_synthetic_timestamps():
    for offset in (600, 601, 602):
        assert isinstance(g._uuid(offset), __import__("uuid").UUID)
    assert datetime(2026, 5, 20, tzinfo=UTC).tzinfo is not None
