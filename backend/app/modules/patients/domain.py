"""Pure patient domain representation.

This module deliberately has no dependency on FastAPI, SQLAlchemy, or any
persistence implementation. Infrastructure adapters map their records into
:class:`PatientEntity` before data crosses into the application layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PatientEntity:
    """Patient data exposed to application use cases."""

    id: UUID
    clinic_id: UUID
    first_name: str
    last_name: str
    phone: str | None
    email: str | None
    date_of_birth: date | None
    notes: str | None
    status: str
    do_not_contact: bool
    gender: str | None
    national_id: str | None
    national_id_type: str | None
    profession: str | None
    workplace: str | None
    preferred_language: str
    address: dict[str, Any] | None
    photo_url: str | None
    billing_name: str | None
    billing_tax_id: str | None
    billing_address: dict[str, Any] | None
    billing_email: str | None
    created_at: datetime
    updated_at: datetime

    @property
    def full_name(self) -> str:
        """Return the display name without depending on an ORM model."""
        return f"{self.first_name} {self.last_name}"

    @property
    def has_complete_billing_info(self) -> bool:
        """Whether the minimum invoicing identity is present."""
        return bool(self.billing_name and self.billing_tax_id)
