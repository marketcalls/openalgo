"""
Tests for the server-side scalping risk monitor's SL / TP / TSL trigger logic.

Covers the pure decision core (evaluate_trail) for long and short legs, and the
event-driven tick path (_on_tick) that fires exits — all without touching a
broker, the DB, or the network (the exit + persist sinks are monkeypatched).

Run: uv run pytest test/test_scalping_risk_monitor.py -v
"""

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

mod = importlib.import_module("services.scalping_risk_monitor_service")
evaluate_trail = mod.evaluate_trail
ScalpingRiskMonitor = mod.ScalpingRiskMonitor


# --------------------------------------------------------------------- evaluate_trail
def _long(**over):
    s = {
        "symbol": "NIFTY25JUN2623600CE",
        "exchange": "NFO",
        "product": "NRML",
        "side": "BUY",
        "entry_price": 100.0,
        "current_sl": 90.0,
        "initial_sl": 90.0,
        "target": 0.0,
        "trailing_enabled": False,
        "trailing_step": 0.0,
        "highest_price": 100.0,
        "lowest_price": 100.0,
    }
    s.update(over)
    return s


def _short(**over):
    s = _long(side="SELL", current_sl=110.0, initial_sl=110.0)
    s.update(over)
    return s


class TestStopLoss:
    def test_long_sl_breaches_at_or_below_stop(self):
        r = evaluate_trail(_long(current_sl=95.0), 95.0)
        assert r["breached"] and r["reason"] == "sl"
        r = evaluate_trail(_long(current_sl=95.0), 94.9)
        assert r["breached"] and r["reason"] == "sl"

    def test_long_sl_holds_above_stop(self):
        r = evaluate_trail(_long(current_sl=95.0), 95.1)
        assert not r["breached"]

    def test_short_sl_breaches_at_or_above_stop(self):
        r = evaluate_trail(_short(current_sl=105.0), 105.0)
        assert r["breached"] and r["reason"] == "sl"
        r = evaluate_trail(_short(current_sl=105.0), 105.1)
        assert r["breached"] and r["reason"] == "sl"

    def test_short_sl_holds_below_stop(self):
        r = evaluate_trail(_short(current_sl=105.0), 104.9)
        assert not r["breached"]


class TestTarget:
    def test_long_target_breaches_at_or_above(self):
        r = evaluate_trail(_long(target=120.0), 120.0)
        assert r["breached"] and r["reason"] == "target"

    def test_long_target_holds_below(self):
        r = evaluate_trail(_long(target=120.0), 119.9)
        assert not r["breached"]

    def test_short_target_breaches_at_or_below(self):
        r = evaluate_trail(_short(target=80.0), 80.0)
        assert r["breached"] and r["reason"] == "target"

    def test_short_target_holds_above(self):
        r = evaluate_trail(_short(target=80.0), 80.1)
        assert not r["breached"]

    def test_sl_takes_priority_when_both_hit(self):
        # Long: price below SL and ... target is above, so only SL hits here.
        r = evaluate_trail(_long(current_sl=95.0, target=120.0), 90.0)
        assert r["breached"] and r["reason"] == "sl"


