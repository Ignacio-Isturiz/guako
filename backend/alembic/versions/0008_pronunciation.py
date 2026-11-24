"""Pronunciation analysis: wider dimension/status columns and the monthly Azure audio counter.

turn_analyses.dimension and .status were String(10): "pronunciation" (13) and "skipped_no_audio"
(16) do not fit. They stay plain strings (validated by the Python enums) widened to 32, instead of a
database enum, so adding a value later never needs ALTER TYPE. On PostgreSQL widening a varchar is
a metadata-only change; SQLite does not enforce the length, and batch mode keeps it portable.

azure_speech_usage keeps the seconds of audio sent to Azure Speech per month (free plan quota).

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("turn_analyses") as batch:
        batch.alter_column("dimension", existing_type=sa.String(length=10), type_=sa.String(length=32), existing_nullable=False)
        batch.alter_column("status", existing_type=sa.String(length=10), type_=sa.String(length=32), existing_nullable=False)
    op.create_table(
        "azure_speech_usage",
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("seconds", sa.Float(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("month"),
    )


def downgrade() -> None:
    op.drop_table("azure_speech_usage")
    # Pronunciation rows are the only ones that can hold a value longer than 10 characters
    # ("pronunciation", "skipped_*"); they are removed so the narrower columns accept the rest.
    op.execute("DELETE FROM turn_analyses WHERE dimension = 'pronunciation'")
    with op.batch_alter_table("turn_analyses") as batch:
        batch.alter_column("status", existing_type=sa.String(length=32), type_=sa.String(length=10), existing_nullable=False)
        batch.alter_column("dimension", existing_type=sa.String(length=32), type_=sa.String(length=10), existing_nullable=False)
