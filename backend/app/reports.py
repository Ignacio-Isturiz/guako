"""End-of-session report: schemas and the aggregation of the per-turn analyses (no I/O, no LLM here).

The analyses themselves are made in the background after each turn (app/analysis) and stored in
``turn_analyses``; the report only reads them.

Grammar score
    score = round(100 * max(0, 1 - errors / words)), over the turns whose analysis is done.
    One error per 10 words → 90; one per 2 words → 50; one per word or worse → 0.
    Only errors above the confidence threshold count (see app/analysis/grammar.py).

Fluency score: formula in app/analysis/fluency.py, computed from the totals of the turns with timings.

Status of a dimension: ``ok`` every turn analysed · ``incomplete`` some turns pending, failed or never
queued (the figures cover the rest) · ``empty`` nothing to measure.

Pronunciation score: the mean Azure word accuracy (0-100) over every assessed word of the turns that
were assessed. Words below HARD_WORD_THRESHOLD are listed as "words that were hard" (``hard_words``).

FAIRNESS RULE for pronunciation. The score compares the learner with a standard-English model, and
Latin American accents will score lower for reasons that are not mistakes. So the report must never
say or imply "wrong accent", "bad accent" or that someone "mispronounces": it only lists the words
that "costaron" (were hard) and always carries the note FAIRNESS_NOTE. Do not rename ``hard_words``
into anything that judges the accent. A test enforces the forbidden phrases.

Communication ("darse a entender") and listening: one LLM judge per turn scores both from 1 to 5 (see
app/analysis/judge.py); the report shows 0-100 = (score - 1) / 4 * 100, averaged over the turns that were judged.
HONESTY RULE: a score the judge was not confident about (JUDGE confidence below MIN_JUDGE_CONFIDENCE, after the cap
for an unreliable transcript) is never shown: that turn counts as "not measured" and the dimension is incomplete.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel

from app.analysis.fluency import LONG_PAUSE_SECONDS, analyze_fluency, fluency_score
from app.enums import AnalysisStatus
from app.stt import WordTiming

__all__ = ["LONG_PAUSE_SECONDS"]

# empty: nothing to measure · incomplete: some turns could not be analysed · pending: not built yet
Status = Literal["ok", "incomplete", "empty", "pending"]


class ReportGrammarError(BaseModel):
    turn_number: int
    original: str
    correction: str
    error_type: str
    explanation: str


class GrammarReport(BaseModel):
    status: Status
    score: int | None
    errors: list[ReportGrammarError]
    turns_analyzed: int
    turns_failed: int
    turns_pending: int = 0  # queued, still running, or never queued (old sessions)


class FluencyReport(BaseModel):
    status: Status
    score: int | None
    words_per_minute: float | None
    long_pauses: int
    filler_words: int
    total_words: int
    # Metrics no turn could provide (e.g. no word timings): their value above is a placeholder, not data.
    unavailable: list[str] = []
    turns_without_timings: int = 0


# Azure is lenient (it rewards being understood, not sounding native): on real sessions the median word
# scored 94. Below 85 is where a learner still has something to work on. Azure's own "mispronounced"
# line is 60, far too forgiving to teach with. The app is meant to be strict so people can really learn.
HARD_WORD_THRESHOLD = 85.0

# Words that are normally said in their weak, reduced form in a sentence ("for" sounds like /fɚ/): a low
# score there is natural English, not something to practise, and said alone they score 100 right away.
# They still count in the score; they are only left out of the list of hard words.
FUNCTION_WORDS = frozenset(
    "a an the and or but nor so if than then that this these those there here of to in on at for from with by as "
    "into onto up out off over about am is are was were be been being do does did have has had will can could "
    "should shall may might must not i you he she it we they me him her us them my your his its our their".split()
)
MAX_HARD_WORDS = 10

# Shown with every pronunciation score (Spanish, like the rest of the API messages).
FAIRNESS_NOTE = (
    "El puntaje de pronunciación se compara contra un modelo de inglés estándar y puede ser injusto "
    "con los acentos latinos. Tómalo como una guía para practicar, no como un veredicto."
)
NO_AUDIO_NOTE = (
    "La pronunciación solo se mide si aceptas guardar tu audio; en esta sesión no hay audio guardado."
)

# Like Status, plus "unavailable": there is nothing to measure for a known reason (see ``reason``).
PronunciationStatus = Literal["ok", "incomplete", "empty", "pending", "unavailable"]
PronunciationReason = Literal["no_audio_consent", "quota", "failed"]


class HardSound(BaseModel):
    ipa: str
    score: int


class PracticeState(BaseModel):
    """Where the learner is in "now you say it" for one word (kept apart from the saved report)."""

    attempts_used: int = 0
    attempts_left: int = 2
    passed: bool = False
    locked: bool = False  # passed, or out of attempts: no more tries
    best_score: int | None = None


class HardWord(BaseModel):
    """A word that cost the learner: low score, never "wrong"."""

    word: str
    score: int
    turn_number: int
    times: int  # how many times it scored below the threshold in the session
    # How the word is said (IPA, no stress marks) and the sounds of its lowest-scoring occurrence, so the
    # report can show where it cost. Empty for reports saved before this field existed.
    ipa: str = ""
    sounds: list[HardSound] = []
    weakest_sound: int | None = None  # index in ``sounds`` of the sound that cost the most
    practice: PracticeState | None = None  # filled in when the report is served, never saved with it


class HeardFix(BaseModel):
    """A word the recognizer wrote that was scored as another word that sounds alike ("to die" -> "today")."""

    turn_number: int
    heard: str
    intended: str


class PronunciationReport(BaseModel):
    # Defaults match the old placeholder, so reports saved before this dimension existed still load.
    status: PronunciationStatus = "pending"
    score: int | None = None
    hard_words: list[HardWord] = []
    heard_fixes: list[HeardFix] = []
    turns_analyzed: int = 0
    turns_pending: int = 0
    turns_failed: int = 0
    turns_without_audio: int = 0
    turns_over_quota: int = 0
    turns_partial: int = 0  # long turns: only the first seconds were assessed
    reason: PronunciationReason | None = None  # why there is no score (status "unavailable")
    notes: list[str] = []


JudgeStatus = Literal["ok", "incomplete", "empty", "pending"]


class JudgedTurn(BaseModel):
    turn_number: int
    score: int  # 1-5, as the judge gave it
    rationale: str


class JudgeReport(BaseModel):
    """A dimension scored by the LLM judge. The defaults match the old placeholder, so saved reports still load."""

    status: JudgeStatus = "pending"
    score: int | None = None  # 0-100
    turns_judged: int = 0
    turns_hidden: int = 0  # the judge was not confident enough: not shown (honesty rule)
    turns_failed: int = 0
    turns_pending: int = 0
    turns_trivial: int = 0  # too short to judge ("yes", "me too")
    turns_without_context: int = 0  # listening: no previous message from the tutor
    turns_asked_to_repeat: int = 0  # listening: the learner asked to repeat or explain (a request, not scored)
    turns: list[JudgedTurn] = []
    notes: list[str] = []


class SessionReport(BaseModel):
    session_id: int
    user_turns: int
    grammar: GrammarReport
    fluency: FluencyReport
    pronunciation: PronunciationReport = PronunciationReport()
    communication: JudgeReport = JudgeReport()
    listening: JudgeReport = JudgeReport()


def count_words(text: str) -> int:
    return len(text.split())


def grammar_score(errors: int, words: int) -> int | None:
    if words <= 0:
        return None
    return round(100 * max(0.0, 1 - errors / words))


def _turn_status(row: object | None) -> str:
    """Status of an analysis row; a turn that was never queued counts as pending."""
    return getattr(row, "status", AnalysisStatus.PENDING.value)


def build_grammar_report(turns: Sequence[tuple[int, str]], rows: Mapping[int, object | None]) -> GrammarReport:
    """``turns`` = (turn_number, transcript); ``rows`` = the grammar analysis row of each turn_number."""
    errors: list[ReportGrammarError] = []
    analyzed = failed = pending = analyzed_words = 0
    for number, transcript in turns:
        row = rows.get(number)
        status = _turn_status(row)
        if status == AnalysisStatus.DONE.value:
            analyzed += 1
            analyzed_words += count_words(transcript)
            errors.extend(
                ReportGrammarError(turn_number=number, **{k: e[k] for k in ("original", "correction", "error_type", "explanation")})
                for e in (row.result or {}).get("errors", [])  # type: ignore[union-attr]
            )
        elif status == AnalysisStatus.FAILED.value:
            failed += 1
        else:
            pending += 1
    return GrammarReport(
        status="incomplete" if failed or pending else "ok",
        score=grammar_score(len(errors), analyzed_words) if analyzed else None,
        errors=errors,
        turns_analyzed=analyzed,
        turns_failed=failed,
        turns_pending=pending,
    )


def build_fluency_report(results: Sequence[dict | None]) -> FluencyReport:
    """``results`` = the stored result of each user turn's fluency analysis (None = not done)."""
    done = [r for r in results if r is not None]
    timed = [r for r in done if r["metrics"]["words_per_minute"]["status"] == "ok"]
    total_words = sum(r["total_words"] for r in timed)
    seconds = sum(r["speaking_seconds"] for r in timed)
    pauses = sum(r["metrics"]["long_pauses"]["value"] for r in timed)
    fillers = sum(r["metrics"]["filler_words"]["value"] for r in timed)
    unavailable = [] if timed else ["words_per_minute", "long_pauses", "filler_words"]
    missing = len(results) - len(done)

    if not timed:
        return FluencyReport(
            status="incomplete" if missing else "empty",
            score=None,
            words_per_minute=None,
            long_pauses=0,
            filler_words=0,
            total_words=0,
            unavailable=unavailable,
            turns_without_timings=len(done),
        )
    minutes = seconds / 60
    wpm = total_words / minutes
    return FluencyReport(
        status="incomplete" if missing else "ok",
        score=fluency_score(wpm, pauses / minutes, fillers / total_words),
        words_per_minute=round(wpm, 1),
        long_pauses=pauses,
        filler_words=fillers,
        total_words=total_words,
        turns_without_timings=len(done) - len(timed),
    )


