from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.conversation.errors import register_speech_error_handlers
from app.grammar_api import router as grammar_router
from app.llm.handlers import register_llm_error_handlers
from app.sessions_api import router as sessions_router
from app.streak_api import router as streak_router
from app.users import UserCreate, UserRead, UserUpdate, auth_backend, fastapi_users
from app.users_api import router as users_settings_router


app = FastAPI(title="Guako API")
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
