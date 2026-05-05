"""Shared pytest fixtures + sys.path setup.

Adds the project root to sys.path so tests can `from utils import ...`,
`from services.strategy import ...`, etc. without needing the project
to be pip-installed.

Also loads .env so tests pick up DATABASE_URL and APP_KEY (the production
DB modules build engines at import time from os.getenv).
"""

import os
import sys

# Repo root = parent of `test/`
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Load .env early — before any test module imports DB-touching code.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_REPO_ROOT, ".env"))
except ImportError:
    # python-dotenv is in deps; if it's missing we'll fail loud later anyway.
    pass

# Provide a deterministic APP_KEY fallback for unit tests so
# utils.secret_box.encrypt_at_rest doesn't blow up if the developer hasn't
# set APP_KEY in their env. The secret_box test fixture overrides this with
# its own value.
os.environ.setdefault("APP_KEY", "openalgo-test-app-key-deterministic-32b")
