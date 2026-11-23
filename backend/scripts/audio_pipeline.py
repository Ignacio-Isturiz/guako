"""One audio turn (STT -> LLM -> TTS), shared by the demo and latency scripts."""

import time
from dataclasses import dataclass

from app.llm.base import LLMProvider
from app.llm.schemas import TutorReply
from app.stt import STTError, STTProvider
from app.tts import TTSProvider

TUTOR_SYSTEM_PROMPT = "You are an English tutor. Reply in 1-2 short English sentences."


@dataclass
class TurnResult:
    """Outcome of one turn. Filled progressively so a failure keeps earlier stages."""

    transcript: str = ""
    reply: str = ""
    stt_ms: float | None = None
    llm_ms: float | None = None
    tts_ms: float | None = None
    total_ms: float | None = None
    from_cache: bool | None = None
    audio_path: str | None = None


def run_turn(
    stt: STTProvider,
    llm: LLMProvider,
    tts: TTSProvider,
    audio_path: str,
    output_path: str,
    *,
    tts_text: str | None = None,
    result: TurnResult | None = None,
) -> TurnResult:
    """Run STT -> LLM -> TTS and time each stage.

    ``tts_text`` replaces the LLM reply as TTS input (the LLM still runs and is
    timed); the latency script uses it to force a TTS cache hit.
    Pass ``result`` to keep partial timings when a stage raises.
    Raises STTError, LLMError or TTSError.
    """
    out = result if result is not None else TurnResult()
    t0 = time.perf_counter()
    try:
        out.transcript = stt.transcribe(audio_path).text
    finally:
        t1 = time.perf_counter()
        out.stt_ms = (t1 - t0) * 1000
    if not out.transcript:
        raise STTError("STT returned an empty transcript (no speech detected?)")

    # The prompt asks for English only, so the reply goes to TTS as it is.
    try:
        out.reply = llm.generate(out.transcript, TutorReply, system=TUTOR_SYSTEM_PROMPT).reply
    finally:
        t2 = time.perf_counter()
        out.llm_ms = (t2 - t1) * 1000

    try:
        tts_result = tts.synthesize(tts_text or out.reply, output_path)
    finally:
        t3 = time.perf_counter()
        out.tts_ms = (t3 - t2) * 1000
    out.total_ms = (t3 - t0) * 1000
    out.from_cache = tts_result.from_cache
    out.audio_path = tts_result.audio_path
    return out
