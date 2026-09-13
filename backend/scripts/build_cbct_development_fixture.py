"""Build a deterministic SYNTHETIC CBCT/DICOM development fixture.

This is DEVELOPMENT/TEST tooling, never production content: the emitted
series is explicitly labelled synthetic (Manufacturer/SeriesDescription)
and carries no patient PHI and no clinical finding. It exists so the real
Dentora CBCT -> alignment -> patient-space reference-frame workflow can be
exercised end-to-end without a real patient scan.

The fixture is spatially coherent with a patient's IOS mesh: mesh vertices
are rasterised into synthetic axial CT slices (16-bit, value 1000) using
the DICOM patient-coordinate mapping (ImagePositionPatient /
ImageOrientationPatient / PixelSpacing), so a threshold-extracting anatomy
consumer reproduces a point cloud that genuinely registers against the
mesh with the production Open3D pipeline. Nothing here fabricates
anatomy, a diagnosis, or an acceptance decision — the dentist review
steps stay exactly as designed.

Usage (backend venv):
    python -m scripts.build_cbct_development_fixture \
        --mesh /path/to/scan.stl --out-dir /tmp/cbct_fixture_dev \
        [--ios-units mm] [--slices 12] [--slice-spacing-mm 0.5] \
        [--pixel-size-mm 0.3] [--grid 256]

Outputs one ``.dcm`` per slice plus ``fixture_manifest.json`` with the
deterministic Study/Series/Frame-of-Reference UIDs for the alignment
request.
"""

from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

# Fixed UIDs: the fixture is deterministic and reproducible by design.
FIXTURE_STUDY_UID = "1.2.826.0.1.3680043.10.1337.9001"
FIXTURE_SERIES_UID = "1.2.826.0.1.3680043.10.1337.9002"
FIXTURE_FRAME_OF_REFERENCE_UID = "1.2.826.0.1.3680043.10.1337.9003"
FIXTURE_MANUFACTURER = "DENTORA-DEV-FIXTURE"
FIXTURE_MODEL_NAME = "SYNTHETIC-CBCT-DEV-0.1"
PIXEL_VALUE = 1000

_UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4}


def build_series_bytes(
    *,
    mesh_path: Path,
    slices: int = 12,
    slice_spacing_mm: float = 0.5,
    pixel_size_mm: float = 0.3,
    grid: int = 256,
    ios_units: str = "mm",
) -> list[tuple[str, bytes, dict]]:
    """Rasterise ``mesh_path`` into ``slices`` synthetic axial CT instances.

    Returns ``[(filename, bytes, header_dict), ...]`` sorted by InstanceNumber.
    """
    import numpy as np
    import open3d as o3d
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian

    mesh = o3d.io.read_triangle_mesh(str(mesh_path), enable_post_processing=False)
    if mesh.is_empty():
        raise SystemExit(f"fixture builder: could not read mesh vertices from {mesh_path}")
    vertices = np.asarray(mesh.vertices, dtype=float) * _UNIT_TO_MM[ios_units]
    if not np.isfinite(vertices).all():
        raise SystemExit("fixture builder: mesh contains non-finite coordinates")

    # Center the mesh at the origin, lift the arch onto the slice stack and
    # place it inside the FOV so row/col indices stay in range.
    center = (vertices.min(axis=0) + vertices.max(axis=0)) / 2.0
    z0 = round(slices * slice_spacing_mm / 2.0, 3)  # mid-stack patient z
    pts = vertices - center
    pts[:, 2] += z0

    extent = float(np.abs(pts[:, :2]).max()) + 4 * pixel_size_mm
    if extent >= grid * pixel_size_mm / 2.0:
        raise SystemExit("fixture builder: mesh does not fit the requested pixel grid")

    origin_xy = -(grid * pixel_size_mm) / 2.0
    orientation = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]  # axial, HFS-style LPS
    files: list[tuple[str, bytes, dict]] = []
    for index in range(slices):
        position = [round(origin_xy, 4), round(origin_xy, 4), round(index * slice_spacing_mm, 4)]
        slice_z = position[2]
        on_slice = np.abs(pts[:, 2] - slice_z) <= slice_spacing_mm / 2.0
        pixels = np.zeros((grid, grid), dtype=np.uint16)
        cols = np.round((pts[on_slice, 0] - position[0]) / pixel_size_mm).astype(int)
        rows = np.round((pts[on_slice, 1] - position[1]) / pixel_size_mm).astype(int)
        keep = (cols >= 0) & (cols < grid) & (rows >= 0) & (rows < grid)
        pixels[rows[keep], cols[keep]] = PIXEL_VALUE

        sop_uid = f"{FIXTURE_SERIES_UID}.{index + 1}"
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = CTImageStorage
        file_meta.MediaStorageSOPInstanceUID = sop_uid
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file_meta.ImplementationClassUID = "1.2.826.0.1.3680043.10.1337.9000"
        dataset = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
        dataset.SOPClassUID = CTImageStorage
        dataset.SOPInstanceUID = sop_uid
        dataset.StudyInstanceUID = FIXTURE_STUDY_UID
        dataset.SeriesInstanceUID = FIXTURE_SERIES_UID
        dataset.FrameOfReferenceUID = FIXTURE_FRAME_OF_REFERENCE_UID
        dataset.Modality = "CT"
        dataset.SeriesDescription = "SYNTHETIC development fixture - not a patient scan"
        dataset.Manufacturer = FIXTURE_MANUFACTURER
        dataset.ManufacturerModelName = FIXTURE_MODEL_NAME
        dataset.Rows = grid
        dataset.Columns = grid
        dataset.NumberOfFrames = 1
        dataset.PixelSpacing = [pixel_size_mm, pixel_size_mm]
        dataset.SliceThickness = slice_spacing_mm
        dataset.ImagePositionPatient = position
        dataset.ImageOrientationPatient = orientation
        dataset.InstanceNumber = index + 1
        dataset.BitsAllocated = 16
        dataset.BitsStored = 16
        dataset.HighBit = 15
        dataset.PixelRepresentation = 0
        dataset.SamplesPerPixel = 1
        dataset.PhotometricInterpretation = "MONOCHROME2"
        dataset.PixelData = pixels.tobytes()

        stream = BytesIO()
        dataset.save_as(stream, enforce_file_format=True)
        files.append(
            (
                f"slice_{index:03d}.dcm",
                stream.getvalue(),
                {
                    "sop_instance_uid": sop_uid,
                    "image_position_patient_mm": position,
                    "image_orientation_patient": orientation,
                    "pixel_spacing_mm": [pixel_size_mm, pixel_size_mm],
                    "slice_thickness_mm": slice_spacing_mm,
                },
            )
        )
    return files


