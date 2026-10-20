"""The joins between partitions of the gthread work, checked where they meet.

Each partition tested its own files. These are the places where one partition's
change needed a small edit in another's file: the Telegram mode toggle taking
the analyzer mode lock, a sandbox reset waiting behind a mode change, a master
contract reload dropping cached strikes, the position and order book reads
answering a busy broker with 429, the strategy engine's pending-stop alert
sent once, and the request pool's busy count on a gunicorn that no longer keeps
a futures list.
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

import pytest

# ---------------------------------------------------------------------------
# Telegram mode toggle
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, data: str):
        self.data = data
        self.from_user = types.SimpleNamespace(id=101)
        self.message = types.SimpleNamespace(chat=types.SimpleNamespace(id=202))
        self.edits: list[str] = []

    async def answer(self):
        return None

    async def edit_message_text(self, text, **_kwargs):
        self.edits.append(text)


@pytest.fixture
def telegram(monkeypatch):
    """A bot service with its database and emits stubbed out."""
    import extensions
    import services.telegram_bot_service as tg

    monkeypatch.setattr(tg, "get_bot_config", lambda: {"bot_token": "1:a", "is_active": False})
    monkeypatch.setattr(tg, "update_bot_config", lambda values: True)
    monkeypatch.setattr(tg, "log_command", lambda *args, **kwargs: None)
    emits: list[tuple] = []
    monkeypatch.setattr(
        extensions, "emit_from_any_thread", lambda *args, **kwargs: emits.append(args)
    )
    svc = tg.TelegramBotService()
    svc.emits = emits
    return svc


def _press(svc, data: str) -> _FakeQuery:
    query = _FakeQuery(data)
    update = types.SimpleNamespace(callback_query=query)
    asyncio.run(svc.button_callback(update, types.SimpleNamespace(bot=None)))
    return query


def test_the_telegram_toggle_brings_the_sandbox_engine_in_line(telegram, monkeypatch):
    """Writing the mode alone left sandbox mode with no engine running.

    The web toggle writes the mode and starts or stops the sandbox execution
    engine and square-off scheduler as one step under the analyzer mode lock.
    The Telegram buttons only wrote the mode. Under gthread they now take the
    same step; eventlet and the dev server keep writing the mode only (see the
    next test).
    """
    from database import settings_db
    from services import analyzer_service
    from utils import runtime

    monkeypatch.setattr(runtime, "gthread_active", lambda: True)

    stored = {"mode": False}
    reconciled: list[tuple] = []
    monkeypatch.setattr(analyzer_service, "get_analyze_mode", lambda: stored["mode"])
    monkeypatch.setattr(
        analyzer_service, "set_analyze_mode", lambda mode: stored.update(mode=bool(mode))
    )
    monkeypatch.setattr(
        settings_db, "set_analyze_mode", lambda mode: stored.update(mode=bool(mode))
    )
    monkeypatch.setattr(
        analyzer_service,
        "_reconcile_sandbox",
        lambda mode, **kwargs: reconciled.append((mode, kwargs)),
    )

    query = _press(telegram, "mode_analyze")

    assert stored["mode"] is True
    assert reconciled == [(True, {"with_scheduler": True, "catchup": True})]
    assert "Analyze Mode" in query.edits[-1]
    assert telegram.emits == [("app_mode_changed", {"analyze_mode": True})]

    query = _press(telegram, "mode_live")

    assert stored["mode"] is False
    assert reconciled[-1] == (False, {"with_scheduler": True, "catchup": True})
    assert "Live Mode" in query.edits[-1]


def test_outside_gthread_the_telegram_toggle_writes_the_mode_only(telegram, monkeypatch):
    """Review eventlet-neutrality-03: an install still on eventlet sees no change."""
    from database import settings_db
    from services import analyzer_service
    from utils import runtime

    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    stored = {"mode": False}
    monkeypatch.setattr(
        settings_db, "set_analyze_mode", lambda mode: stored.update(mode=bool(mode))
    )

    def not_called(*args, **kwargs):
        raise AssertionError("the sandbox engine was touched outside gthread")

    monkeypatch.setattr(analyzer_service, "apply_analyze_mode", not_called)
    monkeypatch.setattr(analyzer_service, "_reconcile_sandbox", not_called)

    query = _press(telegram, "mode_analyze")

    assert stored["mode"] is True
    assert "Analyze Mode" in query.edits[-1]
    assert telegram.emits == [("app_mode_changed", {"analyze_mode": True})]


def test_a_telegram_toggle_behind_a_stuck_change_says_so(telegram, monkeypatch):
    from services import analyzer_service
    from utils import runtime
    from utils.keyed_locks import LockBusy

    monkeypatch.setattr(runtime, "gthread_active", lambda: True)

    def busy(*_args, **_kwargs):
        raise LockBusy("analyze_mode", name="analyzer-mode", timeout=30)

    monkeypatch.setattr(analyzer_service, "apply_analyze_mode", busy)

    query = _press(telegram, "mode_analyze")

    assert query.edits[-1] == analyzer_service.MODE_BUSY_MESSAGE
    assert telegram.emits == []


def test_the_telegram_toggle_reaches_the_mode_lock_through_the_app_world():
    """Under eventlet the lock is green and the bot is a real thread."""
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "services" / "telegram_bot_service.py"
    ).read_text(encoding="utf-8")
    body = next(
        ast.get_source_segment(source, node)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "button_callback"
    )
    toggle = body[body.index('"mode_live", "mode_analyze"') :]
    toggle = toggle[: toggle.index("return\n")]
    assert "set_analyze_mode" not in toggle
    assert "self._in_app_world(" in toggle and "apply_analyze_mode" in toggle
    assert "_write_analyze_mode_only" in toggle


# ---------------------------------------------------------------------------
# Sandbox reset under the analyzer mode lock
# ---------------------------------------------------------------------------

RESET_USER = "gthread_integration_reset"
RESET_KEYS = [
    "starting_capital",
    "reset_day",
    "reset_time",
    "order_check_interval",
    "mtm_update_interval",
    "nse_bse_square_off_time",
    "cds_bcd_square_off_time",
    "mcx_square_off_time",
    "ncdex_square_off_time",
    "equity_mis_leverage",
    "equity_cnc_leverage",
    "futures_leverage",
    "option_buy_leverage",
    "option_sell_leverage",
]


@pytest.fixture
def reset_account():
    from test_gthread_sandbox_support import (
        configs_restored,
        prepare_databases,
        release_sessions,
        reset_user,
    )

    prepare_databases()
    reset_user(RESET_USER)
    release_sessions()
    with configs_restored(RESET_KEYS):
        yield
    release_sessions()


def _reset():
    """Run the reset view inside a request, as the logged-in user."""
    import inspect

    from flask import Flask, session
    from test_gthread_sandbox_support import release_sessions

    import blueprints.sandbox as sandbox_views

    view = inspect.unwrap(sandbox_views.reset_config)
    app = Flask(__name__)
    app.secret_key = "test-only"
    with app.test_request_context(json={}, method="POST"):
        session["user"] = RESET_USER
        response = view()
        status = 200
        if isinstance(response, tuple):
            response, status = response
        payload = response.get_json()
    release_sessions()
    return payload, status


def test_a_sandbox_reset_waits_for_a_mode_change_in_progress(reset_account, monkeypatch):
    import blueprints.sandbox as sandbox_views
    from services import analyzer_service

    wiped: list[tuple] = []
    monkeypatch.setattr(sandbox_views, "gthread_active", lambda: False)
    monkeypatch.setattr(sandbox_views, "_wipe_sandbox_account", lambda *a: wiped.append(a))

    outcome: dict = {}

    def run():
        outcome["result"] = _reset()

    analyzer_service._MODE_LOCK.acquire()
    worker = threading.Thread(target=run, daemon=True)
    try:
        worker.start()
        worker.join(0.5)
        assert worker.is_alive(), "the reset ran beside a mode change"
        assert wiped == []
    finally:
        analyzer_service._MODE_LOCK.release()
    worker.join(10)

    payload, status = outcome["result"]
    assert status == 200 and payload["status"] == "success", payload
    assert len(wiped) == 1


def test_under_gthread_a_reset_behind_a_stuck_mode_change_is_refused(reset_account, monkeypatch):
    import blueprints.sandbox as sandbox_views
    from services import analyzer_service
    from utils import runtime

    wrote: list[tuple] = []
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(
        analyzer_service,
        "mode_transition",
        functools.partial(analyzer_service.mode_transition, timeout=0.2),
    )
    monkeypatch.setattr(sandbox_views, "set_config", lambda *a: wrote.append(a))
    monkeypatch.setattr(sandbox_views, "_wipe_sandbox_account", lambda *a: wrote.append(a))

    analyzer_service._MODE_LOCK.acquire()
    try:
        payload, status = _reset()
    finally:
        analyzer_service._MODE_LOCK.release()

    assert status == 409
    assert payload == {"status": "error", "message": analyzer_service.MODE_BUSY_MESSAGE}
    assert wrote == [], "a refused reset still changed the account"


# ---------------------------------------------------------------------------
# Master contract reload drops cached strikes
# ---------------------------------------------------------------------------


def test_a_master_contract_reload_drops_the_cached_strikes(monkeypatch):
    from database import master_contract_cache_hook as hook
    from database import token_db_enhanced
    from services import option_symbol_service as strikes

    monkeypatch.setattr(token_db_enhanced, "load_cache_for_broker", lambda broker: True)
    monkeypatch.setattr(
        token_db_enhanced,
        "get_cache_stats",
        lambda: {"total_symbols": 1, "stats": {"memory_usage_mb": 0}},
    )
    monkeypatch.setattr(hook, "socketio", types.SimpleNamespace(emit=lambda *a, **k: None))

    strikes.clear_strikes_cache()
    strikes._STRIKES_CACHE[("NIFTY", "NFO", "28MAR24", "CE")] = (22000.0, 22050.0)
    assert len(strikes._STRIKES_CACHE) == 1

    assert hook.load_symbols_to_cache("zerodha") is True
    assert len(strikes._STRIKES_CACHE) == 0


# ---------------------------------------------------------------------------
# Position and order book reads refused as busy
# ---------------------------------------------------------------------------

BUSY = "Your broker is rate limiting requests. Try again in 12 seconds."


def _refusing(*_args, **_kwargs):
    from utils.broker_backpressure import BrokerBusyError

    raise BrokerBusyError(BUSY, retry_after=12)


@pytest.mark.parametrize(
    "module_name,call,funcs",
    [
        (
            "services.positionbook_service",
            "get_positionbook_with_auth",
            ("get_positions", "map_position_data", "transform_positions_data"),
        ),
        (
            "services.orderbook_service",
            "get_orderbook_with_auth",
            (
                "get_order_book",
                "map_order_data",
                "calculate_order_statistics",
                "transform_order_data",
            ),
        ),
    ],
)
def test_a_busy_book_read_answers_429_with_the_sentence(monkeypatch, module_name, call, funcs):
    import importlib

    from database import settings_db

    module = importlib.import_module(module_name)
    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
    broker = {name: (lambda *a, **k: []) for name in funcs}
    broker[funcs[0]] = _refusing
    monkeypatch.setattr(module, "import_broker_module", lambda name: broker)

    ok, response, status = getattr(module, call)("token", "zerodha")

    assert (ok, status) == (False, 429)
    assert response == {"status": "error", "message": BUSY}


def test_an_ordinary_book_failure_is_still_a_500(monkeypatch):
    from database import settings_db
    from services import positionbook_service

    def broken(*_args, **_kwargs):
        raise RuntimeError("socket closed")

    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(
        positionbook_service,
        "import_broker_module",
        lambda name: {
            "get_positions": broken,
            "map_position_data": lambda d: d,
            "transform_positions_data": lambda d: d,
        },
    )

    ok, response, status = positionbook_service.get_positionbook_with_auth("token", "zerodha")

    assert (ok, status) == (False, 500)
    assert response["message"] == "socket closed"


# ---------------------------------------------------------------------------
# Strategy engine: one pending-stop alert per run
# ---------------------------------------------------------------------------


class _SlowSet(set):
    """A set whose membership test takes long enough for a second caller to arrive."""

    def __contains__(self, item):
        present = super().__contains__(item)
        time.sleep(0.05)
        return present


def test_racing_callers_record_an_unactionable_run_once(monkeypatch):
    from services.strategy_module import engine

    alerts: list[tuple] = []
    monkeypatch.setattr(engine, "_unactionable_runs", _SlowSet())
    monkeypatch.setattr(engine, "_emit", lambda *args, **kwargs: alerts.append(args[2]))

    start = threading.Barrier(6)

    def note():
        start.wait()
        engine._note_unactionable(7, "trader", 99, [{"leg": 1}], None)

    threads = [threading.Thread(target=note) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert alerts == ["leg_exit_rejected"]

    start = threading.Barrier(6)

    def recover():
        start.wait()
        engine._note_actionable_again(7, "trader", 99)

    threads = [threading.Thread(target=recover) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert alerts == ["leg_exit_rejected", "recovery_succeeded"]
    assert 99 not in engine._unactionable_runs


# ---------------------------------------------------------------------------
# The request pool's busy count without ThreadWorker.futures
# ---------------------------------------------------------------------------


def test_the_busy_count_comes_from_the_pool_when_gunicorn_keeps_no_futures(monkeypatch):
    from utils import runtime

    worker_cls = type("FakeWorker", (), {})
    worker_cls.__module__ = "gunicorn.workers.gthread"
    worker = worker_cls()
    worker.cfg = types.SimpleNamespace(
        worker_class_str="gthread", threads=3, workers=1, graceful_timeout=30
    )
    worker.nr_conns = 2
    release = threading.Event()
    pool = ThreadPoolExecutor(max_workers=3)
    worker.tpool = pool

    monkeypatch.setattr(runtime, "_registered", None)
    monkeypatch.setattr(runtime, "_worker_ref", None)
    try:
        runtime.register_gunicorn_worker(worker)
        pool.submit(release.wait)
        pool.submit(release.wait)
        pool.submit(lambda: None).result(5)
        deadline = time.monotonic() + 5
        while pool._idle_semaphore._value < 1 and time.monotonic() < deadline:
            time.sleep(0.01)

        stats = runtime.gthread_pool_stats()

        assert stats["spawned"] == 3
        assert stats["busy"] == 2
        assert stats["open_connections"] == 2
    finally:
        release.set()
        pool.shutdown(wait=True)


def test_the_admin_report_carries_the_http_pool():
    from blueprints import admin

    info = admin._runtime_info()

    assert "http_pool" in info
