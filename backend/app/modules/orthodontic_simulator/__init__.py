"""Independent, removable deterministic Orthodontic Simulator module."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .router import router


class OrthodonticSimulatorModule(BaseModule):
    manifest = {
        "name": "orthodontic_simulator",
        "version": "0.1.0",
        "summary": (
            "Local deterministic orthodontic movement sandbox over reviewed per-tooth "
            "Dental3D geometry. Non-predictive, non-clinical and fail-closed when geometry, "
            "scale or coordinate-frame provenance is unavailable."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["patients", "dental_3d"],
        "installable": True,
        "auto_install": False,
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["*"],
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
        return []

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "write"]


__all__ = ["OrthodonticSimulatorModule"]
