"""Estimated cost in USD of each provider call.

Accuracy, call by call (this is our estimate, not OpenAI's invoice):
- LLM: tokens as the API reports them x the price per million. As exact as the price table.
- Speech to text: seconds of audio x the price per minute. Exact for per-minute billing.
- Text to speech: the speech API reports no usage, so it is the generated audio's length x the price per
  minute x ``tts_cost_safety_factor``. Within roughly +-30 %, pessimistic on purpose.
Free providers (Groq, Gemini) cost 0 here: their limits are quotas, tracked by the daily counters.
"""

from app.config import Settings
from app.providers.types import Usage

PAID_PROVIDERS = frozenset({"openai"})
# English speech is about 15 characters a second: only used to guess a text-to-speech call's cost before it happens.
_CHARS_PER_SECOND = 15.0
_ESTIMATED_COMPLETION_TOKENS = 600
_ESTIMATED_STT_SECONDS = 30.0


def is_paid(provider: str) -> bool:
    return provider in PAID_PROVIDERS


class Pricing:
    def __init__(self, cfg: Settings) -> None:
        self._cfg = cfg

    def cost(self, provider: str, capability: str, usage: Usage) -> float:
        """What a finished call cost."""
        if not is_paid(provider) or usage.from_cache:
            return 0.0
        cfg = self._cfg
        if capability == "llm":
            return (
                usage.prompt_tokens * cfg.price_openai_llm_input_per_m + usage.completion_tokens * cfg.price_openai_llm_output_per_m
            ) / 1_000_000
        if capability == "stt":
            return usage.audio_seconds_in / 60 * cfg.price_openai_stt_per_minute
        return usage.audio_seconds_out / 60 * cfg.price_openai_tts_per_minute * cfg.tts_cost_safety_factor

    # --- before the call, to keep a big one from overshooting the budget ---------------------------

    def estimate_llm(self, provider: str, prompt_chars: int) -> float:
        usage = Usage(prompt_tokens=prompt_chars // 4, completion_tokens=_ESTIMATED_COMPLETION_TOKENS)
        return self.cost(provider, "llm", usage)

    def estimate_stt(self, provider: str) -> float:
        return self.cost(provider, "stt", Usage(audio_seconds_in=_ESTIMATED_STT_SECONDS))

    def estimate_tts(self, provider: str, text: str) -> float:
        return self.cost(provider, "tts", Usage(audio_seconds_out=len(text) / _CHARS_PER_SECOND))
