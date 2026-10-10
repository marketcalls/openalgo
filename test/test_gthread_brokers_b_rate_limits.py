"""Broker request pacing: bounded under gthread, unchanged under eventlet and dev.

The Upstox, TradeSmart, IIFL Capital and IndMoney limiters book a future slot
for every caller and make it sleep until the slot comes round, however far
ahead that is. Upstox's 30-minute window meant a sleep of up to 1800 seconds,
orders included. Under eventlet that sleep is green and costs time only; under
the gthread worker it holds one of a fixed number of request threads, and a
burst parks all of them behind one broker.

So under gthread a caller whose slot is further away than the ceiling in
``utils.broker_backpressure`` is refused with a sentence a trader can act on,
books nothing, and sends nothing. Under eventlet and the dev server every
limiter waits exactly as it did. Each case below is asserted both ways.

No account and no network: sleeps are recorded instead of slept, and every
HTTP client is a stub that fails the test if an order reaches it.
"""

from __future__ import annotations

import time
from collections import deque

import pytest

from utils import runtime
from utils.broker_backpressure import BROKER_MAX_ORDER_QUEUE_WAIT_SECONDS, BrokerBusyError


@pytest.fixture
def gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)


@pytest.fixture
def not_gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)


class SleepRecorder:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def _record_sleeps(monkeypatch, module) -> SleepRecorder:
    recorder = SleepRecorder()
    monkeypatch.setattr(module.time, "sleep", recorder)
    return recorder


def _assert_plain_sentence(message: str):
    assert message and message[0].isupper() and message.endswith(".")
    for jargon in ("429", "HTTP", "BrokerBusyError", "Exception", "gthread"):
        assert jargon not in message, f"{jargon!r} is not for a trader: {message}"


class NoHttp:
    """An httpx client stand-in that fails the test if anything is sent."""

    def __init__(self):
        self.sent = []

    def _send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        raise AssertionError("a request reached the broker although it was refused")

    get = post = put = delete = request = _send


# --- Upstox --------------------------------------------------------------------


@pytest.fixture
def upstox_rl():
    from broker.upstox.api import rate_limiter

    return rate_limiter


def _full_upstox_limiter(rl, kind="data"):
    limiter = rl.SlidingWindowLimiter("t", 5, 5, 5, kind=kind)
    for _ in range(5):
        assert limiter.reserve() == pytest.approx(0.0, abs=0.01)
    return limiter


def test_upstox_a_full_half_hour_is_refused_under_gthread(upstox_rl, gthread, monkeypatch):
    sleeps = _record_sleeps(monkeypatch, upstox_rl)
    limiter = _full_upstox_limiter(upstox_rl)

    with pytest.raises(BrokerBusyError) as refused:
        limiter.acquire()

    assert sleeps.calls == []
    assert limiter.depth() == 5, "a refused caller must not book a slot"
    assert refused.value.retry_after == pytest.approx(1800.0, abs=1.0)
    assert "30 minutes" in str(refused.value)
    _assert_plain_sentence(str(refused.value))


def test_upstox_still_waits_the_half_hour_outside_gthread(upstox_rl, not_gthread, monkeypatch):
    sleeps = _record_sleeps(monkeypatch, upstox_rl)
    limiter = _full_upstox_limiter(upstox_rl)

    limiter.acquire()

    assert sleeps.calls == [pytest.approx(1800.0, abs=1.0)]
    assert limiter.depth() == 6


def test_upstox_a_short_wait_is_still_slept_under_gthread(upstox_rl, gthread, monkeypatch):
    """Only a wait past the ceiling is refused; ordinary pacing is unchanged."""
    sleeps = _record_sleeps(monkeypatch, upstox_rl)
    limiter = upstox_rl.SlidingWindowLimiter("t", 2, 100, 100)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()
    assert len(sleeps.calls) == 1 and 0.5 < sleeps.calls[0] <= 1.0
    assert limiter.depth() == 3


