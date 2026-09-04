"""Pathology inference engine contract + factory.

The engine layer is deliberately framework-decoupled:

* ``PathologyEngine`` is a plain Protocol. The service layer never
  imports torch/torchvision — it calls ``analyze()`` on whatever the
  factory returns.
* ``TorchvisionFasterRcnnEngine`` (in :mod:`.torchvision_engine`)
  imports torch *lazily inside the constructor*, so the module can be
  discovered and the backend can boot without the optional
  ``ai-pathology`` extra installed.
* If no model file is provisioned the factory raises
  :class:`EngineUnavailableError`; the router converts it to HTTP 503.

Model provenance policy: Dentora ships **no pretrained weights**.
Operators provision a checkpoint produced from data they are licensed
to use (see ``docs/technical/pathology_detection/provenance.md`` — the public DENTEX
dataset is CC BY-NC-SA 4.0 and must NOT be shipped inside this
commercial product).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from PIL import Image

from app.config import settings

__all__ = [
    "DetectedFinding",
    "EngineUnavailableError",
    "InferenceResult",
    "PathologyEngine",
    "get_engine",
    "engine_capabilities",
]


class EngineUnavailableError(RuntimeError):
    """Raised when the configured engine/model cannot be loaded."""


@dataclass(frozen=True)
class DetectedFinding:
    """One model detection, coordinates normalized to [0, 1]."""

    diagnosis: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    def as_dict(self) -> dict[str, float | str]:
        return {
            "diagnosis": self.diagnosis,
            "confidence": round(self.confidence, 4),
            "x1": round(self.x1, 6),
            "y1": round(self.y1, 6),
            "x2": round(self.x2, 6),
            "y2": round(self.y2, 6),
        }


@dataclass(frozen=True)
class InferenceResult:
    """Raw engine output before FDI enumeration."""

    findings: list[DetectedFinding] = field(default_factory=list)
    engine: str = "unknown"
    model_version: str = "unknown"
    inference_ms: int = 0


@runtime_checkable
class PathologyEngine(Protocol):
    """A model runner. Implementations must be safe to construct only
    when the model artifact is provisioned."""

    name: str
    model_version: str

    def analyze(self, image: Image.Image) -> InferenceResult: ...


def get_engine() -> PathologyEngine:
    """Build the engine selected by ``PATHOLOGY_ENGINE``.

    Raises :class:`EngineUnavailableError` when the model file is not
    provisioned — the router turns that into a 503 so clinics see a
    clear, actionable message instead of a crash.
    """
    engine_kind = settings.PATHOLOGY_ENGINE.strip().lower()
    if engine_kind == "torchvision_fasterrcnn":
        # Local import: torchvision_engine imports DetectedFinding from
        # this module (the engine class lazily imports torch itself).
        from .torchvision_engine import TorchvisionFasterRcnnEngine

        model_path = settings.PATHOLOGY_MODEL_PATH.strip()
        if not model_path:
            raise EngineUnavailableError(
                "Pathology model not provisioned: set PATHOLOGY_MODEL_PATH "
                "to a trained .pt checkpoint (see docs/technical/pathology_detection/provenance.md)."
            )
        return TorchvisionFasterRcnnEngine(
            model_path=model_path,
            device=settings.PATHOLOGY_DEVICE,
            confidence_threshold=settings.PATHOLOGY_CONFIDENCE_THRESHOLD,
            nms_iou_threshold=settings.PATHOLOGY_NMS_IOU_THRESHOLD,
            max_side=settings.PATHOLOGY_MAX_SIDE,
        )
    raise EngineUnavailableError(
        f"Unknown PATHOLOGY_ENGINE '{engine_kind}' — supported: torchvision_fasterrcnn."
    )


def engine_capabilities() -> dict[str, str | bool]:
    """Advertisement payload for ``GET /capabilities``.

    Lets the frontend distinguish "not installed" from "analysis failed"
    without probing private paths.
    """
    configured = bool(settings.PATHOLOGY_MODEL_PATH.strip())
    try:
        engine = get_engine()
        return {
            "available": True,
            "engine": engine.name,
            "model_version": engine.model_version,
            "configured": configured,
        }
    except EngineUnavailableError as exc:
        return {
            "available": False,
            "engine": settings.PATHOLOGY_ENGINE,
            "model_version": "",
            "configured": configured,
            "reason": str(exc),
        }
