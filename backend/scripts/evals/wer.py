"""Speech-to-text eval: word error rate (WER) of the app's recognizer on evals/audio/latency/*.ogg.

Each audio of manifest.csv is transcribed by the app's own STT chain (the router: Groq Whisper first, OpenAI as the
paid backup) and compared with the manifest's ``text`` using jiwer. WER = (substitutions + deletions + insertions)
/ words in the reference. The global WER pools every word of every audio (not the mean of the per-audio WERs, which
would let a 4-word audio weigh as much as a 30-word one).

NORMALIZATION. Applied to the reference AND the transcript alike, in this order (``normalize``):
1. Accents and other diacritics are dropped: "Medellín" == "Medellin" (Whisper writes either; not a recognition error).
2. Lower case; curly apostrophes become straight ones.
3. Contractions are expanded, so "don't" == "do not" and "I'm" == "I am": both are the same words said.
   n't -> " not" (can't -> "can not", won't -> "will not"), 'm -> am, 're -> are, 've -> have, 'll -> will,
   'd -> would (it can also be "had": the one ambiguous case, accepted because both sides are expanded alike),
   's -> is ONLY after it/he/she/that/what/there/here/who/where/how/let's (-> let us); any other 's is a possessive
   and only loses the apostrophe ("John's" -> "johns").
4. Numbers become words, so "3" == "three": integers up to 9999 and clock times ("8:30" -> "eight thirty",
   "9:00" -> "nine"). Ordinals, decimals and money are NOT converted (the references have none).
5. Hyphens and slashes separate words ("eight-thirty" -> "eight thirty"); every other punctuation mark is removed.
6. Filler words (um, uh, er, hmm...) are removed: the references only hold the intended words.
NOT normalized: British/American spelling ("favourite" vs "favorite") and compound words written apart
("someday" vs "some day"): both count as errors.

The WER without normalization (jiwer on the raw texts) is reported too, only to show how much the rules change it.

FAIRNESS. manifest.csv says who recorded each audio (``speaker``) and their accent (``accent``); the WER is also given
per accent and per speaker. With a single speaker it CANNOT say whether the recognizer is fair to Latin American
accents: the report says so instead of comparing.
"""

import csv
import re
import unicodedata
from pathlib import Path
from typing import Any

import jiwer

from app.analysis.judge import FILLER_WORDS
from app.providers import chains
from scripts.evals.common import (
    EVALS_DIR,
    Plan,
    Tracker,
    base_result,
    classify_stt_failure,
    new_run_id,
    now_iso,
    served_by,
    stt_cost,
    with_retries,
)

AUDIO_DIR = EVALS_DIR / "audio" / "latency"
MANIFEST = AUDIO_DIR / "manifest.csv"
# Upper bound used for the cost estimate when an audio's length is unknown (OGG files are not parsed here).
ESTIMATED_SECONDS_PER_AUDIO = 30.0

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_IS_AFTER = {"it", "he", "she", "that", "what", "there", "here", "who", "where", "how"}
_CONTRACTIONS = [
    (r"\bcan't\b", "can not"),
    (r"\bwon't\b", "will not"),
    (r"\bshan't\b", "shall not"),
    (r"\blet's\b", "let us"),
    (r"n't\b", " not"),
    (r"'m\b", " am"),
    (r"'re\b", " are"),
    (r"'ve\b", " have"),
    (r"'ll\b", " will"),
    (r"'d\b", " would"),
]


