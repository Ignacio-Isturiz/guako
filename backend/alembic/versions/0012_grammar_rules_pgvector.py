"""Embeddings of the grammar-rule corpus (RAG), stored with pgvector.

Only the vector, the error type, the level and a hash of the embedded text are saved: the rule text is read from
``app/rag/rules`` so there is a single source of truth. The ``vector`` extension and the vector column exist only
in PostgreSQL; in SQLite (local default, tests) the column is JSON and the RAG stays switched off.

No vector index on purpose: the corpus is a few dozen rows and an exact scan is faster and always correct.
Add an HNSW index (``USING hnsw (embedding vector_cosine_ops)``) if it grows to tens of thousands of rows.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

DIMENSIONS = 768  # must match settings.embedding_dimensions


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "grammar_rules",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("error_type", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=2), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(DIMENSIONS) if postgres else sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_grammar_rules_error_type"), "grammar_rules", ["error_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_grammar_rules_error_type"), table_name="grammar_rules")
    op.drop_table("grammar_rules")
