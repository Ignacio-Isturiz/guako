"""End-to-end latency of a conversation turn, as the learner lives it, with REAL provider calls.

Run from backend/:
    python -m scripts.measure_turn_latency          # shows the plan; sends nothing
    python -m scripts.measure_turn_latency --yes    # runs it

Unlike scripts.measure_latency (a bare STT -> LLM -> TTS loop with a fixed prompt), this goes through the
real app: POST /api/sessions/{id}/turns with the audio, the provider router, the tutor prompt, the growing
history of the session, the database, and then GET of the reply audio. "Perceived" = the POST plus the audio
download: the moment the browser can start playing Guako's voice.

Isolation: a throwaway SQLite database, a throwaway audio folder and an EMPTY TTS cache (replies to new
messages are never cached in real life). The background analysis is switched off (in the real server it runs
after the response is sent, so it adds no latency) and Azure is never called. Not included: the network
between the browser and the server (here they share the process) and the time the browser takes to detect
that you stopped speaking.

Writes one JSON line per request to results/latency/turns-<run_id>.jsonl.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

# Before any app import: settings are read once at import time.
_TMP = Path(tempfile.mkdtemp(prefix="guako_turn_latency_"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'latency.db').as_posix()}"
os.environ["SESSIONS_AUDIO_DIR"] = str(_TMP / "sessions")
os.environ["TTS_CACHE_DIR"] = str(_TMP / "tts_cache")
os.environ["BACKGROUND_TASKS_ENABLED"] = "false"
os.environ["AZURE_SPEECH_KEY"] = ""
os.environ["AZURE_SPEECH_REGION"] = ""
os.environ["DAILY_LIMIT_MINUTES"] = "100000"

import asyncio  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from dataclasses import asdict, dataclass, field  # noqa: E402
from typing import Any  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app import sessions_api  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, User, get_async_session  # noqa: E402
from app.main import app  # noqa: E402
from app.users import current_active_user  # noqa: E402
from scripts.measure_latency import ManifestRow, audio_seconds, check_audio_files, load_manifest, new_run_id, percentile  # noqa: E402

LEVEL = "B1"
TOPIC = "Everyday life: work, travel and hobbies"


# --- Stage timers -----------------------------------------------------------


@dataclass
class StageLog:
    """What the providers did during one request. Requests run one at a time, so one log is enough."""

    stt_ms: float | None = None
    llm_ms: float | None = None
    tts_ms: float | None = None
    stt_provider: str | None = None
    llm_provider: str | None = None
    tts_provider: str | None = None
    tts_from_cache: bool | None = None
    llm_prompt_chars: int | None = None


_log = StageLog()
_lock = threading.Lock()


def _reset_log() -> StageLog:
    global _log
    with _lock:
        _log = StageLog()
        return _log


class _Timed:
    """Wraps a real provider; delegates everything and times the one call that matters."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class TimedSTT(_Timed):
    def transcribe(self, audio_path: str, context: str | None = None) -> Any:
        start = time.perf_counter()
        try:
            return self._inner.transcribe(audio_path, context)
        finally:
            _log.stt_ms = (time.perf_counter() - start) * 1000
            _log.stt_provider = f"{_safe(self._inner, 'name')}/{_safe(self._inner, 'model')}"


class TimedLLM(_Timed):
    def generate(self, prompt: str, response_model: Any, *, system: str | None = None) -> Any:
        start = time.perf_counter()
        try:
            return self._inner.generate(prompt, response_model, system=system)
        finally:
            _log.llm_ms = (time.perf_counter() - start) * 1000
            _log.llm_provider = f"{_safe(self._inner, 'name')}/{_safe(self._inner, 'model')}"
            _log.llm_prompt_chars = len(prompt) + len(system or "")


