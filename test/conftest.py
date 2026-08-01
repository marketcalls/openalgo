"""Safe environment defaults for tests collected outside an installation."""

import os

os.environ.setdefault("API_KEY_PEPPER", "0" * 64)
os.environ.setdefault("DATABASE_URL", "sqlite:///db/openalgo-test.db")
os.environ.setdefault("APP_KEY", "test-only-app-key")
