"""Enforce one valid role-bearing membership per user and clinic.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-26

The application treats ``ClinicMembership`` as the authoritative tenant/RBAC
binding.  Duplicate rows for the same user/clinic can otherwise produce
ambiguous or conflicting roles, and direct database writes could persist a
role unknown to the RBAC permission map.  Fail closed when legacy data would
violate either invariant rather than deleting or rewriting security data.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALLOWED_ROLES = ("admin", "dentist", "hygienist", "assistant", "receptionist")


def upgrade() -> None:
    bind = op.get_bind()

    duplicate = bind.execute(
        sa.text(
            """
            SELECT user_id, clinic_id
            FROM clinic_memberships
            GROUP BY user_id, clinic_id
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot enforce clinic membership uniqueness: duplicate "
            f"user/clinic membership exists ({duplicate.user_id}, {duplicate.clinic_id})"
        )

    invalid_role = bind.execute(
        sa.text(
            """
            SELECT id, role
            FROM clinic_memberships
            WHERE role NOT IN ('admin', 'dentist', 'hygienist', 'assistant', 'receptionist')
            LIMIT 1
            """
        )
    ).first()
    if invalid_role is not None:
        raise RuntimeError(
            "Cannot enforce clinic membership role constraint: invalid role "
            f"{invalid_role.role!r} on membership {invalid_role.id}"
        )

    op.create_unique_constraint(
        "uq_clinic_memberships_user_clinic",
        "clinic_memberships",
        ["user_id", "clinic_id"],
    )
    op.create_check_constraint(
        "ck_clinic_memberships_role",
        "clinic_memberships",
        "role IN ('admin', 'dentist', 'hygienist', 'assistant', 'receptionist')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_clinic_memberships_role",
        "clinic_memberships",
        type_="check",
    )
    op.drop_constraint(
        "uq_clinic_memberships_user_clinic",
        "clinic_memberships",
        type_="unique",
    )
