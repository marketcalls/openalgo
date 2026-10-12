"""Delta today fills are complete only after explicit native pagination EOF."""

from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytz

from broker.deltaexchange.api import order_api
from services import tradebook_service


def test_incomplete_read_keeps_technical_detail_in_exception_log(monkeypatch, caplog):
    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic internal protocol detail")

    monkeypatch.setattr(order_api, "get_api_response", unavailable)
    result = order_api.get_trade_book("test-auth")
    assert result == {
        "status": "error",
        "message": "Unable to load all Delta trades. Please try again.",
        "data": {},
    }
    failures = [
        record for record in caplog.records if "Incomplete Delta trade book" in record.message
    ]
    assert len(failures) == 1
    assert failures[0].levelname == "ERROR"
    assert failures[0].exc_info[0] is RuntimeError


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


def read_pages(monkeypatch, pages):
    calls = []
    responses = iter(pages)

    def read(endpoint, auth, method="GET", params=None):
        calls.append((endpoint, method, params))
        return deepcopy(next(responses))

    monkeypatch.setattr(order_api, "get_api_response", read)
    return calls


def test_all_fifteen_fills_are_read_across_native_pages(monkeypatch):
    rows = [fill(i) for i in range(1, 16)]
    calls = read_pages(monkeypatch, [page(rows[:10], "opaque+/next"), page(rows[10:])])
    assert order_api.get_trade_book("test-auth") == rows
    assert len(calls) == 2
    assert all(call[0:2] == ("/v2/fills", "GET") for call in calls)
    assert all(call[2]["page_size"] == 50 for call in calls)
    assert calls[1][2]["after"] == "opaque+/next"
    first_window = {key: calls[0][2][key] for key in ("start_time", "end_time")}
    assert first_window == {key: calls[1][2][key] for key in first_window}
    assert first_window["end_time"] - first_window["start_time"] == 86400 * 1000000 - 1
    start = datetime.fromtimestamp(
        first_window["start_time"] / 1000000, pytz.timezone("Asia/Kolkata")
    )
    assert start.hour == start.minute == start.second == start.microsecond == 0


def test_identical_overlap_is_deduplicated_by_native_fill_id(monkeypatch):
    first, second = fill(1), fill(2)
    read_pages(monkeypatch, [page([first], "next"), page([first, second])])
    assert order_api.get_trade_book("test-auth") == [first, second]


@pytest.mark.parametrize(
    "response",
    [
        {"success": False, "error": {"code": "request_error"}},
        {"success": True, "result": []},
        {"success": True, "result": [], "meta": {}},
        {"success": True, "result": "bad", "meta": {"after": None}},
        page([None]),
        page([fill(id=None)]),
        page([fill(created_at="not-a-time")]),
        page([fill(price="NaN")]),
        page([fill(size=0)]),
        page([fill(side="unknown")]),
        page([fill(product_id=None)]),
    ],
)
def test_failed_or_malformed_native_page_is_never_successful_empty_book(monkeypatch, response):
    read_pages(monkeypatch, [response])
    result = order_api.get_trade_book("test-auth")
    assert result["status"] == "error"
    assert result["message"]


@pytest.mark.parametrize(
    "later",
    [
        {"success": False, "error": {"code": "request_error"}},
        page([fill(2)], "next"),
        page([fill(1, price="11.00")]),
        page([], ""),
    ],
)
def test_partial_page_failure_repeated_cursor_or_conflicting_fill_refuses_book(monkeypatch, later):
    read_pages(monkeypatch, [page([fill(1)], "next"), later])
    assert order_api.get_trade_book("test-auth")["status"] == "error"


def test_page_cap_refuses_partial_book(monkeypatch):
    monkeypatch.setattr(order_api, "TRADEBOOK_MAX_PAGES", 1, raising=False)
    read_pages(monkeypatch, [page([fill(1)], "next")])
    assert order_api.get_trade_book("test-auth")["status"] == "error"


def test_row_cap_refuses_partial_book(monkeypatch):
    monkeypatch.setattr(order_api, "TRADEBOOK_MAX_ROWS", 1, raising=False)
    read_pages(monkeypatch, [page([fill(1), fill(2)])])
    assert order_api.get_trade_book("test-auth")["status"] == "error"


def test_today_filter_follows_eof_even_if_an_old_fill_precedes_today(monkeypatch):
    old = fill(1)
    old["created_at"] = (datetime.fromisoformat(old["created_at"]) - timedelta(days=1)).isoformat()
    current = fill(2)
    calls = read_pages(monkeypatch, [page([old], "next"), page([current])])
    assert order_api.get_trade_book("test-auth") == [current]
    assert len(calls) == 2


def test_native_page_failure_fails_closed_through_service(monkeypatch):
    monkeypatch.setattr("database.settings_db.get_analyze_mode", lambda: False)
    read_pages(monkeypatch, [{"success": False, "error": {"code": "request_error"}}])
    success, response, status = tradebook_service.get_tradebook_with_auth(
        "test-auth", "deltaexchange"
    )
    assert not success and status == 500 and response["status"] == "error"


def test_explicit_empty_eof_returns_empty_book(monkeypatch):
    read_pages(monkeypatch, [page([])])
    assert order_api.get_trade_book("test-auth") == []


def test_uuid_fill_and_settlement_order_references_survive_native_read(monkeypatch):
    native = fill(
        "61c27c01-cb33-4aab-a5a3-6b5fc6dd1348", order_id="6f9c5ba8-9410-4943-badc-cf259d36e171"
    )
    read_pages(monkeypatch, [page([native])])
    assert order_api.get_trade_book("test-auth") == [native]


@pytest.mark.parametrize("field", ["id", "order_id"])
@pytest.mark.parametrize("reference", [True, False, [], {}, None, "", "   ", 0, -1, 1.0])
def test_invalid_native_fill_references_refuse_complete_book(monkeypatch, field, reference):
    read_pages(monkeypatch, [page([fill(**{field: reference})])])
    assert order_api.get_trade_book("test-auth")["status"] == "error"


def test_opaque_cursor_is_encoded_identically_in_signature_and_request(monkeypatch):
    client = Mock()
    client.get.return_value = httpx.Response(200, json={"success": True, "result": []})
    sign = Mock(return_value={"test-signature": "synthetic"})
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
    monkeypatch.setattr(order_api, "get_url", lambda path: "https://example.invalid" + path)
    monkeypatch.setattr(order_api, "consume", lambda *args, **kwargs: None)
    monkeypatch.setattr(order_api, "get_auth_headers", sign)
    monkeypatch.setenv("BROKER_API_SECRET", "test-secret")
    cursor = "opaque+/cursor?part=one&two"
    result = order_api.get_api_response("/v2/fills", "test-auth", params={"after": cursor})
    assert result["success"] is True
    query = urlsplit(client.get.call_args.args[0]).query
    assert sign.call_args.kwargs["query_string"] == "?" + query
    assert parse_qs(query) == {"after": [cursor]}
