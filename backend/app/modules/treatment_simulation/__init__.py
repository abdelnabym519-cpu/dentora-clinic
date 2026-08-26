"""Reviewed-plan Treatment Simulation over the Dental Digital Twin."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import TreatmentSimulationRecord
from .router import router


class TreatmentSimulationModule(BaseModule):
    manifest = {
        "name": "treatment_simulation",
        "version": "1.0.0",
        "summary": (
            "Deterministic, non-predictive visualization of a dentist-accepted AI Treatment "
            "Planning option over the existing Dental Digital Twin, patient-space evidence, "
            "and Risk Map with append-only provenance and stale-input protection."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": [
            "dental_3d",
            "case_intelligence",
            "risk_engine",
            "ai_treatment_planning",
            "patients",
        ],
        "installable": True,
        "auto_install": False,
        "removable": False,
        "role_permissions": {
            "admin": ["read"],
            "dentist": ["read", "generate"],
            "hygienist": ["read"],
            "assistant": ["read"],
            "receptionist": [],
        },
    }

    def get_models(self) -> list:
        return [TreatmentSimulationRecord]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "generate"]


__all__ = ["TreatmentSimulationModule"]
