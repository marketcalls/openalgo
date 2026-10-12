"""Delta fill premiums use authoritative native contract units and currencies."""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytz

from broker.deltaexchange.api import order_api
from broker.deltaexchange.mapping import order_data
from services import tradebook_service


def product(**overrides):
    return {
        "id": 101,
        "symbol": "P-ETH-2500-121026",
        "contract_type": "put_options",
        "contract_value": "0.01",
        "contract_unit_currency": "ETH",
        "notional_type": "vanilla",
        "underlying_asset": {"id": 2, "symbol": "ETH"},
        "quoting_asset": {"id": 14, "symbol": "USD"},
        "settling_asset": {"id": 14, "symbol": "USD"},
        **overrides,
    }


def fill(fill_id=1, **overrides):
    today = datetime.now(pytz.timezone("Asia/Kolkata")).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    return {
        "id": fill_id,
        "product_id": 101,
        "product_symbol": "P-ETH-2500-121026",
        "order_id": 201,
        "size": 1,
        "price": "10.30",
        "side": "buy",
        "created_at": today.astimezone(pytz.UTC).isoformat(),
        **overrides,
        "product": overrides.get("product", product()),
    }


def page(rows, after=None):
    return {"success": True, "result": rows, "meta": {"after": after}}


@pytest.fixture
def symbols(monkeypatch):
    reads = []

    def symbol(token, exchange):
        reads.append((token, exchange))
        return "ETH12OCT262500PE"

    monkeypatch.setattr(order_data, "get_symbol", symbol)
    # A legacy master defaults missing contract values to 1. It must not win
    # over authoritative native product facts.
    monkeypatch.setattr(order_data, "get_symbol_info", lambda *a: SimpleNamespace(contract_value=1))
    return reads


def read_pages(monkeypatch, pages):
    calls = []
    responses = iter(pages)

    def read(endpoint, auth, method="GET", params=None):
        calls.append((endpoint, method, params))
        return deepcopy(next(responses))

    monkeypatch.setattr(order_api, "get_api_response", read)
    return calls


@pytest.mark.parametrize(
    "quantity,price,multiplier,expected",
    [
        (276, "184.00", 0.001, Decimal("50.784")),
        (500, "10.0507", 0.01, Decimal("50.2535")),
    ],
)
def test_contract_multiplier_values_premium_and_preserves_fill_identity(
    monkeypatch, symbols, quantity, price, multiplier, expected
):
    (row,) = order_data.transform_tradebook_data(
        order_data.map_trade_data(
            [fill(size=quantity, price=price, product=product(contract_value=str(multiplier)))]
        )
    )
    assert Decimal(str(row["trade_value"])) == expected
    assert row["fillid"] == "1"
    assert row["fill_price"] == price
    assert Decimal(row["contract_value"]) == Decimal(str(multiplier))
    assert row["trade_value_currency"] == "USD"


def test_symbol_contract_metadata_is_memoized_per_mapping_call(symbols):
    mapped = order_data.map_trade_data([fill(1), fill(2)])
    assert len(symbols) == 1
    assert len(order_data.transform_tradebook_data(mapped)) == 2


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        product(contract_value=None),
        product(contract_value="NaN"),
        product(contract_value=0),
        product(contract_type="spreads"),
        product(id=999),
        product(notional_type="inverse"),
        product(notional_type="quanto"),
        product(contract_unit_currency="USD"),
        product(settling_asset={"symbol": "INR"}),
    ],
)
def test_unknown_or_invalid_contract_metadata_fails_closed_through_service(
    monkeypatch, symbols, metadata
):
    monkeypatch.setattr("database.settings_db.get_analyze_mode", lambda: False)
    read_pages(monkeypatch, [page([fill(product=metadata)])])
    success, response, status = tradebook_service.get_tradebook_with_auth(
        "test-auth", "deltaexchange"
    )
    assert not success and status == 500
    assert response["status"] == "error"


def test_service_keeps_native_precision_alongside_display_price(monkeypatch, symbols):
    monkeypatch.setattr("database.settings_db.get_analyze_mode", lambda: False)
    read_pages(monkeypatch, [page([fill(price="7.21482")])])
    success, response, status = tradebook_service.get_tradebook_with_auth(
        "test-auth", "deltaexchange"
    )
    assert success and status == 200
    (row,) = response["data"]
    assert row["average_price"] == 7.21
    assert row["fill_price"] == "7.21482"


def test_expired_product_uses_native_symbol_when_missing_from_master(monkeypatch):
    monkeypatch.setattr(order_data, "get_symbol", lambda *a: None)
    (row,) = order_data.transform_tradebook_data(order_data.map_trade_data([fill()]))
    assert row["symbol"] == product()["symbol"]
    assert row["trade_value"] == 0.103


def test_native_underlying_notional_is_not_option_premium_value(symbols):
    (row,) = order_data.transform_tradebook_data(
        order_data.map_trade_data([fill(size=171, price="7.01", notional="4396.8033")])
    )
    assert row["trade_value"] == 11.9871


def test_conflicting_native_product_metadata_refuses_all_fills(symbols):
    with pytest.raises(ValueError, match="conflicting native product identity"):
        order_data.map_trade_data([fill(1), fill(2, product=product(contract_value="0.02"))])


@pytest.mark.parametrize("field", ["id", "order_id"])
@pytest.mark.parametrize("reference", [True, False, [], {}, None, "", "   ", 0, -1, 1.0])
def test_invalid_native_references_are_not_mapped_as_fills(symbols, field, reference):
    with pytest.raises(ValueError, match="without native identity"):
        order_data.map_trade_data([fill(**{field: reference})])


def test_uuid_native_references_survive_premium_mapping(symbols):
    native = fill(
        "61c27c01-cb33-4aab-a5a3-6b5fc6dd1348", order_id="6f9c5ba8-9410-4943-badc-cf259d36e171"
    )
    (row,) = order_data.transform_tradebook_data(order_data.map_trade_data([native]))
    assert row["fillid"] == native["id"]
    assert row["orderid"] == "101:" + native["order_id"]


def test_missing_embedded_product_is_resolved_once_from_native_product_route(monkeypatch):
    rows = [fill(1, product=None), fill(2, product=None)]
    calls = read_pages(monkeypatch, [page(rows), {"success": True, "result": product()}])
    result = order_api.get_trade_book("test-auth")
    assert len(result) == 2
    assert all(row["product"] == product() for row in result)
    assert calls[-1] == ("/v2/products/101", "GET", None)
    assert len(calls) == 2


@pytest.mark.parametrize(
    "response",
    [
        {"success": False, "error": {"code": "request_error"}},
        {"success": True, "result": []},
    ],
)
def test_missing_product_and_failed_native_lookup_refuses_book(monkeypatch, response):
    read_pages(monkeypatch, [page([fill(product=None)]), response])
    assert order_api.get_trade_book("test-auth")["status"] == "error"


def test_native_product_lookup_is_bounded(monkeypatch):
    monkeypatch.setattr(order_api, "TRADEBOOK_MAX_PRODUCTS", 0)
    calls = read_pages(monkeypatch, [page([fill(product=None)])])
    assert order_api.get_trade_book("test-auth")["status"] == "error"
    assert len(calls) == 1
