"""Latency measurement of the audio pipeline (STT -> LLM -> TTS) with REAL API calls.

Run from backend/:  python -m scripts.measure_latency --runs 3
Never run by pytest. Writes one JSON line per measurement to results/latency/<run_id>.jsonl.
Each audio is measured in two modes:
  cold - TTS cache empty (a real TTS call)
  warm - TTS cache filled (TTS served from cache; the text is the reply of the cold run)
"""

import argparse
import csv
import json
import sys
import tempfile
import time
import uuid
import wave
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.config import settings
from app.llm.errors import LLMError
from app.llm.factory import get_llm_provider
from app.stt import GroqWhisperSTTProvider, STTError
from app.tts import CachedTTSProvider, GroqOrpheusTTSProvider, TTSCache, TTSError
from scripts.audio_pipeline import TurnResult, run_turn

Mode = Literal["cold", "warm"]
MODES: tuple[Mode, ...] = ("cold", "warm")
STAGES: tuple[str, ...] = ("stt_ms", "llm_ms", "tts_ms", "total_ms")

MANIFEST_COLUMNS: tuple[str, ...] = ("file", "text", "condition", "expected_duration_s")
# MVP target: a whole turn should finish under this many milliseconds.
TARGET_TOTAL_MS = 3000.0
# Below this many valid measurements per mode, p95 is not reliable.
MIN_SAMPLES_FOR_P95 = 30
# Groq free tier: 100 TTS requests/day per organization.
TTS_DAILY_LIMIT = 100


@dataclass(frozen=True)
class LatencyConfig:
    audio_dir: Path
    manifest_path: Path
    results_dir: Path
    runs: int = 3
    limit: int | None = None
    # Idle seconds before each turn (not timed) to stay under the free-tier rate limits.
    pause_s: float = 3.0


@dataclass(frozen=True)
class ManifestRow:
    file: str
    text: str
    condition: str
    expected_duration_s: float | None


@dataclass
class TurnTiming:
    """One measurement (one line of the JSONL file)."""

    run_id: str
    timestamp_utc: str
    file: str
    condition: str
    mode: str
    audio_seconds: float | None
    stt_ms: float | None
    llm_ms: float | None
    tts_ms: float | None
    total_ms: float | None
    tts_cache_hit: bool | None
    retries: int
    error: str | None
    stt_model: str
    llm_model: str
    tts_model: str


class ManifestError(Exception):
    """The manifest or the audio files are missing or malformed."""


# --- Manifest ---------------------------------------------------------------


