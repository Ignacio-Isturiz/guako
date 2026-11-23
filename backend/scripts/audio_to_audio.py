"""End-to-end test: user audio -> STT -> LLM tutor reply -> TTS audio file.

Run from backend/:  python -m scripts.audio_to_audio path/to/question.wav
Makes REAL API calls (Groq STT, the configured LLM, Groq TTS). Never run by pytest.
Prints latency per stage; never prints keys.
"""

import argparse
import sys
import time
from pathlib import Path

from app.config import settings
from app.llm.errors import LLMError
from app.llm.factory import get_llm_provider
from app.llm.schemas import TutorReply
from app.stt import GroqWhisperSTTProvider, STTError
from app.tts import CachedTTSProvider, GroqOrpheusTTSProvider, TTSError

TUTOR_SYSTEM_PROMPT = "You are an English tutor. Reply in 1-2 short English sentences."
DEFAULT_OUTPUT = "output/reply.wav"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audio in, tutor audio reply out.")
    parser.add_argument("audio", help="path to the user's recorded audio (wav, mp3, ogg, ...)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"reply WAV path (default: {DEFAULT_OUTPUT})")
    args = parser.parse_args()

    if not Path(args.audio).is_file():
        print(f"Audio file not found: {args.audio}", file=sys.stderr)
        return 1

    try:
        stt = GroqWhisperSTTProvider()
        llm = get_llm_provider(settings)
        tts = CachedTTSProvider(GroqOrpheusTTSProvider())

        t0 = time.perf_counter()
        transcript = stt.transcribe(args.audio).text
        t1 = time.perf_counter()
        if not transcript:
            print("STT returned an empty transcript (no speech detected?).", file=sys.stderr)
            return 1

        # The prompt asks for English only, so the reply goes to TTS as it is.
        reply = llm.generate(transcript, TutorReply, system=TUTOR_SYSTEM_PROMPT).reply
        t2 = time.perf_counter()

        result = tts.synthesize(reply, args.output)
        t3 = time.perf_counter()
    except (STTError, LLMError, TTSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"You said : {transcript}")
    print(f"Tutor    : {reply}")
    print(f"Audio    : {result.audio_path}\n")
    print(f"{'Stage':<8}{'Seconds':>9}")
    print("-" * 17)
    print(f"{'STT':<8}{t1 - t0:>9.2f}")
    print(f"{'LLM':<8}{t2 - t1:>9.2f}")
    print(f"{'TTS':<8}{t3 - t2:>9.2f}")
    print("-" * 17)
    print(f"{'Total':<8}{t3 - t0:>9.2f}\n")
    print(f"TTS provider: {result.provider} | from cache: {result.from_cache}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
