"""The Telegram bot's start and stop, one bot at a time, in every runtime.

Three defects, each of which a trader could meet by pressing Start:

* **A Python error for Start on a running bot.** The asyncio start path, taken
  wherever eventlet had not patched the process (the gthread worker, Docker,
  a Windows dev server), awaited the synchronous ``stop_bot()``: the bot was
  stopped, and the route answered "'tuple' object can't be awaited".
* **Two pollers on one token.** ``start_bot`` checked ``is_running``, which
  only turns true once polling is live, up to five seconds later, and shared
  one stop Event between generations. Two starts in that window (the auto
  start and a click, or a double click) each spawned a poller; Telegram
  answers the second with 409 Conflict and the bot stops answering, /closeall
  included.
* **A stop that did not stop.** ``stop_bot`` answered "not running" to a bot
  still starting or backing off, and a thread finishing late wrote
  ``is_running = False`` over the next bot's state.

These tests run on real OS threads with no eventlet, which is what the gthread
worker and the dev server are. The eventlet proofs are in
``test_gthread_messaging_eventlet.py``.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import services.telegram_bot_service as tg

REPO = Path(__file__).resolve().parents[1]


# --- helpers ------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _fake_http(status_code=200, payload=None, calls=None):
    def get(url, timeout=None):
        if calls is not None:
            calls.append((url, timeout))
        return _FakeResponse(status_code, payload)

    return types.SimpleNamespace(get=get)


OK_GETME = {"ok": True, "result": {"username": "OpenAlgoTestBot"}}


@pytest.fixture
def service(monkeypatch):
    """A fresh service with the database stubbed out."""
    config = {"bot_token": "123:abc", "is_active": False}
    writes = []
    monkeypatch.setattr(tg, "get_bot_config", lambda: dict(config))
    monkeypatch.setattr(tg, "update_bot_config", lambda values: writes.append(dict(values)) or True)
    svc = tg.TelegramBotService()
    svc.config_writes = writes
    yield svc
    # Stop anything a test left running.
    svc._gen_stop.set()
    thread = svc.bot_thread
    if thread is not None:
        thread.join(5)


def _install_fake_bot(svc, monkeypatch, *, connect_delay=0.0, honour_stop=True):
    """Replace the bot thread body with one that polls nothing.

    It sleeps ``connect_delay`` (the window in which a real bot is connecting),
    marks itself running through the same generation-checked path the real
    thread uses, and runs until its generation's stop is set.
    """
    spawned = []

    def fake_run(gen=None, stop=None):
        spawned.append(gen)
        deadline = time.monotonic() + connect_delay
        while time.monotonic() < deadline:
            if honour_stop and stop.is_set():
                svc._clear_running(gen)
                return
            time.sleep(0.01)
        svc._publish_running(gen, stop)
        while not stop.is_set():
            time.sleep(0.01)
        svc._clear_running(gen)

    monkeypatch.setattr(svc, "_run_bot_in_thread", fake_run)
    return spawned


# --- messaging-04: one synchronous validation path ------------------------------


def test_initialize_on_a_running_bot_keeps_it_running(service, monkeypatch):
    """PORTED DEFECT: Start on a running bot stopped it and returned a TypeError."""
    import utils.httpx_client as httpx_client

    monkeypatch.delitem(sys.modules, "eventlet", raising=False)
    monkeypatch.setattr(httpx_client, "get_httpx_client", lambda: _fake_http(200, OK_GETME))
    stops = []
    monkeypatch.setattr(service, "stop_bot", lambda: stops.append(1) or (True, "stopped"))
    service.is_running = True

    ok, message = service.initialize_bot_sync("123:abc")
    assert ok, message
    assert message == "Bot initialized successfully: @OpenAlgoTestBot"
    assert stops == []
    assert service.is_running is True

    # The coroutine form, which app.py's auto start still uses under gthread.
    ok, message = asyncio.run(service.initialize_bot("123:abc"))
    assert ok, message
    assert stops == []
    assert {"bot_token": "123:abc", "bot_username": "OpenAlgoTestBot"} in service.config_writes


def test_initialize_creates_and_sets_no_event_loop(service, monkeypatch):
    """A pooled gthread request thread must not be left with a loop set on it."""
    import utils.httpx_client as httpx_client

    monkeypatch.setattr(httpx_client, "get_httpx_client", lambda: _fake_http(200, OK_GETME))

    def refuse(*_args, **_kwargs):
        raise AssertionError("token validation touched the asyncio event loop")

    monkeypatch.setattr(asyncio, "new_event_loop", refuse)
    monkeypatch.setattr(asyncio, "set_event_loop", refuse)
    ok, message = service.initialize_bot_sync("123:abc")
    assert ok, message


def test_the_validation_is_one_bounded_get_me(service, monkeypatch):
    import utils.httpx_client as httpx_client

    calls = []
    monkeypatch.setattr(httpx_client, "get_httpx_client", lambda: _fake_http(200, OK_GETME, calls))
    service.initialize_bot_sync("123:abc")
    assert calls == [("https://api.telegram.org/bot123:abc/getMe", 10)]


def test_a_rejected_token_is_explained_to_the_trader(service, monkeypatch):
    import utils.httpx_client as httpx_client

    monkeypatch.setattr(
        httpx_client,
        "get_httpx_client",
        lambda: _fake_http(401, {"ok": False, "description": "Unauthorized"}),
    )
    ok, message = service.initialize_bot_sync("bad")
    assert not ok
    assert "BotFather" in message
    assert "401" not in message and "HTTP" not in message


def test_an_unreachable_telegram_still_stores_the_token(service, monkeypatch):
    """The eventlet worker's long-standing behaviour: store it, retry on start."""
    import utils.httpx_client as httpx_client

    def unreachable():
        def get(url, timeout=None):
            raise OSError("network is unreachable")

        return types.SimpleNamespace(get=get)

    monkeypatch.setattr(httpx_client, "get_httpx_client", unreachable)
    ok, message = service.initialize_bot_sync("123:abc")
    assert ok
    assert service.bot_token == "123:abc"
    assert message == "Token stored (will validate on start)"


