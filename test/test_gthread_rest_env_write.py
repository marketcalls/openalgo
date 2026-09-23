"""Saving broker credentials is one locked, atomic rewrite of .env.

``POST /api/broker/credentials`` used to read .env, edit it in memory and
write it back through ``open(path, "w")`` with no lock. Two saves at once (two
tabs, or this save racing the admin MCP settings save or a startup rotation)
read the same file, and the second write dropped the first one's values; and
a save interrupted between the truncate and the write left .env cut short,
which the app and the launcher both read at the next start.

It now collects every value, validates all of them, and writes them in one
``utils.env_check.update_env_values`` call: a read-modify-write under the
process-wide ``ENV_WRITE_LOCK`` every .env writer shares, through an atomic
replace. A single save writes what it always wrote. A value containing a line
break is refused with a sentence instead of being written as two lines.

The view is called below its session decorator inside a request context, so
no login is needed, and .env is a temporary file.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
import textwrap
import threading
import time
from importlib.util import find_spec
from pathlib import Path

import pytest
from dotenv import dotenv_values
from flask import Flask

import utils.env_check as env_check
from blueprints import broker_credentials

REPO = Path(__file__).resolve().parents[1]

ENV_TEXT = (
    "# OpenAlgo settings\n"
    "BROKER_API_KEY = 'old-key'\n"
    "BROKER_API_SECRET = 'old-secret'\n"
    "REDIRECT_URL = 'http://127.0.0.1:5000/zerodha/callback'\n"
    "VALID_BROKERS = 'zerodha,dhan'\n"
    "HOST_SERVER = 'http://127.0.0.1:5000'\n"
    "WEBSOCKET_URL = 'ws://127.0.0.1:8765'\n"
)

_update_credentials = inspect.unwrap(broker_credentials.update_credentials)
_app = Flask(__name__)


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_bytes(ENV_TEXT.encode("utf-8"))
    monkeypatch.setattr(broker_credentials, "get_env_path", lambda: str(path))
    monkeypatch.setenv("VALID_BROKERS", "zerodha,dhan")
    return path


def _post(payload: dict):
    with _app.test_request_context("/api/broker/credentials", method="POST", json=payload):
        result = _update_credentials()
    response, status = result if isinstance(result, tuple) else (result, 200)
    return status, response.get_json()


def test_two_saves_at_once_keep_both_values(env_file, monkeypatch):
    """The defect: both saves read the same file and the second dropped the first."""
    # Widen the window between reading and writing on either code path: the
    # old writer read through read_env_file(), the new one writes through the
    # atomic replace (inside the shared lock).
    original_read = getattr(broker_credentials, "read_env_file", None)
    if original_read is not None:

        def slow_read():
            result = original_read()
            time.sleep(0.05)
            return result

        monkeypatch.setattr(broker_credentials, "read_env_file", slow_read)

    original_replace = env_check._atomic_replace_text

    def slow_replace(path, content):
        time.sleep(0.05)
        original_replace(path, content)

    monkeypatch.setattr(env_check, "_atomic_replace_text", slow_replace)

    barrier = threading.Barrier(2)
    statuses = []

    def save(payload):
        barrier.wait()
        statuses.append(_post(payload)[0])

    threads = [
        threading.Thread(target=save, args=({"broker_api_key": "new-key"},)),
        threading.Thread(target=save, args=({"host_server": "https://algo.example.com"},)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert statuses == [200, 200]
    values = dotenv_values(env_file)
    assert values["BROKER_API_KEY"] == "new-key"
    assert values["HOST_SERVER"] == "https://algo.example.com"
    assert values["BROKER_API_SECRET"] == "old-secret"


def test_a_save_racing_another_env_writer_keeps_both(env_file, monkeypatch):
    """The credentials save and update_env_values share one lock."""
    original_replace = env_check._atomic_replace_text

    def slow_replace(path, content):
        time.sleep(0.05)
        original_replace(path, content)

    monkeypatch.setattr(env_check, "_atomic_replace_text", slow_replace)
    barrier = threading.Barrier(2)

    def save():
        barrier.wait()
        _post({"broker_api_secret": "new-secret"})

    def other_writer():
        barrier.wait()
        env_check.update_env_values(str(env_file), {"MCP_HTTP_ENABLED": "TRUE"})

    threads = [threading.Thread(target=save), threading.Thread(target=other_writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    values = dotenv_values(env_file)
    assert values["BROKER_API_SECRET"] == "new-secret"
    assert values["MCP_HTTP_ENABLED"] == "TRUE"


def test_a_single_save_writes_what_it_always_wrote(env_file):
    status, body = _post(
        {
            "broker_api_key": "abc:::def",
            "redirect_url": "http://127.0.0.1:5000/dhan/callback",
            "ngrok_allow": False,
            "websocket_url": "wss://algo.example.com/ws",
        }
    )
    assert status == 200
    assert body["status"] == "success"
    assert body["updated_fields"] == [
        "BROKER_API_KEY",
        "REDIRECT_URL",
        "NGROK_ALLOW",
        "WEBSOCKET_URL",
    ]
    assert body["restart_required"] is True

    text = env_file.read_text(encoding="utf-8")
    assert "BROKER_API_KEY = 'abc:::def'\n" in text
    assert "REDIRECT_URL = 'http://127.0.0.1:5000/dhan/callback'\n" in text
    assert text.endswith("NGROK_ALLOW = 'FALSE'\n")
    assert text.startswith("# OpenAlgo settings\n")
    assert "BROKER_API_SECRET = 'old-secret'\n" in text


def test_a_value_with_a_single_quote_is_double_quoted_as_before(env_file):
    status, _ = _post({"broker_api_secret": "it's-secret"})
    assert status == 200
    assert dotenv_values(env_file)["BROKER_API_SECRET"] == "it's-secret"


def test_crlf_line_endings_are_kept(env_file):
    env_file.write_bytes(ENV_TEXT.replace("\n", "\r\n").encode("utf-8"))
    assert _post({"broker_api_key": "crlf-key"})[0] == 200
    raw = env_file.read_bytes()
    assert b"BROKER_API_KEY = 'crlf-key'\r\n" in raw
    assert raw.count(b"\r\n") == raw.count(b"\n")


def test_a_line_break_in_a_value_is_refused_and_nothing_is_written(env_file):
    status, body = _post({"broker_api_key": "abc\nAPP_KEY = 'forged'"})
    assert status == 400
    assert "line break" in body["message"]
    assert env_file.read_bytes() == ENV_TEXT.encode("utf-8")


def test_a_validation_failure_writes_nothing(env_file):
    status, _ = _post({"broker_api_key": "new-key", "host_server": "algo.example.com"})
    assert status == 400
    assert env_file.read_bytes() == ENV_TEXT.encode("utf-8")


def test_nothing_to_update_is_a_400(env_file):
    assert _post({})[0] == 400


def test_a_missing_env_file_is_a_500_as_before(env_file):
    env_file.unlink()
    status, body = _post({"broker_api_key": "new-key"})
    assert status == 500
    assert body["message"] == "Failed to read .env file: Environment file not found"


# --- eventlet neutrality -----------------------------------------------------


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
            "VALID_BROKERS": "zerodha,dhan",
            "PYTHONPATH": str(REPO),
        }
    )
    env.pop("OPENALGO_WORKER_CLASS", None)
    env.pop("OPENALGO_EFFECTIVE_THREADS", None)
    return env


@pytest.mark.skipif(find_spec("eventlet") is None, reason="eventlet is not installed (Windows dev)")
def test_under_eventlet_two_greenlet_saves_keep_both_values(tmp_path):
    """The save under a real monkey_patch: greenlets serialise, nothing hangs."""
    env_path = tmp_path / ".env"
    env_path.write_bytes(ENV_TEXT.encode("utf-8"))
    body = f"""
        import eventlet
        eventlet.monkey_patch()

        import dotenv
        dotenv.load_dotenv = lambda *a, **k: False
        dotenv.main.load_dotenv = dotenv.load_dotenv

        import inspect, time
        from flask import Flask
        import utils.env_check as env_check
        from blueprints import broker_credentials

        broker_credentials.get_env_path = lambda: {str(env_path)!r}
        original_replace = env_check._atomic_replace_text
        def slow_replace(path, content):
            eventlet.sleep(0.05)  # yield inside the lock
            original_replace(path, content)
        env_check._atomic_replace_text = slow_replace

        view = inspect.unwrap(broker_credentials.update_credentials)
        app = Flask(__name__)
        def post(payload):
            with app.test_request_context("/api/broker/credentials", method="POST", json=payload):
                result = view()
            return result[1] if isinstance(result, tuple) else 200

        started = time.monotonic()
        a = eventlet.spawn(post, {{"broker_api_key": "green-key"}})
        b = eventlet.spawn(post, {{"host_server": "https://green.example.com"}})
        assert a.wait() == 200 and b.wait() == 200
        values = dotenv.dotenv_values({str(env_path)!r})
        assert values["BROKER_API_KEY"] == "green-key", values
        assert values["HOST_SERVER"] == "https://green.example.com", values
        assert time.monotonic() - started < 5
        print("OK")
    """
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        cwd=str(REPO),
        env=_child_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr
