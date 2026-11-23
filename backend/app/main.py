from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import create_db_and_tables
from app.grammar_api import router as grammar_router
from app.llm.handlers import register_llm_error_handlers
from app.users import UserCreate, UserRead, UserUpdate, auth_backend, fastapi_users


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await create_db_and_tables()
    yield


app = FastAPI(title="Guako API", lifespan=lifespan)
register_llm_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# POST /api/auth/login · POST /api/auth/logout
app.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/api/auth", tags=["auth"])
# POST /api/auth/register  { username, email, password }
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/api/auth", tags=["auth"])
# GET /api/users/me
app.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/api/users", tags=["users"])

# POST /api/grammar/analyze  { text }
app.include_router(grammar_router)
