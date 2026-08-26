"""Clinician-controlled, read-only patient presentation mode."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .router import router


class PatientPresentationModeModule(BaseModule):
    manifest = {
        "name": "patient_presentation_mode",
        "version": "1.0.0",
        "summary": (
            "Clinician-controlled patient presentation of accepted, current, "
            "evidence-traceable case summaries without clinical-record mutation."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["patients", "case_intelligence", "ai_case_summary"],
        "installable": True,
        "auto_install": False,
        "removable": False,
        "role_permissions": {
            "admin": [],
            "dentist": ["read"],
            "hygienist": [],
            "assistant": [],
            "receptionist": [],
        },
    }

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read"]


__all__ = ["PatientPresentationModeModule"]