def test_upstox_order_is_refused_and_not_sent(upstox_rl, gthread, monkeypatch):
    from broker.upstox.api import order_api

    monkeypatch.setitem(upstox_rl._LIMITERS, "order", _full_upstox_limiter(upstox_rl, "order"))
    client = NoHttp()
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
    monkeypatch.setattr(order_api, "get_token", lambda symbol, exchange: "NSE_EQ|1")
    monkeypatch.setenv("BROKER_API_KEY", "test")

    res, data, orderid = order_api.place_order_api(
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "1",
            "pricetype": "MARKET",
            "product": "MIS",
        },
        "tok",
    )

    assert res.status == 429 and orderid is None
    assert data["status"] == "error" and "order was not sent" in data["message"]
    _assert_plain_sentence(data["message"])
    assert client.sent == []


def test_upstox_smart_order_never_reads_a_refused_book_as_flat(upstox_rl, gthread, monkeypatch):
    """A refused positions read used to fall into get_open_position's catch-all
    and come back as "0", which sizes the order against a flat position."""
    from broker.upstox.api import order_api

    monkeypatch.setitem(upstox_rl._LIMITERS, "standard", _full_upstox_limiter(upstox_rl))
    placed = []
    monkeypatch.setattr(order_api, "place_order_api", lambda *a: placed.append(a))
    monkeypatch.setattr(order_api, "get_br_symbol", lambda symbol, exchange: symbol)

    res, data, orderid = order_api.place_smartorder_api(
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": "10",
            "position_size": "0",
        },
        "tok-upstox-smart",
    )

    assert placed == []
    assert res.status == 429 and orderid is None
    _assert_plain_sentence(data["message"])


def test_upstox_retry_after_past_the_ceiling_is_not_slept_under_gthread(
    upstox_rl, gthread, monkeypatch
):
    from broker.upstox.api import data as upstox_data

    sleeps = _record_sleeps(monkeypatch, upstox_data)
    monkeypatch.setattr(upstox_data, "apply_rate_limit", lambda category: None)
    calls = []

    class Response:
        status_code = 429
        headers = {"Retry-After": "60"}

        def json(self):
            return {"status": "error", "errors": [{"errorCode": "UDAPI10005"}]}

    class Client:
        def get(self, url, headers=None):
            calls.append(url)
            return Response()

    monkeypatch.setattr(upstox_data, "get_httpx_client", lambda: Client())
    # Refused as busy, not handed back as data: an error body read as an empty
    # book is how a smart order ends up sized as if flat (review brokers-05).
    with pytest.raises(BrokerBusyError):
        upstox_data.get_api_response("/market-quote/quotes", "tok")

    assert len(calls) == 1 and sleeps.calls == []


def test_upstox_retry_after_is_honoured_outside_gthread(upstox_rl, not_gthread, monkeypatch):
    from broker.upstox.api import data as upstox_data

    sleeps = _record_sleeps(monkeypatch, upstox_data)
    monkeypatch.setattr(upstox_data, "apply_rate_limit", lambda category: None)
    calls = []

    class Response:
        status_code = 429
        headers = {"Retry-After": "60"}

        def json(self):
            return {"status": "error", "errors": [{"errorCode": "UDAPI10005"}]}

    class Client:
        def get(self, url, headers=None):
            calls.append(url)
            return Response()

    monkeypatch.setattr(upstox_data, "get_httpx_client", lambda: Client())
    upstox_data.get_api_response("/market-quote/quotes", "tok")

    assert len(calls) == 1 + upstox_data.MAX_RETRIES
    assert sleeps.calls == [60.0] * upstox_data.MAX_RETRIES


# --- TradeSmart ----------------------------------------------------------------


@pytest.fixture
def tradesmart_rl():
    from broker.tradesmart.api import rate_limiter

    return rate_limiter


def _full_minute(rl):
    import threading

    lock, reserved = threading.Lock(), deque()
    for _ in range(10):
        rl._reserve_slot(lock, reserved, 100, 10)
    return lock, reserved


