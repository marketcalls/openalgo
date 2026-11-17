"""An order sent but never answered must not be reported as failed (#2067, #2293).

On Windows a read on the shared HTTP/2 connection can fail with
``httpx.ReadError: [WinError 10035]`` after the broker accepted the order.
Dhan, Flattrade, Shoonya, 5paisa and Zerodha let that error escape, so the
service answered "Failed to place order due to internal error"; Fyers, Upstox,
AliceBlue and Groww caught it and returned an error. Either way the caller
placed the order again and the position doubled.
"""

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

# Imported first: place_order_service imports restx_api, whose __init__ imports
# options_multiorder_service, which imports place_order_service back.
import restx_api  # noqa: F401, I001
from utils import httpx_client
from utils.httpx_client import (
    UNANSWERED_ORDER_MESSAGE,
    _BrokerTransport,
    watch_for_unanswered_writes,
)

WIN_10035 = "[WinError 10035] A non-blocking socket operation could not be completed immediately"


class FakeNetwork:
    """Stands in for the pooled connection under _BrokerTransport."""

    def __init__(self, failures):
        self.failures = list(failures)
        self.sent = []

    def handle_request(self, request):
        self.sent.append(request.method)
        if self.failures:
            raise self.failures.pop(0)(WIN_10035, request=request)
        return httpx.Response(200, json={"status": "success", "orderid": "1"})


@pytest.fixture
def network(monkeypatch):
    def install(*failures):
        fake = FakeNetwork(failures)
        monkeypatch.setattr(
            httpx.HTTPTransport,
            "handle_request",
            lambda self, request: fake.handle_request(request),
        )
        return fake

    return install


@pytest.fixture
def client():
    with httpx.Client(transport=_BrokerTransport()) as c:
        yield c


# --- transport ----------------------------------------------------------------


@pytest.mark.parametrize("error", [httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError])
def test_a_broken_read_is_sent_again_once(network, client, error):
    fake = network(error)
    assert client.get("https://broker.example/orders").status_code == 200
    assert fake.sent == ["GET", "GET"]


def test_a_read_that_breaks_twice_still_raises(network, client):
    fake = network(httpx.ReadError, httpx.ReadError)
    with pytest.raises(httpx.ReadError):
        client.get("https://broker.example/orders")
    assert fake.sent == ["GET", "GET"]


def test_a_read_timeout_is_not_retried(network, client):
    fake = network(httpx.ReadTimeout)
    with pytest.raises(httpx.ReadTimeout):
        client.get("https://broker.example/orders")
    assert fake.sent == ["GET"]


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
@pytest.mark.parametrize("error", [httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError])
def test_a_write_is_never_resent_and_is_recorded(network, client, method, error):
    fake = network(error)
    with watch_for_unanswered_writes() as unanswered:
        with pytest.raises(error):
            client.request(method, "https://broker.example/orders")
    assert fake.sent == [method]
    assert unanswered == [f"{method} broker.example"]


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_a_write_that_never_left_is_not_recorded(network, client, error):
    network(error)
    with watch_for_unanswered_writes() as unanswered:
        with pytest.raises(error):
            client.post("https://broker.example/orders")
    assert unanswered == []


def test_nothing_is_recorded_outside_a_watch(network, client):
    network(httpx.ReadError)
    with pytest.raises(httpx.ReadError):
        client.post("https://broker.example/orders")
    with watch_for_unanswered_writes() as unanswered:
        pass
    assert unanswered == []


def test_the_shared_client_uses_the_transport():
    client = httpx_client._create_http_client()
    try:
        assert isinstance(client._transport, _BrokerTransport)
        # get_pool_stats reads the pool through the transport; keep it reachable.
        assert client._transport._pool is not None
    finally:
        client.close()


# --- service ------------------------------------------------------------------

ORDER = {
    "symbol": "CRUDEOIL18NOV265800PE",
    "exchange": "MCX",
    "action": "SELL",
    "pricetype": "MARKET",
    "product": "NRML",
    "quantity": "100",
}


