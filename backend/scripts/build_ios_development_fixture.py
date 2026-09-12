#!/usr/bin/env python3
"""Build a deterministic SYNTHETIC intraoral-scan (IOS) development fixture.

DEVELOPMENT/TEST tooling, never production content and never clinical data:
the emitted mesh is a parametric dental arch, labelled synthetic in its
manifest, carrying no PHI and no clinical finding. It exists because the
real geometry chain — mesh ingestion → CBCT registration → dentist
acceptance → risk map / implant planning / orthodontic simulation — cannot
be exercised without an intraoral scan, and no scan may be committed to the
repository.

The arch is built in **millimetres** with anatomically plausible dimensions
(14 teeth, FDI-numbered, mesiodistal/buccolingual/crown-height sizes per
tooth class, occlusal cusps on premolars and molars, a continuous gingival
ridge) so that:

* ``app.modules.dental_3d.meshfiles`` accepts it as a real binary STL,
* deterministic arch segmentation has tooth positions to partition,
* ``scripts.build_cbct_development_fixture`` can rasterise the very same
  vertices into a CBCT series that genuinely registers against it with the
  production Open3D pipeline (overlap is guaranteed by construction, not by
  tolerance fudging),
* the orthodontic simulator has a patient-derived mesh to move.

Nothing here fabricates anatomy, a diagnosis, or an acceptance decision —
the dentist review steps stay exactly as designed.

Usage (backend venv)::

    python -m scripts.build_ios_development_fixture --out-dir /tmp/ios_fixture_dev
    python -m scripts.build_ios_development_fixture --arch mandibular \
        --out /tmp/ios_fixture_dev/scan_lower.stl

Outputs ``scan_<arch>.stl`` plus ``ios_fixture_manifest.json`` recording the
units, bounding box, per-tooth centres and the file digest, so a run can be
verified byte-for-byte and repeated deterministically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

# Fixed identity: the fixture is deterministic and reproducible by design.
FIXTURE_GENERATOR = "DENTORA-DEV-FIXTURE"
FIXTURE_MESH_NAME = "SYNTHETIC-IOS-ARCH-0.1"

# Arch geometry (millimetres). A human dental arch is well approximated by
# half an ellipse: ~50-55 mm across the molars, ~45-50 mm from the incisal
# edge to the tuberosities.
ARCH_HALF_WIDTH_MM = 25.0
ARCH_DEPTH_MM = 32.0
ARCH_SWEEP_DEG = 96.0  # each side of the midline
GINGIVAL_Z_MM = 0.0
CROWN_HEIGHT_MM = 9.0

# FDI numbering for a full arch, left-to-right across the midline.
MAXILLARY_TEETH = (17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27)
MANDIBULAR_TEETH = (47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37)

# (mesiodistal, buccolingual, crown height) in millimetres, per tooth class.
# Values follow standard adult permanent-tooth averages; they only need to
# be plausible and distinct enough for partitioning and registration.
TOOTH_DIMENSIONS_MM: dict[str, tuple[float, float, float]] = {
    "central_incisor": (8.5, 7.0, 9.0),
    "lateral_incisor": (7.0, 6.2, 8.5),
    "canine": (7.6, 8.0, 10.0),
    "first_premolar": (7.1, 9.0, 8.5),
    "second_premolar": (6.6, 8.7, 8.0),
    "first_molar": (10.0, 11.0, 7.5),
    "second_molar": (9.5, 10.5, 7.0),
}

# Cusp count on the occlusal surface, by class. Anterior teeth get a single
# ridge; premolars two; molars four — enough surface detail for ICP to lock
# onto without pretending to be a real scan.
CUSP_COUNT: dict[str, int] = {
    "central_incisor": 1,
    "lateral_incisor": 1,
    "canine": 1,
    "first_premolar": 2,
    "second_premolar": 2,
    "first_molar": 4,
    "second_molar": 4,
}


@dataclass(frozen=True)
class ToothSpec:
    fdi: int
    tooth_class: str
    index: int  # 0-based position along the arch


def _tooth_class(fdi: int) -> str:
    """Map an FDI number to its anatomical class (position 1-7 from midline)."""
    position = fdi % 10
    return {
        1: "central_incisor",
        2: "lateral_incisor",
        3: "canine",
        4: "first_premolar",
        5: "second_premolar",
        6: "first_molar",
        7: "second_molar",
    }[position]


def _arch_specs(arch: str) -> tuple[ToothSpec, ...]:
    teeth = MAXILLARY_TEETH if arch == "maxillary" else MANDIBULAR_TEETH
    return tuple(ToothSpec(fdi, _tooth_class(fdi), i) for i, fdi in enumerate(teeth))


def _arch_position(index: int, count: int) -> tuple[float, float, float]:
    """A point on the arch ellipse, sweeping from one tuberosity to the other.

    ``index`` runs left-to-right across the midline, so the midline incisors
    land at the front (+Y) and the molars at the back.
    """
    if count == 1:
        t = 0.0
    else:
        fraction = index / (count - 1)  # 0 .. 1
        t = math.radians(-ARCH_SWEEP_DEG + 2 * ARCH_SWEEP_DEG * fraction)
    x = ARCH_HALF_WIDTH_MM * math.sin(t)
    y = ARCH_DEPTH_MM * math.cos(t)
    return x, y, t


def _ellipsoid(radius: tuple[float, float, float], subdivisions: int = 2) -> trimesh.Trimesh:
    sphere = trimesh.creation.icosphere(subdivisions=subdivisions, radius=1.0)
    sphere.apply_scale(1.0)
    sphere.vertices *= np.asarray(radius, dtype=float)
    return sphere


def _tooth_mesh(
    spec: ToothSpec, centre: tuple[float, float, float], tangent: float
) -> trimesh.Trimesh:
    """One crown plus its occlusal cusps, oriented along the arch tangent."""
    mesiodistal, buccolingual, height = TOOTH_DIMENSIONS_MM[spec.tooth_class]
    parts: list[trimesh.Trimesh] = []

    # Crown: an ellipsoid flattened buccolingually, tapering to the incisal
    # edge / occlusal table.
    crown = _ellipsoid((mesiodistal / 2, buccolingual / 2, height / 2))
    crown.apply_translation((0.0, 0.0, height / 2))
    parts.append(crown)

    # Occlusal cusps sit on the crown's top surface.
    cusps = CUSP_COUNT[spec.tooth_class]
    cusp_radius = min(mesiodistal, buccolingual) * 0.22
    for c in range(cusps):
        if cusps == 1:
            offset_md, offset_bl = 0.0, 0.0
        elif cusps == 2:
            offset_md = (mesiodistal / 2 - cusp_radius) * (1 if c == 0 else -1)
            offset_bl = 0.0
        else:
            offset_md = (mesiodistal / 2 - cusp_radius) * (1 if c % 2 == 0 else -1)
            offset_bl = (buccolingual / 2 - cusp_radius) * (1 if c < 2 else -1)
        cusp = _ellipsoid((cusp_radius, cusp_radius, cusp_radius * 1.3), subdivisions=1)
        cusp.apply_translation((offset_md, offset_bl, height - cusp_radius * 0.5))
        parts.append(cusp)

    tooth = trimesh.util.concatenate(parts)
    # Rotate into the arch so the crown's buccal face points outward.
    rotation = trimesh.transformations.rotation_matrix(tangent, (0.0, 0.0, 1.0))
    tooth.apply_transform(rotation)
    tooth.apply_translation(centre)
    return tooth


def build_arch_mesh(arch: str = "maxillary") -> tuple[trimesh.Trimesh, list[dict]]:
    """Return the arch mesh and the per-tooth descriptors used to build it."""
    specs = _arch_specs(arch)
    parts: list[trimesh.Trimesh] = []
    teeth: list[dict] = []

    # Gingival ridge: overlapping ellipsoids along the arch give a continuous
    # base surface, which a real scan always has and which registration uses
    # as the dominant overlap region.
    ridge_steps = 60
    for step in range(ridge_steps + 1):
        x, y, _t = _arch_position(step, ridge_steps + 1)
        ridge = _ellipsoid((6.0, 6.0, 4.0), subdivisions=1)
        ridge.apply_translation((x, y, GINGIVAL_Z_MM + 2.0))
        parts.append(ridge)

    for spec in specs:
        x, y, tangent = _arch_position(spec.index, len(specs))
        mesiodistal, buccolingual, height = TOOTH_DIMENSIONS_MM[spec.tooth_class]
        centre = (x, y, GINGIVAL_Z_MM + 3.0)
        parts.append(_tooth_mesh(spec, centre, tangent))
        teeth.append(
            {
                "fdi": spec.fdi,
                "tooth_class": spec.tooth_class,
                "centre_mm": {"x": round(x, 3), "y": round(y, 3), "z": round(centre[2], 3)},
                "dimensions_mm": {
                    "mesiodistal": mesiodistal,
                    "buccolingual": buccolingual,
                    "crown_height": height,
                },
                "cusps": CUSP_COUNT[spec.tooth_class],
            }
        )

    mesh = trimesh.util.concatenate(parts)
    # A lower arch sits below the occlusal plane and is slightly narrower.
    if arch == "mandibular":
        mesh.apply_scale(0.94)
        mesh.apply_translation((0.0, 0.0, -14.0))
        for tooth in teeth:
            tooth["centre_mm"] = {
                key: round(value * 0.94 + (0.0 if key != "z" else -14.0), 3)
                for key, value in tooth["centre_mm"].items()
            }
    mesh.process(validate=True)
    return mesh, teeth


def write_fixture(mesh: trimesh.Trimesh, teeth: list[dict], *, arch: str, out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(out))
    raw = out.read_bytes()
    bounds = mesh.bounds
    manifest = {
        "generator": FIXTURE_GENERATOR,
        "fixture": FIXTURE_MESH_NAME,
        "arch": arch,
        "synthetic": True,
        "clinical_content": False,
        "units": "mm",
        "file": out.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "bounding_box_mm": {
            "min": [round(float(v), 3) for v in bounds[0]],
            "max": [round(float(v), 3) for v in bounds[1]],
            "extents": [round(float(v), 3) for v in mesh.extents],
        },
        "tooth_count": len(teeth),
        "teeth": teeth,
    }
    manifest_path = out.parent / "ios_fixture_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_ios_development_fixture",
        description="Write a deterministic synthetic IOS arch mesh (development fixture).",
    )
    parser.add_argument("--arch", choices=("maxillary", "mandibular"), default="maxillary")
    parser.add_argument("--out-dir", type=Path, default=None, help="directory for the fixture")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="explicit output .stl path (overrides --out-dir naming)",
    )
    args = parser.parse_args(argv)

    if args.out is not None:
        out = args.out
    elif args.out_dir is not None:
        out = args.out_dir / f"scan_{args.arch}.stl"
    else:
        parser.error("one of --out-dir or --out is required")

    mesh, teeth = build_arch_mesh(args.arch)
    manifest = write_fixture(mesh, teeth, arch=args.arch, out=out)

    print(f"wrote {manifest['file']} ({manifest['bytes']} bytes, {manifest['faces']} faces)")
    print(f"  arch            {manifest['arch']} ({manifest['tooth_count']} teeth)")
    print(f"  units           {manifest['units']}")
    print(f"  extents (mm)    {manifest['bounding_box_mm']['extents']}")
    print(f"  sha256          {manifest['sha256']}")
    print(f"  manifest        {manifest['manifest_path']}")
    print("\nnext: rasterise this mesh into a matching CBCT series")
    print(f"  python -m scripts.build_cbct_development_fixture --mesh {out} --out-dir <cbct_dir>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
