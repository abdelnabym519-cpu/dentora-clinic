"""Copilot module — operational chat plus a strict advisory clinical surface.

The existing agentic chat remains a thin surface over ``app/core/agents`` and
``app/core/llm``. Clinical Copilot is mounted separately under ``/clinical``;
it reads reviewed clinical workflow contracts at request time, exposes no tools,
and never mutates canonical clinical records.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.events.types import EventType
from app.core.plugins import BaseModule
from app.core.scheduling import ScheduledJob

from .clinical_router import router as clinical_router
from .models import CopilotConversation, CopilotMessage, CopilotNudge, CopilotSettings
from .router import router


class CopilotModule(BaseModule):
    manifest = {
        "name": "copilot",
        "version": "0.1.0",
        "summary": "Conversational AI agent over Dentora, scoped to the caller's permissions.",
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": [],
        "installable": True,
        "auto_install": True,
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["chat", "history.read"],
            "hygienist": ["chat", "history.read"],
            "assistant": ["chat", "history.read"],
            "receptionist": ["chat", "history.read"],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [
                {
                    "label": "nav.copilot",
                    "icon": "i-lucide-sparkles",
                    "to": "/copilot",
                    "permission": "copilot.chat",
                    "order": 90,
                },
            ],
        },
    }

    def get_models(self) -> list:
        return [CopilotConversation, CopilotMessage, CopilotNudge, CopilotSettings]

    def get_router(self) -> APIRouter:
        combined = APIRouter()
        combined.include_router(router)
        combined.include_router(clinical_router, prefix="/clinical")
        return combined

    def get_event_handlers(self) -> dict:
        # Proactive nudges (ADR 0014 §Deferred). Subscription only — no
        # cross-module import, so depends = [] holds (ADR 0003).
        from .events import on_appointment_cancelled

        return {EventType.APPOINTMENT_CANCELLED: on_appointment_cancelled}

    def get_permissions(self) -> list[str]:
        # Clinical Copilot reuses ``copilot.chat`` but additionally enforces
        # dentist role in the clinical service before any provider call.
        return ["chat", "history.read", "history.read_all", "supervise", "configure"]

    def get_tools(self) -> list:
        # Copilot consumes tools; it exposes none of its own.
        return []

    def get_scheduled_jobs(self) -> list[ScheduledJob]:
        # Morning digest — hourly gate; the task matches each clinic's
        # digest_hour against the current hour and no-ops otherwise.
        from .tasks import send_morning_digests

        return [
            ScheduledJob(
                id="copilot_morning_digests",
                func=send_morning_digests,
                trigger="cron",
                trigger_args={"minute": 0},
                name="Send the copilot morning digest to opted-in clinics (hourly gate)",
            ),
        ]
