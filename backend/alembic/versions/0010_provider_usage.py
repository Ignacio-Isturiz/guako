"""Provider router: daily usage per provider, a log of calls, and turns that may have no reply audio.

provider_usage: one row per (UTC day, provider, capability, use) with requests, failures, tokens, audio
seconds, characters and the estimated cost in USD. It restores the daily caps and the spending after a restart.

provider_calls: one row per call that reached a provider (no prompts, texts or audio), kept 30 days and
linked to the session/turn it served, to explain afterwards which provider answered what and what it cost.

turns.reply_audio_path becomes nullable: when every voice provider is out, the turn is saved without audio
and the browser reads the reply aloud with its own voice.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_usage",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("capability", sa.String(length=8), nullable=False),
        sa.Column("use", sa.String(length=16), nullable=False),
        sa.Column("requests", sa.Integer(), server_default="0", nullable=False),
        sa.Column("successes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rate_limited", sa.Integer(), server_default="0", nullable=False),
        sa.Column("as_fallback", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("audio_seconds_in", sa.Float(), server_default="0", nullable=False),
        sa.Column("audio_seconds_out", sa.Float(), server_default="0", nullable=False),
        sa.Column("chars", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("day", "provider", "capability", "use"),
    )
    op.create_table(
        "provider_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("capability", sa.String(length=8), nullable=False),
        sa.Column("use", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("audio_seconds", sa.Float(), nullable=True),
        sa.Column("chars", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("fallback_from", sa.String(length=16), nullable=True),
        # No foreign keys on purpose: the log must outlive a deleted session.
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("turn_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_provider_calls_created_at"), "provider_calls", ["created_at"], unique=False)
    op.create_index(op.f("ix_provider_calls_turn_id"), "provider_calls", ["turn_id"], unique=False)
    with op.batch_alter_table("turns") as batch:
        batch.alter_column("reply_audio_path", existing_type=sa.String(length=500), nullable=True)


def downgrade() -> None:
    # Turns saved without audio get an empty path so the column can be NOT NULL again.
    op.execute("UPDATE turns SET reply_audio_path = '' WHERE reply_audio_path IS NULL")
    with op.batch_alter_table("turns") as batch:
        batch.alter_column("reply_audio_path", existing_type=sa.String(length=500), nullable=False)
    op.drop_index(op.f("ix_provider_calls_turn_id"), table_name="provider_calls")
    op.drop_index(op.f("ix_provider_calls_created_at"), table_name="provider_calls")
    op.drop_table("provider_calls")
    op.drop_table("provider_usage")
