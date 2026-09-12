#!/usr/bin/env python3
"""Development stand-in for the operator-managed DentalSegmentator service.

IOS→CBCT registration extracts the CBCT-side anatomy through an external
service behind the ``dental-anatomy-v1`` HTTP contract
(``HttpDentalSegmentatorAdapter``). With ``DENTAL_3D_DENTAL_SEGMENTATOR_URL``
empty the app fails closed — ``dependency_unavailable``, no transform, no
dentist review — which is correct production behaviour but means the whole
downstream chain (accepted alignment → per-tooth orthodontics → implant
planning against accepted geometry) cannot be exercised locally.

The real service is a third-party ML model (DentalSegmentator / nnU-Net)
that an operator deploys with licensed weights; nothing in this repository
can ship it. This script is the local development equivalent: it implements
the same contract and derives the anatomy from the **actual voxels of the
CBCT that was ingested**, by classical intensity thresholding and the
standard DICOM patient-coordinate mapping. It runs no model, invents no
geometry and returns nothing canned — a series with no voxels above the
threshold yields an error, not a plausible-looking point cloud.

Provenance stays honest: it reports ``model_id =
dentora-dev-threshold-anatomy``, which the backend persists with the
alignment result, so anyone reading that record can see a development
threshold extractor produced the geometry rather than a clinical model.

This is NOT a production component and is not wired in by default. Enable it
only for local validation::

    # terminal 1 — the development anatomy service
    python -m scripts.serve_dev_anatomy_service --port 8190

    # terminal 2 — point the backend at it (host Ollama-style addressing)
    DENTAL_3D_DENTAL_SEGMENTATOR_URL=http://host.docker.internal:8190/v1/dental-anatomy \
    DENTAL_3D_DENTAL_SEGMENTATOR_TOKEN=dev-token \
        docker compose up -d backend

For a clinical deployment, replace the URL with the real operator-managed
DentalSegmentator service; nothing else changes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pydicom

CONTRACT = "dental-anatomy-v1"
MODEL_ID = "dentora-dev-threshold-anatomy"
MODEL_VERSION = "1.0.0"
MAX_POINTS = 500_000  # the backend rejects more than this


class ExtractionError(Exception):
    """The archive could not yield usable anatomy."""


def _lps_points(instance, threshold: int) -> np.ndarray:
    """Voxel coordinates above ``threshold``, mapped to DICOM patient LPS mm.

    Uses the standard NEMA mapping: each instance carries its own
    ``ImagePositionPatient``, and a pixel ``(row, column)`` maps to

        P = IPP + column * PixelSpacing[1] * row_cosines
                + row    * PixelSpacing[0] * column_cosines
    """
    pixel_array = instance.pixel_array.astype(np.float32)
    if pixel_array.ndim != 2:
        raise ExtractionError(f"expected a single-frame instance, got shape {pixel_array.shape}")

    ipp = np.asarray(instance.ImagePositionPatient, dtype=np.float64)
    iop = np.asarray(instance.ImageOrientationPatient, dtype=np.float64)
    row_cosines, column_cosines = iop[:3], iop[3:]
    spacing = np.asarray(instance.PixelSpacing, dtype=np.float64)
    delta_row, delta_column = float(spacing[0]), float(spacing[1])

    rows, columns = np.nonzero(pixel_array > threshold)
    if rows.size == 0:
        return np.empty((0, 3), dtype=np.float64)

    points = (
        ipp
        + columns[:, None] * delta_column * row_cosines[None, :]
        + rows[:, None] * delta_row * column_cosines[None, :]
    )
    return points


def _downsample(points: np.ndarray, max_points: int) -> np.ndarray:
    """Deterministic stride downsample — no randomness, no clustering."""
    if points.shape[0] <= max_points:
        return points
    stride = int(np.ceil(points.shape[0] / max_points))
    return points[::stride]


def extract_anatomy(archive: bytes, *, threshold: int) -> tuple[np.ndarray, str]:
    """Extract thresholded anatomy points (LPS mm) from a ZIP of DICOM instances."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise ExtractionError("request body is not a ZIP archive") from exc

    points: list[np.ndarray] = []
    frames: set[str] = set()
    instances = 0

    for name in sorted(zf.namelist()):
        raw = zf.read(name)
        if not raw:
            continue
        try:
            instance = pydicom.dcmread(io.BytesIO(raw), force=True)
        except Exception as exc:  # noqa: BLE001 - report, do not crash the service
            raise ExtractionError(f"{name}: not readable as DICOM ({exc})") from exc
        if not hasattr(instance, "pixel_array"):
            continue
        instances += 1
        frame = getattr(instance, "FrameOfReferenceUID", "")
        if frame:
            frames.add(str(frame))
        try:
            points.append(_lps_points(instance, threshold))
        except ExtractionError:
            raise
        except Exception as exc:  # noqa: BLE001 - a bad instance is a bad request
            raise ExtractionError(f"{name}: {exc}") from exc

    if instances == 0:
        raise ExtractionError("the archive contains no DICOM instances with pixel data")
    if len(frames) != 1:
        raise ExtractionError(
            f"expected exactly one Frame of Reference, found {len(frames)}: {sorted(frames)}"
        )

    merged = np.concatenate(points) if points else np.empty((0, 3))
    if merged.shape[0] < 3:
        raise ExtractionError(
            f"only {merged.shape[0]} voxel(s) above threshold {threshold} — nothing to register"
        )
    return _downsample(merged, MAX_POINTS), frames.pop()


