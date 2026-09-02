"""Pathology detection constants — DENTEX-compatible label space.

The four diagnosis labels follow the DENTEX 2023 challenge taxonomy
(Grand Challenge / MICCAI 2023, CC BY 4.0 paper) so models trained on
DENTEX-style data can be dropped in without a schema change:

* ``caries``            — enamel/dentine caries
* ``deep_caries``       — caries approaching or involving the pulp
* ``periapical_lesion`` — periapical radiolucency
* ``impacted_tooth``    — impacted / partially erupted tooth

FDI numbering (11–48) and quadrant semantics (1 = upper right,
2 = upper left, 3 = lower left, 4 = lower right) match the FDI system
used by the odontogram module and the DENTEX annotation protocol.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Final

DIAGNOSIS_CARIES: Final[str] = "caries"
DIAGNOSIS_DEEP_CARIES: Final[str] = "deep_caries"
DIAGNOSIS_PERIAPICAL_LESION: Final[str] = "periapical_lesion"
DIAGNOSIS_IMPACTED_TOOTH: Final[str] = "impacted_tooth"

DIAGNOSES: Final[tuple[str, ...]] = (
    DIAGNOSIS_CARIES,
    DIAGNOSIS_DEEP_CARIES,
    DIAGNOSIS_PERIAPICAL_LESION,
    DIAGNOSIS_IMPACTED_TOOTH,
)

# Engine states stored on PathologyAnalysis.status.
STATUS_RUNNING: Final[str] = "running"
STATUS_COMPLETED: Final[str] = "completed"
STATUS_FAILED: Final[str] = "failed"
ANALYSIS_STATUSES: Final[tuple[str, ...]] = (
    STATUS_RUNNING,
    STATUS_COMPLETED,
    STATUS_FAILED,
)

# Media kinds eligible for panoramic/periapical analysis.
ANALYZABLE_MEDIA_KINDS: Final[tuple[str, ...]] = ("xray", "photo")

# Model classifier index → diagnosis label. Index 0 is the background
# class used by torchvision Faster R-CNN heads.
CLASS_INDEX_TO_DIAGNOSIS: Final[dict[int, str]] = {
    1: DIAGNOSIS_CARIES,
    2: DIAGNOSIS_DEEP_CARIES,
    3: DIAGNOSIS_PERIAPICAL_LESION,
    4: DIAGNOSIS_IMPACTED_TOOTH,
}
DIAGNOSIS_TO_CLASS_INDEX: Final[dict[str, int]] = {
    value: key for key, value in CLASS_INDEX_TO_DIAGNOSIS.items()
}

NUM_DETECTION_CLASSES: Final[int] = len(DIAGNOSES) + 1  # + background


def summary_counts(findings: Sequence[dict]) -> dict[str, int]:
    """Per-diagnosis counts for the analysis summary blob."""
    counts: Counter[str] = Counter(f.get("diagnosis", "") for f in findings)
    return {name: counts.get(name, 0) for name in DIAGNOSES}


def quadrant_of_fdi(tooth_number: int) -> int:
    """FDI 11–48 → quadrant (1..4). Raises ValueError outside 11–48."""
    if tooth_number < 11 or tooth_number > 48:
        raise ValueError(f"Invalid FDI tooth number: {tooth_number}")
    return tooth_number // 10