# --------------------------------------------------------------------------
# Volumetric mandibular phantom (Task B)
# --------------------------------------------------------------------------
# The arch-surface mode above draws mesh vertices at one constant intensity.
# That is enough to exercise ingestion and registration, but a canal detector
# needs a *volume* with real intensity contrast: dense bone enclosing a dark,
# continuous, roughly circular tube. This mode builds exactly that, from the
# same deterministic arch parametrization the IOS builder uses, so the phantom
# and the intraoral scan stay spatially coherent.
#
# Intensities follow the real CT convention (stored = HU - RescaleIntercept).
PHANTOM_HU = {
    "background": -300.0,  # extra-oral soft tissue / air mix
    "cancellous": 350.0,  # trabecular bone inside the mandibular body
    "cortical": 900.0,  # dense outer shell, gives the canal bright walls
    "tooth": 1500.0,  # enamel/dentin composite
    "canal": 60.0,  # IAN neurovascular bundle: soft tissue in bone
}
PHANTOM_RESCALE_INTERCEPT = -1024.0

BONE_HALF_WIDTH_MM = 5.2  # ~10.4 mm buccolingual body width
BONE_BODY_HEIGHT_MM = 14.0  # alveolar crest down to the inferior border
CORTICAL_SHELL_MM = 1.3
CANAL_RADIUS_MM = 1.4  # 2.8 mm diameter, within the 2-4 mm real range
CANAL_LINGUAL_OFFSET_MM = 1.2  # the canal runs lingual to the tooth row
CANAL_POSTERIOR_DEG = 118.0  # extends back into the ramus past the arch sweep
CANAL_ANTERIOR_DEG = 64.0  # ends at the mental foramen (~2nd premolar)


def _arch_curve(scale: float, z_offset: float, degrees: float, samples: int):
    """Sample the arch ellipse, reusing the IOS builder's own parametrization.

    Returns (points Nx3, tangent angles). The mandibular arch is the same
    ellipse the IOS fixture uses, scaled 0.94 and dropped 14 mm, so bone,
    teeth and scan occupy one coherent space.
    """
    import numpy as np

    from scripts.build_ios_development_fixture import (
        ARCH_DEPTH_MM,
        ARCH_HALF_WIDTH_MM,
    )

    t = np.radians(np.linspace(-degrees, degrees, samples))
    x = ARCH_HALF_WIDTH_MM * np.sin(t) * scale
    y = ARCH_DEPTH_MM * np.cos(t) * scale
    return np.column_stack([x, y, np.full_like(x, z_offset)]), t


