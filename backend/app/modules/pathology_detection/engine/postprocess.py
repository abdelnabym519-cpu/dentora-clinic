"""Post-processing: score/normalized-box → DENTEX-style findings.

The torchvision engine already runs NMS internally; this module adds
the pieces the DENTEX task requires on top of detector output:

1. confidence thresholding,
2. deterministic FDI (permanent 11–48) assignment.

FDI enumeration heuristic
-------------------------
Purely geometric, mirroring the widely used DENTEX quadrant +
position approach (quadrant segmentation + numbering from the X-ray
layout): panoramic X-rays are assumed upright with the patient's right
on the image left (standard dental convention).

* quadrant:  1 = top-left, 2 = top-right, 3 = bottom-right,
             4 = bottom-left  (patient right = image left).
* position:  enumerated 1..8 by distance from the image midline, so
             1 = central incisor and 8 = third molar within each
             quadrant; e.g. FDI 14 = quadrant 1, position 4.

The heuristic is deterministic and unit-testable; models that predict
enumeration directly can replace it later without touching the
service or API contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.pathology_detection.constants import DIAGNOSES

from .base import DetectedFinding


@dataclass(frozen=True)
class EnumeratedFinding:
    """Engine finding + FDI placement."""

    finding: DetectedFinding
    tooth_number: int | None
    quadrant: int | None
    position: int | None

    def as_dict(self) -> dict[str, float | str | int | None]:
        return {
            **self.finding.as_dict(),
            "tooth_number": self.tooth_number,
            "quadrant": self.quadrant,
            "position": self.position,
        }


def quadrant_for_center(cx: float, cy: float) -> int:
    """Map a normalized center to FDI quadrant (1..4)."""
    upper = cy < 0.5
    left = cx < 0.5
    if upper:
        return 1 if left else 2
    return 4 if left else 3


def _sort_key_for_quadrant(quadrant: int):
    """x-sort so FDI position 1 is nearest the midline."""
    # Q1 (top-left): patient right → enumeration runs 11→18 leftwards
    # from the midline, so order by descending x.
    # Q4 (bottom-left): same direction.
    if quadrant in (1, 4):
        return lambda f: -((f.finding.x1 + f.finding.x2) / 2)
    return lambda f: (f.finding.x1 + f.finding.x2) / 2


def enumerate_fdi(findings: list[DetectedFinding]) -> list[EnumeratedFinding]:
    """Assign tooth_number/quadrant/position to every finding.

    Detections on the same tooth keep their own diagnosis; positions
    are assigned per quadrant by x order (ties broken by y then x1).
    """
    enriched: list[EnumeratedFinding] = []
    for finding in findings:
        cx = (finding.x1 + finding.x2) / 2
        cy = (finding.y1 + finding.y2) / 2
        quadrant = quadrant_for_center(cx, cy)
        enriched.append(
            EnumeratedFinding(
                finding=finding,
                tooth_number=None,
                quadrant=quadrant,
                position=None,
            )
        )

    for quadrant in (1, 2, 3, 4):
        group = sorted(
            (f for f in enriched if f.quadrant == quadrant),
            key=_sort_key_for_quadrant(quadrant),
        )
        for index, item in enumerate(group, start=1):
            position = index if index <= 8 else None  # 9+ = artifact / outliers
            tooth = quadrant * 10 + position if position else None
            enriched = [
                EnumeratedFinding(
                    finding=item.finding,
                    tooth_number=tooth,
                    quadrant=item.quadrant,
                    position=position,
                )
                if entry is item
                else entry
                for entry in enriched
            ]

    # Deterministic output order: quadrant, position, diagnosis.
    return sorted(
        enriched,
        key=lambda f: (
            f.quadrant or 9,
            f.position or 9,
            DIAGNOSES.index(f.finding.diagnosis) if f.finding.diagnosis in DIAGNOSES else 9,
        ),
    )


def filter_by_confidence(
    findings: list[DetectedFinding],
    threshold: float,
) -> list[DetectedFinding]:
    """Return findings with ``confidence >= threshold``, sorted by score."""
    return sorted(
        (f for f in findings if f.confidence >= threshold),
        key=lambda f: f.confidence,
        reverse=True,
    )
