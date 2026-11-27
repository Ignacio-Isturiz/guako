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
from tests.fakes import TERMS, FakeLLM, FakeSTT, FakeTTS

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


def _allow_audio(client: TestClient) -> None:
    """The learner says yes to "keep my audio" (the consent log is what allows a session to keep it)."""
    assert client.post("/api/consents", json={"kind": "audio", "granted": True}).status_code == 200


def _login(client: TestClient, name: str) -> None:
    creds = {"username": name, "email": f"{name}@example.com", "password": "Passw0rd123", **TERMS}
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
    assert body["user_transcript"] == "I like to travel by train"
    assert body["reply_text"] == "That sounds fun! Where do you go?"
    assert body["reply_audio_url"] == f"/api/sessions/{session_id}/turns/1/reply-audio"
    # The pipeline order, then the grammar analysis, which runs after the reply is built.
    assert providers.calls == ["stt", "llm", "tts", "llm", "llm"]  # reply, then grammar and judge in the background

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
    assert "That sounds fun! Where do you go?" in providers.llm.tutor_prompts[1]


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
        # The provider rejected the recording (an iOS MP4 Whisper could not read): not "service down"
        ("stt", STTError("bad audio", status_code=400), 422, "audio_unreadable"),
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


def test_end_session_sets_ended_at(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _new_session(client)

    res = client.patch(f"/api/sessions/{session_id}", json={"ended": True})

    assert res.status_code == 200, res.text
    assert res.json()["ended_at"] is not None


def test_end_session_twice_keeps_the_first_ended_at(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _new_session(client)

    first = client.patch(f"/api/sessions/{session_id}", json={"ended": True})
    second = client.patch(f"/api/sessions/{session_id}", json={"ended": True})

    assert first.status_code == second.status_code == 200
    assert first.json()["ended_at"] == second.json()["ended_at"]


def test_end_someone_elses_session_is_404_and_leaves_it_open(
    client: TestClient, providers: Providers, db_path: Path
) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    client.post("/api/auth/logout")
    _login(client, "bob")

    assert client.patch(f"/api/sessions/{session_id}", json={"ended": True}).status_code == 404
    assert client.patch("/api/sessions/9999", json={"ended": True}).status_code == 404
    assert _query(db_path, "select ended_at from sessions") == [(None,)]


def test_turn_after_ending_the_session_is_409(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    client.patch(f"/api/sessions/{session_id}", json={"ended": True})

    res = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "session_ended"
    assert providers.calls == []


def test_end_session_validates_body_and_requires_login(client: TestClient, providers: Providers) -> None:
    assert client.patch("/api/sessions/1", json={"ended": True}).status_code == 401
    _login(client, "ana")
    session_id = _new_session(client)
    assert client.patch(f"/api/sessions/{session_id}", json={"ended": False}).status_code == 422
    assert client.patch(f"/api/sessions/{session_id}", json={}).status_code == 422


def test_consent_can_be_granted_and_the_audio_is_then_kept(
    client: TestClient, providers: Providers, db_path: Path
) -> None:
    _login(client, "ana")
    session_id = _new_session(client)

    _allow_audio(client)
    res = client.patch(f"/api/sessions/{session_id}", json={"audio_consent": True})
    assert res.status_code == 200 and res.json()["audio_consent"] is True
    assert res.json()["ended_at"] is None  # changing consent does not end the session

    client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)
    (path,) = _query(db_path, "select user_audio_path from turns")[0]
    assert path is not None and Path(path).is_file()


def test_withdrawing_consent_deletes_stored_audio_and_stops_keeping_it(
    client: TestClient, providers: Providers, db_path: Path
) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    _allow_audio(client)
    client.patch(f"/api/sessions/{session_id}", json={"audio_consent": True})
    client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)
    (stored,) = _query(db_path, "select user_audio_path from turns")[0]
    assert Path(stored).is_file()

    res = client.patch(f"/api/sessions/{session_id}", json={"audio_consent": False})

    assert res.status_code == 200 and res.json()["audio_consent"] is False
    assert not Path(stored).exists()
    assert _query(db_path, "select user_audio_path from turns") == [(None,)]
    # The reply audio is the tutor's, not the learner's: it stays.
    assert client.get(f"/api/sessions/{session_id}/turns/1/reply-audio").status_code == 200

    client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)
    assert _query(db_path, "select user_audio_path from turns order by turn_number") == [(None,), (None,)]


