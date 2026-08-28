"""whatsapp_evolution — optional self-hosted Evolution API WhatsApp provider.

The module depends only on Dentora's stable notifications channel seam. It is
installable/removable, tenant-scoped and never makes WhatsApp a core boot
requirement. Importing the module registers its ChannelAdapter idempotently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from app.core.plugins import BaseModule
from app.modules.notifications.channels import channel_registry

from .adapter import EvolutionApiAdapter
from .models import WhatsappEvolutionSettings, WhatsappEvolutionWebhookReceipt
from .router import router

if TYPE_CHECKING:
    from app.core.plugins.base import ModuleContext

EVOLUTION_TABLES = {
    "whatsapp_evolution_settings",
    "whatsapp_evolution_webhook_receipts",
}

channel_registry.register(EvolutionApiAdapter())


class WhatsappEvolutionModule(BaseModule):
    manifest = {
        "name": "whatsapp_evolution",
        "version": "0.1.0",
        "summary": "WhatsApp notifications via self-hosted Evolution API v2.",
        "author": "Dentora Core Team",
        "license": "BSL-1.1",
        "category": "community",
        "depends": ["notifications", "patients"],
        "installable": True,
        "auto_install": False,
        "removable": True,
        "role_permissions": {"admin": ["*"]},
    }

    def get_models(self) -> list:
        return [WhatsappEvolutionSettings, WhatsappEvolutionWebhookReceipt]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["settings.read", "settings.write"]

    async def uninstall(self, ctx: ModuleContext) -> None:
        channel_registry.unregister("whatsapp_evolution")