class Handler(BaseHTTPRequestHandler):
    server_version = "DentoraDevAnatomy/1.0"

    def log_message(self, fmt: str, *args) -> None:  # route access logs to stdout
        sys.stdout.write(f"[dev-anatomy] {self.address_string()} - {fmt.format(*args)}\n")
        sys.stdout.flush()

    def _send(self, code: int, payload: dict | bytes, content_type: str = "application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server API
        if self.path.rstrip("/") in ("/health", "/healthz", ""):
            self._send(200, {"status": "ok", "model_id": MODEL_ID, "contract": CONTRACT})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802 - http.server API
        if self.headers.get("X-Dentora-Contract") != CONTRACT:
            self._send(400, {"error": f"expected X-Dentora-Contract: {CONTRACT}"})
            return

        expected_token = self.server.expected_token
        if expected_token:
            supplied = self.headers.get("Authorization", "")
            if supplied != f"Bearer {expected_token}":
                self._send(401, {"error": "invalid or missing bearer token"})
                return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._send(400, {"error": "empty request body"})
            return
        archive = self.rfile.read(length)

        declared_digest = self.headers.get("X-Dentora-Input-Digest", "")
        actual_digest = "sha256:" + hashlib.sha256(archive).hexdigest()
        if declared_digest and declared_digest != actual_digest:
            self._send(
                400,
                {
                    "error": "input digest mismatch",
                    "expected": declared_digest,
                    "actual": actual_digest,
                },
            )
            return

        try:
            points, frame_of_reference = extract_anatomy(archive, threshold=self.server.threshold)
        except ExtractionError as exc:
            self._send(422, {"error": str(exc)})
            return

        payload = {
            "status": "completed",
            "coordinate_system": "DICOM_PATIENT_LPS",
            "unit": "mm",
            "frame_of_reference_uid": frame_of_reference,
            "model_id": MODEL_ID,
            "model_version": MODEL_VERSION,
            "points_mm": [
                {"x": round(float(p[0]), 4), "y": round(float(p[1]), 4), "z": round(float(p[2]), 4)}
                for p in points
            ],
        }
        body = json.dumps(payload).encode()
        sys.stdout.write(
            f"[dev-anatomy] extracted {len(points)} points "
            f"(threshold={self.server.threshold}, {len(body)} bytes, for={frame_of_reference})\n"
        )
        sys.stdout.flush()
        self._send(200, body)


class Service(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, threshold: int, expected_token: str):
        super().__init__(address, Handler)
        self.threshold = threshold
        self.expected_token = expected_token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="serve_dev_anatomy_service",
        description="Serve the dental-anatomy-v1 contract with a development threshold extractor.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8190)
    parser.add_argument(
        "--threshold",
        type=int,
        default=300,
        help="intensity above which a voxel counts as anatomy (development fixtures use 1000; "
        "real CBCT bone is roughly 300+ HU)",
    )
    parser.add_argument(
        "--token",
        default="",
        help="if set, require Authorization: Bearer <token> "
        "(matches DENTAL_3D_DENTAL_SEGMENTATOR_TOKEN)",
    )
    args = parser.parse_args(argv)

    service = Service((args.host, args.port), args.threshold, args.token)
    print("=" * 72)
    print("Dentora DEVELOPMENT anatomy service (threshold extractor)")
    print("=" * 72)
    print(f"  listening  http://{args.host}:{args.port}/v1/dental-anatomy")
    print(f"  health     http://{args.host}:{args.port}/health")
    print(f"  contract   {CONTRACT}")
    print(f"  model_id   {MODEL_ID} v{MODEL_VERSION}")
    print(f"  threshold  {args.threshold}")
    print(f"  auth       {'bearer token required' if args.token else 'none'}")
    print("\n  Not a clinical model: geometry comes from thresholding the voxels")
    print("  of the CBCT that was actually ingested. Point the backend at it with")
    print("  DENTAL_3D_DENTAL_SEGMENTATOR_URL for local validation only.")
    print("=" * 72, flush=True)
    try:
        service.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        service.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
