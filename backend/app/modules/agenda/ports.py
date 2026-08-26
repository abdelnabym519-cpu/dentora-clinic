"""Application ports for Agenda.

The application layer depends on this protocol instead of SQLAlchemy, FastAPI,
ORM models, or the Dentora event bus.  The concrete gateway lives in the outer
infrastructure layer.
"""

from __future__ import annotations

from typing import Any, Protocol


class AgendaGateway(Protocol):
    """Persistence/integration operations required by Agenda use cases.

    The compatibility migration intentionally exposes operation names matching
    the stable Agenda service contract so callers can migrate without an API or
    behavior rewrite.  Concrete implementations may use SQLAlchemy/PostgreSQL.
    """

    async def invoke(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        """Execute one Agenda operation in an outer adapter."""
        ...
