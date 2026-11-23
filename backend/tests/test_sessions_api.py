import sqlite3
from datetime import UTC, datetime, timedelta
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.conversation.deps import get_stt_provider, get_tts_provider
from app.llm.errors import LLMProviderError
from app.llm.factory import get_llm_provider
from app.main import app
from app.stt.errors import STTError
from app.tts.errors import TTSError
from tests.fakes import FakeLLM, FakeSTT, FakeTTS

AUDIO = {"audio": ("turn.wav", b"RIFFfake-audio", "audio/wav")}


@dataclass
class Providers:
    calls: list[str] = field(default_factory=list)
    stt: FakeSTT = field(init=False)
    llm: FakeLLM = field(init=False)
    tts: FakeTTS = field(init=False)

    def __post_init__(self) -> None:
        self.stt, self.llm, self.tts = FakeSTT(self.calls), FakeLLM(self.calls), FakeTTS(self.calls)


@pytest.fixture
def providers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Providers]:
    monkeypatch.setattr(settings, "sessions_audio_dir", str(tmp_path / "audio"))
    fakes = Providers()
    app.dependency_overrides[get_stt_provider] = lambda: fakes.stt
    app.dependency_overrides[get_llm_provider] = lambda: fakes.llm
    app.dependency_overrides[get_tts_provider] = lambda: fakes.tts
    yield fakes


def _login(client: TestClient, name: str) -> None:
    creds = {"username": name, "email": f"{name}@example.com", "password": "Passw0rd123"}
    assert client.post("/api/auth/register", json=creds).status_code == 201
    login = client.post("/api/auth/login", data={"username": creds["email"], "password": creds["password"]})
    assert login.status_code == 204


