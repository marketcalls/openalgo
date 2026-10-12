"""Spot base quantities and derivative contract units coexist in Delta tradebooks."""

import json
from copy import deepcopy
from datetime import datetime
from decimal import Decimal

import httpx
import pytest
import pytz

from broker.deltaexchange.api import data, order_api
from broker.deltaexchange.mapping import order_data
from services import tradebook_service


def spot_product(**changes):
    # Native spot products have a base and quote asset; settling_asset is null.
    # https://docs.delta.exchange/#spot-trading
    return {
        "id": 303,
        "symbol": "BTC_INR",
        "contract_type": "spot",
        "underlying_asset": {"symbol": "BTC"},
        "quoting_asset": {"symbol": "INR"},
        **changes,
    }


def option_product():
    return {
        "id": 101,
        "symbol": "P-TEST-100-010130",
        "contract_type": "put_options",
        "contract_value": "0.01",
        "contract_unit_currency": "TEST",
        "notional_type": "vanilla",
        "underlying_asset": {"symbol": "TEST"},
        "quoting_asset": {"symbol": "USD"},
        "settling_asset": {"symbol": "USD"},
    }


def fill(product=None, **changes):
    product = spot_product() if product is None else product
    now = datetime.now(pytz.timezone("Asia/Kolkata")).astimezone(pytz.UTC)
    return {
        "id": "synthetic-spot-fill",
        "order_id": 201,
        "product_id": product["id"],
        "product_symbol": product["symbol"],
        "size": "0.000001",
        "price": "4200000.1234",
        "side": "buy",
        "created_at": now.isoformat(),
        "product": product,
        **changes,
    }


@pytest.fixture
def read_book(monkeypatch):
    monkeypatch.setattr("database.settings_db.get_analyze_mode", lambda: False)
    monkeypatch.setattr(order_data, "get_symbol", lambda *args: None)

    def read(rows, products=None):
        calls = []

        def native(endpoint, auth, method="GET", params=None):
            calls.append((endpoint, method))
            if endpoint == "/v2/fills":
                return {"success": True, "result": deepcopy(rows), "meta": {"after": None}}
            pytest.fail("Native fills are the only authenticated tradebook read")

        def public(path, timeout=15.0, params=None):
            calls.append((path, "GET"))
            symbol = path.rsplit("/", 1)[-1]
            product = next((p for p in (products or {}).values() if p["symbol"] == symbol), None)
            return httpx.Response(
                200, json={"success": product is not None, "result": deepcopy(product)}
            )

        monkeypatch.setattr(order_api, "get_api_response", native)
        monkeypatch.setattr(data, "_public_get", public)
        result = tradebook_service.get_tradebook_with_auth("test-auth", "deltaexchange")
        return result, calls

    return read


@pytest.mark.parametrize(
    "derivative_fields",
    [
        {},
        {
            "contract_value": "1",
            "contract_unit_currency": "BTC",
            "notional_type": "vanilla",
            "settling_asset": None,
        },
        {
            "contract_value": "0.001",
            "contract_unit_currency": "USD",
            "notional_type": "inverse",
            "settling_asset": {"symbol": "USD"},
        },
    ],
)
def test_spot_uses_base_quantity_and_quote_value_without_derivative_assumptions(
    read_book, derivative_fields
):
    (success, response, code), _ = read_book([fill(spot_product(**derivative_fields))])
    assert success and code == 200
    (row,) = response["data"]
    assert row["symbol"] == "BTC_INR"
    assert row["product"] == "CNC"
    assert Decimal(str(row["quantity"])) == Decimal("0.000001")
    assert row["fill_quantity"] == "0.000001"
    assert row["fill_price"] == "4200000.1234"
    assert row["contract_value"] == "1"
    assert row["trade_value"] == 4.2
    assert row["trade_value_currency"] == "INR"
    assert row["fillid"] == "synthetic-spot-fill"