def test_the_start_route_leaves_a_running_bot_running(monkeypatch):
    """The route validates, then start_bot refuses; nothing stops the bot."""
    from flask import Flask

    import blueprints.telegram as telegram_bp

    calls = []
    fake = types.SimpleNamespace(
        is_running=True,
        initialize_bot_sync=lambda token: calls.append("init") or (True, "ok"),
        start_bot=lambda: calls.append("start") or (False, "Bot is already running"),
        stop_bot=lambda: calls.append("stop") or (True, "stopped"),
    )
    monkeypatch.setattr(telegram_bp, "telegram_bot_service", fake)
    monkeypatch.setattr(telegram_bp, "get_bot_config", lambda: {"bot_token": "123:abc"})
    app = Flask(__name__)
    view = inspect.unwrap(telegram_bp.start_bot)
    with app.test_request_context("/telegram/bot/start", method="POST"):
        response, status = view()
    assert calls == ["init", "start"]
    assert status == 500
    assert response.get_json()["message"] == "Bot is already running"


def test_the_start_route_holds_no_asyncio_path():
    source = (REPO / "blueprints" / "telegram.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "asyncio"
    }
    assert names == set(), f"blueprints/telegram.py still uses asyncio: {sorted(names)}"
    assert "initialize_bot(" not in source


# --- messaging-05: single-flight start and stop -------------------------------------


