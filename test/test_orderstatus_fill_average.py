"""Executed order fallback VWAP uses every matching fill and confirmed quantity."""

from copy import deepcopy
from decimal import Decimal

import pytest

from services import orderbook_service, orderstatus_service


@pytest.fixture
def status(monkeypatch):
    monkeypatch.setattr(orderstatus_service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(orderstatus_service.log_executor, "submit", lambda *a, **k: None)

    def run(order, trades, broker="deltaexchange", trade_success=True):
        monkeypatch.setattr(
            orderbook_service,
            "get_orderbook",
            lambda **kwargs: (
                True,
                {"status": "success", "data": {"orders": [deepcopy(order)]}},
                200,
            ),
        )
        monkeypatch.setattr(
            orderstatus_service,
            "get_tradebook",
            lambda **kwargs: (
                trade_success,
                {"status": "success" if trade_success else "error", "data": trades},
                200 if trade_success else 500,
            ),
        )
        success, response, code = orderstatus_service.get_order_status_with_auth(
            {"orderid": order["orderid"]}, "test-auth", broker, {}
        )
        assert success and code == 200
        return response["data"]

    return run


def order(**kwargs):
    return {
        "orderid": "101:201",
        "quantity": 101,
        "order_status": "complete",
        "client_order_id": None,
        **kwargs,
    }


def test_weighted_partial_fills_use_quantities_and_preserved_native_price(status):
    rows = [
        {"orderid": "101:201", "quantity": 1, "average_price": 10.3, "fill_price": "10.30"},
        {"orderid": "101:201", "quantity": 100, "average_price": 10.2, "fill_price": "10.20001"},
        {"orderid": "another-order", "quantity": 500, "average_price": 500},
    ]
    result = status(order(), rows)
    expected = (Decimal("10.30") + 100 * Decimal("10.20001")) / 101
    assert float(result["average_price"]) == pytest.approx(float(expected), rel=1e-12)


def test_normal_indian_broker_uses_weighted_trade_prices(status):
    rows = [
        {"orderid": "12345", "quantity": 10, "average_price": 100},
        {"orderid": "12345", "quantity": 20, "average_price": 110},
    ]
    result = status(order(orderid="12345", quantity=30), rows, broker="zerodha")
    assert float(result["average_price"]) == pytest.approx(3200 / 30)


def test_native_average_without_complete_quantity_is_not_accepted(status):
    rows = [
        {"orderid": "101:201", "quantity": 101, "average_price": 10.2, "fill_price": "10.20001"}
    ]
    result = status(order(average_price="10.0507", filled_quantity="1"), rows)
    assert Decimal(str(result["average_price"])) == Decimal("10.20001")


def test_partial_delta_fills_do_not_certify_complete_order_average(status):
    rows = [{"orderid": "101:201", "quantity": 1, "average_price": 10.3, "fill_price": "10.30"}]
    assert status(order(), rows)["average_price"] == 0.0


@pytest.mark.parametrize("quantity,price", [(0, 10), (-1, 10), (1, "NaN"), (1, "bad")])
def test_invalid_matching_fill_is_not_a_price_fact(status, quantity, price):
    rows = [{"orderid": "101:201", "quantity": quantity, "average_price": price}]
    assert status(order(), rows)["average_price"] == 0.0
