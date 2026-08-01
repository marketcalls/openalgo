"""Single-flight Telegram initialization (gate C4, GT-T-01).

The route used to spawn a bare thread, join it for 10 seconds and continue
regardless. On timeout the thread kept running and went on to write bot_token
and the database config -- after the route had already reported failure -- and
an immediate retry started a second initializer against the same token.
"""

import inspect
import threading
import time
from pathlib import Path

from services.telegram_bot_service import TelegramBotService

REPO = Path(__file__).resolve().parent.parent


def test_service_owns_the_threaded_initializer():
    service = TelegramBotService()
    assert hasattr(service, "initialize_bot_threaded")
    assert hasattr(service, "_init_lock")
    assert hasattr(service, "_init_executor")


def test_worker_is_bounded_to_one():
    """A queued retry must not run alongside the first initializer."""
    service = TelegramBotService()
    assert service._init_executor._max_workers == 1


def test_route_no_longer_spawns_its_own_thread():
    src = (REPO / "blueprints" / "telegram.py").read_text(encoding="utf-8")
    start = src.index("def start_bot()")
    body = src[start : start + 2500]
    assert "threading.Thread(" not in body, "the route still spawns an untracked thread"
    assert "initialize_bot_threaded" in body


def test_a_second_call_is_refused_while_the_first_runs(monkeypatch):
    """The core regression: two initializers against one token."""
    service = TelegramBotService()
    running = threading.Event()
    release = threading.Event()
    calls = []

    def slow_init(_token):
        calls.append(1)
        running.set()
        release.wait(timeout=2)
        return True, "ok"

    monkeypatch.setattr(service, "_initialize_bot_blocking", slow_init)

    first_result = []
    t = threading.Thread(
        target=lambda: first_result.append(service.initialize_bot_threaded("tok", timeout=2))
    )
    t.start()
    assert running.wait(timeout=2), "first initializer never started"

    ok, message = service.initialize_bot_threaded("tok", timeout=1)
    assert ok is False
    assert "already in progress" in message

    release.set()
    t.join(timeout=3)
    assert calls == [1], "a second initializer ran"
    assert first_result == [(True, "ok")]


def test_timeout_reports_honestly_rather_than_claiming_failure(monkeypatch):
    """The work is still running. Saying 'failed' invites an immediate retry,
    which is what produced two initializers in the first place."""
    service = TelegramBotService()
    release = threading.Event()

    def slow_init(_token):
        release.wait(timeout=3)
        return True, "ok"

    monkeypatch.setattr(service, "_initialize_bot_blocking", slow_init)
    started = time.monotonic()
    ok, message = service.initialize_bot_threaded("tok", timeout=0.2)
    elapsed = time.monotonic() - started

    assert ok is False
    assert "still running" in message, f"misleading timeout message: {message}"
    assert elapsed < 1.5, "the caller was not released at the timeout"
    release.set()


def test_the_lock_is_released_after_a_timeout(monkeypatch):
    """A timed-out initializer must not wedge every later attempt."""
    service = TelegramBotService()
    release = threading.Event()

    monkeypatch.setattr(
        service, "_initialize_bot_blocking", lambda _t: (release.wait(timeout=3), (True, "ok"))[1]
    )
    service.initialize_bot_threaded("tok", timeout=0.1)
    release.set()

    assert service._init_lock.acquire(blocking=False), "init lock was left held"
    service._init_lock.release()


def test_blocking_initializer_handles_a_thread_with_no_event_loop():
    """It runs on a worker thread, where asyncio.get_event_loop() raises rather
    than creating a loop -- so asyncio.run is the correct entry point."""
    src = inspect.getsource(TelegramBotService._initialize_bot_blocking)
    assert "asyncio.run(" in src
    assert "except RuntimeError:" in src, "no fallback if a loop is already set"
