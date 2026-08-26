"""Evidence-traceable AI treatment planning over unified case intelligence."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import AITreatmentPlanningRecord
from .router import router


class AITreatmentPlanningModule(BaseModule):
    manifest = {
        "name": "ai_treatment_planning",
        "version": "1.0.0",
        "summary": (
            "Advisory AI-generated treatment options grounded in redacted CaseSnapshot evidence "
            "and deterministic Risk Engine context, with append-only provenance and mandatory "
            "dentist review; never writes a canonical treatment plan automatically."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["case_intelligence", "risk_engine", "patients"],
        "installable": True,
        "auto_install": False,
        "removable": False,
        "role_permissions": {
            "admin": ["read", "generate"],
            "dentist": ["read", "generate", "review"],
            "hygienist": ["read"],
            "assistant": ["read"],
            "receptionist": [],
        },
    }

    def get_models(self) -> list:
        return [AITreatmentPlanningRecord]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "generate", "review"]


__all__ = ["AITreatmentPlanningModule"]
