"""Text embeddings with Gemini (sync, like the LLM providers: callers run it in a worker thread).

``gemini-embedding-001`` can return shorter vectors; 768 keeps the table small and the quality is almost the
same as the full 3072. Shortened vectors are not unit length, so they are normalised here.
Documents and queries use different task types: that is what makes the search work well.
"""

import logging
import math
from typing import Literal, Protocol

from google import genai
from google.genai import types
from pydantic import SecretStr

logger = logging.getLogger("app.rag")

Task = Literal["document", "query"]
_TASK_TYPES = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


class EmbeddingError(RuntimeError):
    """The embedding call failed (network, quota, key). Retrieval treats it as "no rule found"."""


class Embedder(Protocol):
    dimensions: int

    def embed(self, texts: list[str], task: Task) -> list[list[float]]: ...


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


class GeminiEmbedder:
    # Gemini accepts up to 100 texts per embed_content call.
    BATCH = 100

    def __init__(self, api_key: SecretStr, model: str, dimensions: int, timeout_seconds: float) -> None:
        self.model = model
        self.dimensions = dimensions
        self._client = genai.Client(
            api_key=api_key.get_secret_value(),
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )

    def embed(self, texts: list[str], task: Task) -> list[list[float]]:
        config = types.EmbedContentConfig(task_type=_TASK_TYPES[task], output_dimensionality=self.dimensions)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH):
            batch = texts[start : start + self.BATCH]
            try:
                response = self._client.models.embed_content(model=self.model, contents=batch, config=config)
            except Exception as exc:  # google-genai raises several types (ClientError, APIError, httpx...)
                logger.warning("embedding_failed model=%s error=%s", self.model, type(exc).__name__)
                raise EmbeddingError(f"embedding call failed: {type(exc).__name__}") from exc
            embeddings = response.embeddings or []
            if len(embeddings) != len(batch) or any(e.values is None for e in embeddings):
                raise EmbeddingError("the embedding response does not match the request")
            vectors.extend(_normalise(list(e.values)) for e in embeddings)  # type: ignore[arg-type]
        return vectors
