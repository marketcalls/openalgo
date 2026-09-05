"""Unit tests for the symbol exit watch (position calculator SL/target).

Covers the decision logic — the part that is pure, translated from a DB row
into ``services/risk`` and evaluated per tick — plus the registration gate that
decides whether a placed order is worth watching at all. DB-touching paths are
thin ORM wrappers already exercised by scalping tests, so they stay out.
"""

from unittest.mock import Mock

import pytest

from services.risk.position import evaluate_position_state
from services.symbol_exit_monitor_service import (
    SymbolExitMonitor,
    _classify_entry,
    _exit_sizing,
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

    def test_build_state_carries_watch_status(self):
        assert build(base_row())["status"] == "active"
        assert build(base_row(status="pending"))["status"] == "pending"


class TestEntryClassification:
    """A broker accepts an order before filling it; the watch must only become
    active once the entry order is confirmed filled."""

    def test_complete_status_activates(self):
        assert _classify_entry({"order_status": "complete"}) == "filled"
        assert _classify_entry({"order_status": "filled"}) == "filled"

    def test_partial_fill_activates(self):
        assert _classify_entry({"order_status": "open", "filled_quantity": 25}) == "filled"

    def test_open_and_trigger_pending_stay_waiting(self):
        assert _classify_entry({"order_status": "open"}) == "open"
        assert _classify_entry({"order_status": "trigger pending"}) == "open"
        assert _classify_entry({"order_status": "unknown"}) == "open"
        assert _classify_entry({"order_status": ""}) == "open"

    def test_rejected_and_cancelled_drop_the_watch(self):
        assert _classify_entry({"order_status": "rejected"}) == "dead"
        assert _classify_entry({"order_status": "cancelled"}) == "dead"


class TestPendingResolution:
    def test_filled_entry_waits_for_positionbook_propagation(self, monkeypatch):
        monitor = SymbolExitMonitor()
        monkeypatch.setattr(monitor, "_mode", lambda: "live")
        monkeypatch.setattr(monitor, "_resolve_api_key", lambda: "k")
        monkeypatch.setattr(monitor, "_find_entry_order", lambda *a: {"order_status": "complete"})
        monkeypatch.setattr(monitor, "_position_open", lambda *a: False)
        activate = Mock()
        monkeypatch.setattr(monitor, "_set_active", activate)
        monitor._resolve_pending(1, build(base_row(status="pending")))
        activate.assert_not_called()

    @pytest.mark.parametrize("status", ["open", "cancelled"])
    def test_partial_fill_without_orderbook_quantity_activates(self, monkeypatch, status):
        monitor = SymbolExitMonitor()
        state = build(base_row(status="pending"))
        monkeypatch.setattr(monitor, "_mode", lambda: "live")
        monkeypatch.setattr(monitor, "_resolve_api_key", lambda: "k")
        monkeypatch.setattr(monitor, "_find_entry_order", lambda *a: {"order_status": status})
        monkeypatch.setattr(monitor, "_position_open", lambda *a: True)
        monkeypatch.setattr(
            "services.tradebook_service.get_tradebook",
            lambda **kw: (
                True,
                {
                    "data": [
                        {
                            "orderid": "o1",
                            "symbol": "SBI",
                            "exchange": "NSE",
                            "product": "MIS",
                            "action": "BUY",
                            "quantity": 5,
                            "average_price": 101,
                        },
                        {
                            "orderid": "o1",
                            "symbol": "SBI",
                            "exchange": "NSE",
                            "product": "MIS",
                            "action": "BUY",
                            "quantity": 5,
                            "average_price": 103,
                        },
                    ]
                },
                200,
            ),
        )
        seed, activate = Mock(), Mock()
        monkeypatch.setattr(monitor, "_seed_fill_price", seed)
        monkeypatch.setattr(monitor, "_set_active", activate)
        monitor._resolve_pending(1, state)
        seed.assert_called_once_with(1, state, 102)
        activate.assert_called_once_with(1, state)

    @pytest.mark.parametrize("trades", [[], None])
    def test_open_entry_does_not_borrow_unrelated_position(self, monkeypatch, trades):
        monitor = SymbolExitMonitor()
        monkeypatch.setattr(monitor, "_mode", lambda: "live")
        monkeypatch.setattr(monitor, "_resolve_api_key", lambda: "k")
        monkeypatch.setattr(monitor, "_find_entry_order", lambda *a: {"order_status": "open"})
        monkeypatch.setattr(monitor, "_entry_trades", lambda *a: trades)
        activate, position = Mock(), Mock(return_value=True)
        monkeypatch.setattr(monitor, "_set_active", activate)
        monkeypatch.setattr(monitor, "_position_open", position)
        monitor._resolve_pending(1, build(base_row(status="pending")))
        activate.assert_not_called()
        position.assert_not_called()

    def test_trade_lookup_excludes_other_entries(self, monkeypatch):
        monkeypatch.setattr(
            "services.tradebook_service.get_tradebook",
            lambda **kw: (
                True,
                {"data": [{"orderid": "another-order", "quantity": 50, "average_price": 100}]},
                200,
            ),
        )
        assert SymbolExitMonitor()._entry_trades(build(base_row()), "k") == []


class TestAutomaticExitRouting:
    def test_partial_entry_remainder_is_cancelled_before_exit(self, monkeypatch):
        monitor = SymbolExitMonitor()
        lookup = Mock(
            side_effect=[
                {"order_status": "open", "filled_quantity": 5},
                {"order_status": "cancelled", "filled_quantity": 5},
            ]
        )
        monkeypatch.setattr(monitor, "_find_entry_order", lookup)
        monkeypatch.setattr("database.auth_db.get_auth_token_broker", lambda key: ("token", "test"))
        cancel = Mock(return_value=(True, {}, 200))
        monkeypatch.setattr("services.cancel_order_service.cancel_order", cancel)
        assert monitor._cancel_entry_remainder(build(base_row()), "k")
        cancel.assert_called_once_with("o1", api_key="k", auth_token="token", broker="test")

    def test_unconfirmed_entry_cancellation_keeps_protection(self, monkeypatch):
        monitor = SymbolExitMonitor()
        monkeypatch.setattr(monitor, "_find_entry_order", lambda *a: {"order_status": "open"})
        monkeypatch.setattr("database.auth_db.get_auth_token_broker", lambda key: ("token", "test"))
        monkeypatch.setattr(
            "services.cancel_order_service.cancel_order", Mock(return_value=(True, {}, 200))
        )
        assert not monitor._cancel_entry_remainder(build(base_row()), "k")

    def test_semi_auto_queue_is_bypassed_with_broker_auth(self, monkeypatch):
        monkeypatch.setattr("database.auth_db.get_auth_token_broker", lambda key: ("token", "test"))
        monkeypatch.setattr(
            "services.place_order_service.validate_order_data", lambda data: (True, data, None)
        )
        queue = Mock(return_value=True)
        place = Mock(return_value=(True, {"orderid": "exit"}, 200))
        monkeypatch.setattr("services.order_router_service.should_route_to_pending", queue)
        monkeypatch.setattr("services.place_order_service.place_order_with_auth", place)
        assert SymbolExitMonitor()._place_exit(build(base_row()), "SELL", 5, "k")[0]
        queue.assert_not_called()
        assert place.call_args.args[1:3] == ("token", "test")
        assert place.call_args.args[3]["apikey"] == "k"

    def test_subscribe_only_records_accepted_symbols(self, monkeypatch):
        monitor = SymbolExitMonitor()
        ws = Mock()
        ws.subscribe.return_value = {
            "status": "partial",
            "subscriptions": [
                {"symbol": "SBI", "exchange": "NSE", "status": "success"},
                {"symbol": "BAD", "exchange": "NSE", "status": "error"},
            ],
        }
        monkeypatch.setattr(monitor, "_ws", ws)
        monkeypatch.setattr(monitor, "_subscribed", set())
        monitor._subscribe({"NSE:SBI", "NSE:BAD"})
        assert monitor._subscribed == {"NSE:SBI"}

    def test_closed_watch_requests_subscription_reconciliation(self, monkeypatch):
        monitor = SymbolExitMonitor()
        monkeypatch.setattr("database.symbol_exit_db.mark_watch_executed", Mock())
        reconcile = Mock()
        monkeypatch.setattr(monitor, "request_sync", reconcile)
        monitor._closed(999, "sl", 80)
        reconcile.assert_called_once()


class TestExitSizing:
    """An exit protects its watched entry; it must never square an aggregate
    position that shares the symbol/exchange/product with other exposure."""

    def test_exit_capped_to_watched_quantity(self):
        state = build(base_row(quantity=10, side="BUY"))
        assert _exit_sizing(state, 110) == ("SELL", 10)

    def test_exit_uses_remaining_net_when_less_than_watch(self):
        state = build(base_row(quantity=10, side="BUY"))
        assert _exit_sizing(state, 6) == ("SELL", 6)

    def test_buy_flat_nothing_to_exit(self):
        state = build(base_row(quantity=10, side="BUY"))
        assert _exit_sizing(state, 0) is None

    def test_sell_side_exits_buy_capped(self):
        state = build(base_row(quantity=75, side="SELL"))
        assert _exit_sizing(state, -110) == ("BUY", 75)

    def test_sell_flat_or_flipped_nothing_to_exit(self):
        state = build(base_row(quantity=75, side="SELL"))
        assert _exit_sizing(state, 0) is None
        assert _exit_sizing(state, 20) is None


class TestNetQtyNeverReadsFailureAsFlat:
    """A transient positionbook failure must keep the watch open, not clear it
    as a flat position without placing the exit."""

    def test_broker_error_is_not_flat(self, monkeypatch):
        def fake(api_key=None, **kwargs):
            return False, {"status": "error", "message": "down"}, 500

        monkeypatch.setattr("services.positionbook_service.get_positionbook", fake)
        assert SymbolExitMonitor()._net_qty(build(base_row()), "k") is None

    def test_exception_is_not_flat(self, monkeypatch):
        def fake(api_key=None, **kwargs):
            raise RuntimeError("connection reset")

        monkeypatch.setattr("services.positionbook_service.get_positionbook", fake)
        assert SymbolExitMonitor()._net_qty(build(base_row()), "k") is None

    def test_malformed_response_is_not_flat(self, monkeypatch):
        def fake(api_key=None, **kwargs):
            return True, {"status": "success", "data": "oops"}, 200

        monkeypatch.setattr("services.positionbook_service.get_positionbook", fake)
        assert SymbolExitMonitor()._net_qty(build(base_row()), "k") is None

    def test_genuine_flat_returns_zero(self, monkeypatch):
        def fake(api_key=None, **kwargs):
            return True, {"status": "success", "data": []}, 200

        monkeypatch.setattr("services.positionbook_service.get_positionbook", fake)
        assert SymbolExitMonitor()._net_qty(build(base_row()), "k") == 0

    def test_matching_position_returns_signed_quantity(self, monkeypatch):
        def fake(api_key=None, **kwargs):
            return (
                True,
                {
                    "status": "success",
                    "data": [
                        {"symbol": "SBI", "exchange": "NSE", "product": "MIS", "quantity": 75}
                    ],
                },
                200,
            )

        monkeypatch.setattr("services.positionbook_service.get_positionbook", fake)
        assert SymbolExitMonitor()._net_qty(build(base_row()), "k") == 75

    def test_position_open_only_when_net_matches_watch_side(self, monkeypatch):
        def fake(api_key=None, **kwargs):
            return (
                True,
                {
                    "status": "success",
                    "data": [
                        {"symbol": "SBI", "exchange": "NSE", "product": "MIS", "quantity": -90}
                    ],
                },
                200,
            )

        monkeypatch.setattr("services.positionbook_service.get_positionbook", fake)
        monitor = SymbolExitMonitor()
        # A short net of -90 is not a BUY watch's position: do not activate it.
        assert monitor._position_open(build(base_row(side="BUY")), "k") is False
        assert monitor._position_open(build(base_row(side="SELL")), "k") is True


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
        assert register_exit_watch(order_data, {}, "o1", "live") is None

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
        monkeypatch.setattr(monitor_mod.SymbolExitMonitor, "request_sync", lambda self: None)

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
