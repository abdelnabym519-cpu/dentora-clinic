"""Online booking module.

Public patient booking flow that creates appointments directly in Agenda.
Depends on patients for patient identity/matching, agenda for appointments,
and schedules for real availability/free-slot calculation.
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule
from app.core.scheduling import ScheduledJob

from .models import BookingCloudRequest, BookingSettings
from .router import router


class BookingModule(BaseModule):
    manifest = {
        "name": "booking",
        "version": "0.1.0",
        "summary": "Public online appointment booking for patients.",
        "author": "DentalPin Clinic Custom",
        "license": "BSL-1.1",
        "category": "community",
        "depends": ["patients", "agenda", "schedules"],
        "installable": True,
        "auto_install": True,
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        return [BookingSettings, BookingCloudRequest]

    def get_scheduled_jobs(self) -> list[ScheduledJob]:
        from .tasks import sync_cloud_booking_requests

        return [
            ScheduledJob(
                id="booking_cloud_sync",
                func=sync_cloud_booking_requests,
                trigger="interval",
                trigger_args={"seconds": 30},
                name="Synchronize public booking cloud requests",
                max_instances=1,
            ),
        ]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["settings.read", "settings.write"]
