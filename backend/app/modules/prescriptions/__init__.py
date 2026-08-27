"""Electronic Prescription module plugin."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import PrescriptionAuditRecord, PrescriptionItemRecord, PrescriptionRecord
from .router import router


class ElectronicPrescriptionModule(BaseModule):
    manifest = {
        "name": "prescriptions",
        "version": "1.1.0",
        "summary": "Tenant-isolated prescriptions with auditable WhatsApp delivery.",
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["patients", "notifications"],
        "installable": True,
        "auto_install": True,
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["read", "write", "issue", "cancel", "void", "audit"],
            "hygienist": ["read"],
            "assistant": ["read"],
            "receptionist": [],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [
                {
                    "label": "Prescriptions",
                    "to": "/prescriptions",
                    "icon": "i-lucide-pill",
                    "permission": "prescriptions.read",
                }
            ],
        },
    }

    def get_models(self) -> list:
        return [PrescriptionRecord, PrescriptionItemRecord, PrescriptionAuditRecord]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "write", "issue", "cancel", "void", "audit"]
