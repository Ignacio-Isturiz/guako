from pathlib import Path

import pytest

from app.tts import CachedTTSProvider, TTSResult
from app.tts.audio import wav_duration_seconds
from tests.fakes import FakeTTS


class Named(FakeTTS):
    def __init__(self, name: str, voice: str, calls: list[str], error: Exception | None = None) -> None:
        super().__init__(calls, error)
        self.name = name
        self.voice = voice


def test_each_provider_has_its_own_cache(tmp_path: Path) -> None:
    """A phrase cached from Groq must not be served as if it were the OpenAI voice."""
    from app.tts import TTSCache

    calls: list[str] = []
    groq = CachedTTSProvider(Named("groq", "hannah", calls), cache=TTSCache(str(tmp_path / "cache")))
    groq.synthesize("hello", str(tmp_path / "1.wav"))
    again = groq.synthesize("hello", str(tmp_path / "2.wav"))

    assert again.from_cache is True and calls == ["tts"]


def test_has_cached_tells_without_calling_the_provider(tmp_path: Path) -> None:
    from app.tts import TTSCache

    calls: list[str] = []
    provider = CachedTTSProvider(Named("groq", "hannah", calls), cache=TTSCache(str(tmp_path / "cache")))
    assert provider.has_cached("hello") is False

    provider.synthesize("hello", str(tmp_path / "1.wav"))

    assert provider.has_cached("hello") is True and provider.has_cached("other") is False
    assert calls == ["tts"]


def test_wav_duration(tmp_path: Path) -> None:
    out = tmp_path / "a.wav"
    FakeTTS([]).synthesize("hi", str(out))
    assert wav_duration_seconds(str(out)) == pytest.approx(1.0)
    assert wav_duration_seconds(str(tmp_path / "missing.wav")) == 0.0
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"\x00" * (44 + 48_000))  # not a valid header: estimated from the size
    assert wav_duration_seconds(str(broken)) == pytest.approx(1.0)


def test_tts_result_type() -> None:
    assert TTSResult(audio_path="x", provider="groq", from_cache=False).provider == "groq"
