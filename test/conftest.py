"""Safe environment defaults for tests collected outside an installation.

Every database URL is pinned to a test file. The sandbox one matters most:
without it the sandbox suite runs against db/sandbox.db - the user's real
analyzer database - so a test that resets funds or creates a GTT mutates live
sandbox state, and results depend on whatever that database happened to hold.
"""

import os

os.environ.setdefault("API_KEY_PEPPER", "0" * 64)
os.environ.setdefault("APP_KEY", "test-only-app-key")

os.environ.setdefault("DATABASE_URL", "sqlite:///db/openalgo-test.db")
os.environ.setdefault("SANDBOX_DATABASE_URL", "sqlite:///db/sandbox-test.db")
os.environ.setdefault("LOGS_DATABASE_URL", "sqlite:///db/logs-test.db")
os.environ.setdefault("LATENCY_DATABASE_URL", "sqlite:///db/latency-test.db")
