"""Development stand-in for the operator-managed IAN nerve-inference service.

Why this exists
---------------
``app/modules/dental_3d/nerve_inference.py`` fails closed with ``missing_model``
unless ``DENTAL_3D_NERVE_INFERENCE_URL`` points at a real service. The
production service in ``nerve-inference-service/`` runs DentalSegmentator
(nnU-Net v2) against weights hosted on Zenodo, which are deliberately never
bundled with Dentora. Where those weights cannot be obtained, this script lets
the rest of the chain be exercised honestly.

It is **not** a neural network and does not claim to be. It implements the
``nerve-detection-v1`` HTTP contract with a classical, published image-analysis
pipeline:

1. Multi-Otsu thresholding to separate background / bone / enamel. CBCT
   intensities are not calibrated HU, so every threshold here is derived from
   the volume's own histogram rather than hardcoded.
2. The bone region is hole-filled, so a dark lumen *inside* bone stays part of
   the search space.
3. Frangi-style multi-scale vesselness on the bone-inverted image, which is the
   standard classical detector for tubular structures. Scales bracket the real
   2-4 mm mandibular canal diameter.
4. Candidate components must pass geometric tests that a mandibular canal
   satisfies and incidental dark structures do not: minimum traced length,
   tubularity (principal/second axis ratio), a plausible lumen radius, and a
   *wall test* requiring bone-density material in an annulus around the trace.
5. The centreline is recovered by PCA-slab centroids and reported in DICOM
   patient LPS millimetres.

The honesty requirement is enforced by construction: if no component passes
those tests the service returns ``status="no_detection"`` with no findings, so
it reports "not detected" on a scan that genuinely has no canal. ``model_id``
names the method exactly, and it never masquerades as nnU-Net output.

Usage
-----
    python -m scripts.serve_dev_nerve_service --host 127.0.0.1 --port 8191 \\
        --token dev-token

    # prove the detector is input-dependent (positive + two negative controls)
    python -m scripts.serve_dev_nerve_service --self-test \\
        --mandibular /tmp/mand/cbct_canal \\
        --ablation   /tmp/mand/cbct_nocanal \\
        --maxillary  /tmp/fix/cbct_v3
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
import pydicom
from scipy import ndimage

MODEL_ID = "dentora-dev-classical-ian-vesselness"
MODEL_VERSION = "0.1.0"
CONTRACT = "nerve-detection-v1"

# Detection criteria. These are anatomical, not fixture-specific: a mandibular
# canal is a 2-4 mm tube traceable for tens of millimetres inside bone.
MIN_TRACE_LENGTH_MM = 12.0
MIN_TUBULARITY_RATIO = 3.0
MIN_LUMEN_RADIUS_MM = 0.6
MAX_LUMEN_RADIUS_MM = 3.0
WALL_ANNULUS_MM = (1.8, 4.0)
VESSELNESS_SCALES_MM = (1.0, 1.5, 2.2)
SEED_FRACTION = 0.45  # hysteresis seed, relative to the 99.5th percentile
CONNECT_FRACTION = 0.12  # hysteresis connect level
ANALYSIS_SPACING_MM = 0.9  # resample pitch for the filter bank
MAX_POINTS_PER_FINDING = 96
MAX_FINDINGS = 2
LOW_CONFIDENCE_FLOOR = 0.6  # backend marks <0.6 as "uncertain"


# --------------------------------------------------------------------------
# DICOM -> HU volume in patient coordinates
# --------------------------------------------------------------------------
def load_volume(archive: bytes) -> tuple[np.ndarray, dict[str, Any]]:
    """Return ``(hu[k, row, col], frame)`` from a zipped DICOM CT series."""
    instances = []
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for name in sorted(zf.namelist()):
            if not name.lower().endswith((".dcm", ".dicom")):
                continue
            dataset = pydicom.dcmread(io.BytesIO(zf.read(name)), force=True)
            if getattr(dataset, "Modality", "") not in ("CT", "CBCT"):
                continue
            instances.append(dataset)
    if not instances:
        raise ValueError("archive contained no CT instances")

    slopes, intercepts, positions = [], [], []
    for dataset in instances:
        slopes.append(float(getattr(dataset, "RescaleSlope", 1.0) or 1.0))
        intercepts.append(float(getattr(dataset, "RescaleIntercept", 0.0) or 0.0))
        positions.append([float(v) for v in dataset.ImagePositionPatient])

    iop = np.asarray(instances[0].ImageOrientationPatient, dtype=np.float64)
    row_cosines, col_cosines = iop[:3], iop[3:]
    normal = np.cross(row_cosines, col_cosines)
    order = np.argsort([float(np.dot(p, normal)) for p in positions])

    spacing = [float(v) for v in instances[0].PixelSpacing]
    slice_positions = np.array(positions, dtype=np.float64)[order]
    gaps = np.linalg.norm(np.diff(slice_positions, axis=0), axis=1)
    slice_spacing = float(np.median(gaps)) if gaps.size else 1.0

    hu_slices = []
    for index in order:
        dataset = instances[index]
        pixels = dataset.pixel_array.astype(np.float32)
        hu_slices.append(pixels * slopes[index] + intercepts[index])
    volume = np.stack(hu_slices)

    frame = {
        "origin_mm": slice_positions[0],
        "row_cosines": row_cosines,
        "col_cosines": col_cosines,
        "pixel_spacing_mm": spacing,
        "slice_spacing_mm": slice_spacing,
        "shape": volume.shape,
        "frame_of_reference_uid": str(getattr(instances[0], "FrameOfReferenceUID", "")),
        "series_instance_uid": str(getattr(instances[0], "SeriesInstanceUID", "")),
        "instance_count": len(instances),
    }
    return volume, frame


def voxel_to_patient(indices: np.ndarray, frame: dict[str, Any]) -> np.ndarray:
    """(k, row, col) -> patient LPS millimetres, using the standard NEMA mapping."""
    k = indices[:, 0].astype(np.float64)
    row = indices[:, 1].astype(np.float64)
    col = indices[:, 2].astype(np.float64)
    row_spacing, col_spacing = frame["pixel_spacing_mm"]
    origin = np.asarray(frame["origin_mm"], dtype=np.float64)
    normal = np.cross(frame["row_cosines"], frame["col_cosines"])
    points = (
        origin[None, :]
        # Row cosines point along increasing *column* index, column cosines
        # along increasing *row* index -- the NEMA patient-coordinate mapping.
        + (col * col_spacing)[:, None] * frame["row_cosines"][None, :]
        + (row * row_spacing)[:, None] * frame["col_cosines"][None, :]
        + (k * frame["slice_spacing_mm"])[:, None] * normal[None, :]
    )
    return points


# --------------------------------------------------------------------------
# classical detection pipeline
# --------------------------------------------------------------------------
def multi_otsu(values: np.ndarray, classes: int = 3) -> list[float]:
    """Otsu's method generalised to ``classes`` bins (Otsu 1979)."""
    hist, edges = np.histogram(values, bins=256)
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total == 0:
        return [float(edges[0]), float(edges[-1])]
    if classes == 3:
        # Exhaustive search over the 256x256 upper triangle is cheap enough.
        probabilities = hist / total
        cumulative = np.cumsum(probabilities)
        best, thresholds = -1.0, (0, 0)
        for t1 in range(1, 250):
            w0 = cumulative[t1]
            if w0 <= 0:
                continue
            mu0 = float(np.sum(probabilities[: t1 + 1] * np.arange(t1 + 1))) / w0
            for t2 in range(t1 + 1, 251):
                w1 = cumulative[t2] - cumulative[t1]
                w2 = 1.0 - cumulative[t2]
                if w1 <= 0 or w2 <= 0:
                    continue
                mu1 = float(np.sum(probabilities[t1 + 1 : t2 + 1] * np.arange(t1 + 1, t2 + 1))) / w1
                mu2 = float(np.sum(probabilities[t2 + 1 :] * np.arange(t2 + 1, 256))) / w2
                between = w0 * mu0**2 + w1 * mu1**2 + w2 * mu2**2
                if between > best:
                    best, thresholds = between, (t1, t2)
        centres = (edges[:-1] + edges[1:]) / 2.0
        return [float(centres[thresholds[0]]), float(centres[thresholds[1]])]
    raise ValueError("only 3-class Otsu is implemented")


