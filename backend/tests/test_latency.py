from pathlib import Path

import pytest

from scripts.measure_latency import (
    ManifestError,
    TurnTiming,
    audio_seconds,
    check_audio_files,
    load_manifest,
    percentile,
    summarize,
)

HEADER = "file,text,condition,expected_duration_s\n"


def _write_manifest(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "manifest.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def _timing(mode: str = "cold", total: float | None = 1000.0, error: str | None = None) -> TurnTiming:
    return TurnTiming(
        run_id="r", timestamp_utc="t", file="a.wav", condition="short_clean", mode=mode,
        audio_seconds=1.0, stt_ms=100.0, llm_ms=200.0, tts_ms=300.0, total_ms=total,
        tts_cache_hit=False, retries=0, error=error, stt_model="s", llm_model="l", tts_model="t",
    )


# --- percentile ---


def test_percentile_single_value() -> None:
    assert percentile([7.0], 95) == 7.0


def test_percentile_median_odd_and_even() -> None:
    assert percentile([3, 1, 2], 50) == 2
    assert percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)


def test_percentile_p95_interpolates() -> None:
    values = list(range(1, 101))  # 1..100
    assert percentile(values, 95) == pytest.approx(95.05)


def test_percentile_bounds_and_unsorted_input() -> None:
    assert percentile([5, 1, 9], 0) == 1
    assert percentile([5, 1, 9], 100) == 9


def test_percentile_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1, 2], 101)


# --- manifest ---


def test_load_manifest_parses_rows(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, 'a.wav,"Yes, I do.",short_clean,1.5\nb.wav,Medellín,medium_clean,\n')
    rows = load_manifest(path)
    assert [r.file for r in rows] == ["a.wav", "b.wav"]
    assert rows[0].text == "Yes, I do."
    assert rows[0].expected_duration_s == 1.5
    assert rows[1].text == "Medellín"
    assert rows[1].expected_duration_s is None


@pytest.mark.parametrize(
    "body",
    ["a.wav,x,c,notanumber\n", ",x,c,\n", "a.wav,x,c,\na.wav,y,c,\n", ""],
)
def test_load_manifest_rejects_bad_rows(tmp_path: Path, body: str) -> None:
    with pytest.raises(ManifestError):
        load_manifest(_write_manifest(tmp_path, body))


def test_load_manifest_missing_file_and_columns(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(tmp_path / "nope.csv")
    bad = tmp_path / "bad.csv"
    bad.write_text("file,text\na.wav,x\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="condition"):
        load_manifest(bad)


def test_check_audio_files_lists_all_missing(tmp_path: Path) -> None:
    rows = load_manifest(_write_manifest(tmp_path, "a.wav,x,c,\nb.wav,y,c,\nc.wav,z,c,\n"))
    (tmp_path / "a.wav").write_bytes(b"")
    with pytest.raises(ManifestError, match="2 audio file") as info:
        check_audio_files(rows, tmp_path)
    assert "b.wav" in str(info.value) and "c.wav" in str(info.value)
    (tmp_path / "b.wav").write_bytes(b"")
    (tmp_path / "c.wav").write_bytes(b"")
    check_audio_files(rows, tmp_path)  # no error


# --- audio duration ---


def test_audio_seconds_reads_wav(tmp_path: Path) -> None:
    import wave

    path = tmp_path / "a.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 32000)
    assert audio_seconds(path) == pytest.approx(2.0)


def test_audio_seconds_reads_ogg_fixture() -> None:
    fixture = Path(__file__).parent / "fixtures" / "sample.ogg"
    if not fixture.is_file():
        pytest.skip("sample.ogg fixture not present")
    seconds = audio_seconds(fixture)
    assert seconds is not None and 0 < seconds < 60


def test_audio_seconds_unreadable(tmp_path: Path) -> None:
    bad = tmp_path / "x.ogg"
    bad.write_bytes(b"not ogg")
    assert audio_seconds(bad) is None
    assert audio_seconds(tmp_path / "missing.wav") is None


# --- summary ---


def test_summarize_warns_below_30_and_counts_errors() -> None:
    timings = [_timing("cold", 1000.0), _timing("cold", None, error="STTError: x"), _timing("warm", 500.0)]
    text = "\n".join(summarize(timings))
    assert "COLD  valid=1 errors=1" in text
    assert "WARM  valid=1 errors=0" in text
    assert "p95 is not stable" in text


def test_summarize_no_warning_with_30_valid() -> None:
    timings = [_timing("cold", float(i)) for i in range(30)] + [_timing("warm", float(i)) for i in range(30)]
    assert "not stable" not in "\n".join(summarize(timings))
