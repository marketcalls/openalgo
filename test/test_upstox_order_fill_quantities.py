"""Preserve broker-reported cumulative fills in live Upstox order responses."""

import copy
from unittest.mock import Mock

import pytest

from broker.upstox.mapping import order_data

FILL_CASES = [
    pytest.param("open", {"filled_quantity": 0, "pending_quantity": 65}, id="unfilled"),
    pytest.param("open", {"filled_quantity": 25, "pending_quantity": 40}, id="partial"),
    pytest.param("complete", {"filled_quantity": 65, "pending_quantity": 0}, id="complete"),
    pytest.param("cancelled", {"filled_quantity": 25, "pending_quantity": 40}, id="cancelled"),
    pytest.param("rejected", {"filled_quantity": 0, "pending_quantity": 65}, id="rejected"),
    pytest.param("cancelled", {}, id="missing"),
    pytest.param("open", {"filled_quantity": None, "pending_quantity": None}, id="null"),
    pytest.param("open", {"filled_quantity": 25}, id="pending-unavailable"),
    pytest.param("open", {"pending_quantity": 40}, id="filled-unavailable"),
    pytest.param("complete", {}, id="complete-missing"),
    pytest.param(
        "complete", {"filled_quantity": None, "pending_quantity": None}, id="complete-null"
    ),
    pytest.param(
        "open", {"filled_quantity": 0, "pending_quantity": None}, id="zero-fill-null-pending"
    ),
    pytest.param(
        "open", {"filled_quantity": None, "pending_quantity": 0}, id="null-fill-zero-pending"
    ),
]


def _order(status, quantities):
    return {
        "order_id": "offline-test-order",
        "instrument_token": "NSE_EQ|TEST",
        "tradingsymbol": "SYNTHETIC",
        "exchange": "NSE",
        "transaction_type": "BUY",
        "quantity": 65,
        "price": 101.25,
        "trigger_price": 0.0,
        "order_type": "LIMIT",
        "product": "I",
        "status": status,
        "order_timestamp": "2026-10-30 10:00:00",
        **quantities,
    }


@pytest.mark.parametrize("status,quantities", FILL_CASES)
@pytest.mark.parametrize("single_order", [False, True], ids=["list", "dict"])
def test_mapper_preserves_reported_quantities(status, quantities, single_order):
    raw = _order(status, quantities)
    original = copy.deepcopy(raw)

    [mapped] = order_data.transform_order_data(raw if single_order else [raw])

    for field in ("filled_quantity", "pending_quantity"):
        if quantities.get(field) is None:
            assert field not in mapped
        else:
            assert mapped[field] == quantities[field]
    assert mapped["quantity"] == 65
    assert mapped["orderid"] == raw["order_id"]
    assert mapped["symbol"] == raw["tradingsymbol"]
    assert mapped["order_status"] == status
    assert mapped["price"] == raw["price"]
    assert raw == original


@pytest.mark.parametrize("status,quantities", FILL_CASES)
def test_live_orderbook_and_status_keep_same_fill_totals(monkeypatch, status, quantities):
    from broker.upstox.api import order_api
    from database import settings_db
    from services import orderbook_service, orderstatus_service

    raw = _order(status, quantities)
    fetch = Mock(side_effect=lambda token: {"status": "success", "data": [copy.deepcopy(raw)]})
    monkeypatch.setattr(order_api, "get_order_book", fetch)
    monkeypatch.setattr(order_data, "get_symbol", lambda token, exchange: "SYNTHETIC")
    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(orderstatus_service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(orderstatus_service.log_executor, "submit", Mock())
    # A lagging tradebook must not erase cumulative quantities from the orderbook.
    monkeypatch.setattr(
        orderstatus_service,
        "get_tradebook",
        Mock(return_value=(True, {"status": "success", "data": []}, 200)),
    )

    success, book, code = orderbook_service.get_orderbook(auth_token="test", broker="upstox")
    assert success and code == 200
    [book_order] = book["data"]["orders"]

    success, response, code = orderstatus_service.get_order_status(
        {"orderid": raw["order_id"]}, auth_token="test", broker="upstox"
    )
    assert success and code == 200
    for field in ("filled_quantity", "pending_quantity"):
        if quantities.get(field) is None:
            assert field not in book_order
            assert field not in response["data"]
        else:
            assert book_order[field] == quantities[field]
            assert response["data"][field] == quantities[field]
    assert fetch.call_count == 2


@pytest.mark.parametrize("endpoint", ["orderbook", "orderstatus"])
def test_analyzer_requests_still_use_sandbox(monkeypatch, endpoint):
    from database import settings_db
    from services import orderbook_service, orderstatus_service, sandbox_service

    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: True)
    monkeypatch.setattr(orderstatus_service, "get_analyze_mode", lambda: True)
    monkeypatch.setattr(
        orderbook_service,
        "import_broker_module",
        Mock(side_effect=AssertionError("Analyzer request reached the live broker")),
    )
    row = {"orderid": "sandbox-order", "filled_quantity": 25, "pending_quantity": 40}
    expected = (True, {"status": "success", "mode": "analyze", "data": row}, 200)
    sandbox = Mock(return_value=expected)
    monkeypatch.setattr(sandbox_service, "sandbox_get_orderbook", sandbox)
    monkeypatch.setattr(sandbox_service, "sandbox_get_order_status", sandbox)
    authenticate = Mock(return_value=("test", "upstox"))
    monkeypatch.setattr(orderbook_service, "get_auth_token_broker", authenticate)
    monkeypatch.setattr(orderstatus_service, "get_auth_token_broker", authenticate)

    if endpoint == "orderbook":
        result = orderbook_service.get_orderbook(api_key="test-api-key")
        sandbox.assert_called_once_with("test-api-key", {"apikey": "test-api-key"})
    else:
        result = orderstatus_service.get_order_status(
            {"orderid": row["orderid"]}, api_key="test-api-key"
        )
        sandbox.assert_called_once_with(
            {"orderid": row["orderid"], "apikey": "test-api-key"},
            "test-api-key",
            {"orderid": row["orderid"], "apikey": "test-api-key"},
        )
    assert result == expected
