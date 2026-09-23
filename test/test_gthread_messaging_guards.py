"""Messaging code asks whether eventlet patched the process, never whether it was imported.

Under the gthread worker eventlet stays installed as the fallback, and several
modules used to import it merely to ask about it. Every ``"eventlet" in
sys.modules`` test then took its eventlet branch in a process nothing had
patched, and which path the Telegram bot took depended on what the process
happened to import first. ``utils.runtime.is_monkey_patched`` answers the real
question without importing eventlet; these tests keep the messaging files on it.

Also here: the two dead Telegram service variants stay deleted, because a
future import of either would start a second bot class with its own poller.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

MESSAGING_GLOBS = (
    "blueprints/mcp_http.py",
    "blueprints/mcp_oauth.py",
    "mcp/**/*.py",
    "services/whatsapp_*.py",
    "blueprints/whatsapp*.py",
    "services/telegram_*.py",
    "blueprints/telegram.py",
    "restx_api/telegram_bot.py",
    "services/agent/**/*.py",
    "blueprints/agent.py",
    "utils/email_utils.py",
    "services/*alert*.py",
    "blueprints/*alert*.py",
)


def _messaging_files() -> list[Path]:
    files: set[Path] = set()
    for pattern in MESSAGING_GLOBS:
        files.update(p for p in REPO.glob(pattern) if p.is_file())
    return sorted(files)


def _is_eventlet_import_test(node: ast.AST) -> bool:
    """``"eventlet..." in sys.modules`` (or ``not in``), in code, not in a string."""
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return False
    if not isinstance(node.ops[0], (ast.In, ast.NotIn)):
        return False
    left, right = node.left, node.comparators[0]
    return (
        isinstance(left, ast.Constant)
        and isinstance(left.value, str)
        and left.value.startswith("eventlet")
        and isinstance(right, ast.Attribute)
        and right.attr == "modules"
        and isinstance(right.value, ast.Name)
        and right.value.id == "sys"
    )


def _imports_eventlet(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name.split(".")[0] == "eventlet" for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[0] == "eventlet"
    return False


def test_the_scan_covers_the_partition():
    names = {p.relative_to(REPO).as_posix() for p in _messaging_files()}
    for expected in (
        "services/telegram_bot_service.py",
        "blueprints/telegram.py",
        "services/agent/chatgpt_oauth.py",
        "blueprints/mcp_http.py",
        "services/whatsapp_bot_service.py",
    ):
        assert expected in names


def test_no_messaging_file_tests_whether_eventlet_was_imported():
    offenders = []
    for path in _messaging_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if _is_eventlet_import_test(node) or _imports_eventlet(node):
                offenders.append(f"{path.relative_to(REPO).as_posix()}:{node.lineno}")
    assert offenders == [], (
        "use utils.runtime.is_monkey_patched() (or utils.real_threading) instead: "
        + ", ".join(offenders)
    )


def test_the_dead_telegram_variants_stay_deleted():
    for name in ("telegram_bot_service_fixed.py", "telegram_bot_service_v2.py"):
        assert not (REPO / "services" / name).exists(), name
    for folder in ("services", "blueprints", "restx_api", "utils", "database"):
        for path in (REPO / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "telegram_bot_service_fixed" not in text, path
            assert "telegram_bot_service_v2" not in text, path
    app_text = (REPO / "app.py").read_text(encoding="utf-8")
    assert "telegram_bot_service_fixed" not in app_text
    assert "telegram_bot_service_v2" not in app_text


def _eventlet_installed() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("eventlet") is not None
    except (ImportError, ValueError):
        return False


@pytest.mark.skipif(not _eventlet_installed(), reason="eventlet is not installed (Windows dev)")
def test_an_unpatched_eventlet_import_changes_no_telegram_path(tmp_path):
    """The gthread case: eventlet imported, nothing patched.

    The bot's threads are the stdlib's own, so ``threading.enumerate()`` and
    thread dumps still see them, and a token is validated the one synchronous
    way, without an asyncio loop.
    """
    body = textwrap.dedent(
        """
        import asyncio, sys, threading, types
        import eventlet  # imported, never patched

        from utils import real_threading, runtime
        assert runtime.is_monkey_patched() is False

        import services.telegram_bot_service as tg
        assert tg.original_threading is threading
        assert real_threading.Thread is threading.Thread
        svc = tg.TelegramBotService()
        assert isinstance(svc._gen_stop, threading.Event)

        import utils.httpx_client as hc

        class R:
            status_code = 200
            def json(self):
                return {"ok": True, "result": {"username": "b"}}

        hc.get_httpx_client = lambda: types.SimpleNamespace(get=lambda url, timeout=None: R())
        tg.update_bot_config = lambda values: True

        def refuse(*a, **k):
            raise AssertionError("an asyncio loop was created")

        asyncio.new_event_loop = refuse
        ok, message = svc.initialize_bot_sync("t")
        assert ok, message
        print("OK")
        """
    )
    env = dict(os.environ)
    db = tmp_path / "db"
    db.mkdir()
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{(db / 'openalgo.db').as_posix()}",
            "LOG_DIR": str(tmp_path / "log"),
            "API_KEY_PEPPER": "0" * 64,
            "APP_KEY": "test-only-app-key",
            "PYTHONPATH": str(REPO),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", body],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr
