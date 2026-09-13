#!/usr/bin/env python3
"""Drive the real geometry + clinical-AI chain against a running backend.

This is DEVELOPMENT/TEST tooling. It performs no mocking: every step is a
real authenticated HTTP call to a live Dentora backend, which runs the real
ingestion, registration, deterministic engines and LLM pipeline. It exists
because "the code looks right" is not evidence — the modules in the AI
activation chain are gated on each other, and the only way to know whether
a gate is satisfied is to walk the chain and look at what comes back.

The chain, in dependency order:

    IOS mesh ingest -> CBCT DICOM ingest -> segmentation (+ dentist review)
      -> nerve detection (+ dentist review, optional inference service)
      -> IOS->CBCT alignment (+ DENTIST ACCEPTANCE)
      -> scene reflects real geometry
      -> risk engine / 3D risk map
      -> implant planning (evaluates against accepted geometry)
      -> orthodontic simulator capability + simulation
      -> AI case summary -> treatment plan draft -> simulation
      -> second review -> clinical report -> copilot advisory

Human-in-the-loop is preserved by construction: nothing here writes an
``accepted``/``approved`` flag directly, every review state is produced by
the module's own review endpoint under a dentist token, and AI outputs stay
``review_status="suggested"``.

Fixtures come from the sibling development-fixture scripts, which generate
clearly-labelled synthetic geometry (never real patient data)::

    python -m scripts.build_ios_development_fixture  --out-dir /tmp/dentora_fix
    python -m scripts.build_cbct_development_fixture --mesh /tmp/dentora_fix/scan_maxillary.stl \
        --out-dir /tmp/dentora_fix/cbct

Usage::

    python -m scripts.verify_ai_geometry_chain \
        --base-url http://localhost:8100 \
        --email dentist@demo.clinic --password demo1234 \
        --ios /tmp/dentora_fix/scan_maxillary.stl \
        --cbct-dir /tmp/dentora_fix/cbct

    # geometry only (no LLM provider needed):
    python -m scripts.verify_ai_geometry_chain --steps geometry ...

Exit status is 0 when every attempted step passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

PASS, FAIL, SKIP, INFO = "PASS", "FAIL", "SKIP", "INFO"


@dataclass
class Chain:
    """Step outcomes plus the evidence collected along the way."""

    results: list[tuple[str, str, str]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def record(self, step: str, status: str, detail: str = "") -> None:
        self.results.append((step, status, detail))
        marker = {"PASS": "+", "FAIL": "x", "SKIP": "-", "INFO": "i"}[status]
        print(f"  [{marker}] {status:<4} {step}" + (f" — {detail}" if detail else ""))

    def note(self, label: str, value: Any) -> None:
        self.evidence[label] = value
        print(f"      {label}: {value}")

    @property
    def failed(self) -> list[tuple[str, str, str]]:
        return [r for r in self.results if r[1] == FAIL]


class Api:
    """A thin authenticated client that surfaces backend errors verbatim."""

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 300.0):
        self.base = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)
        self.token = token

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request(self, method: str, path: str, headers: dict | None = None, **kwargs):
        merged = self._headers()
        if headers:
            merged.update(headers)
        response = self.client.request(method, f"{self.base}{path}", headers=merged, **kwargs)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, response.text[:600]

    def get(self, path: str) -> tuple[int, Any]:
        return self.request("GET", path)

    def post(self, path: str, payload: Any = None, **kwargs) -> tuple[int, Any]:
        if payload is not None:
            kwargs["json"] = payload
        return self.request("POST", path, **kwargs)


def _data(body: Any) -> Any:
    """Unwrap the ``ApiResponse`` envelope (``{"data": ..., "message": ...}``)."""
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def _detail(body: Any) -> str:
    """A compact, readable rendering of a failure body."""
    if isinstance(body, dict):
        for key in ("detail", "message", "error"):
            if key in body:
                value = body[key]
                if isinstance(value, dict):
                    return json.dumps(value)[:400]
                return str(value)[:400]
        return json.dumps(body)[:400]
    return str(body)[:400]


# --- steps ----------------------------------------------------------------


def step_login(chain: Chain, api: Api, email: str, password: str) -> bool:
    print("\n[1] Authenticate as the dentist (reviews must be dentist-made)")
    status, body = api.request(
        "POST",
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if status != 200:
        chain.record("login", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    token = body.get("access_token")
    if not token:
        chain.record("login", FAIL, f"no access_token in response: {str(body)[:200]}")
        return False
    api.token = token
    chain.record("login", PASS, email)

    status, body = api.get("/api/v1/auth/me")
    if status == 200:
        me = _data(body) or {}
        # /auth/me returns {user, clinics: [{id, name, role}], permissions: [...]}
        clinics = me.get("clinics") or []
        role = clinics[0].get("role") if clinics else (me.get("role") or "?")
        chain.note("authenticated as", (me.get("user") or {}).get("email"))
        chain.note("clinic", clinics[0].get("name") if clinics else "?")
        chain.note("authenticated role", role)
        chain.note("permissions granted", len(me.get("permissions") or []))
        if "dentist" not in str(role).lower():
            chain.record("role", FAIL, f"expected a dentist for review steps, got {role!r}")
            return False
    else:
        chain.record("auth/me", INFO, f"HTTP {status} (role not verified)")
    return True


def step_resolve_patient(chain: Chain, api: Api, patient_id: str | None, search: str) -> str | None:
    print("\n[2] Resolve the real test patient")
    if patient_id:
        status, body = api.get(f"/api/v1/patients/{patient_id}")
        if status != 200:
            chain.record("patient", FAIL, f"HTTP {status} for {patient_id}: {_detail(body)}")
            return None
        patient = _data(body)
        chain.note(
            "patient", f"{patient.get('id')} {patient.get('first_name')} {patient.get('last_name')}"
        )
        chain.record("patient", PASS, "explicit --patient-id")
        return str(patient["id"])

    status, body = api.get(f"/api/v1/patients?search={search}&page_size=25")
    if status != 200:
        chain.record("patient search", FAIL, f"HTTP {status}: {_detail(body)}")
        return None
    payload = _data(body) or {}
    items = payload.get("items") if isinstance(payload, dict) else payload
    items = items or []
    if not items:
        chain.record(
            "patient search", FAIL, f"no patient matches {search!r} — seed demo data first"
        )
        return None
    # Prefer the AI demo case: it carries the clinical evidence the
    # case-summary/planning chain needs.
    chosen = next(
        (p for p in items if "demo" in f"{p.get('first_name')} {p.get('last_name')}".lower()),
        items[0],
    )
    chain.note(
        "patient", f"{chosen.get('id')} {chosen.get('first_name')} {chosen.get('last_name')}"
    )
    chain.note("candidates", len(items))
    chain.record("patient", PASS, search)
    return str(chosen["id"])


def step_scene_baseline(chain: Chain, api: Api, pid: str) -> None:
    print("\n[3] Scene baseline before any geometry is ingested")
    status, body = api.get(f"/api/v1/dental_3d/patients/{pid}/scene")
    if status != 200:
        chain.record("scene baseline", FAIL, f"HTTP {status}: {_detail(body)}")
        return
    scene = _data(body) or {}
    meshes = scene.get("meshes") or []
    sources = sorted({str(m.get("source")) for m in meshes}) or ["(none)"]
    chain.note("mesh count", len(meshes))
    chain.note("mesh sources", ", ".join(sources))
    chain.note("scene generator", scene.get("generator") or scene.get("source") or "?")
    chain.record("scene baseline", PASS, "pre-ingestion state recorded")


def step_upload_ios(chain: Chain, api: Api, pid: str, ios_path: Path) -> str | None:
    print("\n[4] Ingest the IOS mesh through the real upload endpoint")
    if not ios_path.exists():
        chain.record("IOS upload", FAIL, f"{ios_path} does not exist")
        return None
    raw = ios_path.read_bytes()
    chain.note("file", f"{ios_path.name} ({len(raw)} bytes)")
    status, body = api.post(
        f"/api/v1/dental_3d/patients/{pid}/meshes",
        files={"file": (ios_path.name, raw, "model/stl")},
        data={"title": "Development IOS fixture (synthetic)"},
    )
    if status not in (200, 201):
        chain.record("IOS upload", FAIL, f"HTTP {status}: {_detail(body)}")
        return None
    mesh = _data(body) or {}
    document_id = mesh.get("document_id")
    chain.note("mesh source", mesh.get("source"))
    chain.note("format", mesh.get("format"))
    chain.note("vertex_count", mesh.get("vertex_count"))
    chain.note("document_id", document_id)
    if not document_id:
        chain.record("IOS upload", FAIL, "response carries no document_id (alignment needs it)")
        return None
    chain.record("IOS upload", PASS, "real mesh document stored via the media module")
    return str(document_id)


def step_upload_cbct(chain: Chain, api: Api, pid: str, cbct_dir: Path) -> str | None:
    print("\n[5] Ingest the CBCT series instance by instance")
    manifest_path = cbct_dir / "fixture_manifest.json"
    if not manifest_path.exists():
        chain.record("CBCT ingest", FAIL, f"{manifest_path} does not exist")
        return None
    manifest = json.loads(manifest_path.read_text())
    series_uid = manifest.get("series_instance_uid")
    files = sorted(cbct_dir.glob("*.dcm"))
    chain.note("series_instance_uid", series_uid)
    chain.note("frame_of_reference_uid", manifest.get("frame_of_reference_uid"))
    chain.note("instances", len(files))
    if not files:
        chain.record("CBCT ingest", FAIL, "no .dcm files in the fixture directory")
        return None

    accepted = 0
    for path in files:
        status, body = api.post(
            f"/api/v1/dental_3d/patients/{pid}/cbct/dicom-instances",
            files={"file": (path.name, path.read_bytes(), "application/dicom")},
            data={"title": "Development CBCT fixture (synthetic)"},
        )
        if status not in (200, 201):
            chain.record("CBCT ingest", FAIL, f"{path.name}: HTTP {status}: {_detail(body)}")
            return None
        accepted += 1
    chain.note("instances accepted", accepted)
    chain.record("CBCT ingest", PASS, f"{accepted} DICOM instances normalized and stored")
    return str(series_uid)


def step_segmentation(chain: Chain, api: Api, pid: str) -> bool:
    print("\n[6] Deterministic segmentation, then dentist review")
    status, body = api.post(f"/api/v1/dental_3d/patients/{pid}/segmentation", {})
    if status not in (200, 201):
        chain.record("segmentation", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    result = _data(body) or {}
    analysis_id = result.get("analysis_id") or result.get("id")
    teeth = result.get("teeth") or []
    chain.note("analysis_id", analysis_id)
    chain.note("teeth segmented", len(teeth))
    chain.note("review_status", result.get("review_status") or result.get("status"))
    chain.note("confidence", result.get("confidence"))
    chain.record("segmentation", PASS, f"{len(teeth)} teeth")

    if not analysis_id:
        chain.record("segmentation review", FAIL, "no analysis id to review")
        return False
    status, body = api.post(
        f"/api/v1/dental_3d/patients/{pid}/segmentation/{analysis_id}/review",
        {"decision": "accepted", "note": "Development fixture verification."},
    )
    if status != 200:
        chain.record("segmentation review", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    reviewed = _data(body) or {}
    chain.note(
        "review_status after dentist decision",
        reviewed.get("review_status") or reviewed.get("status"),
    )
    chain.record("segmentation review", PASS, "accepted by the dentist token")
    return True


def step_nerve_detection(chain: Chain, api: Api, pid: str, series_uid: str | None) -> str:
    """Run nerve detection; report geometry or the documented unavailable state.

    Without the optional operator-managed inference service the module must
    return an explicit unavailable/``missing_model`` state rather than
    inventing a canal. Both outcomes are correct behaviour, so this step
    never fails on the unavailable branch — it records which one happened.
    """
    print("\n[7] Nerve / mandibular-canal detection (+ dentist review when available)")
    payload = {"series_instance_uid": series_uid} if series_uid else {}
    status, body = api.post(f"/api/v1/dental_3d/patients/{pid}/nerve-detection", payload)
    if status not in (200, 201):
        detail = _detail(body)
        lowered = detail.lower()
        if any(token in lowered for token in ("missing_model", "unavailable", "inference")):
            chain.record(
                "nerve detection",
                SKIP,
                f"explicit unavailable state (no inference service): {detail[:160]}",
            )
            return "unavailable"
        chain.record("nerve detection", FAIL, f"HTTP {status}: {detail}")
        return "failed"

    result = _data(body) or {}
    analysis_id = result.get("analysis_id") or result.get("id")
    state = result.get("status") or result.get("state") or result.get("availability")
    failure = result.get("failure") or {}
    chain.note("analysis_id", analysis_id)
    chain.note("state", state)
    chain.note("review_status", result.get("review_status"))
    if failure:
        chain.note("failure", f"{failure.get('code')}: {failure.get('message')}")
    for key in ("canal_points", "nerve_points", "points", "centerline", "pathways"):
        if isinstance(result.get(key), list):
            chain.note(f"{key} count", len(result[key]))

    if state == "failed" and failure.get("code") in ("missing_model", "dependency_unavailable"):
        # Correct fail-closed behaviour: no operator-managed nerve inference
        # service is configured, so no canal geometry is invented. Implant
        # planning then evaluates without a canal, which the module reports
        # explicitly rather than silently guessing.
        chain.record(
            "nerve detection",
            SKIP,
            f"fail-closed, no inference service configured: {failure.get('message')}",
        )
        return "missing_model"
    if state == "failed":
        chain.record("nerve detection", FAIL, f"{failure.get('code')}: {failure.get('message')}")
        return "failed"
    chain.record("nerve detection", PASS, f"state={state}")

    if analysis_id:
        status, body = api.post(
            f"/api/v1/dental_3d/patients/{pid}/nerve-detection/{analysis_id}/review",
            {"decision": "accepted", "note": "Development fixture verification."},
        )
        if status == 200:
            chain.record("nerve review", PASS, "accepted by the dentist token")
        else:
            chain.record("nerve review", INFO, f"HTTP {status}: {_detail(body)}")
    return "accepted"


def step_alignment(
    chain: Chain, api: Api, pid: str, mesh_document_id: str, series_uid: str
) -> str | None:
    print("\n[8] Real IOS→CBCT registration, then DENTIST ACCEPTANCE")
    payload = {
        "mesh_document_id": mesh_document_id,
        "series_instance_uid": series_uid,
        "ios_units": "mm",
    }
    status, body = api.post(f"/api/v1/dental_3d/patients/{pid}/alignment", payload)
    if status not in (200, 201):
        chain.record("alignment", FAIL, f"HTTP {status}: {_detail(body)}")
        return None
    result = _data(body) or {}
    alignment_id = result.get("alignment_id") or result.get("id")
    chain.note("alignment_id", alignment_id)
    chain.note("status", result.get("status"))
    chain.note("review_status", result.get("review_status"))
    for key in (
        "fitness",
        "rmse_mm",
        "inlier_ratio",
        "source_points",
        "target_points",
        "algorithm",
        "frame_of_reference_uid",
    ):
        if key in result:
            chain.note(key, result[key])
    transform = result.get("transform") or result.get("matrix")
    if transform:
        chain.note(
            "transform (first row)", transform[0] if isinstance(transform, list) else transform
        )
    failure = result.get("failure") or {}
    if result.get("status") == "failed" or failure:
        chain.record(
            "alignment",
            FAIL,
            f"registration failed closed: {failure.get('code')} — {failure.get('message')}",
        )
        return None
    if not transform:
        chain.record("alignment", FAIL, "status is not failed but no transform was returned")
        return None
    metrics = result.get("metrics") or {}
    for key in ("fitness", "inlier_rmse_mm", "rmse_mm", "correspondence_count"):
        if key in metrics:
            chain.note(f"metrics.{key}", metrics[key])
    chain.note("provenance", json.dumps(result.get("provenance") or {})[:260])
    chain.record("alignment", PASS, f"status={result.get('status')} with a real transform")

    if not alignment_id:
        chain.record("alignment acceptance", FAIL, "no alignment id to review")
        return None
    status, body = api.post(
        f"/api/v1/dental_3d/patients/{pid}/alignment/{alignment_id}/review",
        {"decision": "accepted", "note": "Development fixture verification — dentist acceptance."},
    )
    if status != 200:
        chain.record("alignment acceptance", FAIL, f"HTTP {status}: {_detail(body)}")
        return None
    reviewed = _data(body) or {}
    # AlignmentResult carries the review outcome in `status`
    # (pending_review -> accepted); `review_status` is not part of it.
    accepted_status = reviewed.get("status")
    chain.note("status after dentist decision", accepted_status)
    chain.note("reviewed_by", reviewed.get("reviewed_by"))
    chain.note("reviewed_at", reviewed.get("reviewed_at"))
    chain.note("review_note", reviewed.get("review_note"))
    chain.note("requires_review", reviewed.get("requires_review"))
    chain.note("is_clinical", reviewed.get("is_clinical"))
    chain.note("disclaimer", (reviewed.get("disclaimer") or "")[:120])
    if accepted_status != "accepted":
        chain.record("alignment acceptance", FAIL, f"expected accepted, got {accepted_status!r}")
        return None
    chain.record(
        "alignment acceptance",
        PASS,
        f"accepted by dentist {str(reviewed.get('reviewed_by'))[:8]} through the module's own "
        "review endpoint — no flag was written directly",
    )
    return str(alignment_id)


def step_scene_after(chain: Chain, api: Api, pid: str) -> bool:
    print("\n[9] Scene now reflects real ingested geometry")
    status, body = api.get(f"/api/v1/dental_3d/patients/{pid}/scene")
    if status != 200:
        chain.record("scene after", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    scene = _data(body) or {}
    meshes = scene.get("meshes") or []
    sources = sorted({str(m.get("source")) for m in meshes})
    chain.note("mesh count", len(meshes))
    chain.note("mesh sources", ", ".join(sources) or "(none)")
    # "Real geometry" here means the scene serves the ingested scan rather
    # than the procedural fallback: an intraoral_scan mesh backed by a stored
    # document in a real file format. CBCT-derived anatomy is not exposed as
    # a scene mesh by the current Dental3D contract, so it is not required.
    ingested = [
        m
        for m in meshes
        if m.get("source") in ("intraoral_scan", "cbct", "segmentation", "nerve")
        and m.get("document_id")
        and m.get("format") in ("stl", "ply", "obj", "gltf")
    ]
    procedural = [
        m for m in meshes if m.get("format") == "procedural" or m.get("source") == "synthetic"
    ]
    chain.note("meshes backed by an ingested document", len(ingested))
    chain.note("procedural/synthetic fallback meshes", len(procedural))
    for mesh in ingested[:4]:
        chain.note(
            f"  {mesh.get('label') or mesh.get('source')}",
            f"source={mesh.get('source')} format={mesh.get('format')} "
            f"vertices={mesh.get('vertex_count')} document={str(mesh.get('document_id'))[:8]}",
        )
    if not ingested:
        chain.record(
            "scene after", FAIL, "the scene still serves only procedural fallback geometry"
        )
        return False
    chain.record(
        "scene after",
        PASS,
        f"{len(ingested)} mesh(es) served from ingested scan documents "
        f"({len(procedural)} procedural fallback)",
    )
    return True


def step_prosthetic_target(
    chain: Chain,
    api: Api,
    pid: str,
    alignment_id: str,
    frame_uid: str,
    site: tuple[float, float, float],
) -> bool:
    """Create a dentist-defined prosthetic target and have the dentist accept it.

    Implant proposals are ranked *against a prosthetic goal the clinician
    set*, so the target has to exist and be reviewed first — that ordering is
    the module's own gate, not something this script works around.
    """
    print("\n[9b] Dentist-defined prosthetic target (+ its own review)")
    payload = {
        "alignment_id": alignment_id,
        "platform_center": {"x": site[0], "y": site[1], "z": site[2]},
        "axis": {"x": 0.0, "y": 0.0, "z": -1.0},
        "frame_of_reference_uid": frame_uid,
        "source_type": "dentist_defined",
        "source_reference_space": "dicom_patient",
        # The validator requires a dicom_patient source to declare the same
        # Frame of Reference as the target; `dentist_defined` needs no digest
        # or source documents (only registered_ios / prosthetic_scan do).
        "source_frame_of_reference_uid": frame_uid,
        "source_method": "development-fixture-verification",
        "source_identifier": "scripts.verify_ai_geometry_chain",
        "source_document_ids": [],
    }
    chain.note("platform_center (LPS mm)", payload["platform_center"])
    chain.note("axis", payload["axis"])
    status, body = api.post(f"/api/v1/dental_3d/patients/{pid}/prosthetic-targets", payload)
    if status not in (200, 201):
        chain.record("prosthetic target", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    target = _data(body) or {}
    target_id = target.get("id")
    chain.note("target_id", target_id)
    chain.note("status", target.get("status") or target.get("review_status"))
    chain.record("prosthetic target", PASS, "created in the DICOM patient frame")

    status, body = api.post(
        f"/api/v1/dental_3d/patients/{pid}/prosthetic-targets/{target_id}/review",
        {"decision": "accepted", "note": "Development fixture verification."},
    )
    if status != 200:
        chain.record("prosthetic target review", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    reviewed = _data(body) or {}
    state = reviewed.get("status") or reviewed.get("review_status")
    chain.note("status after dentist decision", state)
    chain.note("reviewed_by", reviewed.get("reviewed_by"))
    if state != "accepted":
        chain.record("prosthetic target review", FAIL, f"expected accepted, got {state!r}")
        return False
    chain.record("prosthetic target review", PASS, "accepted by the dentist token")
    return True


def step_risk_engine(chain: Chain, api: Api, pid: str) -> bool:
    print("\n[10] Risk engine + 3D risk map over real geometry")
    status, body = api.post(f"/api/v1/risk_engine/patients/{pid}", {})
    if status not in (200, 201):
        chain.record("risk engine", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    result = _data(body) or {}
    chain.note("result_id", result.get("id"))
    chain.note("contract_version", result.get("contract_version"))
    chain.note("review_status", result.get("review_status"))
    # The risk engine is observed-fact decision support by contract: it has no
    # "overall risk score" field at all, and is_clinical/advisory_only are
    # constants. Report what it actually emits.
    chain.note(
        "advisory_only / requires_review / is_clinical",
        f"{result.get('advisory_only')} / {result.get('requires_review')} / {result.get('is_clinical')}",
    )
    factors = result.get("factors") or []
    evidence = result.get("evidence") or []
    chain.note("factors evaluated", len(factors))
    chain.note("evidence references", len(evidence))
    for factor in factors[:6]:
        chain.note(
            f"  {factor.get('factor_id')}",
            f"state={factor.get('state')} band={factor.get('display_band')} "
            f"observed={factor.get('observed_value')}{factor.get('unit') or ''}",
        )
    risk_map = result.get("risk_map") or {}
    chain.note("risk_map.status", risk_map.get("status"))
    chain.note("risk_map.reason", risk_map.get("reason"))
    chain.note("risk_map.synthetic_geometry", risk_map.get("synthetic_geometry"))
    frame = risk_map.get("frame") or {}
    if frame:
        chain.note(
            "risk_map.frame",
            f"{frame.get('kind')} {frame.get('unit')} for={frame.get('frame_of_reference_uid')}",
        )
    regions = risk_map.get("regions") or []
    chain.note("risk_map.regions", len(regions))
    for region in regions[:4]:
        chain.note(
            f"  region {region.get('region_id')}",
            f"kind={region.get('kind')} band={region.get('display_band')} "
            f"points={len(region.get('points') or [])} radius_mm={region.get('radius_mm')}",
        )
    chain.note("disclaimer", (result.get("disclaimer") or "")[:120])
    if risk_map.get("status") != "available":
        chain.record(
            "risk engine",
            PASS,
            f"ran deterministically; 3D risk map {risk_map.get('status')}: {risk_map.get('reason')}",
        )
    else:
        chain.record(
            "risk engine",
            PASS,
            f"{len(factors)} factors, {len(evidence)} evidence refs, {len(regions)} 3D map regions",
        )
    return True


def step_implant_planning(chain: Chain, api: Api, pid: str) -> bool:
    print("\n[11] Implant planning against the accepted geometry")
    status, body = api.get(f"/api/v1/dental_3d/patients/{pid}/implant-planning")
    if status != 200:
        chain.record("implant planning state", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    state = _data(body) or {}
    chain.note("readiness", state.get("readiness") or state.get("status"))
    for key in ("available", "unavailable_reason", "missing", "geometry", "accepted_alignment"):
        if key in state:
            value = state[key]
            chain.note(
                key, value if not isinstance(value, (dict, list)) else json.dumps(value)[:200]
            )

    # The proposal endpoint is deterministic but needs the clinician's own
    # implant catalog and planning policy: it ranks candidates against them,
    # it does not choose products by itself.
    proposal_request = {
        "catalog": [
            {
                "id": "dev-fixture-4x10",
                "label": "Development fixture implant 4.0 x 10 mm",
                "diameter_mm": 4.0,
                "length_mm": 10.0,
                "dimension_source": "development-fixture",
                "source_identifier": "scripts.build_ios_development_fixture",
            },
            {
                "id": "dev-fixture-4x13",
                "label": "Development fixture implant 4.0 x 13 mm",
                "diameter_mm": 4.0,
                "length_mm": 13.0,
                "dimension_source": "development-fixture",
                "source_identifier": "scripts.build_ios_development_fixture",
            },
        ],
        "policy": {
            "criteria": [
                {"name": "nerve_surface_to_centerline_mm", "direction": "desc"},
                {"name": "prosthetic_offset_mm", "direction": "asc"},
                {"name": "prosthetic_axis_angle_deg", "direction": "asc"},
            ]
        },
    }
    status, body = api.post(
        f"/api/v1/dental_3d/patients/{pid}/implant-plans/proposals", proposal_request
    )
    if status not in (200, 201):
        detail = _detail(body)
        lowered = detail.lower()
        if any(t in lowered for t in ("unavailable", "missing", "not_ready", "requires")):
            chain.record("implant proposal", SKIP, f"explicit readiness gate: {detail[:200]}")
            return True
        chain.record("implant proposal", FAIL, f"HTTP {status}: {detail}")
        return False
    proposal = _data(body) or {}
    chain.note("proposal id", proposal.get("id"))

    # The POST returns the created plan; the module's own GET exposes the full
    # deterministic state (prosthetic readiness + plan + current revision).
    status, state_body = api.get(f"/api/v1/dental_3d/patients/{pid}/implant-planning")
    state = _data(state_body) or {} if status == 200 else {}
    prosthetic = state.get("prosthetic") or {}
    chain.note(
        "prosthetic readiness", f"{prosthetic.get('status')} (reason={prosthetic.get('reason')})"
    )
    plans = state.get("plans") or []
    chain.note("plans", len(plans))
    for plan in plans[:2]:
        revision = plan.get("current_revision") or {}
        cand = revision.get("candidate") or {}
        chain.note("  plan status", plan.get("status"))
        chain.note("  revision", revision.get("revision_number"))
        chain.note(
            "  candidate",
            f"center={cand.get('center')} axis={cand.get('axis')} "
            f"diameter={cand.get('diameter_mm')}mm length={cand.get('length_mm')}mm "
            f"catalog={cand.get('catalog_entry_id')} frame={cand.get('frame_of_reference_uid')}",
        )
        chain.note("  dimension_source", cand.get("dimension_source"))
    if not plans:
        chain.record("implant proposal", FAIL, "proposal accepted but no plan was persisted")
        return False
    states = {str(pl.get("status")) for pl in plans}
    # Human-in-the-loop: a generated plan must stay proposed/draft, never approved.
    if not states <= {"proposed", "draft", "pending_review"}:
        chain.record("implant proposal", FAIL, f"plan auto-advanced past review: {sorted(states)}")
        return False
    chain.record(
        "implant proposal",
        PASS,
        f"deterministic plan generated against the accepted target, left {sorted(states)} "
        "for dentist approval",
    )
    return True


def step_clinical_record(chain: Chain, api: Api, pid: str) -> bool:
    """Enter the clinical-record sections the readiness gate requires.

    ``case_intelligence`` marks ``medical_context``, ``odontogram``,
    ``periodontogram`` and ``treatment_history`` as ``not_available`` for a
    patient that has no clinical record, and the report/copilot readiness gate
    then reports ``clinical_context_insufficient``. These are ordinary
    dentist-entered records created through their own module endpoints, so the
    gate's precondition is satisfied with real data instead of being weakened.

    Values are ordinary-charting fixture data for a clearly synthetic patient.
    """
    print("\n[.] Clinical record (dentist-entered sections)")
    medical = {
        "is_pregnant": False,
        "is_lactating": False,
        "is_on_anticoagulants": False,
        "is_smoker": False,
        "smoking_frequency": "never",
        "alcohol_consumption": "occasional",
        "bruxism": False,
        "adverse_reactions_to_anesthesia": False,
    }
    status, body = api.request(
        "PUT", f"/api/v1/patients_clinical/patients/{pid}/medical-context", json=medical
    )
    if status != 200:
        chain.record("clinical record: medical context", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    chain.record("clinical record: medical context", PASS, "medical_context section available")

    updates = [
        {"tooth_number": 36, "general_condition": "caries", "notes": "Fixture: MOD caries"},
        {"tooth_number": 46, "general_condition": "restored", "notes": "Fixture: composite"},
        {"tooth_number": 35, "general_condition": "healthy"},
        {"tooth_number": 37, "general_condition": "healthy"},
        {"tooth_number": 45, "general_condition": "healthy"},
    ]
    status, body = api.request(
        "PATCH", f"/api/v1/odontogram/patients/{pid}/teeth/bulk", json={"updates": updates}
    )
    if status != 200:
        chain.record("clinical record: odontogram", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    chain.record("clinical record: odontogram", PASS, f"{len(updates)} tooth records written")

    status, body = api.post(f"/api/v1/periodontogram/patients/{pid}/draft")
    if status not in (200, 201):
        chain.record("clinical record: periodontogram", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    snapshot = _data(body) or {}
    snapshot_id = snapshot.get("id")
    charting = {
        36: {"MV": 4, "V": 3, "DV": 4, "ML": 3, "L": 4, "DL": 3},
        46: {"MV": 3, "V": 2, "DV": 3, "ML": 2, "L": 3, "DL": 2},
    }
    sites = 0
    for tooth, depths in charting.items():
        api.request(
            "PATCH",
            f"/api/v1/periodontogram/snapshots/{snapshot_id}/teeth/{tooth}",
            json={"is_present": True, "mobility": 1, "keratinized_gingiva_mm": 3},
        )
        for site_code, depth in depths.items():
            status, _body = api.request(
                "PATCH",
                f"/api/v1/periodontogram/snapshots/{snapshot_id}/teeth/{tooth}/sites/{site_code}",
                json={
                    "probing_depth_mm": depth,
                    "gingival_margin_mm": 0,
                    "bleeding_on_probing": tooth == 36 and site_code == "DV",
                    "plaque": False,
                },
            )
            sites += 1 if status == 200 else 0
    status, body = api.post(
        f"/api/v1/periodontogram/snapshots/{snapshot_id}/close",
        {"notes": "Fixture periodontal charting"},
    )
    if status != 200:
        chain.record("clinical record: periodontogram", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    chain.record(
        "clinical record: periodontogram",
        PASS,
        f"snapshot {str(snapshot_id)[:8]} closed, {sites} sites",
    )

    status, body = api.post(
        f"/api/v1/odontogram/patients/{pid}/treatments",
        {
            "clinical_type": "filling_composite",
            "scope": "tooth",
            "tooth_numbers": [36],
            "status": "planned",
            "source_module": "odontogram",
            "notes": "Fixture: composite restoration of 36",
        },
    )
    if status not in (200, 201):
        chain.record("clinical record: treatment history", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    treatment = _data(body) or {}
    status, body = api.request(
        "PATCH",
        f"/api/v1/odontogram/treatments/{treatment.get('id')}/perform",
        json={"notes": "Performed on the fixture patient"},
    )
    if status != 200:
        chain.record("clinical record: treatment history", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    chain.record("clinical record: treatment history", PASS, "one performed treatment recorded")
    return True


def step_implant_approval(chain: Chain, api: Api, pid: str) -> bool:
    """Dentist accepts the deterministic implant plan through its own review route.

    ``risk_engine`` keeps ``accepted_implant_intersects_accepted_nerve_centerline``
    at ``not_available`` until an implant plan is accepted, which leaves the risk
    context ``partial`` and blocks the report/copilot readiness gate. Accepting
    the plan is the dentist decision the product already requires, so this
    satisfies the gate's real precondition rather than relaxing it.
    """
    print("\n[.] Dentist acceptance of the deterministic implant plan")
    status, body = api.get(f"/api/v1/dental_3d/patients/{pid}/implant-planning")
    if status != 200:
        chain.record("implant acceptance", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    plans = (_data(body) or {}).get("plans") or []
    if not plans:
        chain.record("implant acceptance", SKIP, "no implant plan to accept")
        return True
    plan_id = plans[0].get("id")
    status, body = api.post(
        f"/api/v1/dental_3d/patients/{pid}/implant-plans/{plan_id}/review",
        {
            "decision": "accepted",
            "note": "Development verification — dentist accepts the deterministic plan.",
        },
    )
    if status != 200:
        chain.record("implant acceptance", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    accepted = _data(body) or {}
    chain.note("implant plan status", accepted.get("status"))
    if accepted.get("status") != "accepted":
        chain.record("implant acceptance", FAIL, f"status={accepted.get('status')!r}")
        return False
    chain.record(
        "implant acceptance",
        PASS,
        f"accepted by dentist {str(accepted.get('reviewed_by'))[:8]} via the module's review route",
    )
    return True


def step_orthodontics(chain: Chain, api: Api, pid: str) -> bool:
    print("\n[12] Orthodontic simulator capability + simulation")
    status, body = api.get(f"/api/v1/orthodontic_simulator/patients/{pid}/capability")
    if status != 200:
        chain.record("ortho capability", FAIL, f"HTTP {status}: {_detail(body)}")
        return False
    capability = _data(body) or {}
    chain.note("whole_arch_mesh_count", capability.get("whole_arch_mesh_count"))
    chain.note("per_tooth_mesh_count", capability.get("per_tooth_mesh_count"))
    chain.note("reviewed_per_tooth_mesh_count", capability.get("reviewed_per_tooth_mesh_count"))
    chain.note("accepted_alignment", capability.get("accepted_alignment"))
    chain.note("translation_eligible", capability.get("translation_eligible"))
    chain.note("rotation_eligible", capability.get("rotation_eligible"))
    for reason in (capability.get("reasons") or [])[:3]:
        chain.note(f"  reason {reason.get('code')}", reason.get("message"))
    if capability.get("whole_arch_mesh_count", 0) < 1:
        chain.record(
            "ortho capability",
            FAIL,
            f"no whole-arch mesh available: {[r.get('code') for r in capability.get('reasons') or []]}",
        )
        return False
    summary = (
        f"whole-arch meshes={capability.get('whole_arch_mesh_count')} "
        f"per-tooth={capability.get('per_tooth_mesh_count')} "
        f"accepted_alignment={capability.get('accepted_alignment')}"
    )
    if not capability.get("translation_eligible") and not capability.get("rotation_eligible"):
        # Not a data gap this script can fill: per-tooth movement needs a
        # reviewed per-tooth mesh mapping and trusted tooth-local frames,
        # which the current Dental3D contract does not expose. The module
        # says so explicitly instead of simulating on nothing.
        chain.record(
            "ortho capability",
            SKIP,
            f"{summary} — movement disabled by contract: "
            + "; ".join(str(r.get("code")) for r in capability.get("reasons") or []),
        )
        return False
    chain.record("ortho capability", PASS, summary)

    # A real authored movement: 0.2 mm distal translation of the upper right
    # first molar, inside the module's own caps. Only attempted when the
    # capability endpoint says movement is eligible.
    simulate_request = {
        "movements": [{"tooth": {"value": "16", "system": "FDI"}, "translate_y_mm": -0.2}],
        "caps": {"linear_mm": 0.25, "vertical_mm": 0.1, "angular_deg": 1.0, "rotation_deg": 2.0},
    }
    status, body = api.post(
        f"/api/v1/orthodontic_simulator/patients/{pid}/simulate", simulate_request
    )
    if status not in (200, 201):
        detail = _detail(body)
        if "unavailable" in detail.lower() or "locked" in detail.lower():
            chain.record("ortho simulation", SKIP, f"gate reported: {detail[:200]}")
            return True
        chain.record("ortho simulation", FAIL, f"HTTP {status}: {detail}")
        return False
    simulation = _data(body) or {}
    chain.note("simulation id", simulation.get("id"))
    chain.note("review_status", simulation.get("review_status"))
    for key in ("movements", "results", "teeth", "applied", "clamped"):
        value = simulation.get(key)
        if isinstance(value, list):
            chain.note(f"{key}", len(value))
            for item in value[:3]:
                if isinstance(item, dict):
                    chain.note(
                        f"  {item.get('tooth') or item.get('fdi') or ''}",
                        json.dumps({k: v for k, v in item.items() if k not in ("tooth", "fdi")})[
                            :200
                        ],
                    )
    chain.note(
        "advisory_only / is_clinical",
        f"{simulation.get('advisory_only')} / {simulation.get('is_clinical')}",
    )
    chain.record("ortho simulation", PASS, "deterministic simulation produced")
    return True


# --- AI generation chain --------------------------------------------------


# Review states that prove the AI stayed advisory. This codebase uses
# `pending_review` (see ai_case_summary/contracts.py ReviewStatus); the
# master brief called the same idea "suggested". What must never happen is
# an AI artifact landing in an approved state without a clinician acting.
PENDING_STATES = {"pending_review", "suggested", "draft", "proposed"}
APPROVED_STATES = {"accepted", "approved", "signed", "finalized"}
CONTENT_KEYS = (
    "claims",
    "options",
    "steps",
    "sections",
    "findings",
    "messages",
    "recommendations",
    "paragraphs",
    "items",
    "notes",
    "red_flags",
    "evidence",
)


def _ai_evidence(label: str, chain: Chain, data: dict[str, Any]) -> None:
    prov = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
    chain.note(f"{label} id", data.get("id"))
    chain.note(f"{label} review_status", data.get("review_status"))
    chain.note(f"{label} provider", prov.get("provider") or data.get("provider"))
    chain.note(f"{label} model", prov.get("model") or prov.get("model_id") or data.get("model"))
    chain.note(f"{label} contract_version", data.get("contract_version"))
    counts = {k: len(data[k]) for k in CONTENT_KEYS if isinstance(data.get(k), list) and data[k]}
    if counts:
        chain.note(f"{label} payload", counts)
    # Show that real generated text came back, not an empty envelope.
    preview = None
    for value in data.values():
        if isinstance(value, str) and len(value) > 60:
            preview = value
            break
        if isinstance(value, list) and value and isinstance(value[0], dict):
            for inner in value[0].values():
                if isinstance(inner, str) and len(inner) > 40:
                    preview = inner
                    break
        if preview:
            break
    if preview:
        chain.note(f"{label} sample text", f"{preview[:180]}...")


def _hitl_check(chain: Chain, label: str, data: dict[str, Any]) -> None:
    status = data.get("review_status")
    if status is None:
        chain.note(f"{label} human-in-the-loop", "no review_status field in this contract")
        return
    if str(status) in APPROVED_STATES:
        chain.record(
            f"{label} human-in-the-loop",
            FAIL,
            f"AI artifact was auto-approved: review_status={status!r}",
        )
        return
    if str(status) in PENDING_STATES:
        chain.record(
            f"{label} human-in-the-loop",
            PASS,
            f"review_status={status!r} — stays advisory until a clinician reviews it",
        )
        return
    chain.record(f"{label} human-in-the-loop", INFO, f"unexpected review_status={status!r}")


def _ai_step(
    chain: Chain, api: Api, label: str, method: str, path: str, payload: Any = None
) -> Any:
    status, body = api.post(path, payload) if method == "POST" else api.get(path)
    if status in (200, 201):
        data = _data(body) or {}
        _ai_evidence(label, chain, data)
        chain.record(label, PASS, f"HTTP {status}")
        _hitl_check(chain, label, data)
        return data
    detail = _detail(body)
    if status == 503 and "provider_unavailable" in detail:
        chain.record(label, FAIL, f"provider unavailable: {detail[:300]}")
    elif status == 502:
        chain.record(label, FAIL, f"provider output failed contract validation: {detail[:200]}")
    elif status == 409:
        chain.record(label, SKIP, f"readiness gate: {detail[:250]}")
    else:
        chain.record(label, FAIL, f"HTTP {status}: {detail[:300]}")
    return None


def _dentist_review(
    chain: Chain, api: Api, label: str, path: str, payload: dict[str, Any] | None = None
) -> Any:
    """Have the dentist accept an AI artifact through the module's own endpoint.

    This is the human-in-the-loop step the product is built around: the AI
    leaves the artifact `pending_review` and only a clinician token can move
    it. Nothing here writes an accepted flag directly.
    """
    if payload is None:
        payload = {
            "decision": "accepted",
            "note": "Development verification — dentist acceptance.",
        }
    status, body = api.post(path, payload)
    detail = _detail(body)
    if status == 422 and "note" in detail and "extra_forbidden" in detail:
        # Some review contracts are extra="forbid" and take the decision only.
        payload.pop("note")
        status, body = api.post(path, payload)
    if status not in (200, 201):
        chain.record(f"{label} dentist acceptance", FAIL, f"HTTP {status}: {_detail(body)[:250]}")
        return None
    data = _data(body) or {}
    chain.note(f"{label} review_status after dentist decision", data.get("review_status"))
    chain.note(f"{label} reviewed_by", data.get("reviewed_by"))
    chain.note(f"{label} reviewed_at", data.get("reviewed_at"))
    # ai_second_review records the dentist decision as "reviewed"; the summary
    # and planning contracts use "accepted". Both are the module's own terminal
    # human-in-the-loop state, so neither is a failure.
    if data.get("review_status") not in {"accepted", "reviewed"}:
        chain.record(
            f"{label} dentist acceptance",
            FAIL,
            f"expected accepted/reviewed, got {data.get('review_status')!r}",
        )
        return None
    chain.record(
        f"{label} dentist acceptance",
        PASS,
        f"accepted by dentist {str(data.get('reviewed_by'))[:8]} via {path.split('/api/v1')[1]}",
    )
    return data


def _first_option_id(plan: dict[str, Any]) -> str | None:
    """First option id, wherever the planning response nests its content.

    The public response carries the contract under ``content`` (and a rendered
    view under ``clinical_output``), so looking only at the top level silently
    reported "no options" for a plan that actually had two.
    """
    containers: list[dict[str, Any]] = [plan]
    for key in ("content", "clinical_output", "planning_data"):
        nested = plan.get(key)
        if isinstance(nested, dict):
            containers.append(nested)
    for container in containers:
        for key in ("options", "treatment_options", "plan_options"):
            options = container.get(key)
            if isinstance(options, list) and options:
                first = options[0]
                if isinstance(first, dict):
                    for field in ("id", "option_id"):
                        if first.get(field):
                            return str(first[field])
                elif isinstance(first, str):
                    return first
    return None


def step_ai_chain(chain: Chain, api: Api, pid: str) -> bool:
    """Walk the clinical-AI chain in its real dependency order.

    case intelligence -> case summary -> dentist accepts it -> treatment
    planning -> dentist accepts it -> deterministic simulation -> second
    review -> clinical report / copilot advisory. Each gate below is the
    module's own precondition; the script satisfies it by doing the clinical
    step (a dentist acceptance) rather than by weakening the check.
    """
    print("\n[13] Clinical-AI generation chain (dependency order)")
    print("      case intelligence -> case summary -> dentist accept -> treatment plan")
    print("      -> dentist accept -> simulation -> second review -> report / copilot")

    _ai_step(
        chain,
        api,
        "Case intelligence (evidence snapshot)",
        "GET",
        f"/api/v1/case_intelligence/patients/{pid}",
    )

    # Ordering matters: the report/copilot readiness gates compare each
    # artifact against the *current* case snapshot, so the risk result has to
    # be produced after the snapshot the AI steps will read.
    print("\n[13a] Refresh the risk context against the current case snapshot")
    status, body = api.post(f"/api/v1/risk_engine/patients/{pid}", {})
    refreshed = (_data(body) or {}) if status == 200 else {}
    chain.note("risk refresh result_id", refreshed.get("id"))
    chain.note("risk refresh factors", len(refreshed.get("factors") or []))

    summary = _ai_step(
        chain, api, "AI case summary", "POST", f"/api/v1/ai_case_summary/patients/{pid}", {}
    )
    summary_id = (summary or {}).get("id")
    if summary_id:
        _dentist_review(
            chain, api, "AI case summary", f"/api/v1/ai_case_summary/summaries/{summary_id}/review"
        )
    else:
        chain.record("AI treatment plan draft", SKIP, "no case summary artifact to build on")

    plan = _ai_step(
        chain,
        api,
        "AI treatment plan draft",
        "POST",
        f"/api/v1/ai_treatment_planning/patients/{pid}",
        {},
    )
    planning_id = (plan or {}).get("id")
    option_id = _first_option_id(plan or {}) if plan else None
    chain.note("planning_id", planning_id)
    chain.note("option_id", option_id)
    if planning_id:
        _dentist_review(
            chain,
            api,
            "AI treatment plan",
            f"/api/v1/ai_treatment_planning/results/{planning_id}/review",
        )

    simulation = None
    if planning_id and option_id:
        simulation = _ai_step(
            chain,
            api,
            "Treatment simulation (deterministic)",
            "POST",
            f"/api/v1/treatment_simulation/patients/{pid}",
            {"planning_id": planning_id, "option_id": option_id},
        )
    else:
        chain.record(
            "Treatment simulation (deterministic)",
            SKIP,
            f"needs an accepted plan option (planning_id={planning_id}, option_id={option_id})",
        )
    simulation_id = (simulation or {}).get("id")
    chain.note("simulation_id", simulation_id)

    if simulation_id:
        review = _ai_step(
            chain,
            api,
            "AI second review",
            "POST",
            f"/api/v1/ai_second_review/patients/{pid}",
            {"simulation_id": simulation_id},
        )
        review_id = (review or {}).get("id")
        if review_id:
            _dentist_review(
                chain,
                api,
                "AI second review",
                f"/api/v1/ai_second_review/results/{review_id}/review",
                # this contract is extra="forbid" and takes {"reviewed": true}
                {"reviewed": True},
            )
    else:
        chain.record("AI second review", SKIP, "needs a simulation_id from the previous step")

    # Readiness is its own endpoint: show what the gate actually sees.
    status, body = api.get(f"/api/v1/ai_clinical_report/patients/{pid}/readiness")
    if status == 200:
        readiness = _data(body) or {}
        chain.note("report readiness", readiness.get("status") or readiness.get("ready"))
        chain.note("report readiness detail", json.dumps(readiness)[:400])
    _ai_step(
        chain,
        api,
        "AI clinical report",
        "POST",
        "/api/v1/ai_clinical_report/generate",
        {"patient_id": pid},
    )

    status, body = api.get(f"/api/v1/clinical_copilot/patients/{pid}/context")
    if status == 200:
        context = _data(body) or {}
        chain.note("copilot context keys", ", ".join(sorted(context)[:12]))
    _ai_step(
        chain,
        api,
        "Clinical copilot advisory",
        "POST",
        "/api/v1/clinical_copilot/advise",
        {"patient_id": pid, "focus": "case_review"},
    )
    return True


# --- runner ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_ai_geometry_chain",
        description="Walk the real geometry + clinical-AI chain against a running backend.",
    )
    parser.add_argument("--base-url", default="http://localhost:8100")
    parser.add_argument("--email", default="dentist@demo.clinic")
    parser.add_argument("--password", default="demo1234")
    parser.add_argument("--patient-id", default=None)
    parser.add_argument("--patient-search", default="Demo")
    parser.add_argument("--ios", type=Path, default=None, help="IOS mesh STL to ingest")
    parser.add_argument(
        "--cbct-dir", type=Path, default=None, help="directory of CBCT .dcm fixtures"
    )
    parser.add_argument(
        "--target-site",
        type=float,
        nargs=3,
        default=(-21.54, -1.26, 15.21),
        metavar=("X", "Y", "Z"),
        help="prosthetic platform centre in DICOM patient LPS mm (default sits on the "
        "development fixture's posterior-left occlusal anatomy)",
    )
    parser.add_argument(
        "--seed-clinical-record",
        action="store_true",
        help="enter medical context, odontogram, periodontogram and one performed "
        "treatment so the report/copilot readiness gate has a complete case",
    )
    parser.add_argument(
        "--accept-implant-plan",
        action="store_true",
        help="have the dentist accept the deterministic implant plan, which the risk "
        "engine needs before the implant/nerve intersection factor resolves",
    )
    parser.add_argument(
        "--steps",
        choices=("all", "geometry", "ai"),
        default="all",
        help="geometry = ingestion/alignment/gated engines; ai = the LLM generation chain",
    )
    args = parser.parse_args(argv)

    chain = Chain()
    api = Api(args.base_url)
    print("=" * 78)
    print(f"Dentora AI + geometry chain verification against {args.base_url}")
    print("=" * 78)

    status, body = api.get("/health")
    if status != 200:
        chain.record("backend health", FAIL, f"HTTP {status}: {_detail(body)}")
        print("\nIs the backend running? (docker compose up -d backend)")
        return 1
    chain.record("backend health", PASS, str(_data(body) or body)[:80])

    if not step_login(chain, api, args.email, args.password):
        return _summarize(chain)

    pid = step_resolve_patient(chain, api, args.patient_id, args.patient_search)
    if not pid:
        return _summarize(chain)

    if args.steps in ("all", "geometry"):
        step_scene_baseline(chain, api, pid)

        mesh_document_id = None
        series_uid = None
        if args.ios and args.cbct_dir:
            mesh_document_id = step_upload_ios(chain, api, pid, args.ios)
            series_uid = step_upload_cbct(chain, api, pid, args.cbct_dir)
        else:
            chain.record(
                "geometry fixtures",
                SKIP,
                "pass --ios and --cbct-dir to ingest real geometry (see the module docstring)",
            )

        if mesh_document_id:
            step_segmentation(chain, api, pid)
            nerve_state = step_nerve_detection(chain, api, pid, series_uid)
            chain.note("nerve geometry state", nerve_state)
            if series_uid:
                alignment_id = step_alignment(chain, api, pid, mesh_document_id, series_uid)
                if alignment_id:
                    step_scene_after(chain, api, pid)
                    frame_uid = str(chain.evidence.get("frame_of_reference_uid") or "")
                    if frame_uid:
                        step_prosthetic_target(
                            chain, api, pid, alignment_id, frame_uid, tuple(args.target_site)
                        )
                    else:
                        chain.record("prosthetic target", SKIP, "no frame of reference recorded")
            else:
                chain.record("alignment", SKIP, "no CBCT series to register against")
        else:
            chain.record("segmentation", SKIP, "no IOS mesh ingested")
            chain.record("alignment", SKIP, "no IOS mesh ingested")

        step_risk_engine(chain, api, pid)
        step_implant_planning(chain, api, pid)
        if args.accept_implant_plan:
            step_implant_approval(chain, api, pid)
        step_orthodontics(chain, api, pid)

    if args.seed_clinical_record:
        step_clinical_record(chain, api, pid)

    if args.steps in ("all", "ai"):
        step_ai_chain(chain, api, pid)

    return _summarize(chain)


def _summarize(chain: Chain) -> int:
    print("\n" + "=" * 78)
    print("SUMMARY")
    for step, status, detail in chain.results:
        print(f"  {status:<4} {step}" + (f" — {detail[:120]}" if detail else ""))
    counts: dict[str, int] = {}
    for _step, status, _detail in chain.results:
        counts[status] = counts.get(status, 0) + 1
    print(
        f"\n{counts.get(PASS, 0)} passed, {counts.get(FAIL, 0)} failed, "
        f"{counts.get(SKIP, 0)} skipped/gated, {counts.get(INFO, 0)} informational"
    )
    print("=" * 78)
    return 1 if chain.failed else 0


if __name__ == "__main__":
    sys.exit(main())
