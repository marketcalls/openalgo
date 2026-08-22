"""Non-finite numbers must be rejected by the API analyzer.

``float()`` accepts "nan", "inf" and "-inf", and every range check in
``utils.api_analyzer`` is a comparison (``<= 0``, ``< 0``, ``== 0``). All of
those are False for NaN, so before the ``math.isfinite`` guard a NaN quantity
or price passed validation and reached the broker.

Run with: uv run pytest test/test_api_analyzer_numeric_validation.py -v
"""

import pytest

from utils import api_analyzer
from utils.api_analyzer import (
    _finite_float,
    analyze_api_request,
    analyze_modify_order_request,
    analyze_smart_order_request,
)

# Both the string spellings that arrive over JSON and the float objects that
# arrive from a Python client.
NON_FINITE = ["nan", "NaN", "inf", "-inf", "Infinity", float("nan"), float("inf"), float("-inf")]

QUANTITY_ISSUE = "Invalid quantity value"
PRICE_ISSUE = "Invalid numeric value for price, trigger_price, or disclosed_quantity"
# modifyorder validates quantity inside the same try, so its message differs.
MODIFY_NUMERIC_ISSUE = (
    "Invalid numeric value for price, trigger_price, quantity, or disclosed_quantity"
)


@pytest.fixture(autouse=True)
def _known_symbol(monkeypatch):
    """Take symbol lookup out of play so only numeric validation is asserted."""
    monkeypatch.setattr(api_analyzer, "validate_symbol", lambda symbol, exchange: True)


def _order(**overrides):
    """A placeorder payload carrying every REQUIRED_ORDER_FIELDS entry."""
    order = {
        "apikey": "test-key",
        "strategy": "test",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": "1",
        "pricetype": "MARKET",
        "product": "MIS",
    }
    order.update(overrides)
    return order


def _smart_order(**overrides):
    """A smart-order payload; position_size is required on this path."""
    order = _order(position_size="0")
    order.update(overrides)
    return order


def _modify_order(**overrides):
    """A modifyorder payload carrying every REQUIRED_MODIFY_ORDER_FIELDS entry."""
    order = _order(
        orderid="250101000000001",
        pricetype="LIMIT",
        price="100",
        disclosed_quantity="0",
        trigger_price="0",
    )
    order.update(overrides)
    return order


class TestFiniteFloat:
    @pytest.mark.parametrize("value", NON_FINITE)
    def test_rejects_non_finite(self, value):
        with pytest.raises(ValueError):
            _finite_float(value)

    @pytest.mark.parametrize("value", ["0", "-1.5", "1e308", 0, 12345.678])
    def test_accepts_finite(self, value):
        assert _finite_float(value) == float(value)

    def test_message_does_not_echo_the_input(self):
        with pytest.raises(ValueError) as excinfo:
            _finite_float("nan")
        assert "nan" not in str(excinfo.value).lower()


class TestPlaceOrder:
    @pytest.mark.parametrize("value", NON_FINITE)
    def test_quantity_rejected(self, value):
        response = analyze_api_request(_order(quantity=value))
        assert response["status"] == "error"
        assert QUANTITY_ISSUE in response["message"]

    @pytest.mark.parametrize("field", ["price", "trigger_price", "disclosed_quantity"])
    @pytest.mark.parametrize("value", NON_FINITE)
    def test_price_fields_rejected(self, field, value):
        order = _order(pricetype="LIMIT", price="100")
        order[field] = value
        response = analyze_api_request(order)
        assert response["status"] == "error"
        assert PRICE_ISSUE in response["message"]

    def test_finite_order_still_valid(self):
        response = analyze_api_request(_order(pricetype="LIMIT", price="100"))
        assert response["status"] == "success"

    def test_finite_boundaries_unchanged(self):
        assert "Quantity must be greater than 0" in analyze_api_request(_order(quantity="0"))["message"]
        assert "Price cannot be negative" in analyze_api_request(_order(price="-1"))["message"]
        assert "Price is required for LIMIT orders" in analyze_api_request(
            _order(pricetype="LIMIT", price="0")
        )["message"]

    def test_rejection_does_not_echo_the_input(self):
        response = analyze_api_request(_order(quantity="nan"))
        assert "nan" not in response["message"].lower()


class TestSmartOrder:
    @pytest.mark.parametrize("value", NON_FINITE)
    def test_quantity_rejected(self, value):
        response = analyze_smart_order_request(_smart_order(quantity=value))
        assert response["status"] == "error"
        assert QUANTITY_ISSUE in response["message"]

    @pytest.mark.parametrize("value", NON_FINITE)
    def test_position_size_rejected(self, value):
        response = analyze_smart_order_request(_smart_order(position_size=value))
        assert response["status"] == "error"
        assert "Invalid position size value" in response["message"]

    def test_finite_smart_order_still_valid(self):
        response = analyze_smart_order_request(_smart_order(quantity="0"))
        assert response["status"] == "success"


class TestModifyOrder:
    @pytest.mark.parametrize("value", NON_FINITE)
    def test_quantity_rejected(self, value):
        response = analyze_modify_order_request(_modify_order(quantity=value))
        assert response["status"] == "error"
        assert MODIFY_NUMERIC_ISSUE in response["message"]

    @pytest.mark.parametrize("field", ["price", "trigger_price", "disclosed_quantity"])
    @pytest.mark.parametrize("value", NON_FINITE)
    def test_price_fields_rejected(self, field, value):
        order = _modify_order()
        order[field] = value
        response = analyze_modify_order_request(order)
        assert response["status"] == "error"
        assert MODIFY_NUMERIC_ISSUE in response["message"]

    def test_finite_modify_still_valid(self):
        assert analyze_modify_order_request(_modify_order())["status"] == "success"
