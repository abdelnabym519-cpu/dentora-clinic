"""Shared normalization helpers for Case Intelligence source adapters."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from .contracts import AvailabilityStatus, digest_value


def jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def data(row: Any, *fields: str) -> dict[str, Any]:
    return {field: getattr(row, field) for field in fields}


def evidence(
    module: str,
    entity: str,
    record_id: Any,
    payload: Any,
    *,
    version: str | None = None,
    validation_state: str | None = None,
) -> dict[str, Any]:
    return {
        "source_module": module,
        "source_entity": entity,
        "source_record_id": str(record_id) if record_id is not None else None,
        "source_version": version,
        "source_digest": digest_value(jsonable(payload)),
        "validation_state": validation_state,
    }


def section(
    status: AvailabilityStatus,
    *,
    data_value: Any = None,
    evidence_value: list[dict[str, Any]] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status.value,
        "data": jsonable(data_value),
        "evidence": evidence_value or [],
        "reason": reason,
    }
