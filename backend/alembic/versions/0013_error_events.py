"""Memory of the learner's grammar mistakes (RAG 2): one row per mistake, with its embedding.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

DIMENSIONS = 768  # must match settings.embedding_dimensions


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    op.create_table(
        "error_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=32), nullable=False),
        sa.Column("rule_id", sa.String(length=80), nullable=True),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("correction", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(DIMENSIONS) if postgres else sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "session_id", "turn_id"):
        op.create_index(op.f(f"ix_error_events_{column}"), "error_events", [column], unique=False)


def downgrade() -> None:
    for column in ("turn_id", "session_id", "user_id"):
        op.drop_index(op.f(f"ix_error_events_{column}"), table_name="error_events")
    op.drop_table("error_events")
