"""Word practice: attempts of the "now you say it" exercise on the words that were hard.

One row per (session, word). It keeps how many scored attempts were used, how many Azure calls were
made (silence also costs a call), whether the word was passed and the best score, so the limits are
enforced by the server and survive a page reload. The table only references sessions (cascade).

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "word_practice",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("word", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("passed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("best_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "word"),
    )
    op.create_index(op.f("ix_word_practice_session_id"), "word_practice", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_word_practice_session_id"), table_name="word_practice")
    op.drop_table("word_practice")
