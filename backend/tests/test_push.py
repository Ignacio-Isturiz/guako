"""Web Push daily reminder (installed web app): subscription endpoints and who gets a reminder when."""

import asyncio
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings, settings
from app.push import PushGone, allowed_endpoint, due_day, send_due
from tests.test_sessions_api import _login

FCM = "https://fcm.googleapis.com/fcm/send/abc123"
APPLE = "https://web.push.apple.com/QGx1"
SUB = {"endpoint": FCM, "keys": {"p256dh": "BPk3", "auth": "a1b2"}, "hour": 19, "tz": "America/Bogota", "lang": "es"}
PUSH = Settings(vapid_public_key="BPublic", vapid_private_key=SecretStr("priv"), vapid_subject="mailto:a@b.co")


def _rows(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("select endpoint, hour, timezone, lang, last_sent_day from push_subscriptions").fetchall()


def _send(db_path: Path, now: datetime, sender) -> int:  # type: ignore[no-untyped-def]
    async def run() -> int:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            return await send_due(async_sessionmaker(engine, expire_on_commit=False), PUSH, sender, now)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_due_day_window_and_once_a_day() -> None:
    bogota_1930 = datetime(2026, 11, 27, 0, 30, tzinfo=timezone.utc)
    today = date(2026, 11, 26)
    assert due_day(19, "America/Bogota", None, None, bogota_1930) == today
    assert due_day(20, "America/Bogota", None, None, bogota_1930) is None  # not yet
    assert due_day(15, "America/Bogota", None, None, bogota_1930) is None  # window (3 h) is over
    assert due_day(19, "America/Bogota", today, None, bogota_1930) is None  # already sent today
    assert due_day(19, "America/Bogota", None, today, bogota_1930) is None  # already practiced today
    assert due_day(19, "America/Bogota", date(2026, 11, 25), date(2026, 11, 25), bogota_1930) == today
    assert due_day(0, "Not/AZone", None, None, datetime(2026, 11, 26, 1, tzinfo=timezone.utc)) == date(2026, 11, 26)


def test_only_known_push_services_are_accepted() -> None:
    assert allowed_endpoint(FCM) and allowed_endpoint(APPLE)
    assert allowed_endpoint("https://updates.push.services.mozilla.com/wpush/v2/x")
    assert not allowed_endpoint("http://fcm.googleapis.com/x")  # not https
    assert not allowed_endpoint("https://evil.com/fcm.googleapis.com")
    assert not allowed_endpoint("https://fcm.googleapis.com.evil.com/x")
    assert not allowed_endpoint("https://127.0.0.1/x")


def test_public_key_is_null_without_configuration(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vapid_public_key", "")
    assert client.get("/api/push/key").json() == {"public_key": None}
    for name in ("vapid_public_key", "vapid_private_key", "vapid_subject"):
        monkeypatch.setattr(settings, name, getattr(PUSH, name))
    assert client.get("/api/push/key").json() == {"public_key": "BPublic"}


def test_subscribe_update_and_remove(client: TestClient, db_path: Path) -> None:
    assert client.put("/api/push/subscription", json=SUB).status_code == 401
    _login(client, "ana")
    assert client.put("/api/push/subscription", json=SUB).status_code == 204
    assert client.put("/api/push/subscription", json={**SUB, "hour": 8, "lang": "en"}).status_code == 204
    assert _rows(db_path) == [(FCM, 8, "America/Bogota", "en", None)]

    assert client.put("/api/push/subscription", json={**SUB, "endpoint": "https://evil.com/x"}).status_code == 422
    assert client.put("/api/push/subscription", json={**SUB, "hour": 24}).status_code == 422

    assert client.request("DELETE", "/api/push/subscription", json={"endpoint": FCM}).status_code == 204
    assert _rows(db_path) == []


def test_same_browser_moves_to_the_new_account(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    client.put("/api/push/subscription", json=SUB)
    client.post("/api/auth/logout")
    _login(client, "beto")
    client.put("/api/push/subscription", json=SUB)
    with sqlite3.connect(db_path) as conn:
        owner = conn.execute("select u.username from push_subscriptions p join user u on u.id = p.user_id").fetchall()
    assert owner == [("beto",)]


def test_send_due_sends_once_skips_practiced_and_drops_gone(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    client.put("/api/push/subscription", json=SUB)
    client.put("/api/push/subscription", json={**SUB, "endpoint": APPLE, "lang": "en"})
    now = datetime(2026, 11, 27, 0, 30, tzinfo=timezone.utc)  # 19:30 in Bogotá

    sent: list[tuple[str, str]] = []
    assert _send(db_path, now, lambda sub, payload, _: sent.append((sub.endpoint, payload))) == 2
    assert {e for e, _ in sent} == {FCM, APPLE}
    assert "racha" in dict(sent)[FCM] and "streak" in dict(sent)[APPLE]
    assert {r[4] for r in _rows(db_path)} == {"2026-11-26"}
    assert _send(db_path, now, lambda *_: sent.append(("again", ""))) == 0  # once a day

    # Next day: practiced already → nothing; the gone subscription is deleted
    next_day = datetime(2026, 11, 28, 0, 30, tzinfo=timezone.utc)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into streaks (user_id, current, best, last_day, recoveries_used, recoveries_month, timezone)"
            " values (1, 1, 1, '2026-11-27', 0, '', 'America/Bogota')"
        )
    assert _send(db_path, next_day, lambda *_: None) == 0

    def gone(sub, payload, config):  # type: ignore[no-untyped-def]
        if sub.endpoint == APPLE:
            raise PushGone

    third_day = datetime(2026, 11, 29, 0, 30, tzinfo=timezone.utc)
    assert _send(db_path, third_day, gone) == 1
    assert [r[0] for r in _rows(db_path)] == [FCM]


def test_a_failing_send_is_retried_on_the_next_round(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    client.put("/api/push/subscription", json=SUB)
    now = datetime(2026, 11, 27, 0, 30, tzinfo=timezone.utc)

    def boom(*_):  # type: ignore[no-untyped-def]
        raise RuntimeError("network")

    assert _send(db_path, now, boom) == 0
    assert _rows(db_path)[0][4] is None
    assert _send(db_path, now, lambda *_: None) == 1


def test_cron_endpoint_needs_its_token(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.post("/api/push/run").status_code == 404  # no token configured
    monkeypatch.setattr(settings, "push_cron_token", SecretStr("s3cret"))
    assert client.post("/api/push/run", headers={"X-Cron-Token": "nope"}).status_code == 404
    monkeypatch.setattr("app.push_api.send_due", lambda *_: asyncio.sleep(0, result=3))
    assert client.post("/api/push/run", headers={"X-Cron-Token": "s3cret"}).json() == {"sent": 3}


def test_deleting_the_account_drops_its_subscriptions(client: TestClient, db_path: Path) -> None:
    _login(client, "ana")
    client.put("/api/push/subscription", json=SUB)
    assert client.delete("/api/users/me").status_code == 204
    assert _rows(db_path) == []