class TestTrailing:
    def test_long_trail_raises_stop(self):
        s = _long(trailing_enabled=True, trailing_step=3.0, current_sl=90.0)
        r = evaluate_trail(s, 110.0)
        # stop trails to highest(110) - step(3) = 107, no breach
        assert not r["breached"]
        assert r["current_sl"] == pytest.approx(107.0)
        assert r["highest_price"] == pytest.approx(110.0)

    def test_long_trail_only_moves_up(self):
        s = _long(trailing_enabled=True, trailing_step=3.0, current_sl=107.0, highest_price=110.0)
        # price pulls back to 108 (still above stop): stop must NOT drop below 107
        r = evaluate_trail(s, 108.0)
        assert not r["breached"]
        assert r["current_sl"] == pytest.approx(107.0)

    def test_long_trail_does_not_start_until_in_profit(self):
        # < MIN_TRAIL_PROFIT above entry => no trailing yet
        s = _long(trailing_enabled=True, trailing_step=3.0, current_sl=90.0, entry_price=100.0)
        r = evaluate_trail(s, 100.5)
        assert r["current_sl"] == pytest.approx(90.0)

    def test_long_trailed_stop_then_breaches(self):
        # Move up (trail to 107), then a tick at 106.9 must breach the trailed stop.
        s = _long(trailing_enabled=True, trailing_step=3.0, current_sl=90.0)
        r1 = evaluate_trail(s, 110.0)
        s2 = {**s, **r1}  # apply the trailed state
        r2 = evaluate_trail(s2, 106.9)
        assert r2["breached"] and r2["reason"] == "sl"

    def test_short_trail_lowers_stop(self):
        s = _short(trailing_enabled=True, trailing_step=3.0, current_sl=110.0)
        r = evaluate_trail(s, 90.0)
        # stop trails to lowest(90) + step(3) = 93, no breach
        assert not r["breached"]
        assert r["current_sl"] == pytest.approx(93.0)
        assert r["lowest_price"] == pytest.approx(90.0)

    def test_short_trailed_stop_then_breaches(self):
        s = _short(trailing_enabled=True, trailing_step=3.0, current_sl=110.0)
        r1 = evaluate_trail(s, 90.0)
        s2 = {**s, **r1}
        r2 = evaluate_trail(s2, 93.1)
        assert r2["breached"] and r2["reason"] == "sl"


# --------------------------------------------------------------------- _on_tick wiring
def _tick(symbol, exchange, ltp):
    return {"type": "market_data", "symbol": symbol, "exchange": exchange,
            "mode": "LTP", "data": {"ltp": ltp}}


class TestOnTickEventDriven:
    def setup_method(self):
        self.mon = ScalpingRiskMonitor()
        self.mon._states = {}
        self.mon._exit_inflight = set()
        self.mon._last_exit_attempt = {}
        self.mon._last_persist = {}

    def test_breach_dispatches_exit(self, monkeypatch):
        fired = []
        monkeypatch.setattr(self.mon, "_dispatch_exit",
                            lambda key, st, reason, ltp: fired.append((key, reason, ltp)))
        key = mod._slkey("NIFTY25JUN2623600CE", "NFO", "NRML")
        self.mon._states[key] = _long(current_sl=95.0)
        self.mon._on_tick(_tick("NIFTY25JUN2623600CE", "NFO", 94.0))
        assert len(fired) == 1
        assert fired[0][1] == "sl"

    def test_no_breach_no_exit(self, monkeypatch):
        fired = []
        monkeypatch.setattr(self.mon, "_dispatch_exit",
                            lambda *a: fired.append(a))
        key = mod._slkey("NIFTY25JUN2623600CE", "NFO", "NRML")
        self.mon._states[key] = _long(current_sl=95.0)
        self.mon._on_tick(_tick("NIFTY25JUN2623600CE", "NFO", 99.0))
        assert fired == []

    def test_trailing_updates_in_memory_and_persists(self, monkeypatch):
        persisted = []
        monkeypatch.setattr(self.mon, "_maybe_persist",
                            lambda key, st: persisted.append((key, st["current_sl"])))
        monkeypatch.setattr(self.mon, "_dispatch_exit",
                            lambda *a: pytest.fail("should not exit on a trailing tick"))
        key = mod._slkey("NIFTY25JUN2623600CE", "NFO", "NRML")
        self.mon._states[key] = _long(trailing_enabled=True, trailing_step=3.0, current_sl=90.0)
        self.mon._on_tick(_tick("NIFTY25JUN2623600CE", "NFO", 110.0))
        # in-memory state advanced and persist was invoked with the trailed stop
        assert self.mon._states[key]["current_sl"] == pytest.approx(107.0)
        assert persisted and persisted[0][1] == pytest.approx(107.0)

    def test_tick_for_unwatched_symbol_is_ignored(self, monkeypatch):
        monkeypatch.setattr(self.mon, "_dispatch_exit",
                            lambda *a: pytest.fail("no state for this symbol"))
        self.mon._on_tick(_tick("SOMETHINGELSE", "NFO", 1.0))  # no states at all

    def test_zero_or_missing_ltp_ignored(self, monkeypatch):
        monkeypatch.setattr(self.mon, "_dispatch_exit", lambda *a: pytest.fail("no ltp"))
        key = mod._slkey("NIFTY25JUN2623600CE", "NFO", "NRML")
        self.mon._states[key] = _long(current_sl=95.0)
        self.mon._on_tick(_tick("NIFTY25JUN2623600CE", "NFO", 0))
        self.mon._on_tick({"type": "market_data", "symbol": "NIFTY25JUN2623600CE",
                           "exchange": "NFO", "data": {}})


