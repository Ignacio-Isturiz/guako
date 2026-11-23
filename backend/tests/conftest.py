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

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())
