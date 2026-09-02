"""API + persistence tests for the pathology detection module.

The inference engine is injected with a controllable fake so the whole
API surface (upload → analyze → list → detail → delete) is exercised
without a GPU or a trained checkpoint. Engine-internal tests live in
``test_engine.py`` (torch-gated).
"""

from __future__ import annotations

import io

import pytest
from httpx import AsyncClient
from PIL import Image

from app.modules.pathology_detection import service as service_module
from app.modules.pathology_detection.engine.base import (
    DetectedFinding,
    EngineUnavailableError,
    InferenceResult,
)
from app.modules.patients.models import Patient

pytestmark = pytest.mark.asyncio


def _png_bytes(size: tuple[int, int] = (640, 320)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(40, 40, 44)).save(buf, format="PNG")
    return buf.getvalue()


class FakeEngine:
    name = "fake_engine"
    model_version = "fake-1"

    def __init__(self, findings: list[DetectedFinding] | None = None) -> None:
        self._findings = findings or []

    def analyze(self, image: Image.Image) -> InferenceResult:
        return InferenceResult(
            findings=self._findings,
            engine=self.name,
            model_version=self.model_version,
            inference_ms=7,
        )


class FailingEngine:
    name = "fake_engine"
    model_version = "fake-1"

    def analyze(self, image: Image.Image) -> InferenceResult:
        raise RuntimeError("detector exploded")


async def _upload_xray(
    client: AsyncClient,
    auth_headers: dict[str, str],
    patient_id: str,
    *,
    kind: str = "xray",
) -> dict:
    response = await client.post(
        f"/api/v1/media/patients/{patient_id}/photos",
        headers=auth_headers,
        files={"file": ("rx.png", _png_bytes(), "image/png")},
        data={
            "title": "panoramic",
            "media_kind": kind,
            "media_category": "xray" if kind == "xray" else "intraoral",
            "media_subtype": "panoramic" if kind == "xray" else "frontal",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_capabilities_reports_unprovisioned(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the unprovisioned state even when the developer runs the
    # suite with PATHOLOGY_MODEL_PATH exported (real-engine mode).
    from app.config import settings

    monkeypatch.setattr(settings, "PATHOLOGY_MODEL_PATH", "")
    response = await client.get("/api/v1/pathology_detection/capabilities", headers=auth_headers)
    assert response.status_code == 200
    capabilities = response.json()["data"]
    assert capabilities["available"] is False
    assert "PATHOLOGY_MODEL_PATH" in capabilities["reason"]


async def test_run_analysis_roundtrip(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    findings = [
        DetectedFinding("caries", 0.95, 0.10, 0.10, 0.20, 0.30),
        DetectedFinding("impacted_tooth", 0.80, 0.70, 0.10, 0.85, 0.30),
    ]
    monkeypatch.setattr(service_module, "get_engine", lambda: FakeEngine(findings))

    doc = await _upload_xray(client, auth_headers, str(test_patient.id))

    response = await client.post(
        f"/api/v1/pathology_detection/patients/{test_patient.id}/analyses",
        headers=auth_headers,
        json={"document_id": doc["id"]},
    )
    assert response.status_code == 201, response.text
    detail = response.json()["data"]
    assert detail["status"] == "completed"
    assert detail["findings_count"] == 2
    assert detail["summary"]["caries"] == 1
    assert detail["summary"]["impacted_tooth"] == 1
    assert detail["engine"] == "fake_engine"

    findings_by_diagnosis = {f["diagnosis"]: f for f in detail["findings"]}
    assert findings_by_diagnosis["caries"]["tooth_number"] == 11  # Q1 position 1
    assert findings_by_diagnosis["impacted_tooth"]["tooth_number"] == 21  # Q2 position 1
    assert findings_by_diagnosis["impacted_tooth"]["bbox"]["x1"] == 0.70

    # History + detail + delete.
    history = await client.get(
        f"/api/v1/pathology_detection/patients/{test_patient.id}/analyses",
        headers=auth_headers,
    )
    assert history.status_code == 200
    assert history.json()["data"][0]["id"] == detail["id"]

    fetched = await client.get(
        f"/api/v1/pathology_detection/analyses/{detail['id']}",
        headers=auth_headers,
    )
    assert fetched.status_code == 200
    assert len(fetched.json()["data"]["findings"]) == 2

    deleted = await client.delete(
        f"/api/v1/pathology_detection/analyses/{detail['id']}",
        headers=auth_headers,
    )
    assert deleted.status_code == 200
    gone = await client.get(
        f"/api/v1/pathology_detection/analyses/{detail['id']}",
        headers=auth_headers,
    )
    assert gone.status_code == 404


async def test_run_analysis_503_when_engine_unavailable(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> None:
        raise EngineUnavailableError("PATHOLOGY_MODEL_PATH not set")

    monkeypatch.setattr(service_module, "get_engine", unavailable)
    doc = await _upload_xray(client, auth_headers, str(test_patient.id))
    response = await client.post(
        f"/api/v1/pathology_detection/patients/{test_patient.id}/analyses",
        headers=auth_headers,
        json={"document_id": doc["id"]},
    )
    assert response.status_code == 503
    body = response.json()
    assert "PATHOLOGY_MODEL_PATH" in (body.get("detail") or body.get("message") or "")


async def test_run_analysis_422_for_non_analyzable_document(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_module, "get_engine", lambda: FakeEngine())
    # Upload a plain administrative document (media_kind="document"),
    # which is not in ANALYZABLE_MEDIA_KINDS.
    response = await client.post(
        f"/api/v1/media/patients/{test_patient.id}/documents",
        headers=auth_headers,
        files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"document_type": "report", "title": "MR report"},
    )
    assert response.status_code == 201, response.text
    doc = response.json()["data"]
    response = await client.post(
        f"/api/v1/pathology_detection/patients/{test_patient.id}/analyses",
        headers=auth_headers,
        json={"document_id": doc["id"]},
    )
    assert response.status_code == 422
    body = response.json()
    assert "not analyzable" in (body.get("detail") or body.get("message") or "")


async def test_run_analysis_404_for_unknown_document(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_module, "get_engine", lambda: FakeEngine())
    response = await client.post(
        f"/api/v1/pathology_detection/patients/{test_patient.id}/analyses",
        headers=auth_headers,
        json={"document_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404
    body = response.json()
    assert (body.get("detail") or body.get("message")) == "Document not found"


async def test_failed_run_persists_error(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_module, "get_engine", lambda: FailingEngine())
    doc = await _upload_xray(client, auth_headers, str(test_patient.id))
    response = await client.post(
        f"/api/v1/pathology_detection/patients/{test_patient.id}/analyses",
        headers=auth_headers,
        json={"document_id": doc["id"]},
    )
    assert response.status_code == 500
    history = await client.get(
        f"/api/v1/pathology_detection/patients/{test_patient.id}/analyses",
        headers=auth_headers,
    )
    attempts = history.json()["data"]
    assert attempts[0]["status"] == "failed"
    details = await client.get(
        f"/api/v1/pathology_detection/analyses/{attempts[0]['id']}",
        headers=auth_headers,
    )
    assert "detector exploded" in details.json()["data"]["error"]


async def test_unknown_patient_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic,
) -> None:
    from uuid import uuid4

    response = await client.post(
        f"/api/v1/pathology_detection/patients/{uuid4()}/analyses",
        headers=auth_headers,
        json={"document_id": str(uuid4())},
    )
    assert response.status_code == 404