def test_withdrawing_after_the_end_works_but_granting_does_not(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    _allow_audio(client)
    client.patch(f"/api/sessions/{session_id}", json={"audio_consent": True, "ended": True})

    assert client.patch(f"/api/sessions/{session_id}", json={"audio_consent": False}).status_code == 200
    _allow_audio(client)
    late = client.patch(f"/api/sessions/{session_id}", json={"audio_consent": True})
    assert late.status_code == 409 and late.json()["detail"]["code"] == "session_ended"


def test_consent_of_someone_elses_session_is_404(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    client.post("/api/auth/logout")
    _login(client, "bob")

    assert client.patch(f"/api/sessions/{session_id}", json={"audio_consent": True}).status_code == 404
    assert _query(db_path, "select audio_consent from sessions") == [(0,)]


def test_consent_must_be_a_boolean(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    assert client.patch(f"/api/sessions/{session_id}", json={"audio_consent": "maybe"}).status_code == 422


def test_role_is_saved_trimmed_and_blank_means_none(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")

    with_role = client.post("/api/sessions", json={"level": "B1", "topic": "Family", "role": "  my dad  "})
    blank = client.post("/api/sessions", json={"level": "B1", "topic": "Family", "role": "   "})
    absent = client.post("/api/sessions", json={"level": "B1", "topic": "Family"})

    assert with_role.status_code == blank.status_code == absent.status_code == 201
    assert with_role.json()["role"] == "my dad"
    assert blank.json()["role"] is None and absent.json()["role"] is None


def test_role_is_too_long_is_422(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    res = client.post("/api/sessions", json={"level": "B1", "topic": "Family", "role": "x" * 201})
    assert res.status_code == 422


def test_turn_uses_the_role_of_the_session(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = client.post(
        "/api/sessions", json={"level": "B1", "topic": "Family", "role": "my mom, I ask her for money"}
    ).json()["id"]

    assert client.post(f"/api/sessions/{session_id}/turns", files=AUDIO).status_code == 201

    assert "my mom, I ask her for money" in providers.llm.systems[0]


def test_list_turns_returns_the_saved_conversation_in_order(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    assert client.get(f"/api/sessions/{session_id}/turns").json() == []

    client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)
    client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)
    res = client.get(f"/api/sessions/{session_id}/turns")

    assert res.status_code == 200
    body = res.json()
    assert [t["turn_number"] for t in body] == [1, 2]
    assert body[0]["user_transcript"] == "I like to travel by train"
    assert body[0]["reply_text"] == "That sounds fun! Where do you go?"
    assert body[0]["reply_audio_url"] == f"/api/sessions/{session_id}/turns/1/reply-audio"


def test_list_turns_of_someone_elses_session_is_404(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _new_session(client)
    client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)
    client.post("/api/auth/logout")
    assert client.get(f"/api/sessions/{session_id}/turns").status_code == 401
    _login(client, "bob")

    assert client.get(f"/api/sessions/{session_id}/turns").status_code == 404
    assert client.get("/api/sessions/9999/turns").status_code == 404


def test_list_sessions_returns_only_my_conversations_with_turns_newest_first(
    client: TestClient, providers: Providers
) -> None:
    _login(client, "ana")
    empty = _new_session(client)  # no turns: not a conversation
    first = _new_session(client)
    second = client.post("/api/sessions", json={"level": "A2", "topic": "Work", "role": "my boss"}).json()["id"]
    client.post(f"/api/sessions/{first}/turns", files=AUDIO)
    client.post(f"/api/sessions/{second}/turns", files=AUDIO)
    client.post(f"/api/sessions/{second}/turns", files=AUDIO)
    client.patch(f"/api/sessions/{second}", json={"ended": True})
    client.post("/api/auth/logout")
    _login(client, "bob")
    bobs = _new_session(client)
    client.post(f"/api/sessions/{bobs}/turns", files=AUDIO)
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login", data={"username": "ana@example.com", "password": "Passw0rd123"}
    )

    res = client.get("/api/sessions")

    assert res.status_code == 200
    body = res.json()
    assert [s["id"] for s in body] == [second, first]  # newest first, no empty session, nothing of bob's
    assert empty not in [s["id"] for s in body]
    assert (body[0]["turns"], body[0]["role"], body[0]["level"]) == (2, "my boss", "A2")
    assert body[0]["ended_at"] is not None and body[1]["ended_at"] is None
    assert body[0]["duration_seconds"] == pytest.approx(7.0)  # 2 turns x (2.5 s learner + 1.0 s tutor)


def test_list_sessions_requires_login(client: TestClient, providers: Providers) -> None:
    assert client.get("/api/sessions").status_code == 401


def _role_session(client: TestClient) -> int:
    return client.post(
        "/api/sessions", json={"level": "B1", "topic": "Family", "role": "my mom, who doubts about giving me money"}
    ).json()["id"]


def test_guako_opens_the_scene_in_the_chosen_role(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _role_session(client)

    res = client.post(f"/api/sessions/{session_id}/opening")

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["turn_number"] == 0 and body["user_transcript"] == ""
    assert body["reply_text"] == "That sounds fun! Where do you go?"  # the fake LLM's line
    assert body["reply_audio_url"] == f"/api/sessions/{session_id}/turns/0/reply-audio"
    assert providers.calls == ["llm", "tts"]  # no transcription: the learner has not spoken
    assert "my mom, who doubts about giving me money" in providers.llm.systems[0]
    assert "first line" in providers.llm.prompts[0]
    assert client.get(body["reply_audio_url"]).status_code == 200
    assert _query(db_path, "select turn_number, user_transcript from turns") == [(0, "")]


def test_opening_twice_returns_the_saved_one(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    session_id = _role_session(client)

    first = client.post(f"/api/sessions/{session_id}/opening")
    second = client.post(f"/api/sessions/{session_id}/opening")

    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json() == second.json()
    assert providers.calls == ["llm", "tts"]  # the second call spent nothing
    assert _query(db_path, "select count(*) from turns") == [(1,)]


def test_first_learner_turn_after_the_opening_is_turn_1_and_sees_the_opening(
    client: TestClient, providers: Providers
) -> None:
    _login(client, "ana")
    session_id = _role_session(client)
    client.post(f"/api/sessions/{session_id}/opening")
    providers.llm.reply = "Why do you need it?"

    turn = client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)

    assert turn.status_code == 201 and turn.json()["turn_number"] == 1
    history_prompt = providers.llm.tutor_prompts[-1]
    assert "Guako: That sounds fun! Where do you go?" in history_prompt  # the opening is in the history
    assert "Learner: " not in history_prompt  # ...and the learner has no line before it


def test_opening_after_the_learner_spoke_is_409(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _role_session(client)
    client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)
    providers.calls.clear()

    res = client.post(f"/api/sessions/{session_id}/opening")

    assert res.status_code == 409 and res.json()["detail"]["code"] == "session_started"
    assert providers.calls == []


def test_opening_of_an_ended_or_foreign_session_is_refused(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _role_session(client)
    client.patch(f"/api/sessions/{session_id}", json={"ended": True})
    assert client.post(f"/api/sessions/{session_id}/opening").status_code == 409
    client.post("/api/auth/logout")
    _login(client, "bob")

    assert client.post(f"/api/sessions/{session_id}/opening").status_code == 404
    assert providers.calls == []


def test_opening_respects_the_daily_limit(client: TestClient, providers: Providers, db_path: Path) -> None:
    _login(client, "ana")
    old_session = _new_session(client)
    _insert_turn(db_path, old_session, seconds=20 * 60, created_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))
    session_id = _role_session(client)

    res = client.post(f"/api/sessions/{session_id}/opening")

    assert res.status_code == 429 and providers.calls == []


def test_a_session_with_only_the_opening_is_not_a_conversation_yet(client: TestClient, providers: Providers) -> None:
    _login(client, "ana")
    session_id = _role_session(client)
    client.post(f"/api/sessions/{session_id}/opening")
    assert client.get("/api/sessions").json() == []

    client.post(f"/api/sessions/{session_id}/turns", files=AUDIO)
    (listed,) = client.get("/api/sessions").json()

    assert listed["turns"] == 1  # the opening is not counted
    assert listed["duration_seconds"] == pytest.approx(3.5)  # learner 2.5 s + tutor 1.0 s, opening excluded
    turns = client.get(f"/api/sessions/{session_id}/turns").json()
    assert [t["turn_number"] for t in turns] == [0, 1]  # but the review shows it
