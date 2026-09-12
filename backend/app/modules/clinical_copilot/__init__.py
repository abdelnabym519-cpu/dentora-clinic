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
            # infrastructure.py reads the dentist-reviewed AI Second Review
            # records (read-only) so the Clinical Safety Governor sees that
            # stage instead of reporting it permanently "unavailable". The
            # edge is deliberate; declaring it keeps the module-isolation
            # guard honest. Placed in pipeline order: second review follows
            # the simulation it reviews.
            "ai_second_review",
            "copilot",
        ],
        "installable": True,
        "auto_install": True,
        "removable": False,
        "role_permissions": {
            "admin": ["read"],
            "dentist": ["read", "use"],
            "hygienist": ["read"],
            "assistant": [],
            "receptionist": [],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        return []

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "use"]


__all__ = ["ClinicalCopilotModule"]
