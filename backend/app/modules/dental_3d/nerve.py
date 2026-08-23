"""Mandibular nerve detection — the application/domain boundary port.

ADR 0019 / ADR 0022: nerve detection is an external capability (today a
deterministic canonical-anatomy model, tomorrow a real CBCT/ML detector)
and must sit behind an **interface defined at the inner boundary**. The
application layer (:class:`DentalNerveService`) depends on the
:class:`NerveDetectionProvider` protocol only, never on a concrete
implementation:

    Application use case (service.py)
            ↓ depends on
    NerveDetectionProvider            ← this file (inner layer)
            ↑ implemented by
    infrastructure.py adapter         (canonical model today, ML later)

Safety invariants encoded in the contracts themselves:

- Every result is **non-clinical** (``is_clinical=False`` is fixed by
  the schema — no provider can claim otherwise) and **requires dentist
  review** (``requires_review=True``, likewise fixed). The workflow is
  input → nerve analysis → evidence/confidence → dentist review →
  dentist decision; the dentist remains the final decision-maker.
- Proximities are **planning-support measurements** ("AI-estimated
  proximity"), never clinical safety verdicts: no tooth is ever
  labelled clinically unsafe, and no implant/surgical plan is approved
  or produced.
- Determinism for the Phase 4 foundation: identical requests yield
  identical results; the request carries the server clock so providers
  never read the environment, and the Phase 4 adapter contains no
  randomness.

Coordinate frame: pathway points are expressed in the **same canonical
arch frame as the synthetic dentition** (``frontend/lib/dentalArch.ts``
— half-width 2.2, depth 1.5, gap 0.5, lower arch at ``y = -0.25``).
The adapter documents the millimetre scale factor. Client viewers can
therefore plot pathways without re-projection while the synthetic arch
renders; overlaying a canonical pathway on patient scan geometry would
pretend an alignment nobody has, so the viewer does not do it.

This file must stay framework-free: no FastAPI, no SQLAlchemy, no ML
frameworks, no HTTP — only neutral contracts (pydantic, like the
module's other schemas). Adapters live in ``.infrastructure``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .schemas import DentalMesh, Tooth3D, _is_valid_fdi

#: What kind of input a provider understands. Phase 4 providers analyse
#: the *scene* (tooth universe + mesh references); a future CBCT-based
#: kind extends this literal, never the port.
NerveDetectionInputKind = Literal["scene"]

#: Anatomical region label for a pathway. Phase 4 models the mandibular
#: canal (inferior alveolar nerve); future regions extend the literal.
NerveRegion = Literal["mandibular_canal"]

#: Which side of the mandible a pathway belongs to.
NerveSide = Literal["left", "right"]

#: Pathway-level detection status.
#: ``detected`` — the model produced a pathway (still non-clinical);
#: ``uncertain`` — generic model geometry with no patient geometry
#: backing it; every pathway always requires dentist verification.
NervePathwayStatus = Literal["detected", "uncertain"]

#: Where the pathway geometry came from. Phase 4 emits a canonical
#: demo anatomical model — never patient-measured data.
NervePathwaySource = Literal["canonical_demo_model"]

#: Per-tooth proximity warning band (planning support only).
#: ``near``   — closer than PROXIMITY_NEAR_MM to the modelled pathway
#: ``watch``  — closer than PROXIMITY_WATCH_MM
#: ``none``   — listed for completeness, outside both bands
#: These bands never mark a tooth clinically unsafe.
NerveProximityWarning = Literal["near", "watch", "none"]

#: Review outcome recorded by a dentist (never by a provider).
NerveReviewDecision = Literal["accepted", "rejected"]

#: Confidence bands surfaced to the UI (same thresholds as Phase 3,
#: documented in ADR 0021 / ADR 0022).
CONFIDENCE_HIGH = 0.8
CONFIDENCE_MEDIUM = 0.6

#: Proximity thresholds in millimetres (canonical-frame model units ×
#: MM_PER_UNIT). Planning-support bands — NOT clinical safety limits.
PROXIMITY_NEAR_MM = 2.0
PROXIMITY_WATCH_MM = 5.0
#: Teeth farther than this from the modelled pathway are omitted from
#: the proximity list (the canal model ends at the premolar region).
PROXIMITY_MAX_MM = 15.0


class NerveEvidence(BaseModel):
    """How the provider derived one pathway.

    Evidence is explanatory metadata for the dentist — never proof of
    clinical correctness. ``basis`` says what the model looked at;
    ``backing_documents`` lists the media documents (scan meshes) that
    informed the analysis, if any.
    """

    basis: Literal["anatomical_model", "mesh_backed"]
    note: str | None = Field(default=None, max_length=255)
    backing_documents: list[UUID] = Field(default_factory=list, max_length=16)


class NervePathPoint(BaseModel):
    """One 3D point of a pathway polyline, in the canonical arch frame."""

    x: float
    y: float
    z: float


class NervePathway(BaseModel):
    """One mandibular nerve pathway — structured geometry, not a UI line.

    A pathway is a polyline of at least two points carrying its own
    anatomical identity (side + region), provenance (``source`` —
    always the canonical demo model in Phase 4), status, confidence and
    evidence. Patient-specific clinical anatomy is never hardcoded as
    real medical data: ``source`` states what the geometry is.
    """

    side: NerveSide
    region: NerveRegion = "mandibular_canal"
    source: NervePathwaySource = "canonical_demo_model"
    status: NervePathwayStatus
    confidence: float = Field(ge=0.0, le=1.0)
    points: list[NervePathPoint] = Field(min_length=2, max_length=64)
    evidence: NerveEvidence = Field(default_factory=NerveEvidence)


class ToothNerveProximity(BaseModel):
    """AI-estimated distance from one tooth to a pathway (support only).

    ``distance_mm`` is a model-space measurement against **canonical
    demo anatomy** — an estimate for the dentist to verify, never a
    clinical clearance or safety verdict. ``warning`` bands the value
    for display; ``closest_point_index`` references the pathway's
    ``points`` array for viewer highlighting.
    """

    tooth_number: int
    side: NerveSide
    distance_mm: float = Field(ge=0.0, le=100.0)
    closest_point_index: int = Field(ge=0)
    warning: NerveProximityWarning
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("tooth_number")
    @classmethod
    def _valid_fdi(cls, value: int) -> int:
        if not _is_valid_fdi(value):
            raise ValueError(f"{value} is not a valid FDI tooth number")
        return value


class NerveDetectionRequest(BaseModel):
    """Everything a provider may look at — one patient's scene.

    ``teeth`` is the odontogram-driven tooth universe (presence and
    conditions from ``ToothRecord`` — the existing source of truth);
    ``meshes`` are the real geometry references the scene carries. Both
    are already clinic-scoped by the caller; providers never query
    anything themselves.
    """

    clinic_id: UUID
    patient_id: UUID
    teeth: list[Tooth3D] = Field(default_factory=list, max_length=52)
    meshes: list[DentalMesh] = Field(default_factory=list, max_length=16)
    performed_at: datetime


class NerveDetectionResult(BaseModel):
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
    pathways: list[NervePathway] = Field(default_factory=list, max_length=4)
    proximities: list[ToothNerveProximity] = Field(default_factory=list, max_length=52)
    performed_at: datetime

    @property
    def detected(self) -> list[NervePathway]:
        return [p for p in self.pathways if p.status == "detected"]

    @property
    def uncertain(self) -> list[NervePathway]:
        return [p for p in self.pathways if p.status == "uncertain"]

    @property
    def near_teeth(self) -> list[ToothNerveProximity]:
        return [p for p in self.proximities if p.warning == "near"]


@runtime_checkable
class NerveDetectionProvider(Protocol):
    """Port: mandibular nerve detection, regardless of engine.

    Implementations are constructed by the composition root in
    ``infrastructure.py`` and must be **deterministic** for identical
    requests. ``name`` is a stable identity for logging and future
    per-provider configuration; ``input_kind`` declares what the
    provider analyses (Phase 4: the scene). Replacing the Phase 4
    canonical-model adapter with a real CBCT/ML detector means
    implementing this protocol — the application/domain contracts do
    not change.
    """

    name: str
    input_kind: NerveDetectionInputKind

    async def detect(self, request: NerveDetectionRequest) -> NerveDetectionResult:
        """Analyse the request's scene and return pathway + proximity proposals."""
        ...


