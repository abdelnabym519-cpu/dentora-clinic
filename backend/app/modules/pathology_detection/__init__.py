"""Pathology detection module — AI-assisted panoramic X-ray analysis.

Optional, removable module. Registering a slot inside the **Diagnosis**
mode of the patient clinical tab (``patient.diagnosis.subtabs``),
alongside odontogram and periodontogram.

Feature: given an existing media X-ray/photo document, runs a
DENTEX-style detector (four diagnoses: caries, deep caries, periapical
lesion, impacted tooth) and stores normalized bounding boxes with FDI
tooth enumeration (quadrant + position) as an immutable analysis
snapshot with per-finding rows.

Coupling with ``media`` is read-only: ``document_id`` is stored as a
plain UUID (no FK) so the module can be uninstalled cleanly via its
isolated Alembic branch.

**No weights are shipped.** The engine loads a checkpoint from
``PATHOLOGY_MODEL_PATH`` — see ``docs/technical/pathology_detection/provenance.md`` for
provenance requirements (the public DENTEX dataset is CC BY-NC-SA 4.0
and must not ship inside this BSL 1.1 product).
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import PathologyAnalysis, PathologyFinding
from .router import router


class PathologyDetectionModule(BaseModule):
    manifest = {
        "name": "pathology_detection",
        "version": "0.1.0",
        "summary": (
            "AI pathology detection on panoramic X-rays — caries, deep "
            "caries, periapical lesions, impacted teeth with FDI enumeration."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["patients", "media"],
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
        return [PathologyAnalysis, PathologyFinding]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "write"]
