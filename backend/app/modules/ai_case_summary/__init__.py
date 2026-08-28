"""Traceable AI case summaries and evidence-grounded treatment-planning drafts."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import AICaseSummaryRecord
from .router import router
from .treatment_models import AITreatmentPlanRecord
from .treatment_router import router as treatment_router

router.include_router(treatment_router)


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
        "depends": ["case_intelligence", "patients"],
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
        return [AICaseSummaryRecord, AITreatmentPlanRecord]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "generate", "review"]


__all__ = ["AICaseSummaryModule"]
