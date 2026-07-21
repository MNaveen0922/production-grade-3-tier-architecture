"""
smoke_test.py — post-deploy smoke test.

Unlike the integration tests (which run services as local subprocesses
against a test DB), this hits the REAL live ALB URL after a real
deployment — the last check before calling a rollout successful. It only
checks health/readiness, never mutates data (no signup/create-ticket
calls) since it can run against the actual production database.

Usage:
    python tests/smoke/smoke_test.py https://<alb-dns-name>
"""
import sys
import time

import requests

ENDPOINTS = [
    ("/health", "frontend"),
    ("/auth/health", "auth service"),
    ("/tickets/health", "ticket service"),
    ("/assign/health", "assignment service"),
]


def run(base_url: str, retries: int = 10, delay_seconds: int = 10) -> bool:
    base_url = base_url.rstrip("/")
    all_ok = True

    for path, label in ENDPOINTS:
        url = f"{base_url}{path}"
        ok = False

        for attempt in range(1, retries + 1):
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    print(f"[PASS] {label} ({url}) — 200 OK on attempt {attempt}")
                    ok = True
                    break
                print(f"[retry] {label} ({url}) — got {resp.status_code}, attempt {attempt}/{retries}")
            except requests.RequestException as e:
                print(f"[retry] {label} ({url}) — {e}, attempt {attempt}/{retries}")

            if attempt < retries:
                time.sleep(delay_seconds)

        if not ok:
            print(f"[FAIL] {label} ({url}) — did not return 200 after {retries} attempts")
            all_ok = False

    return all_ok


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python smoke_test.py <base_url>")
        sys.exit(2)

    success = run(sys.argv[1])
    sys.exit(0 if success else 1)
