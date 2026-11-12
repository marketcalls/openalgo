"""Tradejini never reports a refused order as placed (issue #2385).

The order services treat ``res.status == 200`` as a placed order. Tradejini can
answer a refusal with its error envelope over HTTP 200, and the plugin returned
that 200 unchanged, so the trader saw "Order Placed ... Order ID: None". On an
HTTP error it returned ``None`` as the response object, and the service raised
on ``res.status``. These tests run the real plugin under the real service with
only the HTTP client and the symbol lookups faked.
"""

from unittest.mock import patch

import httpx
import pytest

# Imported first: place_order_service imports restx_api, whose __init__ imports
# options_multiorder_service, which imports place_order_service back.
import restx_api  # noqa: F401, I001
from broker.tradejini.api import order_api
from broker.tradejini.mapping import transform_data as tj_transform
from events import OrderFailedEvent, OrderPlacedEvent

URL = "https://api.tradejini.com/v2/api/oms/place-order"

ORDER = {
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "pricetype": "MARKET",
    "product": "MIS",
    "quantity": "1",
}


class FakeClient:
    """Stands in for the shared httpx client and records what was sent."""

    def __init__(self, answer):
        self.answer = answer
        self.sent = []

    def post(self, url, headers=None, data=None, timeout=None):
        self.sent.append(data)
        if isinstance(self.answer, Exception):
            raise self.answer
        status, body = self.answer
        request = httpx.Request("POST", url)
        if isinstance(body, str):
            return httpx.Response(status, text=body, request=request)
        return httpx.Response(status, json=body, request=request)


@pytest.fixture
def tradejini(monkeypatch):
    """Patch the lookups; return a function that installs a broker answer."""
    monkeypatch.setattr(order_api, "get_token", lambda symbol, exchange: "3045")
    monkeypatch.setattr(order_api, "get_api_key", lambda: "key")
    monkeypatch.setattr(tj_transform, "get_br_symbol", lambda symbol, exchange: "EQT_SBIN_EQ_NSE")

    def answer(reply):
        client = FakeClient(reply)
        monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
        return client

    return answer


def place():
    """Place ORDER through the live service with Tradejini as the broker."""
    from services import place_order_service

    with (
        patch.object(place_order_service, "get_analyze_mode", return_value=False),
        patch.object(place_order_service, "import_broker_module", return_value=order_api),
        patch.object(place_order_service.bus, "publish") as publish,
    ):
        result = place_order_service.place_order_with_auth(
            dict(ORDER), "token", "tradejini", {"apikey": "k", **ORDER}
        )
    events = [call.args[0] for call in publish.call_args_list]
    return result, events


def assert_failed(events):
    assert not any(isinstance(e, OrderPlacedEvent) for e in events)
    assert any(isinstance(e, OrderFailedEvent) for e in events)


def test_placed_order_is_unchanged(tradejini):
    tradejini((200, {"s": "ok", "d": {"msg": "Order Placed Successfully", "orderId": "2101"}}))
    (ok, body, status), events = place()
    assert (ok, body, status) == (True, {"status": "success", "orderid": "2101"}, 200)
    assert [e.orderid for e in events if isinstance(e, OrderPlacedEvent)] == ["2101"]


def test_error_envelope_over_http_200_is_a_refusal(tradejini):
    tradejini((200, {"s": "error", "msg": "RMS: Margin Exceeds"}))
    (ok, body, status), events = place()
    assert ok is False
    assert body == {"status": "error", "message": "RMS: Margin Exceeds"}
    assert status == 400
    assert_failed(events)


def test_http_error_keeps_status_and_message_and_does_not_raise(tradejini):
    tradejini(
        (
            400,
            {
                "s": "error",
                "msg": "Input validation failed. Kindly check your input contains "
                "required fields for the request",
            },
        )
    )
    (ok, body, status), events = place()
    assert ok is False
    assert body["message"].startswith("Input validation failed")
    assert status == 400
    assert_failed(events)


def test_unauthorized_keeps_its_status(tradejini):
    tradejini((401, {"s": "error", "msg": "Unauthorized"}))
    (ok, body, status), _ = place()
    assert (ok, body["message"], status) == (False, "Unauthorized", 401)


def test_http_error_with_unreadable_body_has_no_status_code_in_message(tradejini):
    tradejini((502, "<html>bad gateway</html>"))
    (ok, body, status), _ = place()
    assert (ok, status) == (False, 502)
    assert body["message"] == "Tradejini refused the order"


def test_ok_without_order_id_sends_trader_to_order_book(tradejini):
    tradejini((200, {"s": "ok", "d": {"msg": "Order Placed Successfully"}}))
    (ok, body, status), events = place()
    assert ok is False
    assert body["message"] == order_api.NO_ORDER_ID_MESSAGE
    assert status == 502
    assert_failed(events)


@pytest.mark.parametrize(
    "body",
    [{"s": "ok"}, {"s": "ok", "d": None}, {"s": "ok", "d": "Order Placed"}, {"s": "ok", "d": []}],
    ids=["no-d", "d-null", "d-string", "d-list"],
)
def test_ok_with_unexpected_payload_is_never_a_refusal(tradejini, body):
    # "ok" means the order may exist, whatever shape the payload has.
    tradejini((200, body))
    (ok, resp, status), events = place()
    assert ok is False
    assert resp["message"] == order_api.NO_ORDER_ID_MESSAGE
    assert status == 502
    assert_failed(events)


def test_unreadable_200_sends_trader_to_order_book(tradejini):
    tradejini((200, "not json"))
    (ok, body, status), _ = place()
    assert (ok, body["message"], status) == (False, order_api.NO_ORDER_ID_MESSAGE, 502)


def test_symbol_missing_from_master_contract_is_refused_before_sending(tradejini, monkeypatch):
    client = tradejini((200, {"s": "ok", "d": {"orderId": "should-not-happen"}}))
    monkeypatch.setattr(tj_transform, "get_br_symbol", lambda symbol, exchange: None)
    (ok, body, status), events = place()
    assert ok is False
    assert body["message"] == tj_transform.SYMBOL_NOT_FOUND_MESSAGE
    assert status == 400
    assert client.sent == []
    assert_failed(events)


def test_plugin_never_returns_none_or_200_for_a_failure(tradejini):
    for reply in [
        (200, {"s": "error", "msg": "x"}),
        (200, {"s": "ok", "d": {}}),
        (200, "not json"),
        (200, ["unexpected"]),
        (400, {"s": "error", "msg": "x"}),
        httpx.ConnectError("refused"),
    ]:
        tradejini(reply)
        res, data, order_id = order_api.place_order_api(dict(ORDER), "token")
        assert res is not None, reply
        assert res.status != 200, reply
        assert data["status"] == "error", reply
        assert order_id is None, reply
