"""Phase 2 — serializer tests.

Asserts that the strategy-scoped envelopes match the global /orderbook,
/tradebook, /positionbook contracts byte-for-byte on field names so the
frontend can reuse table components.

Pure-function tests — no DB. Builds SimpleNamespace objects that quack like
SQLAlchemy rows (the serializers only read attributes via getattr).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from services.strategy import serializers


def _order(**overrides):
    base = dict(
        id=1, run_id=10, leg_id=100, strategy_id=99,
        action="BUY", symbol="INFY", exchange="NSE",
        orderid="OID1", product="MIS", quantity="50",
        price=1500.5, pricetype="MARKET", order_status="complete",
        trigger_price=0, timestamp="08-May-2026 14:30:30",
        source="entry", mode="live", placed_at=None,
        rms_event_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _trade(**overrides):
    base = dict(
        id=1, order_id=1, run_id=10, leg_id=100, strategy_id=99,
        action="BUY", symbol="INFY", exchange="NSE",
        orderid="OID1", product="MIS",
        quantity=Decimal(50), average_price=Decimal("1500.5"),
        trade_value=Decimal("75025"), timestamp="14:30:30",
        broker_tradeid="TID1", traded_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _position(**overrides):
    base = dict(
        id=1, run_id=10, leg_id=100, strategy_id=99,
        symbol="INFY", exchange="NSE", product="MIS",
        quantity="50", average_price="1500.5", ltp="1505",
        pnl="225",
        net_qty=50, avg_entry=Decimal("1500.5"),
        ltp_decimal=Decimal("1505"),
        unrealized_pnl=Decimal("225"), realized_pnl=Decimal(0),
        current_sl_price=Decimal("1485"),
        current_target_price=Decimal("1525"),
        last_trail_anchor=Decimal("1500.5"),
        trail_advances_count=0,
        peak_favorable_price=None,
        trail_to_entry_armed=False,
        leg_state="OPEN", updated_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _event(**overrides):
    base = dict(
        id=1, strategy_id=99, run_id=10, leg_id=None,
        ts=datetime(2026, 5, 6, 9, 0, 30, tzinfo=timezone.utc),
        type="STATE_CHANGE",
        payload=json.dumps({"old_state": "ARMED", "new_state": "ENTERING"}),
        prev_hash="aa", row_hash="bb",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _run(**overrides):
    base = dict(
        id=10, strategy_id=99, state="IN_TRADE", mode="live",
        signal_payload="{}", signal_source="webhook",
        triggered_at=datetime(2026, 5, 6, 9, 0, 0, tzinfo=timezone.utc),
        entered_at=datetime(2026, 5, 6, 9, 0, 5, tzinfo=timezone.utc),
        exited_at=None, exit_reason=None,
        peak_mtm=Decimal("1500"), trough_mtm=Decimal(0),
        profit_locked=False,
        realized_pnl=Decimal(0), max_unrealized_pnl=Decimal("1500"),
        max_drawdown=Decimal(0),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ----------------------------------------------------------------------------
# orderbook envelope
# ----------------------------------------------------------------------------


def test_orderbook_envelope_matches_global_shape():
    out = serializers.to_orderbook_format([_order()])
    # Top-level matches services.orderbook_service:get_orderbook_with_auth
    assert out["status"] == "success"
    assert "data" in out
    assert "orders" in out["data"]
    assert "statistics" in out["data"]


def test_orderbook_row_has_all_global_fields():
    out = serializers.to_orderbook_format([_order()])
    row = out["data"]["orders"][0]
    # Field names match /orderbook
    for f in ("action", "symbol", "exchange", "orderid", "product",
              "quantity", "price", "pricetype", "order_status",
              "trigger_price", "timestamp"):
        assert f in row, f"missing field {f}"
    # Strategy-only metadata also present
    for f in ("source", "mode", "leg_id", "run_id"):
        assert f in row


def test_orderbook_quantity_is_string_matching_global():
    """Global /orderbook returns quantity as a string. Match it."""
    out = serializers.to_orderbook_format([_order(quantity="50")])
    assert out["data"]["orders"][0]["quantity"] == "50"
    assert isinstance(out["data"]["orders"][0]["quantity"], str)


def test_orderbook_statistics_counts():
    orders = [
        _order(action="BUY", order_status="complete"),
        _order(action="BUY", order_status="open"),
        _order(action="SELL", order_status="rejected"),
        _order(action="SELL", order_status="complete"),
    ]
    stats = serializers.to_orderbook_format(orders)["data"]["statistics"]
    assert stats["total_buy_orders"] == 2
    assert stats["total_sell_orders"] == 2
    assert stats["total_completed_orders"] == 2
    assert stats["total_open_orders"] == 1
    assert stats["total_rejected_orders"] == 1


def test_orderbook_statistics_empty_list():
    stats = serializers.to_orderbook_format([])["data"]["statistics"]
    assert stats == {
        "total_buy_orders": 0.0,
        "total_sell_orders": 0.0,
        "total_completed_orders": 0.0,
        "total_open_orders": 0.0,
        "total_rejected_orders": 0.0,
    }


def test_orderbook_falls_back_to_placed_at_when_timestamp_missing():
    placed_at = datetime(2026, 5, 6, 9, 0, 30, tzinfo=timezone.utc)
    o = _order(timestamp=None, placed_at=placed_at)
    out = serializers.to_orderbook_format([o])
    # 09:00:30 UTC + 05:30 = 14:30:30 IST
    assert out["data"]["orders"][0]["timestamp"] == "06-May-2026 14:30:30"


# ----------------------------------------------------------------------------
# tradebook envelope
# ----------------------------------------------------------------------------


def test_tradebook_envelope_matches_global_shape():
    out = serializers.to_tradebook_format([_trade()])
    assert out["status"] == "success"
    assert isinstance(out["data"], list)


def test_tradebook_row_fields():
    out = serializers.to_tradebook_format([_trade()])
    row = out["data"][0]
    for f in ("action", "symbol", "exchange", "orderid", "product",
              "quantity", "average_price", "trade_value", "timestamp"):
        assert f in row


def test_tradebook_quantity_is_float_matching_global():
    """Global /tradebook returns quantity as a number. Match it."""
    out = serializers.to_tradebook_format([_trade(quantity=Decimal(50))])
    assert out["data"][0]["quantity"] == 50.0
    assert isinstance(out["data"][0]["quantity"], float)


def test_tradebook_falls_back_to_traded_at_when_timestamp_missing():
    traded_at = datetime(2026, 5, 6, 9, 0, 30, tzinfo=timezone.utc)
    t = _trade(timestamp=None, traded_at=traded_at)
    out = serializers.to_tradebook_format([t])
    assert out["data"][0]["timestamp"] == "14:30:30"


# ----------------------------------------------------------------------------
# positionbook envelope
# ----------------------------------------------------------------------------


def test_positionbook_envelope_matches_global_shape():
    out = serializers.to_positionbook_format([_position()])
    assert out["status"] == "success"
    assert isinstance(out["data"], list)


def test_positionbook_string_fields_match_global():
    """Global /positionbook returns these as strings. Match it."""
    out = serializers.to_positionbook_format([_position()])
    row = out["data"][0]
    assert isinstance(row["quantity"], str)
    assert isinstance(row["average_price"], str)
    assert isinstance(row["ltp"], str)
    assert isinstance(row["pnl"], str)


def test_positionbook_decimal_fields_added_for_strategy_use():
    """Strategy-only decimal fields for charts / RMS math."""
    out = serializers.to_positionbook_format([_position()])
    row = out["data"][0]
    assert row["net_qty"] == 50
    assert row["avg_entry"] == 1500.5
    assert row["unrealized_pnl"] == 225.0
    assert row["realized_pnl"] == 0.0


def test_positionbook_rms_state_surface():
    """SL / target / trail-advance count exposed for the monitor view."""
    out = serializers.to_positionbook_format([_position()])
    row = out["data"][0]
    assert row["current_sl_price"] == 1485.0
    assert row["current_target_price"] == 1525.0
    assert row["trail_advances_count"] == 0
    assert row["leg_state"] == "OPEN"


def test_positionbook_handles_none_decimals():
    p = _position(avg_entry=None, ltp_decimal=None,
                  current_sl_price=None, current_target_price=None)
    row = serializers.to_positionbook_format([p])["data"][0]
    assert row["avg_entry"] is None
    assert row["current_sl_price"] is None


# ----------------------------------------------------------------------------
# Events
# ----------------------------------------------------------------------------


def test_event_payload_decoded_to_object():
    out = serializers.to_events_format([_event()])
    row = out["data"][0]
    assert isinstance(row["payload"], dict)
    assert row["payload"]["new_state"] == "ENTERING"


def test_event_handles_corrupt_payload():
    e = _event(payload="not json")
    row = serializers.to_events_format([e])["data"][0]
    assert row["payload"] == "not json"  # surfaced raw, not crashed


def test_event_carries_both_timestamps():
    out = serializers.to_events_format([_event()])
    row = out["data"][0]
    assert "ts_utc" in row and isinstance(row["ts_utc"], int)
    assert "ts_ist" in row and row["ts_ist"] == "06-May-2026 14:30:30"


def test_event_does_not_leak_prev_hash():
    """prev_hash is for the verifier endpoint to walk; row clients don't need it."""
    row = serializers.to_events_format([_event()])["data"][0]
    assert "prev_hash" not in row
    assert "row_hash" in row  # but row_hash is fine — it's the row's own fingerprint


# ----------------------------------------------------------------------------
# Runs
# ----------------------------------------------------------------------------


def test_runs_basic_serialization():
    out = serializers.to_runs_format([_run()])
    row = out["data"][0]
    assert row["id"] == 10
    assert row["state"] == "IN_TRADE"
    assert row["mode"] == "live"
    assert row["peak_mtm"] == 1500.0


def test_runs_timestamps_in_ist():
    out = serializers.to_runs_format([_run()])
    row = out["data"][0]
    # 09:00:00 UTC + 05:30 = 14:30:00 IST
    assert row["triggered_at"] == "06-May-2026 14:30:00"
    assert row["entered_at"] == "06-May-2026 14:30:05"
    assert row["exited_at"] is None  # still in trade


def test_run_detail_envelope():
    out = serializers.run_detail(_run())
    assert out["status"] == "success"
    assert out["data"]["id"] == 10
