"""Persistence-neutral ports for Media application use cases."""

from __future__ import annotations

from typing import Any, Protocol


class MediaGateway(Protocol):
    """Outer adapter contract used by the Media application boundary."""

    async def invoke(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...

    def invoke_sync(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...
