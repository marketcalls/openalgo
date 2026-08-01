"""Tests for runtime diagnostics and the promoted Telegram path (PR-9, gate C5).

Covers GT-C5-01, GT-C5-02, GT-C5-03.

Diagnostics are how a bad cutover is *detected*, which is why they ship before
the cutover rather than after. The previous implementation keyed entirely off
eventlet: it defaulted wsgi_hint to "flask-dev" and only changed that when
eventlet was monkey-patched, so a gthread worker in production would have
reported itself as a development server.
"""

import sys
from pathlib import Path

import pytest

from blueprints.admin import _runtime_info

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# GT-C5-01: runtime identity
# --------------------------------------------------------------------------


def test_runtime_reports_every_field_needed_to_judge_a_cutover():
    info = _runtime_info()
    for key in (
        "wsgi_hint",
        "gunicorn_version",
        "worker_class",
        "configured_threads",
        "configured_workers",
        "active_threads",
        "websocket_proxy_mode",
        "eventlet_active",
    ):
        assert key in info, f"missing diagnostic field: {key}"


def test_active_thread_count_is_live():
    """Needed to compare actual threads against the configured budget."""
    import threading

    info = _runtime_info()
    assert isinstance(info["active_threads"], int)
    assert info["active_threads"] >= threading.active_count() - 2


def test_worker_class_is_reported_not_inferred_from_eventlet(monkeypatch):
    """The regression. Under gthread, eventlet is absent -- the old code would
    conclude "flask-dev" and hide the fact that a real worker is running."""
    fake_gunicorn = type(sys)("gunicorn")
    fake_gunicorn.__version__ = "26.0.0"
    monkeypatch.setitem(sys.modules, "gunicorn", fake_gunicorn)
    monkeypatch.setattr(sys, "argv", ["gunicorn", "--worker-class", "gthread", "--threads", "64"])

    info = _runtime_info()
    assert info["gunicorn_version"] == "26.0.0"
    assert info["worker_class"] == "gthread"
    assert info["configured_threads"] == 64
    assert info["wsgi_hint"] == "gunicorn-gthread"
    assert info["eventlet_active"] is False


def test_eventlet_worker_is_still_reported_correctly(monkeypatch):
    """Must stay accurate before the cutover, not only after it."""
    fake_gunicorn = type(sys)("gunicorn")
    fake_gunicorn.__version__ = "25.1.0"
    monkeypatch.setitem(sys.modules, "gunicorn", fake_gunicorn)
    monkeypatch.setattr(sys, "argv", ["gunicorn", "--worker-class", "eventlet"])

    import blueprints.admin as admin

    monkeypatch.setattr(
        admin, "_gunicorn_config", lambda: {"worker_class": "eventlet", "threads": None}
    )
    fake_patcher = type(sys)("eventlet.patcher")
    fake_patcher.is_monkey_patched = lambda _name: True
    monkeypatch.setitem(sys.modules, "eventlet.patcher", fake_patcher)
    monkeypatch.setitem(sys.modules, "eventlet", type(sys)("eventlet"))

    info = _runtime_info()
    assert info["eventlet_active"] is True
    assert info["wsgi_hint"] == "gunicorn-eventlet"


def test_dev_server_is_reported_as_dev_server(monkeypatch):
    monkeypatch.delitem(sys.modules, "gunicorn", raising=False)
    info = _runtime_info()
    assert info["wsgi_hint"] == "flask-dev"
    assert info["gunicorn_version"] is None


def test_proxy_mode_is_included():
    """A cutover that silently relocates the proxy must be visible (PR-2)."""
    info = _runtime_info()
    assert info["websocket_proxy_mode"] in ("external", "subprocess", "thread")


# --------------------------------------------------------------------------
# GT-C5-02: the frontend type must carry the new fields
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "gunicorn_version",
        "worker_class",
        "configured_threads",
        "configured_workers",
        "active_threads",
        "websocket_proxy_mode",
    ],
)
def test_frontend_runtime_type_exposes_the_new_fields(field):
    src = (REPO / "frontend" / "src" / "types" / "admin.ts").read_text(encoding="utf-8")
    block = src[src.index("export interface SystemRuntime") :]
    block = block[: block.index("}")]
    assert field in block, f"SystemRuntime is missing {field}"


def test_system_report_renders_the_runtime_fields():
    """The downloadable report is what users paste into issues."""
    src = (REPO / "blueprints" / "admin.py").read_text(encoding="utf-8")
    for label in ("Worker class", "Configured threads", "WebSocket proxy mode", "Gunicorn"):
        assert f'"{label}"' in src, f"system report does not show {label}"


# --------------------------------------------------------------------------
# GT-C5-03: the Telegram branch that becomes production
# --------------------------------------------------------------------------


def test_eventlet_only_startup_test_skips_instead_of_erroring():
    """It hard-imported eventlet, so it failed collection once eventlet was
    no longer installed. A suite that cannot be collected protects nothing."""
    src = (REPO / "test" / "test_telegram_startup.py").read_text(encoding="utf-8")
    assert "importorskip" in src
    assert "eventlet.monkey_patch()" in src, "the eventlet branch is still covered when present"


def test_non_eventlet_init_is_defensive_about_the_event_loop():
    """Under gthread the else-branch becomes the production path. It runs on a
    worker thread, where asyncio.get_event_loop() raises rather than creating
    a loop, so the RuntimeError fallback is load-bearing.

    Moved out of blueprints/telegram.py in PR-10g: the route used to spawn its
    own untracked thread, and that logic now lives in the service so it can be
    single-flight. The guarantee is unchanged, only its home.
    """
    import inspect

    from services.telegram_bot_service import TelegramBotService

    src = inspect.getsource(TelegramBotService._initialize_bot_blocking)
    assert "except RuntimeError:" in src
    assert "asyncio.run(" in src

    # And the route must no longer carry its own copy.
    route = (REPO / "blueprints" / "telegram.py").read_text(encoding="utf-8")
    assert "def init_bot()" not in route, "the inline initializer is back"


def test_telegram_service_falls_back_to_plain_threading_without_eventlet():
    """The escape hatch must degrade, not break, when eventlet is absent."""
    src = (REPO / "services" / "telegram_bot_service.py").read_text(encoding="utf-8")
    assert "import threading as original_threading" in src
