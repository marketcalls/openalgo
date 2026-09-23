"""Every scoped session under database/ is released by the teardown sweep.

Under the gthread worker request threads are pooled and never exit, so a
scoped session the per-request sweep does not know about stays open on its
thread from one request to the next: a connection held, and an identity map
that can be a day's master contract re-download out of date. Under eventlet
each request's greenlet took its sessions with it. The sweep
(utils.db_sessions.remove_all_scoped_sessions) covers a fixed list plus every
loaded broker master-contract module; this tripwire keeps the list complete.
"""

from __future__ import annotations

import ast
from pathlib import Path

from utils import db_sessions

REPO = Path(__file__).resolve().parents[1]


def _scoped_sessions_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if called != "scoped_session":
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
    return names


def test_every_database_scoped_session_is_swept():
    listed = set(db_sessions.SCOPED_SESSION_MODULES)
    missing = []
    for path in sorted((REPO / "database").glob("*.py")):
        module = f"database.{path.stem}"
        for attr in _scoped_sessions_in(path):
            if (module, attr) not in listed:
                missing.append(f"{module}.{attr}")
    assert missing == [], (
        "Add these to utils/db_sessions.SCOPED_SESSION_MODULES so pooled "
        f"request threads release them: {missing}"
    )


def test_broker_master_contract_sessions_are_found_by_name():
    # Loaded broker modules are swept without being listed; the naming rule
    # is what makes that work, so pin it.
    sample = sorted((REPO / "broker").glob("*/database/master_contract_db.py"))
    assert sample, "no broker master contract modules found"
    for path in sample[:5]:
        assert "db_session" in _scoped_sessions_in(path), path
