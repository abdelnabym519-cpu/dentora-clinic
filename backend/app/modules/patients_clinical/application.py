"""Application boundary for patient clinical use cases."""

from __future__ import annotations

from typing import Any

from .ports import PatientsClinicalGateway


class PatientsClinicalApplication:
    """Route clinical operations through an injected persistence port."""

    def __init__(self, gateway: PatientsClinicalGateway) -> None:
        self._gateway = gateway

    async def invoke(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        return await self._gateway.invoke(operation, *args, **kwargs)
