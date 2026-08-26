"""Clinical Copilot — evidence-grounded, dentist-controlled advisory surface."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .router import router


class ClinicalCopilotModule(BaseModule):
    manifest = {
        "name": "clinical_copilot",
        "version": "1.0.0",
        "summary": (
            "Read-only clinical advisory over Case Intelligence, Risk Engine, AI Treatment "
            "Planning, Treatment Simulation, and AI Second Review provenance."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": [
            "case_intelligence",
            "risk_engine",
            "ai_treatment_planning",
            "treatment_simulation",
            "copilot",
        ],
        "installable": True,
        "auto_install": False,
        "removable": False,
        "role_permissions": {
            "admin": ["read"],
            "dentist": ["read", "use"],
            "hygienist": ["read"],
            "assistant": [],
            "receptionist": [],
        },
    }

    def get_models(self) -> list:
        return []

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "use"]


__all__ = ["ClinicalCopilotModule"]
