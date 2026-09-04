"""Align clinic membership role storage with its RBAC domain constraint.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-26

The role CHECK constraint is the authoritative database guard for the RBAC
domain. Widen the storage column so representative unknown role values reach
that constraint instead of failing earlier on an incidental VARCHAR limit.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "clinic_memberships",
        "role",
        existing_type=sa.String(length=20),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "clinic_memberships",
        "role",
        existing_type=sa.String(length=64),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
