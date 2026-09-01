"""Voice isolated stateless branch marker.

Revision ID: voice_0001
Revises: 0001
Create Date: 2026-08-28

The module persists no database state. This no-op revision gives the removable
module an isolated Alembic branch so its lifecycle cannot traverse another
module's schema history.
"""

from collections.abc import Sequence

revision: str = "voice_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("voice",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