def _new_session(client: TestClient) -> int:
    res = client.post("/api/sessions", json={"level": "B1", "topic": "Travel"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _query(db_path: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(sql).fetchall()


def test_create_session_defaults(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    res = client.post("/api/sessions", json={"level": "B1", "topic": "  Travel  "})
    body = res.json()
    assert res.status_code == 201
    assert (body["level"], body["topic"], body["audio_consent"]) == ("B1", "Travel", False)


def test_create_session_validates_level(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    assert client.post("/api/sessions", json={"level": "Z9", "topic": "Travel"}).status_code == 422
    assert client.post("/api/sessions", json={"level": "B1", "topic": "   "}).status_code == 422


def test_turn_returns_201_and_stores_the_turn(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _new_session(client)

    res = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["turn_number"] == 1
    assert body["reply_text"] == "That sounds fun! Where do you go?"
    assert body["reply_audio_url"] == f"/api/sessions/{session_id}/turns/1/reply-audio"
    assert providers.calls == ["stt", "llm", "tts"]

    rows = _query(db_path, "select turn_number, user_transcript, user_audio_path, word_timestamps from turns")
    assert len(rows) == 1
    assert rows[0][1] == "I like to travel by train"
    assert rows[0][2] is None  # no audio consent: the upload is not kept
    assert '"word": "I"' in rows[0][3]

    audio = client.get(body["reply_audio_url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"


def test_second_turn_continues_the_conversation(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _new_session(client)

    client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)
    second = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    assert second.json()["turn_number"] == 2
    assert "That sounds fun! Where do you go?" in providers.llm.prompts[1]


def test_turn_of_someone_elses_session_is_404(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    client.post("/api/auth/logout")
    _login(client, "bob")

    assert client.post(f"/api/sessions/{session_id}/turns", files=AUDIO).status_code == 404
    assert client.get(f"/api/sessions/{session_id}/turns/1/reply-audio").status_code == 404
    assert client.post("/api/sessions/9999/turns", files=AUDIO).status_code == 404
    assert providers.calls == []
    assert _query(db_path, "select count(*) from turns") == [(0,)]


def test_turn_requires_login(client: TestClient, providers: Providers) -> None:
    assert client.post("/api/sessions/1/turns", files=AUDIO).status_code == 401
    assert client.post("/api/sessions", json={"level": "B1", "topic": "Travel"}).status_code == 401


def test_ended_session_is_409(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    with sqlite3.connect(db_path) as conn:
        conn.execute("update sessions set ended_at = current_timestamp")

    assert client.post(f"/api/sessions/{session_id}/turns", files=AUDIO).status_code == 409
    assert providers.calls == []


def test_llm_failure_creates_no_turn(client: TestClient, providers: Providers, db_path: Path, tmp_path: Path) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    providers.llm.error = LLMProviderError("boom")

    res = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    assert res.status_code >= 500
    assert res.json()["detail"]["message"]
    assert _query(db_path, "select count(*) from turns") == [(0,)]
    assert providers.calls == ["stt", "llm"]  # TTS never ran
    assert list((tmp_path / "audio").rglob("*user*")) == []  # the upload was cleaned up

    # The same session recovers on the next try and the turn is number 1.
    providers.llm.error = None
    retry = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)
    assert retry.status_code == 201 and retry.json()["turn_number"] == 1


@pytest.mark.parametrize(
    ("fake", "error", "status", "code"),
    [
        ("stt", STTError("down"), 503, "stt_unavailable"),
        ("tts", TTSError("down"), 503, "tts_unavailable"),
    ],
)
def test_stt_and_tts_failures_are_503_and_store_nothing(
    client: TestClient, providers: Providers, db_path: Path, fake: str, error: Exception, status: int, code: str
) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    getattr(providers, fake).error = error

    res = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    assert res.status_code == status
    assert res.json()["detail"]["code"] == code
    assert _query(db_path, "select count(*) from turns") == [(0,)]


def test_silence_is_422(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    providers.stt.text = ""

    res = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "no_speech"


def test_bad_uploads_are_rejected(client: TestClient, providers: Providers, monkeypatch: pytest.MonkeyPatch) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    url = f"/api/sessions/{session_id}/turns"

    assert client.post(url, files={"audio": ("notes.txt", b"hi", "text/plain")}).status_code == 415
    assert client.post(url, files={"audio": ("turn.wav", b"", "audio/wav")}).status_code == 400
    monkeypatch.setattr(settings, "max_turn_audio_bytes", 4)
    assert client.post(url, files={"audio": ("turn.wav", b"12345", "audio/wav")}).status_code == 413
    assert providers.calls == []


def test_audio_is_kept_only_with_consent(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    with sqlite3.connect(db_path) as conn:
        conn.execute("update sessions set audio_consent = 1")

    client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    (path,) = _query(db_path, "select user_audio_path from turns")[0]
    assert path is not None and Path(path).is_file()


def test_turn_stores_audio_seconds(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _new_session(client)

    client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    (user_s, reply_s) = _query(db_path, "select user_audio_seconds, reply_audio_seconds from turns")[0]
    assert user_s == pytest.approx(2.5) and reply_s == pytest.approx(1.0)


def _insert_turn(db_path: Path, session_id: int, *, seconds: float, created_at: str) -> None:
    with sqlite3.connect(db_path) as conn:
        number = conn.execute("select coalesce(max(turn_number), 0) + 1 from turns").fetchone()[0]
        conn.execute(
            "insert into turns (session_id, turn_number, user_transcript, reply_text, reply_audio_path,"
            " user_audio_seconds, reply_audio_seconds, created_at) values (?, ?, 'x', 'y', 'z', ?, 0, ?)",
            (session_id, number, seconds, created_at),
        )


def test_daily_limit_blocks_the_next_turn(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    _insert_turn(db_path, session_id, seconds=20 * 60, created_at=now)

    res = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    assert res.status_code == 429
    assert res.json()["detail"]["code"] == "daily_limit_reached"
    assert providers.calls == []  # no STT/LLM/TTS call was spent


def test_below_the_limit_still_works_and_yesterday_does_not_count(
    client: TestClient, providers: Providers, db_path: Path
) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    now = datetime.now(UTC)
    _insert_turn(db_path, session_id, seconds=19 * 60, created_at=now.strftime("%Y-%m-%d %H:%M:%S"))
    assert client.post(f"/api/sessions/{session_id}/turns", files=AUDIO).status_code == 201

    long_ago = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    _insert_turn(db_path, session_id, seconds=60 * 60, created_at=long_ago)
    assert client.post(f"/api/sessions/{session_id}/turns", files=AUDIO).status_code == 201


def test_limit_is_per_user(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    ana_session = _new_session(client)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    _insert_turn(db_path, ana_session, seconds=20 * 60, created_at=now)
    client.post("/api/auth/logout")

    _login(client, "bob")
    bob_session = _new_session(client)
    assert client.post(f"/api/sessions/{bob_session}/turns", files=AUDIO).status_code == 201
