from pathlib import Path

import pytest

from app.config import settings
from app.stt.groq import GroqWhisperSTTProvider

# Short English speech sample (any format Groq accepts, e.g. .mp3 or .wav).
FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = next(iter(sorted(FIXTURES.glob("sample.*"))), None)

_key = settings.groq_api_key
_has_key = _key is not None and bool(_key.get_secret_value().strip())


@pytest.mark.skipif(not _has_key, reason="GROQ_API_KEY is not set")
@pytest.mark.skipif(SAMPLE is None, reason="tests/fixtures/sample.* audio file is missing")
def test_groq_whisper_returns_word_timings() -> None:
    assert SAMPLE is not None
    result = GroqWhisperSTTProvider().transcribe(str(SAMPLE))

    assert result.text
    assert result.words, "expected word-level timestamps"
    assert all(w.start < w.end for w in result.words)
