"""Whisper's ``verbose_json`` answer (the same shape on Groq and on OpenAI) to our own TranscriptionResult."""

import math
from typing import Any

from pydantic import ValidationError

from app.stt.errors import STTError
from app.stt.schemas import TranscriptionResult, WordTiming


def _segment_confidence(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    """(exp of the average log-probability weighted by length, highest no-speech probability) over the segments."""
    segments = [s for s in payload.get("segments") or [] if isinstance(s, dict) and s.get("avg_logprob") is not None]
    if not segments:
        return None, None
    weights = [max(float(s.get("end", 0)) - float(s.get("start", 0)), 0.01) for s in segments]
    mean_logprob = sum(float(s["avg_logprob"]) * w for s, w in zip(segments, weights, strict=True)) / sum(weights)
    no_speech = [float(s["no_speech_prob"]) for s in segments if s.get("no_speech_prob") is not None]
    return round(min(math.exp(mean_logprob), 1.0), 4), (round(max(no_speech), 4) if no_speech else None)


def to_result(payload: dict[str, Any], provider: str) -> TranscriptionResult:
    try:
        confidence, no_speech_prob = _segment_confidence(payload)
        words = [
            WordTiming(
                word=str(item["word"]),
                start=float(item["start"]),
                end=float(item["end"]),
                confidence=None,  # Whisper does not return per-word confidence.
            )
            for item in payload.get("words") or []
        ]
        return TranscriptionResult(
            text=str(payload.get("text", "")).strip(),
            language=payload.get("language"),
            duration=float(payload["duration"]) if payload.get("duration") is not None else None,
            words=words,
            confidence=confidence,
            no_speech_prob=no_speech_prob,
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise STTError(f"{provider} returned an unexpected transcription format") from exc
