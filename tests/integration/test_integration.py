"""
End-to-end flow across all three real services + real MySQL:
  signup -> signin -> create ticket -> assign ticket -> list my tickets

Each assertion checks data that only a real database round-trip could
produce (auto-increment IDs, persisted rows) — nothing here is mocked.
"""
import uuid

import requests


def test_full_ticket_lifecycle(running_services):
    auth_url = running_services["auth"]
    ticket_url = running_services["ticket"]
    assignment_url = running_services["assignment"]

    unique_email = f"agent-{uuid.uuid4().hex[:8]}@example.com"

    # ── 1. Sign up a new agent ─────────────────────────────────
    signup_resp = requests.post(f"{auth_url}/auth/signup", json={
        "name": "Test Agent",
        "email": unique_email,
        "password": "s3cure-password!",
    })
    assert signup_resp.status_code == 201, signup_resp.text
    user_id = signup_resp.json()["user_id"]

    # ── 2. Sign in with the same credentials ───────────────────
    signin_resp = requests.post(f"{auth_url}/auth/signin", json={
        "email": unique_email,
        "password": "s3cure-password!",
    })
    assert signin_resp.status_code == 200, signin_resp.text
    assert signin_resp.json()["user_id"] == user_id

    # Wrong password must be rejected — real bcrypt check, not a mock
    bad_signin = requests.post(f"{auth_url}/auth/signin", json={
        "email": unique_email,
        "password": "wrong-password",
    })
    assert bad_signin.status_code == 401

    # ── 3. Create a ticket ──────────────────────────────────────
    create_resp = requests.post(f"{ticket_url}/tickets", json={
        "title": "Integration test ticket",
        "description": "Created by the integration test suite",
        "priority": "medium",
    })
    assert create_resp.status_code == 201, create_resp.text
    ticket_id = create_resp.json()["ticket_id"]

    # Confirm it's really persisted — fetch it back by ID
    get_resp = requests.get(f"{ticket_url}/tickets/{ticket_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "Integration test ticket"

    # ── 4. Assign the ticket to the agent we just created ───────
    assign_resp = requests.post(f"{assignment_url}/assign", json={
        "user_id": user_id,
        "ticket_id": ticket_id,
    })
    assert assign_resp.status_code == 201, assign_resp.text

    # Assigning the same ticket to the same agent twice must be rejected
    dup_resp = requests.post(f"{assignment_url}/assign", json={
        "user_id": user_id,
        "ticket_id": ticket_id,
    })
    assert dup_resp.status_code == 409

    # ── 5. Confirm it shows up in "my tickets" ──────────────────
    my_tickets_resp = requests.get(f"{assignment_url}/assign/mytickets/{user_id}")
    assert my_tickets_resp.status_code == 200
    titles = [t["title"] for t in my_tickets_resp.json()]
    assert "Integration test ticket" in titles


def test_bulk_csv_import_end_to_end(running_services):
    """
    Uploads a real CSV to the real ticket service. Since SQS is unset in
    this environment, send_to_sqs() no-ops (see ticket_service.py) —
    this test verifies the CSV parsing / row validation logic end-to-end
    over real HTTP, not the SQS hand-off itself (that's covered by the
    ticket-service unit tests, which mock send_to_sqs and assert on what
    would have been queued).
    """
    ticket_url = running_services["ticket"]

    csv_content = (
        "title,description,priority\n"
        "Integration bulk row 1,First bulk row,low\n"
        "Integration bulk row 2,Second bulk row,high\n"
    )
    files = {"file": ("bulk.csv", csv_content, "text/csv")}

    resp = requests.post(f"{ticket_url}/tickets/import", files=files)

    assert resp.status_code == 202
    assert resp.json()["queued"] == 2
    assert resp.json()["skipped_rows"] == 0
