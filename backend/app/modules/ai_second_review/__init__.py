"""Advisory AI Second Review over the reviewed clinical artifact chain."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import AISecondReviewRecord
from .router import router


class AISecondReviewModule(BaseModule):
    manifest = {
        "name": "ai_second_review",
        "version": "1.0.0",
        "summary": (
            "Evidence-traceable advisory second review of a dentist-accepted AI Treatment "
            "Planning option and deterministic Treatment Simulation, with fail-closed stale "
            "artifact validation and mandatory dentist review."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": [
            "case_intelligence",
            "risk_engine",
            "ai_treatment_planning",
            "treatment_simulation",
            "patients",
        ],
        "installable": True,
        "auto_install": False,
        "removable": False,
        "role_permissions": {
            "admin": ["read"],
            "dentist": ["read", "generate", "review"],
            "hygienist": ["read"],
            "assistant": ["read"],
            "receptionist": [],
        },
    }

    def get_models(self) -> list:
        return [AISecondReviewRecord]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "generate", "review"]


__all__ = ["AISecondReviewModule"]