def number_to_words(n: int) -> str:
    """0..9999 in words, the way they are usually said ("one thousand two hundred five")."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_ONES[hundreds]} hundred" + (f" {number_to_words(rest)}" if rest else "")
    thousands, rest = divmod(n, 1000)
    return f"{number_to_words(thousands)} thousand" + (f" {number_to_words(rest)}" if rest else "")


def _time_to_words(match: re.Match[str]) -> str:
    hour, minute = int(match.group(1)), int(match.group(2))
    if minute == 0:
        return number_to_words(hour)
    return f"{number_to_words(hour)} {'oh ' + _ONES[minute] if minute < 10 else number_to_words(minute)}"


def normalize(text: str) -> str:
    """The normalization described in the module docstring. Same function for the reference and the transcript."""
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'").replace("‘", "'")
    for pattern, replacement in _CONTRACTIONS:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"\b(\w+)'s\b", lambda m: f"{m.group(1)} is" if m.group(1) in _IS_AFTER else f"{m.group(1)}s", text)
    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", _time_to_words, text)
    text = re.sub(r"\b\d{1,4}\b", lambda m: number_to_words(int(m.group(0))), text)
    text = re.sub(r"[-/]", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    words = [w for w in text.split() if w not in FILLER_WORDS]
    return " ".join(words)


def load_manifest(path: Path = MANIFEST) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {
                "file": r["file"].strip(),
                "text": r["text"].strip(),
                "condition": (r.get("condition") or "").strip(),
                "speaker": (r.get("speaker") or "").strip() or "unknown",
                "accent": (r.get("accent") or "").strip() or "unknown",
            }
            for r in csv.DictReader(handle)
        ]


def unlisted_audio(rows: list[dict[str, str]], audio_dir: Path = AUDIO_DIR) -> list[str]:
    """Audio files in the folder that the manifest does not list (they have no reference, so they are not used)."""
    listed = {r["file"] for r in rows}
    return sorted(p.name for p in audio_dir.iterdir() if p.suffix.lower() in {".ogg", ".wav", ".m4a", ".mp3", ".webm"} and p.name not in listed)


def measure(pairs: list[tuple[str, str]]) -> dict[str, Any] | None:
    """Pooled WER (and its parts) of (reference, transcript) pairs, both already normalized. None if empty."""
    pairs = [(r, h) for r, h in pairs if r]
    if not pairs:
        return None
    out = jiwer.process_words([r for r, _ in pairs], [h for _, h in pairs])
    words = out.hits + out.substitutions + out.deletions
    return {
        "audios": len(pairs),
        "reference_words": words,
        "wer": round(out.wer, 4),
        "substitutions": out.substitutions,
        "deletions": out.deletions,
        "insertions": out.insertions,
    }


def _group(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        groups.setdefault(r[key], []).append((r["reference_norm"], r["transcript_norm"]))
    return {name: measure(pairs) for name, pairs in sorted(groups.items())}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    done = [r for r in rows if not r.get("failure")]
    for r in done:
        r["length"], _, r["noise"] = r["condition"].partition("_")
    metrics: dict[str, Any] = {
        "global": measure([(r["reference_norm"], r["transcript_norm"]) for r in done]),
        "global_raw": (
            {"wer": round(jiwer.wer([r["reference"] for r in done], [r["transcript"] for r in done]), 4)} if done else None
        ),
        "by_condition": _group(done, "condition"),
        "by_noise": _group(done, "noise"),
        "by_length": _group(done, "length"),
        "by_accent": _group(done, "accent"),
        "by_speaker": _group(done, "speaker"),
    }
    speakers, accents = {r["speaker"] for r in rows}, {r["accent"] for r in rows}
    if len(speakers) < 2 or len(accents) < 2:
        metrics["fairness_note"] = (
            f"{len(speakers)} speaker(s) and {len(accents)} accent(s) ({', '.join(sorted(accents))}): the WER cannot be "
            "compared across accents. It shows how the recognizer does with this voice, not whether it is fair to Latin "
            "American accents; that needs recordings by several speakers with different accents (and native ones as a baseline)."
        )
    return metrics


def plan(cfg: Any, repeats: int = 1, limit: int | None = None) -> Plan:
    rows = load_manifest()[:limit] if limit else load_manifest()
    missing = [r["file"] for r in rows if not (AUDIO_DIR / r["file"]).is_file()]
    return Plan(
        "wer",
        calls=len(rows) * repeats,
        estimated_cost_usd=stt_cost(cfg, ESTIMATED_SECONDS_PER_AUDIO * len(rows) * repeats),
        notes=[
            f"{len(rows)} audios, STT order '{cfg.stt_order}' (Groq {cfg.stt_model} first, free); estimate assumes OpenAI answers all, {ESTIMATED_SECONDS_PER_AUDIO:.0f} s each",
            f"missing audio: {', '.join(missing) or 'none'}; not in the manifest (ignored): {', '.join(unlisted_audio(rows)) or 'none'}",
        ],
    )


def run(tracker: Tracker, the_plan: Plan, repeats: int = 1, limit: int | None = None, log=print) -> dict[str, Any]:  # noqa: ANN001, ARG001
    manifest = load_manifest()[:limit] if limit else load_manifest()
    stt = chains.build_stt(tracker.cfg, tracker.state)
    run_id, started = new_run_id(), now_iso()
    rows: list[dict[str, Any]] = []
    for item in manifest:
        audio = AUDIO_DIR / item["file"]
        row: dict[str, Any] = {**item, "reference": item["text"], "reference_norm": normalize(item["text"])}
        del row["text"]
        if not audio.is_file():
            row.update(failure="no_audio")
        else:
            attempt = with_retries(lambda a=audio: stt.transcribe(str(a)), classify_stt_failure)
            row.update(attempts=attempt.attempts, served_by=served_by(tracker.collect()))
            if attempt.ok:
                row["transcript"] = attempt.value.text.strip()
                row["transcript_norm"] = normalize(row["transcript"])
                one = measure([(row["reference_norm"], row["transcript_norm"])])
                row.update(wer=one["wer"] if one else None, substitutions=one and one["substitutions"], deletions=one and one["deletions"], insertions=one and one["insertions"])
            else:
                row.update(failure=attempt.failure, error=attempt.error)
        rows.append(row)
        log(f"  {item['file']} " + (f"FAILED ({row['failure']})" if row.get("failure") else f"WER {row['wer']:.0%}  heard: {row['transcript']}"))

    return base_result(
        "wer", run_id, started, the_plan, rows,
        prompt_version=None,
        stt_model_setting=tracker.cfg.stt_model,
        normalization="scripts/evals/wer.py normalize(): diacritics, case, contractions, numbers, punctuation, fillers",
        unlisted_audio=unlisted_audio(manifest),
        metrics=summarize(rows),
        **tracker.summary(),
    )  # fmt: skip


def describe(result: dict[str, Any]) -> list[str]:
    m = result["metrics"]
    if m["global"] is None:
        return ["NOT MEASURED: no audio could be transcribed."]
    g = m["global"]
    lines = [
        f"global WER {g['wer']:.1%} over {g['reference_words']} words in {g['audios']} audios "
        f"(S {g['substitutions']}, D {g['deletions']}, I {g['insertions']}); without normalization {m['global_raw']['wer']:.1%}",
    ]
    for key in ("by_noise", "by_length", "by_accent"):
        lines.append(f"  {key[3:]}: " + ", ".join(f"{k} {v['wer']:.1%} ({v['audios']})" for k, v in m[key].items() if v))
    worst = sorted((r for r in result["rows"] if r.get("wer") is not None), key=lambda r: -r["wer"])[:5]
    worst_text = "; ".join(f"{r['file']} {r['wer']:.0%}" for r in worst if r["wer"] > 0)
    lines.append(f"  worst audios: {worst_text or 'none above 0%'}")
    if m.get("fairness_note"):
        lines.append(f"  NOTE: {m['fairness_note']}")
    return lines
