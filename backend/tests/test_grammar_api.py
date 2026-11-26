from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.llm.base import BaseLLMProvider, LLMProvider, RawCompletion
from app.llm.errors import LLMAuthError, LLMError, LLMOutputError, LLMRateLimitError, LLMTimeoutError
from app.llm.factory import get_llm_provider
from app.main import app
from app.consents import user_with_terms

VALID = '{"errors": [{"original": "I goed", "correction": "I went", "error_type": "verb", "explanation": "Irregular."}]}'


class Scripted(BaseLLMProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, answer: str | None = None, raises: Exception | None = None) -> None:
        super().__init__(max_retries=0)
        self.answer = answer
        self.raises = raises

    def _complete(self, prompt: str, system: str | None, response_model: type[BaseModel]) -> RawCompletion:
        if self.raises:
            raise self.raises
        return RawCompletion(text=self.answer or "")


@pytest.fixture
def client() -> Iterator[TestClient]:
    # A signed-in user who accepted the current terms (the terms check itself is tested in test_safety).
    app.dependency_overrides[user_with_terms] = lambda: object()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _use(provider: LLMProvider) -> None:
    app.dependency_overrides[get_llm_provider] = lambda: provider


def test_analyze_returns_validated_errors(client: TestClient) -> None:
    _use(Scripted(VALID))
    res = client.post("/api/grammar/analyze", json={"text": "I goed home"})
    assert res.status_code == 200
    assert res.json()["errors"][0]["correction"] == "I went"


def test_empty_text_is_rejected(client: TestClient) -> None:
    _use(Scripted(VALID))
    assert client.post("/api/grammar/analyze", json={"text": ""}).status_code == 422


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (LLMRateLimitError("429 from provider"), 429, "ai_busy"),
        (LLMTimeoutError("read timeout"), 504, "ai_slow"),
        (LLMAuthError("bad key"), 503, "ai_misconfigured"),
        (LLMOutputError("x", last_error="y", attempts=3), 502, "ai_bad_answer"),
    ],
)
def test_errors_become_friendly_messages(client: TestClient, exc: LLMError, status: int, code: str) -> None:
    _use(Scripted(raises=exc))
    res = client.post("/api/grammar/analyze", json={"text": "hello"})
    assert res.status_code == status
    detail = res.json()["detail"]
    assert detail["code"] == code
    # No technical wording leaks to the client.
    assert str(exc) not in detail["message"]
    assert "LLM" not in detail["message"]


def test_requires_login() -> None:
    assert TestClient(app).post("/api/grammar/analyze", json={"text": "hi"}).status_code == 401
