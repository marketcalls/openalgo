"""Non-finite numbers must be rejected by the API analyzer.

``float()`` accepts "nan", "inf" and "-inf", and every range check in
``utils.api_analyzer`` is a comparison (``<= 0``, ``< 0``, ``== 0``). All of
those are False for NaN, so before the ``math.isfinite`` guard a NaN quantity
or price was reported as ``status: success``.

This covers legacy code rather than a reachable path. The ``analyze_*``
functions have no callers outside their own module, and live orders are
rejected one layer earlier by the marshmallow schemas in
``restx_api/schemas.py``, whose ``fields.Float`` defaults to
``allow_nan=False``. The tests pin the guard so the module stays correct for as
long as it is kept.

Run with: uv run pytest test/test_api_analyzer_numeric_validation.py -v
"""

import pytest
from sqlalchemy.exc import OperationalError

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


class _StubColumn:
    """Stand-in for a SQLAlchemy column, so the filter criteria build harmlessly."""

    def __ge__(self, other):
        return True

    def like(self, pattern):
        return True


class _StubQuery:
    def __init__(self, count):
        self._count = count

    def filter(self, *args, **kwargs):
        return self

    def count(self):
        return self._count


def _stub_analyzer_log(count=0):
    """An ``AnalyzerLog`` stand-in whose rate-limit probe reports ``count`` rows."""

    class _StubAnalyzerLog:
        query = _StubQuery(count)
        created_at = _StubColumn()
        response_data = _StubColumn()

    return _StubAnalyzerLog


@pytest.fixture(autouse=True)
def _known_symbol(monkeypatch):
    """Take symbol lookup out of play so only numeric validation is asserted."""
    monkeypatch.setattr(api_analyzer, "validate_symbol", lambda symbol, exchange: True)


@pytest.fixture(autouse=True)
def _quiet_rate_limits(monkeypatch):
    """Stub the rate-limit query so the DB-failure branch stays out of the way.

    ``analyzer_logs`` does not exist in the test database, so every unstubbed
    call raises ``OperationalError``, which the analyzer swallows into
    ``warnings: ["Unable to check rate limits"]`` after logging a traceback.
    That buried the branch under noise and left it unasserted; it is pinned
    explicitly by ``test_rate_limit_probe_failure_is_reported`` below.
    """
    monkeypatch.setattr(api_analyzer, "AnalyzerLog", _stub_analyzer_log())


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
        assert (
            "Quantity must be greater than 0"
            in analyze_api_request(_order(quantity="0"))["message"]
        )
        assert "Price cannot be negative" in analyze_api_request(_order(price="-1"))["message"]
        assert (
            "Price is required for LIMIT orders"
            in analyze_api_request(_order(pricetype="LIMIT", price="0"))["message"]
        )

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


class TestHelperContract:
    """The helper's stated contract: one exception type for every bad number."""

    @pytest.mark.parametrize("value", ["nan", "inf", "-inf", float("nan"), float("inf")])
    def test_non_finite_raises_value_error(self, value):
        with pytest.raises(ValueError):
            _finite_float(value)

    def test_oversized_int_raises_value_error_not_overflow_error(self):
        """``float(10**400)`` raises OverflowError, which the callers do not catch.

        Left unconverted it escapes the per-field ``except ValueError`` handlers
        and collapses the whole analysis into "Internal error analyzing request".
        """
        with pytest.raises(ValueError):
            _finite_float(10**400)

    @pytest.mark.parametrize("value", ["1.5", 1.5, 0, "0"])
    def test_finite_values_pass_through(self, value):
        assert _finite_float(value) == float(value)

    def test_oversized_int_is_reported_as_a_field_issue(self):
        """The OverflowError path must surface as a normal validation issue."""
        response = analyze_api_request(_order(quantity=10**400))
        assert response["status"] == "error"
        assert QUANTITY_ISSUE in response["message"]


class TestRateLimitProbe:
    def test_no_warning_when_probe_succeeds(self):
        assert analyze_api_request(_order())["warnings"] == []

    def test_rate_limit_probe_failure_is_reported(self, monkeypatch):
        """A failing probe degrades to a warning rather than failing the analysis."""

        class _BrokenQuery:
            def filter(self, *args, **kwargs):
                raise OperationalError("no such table: analyzer_logs", {}, None)

            def count(self):
                raise OperationalError("no such table: analyzer_logs", {}, None)

        class _BrokenAnalyzerLog:
            query = _BrokenQuery()
            created_at = _StubColumn()
            response_data = _StubColumn()

        monkeypatch.setattr(api_analyzer, "AnalyzerLog", _BrokenAnalyzerLog)
        response = analyze_api_request(_order())
        assert response["status"] == "success"
        assert response["warnings"] == ["Unable to check rate limits"]

    def test_high_frequency_warning_when_probe_reports_a_burst(self, monkeypatch):
        monkeypatch.setattr(api_analyzer, "AnalyzerLog", _stub_analyzer_log(count=51))
        response = analyze_api_request(_order())
        assert (
            "High request frequency detected. Consider reducing request rate."
            in (response["warnings"])
        )
