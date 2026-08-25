"""Dental 3D — patient-space clinical visualization and engineering decision support."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .implant_models import (
    DentalImplantPlan,
    DentalImplantPlanRevision,
    DentalProstheticTarget,
)
from .implant_router import router as implant_router
from .models import (
    DentalAlignmentResult,
    DentalNerveAnalysis,
    DentalScene,
    DentalSegmentationAnalysis,
)
from .router import router as core_router
from .storage_router import router as storage_router

router = APIRouter()
# Register bounded binary-ingestion endpoints before the existing router so
# public URLs and application services stay unchanged while oversized uploads
# can no longer be read unbounded into process memory.
router.include_router(storage_router)
router.include_router(core_router)
router.include_router(implant_router)


class Dental3DModule(BaseModule):
    manifest = {
        "name": "dental_3d",
        "version": "0.8.0",
        "summary": (
            "Dental 3D — 3D dentition preview on the patient summary with real "
            "mesh ingestion (STL/PLY/OBJ via the media module), patient-space ThreeUI "
            "and a non-clinical automatic tooth-segmentation foundation with "
            "dentist review, plus CBCT/DICOM ingestion and a replaceable, "
            "non-clinical real nerve-inference boundary with native-coordinate "
            "findings and explicit unavailable/failure states, plus patient-specific "
            "rigid IOS-to-CBCT registration with explicit geometry provenance and review, "
            "plus WebGL2/TresJS and Cornerstone CBCT/MPR clinical presentation, and "
            "deterministic prosthetic-guided implant planning with explicit patient-space "
            "provenance, immutable revisions, fail-closed missing-data checks and dentist review."
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
        return [
            DentalScene,
            DentalSegmentationAnalysis,
            DentalNerveAnalysis,
            DentalAlignmentResult,
            DentalProstheticTarget,
            DentalImplantPlan,
            DentalImplantPlanRevision,
        ]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "write"]

    def get_tools(self):
        from .tools import get_tools

        return get_tools()


__all__ = ["Dental3DModule"]
