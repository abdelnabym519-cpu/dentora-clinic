"""AI Clinical Report — evidence-grounded, dentist-controlled draft reports."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .router import router


class AIClinicalReportModule(BaseModule):
    manifest = {
        "name": "ai_clinical_report",
        "version": "1.0.0",
        "summary": (
            "Draft-only AI clinical reports assembled from the reviewed cross-stage clinical "
            "evidence chain, with strict provenance and no canonical record mutation."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["clinical_copilot", "ai_second_review", "copilot"],
        "installable": True,
        "auto_install": False,
        "removable": False,
        "role_permissions": {
            "admin": ["read"],
            "dentist": ["read", "generate"],
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
        return ["read", "generate"]


__all__ = ["AIClinicalReportModule"]