def _distance_map(points_xy, *, grid: int, origin_xy: float, pixel_size_mm: float):
    """Millimetre distance map to a densely sampled polyline.

    The polyline is rasterised into the slice grid and the exact Euclidean
    distance transform is taken from it. Sampling the curve far below the
    pixel pitch keeps the error under a fraction of a pixel, which is well
    inside the tolerance of a 5 mm bone band or a 1.4 mm canal radius, and it
    is orders of magnitude cheaper than an all-pairs segment distance.
    """
    import numpy as np
    from scipy.ndimage import distance_transform_edt

    background = np.ones((grid, grid), dtype=bool)
    cols = np.round((points_xy[:, 0] - origin_xy) / pixel_size_mm).astype(int)
    rows = np.round((points_xy[:, 1] - origin_xy) / pixel_size_mm).astype(int)
    keep = (cols >= 0) & (cols < grid) & (rows >= 0) & (rows < grid)
    background[rows[keep], cols[keep]] = False
    return distance_transform_edt(background, sampling=pixel_size_mm)


def build_phantom_volume(
    *,
    grid: int,
    pixel_size_mm: float,
    slices: int,
    slice_spacing_mm: float,
    arch: str = "mandibular",
    with_canal: bool = True,
):
    """Rasterise a mandibular bone body + teeth + IAN canal into an HU volume.

    Returns ``(volume, meta)`` where ``volume[k, row, col]`` is HU in the
    DICOM patient frame, and ``meta`` carries the geometry plus the *ground
    truth* canal centrelines so a detector can be scored against them.
    """
    import numpy as np

    from scripts.build_ios_development_fixture import build_arch_mesh

    mesh, teeth = build_arch_mesh(arch)
    vertices = np.asarray(mesh.vertices, dtype=float)
    # Same placement rule as the arch-surface mode: centre in-plane, lift the
    # stack so the phantom sits mid-volume.
    center = (vertices.min(axis=0) + vertices.max(axis=0)) / 2.0
    scale = 0.94 if arch == "mandibular" else 1.0

    # build_arch_mesh has already applied the mandibular scale and its -14 mm
    # drop, so only the in-plane centring is left to undo here. Shifting twice
    # pushed the whole bone body below the slice stack.
    zmin_rel = float(vertices[:, 2].min()) - center[2]
    zmax_rel = float(vertices[:, 2].max()) - center[2]
    crest_rel = zmin_rel + 2.0  # alveolar crest, just above the ridge base
    inferior_rel = crest_rel - BONE_BODY_HEIGHT_MM
    # Lift so the crest-to-inferior-border span plus the crowns sit mid-stack.
    z_lift = (slices * slice_spacing_mm) / 2.0 - (inferior_rel + zmax_rel) / 2.0
    mesh_min_z = zmin_rel + z_lift
    mesh_max_z = zmax_rel + z_lift
    z_crest = crest_rel + z_lift
    z_inferior = inferior_rel + z_lift

    origin_xy = -(grid * pixel_size_mm) / 2.0
    axis = origin_xy + np.arange(grid) * pixel_size_mm
    xs, ys = np.meshgrid(axis, axis, indexing="xy")
    zz = np.arange(slices) * slice_spacing_mm

    # --- bone body: a U-shaped band around the arch, crest down to the border
    curve, _t = _arch_curve(scale, 0.0, 130.0, 1400)

    volume = np.full((slices, grid, grid), PHANTOM_HU["background"], dtype=np.float32)
    # The arch curve is in mesh space; the volume is centred, so shift it by
    # the same in-plane centre the teeth and canal use.
    d_bone = _distance_map(
        curve[:, :2] - center[:2], grid=grid, origin_xy=origin_xy, pixel_size_mm=pixel_size_mm
    )
    in_band = d_bone <= BONE_HALF_WIDTH_MM
    cortical = in_band & (d_bone >= BONE_HALF_WIDTH_MM - CORTICAL_SHELL_MM)
    for k, z in enumerate(zz):
        if not (z_inferior - 0.5 <= z <= z_crest + 3.0):
            continue
        slab = np.where(cortical, PHANTOM_HU["cortical"], 0.0)
        slab = np.where(in_band & ~cortical, PHANTOM_HU["cancellous"], slab)
        # cortical also caps the inferior border and the crest
        if z <= z_inferior + CORTICAL_SHELL_MM or z >= z_crest + 3.0 - CORTICAL_SHELL_MM:
            slab = np.where(in_band, PHANTOM_HU["cortical"], slab)
        volume[k] = np.where(in_band, slab, PHANTOM_HU["background"])

    # --- teeth: ellipsoids at the IOS fixture's own centres and dimensions
    from scripts.build_ios_development_fixture import TOOTH_DIMENSIONS_MM

    tooth_pts = []
    for tooth in teeth:
        c = tooth["centre_mm"]
        md, bl, ch = TOOTH_DIMENSIONS_MM[tooth["tooth_class"]]
        cx = c["x"] - center[0]
        cy = c["y"] - center[1]
        cz = c["z"] - center[2] + z_lift
        # crown ellipsoid plus a tapered root below it, both inside the bone
        for dz, r_scale, half_h in ((ch * 0.25, 1.0, ch * 0.55), (-ch * 0.45, 0.62, ch * 0.55)):
            rx, ry, rz = md / 2 * r_scale, bl / 2 * r_scale, half_h
            near = (np.abs(xs - cx) <= rx + 1.0) & (np.abs(ys - cy) <= ry + 1.0)
            kz = [k for k, z in enumerate(zz) if abs(z - (cz + dz)) <= rz + slice_spacing_mm]
            for k in kz:
                dzv = (zz[k] - (cz + dz)) / rz
                if abs(dzv) > 1.0:
                    continue
                ellipse = ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2
                fill = (ellipse + dzv**2) <= 1.0
                volume[k] = np.where(fill & near, PHANTOM_HU["tooth"], volume[k])
        tooth_pts.append((cx, cy, cz))

    ground_truth = []
    if with_canal:
        # --- IAN canal: a tube from the ramus to the mental foramen, lingual
        # to the tooth row and below the roots, mirroring real anatomy.
        for side in (-1.0, 1.0):
            degrees = np.linspace(-CANAL_POSTERIOR_DEG, -CANAL_ANTERIOR_DEG, 220)
            if side > 0:
                degrees = -degrees  # mirror to the patient's left
            t = np.radians(degrees)
            from scripts.build_ios_development_fixture import ARCH_DEPTH_MM, ARCH_HALF_WIDTH_MM

            cx = ARCH_HALF_WIDTH_MM * np.sin(t) * scale
            cy = ARCH_DEPTH_MM * np.cos(t) * scale
            # lingual offset: move toward the arch interior along the normal
            radial = np.column_stack([cx, cy])
            norm = radial / np.maximum(np.linalg.norm(radial, axis=1, keepdims=True), 1e-9)
            cx = cx - norm[:, 0] * CANAL_LINGUAL_OFFSET_MM
            cy = cy - norm[:, 1] * CANAL_LINGUAL_OFFSET_MM
            # z: higher at the ramus, dipping through the body, rising at the foramen
            span = (degrees - degrees[0]) / (degrees[-1] - degrees[0])
            cz = z_crest - 4.0 - 4.5 * np.sin(np.pi * np.clip(span * 1.15, 0, 1))
            # cz is already expressed against z_crest in volume space.
            canal = np.column_stack([cx - center[0], cy - center[1], cz])
            ground_truth.append(
                {
                    "side": "left" if side > 0 else "right",
                    "points_mm": [[round(float(v), 3) for v in p] for p in canal],
                    "radius_mm": CANAL_RADIUS_MM,
                    "length_mm": round(
                        float(np.sum(np.linalg.norm(np.diff(canal, axis=0), axis=1))), 2
                    ),
                }
            )
            # render the tube: distance to the 3D polyline, per slice
            for k, z in enumerate(zz):
                seg = canal[(canal[:, 2] > z - 3.0) & (canal[:, 2] < z + 3.0)]
                if len(seg) < 2:
                    continue
                # The canal rises gently, so within one slice it is very nearly
                # axial and a 2D distance map to the local segment is faithful.
                d = _distance_map(
                    seg[:, :2], grid=grid, origin_xy=origin_xy, pixel_size_mm=pixel_size_mm
                )
                dz_best = np.min(np.abs(seg[:, 2] - z))
                r_eff = (
                    CANAL_RADIUS_MM * np.sqrt(max(0.0, 1.0 - (dz_best / CANAL_RADIUS_MM) ** 2))
                    if dz_best < CANAL_RADIUS_MM
                    else 0.0
                )
                if r_eff <= 0.05:
                    continue
                lumen = d <= r_eff
                volume[k] = np.where(lumen, PHANTOM_HU["canal"], volume[k])

    meta = {
        "arch": arch,
        "with_canal": with_canal,
        "grid": grid,
        "pixel_size_mm": pixel_size_mm,
        "slices": slices,
        "slice_spacing_mm": slice_spacing_mm,
        "origin_xy_mm": origin_xy,
        "z_lift_mm": round(z_lift, 3),
        "z_mesh_base_mm": round(mesh_min_z, 3),
        "z_occlusal_mm": round(mesh_max_z, 3),
        "z_crest_mm": round(z_crest, 3),
        "z_inferior_mm": round(z_inferior, 3),
        "hu": PHANTOM_HU,
        "rescale_intercept": PHANTOM_RESCALE_INTERCEPT,
        "canal_ground_truth": ground_truth,
    }
    return volume, meta


