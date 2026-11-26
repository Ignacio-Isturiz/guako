from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_order(value: str) -> list[str]:
    return [name.strip().lower() for name in value.split(",") if name.strip()]


def _check_order(value: str, allowed: set[str]) -> str:
    names = parse_order(value)
    if not names:
        raise ValueError("the provider order is empty")
    unknown = [n for n in names if n not in allowed]
    if unknown:
        raise ValueError(f"unknown provider {unknown}; allowed: {sorted(allowed)}")
    if len(set(names)) != len(names):
        raise ValueError("a provider appears twice in the order")
    return ",".join(names)


def parse_caps(value: str) -> dict[tuple[str, str], int]:
    """"groq:tts=90,gemini:llm=500" -> {("groq", "tts"): 90, ("gemini", "llm"): 500}."""
    caps: dict[tuple[str, str], int] = {}
    for item in (part.strip() for part in value.split(",") if part.strip()):
        try:
            key, count = item.split("=")
            provider, capability = key.split(":")
            number = int(count)
        except ValueError as exc:
            raise ValueError(f"bad cap '{item}': use provider:capability=count") from exc
        if capability.strip().lower() not in {"llm", "stt", "tts"} or number < 1:
            raise ValueError(f"bad cap '{item}': capability is llm, stt or tts and the count at least 1")
        caps[(provider.strip().lower(), capability.strip().lower())] = number
    return caps


