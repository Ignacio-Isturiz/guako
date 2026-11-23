from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.tts import (
    CachedTTSProvider,
    GroqOrpheusTTSProvider,
    TTSCache,
    TTSError,
    TTSProvider,
    TTSResult,
)

_key = settings.groq_api_key
_has_key = _key is not None and bool(_key.get_secret_value().strip())


def _fake_provider(name: str = "groq", voice: str = "tara") -> MagicMock:
    """A mock TTSProvider whose synthesize() writes a tiny fake WAV file."""
    provider = MagicMock(spec=TTSProvider)
    provider.name = name
    provider.voice = voice

    def _synthesize(text: str, output_path: str) -> TTSResult:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"RIFF-fake")
        return TTSResult(audio_path=output_path, provider=name, from_cache=False)

    provider.synthesize.side_effect = _synthesize
    return provider


def test_same_text_twice_calls_provider_once(tmp_path: Path) -> None:
    inner = _fake_provider()
    tts = CachedTTSProvider(inner, cache=TTSCache(tmp_path / "cache"))

    first = tts.synthesize("Hello there", str(tmp_path / "a.wav"))
    second = tts.synthesize("Hello there", str(tmp_path / "b.wav"))

    assert inner.synthesize.call_count == 1
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.provider == "groq"
    assert (tmp_path / "b.wav").read_bytes() == (tmp_path / "a.wav").read_bytes()


def test_different_text_is_not_served_from_cache(tmp_path: Path) -> None:
    inner = _fake_provider()
    tts = CachedTTSProvider(inner, cache=TTSCache(tmp_path / "cache"))

    tts.synthesize("Hello", str(tmp_path / "a.wav"))
    tts.synthesize("Goodbye", str(tmp_path / "b.wav"))

    assert inner.synthesize.call_count == 2


def test_cache_key_depends_on_text_and_voice(tmp_path: Path) -> None:
    cache = TTSCache(tmp_path)
    assert cache.path_for("hello", "tara") != cache.path_for("hello", "leah")
    assert cache.path_for("hello", "tara") != cache.path_for("hello!", "tara")
    assert cache.path_for("hello", "tara") == cache.path_for("hello", "tara")


def test_provider_error_propagates_and_is_not_cached(tmp_path: Path) -> None:
    inner = _fake_provider()
    inner.synthesize.side_effect = TTSError("Groq speech API error (HTTP 429)", status_code=429)
    cache = TTSCache(tmp_path / "cache")
    tts = CachedTTSProvider(inner, cache=cache)

    with pytest.raises(TTSError) as excinfo:
        tts.synthesize("Hi", str(tmp_path / "out.wav"))

    assert excinfo.value.status_code == 429
    assert not cache.path_for("Hi", "tara").exists()


@pytest.mark.skipif(not _has_key, reason="GROQ_API_KEY is not set")
def test_groq_orpheus_real_api_returns_wav(tmp_path: Path) -> None:
    # Spends 1 of the 100 daily requests of the Groq free tier.
    out = tmp_path / "real.wav"
    result = GroqOrpheusTTSProvider().synthesize("Hello, this is a test.", str(out))

    assert result.provider == "groq"
    assert out.read_bytes()[:4] == b"RIFF"