class TimedTTS(_Timed):
    def synthesize(self, text: str, output_path: str) -> Any:
        start = time.perf_counter()
        try:
            result = self._inner.synthesize(text, output_path)
            _log.tts_from_cache = bool(getattr(result, "from_cache", False))
            return result
        finally:
            _log.tts_ms = (time.perf_counter() - start) * 1000
            _log.tts_provider = f"{_safe(self._inner, 'name')}/{_safe(self._inner, 'voice')}"


def _safe(obj: Any, attr: str) -> str:
    try:
        return str(getattr(obj, attr))
    except Exception:  # noqa: BLE001 - a missing label must never break a measurement
        return "?"


# --- Records ----------------------------------------------------------------


@dataclass
class Measurement:
    run_id: str
    session: int
    kind: str  # "opening" (Guako speaks first) or "turn" (reply to the learner)
    turn_in_session: int  # 0 = opening; 1.. = learner turns, so history grows with it
    file: str | None
    condition: str | None
    audio_seconds: float | None
    post_ms: float | None = None
    download_ms: float | None = None
    perceived_ms: float | None = None
    stt_ms: float | None = None
    llm_ms: float | None = None
    tts_ms: float | None = None
    server_other_ms: float | None = None  # POST time not spent in a provider: upload, DB, graph, files
    llm_prompt_chars: int | None = None
    transcript: str | None = None
    reply: str | None = None
    reply_chars: int | None = None
    reply_audio_kb: float | None = None
    stt_provider: str | None = None
    llm_provider: str | None = None
    tts_provider: str | None = None
    tts_from_cache: bool | None = None
    status: int | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _fill(m: Measurement, log: StageLog) -> None:
    for name in ("stt_ms", "llm_ms", "tts_ms", "stt_provider", "llm_provider", "tts_provider", "tts_from_cache", "llm_prompt_chars"):
        setattr(m, name, getattr(log, name))
    if m.post_ms is not None:
        spent = sum(v for v in (m.stt_ms, m.llm_ms, m.tts_ms) if v is not None)
        m.server_other_ms = m.post_ms - spent


# --- Setup ------------------------------------------------------------------


async def _prepare_db(url: str) -> User:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = User(email="latency@example.test", hashed_password="x", username="latency", is_active=True, is_verified=True)
        db.add(user)
        await db.commit()
    await engine.dispose()
    return user


def _install_overrides(user: User) -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def session_override():  # type: ignore[no-untyped-def]
        async with maker() as db:
            yield db

    # The real chains, built once (as the app does), wrapped only to be timed.
    stt = TimedSTT(sessions_api.get_stt_provider())
    llm = TimedLLM(sessions_api.get_llm_provider(settings))
    tts = TimedTTS(sessions_api.get_tts_provider())
    app.dependency_overrides[get_async_session] = session_override
    app.dependency_overrides[current_active_user] = lambda: user
    app.dependency_overrides[sessions_api.get_stt_provider] = lambda: stt
    app.dependency_overrides[sessions_api.get_llm_provider] = lambda: llm
    app.dependency_overrides[sessions_api.get_tts_provider] = lambda: tts
    app.dependency_overrides[sessions_api.get_pronunciation_provider] = lambda: None

    # The analysis runs after the response in the real server; TestClient would wait for it. Off.
    async def no_analysis(*_: object, **__: object) -> None:
        return None

    sessions_api.run_turn_analysis = no_analysis  # type: ignore[assignment]


# --- Measurement ------------------------------------------------------------


def _download(client: TestClient, url: str | None, m: Measurement) -> None:
    if not url:
        m.download_ms = 0.0
        m.extra["no_audio"] = True
        return
    start = time.perf_counter()
    response = client.get(url)
    m.download_ms = (time.perf_counter() - start) * 1000
    if response.status_code == 200:
        m.reply_audio_kb = len(response.content) / 1024


