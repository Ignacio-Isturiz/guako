from fastapi.testclient import TestClient

from tests.fakes import TERMS

CREDENTIALS = {"username": "ana_test", "email": "ana@example.com", "password": "Passw0rd123", **TERMS}


def _register_and_login(client: TestClient) -> dict:
    created = client.post("/api/auth/register", json=CREDENTIALS)
    assert created.status_code == 201, created.text
    login = client.post("/api/auth/login", data={"username": CREDENTIALS["email"], "password": CREDENTIALS["password"]})
    assert login.status_code == 204, login.text
    return created.json()


def test_new_user_defaults_to_spanish(client: TestClient) -> None:
    created = _register_and_login(client)
    assert created["feedback_language"] == "es"
    assert client.get("/api/users/me").json()["feedback_language"] == "es"


def test_patch_saves_and_returns_english(client: TestClient) -> None:
    _register_and_login(client)
    res = client.patch("/api/users/me/settings", json={"feedback_language": "en"})
    assert res.status_code == 200
    assert res.json()["feedback_language"] == "en"
    assert client.get("/api/users/me").json()["feedback_language"] == "en"


def test_patch_rejects_unsupported_language(client: TestClient) -> None:
    _register_and_login(client)
    res = client.patch("/api/users/me/settings", json={"feedback_language": "fr"})
    assert res.status_code == 422
    assert client.get("/api/users/me").json()["feedback_language"] == "es"


def test_patch_requires_authentication(client: TestClient) -> None:
    res = client.patch("/api/users/me/settings", json={"feedback_language": "en"})
    assert res.status_code == 401
