"""Voice-owned UI action tool.

Domain data/actions are delegated to existing module tools through ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.agents import AgentContext, Tool, ToolCategory


class UIActionArgs(BaseModel):
    action: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)


async def _ui_action(ctx: AgentContext, params: UIActionArgs) -> dict:
    del ctx
    return {"action": params.action, "payload": params.payload}


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="ui_action",
            description="Return a validated Dentora UI action for the Voice control surface.",
            parameters=UIActionArgs,
            handler=_ui_action,
            permissions=["voice.use"],
            category=ToolCategory.READ,
        )
    ]