def _hard_word(word: str, score: float, turn_number: int, phonemes: list[dict], times: int) -> HardWord:
    sounds = [HardSound(ipa=p.get("ipa") or p["phoneme"], score=round(p["accuracy"])) for p in phonemes]
    weakest = min(range(len(sounds)), key=lambda i: sounds[i].score) if sounds else None
    return HardWord(
        word=word,
        score=round(score),
        turn_number=turn_number,
        times=times,
        ipa="".join(s.ipa for s in sounds),
        sounds=sounds,
        weakest_sound=weakest,
    )


def build_pronunciation_report(rows: Sequence[tuple[int, object | None]]) -> PronunciationReport:
    """``rows`` = (turn_number, pronunciation analysis row or None if never queued), one per user turn."""
    counts = {"done": 0, "pending": 0, "failed": 0, "no_audio": 0, "quota": 0}
    partial = 0
    words_seen = 0
    total = 0.0
    fixes: list[HeardFix] = []
    worst: dict[str, tuple[float, int, list]] = {}  # lowercased word -> (lowest score, turn, its phonemes)
    times: dict[str, int] = {}
    shown: dict[str, str] = {}
    for turn_number, row in rows:
        status = _turn_status(row)
        result = getattr(row, "result", None) or {}
        if status == AnalysisStatus.DONE.value:
            words = result.get("words", [])
            if not words:
                continue  # said nothing: not a turn to measure
            counts["done"] += 1
            partial += bool(result.get("truncated"))
            fixes.extend(HeardFix(turn_number=turn_number, **f) for f in result.get("heard_fixes", []))
            for w in words:
                score = float(w["accuracy"])
                words_seen += 1
                total += score
                key = re.sub(r"[^\w']", "", w["word"].lower())
                if score < HARD_WORD_THRESHOLD and key not in FUNCTION_WORDS:
                    times[key] = times.get(key, 0) + 1
                    if key not in worst or score < worst[key][0]:
                        worst[key], shown[key] = (score, turn_number, w.get("phonemes") or []), w["word"]
        elif status == AnalysisStatus.FAILED.value:
            counts["failed"] += 1
        elif status == AnalysisStatus.SKIPPED_NO_AUDIO.value:
            counts["no_audio"] += 1
        elif status == AnalysisStatus.SKIPPED_QUOTA.value:
            counts["quota"] += 1
        else:
            counts["pending"] += 1

    hard = sorted(worst, key=lambda k: (worst[k][0], k))[:MAX_HARD_WORDS]
    common = {
        "turns_analyzed": counts["done"],
        "turns_pending": counts["pending"],
        "turns_failed": counts["failed"],
        "turns_without_audio": counts["no_audio"],
        "turns_over_quota": counts["quota"],
        "turns_partial": partial,
    }
    if not counts["done"]:
        if counts["pending"]:
            return PronunciationReport(status="pending", **common)
        if not any(counts[k] for k in ("failed", "no_audio", "quota")):
            return PronunciationReport(status="empty", **common)
        if counts["quota"]:
            reason, note = "quota", "No se pudo medir la pronunciación: se alcanzó el límite mensual gratuito del servicio."
        elif counts["failed"]:
            reason, note = "failed", "No se pudo medir la pronunciación de esta sesión por un problema del servicio."
        else:
            reason, note = "no_audio_consent", NO_AUDIO_NOTE
        return PronunciationReport(status="unavailable", reason=reason, notes=[note], **common)

    notes = [FAIRNESS_NOTE]
    if partial:
        notes.append(f"En {partial} turno(s) largo(s) solo se evaluaron los primeros segundos de audio.")
    if counts["no_audio"]:
        notes.append(f"{counts['no_audio']} turno(s) no se midieron porque no hay audio guardado.")
    if counts["quota"]:
        notes.append(f"{counts['quota']} turno(s) no se midieron: se alcanzó el límite mensual gratuito del servicio.")
    incomplete = counts["pending"] or counts["failed"] or counts["no_audio"] or counts["quota"]
    return PronunciationReport(
        status="incomplete" if incomplete else "ok",
        score=round(total / words_seen),
        hard_words=[_hard_word(shown[k], *worst[k], times[k]) for k in hard],
        heard_fixes=fixes,
        notes=notes,
        **common,
    )


