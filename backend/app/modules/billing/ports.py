"""Persistence-neutral ports for Billing application use cases."""

from __future__ import annotations

from typing import Any, Protocol


class BillingGateway(Protocol):
    """Outer adapter contract used by the Billing application boundary."""

    async def invoke(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...
