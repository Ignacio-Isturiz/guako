"""Pronunciation eval: evals/grammar/pronunciation_cases.jsonl against Azure Speech (REAL calls, free monthly quota).

Azure is the only pronunciation provider: there is no router and no fallback here, and it costs no money, but
every second sent comes out of the free 5 h a month and is NOT counted in the app's monthly counter.

Audio of case ``pr_01`` is the case's ``audio_file`` (relative to evals/grammar/) or evals/grammar/audio/pr_01.<ext>,
WAV first (other formats go through ffmpeg). A case without audio is reported as ``no_audio``: never invented.

A case is a HIT when every ``target_words`` entry (the word the speaker mispronounced on purpose) scores below
the report's "hard word" threshold, i.e. the learner would see it among the words that cost them.
"""

import re
import wave
from pathlib import Path
from typing import Any

from app.pronunciation import AzurePronunciationProvider, PronunciationError
from app.pronunciation.errors import (
    PronunciationAudioError,
    PronunciationAuthError,
    PronunciationNoSpeechError,
    PronunciationNotConfiguredError,
)
from app.reports import HARD_WORD_THRESHOLD
from scripts.evals.common import EVALS_DIR, Failure, Plan, base_result, load_jsonl, new_run_id, now_iso, with_retries

CASES = EVALS_DIR / "grammar" / "pronunciation_cases.jsonl"
AUDIO_DIR = EVALS_DIR / "grammar" / "audio"
EXTENSIONS = (".wav", ".m4a", ".ogg", ".webm", ".mp3")


def load_cases() -> list[dict[str, Any]]:
    return load_jsonl(CASES)


def _word(text: str) -> str:
    return re.sub(r"[^\w]", "", text.lower())


def find_audio(case: dict[str, Any]) -> Path | None:
    if case.get("audio_file"):
        path = EVALS_DIR / "grammar" / case["audio_file"]
        return path if path.is_file() else None
    return next((p for ext in EXTENSIONS if (p := AUDIO_DIR / f"{case['id']}{ext}").is_file()), None)


def wav_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError):
        return None


def classify(exc: Exception) -> Failure:
    if isinstance(exc, PronunciationNotConfiguredError | PronunciationAuthError):
        return Failure("auth", False)
    if isinstance(exc, PronunciationAudioError | PronunciationNoSpeechError):
        return Failure("bad_input", False)
    if isinstance(exc, PronunciationError):
        return Failure("provider_error", True)
    return Failure("unexpected_error", False)


def plan(cfg: Any, repeats: int = 1, limit: int | None = None) -> Plan:  # noqa: ARG001 - same signature as the other sets
    cases = load_cases()[:limit] if limit else load_cases()
    audios = [find_audio(c) for c in cases]
    missing = [c["id"] for c, a in zip(cases, audios, strict=True) if a is None]
    seconds = [s for a in audios if a and (s := wav_seconds(a)) is not None]
    return Plan(
        "pronunciation",
        calls=len(cases) - len(missing),
        estimated_cost_usd=0.0,
        notes=[
            "Azure Speech, no money: it uses the free 5 h a month (not counted in the app's counter)",
            f"about {sum(seconds):.0f} s of WAV audio to send; missing audio: {', '.join(missing) or 'none'}",
        ],
    )


def run(tracker: Any, the_plan: Plan, repeats: int = 1, limit: int | None = None, log=print) -> dict[str, Any]:  # noqa: ANN001, ARG001
    cases = load_cases()[:limit] if limit else load_cases()
    run_id, started = new_run_id(), now_iso()
    rows: list[dict[str, Any]] = []
    try:
        provider = AzurePronunciationProvider()
    except PronunciationError as exc:  # not configured: every case fails with the same reason, none is dropped
        provider, setup_error = None, f"{type(exc).__name__}: {exc}"
    for case in cases:
        audio = find_audio(case)
        row: dict[str, Any] = {"id": case["id"], "audio": audio.name if audio else None}
        if audio is None:
            row.update(failure="no_audio")
        elif provider is None:
            row.update(failure="auth", error=setup_error)
        else:
            attempt = with_retries(lambda a=audio, c=case: provider.score_turn(str(a), c["text"]), classify)
            row["attempts"] = attempt.attempts
            if attempt.ok:
                by_word = {_word(w.word): w.accuracy for w in attempt.value.words}
                targets = {t: by_word.get(_word(t)) for t in case["target_words"]}
                row.update(
                    pron_score=attempt.value.pron_score,
                    target_scores=targets,
                    hit=all(s is not None and s < HARD_WORD_THRESHOLD for s in targets.values()),
                    words=[{"word": w.word, "accuracy": w.accuracy} for w in attempt.value.words],
                )
            else:
                row.update(failure=attempt.failure, error=attempt.error)
        rows.append(row)
        log(f"  {case['id']} " + (f"FAILED ({row['failure']})" if row.get("failure") else f"hit={row['hit']} targets={row['target_scores']}"))

    scored = [r for r in rows if not r.get("failure")]
    metrics = {
        "cases_scored": len(scored),
        "hits": sum(r["hit"] for r in scored),
        "hit_rate": round(sum(r["hit"] for r in scored) / len(scored), 4) if scored else None,
        # Per word: a case usually has two target words and the speaker may have missed only one of them on purpose.
        "target_words": sum(len(r["target_scores"]) for r in scored),
        "target_words_flagged": sum(1 for r in scored for v in r["target_scores"].values() if v is not None and v < HARD_WORD_THRESHOLD),
        "hard_word_threshold": HARD_WORD_THRESHOLD,
    }
    return base_result(
        "pronunciation", run_id, started, the_plan, rows,
        prompt_version=None, provider="azure", actual_cost_usd=0.0, served_by={"azure": len(scored)}, metrics=metrics,
    )  # fmt: skip


def describe(result: dict[str, Any]) -> list[str]:
    m = result["metrics"]
    if not m["cases_scored"]:
        return ["NOT MEASURED: no case could be scored."]
    return [
        f"Azure Speech, threshold {m['hard_word_threshold']:.0f}: {m['hits']}/{m['cases_scored']} cases with EVERY target word flagged; "
        f"{m['target_words_flagged']}/{m['target_words']} target words flagged",
    ]
