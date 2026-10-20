"""The scalping risk monitor under truly parallel threads.

``_on_tick`` runs on the websocket client's dispatch thread, which also feeds
the sandbox execution engine, the strategy tick feed and Flow. The monitor's
lock is a real RLock, so under the gthread worker it excludes for real, and it
used to be held across a websocket unsubscribe (up to 12s waiting for the proxy
ack), a SQLite write and a Socket.IO emit. An exit clearing its stop while the
proxy was slow then stalled every tick subscriber in the process.

``sync()`` also read the active stops outside the lock and installed them
later, so a stop cleared by an exit in between came back: the next tick
breached again with no cooldown left, and a positionbook that did not yet show
the first exit sent a second, full-size one.

Under eventlet the RLock is owned by the one OS thread, so greenlets re-enter
it and nothing stalled; the last test here checks that stays true.
"""

import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

import database.scalping_db as scalping_db
import extensions
import services.scalping_risk_monitor_service as mod
from services.scalping_risk_monitor_service import ScalpingRiskMonitor

ROOT = Path(__file__).resolve().parents[1]
SYMBOL = "NIFTY25JUN2623600CE"
KEY = mod._slkey(SYMBOL, "NFO", "NRML")


def _long(**overrides):
    state = {
        "symbol": SYMBOL,
        "exchange": "NFO",
        "product": "NRML",
        "side": "BUY",
        "entry_price": 100.0,
        "initial_sl": 95.0,
        "current_sl": 95.0,
        "target": 0.0,
        "trailing_enabled": True,
        "trailing_step": 3.0,
        "highest_price": None,
        "lowest_price": None,
        "mode": "live",
    }
    state.update(overrides)
    return state


def _tick(ltp):
    return {"type": "market_data", "symbol": SYMBOL, "exchange": "NFO", "data": {"ltp": ltp}}


class SlowWs:
    """A connected client whose unsubscribe waits on the proxy for a while."""

    def __init__(self, unsubscribe_seconds=0.0):
        self.alive = True
        self.connected = True
        self.callbacks = {}
        self.unsubscribe_seconds = unsubscribe_seconds
        self.subscribed = []
        self.unsubscribed = []

    def subscribe(self, symbols, mode="LTP"):
        self.subscribed.append(symbols)
        return {"status": "success"}

    def unsubscribe(self, symbols, mode="LTP"):
        time.sleep(self.unsubscribe_seconds)
        self.unsubscribed.append(symbols)
        return {"status": "success"}

    def register_callback(self, event_type, callback):
        self.callbacks.setdefault(event_type, []).append(callback)


@pytest.fixture
def monitor(monkeypatch):
    mon = ScalpingRiskMonitor()
    monkeypatch.setattr(mon, "_states", {})
    monkeypatch.setattr(mon, "_subscribed", set())
    monkeypatch.setattr(mon, "_exit_inflight", set())
    monkeypatch.setattr(mon, "_last_exit_attempt", {})
    monkeypatch.setattr(mon, "_last_persist", {})
    monkeypatch.setattr(mon, "_last_emit", {})
    monkeypatch.setattr(mon, "_cleared", {}, raising=False)
    monkeypatch.setattr(mon, "_syncs_in_flight", {}, raising=False)
    monkeypatch.setattr(mon, "_ws", None)
    monkeypatch.setattr(mon, "_mode", lambda: "live")
    monkeypatch.setattr(extensions.socketio, "emit", lambda *a, **k: None)
    monkeypatch.setattr(scalping_db, "delete_sl_state", lambda *a, **k: True)
    monkeypatch.setattr(scalping_db, "upsert_sl_state", lambda *a, **k: True)
    return mon


def test_clearing_a_stop_does_not_hold_up_ticks(monitor):
    ws = SlowWs(unsubscribe_seconds=2.0)
    monitor._ws = ws
    monitor._subscribed = {mod._symkey(SYMBOL, "NFO")}
    monitor._states[KEY] = _long()
    other = mod._slkey("BANKNIFTY25JUN2650000CE", "NFO", "NRML")
    monitor._states[other] = _long(symbol="BANKNIFTY25JUN2650000CE")

    clearing = threading.Thread(
        target=monitor._clear_state, args=(KEY, SYMBOL, "NFO", "NRML", "live")
    )
    clearing.start()
    assert _wait_for(lambda: KEY not in monitor._states, 2)
    time.sleep(0.05)

    began = time.monotonic()
    monitor._on_tick(
        {
            "type": "market_data",
            "symbol": "BANKNIFTY25JUN2650000CE",
            "exchange": "NFO",
            "data": {"ltp": 99.0},
        }
    )
    elapsed = time.monotonic() - began
    clearing.join(5)

    assert elapsed < 0.1, f"a tick waited {elapsed:.2f}s behind an unsubscribe"
    assert ws.unsubscribed, "the cleared symbol was not unsubscribed"


