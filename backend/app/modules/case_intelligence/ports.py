"""Application ports for authoritative Case Intelligence sources."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class CaseSourceProvider(Protocol):
    """Read authoritative source state without mutating canonical records."""

    async def collect(
        self,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> dict[str, dict]: ...
