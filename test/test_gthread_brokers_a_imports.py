"""Every brokers_a module the Flask process loads imports cleanly, in each runtime.

The gthread changes touched eighteen broker plugins' order, data, rate limit
and websocket modules. A plugin loads lazily, on the first request that needs
it, so an import error would surface as a failed order hours after a restart
rather than at startup. Each module is imported here in a child process: once
as the development server and the gthread worker see it (nothing patched), and
once under a real ``eventlet.monkey_patch()`` (Linux only), the production
default. The child also checks that importing a broker never imports eventlet
into a process nothing patched.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from importlib.util import find_spec
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


#: A child reads no .env. utils.config calls load_dotenv(override=True) at
#: import, which would replace the isolated settings a test passes the child
#: with the installation's own; test/conftest.py does the same in this process.
NO_DOTENV = (
    "import dotenv\n"
    "dotenv.load_dotenv = lambda *args, **kwargs: False\n"
    "dotenv.main.load_dotenv = dotenv.load_dotenv\n"
)


def _no_dotenv(script: str) -> str:
    """Put NO_DOTENV into a child script, after eventlet's patch if it has one."""
    script = textwrap.dedent(script)
    marker = "eventlet.monkey_patch()\n"
    if marker in script:
        head, tail = script.split(marker, 1)
        return head + marker + NO_DOTENV + tail
    return NO_DOTENV + script


BROKERS = [
    "aliceblue",
    "angel",
    "arrow",
    "compositedge",
    "definedge",
    "deltaexchange",
    "dhan",
    "dhan_sandbox",
    "firstock",
    "fivepaisa",
    "fivepaisaxts",
    "flattrade",
    "fyers",
    "groww",
    "hdfcsecurities",
    "hdfcsky",
    "ibulls",
    "iifl",
]


def _modules(broker: str) -> list[str]:
    """The modules of one plugin that run inside the Flask process."""
    root = REPO / "broker" / broker
    names = []
    for folder in ("api", "mapping", "database"):
        for path in sorted((root / folder).glob("*.py")):
            if path.name != "__init__.py":
                names.append(f"broker.{broker}.{folder}.{path.stem}")
    # Order-update adapters run in Flask too (services/order_update_service).
    for path in sorted((root / "streaming").glob("*order_adapter.py")):
        names.append(f"broker.{broker}.streaming.{path.stem}")
    return names


def _child_env(tmp_path: Path) -> dict:
    env = dict(os.environ)
    db = tmp_path / "db"
    db.mkdir(exist_ok=True)
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
            "BROKER_API_KEY": "client:::key:::secret",
            "BROKER_API_SECRET": "secret",
            "PYTHONPATH": str(REPO),
        }
    )
    env.pop("OPENALGO_WORKER_CLASS", None)
    return env


EVENTLET_PREAMBLE = """import eventlet
eventlet.monkey_patch()
"""


def _import_all(tmp_path: Path, preamble: str, broker: str) -> subprocess.CompletedProcess:
    patched = bool(preamble)
    body = preamble + textwrap.dedent(
        f"""
        import importlib, sys
        # The app imports websocket_proxy at startup, before any plugin; a
        # streaming package imported first would meet an import cycle the app
        # never does.
        import websocket_proxy
        failed = []
        for name in {_modules(broker)!r}:
            try:
                importlib.import_module(name)
            except Exception as exc:
                failed.append(f"{{name}}: {{type(exc).__name__}}: {{exc}}")
        assert not failed, "; ".join(failed)
        if not {patched!r}:
            assert "eventlet" not in sys.modules, "a {broker} module imported eventlet"
        print("OK", len({_modules(broker)!r}))
        """
    )
    return subprocess.run(
        [sys.executable, "-c", _no_dotenv(body)],
        cwd=str(REPO),
        env=_child_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.parametrize("broker", BROKERS)
def test_every_module_imports_without_eventlet(broker, tmp_path):
    result = _import_all(tmp_path, "", broker)
    assert "OK" in result.stdout, result.stdout[-2000:] + result.stderr[-4000:]


@pytest.mark.skipif(find_spec("eventlet") is None, reason="eventlet is not installed (Windows dev)")
@pytest.mark.parametrize("broker", BROKERS)
def test_every_module_imports_under_eventlet(broker, tmp_path):
    result = _import_all(tmp_path, EVENTLET_PREAMBLE, broker)
    assert "OK" in result.stdout, result.stdout[-2000:] + result.stderr[-4000:]
