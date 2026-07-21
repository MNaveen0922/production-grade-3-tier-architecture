"""
conftest.py — integration test fixtures.

Unlike the unit tests (which mock get_db() entirely), these tests run the
THREE REAL FastAPI apps as subprocesses (uvicorn) against a REAL MySQL
database — no mocks anywhere. This is what actually proves the services,
the schema, and the SQS-publish code path fit together correctly.

Where the MySQL instance comes from is intentionally NOT docker-compose —
this project doesn't use one. In CI (.github/workflows/ci-cd.yml) it's a
native GitHub Actions `services:` container. Locally, point the env vars
below at any reachable MySQL 8 instance with schema.sql already applied.

SQS/SNS calls are skipped, not mocked — send_to_sqs() in each service
already no-ops when SQS_QUEUE_URL is unset (see each service's own
comments), so leaving it unset here exercises the exact same "local dev
mode" code path real engineers hit before AWS credentials exist.
"""
import os
import socket
import subprocess
import sys
import time

import pytest
import requests

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

SERVICES = {
    "auth":       {"dir": "app/auth",       "module": "auth_service",       "port": 8001, "health": "/auth/health"},
    "ticket":     {"dir": "app/ticket",      "module": "ticket_service",     "port": 8002, "health": "/tickets/health"},
    "assignment": {"dir": "app/assignment",  "module": "assignment_service", "port": 8003, "health": "/assign/health"},
}

TEST_ENV = {
    "DB_HOST":     os.getenv("TEST_DB_HOST", "127.0.0.1"),
    "DB_NAME":     os.getenv("TEST_DB_NAME", "supportdesk"),
    "DB_USER":     os.getenv("TEST_DB_USER", "root"),
    "DB_PASSWORD": os.getenv("TEST_DB_PASSWORD", "root"),
    # AWS_SSM_PATH deliberately left unset — forces secrets.py's local
    # dev fallback, which reads exactly the env vars above.
}


def _wait_for_port(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


@pytest.fixture(scope="session")
def running_services():
    """
    Starts all three FastAPI services as real subprocesses for the whole
    test session, and tears them down afterward. Each runs uvicorn
    directly (not gunicorn) since we only need one worker for tests.
    """
    procs = []
    env = {**os.environ, **TEST_ENV}

    for name, cfg in SERVICES.items():
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", f"{cfg['module']}:app",
             "--host", "127.0.0.1", "--port", str(cfg["port"])],
            cwd=os.path.join(REPO_ROOT, cfg["dir"]),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        procs.append((name, proc))

    for name, cfg in SERVICES.items():
        if not _wait_for_port(cfg["port"]):
            _dump_logs(procs)
            pytest.fail(f"{name} service did not start listening on port {cfg['port']}")

    # Confirm every /health endpoint actually reports healthy (DB reachable)
    # before running any test — fail fast with clear output instead of
    # every individual test timing out against a half-started service.
    for name, cfg in SERVICES.items():
        url = f"http://127.0.0.1:{cfg['port']}{cfg['health']}"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            _dump_logs(procs)
            pytest.fail(f"{name} health check failed: {resp.status_code} {resp.text}")

    yield {name: f"http://127.0.0.1:{cfg['port']}" for name, cfg in SERVICES.items()}

    for _, proc in procs:
        proc.terminate()
    for _, proc in procs:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _dump_logs(procs):
    for name, proc in procs:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=5)
            print(f"\n----- {name} service output -----\n{out.decode(errors='replace')}")
        except Exception:
            pass
