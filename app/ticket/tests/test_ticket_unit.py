"""
Unit tests for the ticket service. get_db() and send_to_sqs() are both
mocked — these tests verify request/response behavior and the
CSV-parsing logic in /tickets/import, not real MySQL or SQS.
"""
import io
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import ticket_service


@pytest.fixture
def client():
    return TestClient(ticket_service.app)


@pytest.fixture
def mock_db(monkeypatch):
    fake_cursor = MagicMock()
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    monkeypatch.setattr(ticket_service, "get_db", lambda: fake_conn)
    return fake_conn, fake_cursor


@pytest.fixture
def mock_sqs(monkeypatch):
    sent = []
    monkeypatch.setattr(ticket_service, "send_to_sqs", lambda msg: sent.append(msg))
    return sent


def test_health(client):
    resp = client.get("/tickets/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_get_tickets_returns_rows(client, mock_db):
    _, cursor = mock_db
    cursor.fetchall.return_value = [
        {"id": 1, "title": "VPN issue", "priority": "high"}
    ]

    resp = client.get("/tickets")

    assert resp.status_code == 200
    assert resp.json()[0]["title"] == "VPN issue"


def test_get_single_ticket_404_when_missing(client, mock_db):
    _, cursor = mock_db
    cursor.fetchone.return_value = None

    resp = client.get("/tickets/999")

    assert resp.status_code == 404


def test_create_ticket_rejects_missing_fields(client, mock_db, mock_sqs):
    resp = client.post("/tickets", json={"title": "", "description": ""})
    assert resp.status_code == 400


def test_create_ticket_publishes_new_ticket_event(client, mock_db, mock_sqs):
    _, cursor = mock_db
    cursor.lastrowid = 7

    resp = client.post("/tickets", json={
        "title": "Printer jam", "description": "Jams every print job", "priority": "low"
    })

    assert resp.status_code == 201
    assert resp.json()["ticket_id"] == 7
    assert len(mock_sqs) == 1
    assert mock_sqs[0]["event_type"] == "new_ticket_created"
    assert mock_sqs[0]["ticket_title"] == "Printer jam"


def test_bulk_import_queues_one_message_per_valid_row(client, mock_sqs):
    csv_content = (
        "title,description,priority\n"
        "Printer jam,Printer on 2nd floor keeps jamming,low\n"
        "VPN drops,VPN disconnects every 20 min,high\n"
        ",missing title,medium\n"  # invalid row — should be skipped
    )
    files = {"file": ("tickets.csv", io.BytesIO(csv_content.encode()), "text/csv")}

    resp = client.post("/tickets/import", files=files)

    assert resp.status_code == 202
    body = resp.json()
    assert body["queued"] == 2
    assert body["skipped_rows"] == 1
    assert len(mock_sqs) == 2
    assert all(m["event_type"] == "bulk_ticket_import" for m in mock_sqs)
