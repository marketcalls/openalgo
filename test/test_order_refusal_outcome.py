"""A broker refusal is never reported as a placed order (issue #2385).

Some plugins answer a refusal with a status-200 response object and
``{"status": "error"}`` (Tradejini's error envelope arrives over HTTP 200), and
some return ``None`` as the response object when the request failed.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Imported first: place_order_service imports restx_api, whose __init__ imports
# options_multiorder_service, which imports place_order_service back.
import restx_api  # noqa: F401, I001
from events import OrderFailedEvent, OrderPlacedEvent
from services.order_outcome import NO_ORDER_ID_MESSAGE, place_order_outcome

ORDER = {
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "pricetype": "MARKET",
    "product": "MIS",
    "quantity": "1",
}

OK = SimpleNamespace(status=200)


def broker_answering(res, response_data, order_id):
    return SimpleNamespace(place_order_api=lambda data, auth: (res, response_data, order_id))


def place(broker):
    from services import place_order_service

    with (
        patch.object(place_order_service, "get_analyze_mode", return_value=False),
        patch.object(place_order_service, "import_broker_module", return_value=broker),
        patch.object(place_order_service.bus, "publish") as publish,
    ):
        result = place_order_service.place_order_with_auth(
            dict(ORDER), "token", "fakebroker", {"apikey": "k", **ORDER}
        )
    events = [call.args[0] for call in publish.call_args_list]
    return result, events


class TestPlaceOrderOutcome:
    def test_200_with_order_id_is_placed(self):
        assert place_order_outcome(OK, {"status": "success"}, "123") == (True, None, 200)

    def test_200_error_envelope_is_refused_with_broker_message(self):
        outcome = place_order_outcome(OK, {"status": "error", "message": "RMS: margin"}, None)
        assert outcome == (False, "RMS: margin", 500)

    def test_none_response_object_is_refused(self):
        outcome = place_order_outcome(None, {"status": "error", "message": "HTTP 400"}, None)
        assert outcome == (False, "HTTP 400", 500)

    def test_http_error_status_is_kept(self):
        res = SimpleNamespace(status=400)
        outcome = place_order_outcome(res, {"status": "error", "message": "bad qty"}, None)
        assert outcome == (False, "bad qty", 400)

    def test_missing_message_falls_back(self):
        assert place_order_outcome(None, None, None) == (False, "Failed to place order", 500)

    @pytest.mark.parametrize(
        "response_data",
        [
            {"s": "error", "message": "RMS: margin"},
            {"stat": "Not_Ok", "message": "RMS: margin"},
            {"status": "failed", "message": "RMS: margin"},
        ],
        ids=["fyers", "noren", "failed"],
    )
    def test_other_refusal_envelopes_carry_the_broker_message(self, response_data):
        assert place_order_outcome(OK, response_data, None) == (False, "RMS: margin", 500)

    def test_error_envelope_with_an_order_id_is_refused(self):
        # Fyers returns the id of an order its risk checks rejected.
        outcome = place_order_outcome(
            OK, {"s": "error", "message": "RMS: margin", "id": "26110700001"}, "26110700001"
        )
        assert outcome == (False, "RMS: margin", 500)

    def test_emsg_is_read_when_there_is_no_message(self):
        outcome = place_order_outcome(
            OK, {"stat": "Not_Ok", "emsg": "Invalid Trading Symbol"}, None
        )
        assert outcome == (False, "Invalid Trading Symbol", 500)

    def test_accepted_without_order_id_says_check_order_book(self):
        outcome = place_order_outcome(OK, {"status": "success"}, None)
        assert outcome == (False, NO_ORDER_ID_MESSAGE, 502)


class TestPlaceOrderService:
    def test_refusal_over_200_is_not_reported_as_placed(self):
        (ok, body, status), events = place(
            broker_answering(OK, {"status": "error", "message": "Invalid symbol"}, None)
        )
        assert ok is False
        assert body == {"status": "error", "message": "Invalid symbol"}
        assert status == 500
        assert not any(isinstance(e, OrderPlacedEvent) for e in events)
        assert any(isinstance(e, OrderFailedEvent) for e in events)

    def test_none_response_object_does_not_raise(self):
        (ok, body, status), events = place(
            broker_answering(None, {"status": "error", "message": "HTTP 503"}, None)
        )
        assert (ok, body, status) == (False, {"status": "error", "message": "HTTP 503"}, 500)
        assert any(isinstance(e, OrderFailedEvent) for e in events)

    def test_accepted_without_order_id(self):
        (ok, body, status), events = place(broker_answering(OK, {"status": "success"}, None))
        assert ok is False
        assert body["message"] == NO_ORDER_ID_MESSAGE
        assert status == 502
        assert not any(isinstance(e, OrderPlacedEvent) for e in events)

    def test_placed_order_is_unchanged(self):
        (ok, body, status), events = place(broker_answering(OK, {"status": "success"}, "42"))
        assert (ok, body, status) == (True, {"status": "success", "orderid": "42"}, 200)
        assert [e.orderid for e in events if isinstance(e, OrderPlacedEvent)] == ["42"]


@pytest.mark.parametrize(
    "res, response_data, expected",
    [
        (OK, {"status": "error", "message": "Invalid symbol"}, "Invalid symbol"),
        (None, {"status": "error", "message": "HTTP 503"}, "HTTP 503"),
        (OK, {"status": "success"}, NO_ORDER_ID_MESSAGE),
    ],
)
def test_basket_and_split_legs_report_the_refusal(res, response_data, expected):
    from services import basket_order_service, split_order_service

    broker = broker_answering(res, response_data, None)

    leg = basket_order_service.place_single_order(dict(ORDER), broker, "token", 1, 0)
    assert leg["status"] == "error"
    assert leg["message"] == expected

    leg = split_order_service.place_single_order(dict(ORDER), broker, "token", 1, 1)
    assert leg["status"] == "error"
    assert leg["message"] == expected


def test_tradejini_refuses_a_symbol_missing_from_the_master_contract():
    from broker.tradejini.mapping import transform_data as td

    with patch.object(td, "get_br_symbol", return_value=None):
        with pytest.raises(td.SymbolNotFoundError, match="Download the master contract"):
            td.transform_data(dict(ORDER), "token")