def test_mixed_spot_and_options_remain_a_successful_complete_book(read_book):
    spot = fill()
    option = fill(
        option_product(),
        id="synthetic-option-fill",
        order_id=202,
        size="20",
        price="10.125",
        side="sell",
    )
    (success, response, code), calls = read_book([spot, option])
    assert success and code == 200 and calls == [("/v2/fills", "GET")]
    spot_row, option_row = response["data"]
    assert (spot_row["product"], spot_row["trade_value_currency"], spot_row["trade_value"]) == (
        "CNC",
        "INR",
        4.2,
    )
    assert (
        option_row["product"],
        option_row["trade_value_currency"],
        option_row["trade_value"],
    ) == ("NRML", "USD", 2.02)
    assert spot_row["quantity"] == 0.000001
    assert option_row["quantity"] == 20
    assert option_row["fill_price"] == "10.125"
    assert len({row["fillid"] for row in response["data"]}) == 2


def test_omitted_spot_product_metadata_is_resolved_once_for_mixed_book(read_book):
    first = fill(product=None)
    first["product"] = None
    second = fill(id="second-spot-fill", size="0.000002", side="sell", product=None)
    second["product"] = None
    option = fill(option_product(), id="option-fill", size="1", price="10")
    (success, response, code), calls = read_book(
        [first, option, second], products={"303": spot_product()}
    )
    assert success and code == 200 and len(response["data"]) == 3
    assert calls == [("/v2/fills", "GET"), ("/v2/products/BTC_INR", "GET")]
    assert [row["product"] for row in response["data"]] == ["CNC", "NRML", "CNC"]


@pytest.mark.parametrize("size", ["0.000001", "0.0001234567890123456789"])
def test_fractional_spot_size_survives_json_and_display_formatting(read_book, size):
    (success, response, code), _ = read_book([fill(size=size)])
    assert success and code == 200
    (row,) = json.loads(json.dumps(response, allow_nan=False))["data"]
    assert isinstance(row["quantity"], (int, float)) and row["quantity"] > 0
    assert abs(Decimal(str(row["quantity"])) - Decimal(size)) < Decimal("1e-19")
    assert row["fill_quantity"] == size


def test_explicit_zero_price_spot_fill_keeps_quantity_and_zero_value(read_book):
    (success, response, code), _ = read_book([fill(price="0")])
    assert success and code == 200
    (row,) = response["data"]
    assert row["quantity"] == 0.000001 and row["fill_quantity"] == "0.000001"
    assert row["average_price"] == row["trade_value"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"size": "0"},
        {"size": "-0.01"},
        {"size": "NaN"},
        {"size": "Infinity"},
        {"size": None},
        {"size": True},
        {"price": "-1"},
        {"price": "NaN"},
        {"price": "Infinity"},
        {"price": None},
        {"price": False},
        {"side": "unknown"},
    ],
)
def test_invalid_spot_execution_facts_refuse_successful_mixed_book(read_book, changes):
    option = fill(option_product(), id="valid-option-fill", size="1", price="10")
    (success, response, code), _ = read_book([option, fill(**changes)])
    assert not success and code == 500 and response["status"] == "error"


@pytest.mark.parametrize(
    "metadata",
    [
        {"underlying_asset": None},
        {"quoting_asset": None},
        {"underlying_asset": {"symbol": ""}},
        {"quoting_asset": {"symbol": ""}},
        {"underlying_asset": {"symbol": 123}},
        {"quoting_asset": {"symbol": ["INR"]}},
        {"id": 999},
        {"symbol": "OTHER_INR"},
    ],
)
def test_invalid_spot_product_facts_refuse_successful_mixed_book(read_book, metadata):
    spot = fill()
    spot["product"] = spot_product(**metadata)
    (success, response, code), _ = read_book([spot])
    assert not success and code == 500 and response["status"] == "error"


@pytest.mark.parametrize(
    "metadata",
    [{"underlying_asset": {"symbol": "ETH"}}, {"quoting_asset": {"symbol": "USD"}}],
)
def test_conflicting_base_or_quote_currency_for_one_spot_product_refuses_book(read_book, metadata):
    first = fill()
    second = fill(spot_product(**metadata), id="second-spot-fill")
    (success, response, code), _ = read_book([first, second])
    assert not success and code == 500 and response["status"] == "error"
