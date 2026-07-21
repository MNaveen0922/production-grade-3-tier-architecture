import os
import sys

# Tests run via `pytest app/auth/tests` from the repo root, so app/auth
# itself (where auth_service.py and secrets.py live) isn't on sys.path
# by default — pytest only auto-adds the tests/ directory itself.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# secrets.py falls back to plain env vars when AWS_SSM_PATH is unset —
# exactly the local/CI dev mode this test suite runs in. No real AWS
# calls happen during unit tests.
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "supportdesk_test")
os.environ.setdefault("DB_USER", "root")
os.environ.setdefault("DB_PASSWORD", "test")