def test_tradesmart_a_full_minute_is_refused_under_gthread(tradesmart_rl, gthread):
    lock, reserved = _full_minute(tradesmart_rl)
    with pytest.raises(BrokerBusyError) as refused:
        tradesmart_rl._reserve_slot(lock, reserved, 100, 10)
    assert len(reserved) == 10, "a refused caller must not book a slot"
    assert refused.value.retry_after > 30
    _assert_plain_sentence(str(refused.value))


def test_tradesmart_still_waits_out_the_minute_outside_gthread(tradesmart_rl, not_gthread):
    lock, reserved = _full_minute(tradesmart_rl)
    assert tradesmart_rl._reserve_slot(lock, reserved, 100, 10) > 30
    assert len(reserved) == 11


def test_tradesmart_quote_refusal_keeps_its_sentence(tradesmart_rl, gthread, monkeypatch):
    from broker.tradesmart.api import data as tradesmart_data

    def refuse(endpoint=None):
        raise tradesmart_rl._busy_error(42.0)

    monkeypatch.setattr(tradesmart_data, "apply_rate_limit", refuse)
    monkeypatch.setattr(tradesmart_data, "get_token", lambda symbol, exchange: "1")
    with pytest.raises(BrokerBusyError) as refused:
        tradesmart_data.BrokerData("uid:::tok").get_quotes("SBIN", "NSE")
    assert str(refused.value).startswith("TradeSmart")


# --- IIFL Capital --------------------------------------------------------------


@pytest.fixture
def iifl_rl(monkeypatch):
    from broker.iiflcapital.api import rate_limiter

    monkeypatch.setattr(rate_limiter, "_last_call_time", 0.0)
    monkeypatch.setattr(rate_limiter, "_last_order_call_time", 0.0)
    return rate_limiter


def test_iifl_a_long_backlog_is_refused_under_gthread(iifl_rl, gthread, monkeypatch):
    sleeps = _record_sleeps(monkeypatch, iifl_rl)
    backlog = time.time() + 100
    iifl_rl._last_call_time = backlog

    with pytest.raises(BrokerBusyError) as refused:
        iifl_rl.apply_rate_limit()

    assert iifl_rl._last_call_time == backlog, "a refused caller must not book a slot"
    assert sleeps.calls == []
    _assert_plain_sentence(str(refused.value))


def test_iifl_still_waits_out_the_backlog_outside_gthread(iifl_rl, not_gthread, monkeypatch):
    sleeps = _record_sleeps(monkeypatch, iifl_rl)
    iifl_rl._last_call_time = time.time() + 100

    iifl_rl.apply_rate_limit()

    assert len(sleeps.calls) == 1 and sleeps.calls[0] > 99


def test_iifl_orders_do_not_queue_behind_data_under_gthread(iifl_rl, gthread, monkeypatch):
    """IIFL caps orders separately; under gthread an order has its own clock."""
    sleeps = _record_sleeps(monkeypatch, iifl_rl)
    iifl_rl._last_call_time = time.time() + 100  # an option chain's OI fan-out

    iifl_rl.apply_rate_limit("order")

    assert all(s <= iifl_rl.MIN_INTERVAL for s in sleeps.calls)
    assert iifl_rl._last_order_call_time > 0


def test_iifl_orders_share_the_one_clock_outside_gthread(iifl_rl, not_gthread, monkeypatch):
    sleeps = _record_sleeps(monkeypatch, iifl_rl)
    iifl_rl._last_call_time = time.time() + 100

    iifl_rl.apply_rate_limit("order")

    assert len(sleeps.calls) == 1 and sleeps.calls[0] > 99
    assert iifl_rl._last_order_call_time == 0.0


