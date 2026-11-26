"""POST /api/sessions/{id}/turns/{n}/flag: a learner reports one of Guako's replies; admins can review them."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_sessions_api import AUDIO, Providers, _login, _new_session, providers  # noqa: F401


def _rows(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("select session_id, turn_number, reason, comment from reply_reports").fetchall()


def _session_with_a_turn(client: TestClient) -> int:
    session_id = _new_session(client)
    assert client.post(f"/api/sessions/{session_id}/turns", files=AUDIO).status_code == 201
    return session_id


def test_flag_saves_the_report_and_a_second_one_updates_it(
    client: TestClient, providers: Providers, db_path: Path
) -> None:
    _login(client, "ana")
    session_id = _session_with_a_turn(client)

    res = client.post(f"/api/sessions/{session_id}/turns/1/flag", json={"reason": "offensive", "comment": "  rude  "})
    assert res.status_code == 201, res.text
    assert _rows(db_path) == [(session_id, 1, "offensive", "rude")]

    res = client.post(f"/api/sessions/{session_id}/turns/1/flag", json={"reason": "wrong"})
    assert res.status_code == 201
    assert _rows(db_path) == [(session_id, 1, "wrong", None)]


def test_flag_validates_reason_and_comment(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _session_with_a_turn(client)
    url = f"/api/sessions/{session_id}/turns/1/flag"
    assert client.post(url, json={"reason": "boring"}).status_code == 422
    assert client.post(url, json={"reason": "other", "comment": "x" * 501}).status_code == 422


def test_flag_of_a_missing_turn_or_someone_elses_session_is_404(
    client: TestClient, providers: Providers, db_path: Path
) -> None:
    _login(client, "ana")
    session_id = _session_with_a_turn(client)
    assert client.post(f"/api/sessions/{session_id}/turns/9/flag", json={"reason": "other"}).status_code == 404
    client.post("/api/auth/logout")
    _login(client, "beto")
    assert client.post(f"/api/sessions/{session_id}/turns/1/flag", json={"reason": "other"}).status_code == 404
    assert _rows(db_path) == []


def test_flag_requires_login(client: TestClient) -> None:
    assert client.post("/api/sessions/1/turns/1/flag", json={"reason": "other"}).status_code == 401


def test_admin_sees_reports_with_the_reply_text(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _session_with_a_turn(client)
    client.post(f"/api/sessions/{session_id}/turns/1/flag", json={"reason": "harmful"})
    assert client.get("/api/admin/reports").status_code == 403  # a learner is not an admin

    with sqlite3.connect(db_path) as conn:
        conn.execute("update user set is_superuser = 1 where email = 'ana@example.com'")
    reports = client.get("/api/admin/reports").json()
    assert [(r["reason"], r["reply_text"]) for r in reports] == [("harmful", "That sounds fun! Where do you go?")]
