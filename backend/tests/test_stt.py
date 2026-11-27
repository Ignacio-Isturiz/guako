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



# --- preparing the recording (iOS recordings that Whisper rejects) -------------------------------

import shutil  # noqa: E402
import subprocess  # noqa: E402

from app.stt import audio as stt_audio  # noqa: E402


def test_without_ffmpeg_there_is_no_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mp4 = tmp_path / "turn.mp4"
    mp4.write_bytes(b"mp4")
    monkeypatch.setattr(stt_audio.shutil, "which", lambda name: None)
    with stt_audio.as_flac(str(mp4)) as path:
        assert path is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_an_unreadable_file_has_no_copy(tmp_path: Path) -> None:
    mp4 = tmp_path / "turn.mp4"
    mp4.write_bytes(b"not really audio")
    with stt_audio.as_flac(str(mp4)) as path:
        assert path is None  # the provider then gives its own error


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_ios_mp4_becomes_flac_mono_16k_and_is_removed_after(tmp_path: Path) -> None:
    mp4 = tmp_path / "turn.mp4"
    # Fragmented MP4 with AAC, as Safari's MediaRecorder writes it
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "aac", "-movflags", "frag_keyframe+empty_moov", str(mp4)],
        check=True,
    )
    with stt_audio.as_flac(str(mp4)) as path:
        assert path is not None
        converted = Path(path)
        assert converted.suffix == ".flac" and converted.exists()
        probe = subprocess.run(["ffmpeg", "-nostdin", "-i", path], capture_output=True, text=True)
        assert "16000 Hz, mono" in probe.stderr
    assert not converted.exists()
