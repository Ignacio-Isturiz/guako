from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    llm_provider: Literal["gemini", "groq"] = "groq"
    # Used when the primary fails (rate limit, outage, invalid output). "none" disables it.
    llm_fallback_provider: Literal["gemini", "groq", "none"] = "gemini"
    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    groq_model: str = "openai/gpt-oss-20b"
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    # Per-call timeout in seconds.
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    # Extra attempts after the first one when the output fails validation.
    llm_max_retries: int = Field(default=2, ge=0, le=10)

    # --- Speech-to-text (Groq-hosted Whisper; reuses groq_api_key) ----
    stt_model: str = "whisper-large-v3"
    # ISO-639-1 language hint sent to Whisper (the tutor listens to English). Empty = auto-detect.
    stt_language: str = "en"
    # Per-request timeout in seconds.
    stt_timeout_seconds: float = Field(default=10.0, gt=0)

    # --- Text-to-speech (Groq-hosted Orpheus; reuses groq_api_key) ----
    tts_model: str = "canopylabs/orpheus-v1-english"
    tts_voice: str = "hannah"
    tts_timeout_seconds: float = Field(default=10.0, gt=0)
    tts_cache_dir: str = "cache/tts"
    # Backup used when Groq TTS fails or hits its daily quota. "none" disables it.
    tts_fallback_provider: Literal["openai", "none"] = "openai"
    # OpenAI is paid, so it only runs as the backup. voice is part of the cache key.
    openai_api_key: SecretStr | None = None
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"

    # --- Conversation ----
    # Where uploaded user audio (with consent) and tutor reply audio are written.
    sessions_audio_dir: str = "output/sessions"
    # Largest accepted turn upload.
    max_turn_audio_bytes: int = 10 * 1024 * 1024
    # Product rule: audio minutes (learner + tutor) a user can use per day.
    daily_limit_minutes: int = Field(default=20, gt=0)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
