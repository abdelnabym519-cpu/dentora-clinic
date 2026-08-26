"""Automatic tooth segmentation — the application/domain boundary port.

ADR 0019 / ADR 0021: segmentation is an external capability (today a
deterministic rule-based analysis, tomorrow a real ML model) and must
sit behind an **interface defined at the inner boundary**. The
application layer (:class:`DentalSegmentationService`) depends on the
:class:`ToothSegmentationProvider` protocol only, never on a concrete
implementation:

    Application use case (service.py)
            ↓ depends on
    ToothSegmentationProvider          ← this file (inner layer)
            ↑ implemented by
    infrastructure.py adapter          (deterministic today, ML later)

Safety invariants encoded in the contracts themselves:

- Every result is **non-clinical** (``is_clinical=False`` is not a
  flag a provider may set — the schema fixes it) and **requires dentist
  review** (``requires_review=True``, likewise fixed). Segmentation is
  decision *support*: input → analysis → evidence/confidence → dentist
  review → dentist decision. No result is ever a diagnosis.
- Determinism for the Phase 3 foundation: a provider receiving the
  same request must return the same analysis. The request carries the
  server clock (``performed_at``) so providers never read the
  environment, and the Phase 3 adapter contains no randomness.

This file must stay framework-free: no FastAPI, no SQLAlchemy, no ML
frameworks, no HTTP — only the neutral contracts from ``.schemas`` and
pydantic. Adapters live in ``.infrastructure``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .schemas import DentalMesh, Tooth3D, _is_valid_fdi

#: What kind of input a provider understands. Phase 3 providers analyse
#: the *scene* (tooth universe + mesh references); future kinds (raw
#: scan vertices, CBCT volumes) extend this literal, never the port.
SegmentationInputKind = Literal["scene"]

#: Per-tooth outcome of a segmentation analysis.
SegmentedToothStatus = Literal["segmented", "uncertain", "missing"]

#: Review outcome recorded by a dentist (never by a provider).
SegmentationReviewDecision = Literal["accepted", "rejected"]

#: Confidence bands surfaced to the UI (thresholds documented in ADR 0021).
CONFIDENCE_HIGH = 0.8
CONFIDENCE_MEDIUM = 0.6


class SegmentationEvidence(BaseModel):
    """How the provider derived one tooth's proposal.

    Evidence is explanatory metadata for the dentist — never proof of
    clinical correctness. ``basis`` says what the rule (or future
    model) looked at; ``backing_documents`` lists the media documents
    (scan meshes) that informed the analysis, if any.
    """

    basis: Literal["odontogram_record", "arch_position", "mesh_backed"]
    arch_region: str = Field(max_length=20)
    backing_documents: list[UUID] = Field(default_factory=list, max_length=16)
    note: str | None = Field(default=None, max_length=255)


class SegmentedTooth(BaseModel):
    """One tooth-level segmentation proposal in FDI notation.

    ``confidence`` is the provider's confidence in the *status*
    assignment (0.0–1.0), not a clinical probability. FDI validity is
    enforced here so a misbehaving adapter can never smuggle an
    invalid tooth number into persistence or the API.
    """

    tooth_number: int
    status: SegmentedToothStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: SegmentationEvidence = Field(default_factory=SegmentationEvidence)

    @field_validator("tooth_number")
    @classmethod
    def _valid_fdi(cls, value: int) -> int:
        if not _is_valid_fdi(value):
            raise ValueError(f"{value} is not a valid FDI tooth number")
        return value


class SegmentationRequest(BaseModel):
    """Everything a provider may look at — one patient's scene.

    ``teeth`` is the odontogram-driven tooth universe (presence and
    conditions from ``ToothRecord`` — the existing source of truth);
    ``meshes`` are the real geometry references the scene carries.
    Both are already clinic-scoped by the caller; providers never
    query anything themselves.
    """

    clinic_id: UUID
    patient_id: UUID
    teeth: list[Tooth3D] = Field(default_factory=list, max_length=52)
    meshes: list[DentalMesh] = Field(default_factory=list, max_length=16)
    performed_at: datetime


class SegmentationAnalysisResult(BaseModel):
    """Provider output — the analysis awaiting dentist review.

    ``provider``/``method`` identify who produced the analysis and how
    (logged, shown in the UI, never a clinical claim). The safety
    fields are **fixed by the schema**: no provider can present itself
    as clinical or as not requiring review.
    """

    provider: str = Field(min_length=1, max_length=50)
    method: str = Field(min_length=1, max_length=100)
    is_clinical: Literal[False] = False
    requires_review: Literal[True] = True
    teeth: list[SegmentedTooth] = Field(default_factory=list, max_length=52)
    performed_at: datetime

    @property
    def segmented(self) -> list[SegmentedTooth]:
        return [t for t in self.teeth if t.status == "segmented"]

    @property
    def uncertain(self) -> list[SegmentedTooth]:
        return [t for t in self.teeth if t.status == "uncertain"]

    @property
    def missing(self) -> list[SegmentedTooth]:
        return [t for t in self.teeth if t.status == "missing"]


@runtime_checkable
class ToothSegmentationProvider(Protocol):
    """Port: automatic tooth segmentation, regardless of engine.

    Implementations are constructed by the composition root in
    ``infrastructure.py`` and must be **deterministic** for identical
    requests. ``name`` is a stable identity for logging and future
    per-provider configuration; ``input_kind`` declares what the
    provider analyses (Phase 3: the scene). Replacing the Phase 3
    rule-based adapter with a real ML model means implementing this
    protocol — the application/domain contracts do not change.
    """

    name: str
    input_kind: SegmentationInputKind

    async def segment(self, request: SegmentationRequest) -> SegmentationAnalysisResult:
        """Analyse the request's scene and return per-tooth proposals."""
        ...


class SegmentationAnalysisResponse(BaseModel):
    """API payload for a persisted analysis: proposals + review state.

    ``counts`` are server-derived from ``teeth``; ``review`` carries
    the dentist-review workflow state (who decided, when, and the
    optional note). ``disclaimer`` is fixed copy — every payload tells
    the truth about what this is (non-clinical decision support).
    """

    id: UUID
    patient_id: UUID
    provider: str
    method: str
    is_clinical: Literal[False] = False
    requires_review: Literal[True] = True
    teeth: list[SegmentedTooth] = Field(default_factory=list, max_length=52)
    performed_at: datetime
    created_at: datetime | None = None
    review_status: Literal["pending", "accepted", "rejected"] = "pending"
    reviewed_at: datetime | None = None
    review_note: str | None = None
    segmented_count: int = Field(default=0, ge=0)
    uncertain_count: int = Field(default=0, ge=0)
    missing_count: int = Field(default=0, ge=0)
    disclaimer: str = (
        "Automatic tooth segmentation is non-clinical decision support. "
        "A dentist must review and decide; results never alter odontogram records."
    )

    def counts_from_teeth(self) -> None:
        """Derive the status counts from ``teeth`` (call after assembly)."""
        self.segmented_count = sum(1 for t in self.teeth if t.status == "segmented")
        self.uncertain_count = sum(1 for t in self.teeth if t.status == "uncertain")
        self.missing_count = sum(1 for t in self.teeth if t.status == "missing")


class SegmentationReviewUpdate(BaseModel):
    """Dentist review decision for one analysis.

    Only ``accepted`` / ``rejected`` are valid decisions — there is no
    client-supplied analysis payload anywhere in the workflow, and a
    review never marks anything clinically completed: it records the
    dentist's decision on decision-support output.
    """

    decision: SegmentationReviewDecision
    note: str | None = Field(default=None, max_length=1000)
