"""Unit tests for the symbol exit watch (position calculator SL/target).

Covers the decision logic — the part that is pure, translated from a DB row
into ``services/risk`` and evaluated per tick — plus the registration gate that
decides whether a placed order is worth watching at all. DB-touching paths are
thin ORM wrappers already exercised by scalping tests, so they stay out.
"""

import pytest

from services.risk.position import evaluate_position_state
from services.symbol_exit_monitor_service import (
    SymbolExitMonitor,
    _is_usable_price,
    _symkey,
    register_exit_watch,
)


def base_row(**overrides):
    row = {
        "id": 1,
        "symbol": "SBI",
        "exchange": "NSE",
        "product": "MIS",
        "side": "BUY",
        "mode": "live",
        "order_id": "o1",
        "strategy": "",
        "quantity": 75,
        "entry_price": 100.0,
        "stop_loss": 80.0,
        "target": 120.0,
        "trailing_step": None,
        "current_stop": None,
        "highest_price": None,
        "lowest_price": None,
    }
    row.update(overrides)
    return row


def build(row):
    monitor = SymbolExitMonitor()
    return monitor._build_state(row)


class TestTranslation:
    def test_symkey_orders_exchange_first(self):
        assert _symkey("NSE", "SBI") == "NSE:SBI"

    def test_usable_price_boundaries(self):
        assert _is_usable_price(1.5)
        assert _is_usable_price("250.75")
        assert not _is_usable_price(0)
        assert not _is_usable_price(None)
        assert not _is_usable_price("")
        assert not _is_usable_price("abc")

    def test_build_state_passes_risk_keys_through(self):
        state = build(
            base_row(
                entry_price=100.0,
                stop_loss=80.0,
                target=120.0,
                trailing_step=5.0,
                current_stop=88.0,
                highest_price=130.0,
                lowest_price=90.0,
            )
        )
        assert state["side"] == "BUY"
        assert state["entry_price"] == 100.0
        assert state["initial_sl"] == 80.0
        assert state["current_sl"] == 88.0
        assert state["target"] == 120.0
        assert state["trailing_enabled"] is True
        assert state["trailing_step"] == 5.0
        assert state["highest_price"] == 130.0
        assert state["lowest_price"] == 90.0
        assert state["identifier"] == "1"

    def test_build_state_disables_trailing_without_a_step(self):
        state = build(base_row())
        assert state["trailing_enabled"] is False
        assert state["trailing_step"] == 0.0

    def test_build_state_falls_back_to_sl_for_current_stop(self):
        state = build(base_row(current_stop=None, stop_loss=80.0))
        assert state["current_sl"] == 80.0


class TestLevelBreach:
    def _eval(self, **overrides):
        return evaluate_position_state(build(base_row(**overrides)), overrides.pop("ltp"))

    def test_long_stop_breach(self):
        decision = evaluate_position_state(build(base_row()), 79.5)
        assert decision.breached
        assert str(decision.reason) == "sl"

    def test_long_target_breach(self):
        decision = evaluate_position_state(build(base_row()), 120.5)
        assert decision.breached
        assert str(decision.reason) == "target"

    def test_long_in_range_no_breach(self):
        decision = evaluate_position_state(build(base_row()), 100.0)
        assert not decision.breached

    def test_short_stop_breach(self):
        decision = evaluate_position_state(
            build(base_row(side="SELL", stop_loss=120.0, target=80.0)), 121.0
        )
        assert decision.breached
        assert str(decision.reason) == "sl"

    def test_short_target_breach(self):
        decision = evaluate_position_state(
            build(base_row(side="SELL", stop_loss=120.0, target=80.0)), 79.0
        )
        assert decision.breached
        assert str(decision.reason) == "target"

    def test_short_below_entry_no_breach(self):
        decision = evaluate_position_state(
            build(base_row(side="SELL", stop_loss=120.0, target=80.0)), 100.0
        )
        assert not decision.breached


class TestTrailing:
    def test_new_high_tightens_stop(self):
        state = build(base_row(stop_loss=80.0, trailing_step=5.0))
        first = evaluate_position_state(state, 118.0)
        assert not first.breached
        assert first.stop_price == 113.0
        assert first.highest_price == 118.0

        state["current_sl"] = first.stop_price
        state["highest_price"] = first.highest_price
        state["lowest_price"] = first.lowest_price

        decision = evaluate_position_state(state, 112.5)
        assert decision.breached
        assert str(decision.reason) == "sl"

    def test_no_trailing_still_uses_flat_stop(self):
        state = build(base_row(stop_loss=80.0, trailing_step=None))
        decision = evaluate_position_state(state, 118.0)
        assert not decision.breached
        assert decision.stop_price == 80.0


class TestRegistrationGate:
    def test_none_without_any_risk_leg(self):
        order_data = {
            "symbol": "SBI",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": 1,
        }
        assert (
            register_exit_watch(
                order_data,
                {"stoploss": None, "target": None, "trailing_stoploss": None},
                "o1",
                "live",
            )
            is None
        )
        assert (
            register_exit_watch(order_data, {}, "o1", "live") is None
        )

    def test_stop_loss_alone_gates_in(self, monkeypatch):
        order_data = {
            "symbol": "SBI",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": 1,
        }
        import database.symbol_exit_db as db_mod
        import services.symbol_exit_monitor_service as monitor_mod

        calls = []

        def fake_create_exit_watch(payload):
            calls.append(payload)
            return {"id": 9, **payload}

        monkeypatch.setattr(db_mod, "create_exit_watch", fake_create_exit_watch)
        # register_exit_watch does `from database.symbol_exit_db import create_exit_watch`
        # at call time, so the monkeypatch already covers it. The feed reconcile
        # must not run (it would hit the real DB / proxy), so drop it here.
        monkeypatch.setattr(
            monitor_mod.SymbolExitMonitor, "request_sync", lambda self: None
        )

        result = register_exit_watch(
            order_data,
            {"stoploss": 80.0, "target": None, "trailing_stoploss": None},
            "o1",
            "live",
        )

        assert result is not None
        assert result["stop_loss"] == 80.0
        assert calls
        assert calls[0]["mode"] == "live"
        assert calls[0]["symbol"] == "SBI"
        assert calls[0]["trailing_step"] is None
