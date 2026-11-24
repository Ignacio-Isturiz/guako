import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin_api import router as admin_router
from app.analysis.retry import run_retrier
from app.config import settings
from app.conversation.deps import get_pronunciation_provider
from app.conversation.errors import register_speech_error_handlers
from app.db import async_session_maker
from app.grammar_api import router as grammar_router
from app.llm.handlers import register_llm_error_handlers
from app.practice_api import router as practice_router
from app.providers import chains
from app.providers.state import get_state
from app.providers.usage import flush_usage, load_baseline, run_flusher
from app.sessions_api import router as sessions_router
from app.streak_api import router as streak_router
from app.users import UserCreate, UserRead, UserUpdate, auth_backend, fastapi_users
from app.users_api import router as users_settings_router


logger = logging.getLogger("app.providers")


def _check_providers() -> None:
    """Build every chain at startup: a chain with no usable provider is a configuration error that must be loud."""
    chains.conversation_llm(settings)
    chains.analysis_llm(settings)
    chains.speech_to_text(settings)
    chains.text_to_speech(settings)
    if settings.openai_api_key is not None and not settings.openai_prices_confirmed:
        logger.warning(
            "openai_prices_unconfirmed the cost estimates use default prices that were not verified: "
            "check platform.openai.com/pricing, set the PRICE_OPENAI_* values and OPENAI_PRICES_CONFIRMED=true"
        )


@asynccontextmanager
async def lifespan(_: FastAPI):  # noqa: ANN201
    """Startup: check the provider chains, restore the day's counters, start the usage flusher and the retrier."""
    tasks: list[asyncio.Task] = []
    state = get_state()
    if settings.background_tasks_enabled:
        _check_providers()
        try:
            await load_baseline(async_session_maker, state)
        except Exception:
            logger.exception("usage_baseline_failed: counters start from zero")
        tasks = [
            asyncio.create_task(run_flusher(async_session_maker, state)),
            asyncio.create_task(
                run_retrier(async_session_maker, lambda: chains.analysis_llm(settings), get_pronunciation_provider)
            ),
        ]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if tasks:
        await flush_usage(async_session_maker, state)


app = FastAPI(title="Guako API", lifespan=lifespan)
register_llm_error_handlers(app)
register_speech_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# POST /api/auth/login · POST /api/auth/logout
app.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/api/auth", tags=["auth"])
# POST /api/auth/register  { username, email, password }
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/api/auth", tags=["auth"])
# GET /api/users/me
app.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/api/users", tags=["users"])
# PATCH /api/users/me/settings  { feedback_language }
app.include_router(users_settings_router)

# GET /api/streak · POST /api/streak/activity  (?tz=America/Bogota)
app.include_router(streak_router)

# POST /api/grammar/analyze  { text }
app.include_router(grammar_router)

# POST /api/sessions · POST /api/sessions/{id}/turns (audio) · GET /api/sessions/{id}/turns/{n}/reply-audio
app.include_router(sessions_router)
app.include_router(practice_router)

# GET /api/admin/usage  (superusers only)
app.include_router(admin_router)
