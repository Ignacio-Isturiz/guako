"""Confidence of the transcription, kept per turn.

Groq and OpenAI Whisper report, per segment, the average log-probability of the words and the probability
that there is no speech. We keep two numbers per turn (``stt_confidence`` = exp of the average log-probability,
``stt_no_speech_prob`` = the highest no-speech probability) because the judges of "darse a entender" and
"listening" run later, in the background, and must know how much to trust the text they read.
Both are NULL for turns saved before this column existed or when the provider did not send them.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("turns") as batch:
        batch.add_column(sa.Column("stt_confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("stt_no_speech_prob", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("turns") as batch:
        batch.drop_column("stt_no_speech_prob")
        batch.drop_column("stt_confidence")