class TestModeSegregation:
    def setup_method(self):
        self.mon = ScalpingRiskMonitor()
        self.mon._states = {}
        self.mon._exit_inflight = set()
        self.mon._last_exit_attempt = {}

    def test_breaching_sl_in_other_mode_is_skipped(self, monkeypatch):
        # Current mode is live; a sandbox (analyze) SL must NOT fire.
        monkeypatch.setattr(self.mon, "_mode", lambda: "live")
        fired = []
        monkeypatch.setattr(self.mon, "_dispatch_exit", lambda *a: fired.append(a))
        key = mod._slkey("NIFTY25JUN2623600CE", "NFO", "NRML")
        self.mon._states[key] = _long(current_sl=95.0, mode="analyze")
        self.mon._on_tick(_tick("NIFTY25JUN2623600CE", "NFO", 94.0))  # would breach
        assert fired == []  # skipped because mode mismatch

    def test_breaching_sl_in_current_mode_fires(self, monkeypatch):
        monkeypatch.setattr(self.mon, "_mode", lambda: "live")
        fired = []
        monkeypatch.setattr(self.mon, "_dispatch_exit", lambda *a: fired.append(a))
        key = mod._slkey("NIFTY25JUN2623600CE", "NFO", "NRML")
        self.mon._states[key] = _long(current_sl=95.0, mode="live")
        self.mon._on_tick(_tick("NIFTY25JUN2623600CE", "NFO", 94.0))
        assert len(fired) == 1

    def test_exit_worker_skips_when_mode_changed_since_detection(self, monkeypatch):
        # Detection->exit race: if the global mode flipped to live but the SL is an
        # analyze SL, the exit worker must skip BEFORE routing (no wrong-mode exit,
        # no clearing) — guards the cubic stale-mode finding.
        monkeypatch.setattr(self.mon, "_mode", lambda: "live")
        reached = []
        monkeypatch.setattr(self.mon, "_resolve_auth", lambda: reached.append("auth"))
        self.mon._exit_worker(
            mod._slkey("X", "NFO", "NRML"),
            {"symbol": "X", "exchange": "NFO", "product": "NRML", "mode": "analyze"},
            "sl",
            100.0,
        )
        assert reached == []  # returned before resolving auth / placing any exit

    def test_request_sync_is_non_blocking(self, monkeypatch):
        # sync() does blocking WS calls; request_sync() must return immediately and
        # run sync() on a background worker (so /sl requests never hang ~12s).
        import threading
        import time as _t

        mon = ScalpingRiskMonitor()
        mon._sync_lock = threading.Lock()
        mon._sync_pending = False
        mon._sync_thread = None
        ran = threading.Event()

        def slow_sync():
            _t.sleep(0.3)
            ran.set()

        monkeypatch.setattr(mon, "sync", slow_sync)
        t0 = _t.monotonic()
        mon.request_sync()
        elapsed = _t.monotonic() - t0
        assert elapsed < 0.1, f"request_sync blocked for {elapsed:.3f}s"
        assert ran.wait(2.0), "background sync did not run"

    def test_unknown_mode_does_not_skip(self, monkeypatch):
        # If mode can't be resolved, don't skip — the exit worker's position check
        # is the backstop.
        monkeypatch.setattr(self.mon, "_mode", lambda: None)
        fired = []
        monkeypatch.setattr(self.mon, "_dispatch_exit", lambda *a: fired.append(a))
        key = mod._slkey("NIFTY25JUN2623600CE", "NFO", "NRML")
        self.mon._states[key] = _long(current_sl=95.0, mode="analyze")
        self.mon._on_tick(_tick("NIFTY25JUN2623600CE", "NFO", 94.0))
        assert len(fired) == 1
