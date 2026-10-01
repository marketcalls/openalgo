"""Every module in the brokers_b plugins imports, under each runtime.

The gthread changes in these plugins add imports from utils (runtime,
broker_backpressure, smart_order_guard, shared_executors) and module-level
state (limiters, gates, pools). A module that fails to import takes its whole
broker down at login, so each one is imported here: in this process, as the
development server and the gthread worker do (nothing patched), and in a
subprocess under a real eventlet monkey patch, as production does.

The websocket proxy package is imported first, as the app does: it and the
streaming packages import each other, and the cycle only resolves in that
order.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import textwrap
from importlib.util import find_spec
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

BROKERS = [
    "iiflcapital",
    "indmoney",
    "jainamxts",
    "kotak",
    "motilal",
    "mstock",
    "nubra",
    "paytm",
    "pocketful",
    "rmoney",
    "samco",
    "shoonya",
    "tradejini",
    "tradesmart",
    "upstox",
    "wisdom",
    "zebu",
    "zerodha",
]


def _modules(broker: str) -> list[str]:
    root = REPO / "broker" / broker
    names = []
    for package in ("api", "database", "mapping", "streaming"):
        folder = root / package
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.py")):
            stem = path.stem
            names.append(f"broker.{broker}.{package}" + ("" if stem == "__init__" else f".{stem}"))
    return names


@pytest.mark.parametrize("broker", BROKERS)
def test_every_module_imports(broker):
    importlib.import_module("websocket_proxy")
    modules = _modules(broker)
    assert any(name.endswith(".api.order_api") for name in modules), modules
    for name in modules:
        importlib.import_module(name)


@pytest.mark.skipif(find_spec("eventlet") is None, reason="eventlet is not installed")
def test_every_module_imports_under_eventlet(tmp_path):
    modules = [name for broker in BROKERS for name in _modules(broker)]
    db = tmp_path / "db"
    db.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{(db / 'openalgo.db').as_posix()}",
            "SANDBOX_DATABASE_URL": f"sqlite:///{(db / 'sandbox.db').as_posix()}",
            "LOGS_DATABASE_URL": f"sqlite:///{(db / 'logs.db').as_posix()}",
            "LATENCY_DATABASE_URL": f"sqlite:///{(db / 'latency.db').as_posix()}",
            "HEALTH_DATABASE_URL": f"sqlite:///{(db / 'health.db').as_posix()}",
            "LOG_DIR": str(tmp_path / "log"),
            "LOG_TO_FILE": "False",
            "API_KEY_PEPPER": "0" * 64,
            "APP_KEY": "test-only-app-key",
            "BROKER_API_KEY": "test",
            "BROKER_API_SECRET": "test",
            "PYTHONPATH": str(REPO),
        }
    )
    env.pop("OPENALGO_WORKER_CLASS", None)
    script = textwrap.dedent(
        f"""
        import eventlet
        eventlet.monkey_patch()

        import dotenv
        dotenv.load_dotenv = lambda *a, **k: False
        dotenv.main.load_dotenv = dotenv.load_dotenv

        import importlib
        importlib.import_module("websocket_proxy")
        for name in {modules!r}:
            importlib.import_module(name)

        from utils import runtime
        assert runtime.worker_class() == "eventlet"
        assert runtime.gthread_active() is False
        print("OK", len({modules!r}))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert "OK" in result.stdout, result.stdout[-3000:] + result.stderr[-3000:]
