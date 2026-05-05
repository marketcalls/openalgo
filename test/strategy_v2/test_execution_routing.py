"""Execution-routing tests — validates services/strategy/execution_service
selects the right BrokerAdapter method per leg-segment composition.

Plan §5.2 matrix:
  CASH/FUT single  → place_order
  CASH/FUT multi   → basket_order  (single API call)
  OPT single       → place_options_order
  OPT multi        → place_options_multiorder  (BUYs first)
  Mixed CASH/FUT + OPT  → basket_order then options_multiorder

Uses a FakeAdapter that records call signatures. Bypasses DB writes via
db_session mocking — execution_service writes strategy_orders and calls
transition_run, both of which we don't need for routing assertions.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.strategy.broker_adapter import BrokerAdapter


class FakeAdapter(BrokerAdapter):
    """Records every call so the test can assert which methods fired."""

    mode = "live"

    def __init__(self):
        self.calls = []  # list of (method_name, payload)
        # Per-method response — tests can override to simulate failures.
        self.responses = {
            "place_order": (True, {"status": "success", "orderid": "OID1", "timestamp": "x"}, 200),
            "place_options_order": (
                True,
                {"status": "success", "orderid": "OID2", "symbol": "NIFTY...CE"},
                200,
            ),
            "place_options_multiorder": (
                True,
                {
                    "status": "success",
                    "underlying": "NIFTY",
                    "results": [],  # filled per-test
                },
                200,
            ),
            "basket_order": (
                True,
                {"status": "success", "results": []},  # filled per-test
                200,
            ),
        }

    def _record(self, name, payload):
        self.calls.append((name, payload))
        return self.responses[name]

    def place_order(self, order_data):
        return self._record("place_order", order_data)

    def place_options_order(self, options_data):
        return self._record("place_options_order", options_data)

    def place_options_multiorder(self, multiorder_data):
        n = len(multiorder_data.get("legs", []))
        # Synthesize per-leg success rows.
        self.responses["place_options_multiorder"] = (
            True,
            {
                "status": "success",
                "underlying": multiorder_data.get("underlying"),
                "results": [
                    {"leg": i + 1, "status": "success", "orderid": f"OPT{i+1}"}
                    for i in range(n)
                ],
            },
            200,
        )
        return self._record("place_options_multiorder", multiorder_data)

    def basket_order(self, basket_data):
        n = len(basket_data.get("orders", []))
        self.responses["basket_order"] = (
            True,
            {
                "status": "success",
                "results": [
                    {"status": "success", "orderid": f"BO{i+1}"}
                    for i in range(n)
                ],
            },
            200,
        )
        return self._record("basket_order", basket_data)

    def cancel_order(self, orderid):
        return self._record("cancel_order", {"orderid": orderid})

    def get_order_status(self, orderid):
        return self._record("get_order_status", {"orderid": orderid})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_strategy(legs):
    return SimpleNamespace(
        id=1,
        underlying="NIFTY",
        underlying_exchange="NSE_INDEX",
        legs=legs,
    )


def _cash_leg(idx, qty=10, position="B", symbol="INFY"):
    return SimpleNamespace(
        id=idx, leg_index=idx, segment="CASH",
        position=position, product="MIS",
        symbol_cash=symbol, qty=qty,
        lots=None, expiry_type=None,
        option_type=None, strike_criteria=None, strike_value=None,
        resolved_symbol=symbol, resolved_exchange="NSE",
        lot_size_cache=1, tick_size_cache=0.05,
    )


def _fut_leg(idx, position="B", lots=1):
    return SimpleNamespace(
        id=idx, leg_index=idx, segment="FUT",
        position=position, product="NRML",
        symbol_cash=None, qty=None,
        lots=lots, expiry_type="CURRENT_MONTH",
        option_type=None, strike_criteria=None, strike_value=None,
        resolved_symbol="NIFTY30MAY26FUT", resolved_exchange="NFO",
        lot_size_cache=75, tick_size_cache=0.05,
    )


def _opt_leg(idx, position="S", option_type="CE", strike_criteria="ATM", strike_value=0):
    return SimpleNamespace(
        id=idx, leg_index=idx, segment="OPT",
        position=position, product="NRML",
        symbol_cash=None, qty=None,
        lots=1, expiry_type="CURRENT_WEEK",
        option_type=option_type, strike_criteria=strike_criteria, strike_value=strike_value,
        resolved_symbol="NIFTY30MAY2626000CE", resolved_exchange="NFO",
        lot_size_cache=75, tick_size_cache=0.05,
    )


@pytest.fixture
def execution_module():
    """Patch DB + state-machine writes so execute_entry runs against the
    FakeAdapter without touching the real DB."""
    from services.strategy import execution_service

    with patch.object(execution_service, "db_session"), \
         patch.object(execution_service, "transition_run", return_value=True), \
         patch.object(execution_service, "_persist_order_row"):
        yield execution_service


# ---------------------------------------------------------------------------
# Single-leg routing
# ---------------------------------------------------------------------------


def test_single_cash_leg_uses_place_order(execution_module):
    legs = [_cash_leg(1)]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    ok, summary = execution_module.execute_entry(
        strategy=s, run_id=99, legs=legs, adapter=adapter,
    )
    assert ok is True
    assert summary["orders_placed"] == 1
    assert [c[0] for c in adapter.calls] == ["place_order"]


def test_single_fut_leg_uses_place_order(execution_module):
    legs = [_fut_leg(1)]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    execution_module.execute_entry(strategy=s, run_id=99, legs=legs, adapter=adapter)
    assert [c[0] for c in adapter.calls] == ["place_order"]
    # FUT qty = lots × lot_size_cache = 1 × 75
    assert adapter.calls[0][1]["quantity"] == 75


def test_single_opt_leg_uses_place_options_order(execution_module):
    legs = [_opt_leg(1)]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    execution_module.execute_entry(strategy=s, run_id=99, legs=legs, adapter=adapter)
    assert [c[0] for c in adapter.calls] == ["place_options_order"]
    # Underlying + exchange propagated from strategy
    payload = adapter.calls[0][1]
    assert payload["underlying"] == "NIFTY"
    assert payload["exchange"] == "NSE_INDEX"


# ---------------------------------------------------------------------------
# Multi-leg routing
# ---------------------------------------------------------------------------


def test_multi_cash_legs_use_basket_order(execution_module):
    legs = [_cash_leg(1, symbol="INFY"), _cash_leg(2, symbol="TCS"), _cash_leg(3, symbol="WIPRO")]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    ok, summary = execution_module.execute_entry(
        strategy=s, run_id=99, legs=legs, adapter=adapter,
    )
    assert ok is True
    assert summary["orders_placed"] == 3
    # Single basket_order call, NOT three place_order calls
    method_calls = [c[0] for c in adapter.calls]
    assert method_calls == ["basket_order"]
    basket_payload = adapter.calls[0][1]
    assert len(basket_payload["orders"]) == 3


def test_multi_fut_legs_use_basket_order(execution_module):
    legs = [_fut_leg(1), _fut_leg(2, position="S")]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    execution_module.execute_entry(strategy=s, run_id=99, legs=legs, adapter=adapter)
    assert [c[0] for c in adapter.calls] == ["basket_order"]


def test_mixed_cash_fut_uses_basket_order(execution_module):
    legs = [_cash_leg(1), _fut_leg(2)]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    execution_module.execute_entry(strategy=s, run_id=99, legs=legs, adapter=adapter)
    assert [c[0] for c in adapter.calls] == ["basket_order"]


def test_multi_opt_legs_use_options_multiorder(execution_module):
    legs = [
        _opt_leg(1, position="S", option_type="CE", strike_criteria="STRIKE_OFFSET", strike_value=4),
        _opt_leg(2, position="S", option_type="PE", strike_criteria="STRIKE_OFFSET", strike_value=4),
        _opt_leg(3, position="B", option_type="CE", strike_criteria="STRIKE_OFFSET", strike_value=6),
        _opt_leg(4, position="B", option_type="PE", strike_criteria="STRIKE_OFFSET", strike_value=6),
    ]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    ok, summary = execution_module.execute_entry(
        strategy=s, run_id=99, legs=legs, adapter=adapter,
    )
    assert ok is True
    assert [c[0] for c in adapter.calls] == ["place_options_multiorder"]
    # 4 legs → 4 entries in payload
    assert len(adapter.calls[0][1]["legs"]) == 4
    assert summary["orders_placed"] == 4


def test_mixed_cash_fut_and_opt_uses_two_calls(execution_module):
    """CASH/FUT goes through basket_order; OPT through options_multiorder.
    Two API calls total, in that order."""
    legs = [
        _cash_leg(1, symbol="INFY"),
        _opt_leg(2, position="B", option_type="CE", strike_criteria="ATM"),
        _opt_leg(3, position="B", option_type="PE", strike_criteria="ATM"),
    ]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    execution_module.execute_entry(strategy=s, run_id=99, legs=legs, adapter=adapter)
    method_calls = [c[0] for c in adapter.calls]
    assert method_calls == ["place_order", "place_options_multiorder"]


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_basket_failure_marks_entry_failed(execution_module):
    legs = [_cash_leg(1, symbol="INFY"), _cash_leg(2, symbol="TCS")]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    # Override basket_order to return failure.
    adapter.basket_order = lambda data: (
        False, {"status": "error", "message": "broker rejected"}, 500,
    )
    ok, summary = execution_module.execute_entry(
        strategy=s, run_id=99, legs=legs, adapter=adapter,
    )
    assert ok is False
    assert summary["errors"]


def test_partial_basket_success_recorded(execution_module):
    legs = [_cash_leg(1, symbol="INFY"), _cash_leg(2, symbol="TCS")]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    # First leg succeeds, second fails.
    adapter.basket_order = lambda data: (
        True,
        {
            "status": "success",
            "results": [
                {"status": "success", "orderid": "OK1"},
                {"status": "error", "message": "out of margin"},
            ],
        },
        200,
    )
    ok, summary = execution_module.execute_entry(
        strategy=s, run_id=99, legs=legs, adapter=adapter,
    )
    assert ok is False
    assert summary["orders_placed"] == 1
    assert summary["errors"] and summary["errors"][0]["message"] == "out of margin"


# ---------------------------------------------------------------------------
# Quantity calculations
# ---------------------------------------------------------------------------


def test_cash_uses_raw_qty_not_lots(execution_module):
    legs = [_cash_leg(1, symbol="HDFCBANK", qty=250)]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    execution_module.execute_entry(strategy=s, run_id=99, legs=legs, adapter=adapter)
    assert adapter.calls[0][1]["quantity"] == 250


def test_fut_quantity_multiplies_lots_by_lot_size(execution_module):
    legs = [_fut_leg(1, lots=3)]  # lot_size_cache=75
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    execution_module.execute_entry(strategy=s, run_id=99, legs=legs, adapter=adapter)
    assert adapter.calls[0][1]["quantity"] == 225  # 3 × 75


def test_opt_quantity_multiplies_lots_by_lot_size(execution_module):
    legs = [_opt_leg(1)]  # 1 lot × 75
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    execution_module.execute_entry(strategy=s, run_id=99, legs=legs, adapter=adapter)
    payload = adapter.calls[0][1]
    assert payload["quantity"] == 75


# ---------------------------------------------------------------------------
# Action mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("position,expected_action", [("B", "BUY"), ("S", "SELL")])
def test_position_maps_to_action(execution_module, position, expected_action):
    legs = [_cash_leg(1, position=position)]
    s = _fake_strategy(legs)
    adapter = FakeAdapter()
    execution_module.execute_entry(strategy=s, run_id=99, legs=legs, adapter=adapter)
    assert adapter.calls[0][1]["action"] == expected_action