def test_only_one_of_many_concurrent_starts_wins(service, monkeypatch):
    """PORTED DEFECT: eight starts inside the connect window spawned eight pollers."""
    spawned = _install_fake_bot(service, monkeypatch, connect_delay=1.0)
    callers = 8
    barrier = threading.Barrier(callers)
    answers = []
    lock = threading.Lock()

    def start():
        barrier.wait()
        answer = service.start_bot()
        with lock:
            answers.append(answer)

    threads = [threading.Thread(target=start) for _ in range(callers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    assert len(spawned) == 1, f"{len(spawned)} bot threads were started"
    successes = [a for a in answers if a[0]]
    refusals = [a for a in answers if not a[0]]
    assert successes == [(True, "Bot started successfully")]
    assert len(refusals) == callers - 1
    assert all(message == tg.BOT_BUSY_MESSAGE for _ok, message in refusals)
    assert service.is_running is True


def test_a_start_while_running_says_so(service, monkeypatch):
    _install_fake_bot(service, monkeypatch)
    assert service.start_bot() == (True, "Bot started successfully")
    assert service.start_bot() == (False, "Bot is already running")


def test_a_stop_during_startup_stops_the_starting_bot(service, monkeypatch):
    """PORTED DEFECT: stop answered "not running" and the bot came up anyway."""
    spawned = _install_fake_bot(service, monkeypatch, connect_delay=2.0)
    starter = threading.Thread(target=service.start_bot)
    starter.start()
    deadline = time.monotonic() + 5
    while not spawned and time.monotonic() < deadline:
        time.sleep(0.01)
    assert spawned, "the bot thread never started"

    ok, message = service.stop_bot()
    assert (ok, message) == (True, "Bot stopped successfully")
    starter.join(10)
    assert service.is_running is False
    assert service.bot_thread is None
    assert service.config_writes[-1] == {"is_active": False}

    # And a later start is free to begin a new generation.
    monkeypatch.setattr(tg, "BOT_START_WAIT_SECONDS", 5.0)
    _install_fake_bot(service, monkeypatch)
    assert service.start_bot() == (True, "Bot started successfully")


def test_a_stop_with_nothing_alive_is_unchanged(service):
    assert service.stop_bot() == (False, "Bot is not running")


def test_a_thread_that_outlives_its_stop_blocks_a_second_poller(service, monkeypatch):
    """A join that times out keeps the thread registered, so start refuses."""
    release = threading.Event()

    def stubborn(gen=None, stop=None):
        service._publish_running(gen, stop)
        release.wait(10)  # ignores its stop, as a thread stuck in a call would
        service._clear_running(gen)

    monkeypatch.setattr(service, "_run_bot_in_thread", stubborn)
    monkeypatch.setattr(tg, "BOT_STOP_JOIN_SECONDS", 0.2)
    assert service.start_bot()[0]
    assert service.stop_bot() == (True, "Bot stopped successfully")
    assert service.bot_thread is not None and service.bot_thread.is_alive()
    assert service.start_bot() == (False, tg.BOT_BUSY_MESSAGE)
    release.set()
    service.bot_thread.join(5)


def test_an_old_generation_cannot_clear_the_new_bots_state(service, monkeypatch):
    """PORTED DEFECT: a late finally wrote is_running=False over a newer bot."""

    async def nothing(gen=None, stop=None):
        return None

    monkeypatch.setattr(service, "_start_bot_isolated", nothing)
    current_loop = object()
    service._gen = 2
    service.is_running = True
    service.bot_loop = current_loop

    stale_stop = threading.Event()
    stale_stop.set()
    service._run_bot_in_thread(gen=1, stop=stale_stop)

    assert service.is_running is True
    assert service.bot_loop is current_loop


def test_the_reconnect_backoff_ends_promptly_on_stop(service):
    stop = threading.Event()

    async def scenario():
        asyncio.get_running_loop().call_later(0.2, stop.set)
        started = time.monotonic()
        stopped = await service._sleep_unless_stopped(stop, 80)
        return stopped, time.monotonic() - started

    stopped, took = asyncio.run(scenario())
    assert stopped is True
    assert took < 2.0


def test_publishing_running_respects_the_stop_and_the_generation(service):
    stop = threading.Event()
    service._gen = 3
    assert service._publish_running(2, stop) is False
    assert service.is_running is False
    stop.set()
    assert service._publish_running(3, stop) is False
    assert service.config_writes == []


# --- hosts-09 and messaging-13: calls out of the bot's real thread ------------------


def test_off_eventlet_a_strategy_stop_runs_as_it_did(service, monkeypatch):
    """No eventlet: the call runs on the loop's executor, exactly as before."""
    import blueprints.python_strategy as python_strategy

    threads = []
    monkeypatch.setattr(
        python_strategy,
        "stop_strategy_process",
        lambda sid: threads.append(threading.get_ident()) or (True, f"stopped {sid}"),
    )

    async def scenario():
        loop_thread = threading.get_ident()
        result = await service._in_app_world(
            tg._stop_python_strategy, "s1", timeout=tg.STRATEGY_CALL_TIMEOUT_SECONDS
        )
        return loop_thread, result

    loop_thread, result = asyncio.run(scenario())
    assert result == (True, "stopped s1")
    assert threads and threads[0] != loop_thread  # the executor, not the loop


def test_the_running_strategy_list_prefers_the_hosts_snapshot(monkeypatch):
    import blueprints.python_strategy as python_strategy

    monkeypatch.setattr(python_strategy, "RUNNING_STRATEGIES", {"a": {}, "b": {}}, raising=False)
    monkeypatch.setattr(
        python_strategy, "STRATEGY_CONFIGS", {"a": {"name": "Alpha"}}, raising=False
    )
    monkeypatch.delattr(python_strategy, "snapshot_running_strategies", raising=False)
    assert tg._running_python_strategies() == [("a", "Alpha"), ("b", "b")]

    monkeypatch.setattr(
        python_strategy, "snapshot_running_strategies", lambda: [("x", "Xray")], raising=False
    )
    assert tg._running_python_strategies() == [("x", "Xray")]


def _function_source(name: str) -> str:
    path = REPO / "services" / "telegram_bot_service.py"
    source = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{name} not found")


def test_the_bot_thread_never_calls_the_strategy_host_directly():
    for name in ("button_callback", "cmd_stoppython"):
        body = _function_source(name)
        assert "stop_strategy_process" not in body, name
        assert "RUNNING_STRATEGIES" not in body, name
        assert "_in_app_world" in body, name


def test_the_mode_toggle_emits_through_the_any_thread_helper():
    body = _function_source("button_callback")
    assert "socketio.emit(" not in body
    assert "emit_from_any_thread(" in body


def test_the_bot_thread_and_its_lock_are_real_threading():
    from utils import real_threading

    svc = tg.TelegramBotService()
    assert isinstance(svc._lifecycle_lock, type(real_threading.Lock()))
    assert isinstance(svc._gen_stop, real_threading.Event)
    source = _function_source("start_bot")
    assert "real_threading.Thread(" in source