def _wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_a_trailing_write_is_made_outside_the_lock(monitor, monkeypatch):
    """The SQLite write can take its whole lock-retry budget; ticks must not
    wait on it."""
    seen = {}

    def upsert(state):
        grabbed = []

        def other_thread():
            if monitor._lock.acquire(timeout=0.5):
                grabbed.append(1)
                monitor._lock.release()

        probe = threading.Thread(target=other_thread)
        probe.start()
        probe.join(2)
        seen["lock_free"] = bool(grabbed)
        seen["current_sl"] = state["current_sl"]

    monkeypatch.setattr(scalping_db, "upsert_sl_state", upsert)
    monitor._states[KEY] = _long(current_sl=90.0)

    monitor._on_tick(_tick(110.0))

    assert seen["lock_free"] is True, "the trailing write ran with the monitor lock held"
    assert seen["current_sl"] == pytest.approx(107.0)
    assert monitor._states[KEY]["current_sl"] == pytest.approx(107.0)


def test_a_breach_starts_one_exit_however_many_ticks_arrive(monitor, monkeypatch):
    started = []
    release = threading.Event()

    def exit_worker(key, state, reason, ltp):
        started.append(key)
        release.wait(2)
        with monitor._lock:
            monitor._exit_inflight.discard(key)

    monkeypatch.setattr(monitor, "_exit_worker", exit_worker)
    monitor._states[KEY] = _long(trailing_enabled=False)
    ticks = threading.Barrier(6)

    def tick():
        ticks.wait()
        monitor._on_tick(_tick(90.0))

    threads = [threading.Thread(target=tick) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    release.set()
    assert _wait_for(lambda: not monitor._exit_inflight, 3)
    assert started == [KEY]


def test_a_stop_cleared_after_the_tick_decided_is_not_exited_again(monitor, monkeypatch):
    """The exit now starts after the lock is released, so it re-checks that the
    stop it was decided for is still the live one."""
    started = []
    monkeypatch.setattr(monitor, "_exit_worker", lambda *args: started.append(args[0]))
    decided = _long(trailing_enabled=False)
    monitor._states[KEY] = decided

    # Cleared between the tick's decision and the dispatch.
    monitor._clear_state(KEY, SYMBOL, "NFO", "NRML", "live")
    monitor._dispatch_exit(KEY, decided, "sl", 90.0)
    assert started == []

    # Replaced by a sync with a fresh row: the next tick decides again.
    monitor._states[KEY] = _long(trailing_enabled=False)
    monitor._dispatch_exit(KEY, decided, "sl", 90.0)
    assert started == []

    monitor._dispatch_exit(KEY, monitor._states[KEY], "sl", 90.0)
    assert _wait_for(lambda: started == [KEY], 2)


def test_sync_cannot_bring_back_a_stop_cleared_while_it_read(monitor, monkeypatch):
    """The exit clears the stop between sync's read and its install."""
    row = _long()
    monkeypatch.setattr(monitor, "_ensure_ws", lambda: False)

    def get_active_sl_states(mode=None):
        rows = [dict(row)]
        # The exit completes and clears the stop after this read was taken.
        clearing = threading.Thread(
            target=monitor._clear_state, args=(KEY, SYMBOL, "NFO", "NRML", "live")
        )
        clearing.start()
        clearing.join(5)
        return rows

    monkeypatch.setattr(scalping_db, "get_active_sl_states", get_active_sl_states)
    monitor._states[KEY] = _long()

    monitor.sync()

    assert KEY not in monitor._states, "sync reinstalled a stop its exit had already cleared"
    assert monitor._cleared == {}, "a finished sync left clear markers behind"
    assert monitor._syncs_in_flight == {}


def test_a_stop_saved_after_the_sync_read_is_still_installed(monitor, monkeypatch):
    """Only stops cleared during the read are dropped, not ones added."""
    monkeypatch.setattr(monitor, "_ensure_ws", lambda: False)
    monkeypatch.setattr(scalping_db, "get_active_sl_states", lambda mode=None: [dict(_long())])

    monitor.sync()

    assert KEY in monitor._states


def test_a_clear_with_no_sync_running_leaves_no_marker(monitor):
    monitor._states[KEY] = _long()

    monitor._clear_state(KEY, SYMBOL, "NFO", "NRML", "live")

    assert monitor._cleared == {}


def test_a_reconnect_subscribes_every_symbol_a_stop_needs(monitor):
    """A subscribe that failed while the feed was reconnecting is retried."""
    ws = SlowWs()
    monitor._ws = ws
    monitor._states[KEY] = _long()
    monitor._subscribed = set()

    monitor._on_auth({"status": "success"})

    requested = {(s["exchange"], s["symbol"]) for batch in ws.subscribed for s in batch}
    assert requested == {("NFO", SYMBOL)}
    assert monitor._subscribed == {mod._symkey(SYMBOL, "NFO")}


def test_a_replaced_client_gets_the_callbacks_once(monitor, monkeypatch):
    import services.websocket_client as websocket_client

    clients = [SlowWs(), SlowWs()]
    handed = iter(clients)
    monkeypatch.setattr(websocket_client, "get_websocket_client", lambda key: next(handed))
    monkeypatch.setattr(monitor, "_resolve_api_key", lambda: "k")

    assert monitor._ensure_ws()
    assert monitor._ensure_ws()  # still alive: not fetched again
    clients[0].alive = False
    monitor._subscribed = {mod._symkey(SYMBOL, "NFO")}
    assert monitor._ensure_ws()

    assert monitor._ws is clients[1]
    assert clients[1].callbacks["market_data"].count(monitor._on_tick) == 1
    assert clients[1].callbacks["auth"].count(monitor._on_auth) == 1
    # The replacement holds none of the old client's subscriptions.
    assert monitor._subscribed == set()


# ---------------------------------------------------------------------------
# Under eventlet
# ---------------------------------------------------------------------------


EVENTLET_BODY = """
import eventlet
eventlet.monkey_patch()

import time

import database.scalping_db as scalping_db
import extensions
import services.scalping_risk_monitor_service as mod

extensions.socketio.emit = lambda *a, **k: None
scalping_db.delete_sl_state = lambda *a, **k: True
scalping_db.upsert_sl_state = lambda *a, **k: True

mon = mod.ScalpingRiskMonitor()
mon._mode = lambda: "live"


class SlowWs:
    alive = connected = True
    callbacks = {}

    def unsubscribe(self, symbols, mode="LTP"):
        eventlet.sleep(1.0)
        return {"status": "success"}

    def subscribe(self, symbols, mode="LTP"):
        return {"status": "success"}


mon._ws = SlowWs()
sym = "NIFTY25JUN2623600CE"
key = mod._slkey(sym, "NFO", "NRML")
other = "BANKNIFTY25JUN2650000CE"
base = {"exchange": "NFO", "product": "NRML", "side": "BUY", "entry_price": 100.0,
        "initial_sl": 95.0, "current_sl": 95.0, "target": 0.0, "trailing_enabled": True,
        "trailing_step": 3.0, "highest_price": None, "lowest_price": None, "mode": "live"}
mon._states = {key: dict(base, symbol=sym),
               mod._slkey(other, "NFO", "NRML"): dict(base, symbol=other)}
mon._subscribed = {mod._symkey(sym, "NFO"), mod._symkey(other, "NFO")}

clearing = eventlet.spawn(mon._clear_state, key, sym, "NFO", "NRML", "live")
eventlet.sleep(0.05)
began = time.monotonic()
mon._on_tick({"type": "market_data", "symbol": other, "exchange": "NFO",
              "data": {"ltp": 110.0}})
elapsed = time.monotonic() - began
clearing.wait()
assert elapsed < 0.2, f"a greenlet's tick waited {elapsed:.2f}s"
assert key not in mon._states
print("OK")
"""


def test_under_eventlet_a_tick_greenlet_is_not_held_up_by_a_clear():
    pytest.importorskip(
        "eventlet",
        reason="eventlet is installed by the production installer, not by pyproject",
    )
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(EVENTLET_BODY)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert "OK" in result.stdout, result.stderr[-4000:]
