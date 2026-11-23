"""Add turns.user_audio_seconds and turns.reply_audio_seconds (daily 20-minute limit).

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("turns") as batch:
        batch.add_column(sa.Column("user_audio_seconds", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("reply_audio_seconds", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("turns") as batch:
        batch.drop_column("reply_audio_seconds")
        batch.drop_column("user_audio_seconds")
