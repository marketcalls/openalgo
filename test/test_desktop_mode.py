"""Desktop mode (utils.desktop): the server started by the keeper with no terminal.

Covers the pieces that can be tested without starting the app: the stop-file
watcher, the env version prompt, and the WebSocket URL a browser on another
device is given. Starting ``app.py`` itself with stdin as a pipe is verified by
hand (see the M3.1 commit), because it binds the configured ports and opens the
real databases.
"""

import builtins
import os
import signal
import sys
import time
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from blueprints.websocket_example import _reachable_websocket_url
from utils import desktop, env_check

# --- desktop flag ---------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " t "])
def test_desktop_flag_on(monkeypatch, value):
    monkeypatch.setenv("FASTALGO_DESKTOP", value)
    assert desktop.is_desktop()


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_desktop_flag_off(monkeypatch, value):
    monkeypatch.setenv("FASTALGO_DESKTOP", value)
    assert not desktop.is_desktop()


# --- stop-file watcher ----------------------------------------------------


def test_watcher_not_started_outside_desktop_mode(monkeypatch, tmp_path):
    monkeypatch.delenv("FASTALGO_DESKTOP", raising=False)
    monkeypatch.setenv("FASTALGO_STOP_FILE", str(tmp_path / "stop.request"))
    assert desktop.start_stop_watcher() is None


def test_watcher_not_started_without_stop_file(monkeypatch):
    monkeypatch.setenv("FASTALGO_DESKTOP", "1")
    monkeypatch.delenv("FASTALGO_STOP_FILE", raising=False)
    assert desktop.start_stop_watcher() is None


def test_stop_file_raises_sigint_and_is_removed(monkeypatch, tmp_path):
    stop = tmp_path / "stop.request"
    monkeypatch.setenv("FASTALGO_DESKTOP", "1")
    monkeypatch.setenv("FASTALGO_STOP_FILE", str(stop))

    received = []
    previous = signal.signal(signal.SIGINT, lambda signum, _frame: received.append(signum))
    try:
        thread = desktop.start_stop_watcher(poll_s=0.05)
        assert thread is not None and thread.daemon

        time.sleep(0.2)
        assert received == [], "the watcher fired before the stop file existed"

        stop.write_text("")
        deadline = time.monotonic() + 5
        # The handler runs on this (main) thread between bytecodes, so keep
        # executing Python while waiting rather than blocking in one call.
        while not received and time.monotonic() < deadline:
            time.sleep(0.05)

        assert received == [signal.SIGINT]
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert not stop.exists()
    finally:
        signal.signal(signal.SIGINT, previous)


# --- env version prompt ---------------------------------------------------


def _fake_env_files(env_version: str, sample_version: str):
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        name = os.path.basename(str(path))
        if name == ".env":
            return mock.mock_open(read_data=f"ENV_CONFIG_VERSION = '{env_version}'\n")()
        if name == ".sample.env":
            return mock.mock_open(read_data=f"ENV_CONFIG_VERSION = '{sample_version}'\n")()
        return real_open(path, *args, **kwargs)

    return fake_open


def test_outdated_env_prompts_in_a_terminal(monkeypatch):
    """The existing behaviour: no terminal answer means the start is cancelled."""
    monkeypatch.delenv("FASTALGO_DESKTOP", raising=False)
    monkeypatch.setattr(env_check.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(builtins, "open", _fake_env_files("1.0.0", "2.0.0"))

    def no_terminal(_prompt=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", no_terminal)
    assert env_check.check_env_version_compatibility() is False


def test_outdated_env_does_not_prompt_in_desktop_mode(monkeypatch):
    monkeypatch.setenv("FASTALGO_DESKTOP", "1")
    monkeypatch.setattr(env_check.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(builtins, "open", _fake_env_files("1.0.0", "2.0.0"))

    # Recorded, not raised: the function wraps the prompt in an outer
    # ``except Exception`` that returns True, so raising from here would be
    # swallowed and the test would pass with the prompt still in place.
    prompts = []

    def no_terminal(prompt=""):
        prompts.append(prompt)
        raise EOFError

    monkeypatch.setattr(builtins, "input", no_terminal)
    assert env_check.check_env_version_compatibility() is True
    assert prompts == [], "desktop mode must never call input()"


# --- WebSocket URL for another device -------------------------------------


@pytest.mark.parametrize(
    ("configured", "request_host", "expected"),
    [
        # Same PC: unchanged.
        ("ws://127.0.0.1:8765", "127.0.0.1:5000", "ws://127.0.0.1:8765"),
        ("ws://127.0.0.1:8765", "localhost:5000", "ws://127.0.0.1:8765"),
        # A phone on the network: the browser's host, the configured port.
        ("ws://127.0.0.1:8765", "192.168.1.20:5000", "ws://192.168.1.20:8765"),
        ("ws://localhost:8765", "fastalgo-pc:5000", "ws://fastalgo-pc:8765"),
        ("ws://127.0.0.1:8765", "[fe80::1]:5000", "ws://[fe80::1]:8765"),
        # A real host configured (nginx, a domain): never touched.
        ("wss://algo.example.com/ws", "192.168.1.20:5000", "wss://algo.example.com/ws"),
        ("ws://192.168.1.5:8765", "192.168.1.20:5000", "ws://192.168.1.5:8765"),
        # A host header that is not a host name: ignored.
        ("ws://127.0.0.1:8765", "evil host/x:5000", "ws://127.0.0.1:8765"),
        ("ws://127.0.0.1:8765", "", "ws://127.0.0.1:8765"),
    ],
)
def test_reachable_websocket_url(configured, request_host, expected):
    assert _reachable_websocket_url(configured, request_host) == expected
