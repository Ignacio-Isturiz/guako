"""Baseline: user, streaks and activity_days.

Until now the tables were created with create_all(). Databases that already have
them are left untouched; only a fresh database gets them created here.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "user" not in existing:
        op.create_table(
            "user",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("hashed_password", sa.String(length=1024), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("is_superuser", sa.Boolean(), nullable=False),
            sa.Column("is_verified", sa.Boolean(), nullable=False),
            sa.Column("username", sa.String(length=30), nullable=False),
        )
        op.create_index("ix_user_email", "user", ["email"], unique=True)
        op.create_index("ix_user_username", "user", ["username"], unique=True)

    if "streaks" not in existing:
        op.create_table(
            "streaks",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("current", sa.Integer(), nullable=False),
            sa.Column("best", sa.Integer(), nullable=False),
            sa.Column("last_day", sa.Date(), nullable=True),
            sa.Column("recoveries_used", sa.Integer(), nullable=False),
            sa.Column("recoveries_month", sa.String(length=7), nullable=False),
            sa.Column("timezone", sa.String(length=64), nullable=False),
        )

    if "activity_days" not in existing:
        op.create_table(
            "activity_days",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("day", sa.Date(), primary_key=True),
            sa.Column("recovered", sa.Boolean(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("activity_days")
    op.drop_table("streaks")
    op.drop_table("user")