def build_phantom_series_bytes(
    *,
    grid: int,
    pixel_size_mm: float,
    slices: int,
    slice_spacing_mm: float,
    arch: str,
    with_canal: bool,
) -> tuple[list[tuple[str, bytes, dict]], dict]:
    """Encode the phantom volume as axial CT instances (HU via rescale tags)."""
    import numpy as np
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian

    volume, meta = build_phantom_volume(
        grid=grid,
        pixel_size_mm=pixel_size_mm,
        slices=slices,
        slice_spacing_mm=slice_spacing_mm,
        arch=arch,
        with_canal=with_canal,
    )
    stored = np.rint(volume - PHANTOM_RESCALE_INTERCEPT).astype(np.uint16)
    origin_xy = meta["origin_xy_mm"]
    orientation = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    files: list[tuple[str, bytes, dict]] = []
    for index in range(slices):
        position = [round(origin_xy, 4), round(origin_xy, 4), round(index * slice_spacing_mm, 4)]
        sop_uid = f"{FIXTURE_SERIES_UID}.{index + 1}"
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = CTImageStorage
        file_meta.MediaStorageSOPInstanceUID = sop_uid
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file_meta.ImplementationClassUID = "1.2.826.0.1.3680043.10.1337.9000"
        dataset = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
        dataset.SOPClassUID = CTImageStorage
        dataset.SOPInstanceUID = sop_uid
        dataset.StudyInstanceUID = FIXTURE_STUDY_UID
        dataset.SeriesInstanceUID = FIXTURE_SERIES_UID
        dataset.FrameOfReferenceUID = FIXTURE_FRAME_OF_REFERENCE_UID
        dataset.Modality = "CT"
        # VR LO is capped at 64 characters; keep the synthetic marker inside it.
        dataset.SeriesDescription = "SYNTHETIC mandibular dev phantom - not a patient scan"
        dataset.Manufacturer = FIXTURE_MANUFACTURER
        dataset.ManufacturerModelName = FIXTURE_MODEL_NAME
        dataset.Rows = grid
        dataset.Columns = grid
        dataset.NumberOfFrames = 1
        dataset.PixelSpacing = [pixel_size_mm, pixel_size_mm]
        dataset.SliceThickness = slice_spacing_mm
        dataset.ImagePositionPatient = position
        dataset.ImageOrientationPatient = orientation
        dataset.InstanceNumber = index + 1
        dataset.BitsAllocated = 16
        dataset.BitsStored = 16
        dataset.HighBit = 15
        dataset.PixelRepresentation = 0
        dataset.SamplesPerPixel = 1
        dataset.PhotometricInterpretation = "MONOCHROME2"
        dataset.RescaleIntercept = PHANTOM_RESCALE_INTERCEPT
        dataset.RescaleSlope = 1.0
        dataset.PixelData = stored[index].tobytes()
        stream = BytesIO()
        dataset.save_as(stream, enforce_file_format=True)
        files.append(
            (
                f"slice_{index:03d}.dcm",
                stream.getvalue(),
                {
                    "sop_instance_uid": sop_uid,
                    "image_position_patient_mm": position,
                    "image_orientation_patient": orientation,
                    "pixel_spacing_mm": [pixel_size_mm, pixel_size_mm],
                    "slice_thickness_mm": slice_spacing_mm,
                    "rescale_intercept": PHANTOM_RESCALE_INTERCEPT,
                    "rescale_slope": 1.0,
                },
            )
        )
    return files, meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mesh",
        type=Path,
        default=None,
        help="IOS mesh file (STL/OBJ/PLY); required for --anatomy arch_surface",
    )
    parser.add_argument(
        "--anatomy",
        choices=("arch_surface", "mandibular_phantom"),
        default="arch_surface",
        help="arch_surface rasterises the mesh's own vertices (the original "
        "fixture). mandibular_phantom builds a volumetric bone body with teeth "
        "and an inferior alveolar canal, so a canal detector has real "
        "intensity contrast to work with.",
    )
    parser.add_argument("--arch", choices=("maxillary", "mandibular"), default="mandibular")
    parser.add_argument(
        "--no-canal",
        action="store_true",
        help="phantom ablation: identical bone and teeth, canal omitted. A real "
        "detector must report no detection on this volume.",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--ios-units", choices=sorted(_UNIT_TO_MM), default="mm")
    parser.add_argument("--slices", type=int, default=12)
    parser.add_argument("--slice-spacing-mm", type=float, default=0.5)
    parser.add_argument("--pixel-size-mm", type=float, default=0.3)
    parser.add_argument("--grid", type=int, default=256)
    parser.add_argument(
        "--uid-namespace",
        type=int,
        default=9000,
        help="UID suffix block. The fixture stays deterministic for a given "
        "value; bump it to mint a fresh study/series/frame of reference so the "
        "same patient (or another one) can be re-ingested without SOP clashes.",
    )
    args = parser.parse_args()

    global FIXTURE_STUDY_UID, FIXTURE_SERIES_UID, FIXTURE_FRAME_OF_REFERENCE_UID
    base = int(args.uid_namespace)
    FIXTURE_STUDY_UID = f"1.2.826.0.1.3680043.10.1337.{base + 1}"
    FIXTURE_SERIES_UID = f"1.2.826.0.1.3680043.10.1337.{base + 2}"
    FIXTURE_FRAME_OF_REFERENCE_UID = f"1.2.826.0.1.3680043.10.1337.{base + 3}"

    phantom_meta: dict = {}
    if args.anatomy == "mandibular_phantom":
        files, phantom_meta = build_phantom_series_bytes(
            grid=args.grid,
            pixel_size_mm=args.pixel_size_mm,
            slices=args.slices,
            slice_spacing_mm=args.slice_spacing_mm,
            arch=args.arch,
            with_canal=not args.no_canal,
        )
    else:
        if args.mesh is None:
            raise SystemExit("fixture builder: --mesh is required for --anatomy arch_surface")
        files = build_series_bytes(
            mesh_path=args.mesh,
            slices=args.slices,
            slice_spacing_mm=args.slice_spacing_mm,
            pixel_size_mm=args.pixel_size_mm,
            grid=args.grid,
            ios_units=args.ios_units,
        )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for filename, payload, _header in files:
        (args.out_dir / filename).write_bytes(payload)
    manifest = {
        "fixture": "dentora-development-cbct-fixture/1",
        "synthetic": True,
        "phi_free": True,
        "study_instance_uid": FIXTURE_STUDY_UID,
        "series_instance_uid": FIXTURE_SERIES_UID,
        "frame_of_reference_uid": FIXTURE_FRAME_OF_REFERENCE_UID,
        "instances": [{"file": filename, **header} for filename, _payload, header in files],
    }
    if phantom_meta:
        # The canal centrelines are ground truth for scoring a detector; they
        # are fixture metadata, never something a detector is allowed to read.
        manifest["fixture"] = "dentora-development-mandibular-phantom/1"
        manifest["phantom"] = phantom_meta
    (args.out_dir / "fixture_manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"WROTE {len(files)} synthetic instances + manifest to {args.out_dir}")
    if phantom_meta:
        canals = phantom_meta.get("canal_ground_truth") or []
        print(
            f"anatomy={args.anatomy} arch={args.arch} canal={'no' if args.no_canal else 'yes'} "
            f"canal_centrelines={len(canals)} "
            f"lengths_mm={[c['length_mm'] for c in canals]}"
        )
        print(
            f"z_occlusal={phantom_meta['z_occlusal_mm']} z_crest={phantom_meta['z_crest_mm']} "
            f"z_inferior={phantom_meta['z_inferior_mm']}"
        )
    print(f"series_instance_uid={FIXTURE_SERIES_UID}")
    print(f"frame_of_reference_uid={FIXTURE_FRAME_OF_REFERENCE_UID}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
