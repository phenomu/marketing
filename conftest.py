# Make repo root importable for tests regardless of how pytest is invoked.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Isolate tests from the developer's .env: force a temp SQLite database
# unless the caller explicitly exports DATABASE_URL (e.g. CI against Postgres).
import os

if "DATABASE_URL" not in os.environ and "POSTGRES_PASSWORD" not in os.environ:
    os.environ["DATABASE_URL"] = f"sqlite:///{ROOT / 'data' / 'marketing-test.db'}"

# Auth must be OFF for the suite as a whole — test_auth.py monkeypatches
# the token reader per test. A stray API_AUTH_TOKEN from the environment
# (e.g. exported in a production shell or CI matrix) would 401 every
# unrelated API test.
os.environ.pop("API_AUTH_TOKEN", None)