def _measure_opening(client: TestClient, run_id: str, session_no: int, session_id: int) -> Measurement:
    m = Measurement(run_id, session_no, "opening", 0, None, None, None)
    log = _reset_log()
    start = time.perf_counter()
    response = client.post(f"/api/sessions/{session_id}/opening")
    m.post_ms = (time.perf_counter() - start) * 1000
    m.status = response.status_code
    if response.status_code >= 400:
        m.error = response.text[:300]
    else:
        body = response.json()
        m.reply = body["reply_text"]
        m.reply_chars = len(m.reply)
        _download(client, body.get("reply_audio_url"), m)
        m.perceived_ms = m.post_ms + (m.download_ms or 0.0)
    _fill(m, log)
    return m


def _measure_turn(
    client: TestClient, run_id: str, session_no: int, session_id: int, index: int, row: ManifestRow, audio_dir: Path
) -> Measurement:
    path = audio_dir / row.file
    m = Measurement(run_id, session_no, "turn", index, row.file, row.condition, audio_seconds(path))
    data = path.read_bytes()
    log = _reset_log()
    start = time.perf_counter()
    response = client.post(
        f"/api/sessions/{session_id}/turns", files={"audio": (f"turn{path.suffix}", data, "audio/ogg")}
    )
    m.post_ms = (time.perf_counter() - start) * 1000
    m.status = response.status_code
    if response.status_code >= 400:
        m.error = response.text[:300]
    else:
        body = response.json()
        m.transcript = body["user_transcript"]
        m.reply = body["reply_text"]
        m.reply_chars = len(m.reply)
        _download(client, body.get("reply_audio_url"), m)
        m.perceived_ms = m.post_ms + (m.download_ms or 0.0)
    _fill(m, log)
    return m


def _sessions(rows: list[ManifestRow], count: int) -> list[list[ManifestRow]]:
    """Round robin, so every session mixes short, long and noisy audios."""
    groups: list[list[ManifestRow]] = [[] for _ in range(count)]
    for i, row in enumerate(rows):
        groups[i % count].append(row)
    return [g for g in groups if g]


# --- Summary ----------------------------------------------------------------

STAGES = ("perceived_ms", "post_ms", "stt_ms", "llm_ms", "tts_ms", "server_other_ms", "download_ms")


def _stats_line(label: str, values: list[float]) -> str:
    if not values:
        return f"{label:<16}{'-':>8}"
    return (
        f"{label:<16}{percentile(values, 50):>8.0f}{percentile(values, 90):>8.0f}"
        f"{percentile(values, 95):>8.0f}{max(values):>8.0f}{sum(values) / len(values):>8.0f}"
    )


def summarize(ms: list[Measurement]) -> list[str]:
    lines: list[str] = []
    head = f"{'':<16}{'p50':>8}{'p90':>8}{'p95':>8}{'max':>8}{'mean':>8}   (ms)"
    for kind in ("turn", "opening"):
        subset = [m for m in ms if m.kind == kind]
        ok = [m for m in subset if m.error is None]
        lines.append(f"\n== {kind.upper()}S  valid={len(ok)} errors={len(subset) - len(ok)}")
        if not ok:
            continue
        lines.append(head)
        for stage in STAGES:
            lines.append(_stats_line(stage, [v for m in ok if (v := getattr(m, stage)) is not None]))
    turns = [m for m in ms if m.kind == "turn" and m.error is None]
    if turns:
        lines.append("\n-- perceived_ms by condition")
        for cond in sorted({m.condition or "" for m in turns}):
            lines.append(_stats_line(cond, [m.perceived_ms for m in turns if m.condition == cond and m.perceived_ms]))
        lines.append("\n-- perceived_ms by position in the session (history grows)")
        for idx in sorted({m.turn_in_session for m in turns}):
            lines.append(_stats_line(f"turn {idx}", [m.perceived_ms for m in turns if m.turn_in_session == idx and m.perceived_ms]))
        for target in (2000, 3000):
            under = sum(1 for m in turns if m.perceived_ms is not None and m.perceived_ms < target)
            lines.append(f"turns under {target / 1000:.0f} s: {under}/{len(turns)}")
        providers = sorted({f"llm={m.llm_provider} stt={m.stt_provider} tts={m.tts_provider}" for m in turns})
        lines.append("\nproviders used: " + " | ".join(providers))
        cache_hits = sum(1 for m in turns if m.tts_from_cache)
        if cache_hits:
            lines.append(f"NOTE: {cache_hits} TTS cache hit(s) (identical reply text).")
        if len(turns) < 30:
            lines.append(f"WARNING: {len(turns)} turns (< 30): p95 is indicative, not stable.")
    return lines


