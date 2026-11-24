"""Shared test setup.

backend/.env points DATABASE_URL at the Docker Postgres (asyncpg), which tests must
never use. Environment variables win over .env in pydantic-settings, so the app is
pointed at SQLite before it is imported.
"""

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-unused.db"
# Azure Speech has a small monthly quota that is not recovered: tests must never reach it, even by
# accident. An empty key means "not configured"; the network guard below is a second barrier.
os.environ["AZURE_SPEECH_KEY"] = ""
os.environ["AZURE_SPEECH_REGION"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

import httpx  # noqa: E402

from app.conversation.deps import get_pronunciation_provider  # noqa: E402
from app.db import Base, get_async_session  # noqa: E402
from app.main import app  # noqa: E402


async def _create_tables(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """SQLite file of this test; open it with sqlite3 to inspect rows."""
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    """A TestClient over a fresh SQLite file; the cookie jar keeps the session."""
    url = f"sqlite+aiosqlite:///{db_path}"
    asyncio.run(_create_tables(url))
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():  # type: ignore[no-untyped-def]
        async with maker() as session:
            yield session

    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_pronunciation_provider] = lambda: None  # tests that need Azure pass a fake
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


@pytest.fixture(autouse=True)
def backoff_waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The retry waits of the background analysis are recorded instead of slept."""
    from app.analysis import runner

    waits: list[float] = []
    monkeypatch.setattr(runner, "_sleep", waits.append)
    return waits


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real HTTP request to Microsoft/Azure fails the test (their free quota is not recovered).

    Clients with a mock transport (httpx.MockTransport) are not affected. Other hosts are left
    alone: a few opt-in tests call Groq for real.
    """
    real_handle = httpx.HTTPTransport.handle_request

    def guarded(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        if request.url.host.endswith(("microsoft.com", "azure.com")):
            raise RuntimeError(f"Real Azure call blocked in tests: {request.url.host}")
        return real_handle(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded)
