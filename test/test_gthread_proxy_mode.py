"""Tests for the WebSocket-proxy topology switch (gthread PR-2, gate A7b).

Covers GT-A7-02: topology must be chosen explicitly, never as a side effect of
the Gunicorn worker class. Before this change the switch was
``_eventlet_active()``, so removing eventlet silently relocated the proxy from
its own process into the Gunicorn worker on native installs.
"""

import sys

import pytest

from websocket_proxy import app_integration


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("WEBSOCKET_PROXY_MODE", raising=False)


def _fake_gunicorn(monkeypatch, present: bool):
    """Simulate running inside (or outside) a Gunicorn worker."""
    if present:
        monkeypatch.setitem(sys.modules, "gunicorn", type(sys)("gunicorn"))
    else:
        monkeypatch.delitem(sys.modules, "gunicorn", raising=False)


@pytest.mark.parametrize("mode", ["external", "subprocess", "thread"])
def test_explicit_mode_always_wins(monkeypatch, mode):
    monkeypatch.setenv("WEBSOCKET_PROXY_MODE", mode)
    _fake_gunicorn(monkeypatch, True)
    assert app_integration.resolve_proxy_mode() == mode


@pytest.mark.parametrize("mode", ["EXTERNAL", " Subprocess ", "THREAD"])
def test_explicit_mode_is_case_and_space_insensitive(monkeypatch, mode):
    monkeypatch.setenv("WEBSOCKET_PROXY_MODE", mode)
    assert app_integration.resolve_proxy_mode() == mode.strip().lower()


def test_invalid_mode_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("WEBSOCKET_PROXY_MODE", "banana")
    _fake_gunicorn(monkeypatch, True)
    # Falls back rather than raising: a typo must not stop the app booting.
    assert app_integration.resolve_proxy_mode() == "subprocess"


def test_default_under_gunicorn_is_subprocess(monkeypatch):
    _fake_gunicorn(monkeypatch, True)
    assert app_integration.resolve_proxy_mode() == "subprocess"


def test_default_on_dev_server_is_thread(monkeypatch):
    _fake_gunicorn(monkeypatch, False)
    assert app_integration.resolve_proxy_mode() == "thread"


def test_topology_does_not_depend_on_eventlet(monkeypatch):
    """The regression this gate exists for.

    Under Gunicorn the proxy must stay a subprocess whether or not eventlet is
    monkey-patched. Keying on eventlet meant a worker-class change relocated
    production topology as an unrelated side effect.
    """
    _fake_gunicorn(monkeypatch, True)

    monkeypatch.setattr(app_integration, "_eventlet_active", lambda: True)
    with_eventlet = app_integration.resolve_proxy_mode()

    monkeypatch.setattr(app_integration, "_eventlet_active", lambda: False)
    without_eventlet = app_integration.resolve_proxy_mode()

    assert with_eventlet == without_eventlet == "subprocess"


def test_valid_modes_are_the_documented_three():
    assert app_integration.VALID_PROXY_MODES == ("external", "subprocess", "thread")
