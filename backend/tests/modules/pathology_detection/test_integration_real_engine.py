"""End-to-end integration test with a REAL torch engine.

Gated on the ``PATHOLOGY_MODEL_PATH`` environment variable plus the
optional ``ai-pathology`` extra — skipped in the default CI (which has
neither). Run locally after provisioning a checkpoint::

    PATHOLOGY_MODEL_PATH=/tmp/pathology-weights/pathology_smoke.pt \\
        python -m pytest tests/modules/pathology_detection/test_integration_real_engine.py

This exercises the full production path: media upload → storage
retrieve → PIL decode → torchvision preprocess/inference → NMS →
confidence filter → FDI enumeration → persistence → API response.
"""

from __future__ import annotations

import io
import os

import pytest
from httpx import AsyncClient
from PIL import Image

pytestmark = pytest.mark.asyncio

_pytest_skip = pytest.mark.skipif(
    not os.environ.get("PATHOLOGY_MODEL_PATH"),
    reason="PATHOLOGY_MODEL_PATH not set (no real engine in default CI)",
)


def _png_bytes(size: tuple[int, int] = (640, 320)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(40, 40, 44)).save(buf, format="PNG")
    return buf.getvalue()


@_pytest_skip
async def test_real_engine_end_to_end(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient,
) -> None:
    response = await client.get("/api/v1/pathology_detection/capabilities", headers=auth_headers)
    assert response.status_code == 200
    capabilities = response.json()["data"]
    assert capabilities["available"] is True
    assert capabilities["engine"] == "torchvision_fasterrcnn"

    upload = await client.post(
        f"/api/v1/media/patients/{test_patient.id}/photos",
        headers=auth_headers,
        files={"file": ("rx.png", _png_bytes(), "image/png")},
        data={
            "title": "integration",
            "media_kind": "xray",
            "media_category": "xray",
            "media_subtype": "panoramic",
        },
    )
    assert upload.status_code == 201, upload.text
    doc = upload.json()["data"]

    run = await client.post(
        f"/api/v1/pathology_detection/patients/{test_patient.id}/analyses",
        headers=auth_headers,
        json={"document_id": doc["id"]},
    )
    assert run.status_code == 201, run.text
    detail = run.json()["data"]
    assert detail["status"] == "completed"
    assert detail["engine"] == "torchvision_fasterrcnn"
    assert detail["image_width"] == 640
    for finding in detail["findings"]:
        assert finding["diagnosis"] in {
            "caries",
            "deep_caries",
            "periapical_lesion",
            "impacted_tooth",
        }
        assert 0.0 <= finding["confidence"] <= 1.0
        bbox = finding["bbox"]
        assert 0.0 <= bbox["x1"] <= bbox["x2"] <= 1.0
        assert 0.0 <= bbox["y1"] <= bbox["y2"] <= 1.0
