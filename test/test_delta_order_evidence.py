"""Delta's final order projection retains native identity and precise fill facts."""

from decimal import Decimal

import pytest

from broker.deltaexchange.mapping import order_data
from services.orderbook_service import format_order_data


def native_order(**changes):
    return {
        "id": 1234,
        "product_id": 7,
        "product_symbol": "P-TEST-100-010130",
        "client_order_id": "synthetic-client-reference",
        "side": "sell",
        "size": 250,
        "unfilled_size": 0,
        "average_fill_price": "7.12345",
        "state": "closed",
        "order_type": "market_order",
        "limit_price": None,
        "created_at": "2030-01-01T10:00:00.123456Z",
        **changes,
    }


@pytest.fixture(autouse=True)
def no_symbol_database(monkeypatch):
    monkeypatch.setattr(order_data, "get_symbol", lambda *args: None)


def project(native):
    mapped = order_data.map_order_data([native])
    projected = order_data.transform_order_data(mapped)
    (row,) = format_order_data(projected)
    return row


def test_complete_market_order_preserves_native_identity_and_precise_fill_facts():
    row = project(native_order())

    assert row["client_order_id"] == "synthetic-client-reference"
    assert row["orderid"] == "7:1234"
    assert row["order_status"] == "complete"
    assert row["quantity"] == 250
    assert row["price"] == 0
    assert Decimal(row["filled_quantity"]) == Decimal("250")
    assert row["average_price"] == "7.12345"


def test_partial_order_preserves_actual_filled_quantity():
    row = project(native_order(size=250, unfilled_size=175, state="open"))

    assert row["quantity"] == 250
    assert row["order_status"] == "open"
    assert Decimal(row["filled_quantity"]) == Decimal("75")
    assert row["average_price"] == "7.12345"


def test_fractional_native_fill_facts_survive_numeric_display_formatting():
    row = project(native_order(size="0.125", unfilled_size="0.100", state="open"))

    assert Decimal(str(row["quantity"])) == Decimal("0.125")
    assert Decimal(row["filled_quantity"]) == Decimal("0.025")
    assert row["average_price"] == "7.12345"


@pytest.mark.parametrize("average", [0, "0", "0.00000"])
@pytest.mark.parametrize("unfilled,state", [(250, "open"), (0, "closed")])
def test_zero_native_average_is_not_execution_price_evidence(average, unfilled, state):
    row = project(native_order(average_fill_price=average, unfilled_size=unfilled, state=state))

    assert Decimal(row["filled_quantity"]) == Decimal(250 - unfilled)
    assert "average_price" not in row
    assert row["client_order_id"] == "synthetic-client-reference"


def test_native_client_reference_survives_direct_projection():
    (row,) = order_data.transform_order_data(native_order())
    assert row["client_order_id"] == "synthetic-client-reference"


@pytest.mark.parametrize("reference", [None, ""])
def test_absent_native_client_reference_is_not_invented(reference):
    assert project(native_order(client_order_id=reference))["client_order_id"] == reference


@pytest.mark.parametrize(
    "changes",
    [
        {"unfilled_size": None, "average_fill_price": None},
        {"unfilled_size": "NaN", "average_fill_price": "Infinity"},
        {"unfilled_size": 251, "average_fill_price": -1},
        {"size": -1, "unfilled_size": 0, "average_fill_price": "NaN"},
    ],
)
def test_invalid_native_fill_facts_are_not_invented(changes):
    row = project(native_order(**changes))
    assert "filled_quantity" not in row
    assert "average_price" not in row


def test_missing_native_fill_facts_preserve_existing_order_fields():
    native = native_order()
    for field in ("size", "unfilled_size", "average_fill_price"):
        native.pop(field)
    row = project(native)

    assert row["client_order_id"] == "synthetic-client-reference"
    assert row["orderid"] == "7:1234"
    assert "filled_quantity" not in row
    assert "average_price" not in row
