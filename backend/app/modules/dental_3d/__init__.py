"""Dental 3D module — foundation for 3D dental visualization (Phase 2).

Optional, removable module. Surfaces a 3D preview of the patient's
dentition in the patient Summary via the ``patient.summary.cards`` slot.
Phase 1 established the source-agnostic scene contract
(``DentalScene`` / ``Tooth3D`` / ``DentalMesh`` / ``SegmentationResult``)
with synthetic demo geometry. Phase 2 adds **real mesh ingestion**:
validated STL / OBJ files stored through the existing **media** module
and surfaced as scene-level mesh references (``DentalGeometrySource``
port — see ``sources.py`` / ADR 0020), rendered by the viewer with the
synthetic geometry kept as fallback.

Coupling with ``odontogram`` is read-only (``ToothRecord`` state drives
per-tooth presence / condition); coupling with ``media`` is document
storage + discovery — no second storage system, no FKs beyond
clinics/patients/users. The module uninstalls cleanly through its
isolated Alembic branch (``dental_3d``); uploaded scans remain ordinary
media documents owned by the media module.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import DentalNerveAnalysis, DentalScene, DentalSegmentationAnalysis
from .router import router


class Dental3DModule(BaseModule):
    manifest = {
        "name": "dental_3d",
        "version": "0.6.0",
        "summary": (
            "Dental 3D — 3D dentition preview on the patient summary with real "
            "mesh ingestion (STL/OBJ via the media module), a synthetic fallback "
            "and a non-clinical automatic tooth-segmentation foundation with "
            "dentist review, plus CBCT/DICOM ingestion and a replaceable, "
            "non-clinical real nerve-inference boundary with native-coordinate "
            "findings and explicit unavailable/failure states."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["patients", "odontogram", "media"],
        "installable": True,
        "auto_install": False,
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["*"],
            "hygienist": ["read", "write"],
            "assistant": ["read"],
            "receptionist": [],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        return [DentalScene, DentalSegmentationAnalysis, DentalNerveAnalysis]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "write"]

    def get_tools(self):
        # Smallest agent surface: one READ wrapper over the service.
        from .tools import get_tools

        return get_tools()
