"""API schemas for the Evolution WhatsApp provider module."""

from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, Field


class EvolutionSettingsUpdate(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    instance_name: str = Field(min_length=1, max_length=120)
    api_key: str | None = Field(default=None, min_length=8, max_length=1000)
    webhook_token: str | None = Field(default=None, min_length=16, max_length=1000)
    is_active: bool = True


class EvolutionSettingsResponse(BaseModel):
    base_url: str | None = None
    instance_name: str | None = None
    has_api_key: bool = False
    has_webhook_token: bool = False
    is_active: bool = False
    is_verified: bool = False
    connection_state: str | None = None
    last_verified_at: datetime | None = None
    webhook_configured_at: datetime | None = None


class EvolutionWebhookConfigureRequest(BaseModel):
    dentora_public_base_url: AnyHttpUrl


class EvolutionConnectionResponse(BaseModel):
    connected: bool
    state: str | None = None
