from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Firma de los tokens de sesión. CÁMBIALA en producción (ver .env.example).
    secret: str = "cambia-esto-en-produccion"
    database_url: str = "sqlite+aiosqlite:///./guako.db"
    # La cookie de sesión solo viaja por HTTPS cuando esto es True (activarlo en producción)
    cookie_secure: bool = False
    session_seconds: int = 60 * 60 * 24 * 14  # 14 días

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
