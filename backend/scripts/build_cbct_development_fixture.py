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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, required=True, help="IOS mesh file (STL/OBJ/PLY)")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--ios-units", choices=sorted(_UNIT_TO_MM), default="mm")
    parser.add_argument("--slices", type=int, default=12)
    parser.add_argument("--slice-spacing-mm", type=float, default=0.5)
    parser.add_argument("--pixel-size-mm", type=float, default=0.3)
    parser.add_argument("--grid", type=int, default=256)
    args = parser.parse_args()

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
    (args.out_dir / "fixture_manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"WROTE {len(files)} synthetic instances + manifest to {args.out_dir}")
    print(f"series_instance_uid={FIXTURE_SERIES_UID}")
    print(f"frame_of_reference_uid={FIXTURE_FRAME_OF_REFERENCE_UID}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
