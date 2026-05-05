"""Shared pytest fixtures + sys.path setup.

Adds the project root to sys.path so tests can `from utils import ...`,
`from services.strategy import ...`, etc. without needing the project
to be pip-installed.
"""

import os
import sys

# Repo root = parent of `test/`
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
