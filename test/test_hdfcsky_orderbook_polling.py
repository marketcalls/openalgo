"""HDFC Sky order book, as the order-update poller reads it.

HDFC Sky is in services/order_update_service.py::_POLLING_BROKERS, so
its order updates come from diffing the normalized order book on
(order_status, filled_quantity). These tests pin what that needs: the fill
fields in the transformed rows, and an error rather than half a
book when one of its two order-book calls fails.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.hdfcsky.api import order_api as sky_order_api  # noqa: E402
from broker.hdfcsky.mapping import order_data as sky_order_data  # noqa: E402

# -- HDFC Sky ---------------------------------------------------------------

SKY_ROW = {
    "trading_symbol": "PNB-EQ",
    "exchange": "NSE",
    "oms_order_id": "200018000000003",
    "order_side": "BUY",
    "quantity": 10,
    "price": 27.8,
    "trigger_price": 0,
    "order_type": "LIMIT",
    "product": "MIS",
    "order_status": "CONFIRMED",
    "filled_quantity": 4,
    "remaining_quantity": 6,
    "average_price": 27.75,
    "rejection_reason": "NONE",
    "order_entry_time": 1605682535,
}


def _sky(**overrides):
    return sky_order_data.transform_order_data([{**SKY_ROW, **overrides}])[0]


def test_sky_rows_carry_fill_progress():
    row = _sky()
    assert row["filled_quantity"] == 4
    assert row["pending_quantity"] == 6
    assert row["average_price"] == 27.75
    assert row["rejection_reason"] == ""


def test_sky_reads_avg_price_when_average_price_is_absent():
    row = dict(SKY_ROW)
    del row["average_price"]
    row["avg_price"] = 27.5
    assert sky_order_data.transform_order_data([row])[0]["average_price"] == 27.5


def test_sky_rejection_reason_only_on_rejected_rows():
    assert _sky(order_status="REJECTED", rejection_reason="Margin Shortfall")[
        "rejection_reason"
    ] == ("Margin Shortfall")
    assert _sky(order_status="REJECTED", rejection_reason="NONE")["rejection_reason"] == ""
    assert _sky(rejection_reason="Margin Shortfall")["rejection_reason"] == ""


def _half(rows):
    return {"status": "success", "message": "", "data": {"orders": rows}}


def test_sky_merges_both_halves():
    pending, completed = _half([{"oms_order_id": "1"}]), _half([{"oms_order_id": "2"}])
    with patch.object(sky_order_api, "_request", side_effect=[pending, completed]):
        book = sky_order_api.get_order_book("tok")
    assert book["status"] == "success"
    assert [o["oms_order_id"] for o in book["data"]["orders"]] == ["1", "2"]


def test_sky_empty_halves_are_a_valid_empty_book():
    with patch.object(sky_order_api, "_request", side_effect=[_half([]), _half([])]):
        book = sky_order_api.get_order_book("tok")
    assert book == {"status": "success", "data": {"orders": []}}


@pytest.mark.parametrize(
    "failed",
    [
        {"status": "error", "message": "Request forbidden", "error_code": 40000, "data": {}},
        {"error": "invalid credentials"},  # what an expired session answers
        RuntimeError("connection reset"),
    ],
)
@pytest.mark.parametrize("failing_half", [0, 1])
def test_sky_one_failed_half_fails_the_whole_book(failed, failing_half):
    answers = [_half([{"oms_order_id": "1"}]), _half([{"oms_order_id": "2"}])]
    answers[failing_half] = failed
    with patch.object(sky_order_api, "_request", side_effect=answers):
        book = sky_order_api.get_order_book("tok")
    assert book["status"] == "error"
    assert "data" not in book
