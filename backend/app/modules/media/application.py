"""Persistence-neutral Media application boundary."""

from __future__ import annotations

from typing import Any

from .ports import MediaGateway


class MediaApplication:
    """Coordinate Media use cases through an injected outer gateway."""

    def __init__(self, gateway: MediaGateway) -> None:
        self._gateway = gateway

    async def invoke(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return await self._gateway.invoke(target, operation, *args, **kwargs)

    def invoke_sync(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return self._gateway.invoke_sync(target, operation, *args, **kwargs)
