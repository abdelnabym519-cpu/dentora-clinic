"""Deterministic advisory Risk Engine over Case Intelligence."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import RiskResultRecord
from .router import router


class RiskEngineModule(BaseModule):
    manifest = {
        "name": "risk_engine",
        "version": "1.0.0",
        "summary": (
            "Deterministic observed-fact risk decision support and fail-closed patient-space "
            "3D Risk Map with explicit availability, provenance and mandatory dentist review."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["case_intelligence", "patients", "dental_3d"],
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
        return [RiskResultRecord]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "generate", "review"]


__all__ = ["RiskEngineModule"]
