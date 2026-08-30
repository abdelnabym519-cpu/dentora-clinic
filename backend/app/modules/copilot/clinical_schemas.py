"""Structured contracts for the patient-scoped clinical AI features.

Every clinical-AI response is validated against one of these Pydantic
models. A malformed / unparseable provider response raises
:class:`ClinicalAIValidationError` and is surfaced to the caller as an
explicit AI-unavailable/validation error — it never degrades into a
fabricated clinical result (see :mod:`app.modules.copilot.clinical`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Every clinical-AI artefact carries this fixed disclaimer so the UI
# cannot render it as an unquestionable clinical truth.
AI_DISCLAIMER = (
    "AI-assisted clinical output for dentist review only. It is not a "
    "medical diagnosis, does not replace professional judgement, and may be "
    "incomplete or wrong. The treating dentist remains responsible."
)


class ClinicalAIBase(BaseModel):
    """Common envelope shared by every structured clinical AI result."""

    generated_by: Literal["ai"] = "ai"
    model: str
    disclaimer: str = AI_DISCLAIMER
    # True only when the structured output came from a real provider call.
    # Never serialized as ``True`` without an actual completion.
    insufficient_information: bool = False


class CaseSummary(ClinicalAIBase):
    """AI case summary (feature B)."""

    summary: str = Field(default="", description="One-paragraph clinical summary.")
    current_condition: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    active_treatments: list[str] = Field(default_factory=list)
    important_history: list[str] = Field(default_factory=list)
    outstanding_items: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    # Provenance: which records fed the model.
    sources: list[str] = Field(default_factory=list)


class ClinicalReport(ClinicalAIBase):
    """AI clinical report (feature C)."""

    title: str = ""
    overview: str = ""
    sections: list[ReportSection] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ReportSection(BaseModel):
    heading: str
    body: str
    findings: list[str] = Field(default_factory=list)


class SecondReview(ClinicalAIBase):
    """Independent AI second review (feature D)."""

    overall_impression: str = ""
    key_findings: list[str] = Field(default_factory=list)
    possible_concerns: list[str] = Field(default_factory=list)
    inconsistencies: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    questions_to_consider: list[str] = Field(default_factory=list)
    # Explicit, non-fabricated uncertainty statement. Never a diagnosis.
    confidence: Literal["low", "medium", "high"] = "low"
    confidence_rationale: str = ""
    sources: list[str] = Field(default_factory=list)


class TreatmentOption(BaseModel):
    title: str
    rationale: str
    priority: int = Field(default=0, ge=0)
    estimated_steps: list[str] = Field(default_factory=list)
    depends_on_missing_info: list[str] = Field(default_factory=list)
    considerations: list[str] = Field(default_factory=list)


class TreatmentPlanAI(ClinicalAIBase):
    """AI treatment-planning suggestions (feature E).

    The AI only *suggests* options; it never creates/updates a plan.
    """

    options: list[TreatmentOption] = Field(default_factory=list)
    suggested_order: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class DeterministicSignal(BaseModel):
    """A rule-derived clinical signal (NOT AI)."""

    kind: str
    severity: Literal["info", "attention", "warning"]
    message: str
    source: str


class CaseIntelligence(ClinicalAIBase):
    """Hybrid case intelligence (feature F).

    ``signals`` are deterministic and authoritative; ``insights`` are
    LLM-derived and clearly labelled as such.
    """

    signals: list[DeterministicSignal] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    risk_attention_points: list[str] = Field(default_factory=list)
    missing_follow_up: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


ClinicalReport.model_rebuild()
