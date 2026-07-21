"""
Unit tests for the auth service.

These mock get_db() entirely — no real MySQL connection is made. That's
deliberate: unit tests should run in milliseconds and never depend on
external infrastructure. Real end-to-end DB behavior is covered by
tests/integration/test_integration.py instead.
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import auth_service


@pytest.fixture
def client():
    return TestClient(auth_service.app)


def test_hash_and_check_password_roundtrip():
    hashed = auth_service.hash_password("correct-horse-battery-staple")
    assert hashed != "correct-horse-battery-staple"  # never store plaintext
    assert auth_service.check_password("correct-horse-battery-staple", hashed)
    assert not auth_service.check_password("wrong-password", hashed)


def test_health_reports_healthy_when_db_reachable(client, monkeypatch):
    fake_conn = MagicMock()
    monkeypatch.setattr(auth_service, "get_db", lambda: fake_conn)

    resp = client.get("/auth/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"
    fake_conn.close.assert_called_once()


def test_health_reports_unhealthy_when_db_unreachable(client, monkeypatch):
    def broken_db():
        raise ConnectionError("could not connect")

    monkeypatch.setattr(auth_service, "get_db", broken_db)

    resp = client.get("/auth/health")

    assert resp.status_code == 500
    assert resp.json()["detail"]["status"] == "unhealthy"


def test_signup_rejects_missing_fields(client):
    resp = client.post("/auth/signup", json={"name": "Ada"})  # no email/password
    assert resp.status_code == 422  # Pydantic validation, not app logic


def test_signup_conflicts_on_existing_email(client, monkeypatch):
    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = {"id": 1}  # email already exists
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    monkeypatch.setattr(auth_service, "get_db", lambda: fake_conn)

    resp = client.post("/auth/signup", json={
        "name": "Ada", "email": "ada@example.com", "password": "s3cret123"
    })

    assert resp.status_code == 409


def test_signup_creates_user_when_email_is_new(client, monkeypatch):
    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = None  # no existing user
    fake_cursor.lastrowid = 42
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    monkeypatch.setattr(auth_service, "get_db", lambda: fake_conn)

    resp = client.post("/auth/signup", json={
        "name": "Ada", "email": "ada@example.com", "password": "s3cret123"
    })

    assert resp.status_code == 201
    assert resp.json()["user_id"] == 42
    fake_conn.commit.assert_called_once()


def test_signin_rejects_unknown_user(client, monkeypatch):
    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = None
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    monkeypatch.setattr(auth_service, "get_db", lambda: fake_conn)

    resp = client.post("/auth/signin", json={"email": "nobody@example.com", "password": "x"})

    assert resp.status_code == 404


def test_signin_rejects_wrong_password(client, monkeypatch):
    hashed = auth_service.hash_password("correct-password")
    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = {
        "id": 1, "name": "Ada", "email": "ada@example.com", "password": hashed
    }
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    monkeypatch.setattr(auth_service, "get_db", lambda: fake_conn)

    resp = client.post("/auth/signin", json={"email": "ada@example.com", "password": "wrong"})

    assert resp.status_code == 401


def test_signin_succeeds_with_correct_credentials(client, monkeypatch):
    hashed = auth_service.hash_password("correct-password")
    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = {
        "id": 1, "name": "Ada", "email": "ada@example.com", "password": hashed
    }
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    monkeypatch.setattr(auth_service, "get_db", lambda: fake_conn)

    resp = client.post("/auth/signin", json={"email": "ada@example.com", "password": "correct-password"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == 1
    assert body["email"] == "ada@example.com"


def test_metrics_endpoint_is_exposed(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"http_requests" in resp.content or b"# HELP" in resp.content