def _post_order(client):
    response = client.post("https://broker.example/orders", data={"side": "SELL"})
    response.status = response.status_code  # as every broker module does
    return response


def broker_that_raises(client):
    """Dhan, Flattrade, Shoonya, 5paisa, Zerodha: the error escapes."""

    def place_order_api(data, auth):
        response = _post_order(client)
        return response, response.json(), "1"

    return SimpleNamespace(place_order_api=place_order_api)


def broker_that_catches(client):
    """Fyers, Upstox, AliceBlue, Groww: the error becomes an error response."""

    def place_order_api(data, auth):
        try:
            response = _post_order(client)
        except httpx.HTTPError as e:
            return (
                SimpleNamespace(status=500),
                {"status": "error", "message": f"HTTP error: {e}"},
                None,
            )
        return response, response.json(), "1"

    return SimpleNamespace(place_order_api=place_order_api)


@pytest.fixture
def place(client):
    from services import place_order_service

    def run(make_broker):
        with (
            patch.object(place_order_service, "get_analyze_mode", return_value=False),
            patch.object(
                place_order_service, "import_broker_module", return_value=make_broker(client)
            ),
            patch.object(place_order_service.bus, "publish"),
        ):
            return place_order_service.place_order_with_auth(
                dict(ORDER), "token", "fakebroker", {"apikey": "k", **ORDER}
            )

    return run


@pytest.mark.parametrize("make_broker", [broker_that_raises, broker_that_catches])
def test_an_unanswered_order_says_it_may_have_been_placed(network, place, make_broker):
    fake = network(httpx.ReadError)
    ok, body, status = place(make_broker)

    assert ok is False
    assert body == {"status": "error", "message": UNANSWERED_ORDER_MESSAGE}
    assert status == 502
    assert fake.sent == ["POST"], "the order must never be sent twice"


@pytest.mark.parametrize("make_broker", [broker_that_raises, broker_that_catches])
def test_an_order_that_never_left_still_fails_plainly(network, place, make_broker):
    network(httpx.ConnectError)
    ok, body, status = place(make_broker)

    assert ok is False
    assert body["message"] != UNANSWERED_ORDER_MESSAGE
    assert status == 500


def test_an_answered_order_is_untouched(network, place):
    network()
    assert place(broker_that_raises) == (True, {"status": "success", "orderid": "1"}, 200)


@pytest.mark.parametrize("make_broker", [broker_that_raises, broker_that_catches])
def test_basket_and_split_legs_say_it_too(network, client, make_broker):
    from services import basket_order_service, split_order_service

    broker = make_broker(client)
    network(httpx.ReadError)
    leg = basket_order_service.place_single_order(dict(ORDER), broker, "token", 1, 0)
    assert leg["message"] == UNANSWERED_ORDER_MESSAGE

    network(httpx.ReadError)
    leg = split_order_service.place_single_order(dict(ORDER), broker, "token", 1, 1)
    assert leg["message"] == UNANSWERED_ORDER_MESSAGE


@pytest.mark.parametrize("make_broker", [broker_that_raises, broker_that_catches])
def test_a_smart_order_says_it_too(network, client, make_broker):
    from services import place_smart_order_service as svc

    plain = make_broker(client).place_order_api
    broker = SimpleNamespace(place_smartorder_api=plain)
    network(httpx.ReadError)
    with (
        patch.object(svc, "get_analyze_mode", return_value=False),
        patch.object(svc, "import_broker_module", return_value=broker),
        patch.object(svc.bus, "publish"),
    ):
        ok, body, status = svc.place_smart_order_with_auth(
            {**ORDER, "apikey": "k", "strategy": "s", "position_size": "0"},
            "token",
            "fakebroker",
            {"apikey": "k", **ORDER},
        )
    assert (ok, body["message"], status) == (False, UNANSWERED_ORDER_MESSAGE, 502)
