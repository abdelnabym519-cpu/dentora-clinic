from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

MANDIBULAR_CANAL_LABEL = 5


@dataclass(frozen=True)
class ImageGeometry:
    size_xyz: tuple[int, int, int]
    spacing_xyz: tuple[float, float, float]
    origin_lps: tuple[float, float, float]
    direction: tuple[float, ...]

    def physical_center_lps(self) -> np.ndarray:
        center_xyz = (np.asarray(self.size_xyz, dtype=np.float64) - 1.0) / 2.0
        return indices_xyz_to_lps(center_xyz[None, :], self)[0]


@dataclass(frozen=True)
class CanalFinding:
    side: str
    confidence: float
    uncertainty: float
    points_mm: tuple[tuple[float, float, float], ...]
    voxels: int


@dataclass(frozen=True)
class PostprocessResult:
    status: str
    findings: tuple[CanalFinding, ...]
    significant_component_count: int


def indices_xyz_to_lps(indices_xyz: np.ndarray, geometry: ImageGeometry) -> np.ndarray:
    indices = np.asarray(indices_xyz, dtype=np.float64)
    spacing = np.asarray(geometry.spacing_xyz, dtype=np.float64)
    origin = np.asarray(geometry.origin_lps, dtype=np.float64)
    direction = np.asarray(geometry.direction, dtype=np.float64).reshape(3, 3)
    return origin + (indices * spacing) @ direction.T


def _ordered_centerline(points_lps: np.ndarray, *, max_points: int = 128) -> tuple[tuple[float, float, float], ...]:
    if len(points_lps) < 2:
        return ()
    center = points_lps.mean(axis=0)
    centered = points_lps - center
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    axis = vh[0]
    projection = centered @ axis
    lo = float(projection.min())
    hi = float(projection.max())
    if hi - lo < 1e-6:
        return ()

    target_points = min(max_points, max(8, int(np.ceil((hi - lo) / 2.0)) + 1))
    edges = np.linspace(lo, hi, target_points + 1)
    centers: list[np.ndarray] = []
    for index in range(target_points):
        if index == target_points - 1:
            selected = (projection >= edges[index]) & (projection <= edges[index + 1])
        else:
            selected = (projection >= edges[index]) & (projection < edges[index + 1])
        if np.any(selected):
            centers.append(points_lps[selected].mean(axis=0))

    if len(centers) < 2:
        return ()
    path = np.vstack(centers)
    if len(path) > 2:
        smoothed = path.copy()
        smoothed[1:-1] = (path[:-2] + path[1:-1] + path[2:]) / 3.0
        path = smoothed

    keep = [0]
    for index in range(1, len(path)):
        if np.linalg.norm(path[index] - path[keep[-1]]) >= 0.25:
            keep.append(index)
    path = path[keep]
    if len(path) < 2:
        return ()

    first = tuple(np.round(path[0], 6))
    last = tuple(np.round(path[-1], 6))
    if first > last:
        path = path[::-1]
    return tuple(tuple(float(value) for value in point) for point in path)


def extract_canal_findings(
    segmentation_zyx: np.ndarray,
    geometry: ImageGeometry,
    *,
    confidence: float,
    low_confidence_threshold: float = 0.6,
    min_component_voxels: int = 1,
) -> PostprocessResult:
    segmentation = np.asarray(segmentation_zyx)
    expected_zyx = tuple(reversed(geometry.size_xyz))
    if segmentation.ndim != 3 or tuple(segmentation.shape) != expected_zyx:
        raise ValueError("segmentation shape does not match native geometry")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError("confidence must be in [0, 1]")
    if min_component_voxels < 1:
        raise ValueError("min_component_voxels must be positive")

    mask = segmentation == MANDIBULAR_CANAL_LABEL
    labels, count = ndimage.label(mask, structure=np.ones((3, 3, 3), dtype=np.uint8))
    if count == 0:
        return PostprocessResult("no_detection", (), 0)

    sizes = np.bincount(labels.ravel())
    significant = [
        (label_id, int(sizes[label_id]))
        for label_id in range(1, len(sizes))
        if sizes[label_id] >= min_component_voxels
    ]
    significant.sort(key=lambda item: (-item[1], item[0]))
    if not significant:
        return PostprocessResult("no_detection", (), 0)

    selected = significant[:2]
    components: list[dict[str, object]] = []
    for label_id, voxel_count in selected:
        indices_zyx = np.argwhere(labels == label_id)
        indices_xyz = indices_zyx[:, ::-1]
        points_lps = indices_xyz_to_lps(indices_xyz, geometry)
        centerline = _ordered_centerline(points_lps)
        if len(centerline) < 2:
            continue
        components.append(
            {
                "voxels": voxel_count,
                "centroid": points_lps.mean(axis=0),
                "points": centerline,
            }
        )

    if not components:
        return PostprocessResult("no_detection", (), len(significant))

    center_x = float(geometry.physical_center_lps()[0])
    if len(components) == 2:
        ordered = sorted(components, key=lambda item: float(np.asarray(item["centroid"])[0]))
        ordered[0]["side"] = "right"
        ordered[1]["side"] = "left"
        components = ordered
    else:
        centroid_x = float(np.asarray(components[0]["centroid"])[0])
        components[0]["side"] = "left" if centroid_x >= center_x else "right"

    uncertainty = 1.0 - confidence
    findings = tuple(
        CanalFinding(
            side=str(item["side"]),
            confidence=float(confidence),
            uncertainty=float(uncertainty),
            points_mm=tuple(item["points"]),
            voxels=int(item["voxels"]),
        )
        for item in components
    )
    status = "detected"
    if confidence < low_confidence_threshold or len(significant) != 2 or len(findings) != 2:
        status = "uncertain"
    return PostprocessResult(status, findings, len(significant))
