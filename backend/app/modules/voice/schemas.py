"""Wire/domain contracts for Dentora Voice."""
from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

class VoiceRisk(StrEnum):
    READ = "read"
    NAVIGATION = "navigation"
    MUTATION = "mutation"
    DESTRUCTIVE = "destructive"

class VoiceState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    EXECUTING = "executing"
    SUCCESS = "success"
    ERROR = "error"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CLARIFICATION_REQUIRED = "clarification_required"

class VoiceUIContext(BaseModel):
    route: str = ""
    patient_id: UUID | None = None
    current_study: str | None = Field(default=None, max_length=255)
    selected_study: str | None = Field(default=None, max_length=255)
    comparison_study: str | None = Field(default=None, max_length=255)
    viewer_open: bool = False
    implant_planner_open: bool = False

class VoiceCommandPlan(BaseModel):
    command: str
    entities: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    risk: VoiceRisk
    available: bool = True
    blocked_reason: str | None = None
    requires_confirmation: bool = False

class InterpretRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=500)
    context: VoiceUIContext = Field(default_factory=VoiceUIContext)

class InterpretResponse(BaseModel):
    commands: list[VoiceCommandPlan]
    clarification_required: bool = False
    clarification_reason: str | None = None

class VoiceUIAction(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)

class VoiceStepResult(BaseModel):
    command: str
    ok: bool
    confidence: float
    message: str | None = None
    data: Any = None
    ui_action: VoiceUIAction | None = None
    clarification_required: bool = False
    confirmation_required: bool = False

class ExecuteResponse(BaseModel):
    state: VoiceState
    steps: list[VoiceStepResult]
    context: VoiceUIContext
