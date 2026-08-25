"""Deterministic unified clinical case snapshot and evidence layer."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import CaseSnapshotRecord
from .router import router


class CaseIntelligenceModule(BaseModule):
    manifest = {
        "name": "case_intelligence",
        "version": "1.0.0",
        "summary": (
            "Deterministic, versioned unified clinical case snapshots with explicit "
            "availability, provenance, evidence references and append-only persistence; "
            "informational infrastructure only, with no diagnosis, risk scoring or AI narrative."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": [
            "patients",
            "patients_clinical",
            "odontogram",
            "periodontogram",
            "patient_timeline",
            "media",
            "dental_3d",
        ],
        "installable": True,
        "auto_install": False,
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["read"],
            "hygienist": ["read"],
            "assistant": ["read"],
            "receptionist": [],
        },
    }

    def get_models(self) -> list:
        return [CaseSnapshotRecord]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read"]


__all__ = ["CaseIntelligenceModule"]
