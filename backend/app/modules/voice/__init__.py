"""Dentora Voice — isolated local/offline voice control surface."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .router import router


class VoiceModule(BaseModule):
    manifest = {
        "name": "voice",
        "version": "0.1.0",
        "summary": "Local/offline deterministic voice control for Dentora.",
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": [],
        "installable": True,
        "auto_install": True,
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["use"],
            "hygienist": ["use"],
            "assistant": ["use"],
            "receptionist": ["use"],
        },
        "frontend": {"layer_path": "frontend", "navigation": []},
    }

    def get_models(self) -> list:
        return []

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["use"]

    def get_tools(self) -> list:
        from . import tools

        return tools.get_tools()
