from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.tts import CachedTTSProvider, TTSError, TTSResult
from app.tts.audio import wav_duration_seconds
from app.tts.factory import get_tts_provider
from app.tts.fallback import FallbackTTSProvider
from tests.fakes import FakeTTS


class Named(FakeTTS):
    def __init__(self, name: str, voice: str, calls: list[str], error: Exception | None = None) -> None:
        super().__init__(calls, error)
        self.name = name
        self.voice = voice


def test_primary_answers_without_touching_the_backup(tmp_path: Path) -> None:
    calls: list[str] = []
    provider = FallbackTTSProvider(Named("groq", "hannah", calls), Named("openai", "alloy", calls))

    result = provider.synthesize("hi", str(tmp_path / "a.wav"))

    assert calls == ["tts"] and result.provider == "groq"
    assert (provider.name, provider.voice, provider.used_fallback) == ("groq", "hannah", False)


def test_backup_answers_when_groq_hits_its_quota(tmp_path: Path) -> None:
    calls: list[str] = []
    quota = TTSError("rate limit", status_code=429)
    provider = FallbackTTSProvider(Named("groq", "hannah", calls, quota), Named("openai", "alloy", calls))

    result = provider.synthesize("hi", str(tmp_path / "a.wav"))

    assert calls == ["tts", "tts"] and result.provider == "openai"
    assert (provider.name, provider.voice, provider.used_fallback) == ("openai", "alloy", True)
    assert Path(result.audio_path).is_file()


def test_both_failing_raises_the_backup_error(tmp_path: Path) -> None:
    provider = FallbackTTSProvider(
        Named("groq", "hannah", [], TTSError("a", status_code=429)), Named("openai", "alloy", [], TTSError("b", status_code=500))
    )
    with pytest.raises(TTSError) as info:
        provider.synthesize("hi", str(tmp_path / "a.wav"))
    assert info.value.status_code == 500


def test_each_provider_has_its_own_cache(tmp_path: Path) -> None:
    """A phrase cached from Groq must not be served as if it were the OpenAI voice."""
    from app.tts import TTSCache

    calls: list[str] = []
    groq = CachedTTSProvider(Named("groq", "hannah", calls), cache=TTSCache(str(tmp_path / "cache")))
    groq.synthesize("hello", str(tmp_path / "1.wav"))
    again = groq.synthesize("hello", str(tmp_path / "2.wav"))

    assert again.from_cache is True and calls == ["tts"]


def _cfg(**overrides) -> Settings:  # type: ignore[no-untyped-def]
    base = {"groq_api_key": SecretStr("g"), "openai_api_key": SecretStr("o")}
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_factory_adds_openai_backup_only_with_a_key() -> None:
    assert isinstance(get_tts_provider(_cfg()), FallbackTTSProvider)
    assert isinstance(get_tts_provider(_cfg(openai_api_key=None)), CachedTTSProvider)
    assert isinstance(get_tts_provider(_cfg(tts_fallback_provider="none")), CachedTTSProvider)


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
