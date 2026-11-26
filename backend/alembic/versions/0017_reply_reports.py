"""Reports of Guako's replies made by learners (Google Play's rule for generative AI apps).

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reply_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "turn_number", "user_id"),
    )
    op.create_index(op.f("ix_reply_reports_user_id"), "reply_reports", ["user_id"], unique=False)
    op.create_index(op.f("ix_reply_reports_created_at"), "reply_reports", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reply_reports_created_at"), table_name="reply_reports")
    op.drop_index(op.f("ix_reply_reports_user_id"), table_name="reply_reports")
    op.drop_table("reply_reports")
