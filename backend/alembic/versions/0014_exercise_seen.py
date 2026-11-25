"""Exercises each learner already answered (personalised practice): only the id and when, never the answer.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercise_seen",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exercise_id", sa.String(length=120), nullable=False),
        sa.Column("times", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "exercise_id"),
    )


def downgrade() -> None:
    op.drop_table("exercise_seen")
