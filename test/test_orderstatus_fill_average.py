"""Executed order fallback VWAP uses every matching fill and confirmed quantity."""

from copy import deepcopy
from decimal import Decimal

import pytest

from broker.deltaexchange.mapping import order_data
from services import orderbook_service, orderstatus_service, tradebook_service


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


@pytest.fixture
def mapped_fills(monkeypatch):
    """Use the production Delta producer and display formatting for native rows."""
    monkeypatch.setattr(order_data, "get_symbol", lambda *args: None)

    def run(quantities, prices, spot=True):
        product = {
            "id": 101,
            "symbol": "ETH_INR" if spot else "P-TEST-100-010130",
            "contract_type": "spot" if spot else "put_options",
            "underlying_asset": {"symbol": "TEST"},
            "quoting_asset": {"symbol": "INR" if spot else "USD"},
            "settling_asset": None if spot else {"symbol": "USD"},
            "contract_value": "0.01",
            "contract_unit_currency": "TEST",
            "notional_type": "vanilla",
        }
        raw = [
            {
                "id": index + 1,
                "product_id": 101,
                "product_symbol": product["symbol"],
                "product": deepcopy(product),
                "order_id": 201,
                "size": quantity,
                "price": price,
                "side": "buy",
                "created_at": "2026-10-12T07:00:00Z",
            }
            for index, (quantity, price) in enumerate(zip(quantities, prices, strict=True))
        ]
        mapped = order_data.map_trade_data(raw)
        return tradebook_service.format_trade_data(order_data.transform_tradebook_data(mapped))

    return run


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


def test_delta_exact_fractional_quantity_certifies_full_order_coverage(status, mapped_fills):
    native_quantity = "0.100000000000000001"
    rows = mapped_fills([native_quantity], ["10.30"])
    assert rows[0]["fill_quantity"] == native_quantity
    result = status(order(quantity=native_quantity), rows)
    assert result["average_price"] == 10.3


def test_delta_exact_fractional_fills_produce_weighted_average(status, mapped_fills):
    quantities = ("0.123456789012345678", "0.876543210987654322")
    prices = ("10.30", "11.20001")
    rows = mapped_fills(quantities, prices)
    assert [row["fill_quantity"] for row in rows] == list(quantities)
    assert [row["fill_price"] for row in rows] == list(prices)
    assert rows[1]["average_price"] == 11.2
    result = status(order(quantity="1"), rows)
    expected = sum(Decimal(q) * Decimal(p) for q, p in zip(quantities, prices, strict=True))
    assert result["average_price"] == pytest.approx(float(expected), rel=1e-12)


def test_native_price_precision_survives_real_tradebook_formatting(status, mapped_fills):
    rows = mapped_fills(["1", "100"], ["10.30", "10.20001"], spot=False)
    assert rows[1]["average_price"] == 10.2
    assert rows[1]["fill_price"] == "10.20001"
    result = status(order(), rows)
    expected = (Decimal("10.30") + 100 * Decimal("10.20001")) / 101
    assert result["average_price"] == pytest.approx(float(expected), rel=1e-12)


@pytest.mark.parametrize("native_quantity", [None, "NaN", "invalid", "0", "-1"])
def test_invalid_preserved_delta_quantity_cannot_fall_back_to_display_quantity(
    status, native_quantity
):
    rows = [
        {
            "orderid": "101:201",
            "quantity": 101,
            "fill_quantity": native_quantity,
            "fill_price": "10.30",
            "average_price": 10.3,
        }
    ]
    assert status(order(), rows)["average_price"] == 0.0


def test_other_broker_weights_its_quantity_without_using_delta_native_field(status):
    rows = [
        {"orderid": "12345", "quantity": 10, "fill_quantity": "999", "average_price": 100},
        {"orderid": "12345", "quantity": 20, "fill_quantity": "1", "average_price": 110},
    ]
    result = status(order(orderid="12345", quantity=30), rows, broker="zerodha")
    assert result["average_price"] == pytest.approx(3200 / 30)


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
