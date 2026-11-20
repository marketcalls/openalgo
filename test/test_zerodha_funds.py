"""Kite funds must work with a trading-only token and fail closed on missing cash."""

import httpx
import pytest

from broker.zerodha.api import funds

MARGINS = {
    "equity": {"net": 125, "available": {"collateral": 20}, "utilised": {"debits": 7}},
    "commodity": {"net": 0, "available": {"collateral": 0}, "utilised": {"debits": 0}},
}
CLOSED = {"quantity": 0, "buy_value": 240, "sell_value": 265}
SHORT = {"quantity": -2, "last_price": 107, "average_price": 110, "multiplier": 10, "pnl": 60}


def read(monkeypatch, replies):
    paths = []

    def handle(request):
        paths.append(request.url.path)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, data = reply
        return httpx.Response(
            status, json={"status": "success" if status == 200 else "error", "data": data}
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(funds, "get_httpx_client", lambda: client)
        result = funds.get_margin_data("test:token")
    assert not replies
    return result, paths


def test_personal_token_values_positions_without_a_quote(monkeypatch):
    result, paths = read(monkeypatch, [(200, MARGINS), (200, {"net": [CLOSED, SHORT]})])
    assert paths == ["/user/margins", "/portfolio/positions"]
    assert result == {
        "availablecash": "112.00",
        "collateral": "20.00",
        "m2munrealized": "60.00",
        "m2mrealized": "25.00",
        "utiliseddebits": "7.00",
    }


@pytest.mark.parametrize("status", [502, 503, 504])
def test_transient_margin_response_retried_once(monkeypatch, status):
    result, paths = read(monkeypatch, [(status, {}), (200, MARGINS), (200, {"net": []})])
    assert paths == ["/user/margins", "/user/margins", "/portfolio/positions"]
    assert result["m2munrealized"] == result["m2mrealized"] == "0.00"


@pytest.mark.parametrize("replies", [[(403, {})], [(429, {})], [(504, {}), (504, {})], [(200, {})]])
def test_no_account_balance_on_terminal_failure(monkeypatch, replies):
    result, paths = read(monkeypatch, replies)
    assert result == {}
    assert set(paths) == {"/user/margins"}


@pytest.mark.parametrize(
    "reply",
    [
        (403, {}),
        (200, {}),
        (200, {"net": [SHORT, {"quantity": 0}]}),
        (200, {"net": [{**SHORT, "last_price": 0}]}),
        (200, {"net": [{**SHORT, "average_price": None}]}),
        (200, {"net": [{**SHORT, "last_price": "nan"}]}),
        (200, {"net": [{**SHORT, "multiplier": 0}]}),
    ],
)
def test_unavailable_position_book_or_mark_preserves_cash(monkeypatch, reply):
    result, paths = read(monkeypatch, [(200, MARGINS), reply])
    assert paths == ["/user/margins", "/portfolio/positions"]
    assert result["availablecash"] == "112.00"
    assert result["m2munrealized"] is None
    assert result["m2mrealized"] is None


def test_funds_api_does_not_report_empty_kite_balance_as_success(monkeypatch):
    from database import settings_db
    from services import funds_service

    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(funds_service, "import_broker_module", lambda name: funds)
    monkeypatch.setattr(funds, "get_margin_data", lambda token: {})
    ok, body, status = funds_service.get_funds_with_auth("test:token", "zerodha")
    assert not ok and body["status"] == "error" and status == 502


def test_telegram_displays_unavailable_without_fabricating_zero():
    from services.telegram_bot_service import TelegramBotService

    result = TelegramBotService._format_pnl_funds(
        None, {"status": "success", "data": {"m2mrealized": None, "m2munrealized": None}}
    )
    assert result == "Position P&L unavailable"


def test_partially_closed_position_preserves_booked_component(monkeypatch):
    partial = {"quantity": -65, "last_price": 91.40, "average_price": 48.10, "pnl": -8992.75}
    result, _ = read(monkeypatch, [(200, MARGINS), (200, {"net": [partial]})])
    assert result["m2munrealized"] == "-2814.50"
    assert result["m2mrealized"] == "-6178.25"


def test_missing_total_does_not_manufacture_booked_pnl(monkeypatch):
    result, _ = read(monkeypatch, [(200, MARGINS), (200, {"net": [{**SHORT, "pnl": None}]})])
    assert result["m2munrealized"] == "60.00"
    assert result["m2mrealized"] is None


def test_margin_timeout_gets_one_retry_within_budget(monkeypatch):
    result, paths = read(
        monkeypatch, [httpx.ReadTimeout("timeout"), (200, MARGINS), (200, {"net": []})]
    )
    assert paths == ["/user/margins", "/user/margins", "/portfolio/positions"]
    assert result["availablecash"] == "112.00"


def test_elapsed_budget_prevents_a_second_margin_request(monkeypatch):
    values = iter([150.0, 150.0, 153.0])
    from types import SimpleNamespace

    monkeypatch.setattr(funds, "time", SimpleNamespace(monotonic=lambda: next(values)))
    result, paths = read(monkeypatch, [httpx.ReadTimeout("timeout")])
    assert paths == ["/user/margins"]
    assert result == {}


def test_transport_cannot_add_an_extra_attempt(monkeypatch):
    from utils.httpx_client import _BrokerTransport

    attempts = []

    def fail(transport, request):
        attempts.append(request.url.path)
        raise httpx.ConnectError("network unavailable", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fail)
    with httpx.Client(transport=_BrokerTransport()) as client:
        monkeypatch.setattr(funds, "get_httpx_client", lambda: client)
        assert funds.get_margin_data("test:token") == {}
    assert attempts == ["/user/margins", "/user/margins"]
