"""Orthodontic Simulator isolated stateless branch marker.

Revision ID: ortho_sim_0001
Revises: 0001
Create Date: 2026-08-28

The module persists no database state. This no-op revision exists solely so the
removable plugin owns an isolated Alembic branch and uninstall/downgrade can be
proven not to traverse another module's revisions.
"""

from collections.abc import Sequence

revision: str = "ortho_sim_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("orthodontic_simulator",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
