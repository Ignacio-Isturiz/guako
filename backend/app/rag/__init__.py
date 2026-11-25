"""RAG over the grammar-rule corpus: see corpus.py (the rules), store.py (pgvector), retrieve.py (the lookup)."""

from functools import lru_cache

from app.config import settings
from app.rag.embeddings import Embedder, EmbeddingError, GeminiEmbedder

__all__ = ["Embedder", "EmbeddingError", "get_embedder"]


@lru_cache
def get_embedder() -> Embedder | None:
    """The embedder, or None when there is no Gemini key (then the report simply has no rules)."""
    if settings.gemini_api_key is None:
        return None
    return GeminiEmbedder(
        settings.gemini_api_key,
        settings.embedding_model,
        settings.embedding_dimensions,
        settings.embedding_timeout_seconds,
    )
