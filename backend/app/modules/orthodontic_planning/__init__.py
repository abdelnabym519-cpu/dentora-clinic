"""Orthodontic planning module — ML/RL decision support (deterministic gate).

Optional, removable module. Provides orthodontic **planning proposals**
as clinical decision support only:

* The clinician records a case assessment (measurements + objectives);
  the module snapshots the patient's odontogram read-only and computes
  a deterministic data-sufficiency report.
* A pluggable ``PlanningProvider`` (default: the deterministic
  ``heuristic_v1`` reference planner) proposes staged tooth movements.
  There are **no shipped model weights and no trained policy** — the
  provider registry is the extension point where an offline-trained
  ML/RL policy plugs in once curated outcome data exists.
* Every suggestion is re-validated by a deterministic constraint layer
  (per-stage/per-tooth bounds, presence rules, overjet/space
  envelopes). Hard violations are refused, audited, and never stored.
* Proposals are draft documents until a clinician explicitly approves
  or rejects them (audited events). The module never writes to other
  modules and can never execute a plan autonomously — clinical
  decision-making stays 100% with the clinician.

Coupling with ``patients``/``odontogram`` is read-only queries; the
dentition snapshot is copied JSONB (no cross-module FK), so uninstall
is clean via the isolated Alembic branch ``orthodontic_planning``.
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import OrthoAssessment, OrthoPlanProposal
from .router import router


class OrthodonticPlanningModule(BaseModule):
    manifest = {
        "name": "orthodontic_planning",
        "version": "0.1.0",
        "summary": (
            "Orthodontic planning decision support: deterministic staged "
            "movement proposals with a hard safety gate, uncertainty "
            "reporting, and mandatory clinician review."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["patients", "odontogram"],
        "installable": True,
        "auto_install": False,
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["read", "write"],
            "hygienist": ["read"],
            "assistant": ["read"],
            "receptionist": [],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        return [OrthoAssessment, OrthoPlanProposal]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "write"]

    def get_tools(self) -> list:
        # Deliberately none: planning is clinician-facing decision
        # support, not an agent action surface.
        return []