def build_judge_report(rows: Sequence[tuple[int, object | None]]) -> JudgeReport:
    """``rows`` = (turn_number, the analysis row of one judge dimension, or None if never queued), one per user turn."""
    counts = {"judged": 0, "hidden": 0, "failed": 0, "pending": 0, "trivial": 0, "no_context": 0, "repeat": 0}
    shown: list[JudgedTurn] = []
    for turn_number, row in rows:
        status = _turn_status(row)
        result = getattr(row, "result", None) or {}
        if status == AnalysisStatus.DONE.value:
            if result.get("asked_to_repeat"):
                counts["repeat"] += 1
            elif result.get("hidden"):
                counts["hidden"] += 1
            elif result.get("score") is not None:
                counts["judged"] += 1
                shown.append(JudgedTurn(turn_number=turn_number, score=int(result["score"]), rationale=str(result.get("rationale", ""))))
        elif status == AnalysisStatus.FAILED.value:
            counts["failed"] += 1
        elif status == AnalysisStatus.SKIPPED_TRIVIAL.value:
            counts["trivial"] += 1
        elif status == AnalysisStatus.SKIPPED_NO_CONTEXT.value:
            counts["no_context"] += 1
        else:
            counts["pending"] += 1

    notes: list[str] = []
    if counts["hidden"]:
        notes.append(f"{counts['hidden']} turno(s) no se cuentan: la evaluación no tuvo suficiente confianza para mostrarte un puntaje.")
    if counts["repeat"]:
        notes.append(f"Pediste repetir o aclarar {counts['repeat']} vez/veces: eso no baja tu puntaje.")
    if counts["trivial"]:
        notes.append(f"{counts['trivial']} respuesta(s) muy corta(s) no se evaluaron.")
    common = {
        "turns_judged": counts["judged"],
        "turns_hidden": counts["hidden"],
        "turns_failed": counts["failed"],
        "turns_pending": counts["pending"],
        "turns_trivial": counts["trivial"],
        "turns_without_context": counts["no_context"],
        "turns_asked_to_repeat": counts["repeat"],
        "turns": shown,
        "notes": notes,
    }
    unmeasured = counts["hidden"] or counts["failed"] or counts["pending"]
    if not counts["judged"]:
        status = "pending" if counts["pending"] else ("incomplete" if unmeasured else "empty")
        return JudgeReport(status=status, **common)
    score = round(sum((t.score - 1) / 4 * 100 for t in shown) / len(shown))
    return JudgeReport(status="incomplete" if unmeasured else "ok", score=score, **common)


def compute_fluency(turns_words: Sequence[Sequence[WordTiming]]) -> FluencyReport:
    """Fluency straight from word timings (analyse each turn, then aggregate)."""
    return build_fluency_report([analyze_fluency(words) for words in turns_words])
