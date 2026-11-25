"""Exercises written by the LLM and accepted by the grammar analyser (personalised practice, layer 2).

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_exercises",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_generated_exercises_rule_id"), "generated_exercises", ["rule_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_generated_exercises_rule_id"), table_name="generated_exercises")
    op.drop_table("generated_exercises")
