"""
Unit tests for the assignment service. get_db() and send_to_sqs() are
mocked — no real MySQL/SQS involved.
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import assignment_service


@pytest.fixture
def client():
    return TestClient(assignment_service.app)


@pytest.fixture
def mock_sqs(monkeypatch):
    sent = []
    monkeypatch.setattr(assignment_service, "send_to_sqs", lambda msg: sent.append(msg))
    return sent


def test_health(client):
    resp = client.get("/assign/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_assign_404_when_ticket_missing(client, monkeypatch, mock_sqs):
    cursor = MagicMock()
    cursor.fetchone.return_value = None  # ticket lookup fails
    conn = MagicMock()
    conn.cursor.return_value = cursor
    monkeypatch.setattr(assignment_service, "get_db", lambda: conn)

    resp = client.post("/assign", json={"user_id": 1, "ticket_id": 999})

    assert resp.status_code == 404


def test_assign_409_when_already_assigned(client, monkeypatch, mock_sqs):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"id": 5, "title": "VPN issue", "priority": "high"},  # ticket exists
        {"id": 1},                                            # already assigned
    ]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    monkeypatch.setattr(assignment_service, "get_db", lambda: conn)

    resp = client.post("/assign", json={"user_id": 1, "ticket_id": 5})

    assert resp.status_code == 409


def test_assign_succeeds_and_publishes_notification(client, monkeypatch, mock_sqs):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"id": 5, "title": "VPN issue", "priority": "high"},        # ticket exists
        None,                                                        # not already assigned
        {"name": "Grace Hopper", "email": "grace@example.com"},      # agent lookup
    ]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    monkeypatch.setattr(assignment_service, "get_db", lambda: conn)

    resp = client.post("/assign", json={"user_id": 1, "ticket_id": 5})

    assert resp.status_code == 201
    conn.commit.assert_called_once()
    assert len(mock_sqs) == 1
    assert mock_sqs[0]["event_type"] == "ticket_assigned"
    assert mock_sqs[0]["user_email"] == "grace@example.com"
    assert mock_sqs[0]["ticket_title"] == "VPN issue"


def test_my_tickets_returns_rows(client, monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"title": "VPN issue", "priority": "high", "status": "open"}
    ]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    monkeypatch.setattr(assignment_service, "get_db", lambda: conn)

    resp = client.get("/assign/mytickets/1")

    assert resp.status_code == 200
    assert resp.json()[0]["title"] == "VPN issue"