class NerveDetectionAnalysisResponse(BaseModel):
    """API payload for a persisted analysis: pathways + review state.

    ``counts`` are server-derived; ``review`` carries the
    dentist-review workflow state. ``disclaimer`` is fixed copy — every
    payload tells the truth about what this is (AI-assisted / simulated
    nerve detection requiring dentist verification).
    """

    id: UUID
    patient_id: UUID
    provider: str
    method: str
    is_clinical: Literal[False] = False
    requires_review: Literal[True] = True
    pathways: list[NervePathway] = Field(default_factory=list, max_length=4)
    proximities: list[ToothNerveProximity] = Field(default_factory=list, max_length=52)
    performed_at: datetime
    created_at: datetime | None = None
    review_status: Literal["pending", "accepted", "rejected"] = "pending"
    reviewed_at: datetime | None = None
    review_note: str | None = None
    pathway_count: int = Field(default=0, ge=0)
    near_count: int = Field(default=0, ge=0)
    watch_count: int = Field(default=0, ge=0)
    disclaimer: str = (
        "AI-assisted / simulated nerve detection on a canonical anatomical model. "
        "It is non-clinical decision support: a dentist must verify the pathway "
        "and proximities before any planning decision."
    )

    def counts_from_result(self) -> None:
        """Derive the display counts from ``pathways``/``proximities``."""
        self.pathway_count = len(self.pathways)
        self.near_count = sum(1 for p in self.proximities if p.warning == "near")
        self.watch_count = sum(1 for p in self.proximities if p.warning == "watch")


class NerveReviewUpdate(BaseModel):
    """Dentist review decision for one analysis.

    Only ``accepted`` / ``rejected`` are valid decisions — there is no
    client-supplied detection payload anywhere in the workflow, and a
    review never approves an implant or surgical plan: it records the
    dentist's acknowledgement of decision-support output.
    """

    decision: NerveReviewDecision
    note: str | None = Field(default=None, max_length=1000)