class Settings(BaseSettings):
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Firma de los tokens de sesión. CÁMBIALA en producción (ver .env.example).
    secret: str = "cambia-esto-en-produccion"
    database_url: str = "sqlite+aiosqlite:///./guako.db"
    # La cookie de sesión solo viaja por HTTPS cuando esto es True (activarlo en producción)
    cookie_secure: bool = False
    session_seconds: int = 60 * 60 * 24 * 14  # 14 días

    # --- LLM providers -------------------------------------------------
    # API keys are SecretStr so they never show up in repr(), logs or tracebacks.
    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    groq_model: str = "openai/gpt-oss-20b"
    # Reasoning effort of the Groq model in the CONVERSATION chain only (gpt-oss: low, medium, high).
    # "low" keeps the learner waiting less; the background analysis keeps the model default.
    # Empty = do not send it (needed for a Groq model without reasoning).
    groq_conversation_reasoning_effort: str = "low"
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    # Per-call timeout in seconds.
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    # Extra attempts after the first one when the output fails validation.
    llm_max_retries: int = Field(default=2, ge=0, le=10)

    # --- RAG: grammar rules found with embeddings (Gemini; reuses gemini_api_key; needs PostgreSQL + pgvector) ----
    embedding_model: str = "gemini-embedding-001"
    # Changing it means a new migration (the column has this size) and re-indexing every rule.
    embedding_dimensions: int = Field(default=768, ge=64, le=3072)
    embedding_timeout_seconds: float = Field(default=10.0, gt=0)
    # Below this cosine similarity the best rule is not shown: a wrong rule is worse than none.
    # 0.70 comes from the rag eval (python -m scripts.run_evals rag) on evals/rag (60 cases): 98% of the shown rules were the expected one,
    # 93% of the cases with a rule got it, 0 of 6 cases without a rule got a wrong one. Only 6 such cases: re-run
    # it when the corpus or the embedding model changes.
    rag_min_similarity: float = Field(default=0.70, ge=0.0, le=1.0)

    # Memory (error_events): a mistake with no rule counts as "the same" as an earlier one only above this cosine
    # similarity. Measured on 8 pairs with real embeddings: the same mistake in other sentences scored 0.80-0.83,
    # different mistakes of the same type 0.58-0.62. A small sample, not real learners: re-check it with real data.
    memory_min_similarity: float = Field(default=0.72, ge=0.0, le=1.0)

    # Generated exercises (app/exercises/generated.py): when a learner is running out of exercises they have not seen
    # for a rule, the analysis LLM writes more in the background; each one is checked with the grammar analyser first.
    exercises_generation_enabled: bool = True
    exercises_low_water: int = Field(default=2, ge=1)  # fewer unseen exercises than this for a rule: write more
    exercises_max_generated_per_rule: int = Field(default=30, ge=1)  # the pool of a rule never grows past this
    exercises_daily_generation_limit: int = Field(default=90, ge=1)  # accepted exercises per day, whole app
    exercises_generation_cooldown_seconds: float = Field(default=900.0, ge=0)  # between two tries for the same rule

    # --- Speech-to-text (Groq-hosted Whisper; reuses groq_api_key) ----
    # turbo: much faster than whisper-large-v3 and nearly as accurate in English; the learner is waiting.
    stt_model: str = "whisper-large-v3-turbo"
    # ISO-639-1 language hint sent to Whisper (the tutor listens to English). Empty = auto-detect.
    stt_language: str = "en"
    # Per-request timeout in seconds.
    stt_timeout_seconds: float = Field(default=10.0, gt=0)

    # --- Provider router: which provider serves each capability, in order ----
    # Names separated by commas; the first one that is healthy, within quota and (if paid) within the
    # budget answers, the next ones are the backup. A provider without an API key is skipped with a warning.
    # Free: groq, gemini. Paid: openai.
    llm_conversation_order: str = "groq,openai,gemini"  # latency matters
    llm_analysis_order: str = "openai,groq,gemini"  # background: protects the conversation's free quota
    stt_order: str = "groq,openai"
    tts_order: str = "groq,openai"  # free quota first (Groq Orpheus: 100 requests a day for the whole organisation)
    # Stop using a provider for a capability after this many requests a day, before it answers 429
    # ("provider:capability=count,..."; capability = llm, stt or tts). Cache hits do not count.
    provider_daily_caps: str = "groq:tts=90"

    # Circuit breaker, one per (provider, capability).
    breaker_failure_threshold: int = Field(default=3, ge=1)  # consecutive 429/503/timeouts that open it
    breaker_cooldown_seconds: float = Field(default=30.0, gt=0)  # first wait; doubles each time it re-opens
    breaker_max_cooldown_seconds: float = Field(default=600.0, gt=0)
    # A 429 that asks to wait longer than this means "quota spent": open at once for that long.
    breaker_quota_wait_seconds: float = Field(default=60.0, gt=0)
    breaker_max_open_seconds: float = Field(default=3600.0, gt=0)  # also used after an auth error

    # Spending cap for paid providers (USD, estimated by us, not OpenAI's invoice). 0 disables paid providers.
    paid_budget_usd: float = Field(default=5.0, ge=0)
    paid_budget_period: Literal["day", "month", "total"] = "month"
    paid_budget_warn_fraction: float = Field(default=0.8, gt=0, le=1)
    # OpenAI models and prices. Prices are NOT verified: the sources found were old and listed these
    # models as deprecated. Check platform.openai.com/pricing, set them here, then set the flag to true.
    openai_llm_model: str = "gpt-4o-mini"
    openai_stt_model: str = "whisper-1"  # needs word timestamps and a prompt: whisper-1
    openai_prices_confirmed: bool = False
    price_openai_llm_input_per_m: float = 0.15  # USD per million input tokens
    price_openai_llm_output_per_m: float = 0.60  # USD per million output tokens
    price_openai_stt_per_minute: float = 0.006  # USD per minute of audio
    price_openai_tts_per_minute: float = 0.015  # USD per minute of generated audio (an estimate by OpenAI)
    # The speech API does not report usage, so its cost is estimated from the audio length; be pessimistic.
    tts_cost_safety_factor: float = Field(default=1.3, ge=1.0)
    # Background jobs of the API process (usage flush, retry of pending analyses). Off in tests.
    background_tasks_enabled: bool = True

    # --- Text-to-speech (Groq-hosted Orpheus; reuses groq_api_key) ----
    tts_model: str = "canopylabs/orpheus-v1-english"
    tts_voice: str = "hannah"
    tts_timeout_seconds: float = Field(default=10.0, gt=0)
    tts_cache_dir: str = "cache/tts"
    # OpenAI is paid (see paid_budget_usd). The voice is part of the cache key.
    openai_api_key: SecretStr | None = None
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"

    # --- Azure Speech (Pronunciation Assessment; free F0 plan) ----
    azure_speech_key: SecretStr | None = None
    azure_speech_region: str = ""  # e.g. "brazilsouth"; the REST hosts are built from it
    azure_speech_timeout_seconds: float = Field(default=20.0, gt=0)

    # --- Conversation ----
    # Where uploaded user audio (with consent) and tutor reply audio are written.
    sessions_audio_dir: str = "output/sessions"
    # Largest accepted turn upload.
    max_turn_audio_bytes: int = 10 * 1024 * 1024
    # Product rule: audio minutes (learner + tutor) a user can use per day.
    daily_limit_minutes: int = Field(default=20, gt=0)

    @field_validator("llm_conversation_order", "llm_analysis_order")
    @classmethod
    def _check_llm_order(cls, value: str) -> str:
        return _check_order(value, {"groq", "gemini", "openai"})

    @field_validator("stt_order", "tts_order")
    @classmethod
    def _check_speech_order(cls, value: str) -> str:
        return _check_order(value, {"groq", "openai"})

    @field_validator("provider_daily_caps")
    @classmethod
    def _check_caps(cls, value: str) -> str:
        parse_caps(value)
        return value

    @property
    def daily_caps(self) -> dict[tuple[str, str], int]:
        return parse_caps(self.provider_daily_caps)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
