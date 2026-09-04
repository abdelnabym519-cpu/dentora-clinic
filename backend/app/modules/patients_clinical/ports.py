"""Persistence-neutral port for patient clinical operations."""

from __future__ import annotations

from typing import Any, Protocol


class PatientsClinicalGateway(Protocol):
    """Outer adapter contract used by the clinical application boundary."""

    async def invoke(self, operation: str, *args: Any, **kwargs: Any) -> Any: ...
