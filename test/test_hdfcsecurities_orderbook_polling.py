"""HDFC Securities order book, as the order-update poller reads it.

HDFC Securities is in services/order_update_service.py::_POLLING_BROKERS, so
its order updates come from diffing the normalized order book on
(order_status, filled_quantity). These tests pin what that needs: the fill
fields in the transformed rows.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.hdfcsecurities.mapping import order_data as hs_order_data  # noqa: E402

# -- HDFC Securities --------------------------------------------------------

HS_ROW = {
    "order_id": "250101000000001",
    "symbol": "SBIN",
    "exchange": "NSE",
    "transaction_type": "BUY",
    "quantity": 15,
    "price": 800.0,
    "trigger_price": 0.0,
    "order_type": "LIMIT",
    "product": "CNC",
    "status": "OPEN",
    "filled_quantity": 5,
    "pending_quantity": 10,
    "average_price": 799.5,
    "status_message": "",
    "order_timestamp": "2025-01-01 10:00:00",
}


def _hs(**overrides):
    return hs_order_data.transform_order_data([{**HS_ROW, **overrides}])[0]


def test_hs_rows_carry_fill_progress():
    row = _hs()
    assert row["filled_quantity"] == 5
    assert row["pending_quantity"] == 10
    assert row["average_price"] == 799.5
    assert row["rejection_reason"] == ""


def test_hs_rejection_reason_comes_from_status_message():
    rejected_status = next(
        raw
        for raw in ("REJECTED", "Rejected", "rejected")
        if hs_order_data.map_order_status(raw) == "rejected"
    )
    row = _hs(status=rejected_status, status_message="RMS: insufficient funds")
    assert row["order_status"] == "rejected"
    assert row["rejection_reason"] == "RMS: insufficient funds"
    assert _hs(status_message="something")["rejection_reason"] == ""
