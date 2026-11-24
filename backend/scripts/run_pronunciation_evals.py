"""Run the pronunciation eval cases against Azure (REAL calls, uses the free monthly audio quota).

Run from backend/:
    python -m scripts.run_pronunciation_evals            # lists what would be sent, sends NOTHING
    python -m scripts.run_pronunciation_evals --yes      # sends the audios

Audio of case ``pr_01`` is looked up in the case's ``audio_file`` (relative to evals/grammar/) or,
if that is null, as evals/grammar/audio/pr_01.{wav,m4a,ogg,webm,mp3} (other formats go through ffmpeg).
Cases without audio are skipped and reported as such: no result is ever invented.

For each case the reference text is the sentence the learner was asked to read, and the question is:
did every ``target_words`` entry score below the "hard word" threshold? (a hit). The audio sent is
printed first, and run only on purpose: seconds sent here are NOT counted in the app's monthly counter,
so they eat into the safety margin. Writes results/evals/pronunciation-<run_id>.jsonl.
"""

import argparse
import json
import re
import uuid
import wave
from datetime import UTC, datetime
from pathlib import Path

from app.pronunciation import AzurePronunciationProvider, PronunciationError
from app.reports import HARD_WORD_THRESHOLD

BACKEND_DIR = Path(__file__).resolve().parents[1]
CASES = BACKEND_DIR / "evals" / "grammar" / "pronunciation_cases.jsonl"
AUDIO_DIR = BACKEND_DIR / "evals" / "grammar" / "audio"
RESULTS_DIR = BACKEND_DIR / "results" / "evals"
EXTENSIONS = (".wav", ".m4a", ".ogg", ".webm", ".mp3")


def normalize(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def find_audio(case: dict) -> Path | None:
    if case.get("audio_file"):
        path = BACKEND_DIR / "evals" / "grammar" / case["audio_file"]
        return path if path.is_file() else None
    for extension in EXTENSIONS:
        path = AUDIO_DIR / f"{case['id']}{extension}"
        if path.is_file():
            return path
    return None


def wav_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="really call Azure (without it nothing is sent)")
    args = parser.parse_args()

    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    plan = [(case, find_audio(case)) for case in cases]
    missing = [case["id"] for case, audio in plan if audio is None]
    print(f"{len(cases) - len(missing)} of {len(cases)} cases have audio. Missing: {', '.join(missing) or 'none'}")
    known = [s for _, audio in plan if audio and (s := wav_seconds(audio)) is not None]
    print(f"WAV audio to send: {sum(known):.0f} s (other formats: length known only after conversion)")
    if not args.yes:
        print("Nothing was sent. Run again with --yes to call Azure.")
        return

    provider = AzurePronunciationProvider()
    results = []
    for case, audio in plan:
        if audio is None:
            results.append({"id": case["id"], "status": "no_audio"})
            continue
        try:
            scored = provider.score_turn(str(audio), case["text"])
        except PronunciationError as exc:
            print(f"{case['id']}: failed ({exc.code})")
            results.append({"id": case["id"], "status": "failed", "error": exc.code})
            continue
        by_word = {normalize(w.word): w.accuracy for w in scored.words}
        targets = {t: by_word.get(normalize(t)) for t in case["target_words"]}
        hit = all(score is not None and score < HARD_WORD_THRESHOLD for score in targets.values())
        print(f"{case['id']}: pron={scored.pron_score} targets={targets} hit={hit}")
        results.append(
            {"id": case["id"], "status": "scored", "pron_score": scored.pron_score, "target_scores": targets, "hit": hit,
             "words": [{"word": w.word, "accuracy": w.accuracy} for w in scored.words]}
        )  # fmt: skip

    scored_cases = [r for r in results if r["status"] == "scored"]
    hits = sum(r["hit"] for r in scored_cases)
    print(f"\nscored={len(scored_cases)} hits={hits} (target words below {HARD_WORD_THRESHOLD:.0f}) no_audio={len(missing)}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    out = RESULTS_DIR / f"pronunciation-{run_id}.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n", encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
