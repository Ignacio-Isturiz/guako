"""Add user.feedback_language ('es' | 'en', default 'es').

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default fills the existing rows when the column is added as NOT NULL.
    # batch mode lets SQLite (used in development) alter tables too.
    with op.batch_alter_table("user") as batch:
        batch.add_column(
            sa.Column(
                "feedback_language",
                sa.Enum("es", "en", name="feedback_language", native_enum=False, length=2),
                nullable=False,
                server_default="es",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("user") as batch:
        batch.drop_column("feedback_language")
