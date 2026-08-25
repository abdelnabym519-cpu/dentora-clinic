"""Traceable AI case summaries derived only from Case Intelligence snapshots."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import AICaseSummaryRecord
from .router import router


class AICaseSummaryModule(BaseModule):
    manifest = {
        "name": "ai_case_summary",
        "version": "1.0.0",
        "summary": (
            "Advisory, evidence-traceable AI summaries derived from redacted CaseSnapshot "
            "inputs with explicit availability semantics and mandatory dentist review."
        ),
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["case_intelligence"],
        "installable": True,
        "auto_install": False,
        "removable": True,
        "role_permissions": {
            "admin": ["read", "generate"],
            "dentist": ["read", "generate", "review"],
            "hygienist": ["read"],
            "assistant": ["read"],
            "receptionist": [],
        },
    }

    def get_models(self) -> list:
        return [AICaseSummaryRecord]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "generate", "review"]


__all__ = ["AICaseSummaryModule"]