# --- Main -------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="End-to-end latency of a conversation turn (real providers).")
    p.add_argument("--yes", action="store_true", help="really call the providers (otherwise only the plan is shown)")
    p.add_argument("--audio-dir", default="evals/audio/latency")
    p.add_argument("--sessions", type=int, default=4, help="the audios are split into this many sessions (default 4)")
    p.add_argument("--limit", type=int, default=None, help="only the first N audios")
    p.add_argument("--pause-s", type=float, default=2.0, help="idle seconds between requests, not timed (default 2)")
    p.add_argument("--no-opening", action="store_true", help="skip Guako's opening line in each session")
    p.add_argument("--results-dir", default="results/latency")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    audio_dir = Path(args.audio_dir)
    rows = load_manifest(audio_dir / "manifest.csv")
    check_audio_files(rows, audio_dir)
    if args.limit is not None:
        rows = rows[: args.limit]
    groups = _sessions(rows, max(1, args.sessions))
    openings = 0 if args.no_opening else len(groups)
    print(
        f"Plan: {len(rows)} learner turns in {len(groups)} sessions (+{openings} openings).\n"
        f"Real calls: {len(rows)} STT, {len(rows) + openings} LLM, up to {len(rows) + openings} TTS "
        f"(order llm={settings.llm_conversation_order} stt={settings.stt_order} tts={settings.tts_order})."
    )
    if not args.yes:
        print("Nothing sent. Add --yes to run it.")
        return 0

    user = asyncio.run(_prepare_db(os.environ["DATABASE_URL"]))
    _install_overrides(user)
    run_id = new_run_id()
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"turns-{run_id}.jsonl"
    print(f"run_id={run_id} -> {out}")
    measurements: list[Measurement] = []

    with TestClient(app) as client, out.open("x", encoding="utf-8") as sink:

        def record(m: Measurement) -> None:
            measurements.append(m)
            sink.write(json.dumps(asdict(m), ensure_ascii=False) + "\n")
            sink.flush()
            if m.error:
                print(f"  s{m.session} {m.kind:<7} #{m.turn_in_session} ERROR {m.status}: {m.error[:120]}")
            else:
                print(
                    f"  s{m.session} {m.kind:<7} #{m.turn_in_session} {m.file or '':<26} perceived={m.perceived_ms:>6.0f} ms"
                    f"  stt={m.stt_ms or 0:>5.0f} llm={m.llm_ms or 0:>5.0f} tts={m.tts_ms or 0:>5.0f}"
                    f" other={m.server_other_ms or 0:>4.0f} dl={m.download_ms or 0:>3.0f}"
                )

        for s_no, group in enumerate(groups, start=1):
            created = client.post("/api/sessions", json={"level": LEVEL, "topic": TOPIC})
            if created.status_code >= 400:
                print(f"Could not create a session: {created.status_code} {created.text[:200]}", file=sys.stderr)
                return 1
            session_id = created.json()["id"]
            if not args.no_opening:
                time.sleep(args.pause_s)
                record(_measure_opening(client, run_id, s_no, session_id))
            for index, row in enumerate(group, start=1):
                time.sleep(args.pause_s)
                record(_measure_turn(client, run_id, s_no, session_id, index, row, audio_dir))

    print("\n".join(summarize(measurements)))
    print(f"\nScratch files (database, audio): {_TMP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
