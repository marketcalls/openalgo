"""Fyers orderbook: filled/pending quantity must survive normalization.

Fyers API v3 "Get Orders" returns orderBook[].filledQty ("filled qty after
partial trades") and remainingQuantity. The normalized order must carry these
as filled_quantity / pending_quantity, because
websocket_proxy/order_adapter.py::PollingOrderUpdateAdapter keys order-change
detection on (order_status, filled_quantity); a missing field reads 0 and hides
partial fills. Mirrors the flattrade/samco mappers. No network.
"""
from broker.fyers.mapping import order_data


def _order(**kw):
    base = {"symbol": "NSE:SBIN-EQ", "exchange": "NSE", "side": 1, "type": 2,
            "productType": "INTRADAY", "qty": 100, "limitPrice": 0.0,
            "stopPrice": 0.0, "id": "25103000012345", "orderDateTime": "30-Oct-2026 10:00:00"}
    base.update(kw)
    return base


def test_partial_fill_surfaces_filled_and_pending():
    out = order_data.transform_order_data([_order(status=6, filledQty=40, remainingQuantity=60)])[0]
    assert out["filled_quantity"] == 40
    assert out["pending_quantity"] == 60


def test_cancelled_after_partial_still_shows_filled():
    out = order_data.transform_order_data([_order(status=1, filledQty=40, remainingQuantity=60)])[0]
    assert out["order_status"] == "cancelled"
    assert out["filled_quantity"] == 40


def test_missing_fill_field_defaults_to_zero_not_crash():
    out = order_data.transform_order_data([_order(status=6)])[0]
    assert out["filled_quantity"] == 0
    assert out["pending_quantity"] == 0
