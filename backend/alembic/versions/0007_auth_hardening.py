"""core — login throttle columns + refresh-token rotation chains.

SECURITY / LOAD VERIFICATION gaps G1 + G5:

* ``users.failed_login_attempts`` / ``users.failed_login_last_at`` back
  the per-account online-guessing throttle (IP rate limits alone cannot
  stop distributed credential stuffing). Fresh columns default to
  zero/NULL, i.e. "never failed" — no backfill needed.
* ``refresh_token_chains`` records the live token id per login session so
  ``/auth/refresh`` rotation can detect reuse of a superseded token
  (theft signal → revoke all sessions of the user).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("failed_login_last_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "refresh_token_chains",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("current_jti", sa.String(length=64), nullable=False),
        sa.Column("previous_jti", sa.String(length=64), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_token_chains_user_id", "refresh_token_chains", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_token_chains_user_id", table_name="refresh_token_chains")
    op.drop_table("refresh_token_chains")
    op.drop_column("users", "failed_login_last_at")
    op.drop_column("users", "failed_login_attempts")