def hessian_eigenvalues(
    image: np.ndarray, sigma_voxels: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised eigenvalues of the smoothed Hessian, ascending by magnitude."""
    derivatives = {}
    for axis_a in range(3):
        for axis_b in range(axis_a, 3):
            order = [0, 0, 0]
            order[axis_a] += 1
            order[axis_b] += 1
            scale = sigma_voxels ** (sum(order))  # gamma-normalised derivatives
            derivatives[(axis_a, axis_b)] = (
                ndimage.gaussian_filter(image, sigma_voxels, order=order) * scale
            )

    h11 = derivatives[(0, 0)]
    h22 = derivatives[(1, 1)]
    h33 = derivatives[(2, 2)]
    h12 = derivatives[(0, 1)]
    h13 = derivatives[(0, 2)]
    h23 = derivatives[(1, 2)]

    # Closed-form eigenvalues of a real symmetric 3x3 matrix (Smith's method).
    q = (h11 + h22 + h33) / 3.0
    p1 = h12**2 + h13**2 + h23**2
    p2 = (h11 - q) ** 2 + (h22 - q) ** 2 + (h33 - q) ** 2 + 2.0 * p1
    p = np.sqrt(np.maximum(p2, 1e-18) / 6.0)

    b11 = (h11 - q) / p
    b22 = (h22 - q) / p
    b33 = (h33 - q) / p
    b12 = h12 / p
    b13 = h13 / p
    b23 = h23 / p
    determinant = (
        b11 * (b22 * b33 - b23**2) - b12 * (b12 * b33 - b23 * b13) + b13 * (b12 * b23 - b22 * b13)
    )
    r = np.clip(determinant / 2.0, -1.0, 1.0)
    phi = np.arccos(r) / 3.0

    eig_a = q + 2.0 * p * np.cos(phi)
    eig_c = q + 2.0 * p * np.cos(phi + 2.0 * math.pi / 3.0)
    eig_b = 3.0 * q - eig_a - eig_c
    stacked = np.stack([eig_a, eig_b, eig_c])
    stacked = np.take_along_axis(stacked, np.argsort(np.abs(stacked), axis=0), axis=0)
    del derivatives
    return stacked[0], stacked[1], stacked[2]


def frangi_vesselness(
    image: np.ndarray, sigma_voxels: float, *, alpha=0.5, beta=0.5, c=None
) -> np.ndarray:
    """Frangi et al. vesselness for bright tubular structures on a dark ground."""
    lam1, lam2, lam3 = hessian_eigenvalues(image, sigma_voxels)
    abs1, abs2, abs3 = np.abs(lam1), np.abs(lam2), np.abs(lam3)
    abs2 = np.maximum(abs2, 1e-9)
    abs3 = np.maximum(abs3, 1e-9)

    ratio_a = abs2 / abs3
    ratio_b = abs1 / np.sqrt(np.maximum(abs2 * abs3, 1e-18))
    structuredness = np.sqrt(lam1**2 + lam2**2 + lam3**2)
    if c is None:
        c = float(np.percentile(structuredness[structuredness > 0], 90) or 1.0)
        c = max(c, 1e-6)

    response = (1.0 - np.exp(-(ratio_a**2) / (2.0 * alpha**2))) * np.exp(
        -(ratio_b**2) / (2.0 * beta**2)
    )
    response = response * (1.0 - np.exp(-(structuredness**2) / (2.0 * c**2)))
    # A bright tube requires both large eigenvalues to be negative.
    response[(lam2 >= 0) | (lam3 >= 0)] = 0.0
    return response.astype(np.float32)


def detect_canals(volume_hu: np.ndarray, frame: dict[str, Any]) -> dict[str, Any]:
    """Run the classical IAN tracer. Returns a ``nerve-detection-v1`` payload."""
    flat = volume_hu.ravel()
    t_low, t_high = multi_otsu(flat[np.isfinite(flat)], classes=3)

    hard = volume_hu >= t_low  # bone + enamel
    bone_only = (volume_hu >= t_low) & (volume_hu <= t_high)
    filled = ndimage.binary_fill_holes(hard)  # keeps dark lumina inside bone
    del hard

    bone_reference = float(np.median(volume_hu[bone_only])) if bone_only.any() else t_high
    inverted = np.clip(bone_reference - volume_hu, 0.0, None).astype(np.float32)
    inverted[~filled] = 0.0  # nothing outside bone is a candidate

    # Resample to a near-isotropic pitch so filter scales mean millimetres.
    row_spacing, col_spacing = frame["pixel_spacing_mm"]
    slice_spacing = frame["slice_spacing_mm"]
    # ndimage.zoom factor > 1 upsamples, so the factor is current/target.
    factors = (
        max(slice_spacing, 1e-6) / ANALYSIS_SPACING_MM,
        max(row_spacing, 1e-6) / ANALYSIS_SPACING_MM,
        max(col_spacing, 1e-6) / ANALYSIS_SPACING_MM,
    )
    work = ndimage.zoom(inverted, factors, order=1, mode="nearest")
    filled_work = ndimage.zoom(filled.astype(np.float32), factors, order=1, mode="nearest") > 0.5
    hu_work = ndimage.zoom(volume_hu.astype(np.float32), factors, order=1, mode="nearest")
    del inverted

    best = None
    for sigma_mm in VESSELNESS_SCALES_MM:
        response = frangi_vesselness(work, sigma_mm / ANALYSIS_SPACING_MM)
        if best is None:
            best = response
        else:
            best = np.maximum(best, response)
        del response
    vesselness = np.where(filled_work, best, 0.0).astype(np.float32)
    del best, work

    # Component indices live in the resampled grid, so patient coordinates must
    # be taken with the resampled pitch. ndimage.zoom maps index i -> i*factor,
    # and factor = original_spacing / ANALYSIS_SPACING_MM, which makes the work
    # pitch exactly ANALYSIS_SPACING_MM on every axis. Using the original pitch
    # here scaled a 26 mm canal down to 11.5 mm and sent the wall probe into
    # empty space.
    work_frame = dict(frame)
    work_frame["pixel_spacing_mm"] = [ANALYSIS_SPACING_MM, ANALYSIS_SPACING_MM]
    work_frame["slice_spacing_mm"] = ANALYSIS_SPACING_MM

    peak = float(vesselness.max()) if vesselness.size else 0.0
    if peak <= 0:
        return {
            "status": "no_detection",
            "model_id": MODEL_ID,
            "model_version": MODEL_VERSION,
            "findings": [],
        }

    # Hysteresis (Canny-style): seed on the strong response, then keep every
    # weakly-connected voxel in the same component. A single hot peak would
    # otherwise fragment a 28 mm canal into short unusable pieces.
    positive = vesselness[filled_work & (vesselness > 0)]
    reference = float(np.percentile(positive, 99.5)) if positive.size else peak
    reference = max(reference, 1e-6)
    seeds = vesselness >= (SEED_FRACTION * reference)
    weak = vesselness >= (CONNECT_FRACTION * reference)
    weak_labels, _weak_count = ndimage.label(weak, structure=np.ones((3, 3, 3)))
    seeded = set(np.unique(weak_labels[seeds]).tolist()) - {0}
    candidates = np.isin(weak_labels, list(seeded)) if seeded else weak
    labels, count = ndimage.label(candidates, structure=np.ones((3, 3, 3)))
    del weak_labels, weak, seeds
    if count == 0:
        return {
            "status": "no_detection",
            "model_id": MODEL_ID,
            "model_version": MODEL_VERSION,
            "findings": [],
        }

    findings: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for label in range(1, count + 1):
        indices = np.argwhere(labels == label)
        if len(indices) < 24:
            continue
        points = voxel_to_patient(indices, work_frame)
        # Undo the resampling so patient coordinates stay truthful.
        centroid = points.mean(axis=0)
        relative = points - centroid
        covariance = np.cov(relative.T)
        eigenvectors = np.linalg.eigh(covariance)[1][:, ::-1]
        projections = relative @ eigenvectors
        extents = projections.max(axis=0) - projections.min(axis=0)
        length_mm = float(extents[0])
        second_mm = float(max(extents[1], 1e-6))
        tubularity = length_mm / second_mm

        # Centreline: bin voxels along the principal axis, take slab centroids.
        bins = max(8, int(length_mm / 1.5))
        edges = np.linspace(projections[:, 0].min(), projections[:, 0].max(), bins + 1)
        centreline: list[np.ndarray] = []
        strength: list[float] = []
        for b in range(bins):
            member = (projections[:, 0] >= edges[b]) & (projections[:, 0] <= edges[b + 1])
            if member.sum() < 3:
                continue
            centreline.append(points[member].mean(axis=0))
            member_indices = indices[member]
            slab = vesselness[member_indices[:, 0], member_indices[:, 1], member_indices[:, 2]]
            strength.append(float(slab.mean()) if slab.size else 0.0)
        if len(centreline) < 6:
            continue
        trace = np.array(centreline)
        path_length = float(np.sum(np.linalg.norm(np.diff(trace, axis=0), axis=1)))

        # Lumen radius from the component's own volume and traced length.
        volume_mm3 = len(indices) * (ANALYSIS_SPACING_MM**3)
        radius_mm = math.sqrt(max(volume_mm3, 1e-6) / (math.pi * max(path_length, 1e-6)))

        # Wall test: the trace must be enclosed by bone-density material.
        wall_samples = _annulus_hu(hu_work, trace, frame, factors, bone_reference)
        wall_threshold = max(t_low, 0.5 * bone_reference)
        enclosed = float(np.mean(wall_samples >= wall_threshold)) if wall_samples.size else 0.0

        record = {
            "label": int(label),
            "voxels": int(len(indices)),
            "length_mm": round(path_length, 2),
            "extent_mm": round(length_mm, 2),
            "tubularity": round(tubularity, 2),
            "radius_mm": round(radius_mm, 2),
            "wall_bone_fraction": round(enclosed, 3),
            "mean_vesselness": round(float(np.mean(strength)) if strength else 0.0, 4),
            "centroid": [round(float(v), 2) for v in centroid],
        }
        diagnostics.append(record)

        reasons = []
        if path_length < MIN_TRACE_LENGTH_MM:
            reasons.append(f"trace {path_length:.1f} mm < {MIN_TRACE_LENGTH_MM} mm")
        if tubularity < MIN_TUBULARITY_RATIO:
            reasons.append(f"tubularity {tubularity:.2f} < {MIN_TUBULARITY_RATIO}")
        if not (MIN_LUMEN_RADIUS_MM <= radius_mm <= MAX_LUMEN_RADIUS_MM):
            reasons.append(
                f"lumen radius {radius_mm:.2f} mm outside {MIN_LUMEN_RADIUS_MM}-{MAX_LUMEN_RADIUS_MM} mm"
            )
        if enclosed < 0.6:
            reasons.append(f"only {enclosed:.0%} of the annulus is bone-density")
        if reasons:
            record["rejected"] = reasons
            continue
        record["accepted"] = True

        # Confidence is a normalised filter response, explicitly not a
        # calibrated probability -- same honesty note the real service makes.
        score = float(np.mean(strength)) / peak if strength and peak > 0 else 0.0
        length_credit = min(1.0, path_length / (2.0 * MIN_TRACE_LENGTH_MM))
        confidence = round(
            min(0.99, 0.55 * score + 0.45 * (0.5 + 0.5 * length_credit) * min(1.0, enclosed + 0.2)),
            3,
        )
        confidence = (
            max(confidence, LOW_CONFIDENCE_FLOOR)
            if enclosed >= 0.8 and path_length >= MIN_TRACE_LENGTH_MM * 1.5
            else confidence
        )

        decimated = _decimate(trace, MAX_POINTS_PER_FINDING)
        findings.append(
            {
                "finding_id": f"ian-{record['label']:03d}-{hashlib.sha256(trace.tobytes()).hexdigest()[:10]}",
                "side": "left" if float(decimated[:, 0].mean()) >= 0 else "right",
                "confidence": confidence,
                "uncertainty": {
                    "value": round(min(1.0, 1.0 - enclosed), 3),
                    "note": "classical vesselness trace; value is 1 - bone-wall fraction, not a calibrated probability",
                },
                "points_mm": [
                    {
                        "x": round(float(p[0]), 3),
                        "y": round(float(p[1]), 3),
                        "z": round(float(p[2]), 3),
                    }
                    for p in decimated
                ],
                "_diagnostics": record,
            }
        )

    findings.sort(key=lambda item: -item["confidence"])
    findings = findings[:MAX_FINDINGS]
    # One finding per side; keep the stronger trace if both landed on one side.
    chosen: dict[str, dict[str, Any]] = {}
    for finding in findings:
        chosen.setdefault(finding["side"], finding)
    findings = list(chosen.values())

    payload: dict[str, Any] = {
        "status": "detected" if findings else "no_detection",
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "findings": [{k: v for k, v in f.items() if not k.startswith("_")} for f in findings],
    }
    payload["_diagnostics"] = {
        "otsu_thresholds": [round(t_low, 1), round(t_high, 1)],
        "bone_reference_hu": round(bone_reference, 1),
        "peak_vesselness": round(peak, 5),
        "hysteresis_reference": round(reference, 5),
        "wall_threshold_hu": round(max(t_low, 0.5 * bone_reference), 1),
        "components": count,
        "candidates": diagnostics,
        "instance_count": frame["instance_count"],
    }
    return payload


def _annulus_hu(hu_work, trace, frame, factors, bone_reference) -> np.ndarray:
    """Sample HU in an annulus around each centreline point (the wall test)."""
    row_spacing, col_spacing = frame["pixel_spacing_mm"]
    samples: list[float] = []
    origin = np.asarray(frame["origin_mm"], dtype=np.float64)
    angles = np.linspace(0, 2 * math.pi, 12, endpoint=False)
    for point in trace[:: max(1, len(trace) // 24)]:
        for radius_mm in WALL_ANNULUS_MM:
            for angle in angles:
                offset = np.array([radius_mm * math.cos(angle), radius_mm * math.sin(angle), 0.0])
                target = point + offset
                col = (target[0] - origin[0]) / col_spacing * factors[2]
                row = (target[1] - origin[1]) / row_spacing * factors[1]
                k = (target[2] - origin[2]) / frame["slice_spacing_mm"] * factors[0]
                ki, ri, ci = int(round(k)), int(round(row)), int(round(col))
                if (
                    0 <= ki < hu_work.shape[0]
                    and 0 <= ri < hu_work.shape[1]
                    and 0 <= ci < hu_work.shape[2]
                ):
                    samples.append(float(hu_work[ki, ri, ci]))
    return np.asarray(samples, dtype=np.float32)


def _decimate(trace: np.ndarray, max_points: int) -> np.ndarray:
    if len(trace) <= max_points:
        return trace
    keep = np.linspace(0, len(trace) - 1, max_points).round().astype(int)
    return trace[np.unique(keep)]


# --------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------
def _read_series(directory: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(directory.glob("*.dcm")):
            zf.write(path, path.name)
    return buffer.getvalue()


def _score_against_ground_truth(payload: dict[str, Any], directory: Path) -> str:
    """Compare traced centrelines with the fixture's own ground truth."""
    manifest_path = directory / "fixture_manifest.json"
    if not manifest_path.exists():
        return "no manifest, cannot score"
    manifest = json.loads(manifest_path.read_text())
    truths = (manifest.get("phantom") or {}).get("canal_ground_truth") or []
    if not truths:
        return "fixture declares no canal ground truth"
    if payload["status"] != "detected":
        return f"MISSED: fixture declares {len(truths)} canal(s), detector reported none"

    lines = []
    for truth in truths:
        truth_points = np.asarray(truth["points_mm"], dtype=float)
        best = None
        for finding in payload["findings"]:
            traced = np.asarray(
                [[p["x"], p["y"], p["z"]] for p in finding["points_mm"]], dtype=float
            )
            distances = np.linalg.norm(traced[:, None, :] - truth_points[None, :, :], axis=2)
            mean_deviation = float(distances.min(axis=0).mean())
            if best is None or mean_deviation < best[0]:
                best = (mean_deviation, finding, float(distances.min(axis=1).mean()))
        lines.append(
            f"    {truth['side']:5} truth {truth['length_mm']}mm -> detector "
            f"{best[1]['side']} {len(best[1]['points_mm'])} pts conf={best[1]['confidence']} "
            f"mean deviation {best[0]:.2f} mm (reverse {best[2]:.2f} mm)"
        )
    return "\n".join(lines)


def _run_case(label: str, directory: Path, expect: str) -> bool:
    archive = _read_series(directory)
    volume, frame = load_volume(archive)
    payload = detect_canals(volume, frame)
    diagnostics = payload.pop("_diagnostics", {})
    print(f"\n[{label}] {directory}")
    print(
        f"  volume={volume.shape} HU {volume.min():.0f}..{volume.max():.0f} instances={frame['instance_count']}"
    )
    print(
        f"  otsu={diagnostics.get('otsu_thresholds')} bone_reference={diagnostics.get('bone_reference_hu')}"
    )
    print(
        f"  peak vesselness={diagnostics.get('peak_vesselness')} components={diagnostics.get('components')}"
    )
    for candidate in diagnostics.get("candidates") or []:
        verdict = "ACCEPT" if candidate.get("accepted") else "reject"
        print(
            f"    {verdict} len={candidate['length_mm']}mm tubularity={candidate['tubularity']} "
            f"radius={candidate['radius_mm']}mm wall_bone={candidate['wall_bone_fraction']} "
            f"{candidate.get('rejected', '')}"
        )
    print(f"  status={payload['status']} findings={len(payload['findings'])} (expected: {expect})")
    for finding in payload["findings"]:
        print(
            f"    {finding['side']:5} confidence={finding['confidence']} points={len(finding['points_mm'])}"
        )
    if expect == "detected":
        print(_score_against_ground_truth(payload, directory))
    ok = payload["status"] == expect
    print(f"  {'PASS' if ok else 'FAIL'}: expected {expect}, got {payload['status']}")
    return ok


def self_test(args: argparse.Namespace) -> int:
    print("=" * 78)
    print(f"{MODEL_ID} v{MODEL_VERSION} — self-test (is the detector input-dependent?)")
    print("=" * 78)
    results = []
    if args.mandibular:
        results.append(
            _run_case("positive: mandibular phantom WITH canal", args.mandibular, "detected")
        )
    if args.ablation:
        results.append(
            _run_case(
                "negative control: same phantom, canal ABLATED", args.ablation, "no_detection"
            )
        )
    if args.maxillary:
        results.append(
            _run_case(
                "negative control: maxillary fixture (no canal exists)",
                args.maxillary,
                "no_detection",
            )
        )
    if not results:
        print("nothing to test; pass --mandibular / --ablation / --maxillary")
        return 2
    print("\n" + "=" * 78)
    print(f"{sum(results)}/{len(results)} controls behaved as expected")
    print("=" * 78)
    return 0 if all(results) else 1


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    token = ""
    verbose = False

    def log_message(self, *args: Any) -> None:
        pass

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/health", "/v1/health"):
            self._send(
                200,
                {
                    "status": "ok",
                    "model_id": MODEL_ID,
                    "model_version": MODEL_VERSION,
                    "contract": CONTRACT,
                },
            )
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.rstrip("/").endswith("/nerve-detection"):
            self._send(404, {"error": "not found"})
            return
        if self.token and self.headers.get("Authorization") != f"Bearer {self.token}":
            self._send(401, {"error": "invalid or missing bearer token"})
            return
        if (self.headers.get("X-Dentora-Contract") or "") != CONTRACT:
            self._send(400, {"error": f"unsupported contract, expected {CONTRACT}"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        archive = self.rfile.read(length) if length else b""
        digest = self.headers.get("X-Dentora-Input-Digest") or ""
        actual = f"sha256:{hashlib.sha256(archive).hexdigest()}"
        if digest and digest != actual:
            self._send(400, {"error": "input digest mismatch"})
            return
        try:
            volume, frame = load_volume(archive)
            payload = detect_canals(volume, frame)
        except ValueError as exc:
            self._send(422, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - report, never fabricate a detection
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
            return

        diagnostics = payload.pop("_diagnostics", None)
        if self.verbose:
            print(
                f"  {frame['series_instance_uid']} -> {payload['status']} "
                f"findings={len(payload['findings'])} otsu={diagnostics.get('otsu_thresholds') if diagnostics else None}",
                flush=True,
            )
        self._send(200, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="serve_dev_nerve_service", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8191)
    parser.add_argument("--token", default="", help="bearer token the backend must present")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--self-test", action="store_true", help="run the controls and exit")
    parser.add_argument(
        "--mandibular", type=Path, default=None, help="phantom WITH canal (expect detected)"
    )
    parser.add_argument(
        "--ablation", type=Path, default=None, help="phantom WITHOUT canal (expect no_detection)"
    )
    parser.add_argument(
        "--maxillary", type=Path, default=None, help="maxillary fixture (expect no_detection)"
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test(args)

    Handler.token = args.token
    Handler.verbose = args.verbose
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"dentora dev nerve service ({MODEL_ID} v{MODEL_VERSION}) listening on "
        f"{args.host}:{args.port} contract={CONTRACT} token={'set' if args.token else 'none'}",
        flush=True,
    )
    print(
        "classical vesselness tracer; reports no_detection when no tube passes the geometric tests",
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
