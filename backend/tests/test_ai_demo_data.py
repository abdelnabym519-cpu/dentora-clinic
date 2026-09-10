"""Regression: the synthetic AI-demo dataset stays valid and honest.

Locks the invariants the AI-activation demo relies on: unique fixed IDs,
clear SYNTHETIC marking on every case, medically coherent completeness for
the "complete" case, a closed periodontogram payload with the module's
site codes, and a deterministic STL fixture that passes the dental_3d
mesh content validation.
"""

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
