"""Manual smoke test: makes a REAL call to Azure Speech (Pronunciation Assessment, REST short audio).

Run from backend/:
    python -m scripts.azure_pronunciation_smoke evals/grammar/audio/pr_01.wav "I think the weather is nice today."

Never run by pytest. The key is read from .env (AZURE_SPEECH_KEY) and is never printed.
The WAV must be PCM 16 kHz mono and shorter than 30 s (Azure's limit for pronunciation assessment).
"""

import argparse
import base64
import json
import sys
import wave
from pathlib import Path

import httpx

from app.config import settings

PATH = "/speech/recognition/conversation/cognitiveservices/v1"
MAX_SECONDS = 30.0


def candidate_urls(region: str) -> list[tuple[str, str]]:
    """Regional speech host first, then the generic regional host with the same path."""
    query = "?language=en-US&format=detailed"
    return [
        ("regional-stt", f"https://{region}.stt.speech.microsoft.com{PATH}{query}"),
        ("generic", f"https://{region}.api.cognitive.microsoft.com{PATH}{query}"),
    ]


def check_wav(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            sys.exit("The WAV must be PCM 16-bit, 16 kHz, mono.")
        seconds = wav.getnframes() / wav.getframerate()
    if seconds >= MAX_SECONDS:
        sys.exit(f"Audio lasts {seconds:.1f}s; pronunciation assessment accepts less than {MAX_SECONDS:.0f}s.")
    return seconds


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", type=Path)
    parser.add_argument("reference_text")
    parser.add_argument("--save", type=Path, help="write the raw JSON response here (test fixture)")
    args = parser.parse_args()

    if settings.azure_speech_key is None or not settings.azure_speech_region:
        sys.exit("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION must be set in .env.")
    seconds = check_wav(args.wav)

    assessment = {
        "ReferenceText": args.reference_text,
        "GradingSystem": "HundredMark",
        "Granularity": "Phoneme",
        "Dimension": "Comprehensive",
    }
    headers = {
        "Ocp-Apim-Subscription-Key": settings.azure_speech_key.get_secret_value(),
        "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
        "Accept": "application/json",
        "Pronunciation-Assessment": base64.b64encode(json.dumps(assessment).encode("utf-8")).decode("ascii"),
    }
    body = args.wav.read_bytes()
    print(f"audio={args.wav.name} seconds={seconds:.2f} region={settings.azure_speech_region}")

    for name, url in candidate_urls(settings.azure_speech_region):
        print(f"\n== endpoint: {name} ({url.split('?')[0]})")
        try:
            response = httpx.post(url, headers=headers, content=body, timeout=30.0)
        except httpx.HTTPError as exc:
            print(f"request failed: {type(exc).__name__}: {exc}")
            continue
        print(f"HTTP {response.status_code}")
        if response.status_code in (401, 404):
            print(f"full body: {response.text}")
            continue  # try the next host
        if args.save and response.status_code == 200:
            text = json.dumps(response.json(), indent=2, ensure_ascii=False)
            args.save.write_text(text + "\n", encoding="utf-8")
            print(f"raw response saved to {args.save}")
        report(response)
        return
    sys.exit("No endpoint worked.")


def report(response: httpx.Response) -> None:
    try:
        data = response.json()
    except ValueError:
        print(f"full body (not JSON): {response.text}")
        return
    if response.status_code != 200 or data.get("RecognitionStatus") != "Success":
        print("full response:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    best = data["NBest"][0]
    print(f"RecognitionStatus={data['RecognitionStatus']} Display={best.get('Display')!r}")
    totals = {k: best.get(k) for k in ("AccuracyScore", "FluencyScore", "CompletenessScore", "PronScore", "ProsodyScore")}
    print(f"totals: {totals}")
    for word in best.get("Words", []):
        score = word.get("AccuracyScore", (word.get("PronunciationAssessment") or {}).get("AccuracyScore"))
        error = word.get("ErrorType", (word.get("PronunciationAssessment") or {}).get("ErrorType"))
        print(f"word {word.get('Word')!r}: accuracy={score} error={error}")
        for phoneme in word.get("Phonemes", []):
            p_score = phoneme.get("AccuracyScore", (phoneme.get("PronunciationAssessment") or {}).get("AccuracyScore"))
            print(f"    phoneme {phoneme.get('Phoneme')!r}: accuracy={p_score}")
    if not any(w.get("Phonemes") for w in best.get("Words", [])):
        print("(the response has no per-phoneme scores)")
    print("\nfull response:")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
