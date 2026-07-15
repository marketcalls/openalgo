"""
Tests for services.order_event_normalizer.

Covers normalization of broker-agnostic order/trade/position dicts (the
shape already produced by every broker's mapping/order_data.py) into the
WebSocket event payloads used by the order_update/trade_update/
position_update channels.
"""

import pytest

from services.order_event_normalizer import (
    ORDER_UPDATE,
    POSITION_UPDATE,
    TRADE_UPDATE,
    build_trade_id,
    normalize_order_event,
    normalize_position_event,
    normalize_trade_event,
)


class TestNormalizeOrderEvent:
    def test_maps_all_broker_normalized_fields(self):
        order = {
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 10,
            "price": 825.5,
            "trigger_price": 0.0,
            "pricetype": "LIMIT",
            "product": "MIS",
            "orderid": "250714000012345",
            "order_status": "open",
            "timestamp": "2026-07-14 09:16:23",
        }

        event = normalize_order_event(order, generation=1, sequence=0)

        assert event["event_type"] == ORDER_UPDATE
        assert event["generation"] == 1
        assert event["sequence"] == 0
        assert event["orderid"] == "250714000012345"
        assert event["symbol"] == "SBIN"
        assert event["exchange"] == "NSE"
        assert event["action"] == "BUY"
        assert event["product"] == "MIS"
        assert event["pricetype"] == "LIMIT"
        assert event["quantity"] == 10
        assert event["price"] == 825.5
        assert event["status"] == "open"
        assert event["timestamp"] == "2026-07-14 09:16:23"

    def test_defaults_missing_fields_instead_of_raising(self):
        event = normalize_order_event({}, generation=1, sequence=0)

        assert event["orderid"] == ""
        assert event["quantity"] == 0
        assert event["status"] == ""

    def test_carries_rejection_reason_when_present(self):
        order = {
            "orderid": "1",
            "order_status": "rejected",
            "rejection_reason": "RMS:Insufficient margin",
        }

        event = normalize_order_event(order, generation=2, sequence=1)

        assert event["status"] == "rejected"
        assert event["rejection_reason"] == "RMS:Insufficient margin"


class TestNormalizeTradeEvent:
    def test_maps_fill_fields(self):
        trade = {
            "symbol": "SBIN",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": 10,
            "average_price": 825.5,
            "trade_value": 8255.0,
            "orderid": "250714000012345",
            "timestamp": "2026-07-14 09:16:24",
        }

        event = normalize_trade_event(trade, generation=1, sequence=1)

        assert event["event_type"] == TRADE_UPDATE
        assert event["orderid"] == "250714000012345"
        assert event["fill_quantity"] == 10
        assert event["fill_price"] == 825.5
        assert event["trade_value"] == 8255.0
        assert event["tradeid"] == build_trade_id(trade)

    def test_trade_id_is_stable_for_identical_trade(self):
        trade = {
            "orderid": "1",
            "quantity": 5,
            "average_price": 100.0,
            "timestamp": "2026-07-14 09:16:24",
        }

        assert build_trade_id(trade) == build_trade_id(trade)

    def test_trade_id_differs_for_different_fills_on_same_order(self):
        # Partial fills on the same order at different prices/quantities
        # must be distinguishable, since orderid alone is not unique per fill.
        first_fill = {"orderid": "1", "quantity": 5, "average_price": 100.0, "timestamp": "t1"}
        second_fill = {"orderid": "1", "quantity": 3, "average_price": 100.5, "timestamp": "t2"}

        assert build_trade_id(first_fill) != build_trade_id(second_fill)


class TestNormalizePositionEvent:
    def test_maps_net_position_fields(self):
        position = {
            "symbol": "SBIN",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 10,
            "pnl": 125.5,
            "average_price": 825.5,
            "ltp": 838.0,
        }

        event = normalize_position_event(position, generation=3, sequence=0)

        assert event["event_type"] == POSITION_UPDATE
        assert event["net_quantity"] == 10
        assert event["average_price"] == 825.5
        assert event["ltp"] == 838.0
        assert event["pnl"] == 125.5

    def test_defaults_missing_fields_instead_of_raising(self):
        event = normalize_position_event({}, generation=1, sequence=0)

        assert event["net_quantity"] == 0
        assert event["pnl"] == 0.0
