"""Broker findings from the gthread review (brokers-01 to brokers-05).

Every case here is about a refusal the gthread worker makes and eventlet never
does: the pacer or the feed gate saying "too long to wait", raised as
BrokerBusyError. Each must reach the trader as that refusal, never as success,
a flat position or a generic failure. The eventlet worker and the development
server never raise it, which the last cases pin.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from utils import runtime
from utils.broker_backpressure import BrokerBusyError, busy_response

GTHREAD = {"worker_class": "gthread", "threads": 64, "workers": 1, "graceful_timeout": 30}


@pytest.fixture
def gthread(monkeypatch):
    monkeypatch.setattr(runtime, "_registered", dict(GTHREAD, pid=os.getpid()))
    assert runtime.gthread_active()


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setattr(runtime, "_registered", None)
    assert not runtime.gthread_active()


class Reply:
    def __init__(self, status_code, body, headers=None):
        self.status_code = status_code
        self.status = status_code
        self._body = body
        self.headers = headers or {}
        self.text = str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("GET", "https://example.invalid")
            raise httpx.HTTPStatusError("error", request=request, response=self)


# ---------------------------------------------------------------------------
# brokers-01: a refused order book read is not a successful cancel-all
# ---------------------------------------------------------------------------


def test_upstox_cancel_all_refused_book_read_is_a_429_not_success(gthread, monkeypatch):
    import broker.upstox.api.order_api as upstox
    import services.cancel_all_order_service as svc

    def refuse(category):
        raise BrokerBusyError()

    monkeypatch.setattr(upstox, "apply_rate_limit", refuse)
    monkeypatch.setattr(svc, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(svc.bus, "publish", lambda event: None)

    ok, response, status = svc.cancel_all_orders_with_auth(
        {"apikey": "x"}, "tok", "upstox", {"apikey": "x"}
    )

    assert (ok, status) == (False, 429), response
    assert response["status"] == "error"
    assert "Canceled 0 orders" not in response.get("message", "")


# ---------------------------------------------------------------------------
# brokers-02: a square-off the pacer refused is not reported as done
# ---------------------------------------------------------------------------


def test_upstox_close_all_reports_refused_legs(gthread, monkeypatch):
    import broker.upstox.api.order_api as upstox

    monkeypatch.setattr(
        upstox,
        "get_positions",
        lambda auth: {
            "status": "success",
            "data": [
                {"quantity": "50", "instrument_token": "t1", "exchange": "NFO", "product": "D"},
                {"quantity": "-75", "instrument_token": "t2", "exchange": "NFO", "product": "D"},
            ],
        },
    )
    monkeypatch.setattr(upstox, "get_symbol", lambda token, exchange: f"SYM{token}")
    monkeypatch.setattr(upstox, "reverse_map_product_type", lambda exchange, product: "NRML")
    sent = []

    def place(payload, auth):
        sent.append(payload["symbol"])
        return busy_response()

    monkeypatch.setattr(upstox, "place_order_api", place)

    response, status = upstox.close_all_positions("x", "tok")

    assert sent == ["SYMt1", "SYMt2"]
    assert status == 429
    assert response["status"] == "error"
    assert response["message"].startswith("2 of 2 open positions were not squared off")


def test_upstox_close_all_refused_positions_read_carries_the_busy_sentence(gthread, monkeypatch):
    import broker.upstox.api.order_api as upstox
    import services.close_position_service as cps

    def refuse(auth):
        raise BrokerBusyError()

    monkeypatch.setattr(upstox, "get_positions", refuse)
    monkeypatch.setattr(cps, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(cps.bus, "publish", lambda event: None)

    ok, response, status = cps.close_position_with_auth(
        {"apikey": "x"}, "tok", "upstox", {"apikey": "x"}
    )

    assert (ok, status) == (False, 429), response


def test_upstox_close_all_unchanged_when_every_leg_is_sent(dev, monkeypatch):
    import broker.upstox.api.order_api as upstox

    monkeypatch.setattr(
        upstox,
        "get_positions",
        lambda auth: {
            "status": "success",
            "data": [
                {"quantity": "50", "instrument_token": "t1", "exchange": "NFO", "product": "D"}
            ],
        },
    )
    monkeypatch.setattr(upstox, "get_symbol", lambda token, exchange: "SYM")
    monkeypatch.setattr(upstox, "reverse_map_product_type", lambda exchange, product: "NRML")
    monkeypatch.setattr(
        upstox,
        "place_order_api",
        lambda payload, auth: (Reply(200, {}), {"status": "success"}, "1"),
    )

    assert upstox.close_all_positions("x", "tok") == (
        {"status": "success", "message": "All Open Positions SquaredOff"},
        200,
    )


def test_indmoney_close_all_reports_refused_legs(gthread, monkeypatch):
    import broker.indmoney.api.order_api as indmoney

    monkeypatch.setattr(
        indmoney,
        "get_positions",
        lambda auth, include_ltp=True: [
            {"net_qty": 50, "security_id": "1", "query_product": "margin"},
        ],
    )
    monkeypatch.setattr(indmoney, "_position_exchange", lambda position: "NFO")
    monkeypatch.setattr(indmoney, "get_symbol", lambda token, exchange: "SYM")
    monkeypatch.setattr(indmoney, "map_product_to_openalgo", lambda product, exchange: "NRML")
    monkeypatch.setattr(indmoney, "place_order_api", lambda payload, auth: busy_response())

    response, status = indmoney.close_all_positions("x", "tok")

    assert status == 429
    assert response["status"] == "error"
    assert response["message"].startswith("1 of 1 open positions were not squared off")


# ---------------------------------------------------------------------------
# brokers-03: a refused Nubra multiquote does not queue at the gate again
# ---------------------------------------------------------------------------


def test_nubra_refused_multiquote_goes_straight_to_rest(gthread, monkeypatch):
    import broker.nubra.api.data as nubra

    ceiling = 0.3
    monkeypatch.setattr(nubra, "max_queue_wait", lambda kind="data": ceiling)
    gate = threading.BoundedSemaphore(nubra._FEED_WAITERS_MAX)
    monkeypatch.setattr(nubra, "_feed_waiters", gate)
    for _ in range(nubra._FEED_WAITERS_MAX):
        gate.acquire()

    waits = []
    real_acquire = gate.acquire

    def counting_acquire(*args, **kwargs):
        waits.append(threading.current_thread().name)
        return real_acquire(*args, **kwargs)

    monkeypatch.setattr(gate, "acquire", counting_acquire)

    class Connected:
        is_connected = True

    data = nubra.BrokerData("tok")
    monkeypatch.setattr(data, "get_websocket", lambda *a, **k: Connected())
    monkeypatch.setattr(data, "_get_quotes_via_rest", lambda symbol, exchange: {"ltp": 1.0})

    symbols = [{"symbol": f"S{i}", "exchange": "NSE"} for i in range(20)]
    started = time.monotonic()
    out = data.get_multiquotes(symbols)
    elapsed = time.monotonic() - started

    assert len(out) == 20 and all(row["data"]["ltp"] == 1.0 for row in out)
    assert len(waits) == 1, f"the gate was waited on {len(waits)} times"
    assert elapsed < ceiling * 3, elapsed


def test_nubra_index_quote_without_feed_is_zeros(gthread, monkeypatch):
    import broker.nubra.api.data as nubra

    data = nubra.BrokerData("tok")
    quote = data._get_quotes_rest_only("NIFTY", "NSE_INDEX")
    assert quote["ltp"] == 0 and set(quote) >= {"bid", "ask", "ltp", "volume", "oi"}


# ---------------------------------------------------------------------------
# brokers-04: the feed gate's refusal keeps its type through the wrappers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["motilal", "tradejini", "pocketful"])
def test_multiquote_refusal_is_a_busy_answer(gthread, monkeypatch, name):
    import importlib

    import services.quotes_service as qs
    from services.broker_busy import is_broker_busy

    module = importlib.import_module(f"broker.{name}.api.data")

    def refuse(self, symbols):
        raise BrokerBusyError(module._FEED_BUSY_MESSAGE)

    monkeypatch.setattr(module.BrokerData, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(module.BrokerData, "_process_multiquotes_batch", refuse)
    monkeypatch.setattr(qs, "get_token", lambda symbol, exchange: "123")

    ok, response, status = qs.get_multiquotes_with_auth(
        "tok", "feed", name, [{"symbol": "NIFTY24OCT25000CE", "exchange": "NFO"}]
    )

    assert not ok
    assert is_broker_busy(status), (status, response)


@pytest.mark.parametrize("method", ["get_quotes", "get_market_depth"])
def test_pocketful_quote_and_depth_refusals_keep_their_type(gthread, monkeypatch, method):
    import broker.pocketful.api.data as pocketful

    def refuse(self, symbol, exchange):
        raise BrokerBusyError(pocketful._FEED_BUSY_MESSAGE)

    monkeypatch.setattr(pocketful.BrokerData, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(pocketful.BrokerData, "_get_quotes_compact", refuse)
    monkeypatch.setattr(pocketful.BrokerData, "_get_market_depth_websocket", refuse)

    with pytest.raises(BrokerBusyError):
        getattr(pocketful.BrokerData(), method)("NIFTY", "NSE_INDEX")


# ---------------------------------------------------------------------------
# brokers-05: a read throttled past the ceiling is busy, not an empty book
# ---------------------------------------------------------------------------


class _IiflClient:
    def __init__(self):
        self.gets = 0
        self.posts = []

    def get(self, url, **kwargs):
        self.gets += 1
        if self.gets == 1:
            return Reply(
                429, {"status": "error", "message": "Too many requests"}, {"Retry-After": "30"}
            )
        return Reply(
            200,
            {
                "status": "success",
                "result": [
                    {
                        "tradingSymbol": "NIFTYFUT",
                        "exchange": "NSEFO",
                        "product": "NRML",
                        "netQuantity": 75,
                    }
                ],
            },
        )

    def post(self, url, **kwargs):
        self.posts.append(kwargs.get("json"))
        return Reply(200, {"status": "success", "result": [{"brokerOrderId": "X1"}]})


@pytest.fixture
def iifl(monkeypatch):
    import broker.iiflcapital.api.order_api as oa

    client = _IiflClient()
    slept = []
    monkeypatch.setattr(oa, "get_httpx_client", lambda: client)
    monkeypatch.setattr(oa, "get_br_symbol", lambda symbol, exchange: symbol)
    monkeypatch.setattr(oa, "get_token", lambda symbol, exchange: "123")
    monkeypatch.setattr(oa, "apply_rate_limit", lambda kind="data": None)
    monkeypatch.setattr(oa, "map_exchange", lambda exchange: "NSEFO")
    monkeypatch.setattr(oa, "map_product_type", lambda product: "NRML")
    monkeypatch.setattr(
        oa,
        "transform_data",
        lambda data, token: {"quantity": data["quantity"], "transactionType": data["action"]},
    )
    monkeypatch.setattr(oa.time, "sleep", lambda seconds: slept.append(seconds))
    return oa, client, slept


SMART = {
    "symbol": "NIFTYFUT",
    "exchange": "NFO",
    "product": "NRML",
    "action": "BUY",
    "quantity": "75",
    "position_size": "75",
}


def test_iifl_smart_order_is_not_sized_off_a_throttle_body(gthread, iifl):
    oa, client, slept = iifl

    res, data, orderid = oa.place_smartorder_api(dict(SMART), "tok")

    assert client.posts == [], "an order was sized against a throttle reply"
    assert orderid is None and res.status == 429
    assert slept == []


def test_iifl_smart_order_on_the_dev_server_still_sleeps_and_retries(dev, iifl):
    oa, client, slept = iifl

    oa.place_smartorder_api(dict(SMART), "tok")

    assert slept == [30.0] and client.gets == 2
    assert client.posts == []  # 75 held, 75 wanted: nothing to send


def test_upstox_read_throttled_past_the_ceiling_is_busy(gthread, monkeypatch):
    import broker.upstox.api.data as data
    import broker.upstox.api.order_api as order

    throttle = Reply(429, {"status": "error"}, {"Retry-After": "30"})

    class Client:
        def get(self, url, **kwargs):
            return throttle

    monkeypatch.setenv("BROKER_API_KEY", "k")
    for module in (order, data):
        monkeypatch.setattr(module, "apply_rate_limit", lambda *a, **k: None)
        monkeypatch.setattr(module, "get_httpx_client", lambda: Client())
        monkeypatch.setattr(module.time, "sleep", lambda s: pytest.fail("slept past the ceiling"))

    with pytest.raises(BrokerBusyError):
        order.get_positions("tok")
    with pytest.raises(BrokerBusyError):
        data.get_api_response("/v3/market-quote/quotes", "tok")


def test_upstox_read_on_the_dev_server_sleeps_and_retries(dev, monkeypatch):
    import broker.upstox.api.order_api as order

    replies = [
        Reply(429, {"status": "error"}, {"Retry-After": "30"}),
        Reply(200, {"status": "success", "data": []}),
    ]
    slept = []

    class Client:
        def get(self, url, **kwargs):
            return replies.pop(0)

    monkeypatch.setenv("BROKER_API_KEY", "k")
    monkeypatch.setattr(order, "apply_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(order, "get_httpx_client", lambda: Client())
    monkeypatch.setattr(order.time, "sleep", lambda s: slept.append(s))

    assert order.get_positions("tok") == {"status": "success", "data": []}
    assert slept == [30.0]
