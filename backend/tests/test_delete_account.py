"""DELETE /api/users/me: the account and everything of it goes away; other learners are untouched."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from tests.test_sessions_api import AUDIO, Providers, _allow_audio, _login, _new_session, providers  # noqa: F401

USER_TABLES = [
    "sessions", "consents", "streaks", "activity_days", "exercise_seen", "error_events", "safety_events", "reply_reports",
]


def _count(db_path: Path, sql: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(sql).fetchone()[0]


def _practice(client: TestClient) -> int:
    """A session with one turn and kept audio, then ended (so the streak and activity rows exist too)."""
    _allow_audio(client)
    session_id = _new_session(client)
    assert client.post(f"/api/sessions/{session_id}/turns", files=AUDIO).status_code == 201
    assert client.post(f"/api/sessions/{session_id}/turns/1/flag", json={"reason": "other"}).status_code == 201
    assert client.patch(f"/api/sessions/{session_id}", json={"ended": True}).status_code == 200
    client.post("/api/streak/activity?tz=America/Bogota")
    return session_id


def test_delete_removes_the_account_its_data_and_its_audio(
    client: TestClient, providers: Providers, db_path: Path
) -> None:
    _login(client, "ana")
    ana_session = _practice(client)
    client.post("/api/auth/logout")
    _login(client, "beto")
    beto_session = _practice(client)
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", data={"username": "ana@example.com", "password": "Passw0rd123"}).status_code == 204

    audio_root = Path(settings.sessions_audio_dir)
    assert (audio_root / str(ana_session)).exists()
    ana = "(select id from user where email = 'ana@example.com')"
    for table in ("sessions", "consents", "streaks", "activity_days", "reply_reports"):  # there is something to delete
        assert _count(db_path, f"select count(*) from {table} where user_id = {ana}") > 0, table

    res = client.delete("/api/users/me")

    assert res.status_code == 204, res.text
    assert "guako_session" in res.headers.get("set-cookie", "")
    assert client.get("/api/users/me").status_code == 401  # the cookie is gone
    assert _count(db_path, "select count(*) from user where email = 'ana@example.com'") == 0
    assert _count(db_path, f"select count(*) from turns where session_id = {ana_session}") == 0
    assert _count(db_path, f"select count(*) from sessions where id = {ana_session}") == 0
    assert not (audio_root / str(ana_session)).exists()

    # Beto keeps everything
    assert _count(db_path, "select count(*) from user where email = 'beto@example.com'") == 1
    assert _count(db_path, f"select count(*) from turns where session_id = {beto_session}") == 1
    assert (audio_root / str(beto_session)).exists()

    # Nothing of Ana is left in any table that points at a user
    for table in USER_TABLES:
        left = _count(db_path, f"select count(*) from {table} where user_id not in (select id from user)")
        assert left == 0, table


def test_deleted_account_cannot_log_in_again(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    assert client.delete("/api/users/me").status_code == 204
    login = client.post("/api/auth/login", data={"username": "ana@example.com", "password": "Passw0rd123"})
    assert login.status_code == 400


def test_delete_requires_login(client: TestClient) -> None:
    assert client.delete("/api/users/me").status_code == 401
