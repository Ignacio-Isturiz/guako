"""End-to-end test: user audio -> STT -> LLM tutor reply -> TTS audio file.

Run from backend/:  python -m scripts.audio_to_audio path/to/question.wav
Makes REAL API calls (Groq STT, the configured LLM, Groq TTS). Never run by pytest.
Prints latency per stage; never prints keys.
"""

import argparse
import sys
from pathlib import Path

from app.config import settings
from app.llm.errors import LLMError
from app.llm.factory import get_llm_provider
from app.stt import GroqWhisperSTTProvider, STTError
from app.tts import CachedTTSProvider, GroqOrpheusTTSProvider, TTSError
from scripts.audio_pipeline import TurnResult, run_turn

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

        turn = TurnResult()
        run_turn(stt, llm, tts, args.audio, args.output, result=turn)
    except (STTError, LLMError, TTSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"You said : {turn.transcript}")
    print(f"Tutor    : {turn.reply}")
    print(f"Audio    : {turn.audio_path}\n")
    print(f"{'Stage':<8}{'Seconds':>9}")
    print("-" * 17)
    print(f"{'STT':<8}{(turn.stt_ms or 0) / 1000:>9.2f}")
    print(f"{'LLM':<8}{(turn.llm_ms or 0) / 1000:>9.2f}")
    print(f"{'TTS':<8}{(turn.tts_ms or 0) / 1000:>9.2f}")
    print("-" * 17)
    print(f"{'Total':<8}{(turn.total_ms or 0) / 1000:>9.2f}\n")
    print(f"TTS provider: {tts.name} | from cache: {turn.from_cache}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