def test_iifl_order_refused_by_the_pacer_is_not_sent(iifl_rl, gthread, monkeypatch):
    from broker.iiflcapital.api import order_api

    iifl_rl._last_order_call_time = time.time() + BROKER_MAX_ORDER_QUEUE_WAIT_SECONDS + 50
    client = NoHttp()
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
    monkeypatch.setattr(order_api, "get_token", lambda symbol, exchange: "2885")

    res, data, orderid = order_api.place_order_api(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "1",
            "pricetype": "MARKET",
            "product": "MIS",
        },
        "tok",
    )

    assert res.status == 429 and orderid is None
    assert "order was not sent" in data["message"]
    _assert_plain_sentence(data["message"])
    assert client.sent == []


def test_iifl_smart_order_is_refused_when_its_position_read_is(iifl_rl, gthread, monkeypatch):
    from broker.iiflcapital.api import order_api

    iifl_rl._last_call_time = time.time() + 100
    placed = []
    monkeypatch.setattr(order_api, "place_order_api", lambda *a: placed.append(a))
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: NoHttp())

    res, data, orderid = order_api.place_smartorder_api(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": "5",
            "position_size": "0",
        },
        "tok",
    )

    assert placed == []
    assert res.status == 429 and orderid is None
    _assert_plain_sentence(data["message"])


# --- IndMoney ------------------------------------------------------------------


@pytest.fixture
def indmoney_rl(monkeypatch):
    from broker.indmoney.api import rate_limiter

    monkeypatch.setattr(rate_limiter, "_next_free", {})
    return rate_limiter


def test_indmoney_a_long_backlog_is_refused_under_gthread(indmoney_rl, gthread, monkeypatch):
    sleeps = _record_sleeps(monkeypatch, indmoney_rl)
    backlog = time.monotonic() + 100
    indmoney_rl._next_free["quote"] = backlog

    with pytest.raises(BrokerBusyError) as refused:
        indmoney_rl.apply_rate_limit("quote")

    assert indmoney_rl._next_free["quote"] == backlog
    assert sleeps.calls == []
    _assert_plain_sentence(str(refused.value))


def test_indmoney_still_waits_out_the_backlog_outside_gthread(
    indmoney_rl, not_gthread, monkeypatch
):
    sleeps = _record_sleeps(monkeypatch, indmoney_rl)
    indmoney_rl._next_free["quote"] = time.monotonic() + 100

    indmoney_rl.apply_rate_limit("quote")

    assert len(sleeps.calls) == 1 and sleeps.calls[0] > 99


def test_indmoney_order_refused_by_the_pacer_is_not_sent(indmoney_rl, gthread, monkeypatch):
    from broker.indmoney.api import order_api

    indmoney_rl._next_free["order"] = time.monotonic() + 100
    client = NoHttp()
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
    monkeypatch.setattr(order_api, "get_token", lambda symbol, exchange: "2885")
    monkeypatch.setattr(order_api, "transform_data", lambda data, token: {"order_type": "MARKET"})

    res, data, orderid = order_api.place_order_api(
        {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": "1"},
        "tok",
    )

    assert res.status == 429 and orderid is None
    assert "order was not sent" in data["message"]
    _assert_plain_sentence(data["message"])
    assert client.sent == []


def test_indmoney_smart_order_never_reads_a_refused_book_as_flat(indmoney_rl, gthread, monkeypatch):
    """get_api_response and get_positions used to turn any failure into an
    error body or an empty list, which get_open_position reads as flat."""
    from broker.indmoney.api import order_api

    indmoney_rl._next_free["non_trading"] = time.monotonic() + 100
    placed = []
    monkeypatch.setattr(order_api, "place_order_api", lambda *a: placed.append(a))
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: NoHttp())
    monkeypatch.setattr(order_api, "get_token", lambda symbol, exchange: "2885")
    monkeypatch.setattr(order_api, "get_br_symbol", lambda symbol, exchange: symbol)

    res, data, orderid = order_api.place_smartorder_api(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": "5",
            "position_size": "0",
        },
        "tok-indmoney-smart",
    )

    assert placed == []
    assert res.status == 429 and orderid is None
    _assert_plain_sentence(data["message"])