def load_manifest(path: Path) -> list[ManifestRow]:
    """Parse manifest.csv. Raises ManifestError on a missing file, column or value."""
    if not path.is_file():
        raise ManifestError(f"Manifest not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing_cols = {"file", "text", "condition"} - set(reader.fieldnames or [])
        if missing_cols:
            raise ManifestError(f"Manifest is missing columns: {', '.join(sorted(missing_cols))}")
        rows: list[ManifestRow] = []
        seen: set[str] = set()
        for line_no, raw in enumerate(reader, start=2):
            name = (raw.get("file") or "").strip()
            if not name:
                raise ManifestError(f"Manifest line {line_no}: empty 'file'")
            if name in seen:
                raise ManifestError(f"Manifest line {line_no}: duplicate file '{name}'")
            seen.add(name)
            duration_raw = (raw.get("expected_duration_s") or "").strip()
            try:
                duration = float(duration_raw) if duration_raw else None
            except ValueError as exc:
                raise ManifestError(f"Manifest line {line_no}: invalid expected_duration_s '{duration_raw}'") from exc
            rows.append(
                ManifestRow(
                    file=name,
                    text=(raw.get("text") or "").strip(),
                    condition=(raw.get("condition") or "").strip(),
                    expected_duration_s=duration,
                )
            )
    if not rows:
        raise ManifestError(f"Manifest is empty: {path}")
    return rows


def check_audio_files(rows: list[ManifestRow], audio_dir: Path) -> None:
    """Fail with the full list of missing files, before any API call."""
    missing = [row.file for row in rows if not (audio_dir / row.file).is_file()]
    if missing:
        raise ManifestError(f"{len(missing)} audio file(s) missing in {audio_dir}: {', '.join(missing)}")


# --- Statistics -------------------------------------------------------------


def percentile(values: list[float], p: float) -> float:
    """Percentile ``p`` (0-100) by linear interpolation between closest ranks."""
    if not values:
        raise ValueError("percentile of an empty list")
    if not 0 <= p <= 100:
        raise ValueError("p must be between 0 and 100")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p / 100
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(timings: list[TurnTiming]) -> list[str]:
    """Console summary lines: p50/p95 per mode and stage, plus errors and warnings."""
    lines: list[str] = []
    for mode in MODES:
        subset = [t for t in timings if t.mode == mode]
        valid = [t for t in subset if t.error is None]
        errors = len(subset) - len(valid)
        lines.append(f"\n== {mode.upper()}  valid={len(valid)} errors={errors}")
        if not valid:
            continue
        lines.append(f"{'stage':<10}{'p50 (ms)':>10}{'p95 (ms)':>10}")
        for stage in STAGES:
            values = [v for t in valid if (v := getattr(t, stage)) is not None]
            if values:
                lines.append(f"{stage:<10}{percentile(values, 50):>10.0f}{percentile(values, 95):>10.0f}")
        totals = [t.total_ms for t in valid if t.total_ms is not None]
        under = sum(1 for v in totals if v < TARGET_TOTAL_MS)
        if totals:
            lines.append(f"turns under {TARGET_TOTAL_MS / 1000:.0f}s: {under}/{len(totals)} ({100 * under / len(totals):.0f}%)")
        if len(valid) < MIN_SAMPLES_FOR_P95:
            lines.append(f"WARNING: only {len(valid)} valid measurements (< {MIN_SAMPLES_FOR_P95}); p95 is not stable.")
    return lines


# --- Measurement ------------------------------------------------------------


def _ogg_seconds(data: bytes) -> float | None:
    """Duration of an Ogg Opus/Vorbis file: last page granule position / sample rate."""
    if not data.startswith(b"OggS"):
        return None
    last = data.rfind(b"OggS")
    granule = int.from_bytes(data[last + 6 : last + 14], "little", signed=True)
    if granule <= 0:
        return None
    if b"OpusHead" in data[:100]:
        start = data.index(b"OpusHead")
        pre_skip = int.from_bytes(data[start + 10 : start + 12], "little")
        return (granule - pre_skip) / 48000  # Opus granules always count at 48 kHz
    if b"\x01vorbis" in data[:100]:
        start = data.index(b"\x01vorbis")
        rate = int.from_bytes(data[start + 12 : start + 16], "little")
        return granule / rate if rate else None
    return None


def audio_seconds(path: Path) -> float | None:
    """Duration in seconds of a WAV or Ogg file; None if it cannot be read."""
    try:
        if path.suffix.lower() == ".ogg":
            return _ogg_seconds(path.read_bytes())
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / wav.getframerate()
    except (wave.Error, EOFError, OSError):
        return None


def _describe(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    suffix = f" [HTTP {status}]" if isinstance(exc, TTSError) and status else ""
    return f"{type(exc).__name__}: {exc}{suffix}"


def _timing(base: dict[str, object], mode: Mode, turn: TurnResult, error: str | None, retries: int) -> TurnTiming:
    return TurnTiming(
        **base,  # type: ignore[arg-type]
        mode=mode,
        stt_ms=turn.stt_ms,
        llm_ms=turn.llm_ms,
        tts_ms=turn.tts_ms,
        total_ms=turn.total_ms if error is None else None,
        tts_cache_hit=turn.from_cache,
        retries=retries,
        error=error,
    )


def measure_audio(
    row: ManifestRow,
    cfg: LatencyConfig,
    run_id: str,
    stt: GroqWhisperSTTProvider,
    llm: object,
    tts_provider: GroqOrpheusTTSProvider,
    out_dir: Path,
) -> list[TurnTiming]:
    """One cold + one warm measurement for ``row``. A failure is recorded, not raised."""
    audio = cfg.audio_dir / row.file
    base: dict[str, object] = {
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "file": row.file,
        "condition": row.condition,
        "audio_seconds": audio_seconds(audio),
        "stt_model": stt.model,
        "llm_model": str(getattr(llm, "model", "unknown")),
        "tts_model": tts_provider.model,
    }
    results: list[TurnTiming] = []
    cold_reply: str | None = None
    # A fresh cache dir per iteration: empty for cold, filled by cold for warm.
    with tempfile.TemporaryDirectory(prefix="guako_tts_cache_") as cache_dir:
        tts = CachedTTSProvider(tts_provider, cache=TTSCache(cache_dir))
        for mode in MODES:
            time.sleep(cfg.pause_s)
            turn = TurnResult()
            error: str | None = None
            if mode == "warm" and cold_reply is None:
                error = "skipped: cold run failed, no reply text to replay"
            else:
                try:
                    run_turn(
                        stt,
                        llm,  # type: ignore[arg-type]
                        tts,
                        str(audio),
                        str(out_dir / f"{audio.stem}_{mode}.wav"),
                        tts_text=cold_reply if mode == "warm" else None,
                        result=turn,
                    )
                except (STTError, LLMError, TTSError) as exc:
                    error = _describe(exc)
            if mode == "cold" and error is None:
                cold_reply = turn.reply
            retries = max(getattr(llm, "last_attempts", 1) - 1, 0)
            results.append(_timing(base, mode, turn, error, retries))
    return results


def new_run_id() -> str:
    return f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"


def run(cfg: LatencyConfig) -> int:
    rows = load_manifest(cfg.manifest_path)
    check_audio_files(rows, cfg.audio_dir)
    if cfg.limit is not None:
        rows = rows[: cfg.limit]
    tts_calls = len(rows) * cfg.runs
    if tts_calls > TTS_DAILY_LIMIT:
        print(
            f"WARNING: {tts_calls} real TTS calls planned (cold runs); the Groq free tier allows {TTS_DAILY_LIMIT}/day.",
            file=sys.stderr,
        )

    try:
        stt = GroqWhisperSTTProvider()
        llm = get_llm_provider(settings)
        tts_provider = GroqOrpheusTTSProvider()
    except (STTError, LLMError, TTSError) as exc:
        print(f"Configuration error: {_describe(exc)}", file=sys.stderr)
        return 1

    run_id = new_run_id()
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    results_path = cfg.results_dir / f"{run_id}.jsonl"
    timings: list[TurnTiming] = []
    print(f"run_id={run_id} files={len(rows)} runs={cfg.runs} -> {results_path}")

    with tempfile.TemporaryDirectory(prefix="guako_latency_out_") as out_name:
        # "x" never overwrites a previous run.
        with results_path.open("x", encoding="utf-8") as sink:
            for row in rows:
                for iteration in range(1, cfg.runs + 1):
                    for timing in measure_audio(row, cfg, run_id, stt, llm, tts_provider, Path(out_name)):
                        timings.append(timing)
                        sink.write(json.dumps(asdict(timing), ensure_ascii=False) + "\n")
                        sink.flush()
                        status = timing.error or f"{timing.total_ms:.0f} ms"
                        print(f"  {row.file} run {iteration} {timing.mode:<4} {status}")

    print("\n".join(summarize(timings)))
    return 0


def parse_args(argv: list[str] | None = None) -> LatencyConfig:
    parser = argparse.ArgumentParser(description="Measure STT -> LLM -> TTS latency with real API calls.")
    parser.add_argument("--runs", type=int, default=3, help="runs per audio and mode (default: 3)")
    parser.add_argument("--audio-dir", default="evals/audio/latency", help="folder with the WAV files and manifest.csv")
    parser.add_argument("--manifest", default=None, help="manifest path (default: <audio-dir>/manifest.csv)")
    parser.add_argument("--results-dir", default="results/latency", help="where the JSONL results go")
    parser.add_argument("--pause-s", type=float, default=3.0, help="idle seconds before each turn, to avoid 429s (default: 3)")
    parser.add_argument("--limit", type=int, default=None, help="measure only the first N audios (cheap smoke test)")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    audio_dir = Path(args.audio_dir)
    return LatencyConfig(
        audio_dir=audio_dir,
        manifest_path=Path(args.manifest) if args.manifest else audio_dir / "manifest.csv",
        results_dir=Path(args.results_dir),
        runs=args.runs,
        limit=args.limit,
        pause_s=args.pause_s,
    )


def main() -> int:
    cfg = parse_args()
    try:
        return run(cfg)
    except ManifestError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
