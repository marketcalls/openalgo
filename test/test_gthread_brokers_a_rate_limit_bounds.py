"""Broker pacers in brokers_a bound their waits under gthread, and only there.

Six plugins pace their REST calls with a shared, module-level queue: AliceBlue
(1800 reads per 15 minutes), Flattrade (per-second and per-minute windows for
data and for orders), Dhan (quotes one a second), Fyers (one clock for every
call), Angel (quote and history clocks plus a penalty push-out) and Definedge
(one clock per host, shared with order placement). Each books the next slot
and makes the caller sleep until it arrives, however far away that is.

Under eventlet a sleeping caller is a parked greenlet. Under the gthread
worker it holds one of a fixed number of request threads, so a burst past a
pacer's rate (dashboard polling plus an option chain, a strategy polling
quotes) parks every thread and the app stops answering, placeorder included.

So under gthread a caller whose turn is further away than
``utils.broker_backpressure.max_queue_wait`` is refused at once, before it
books anything, with a sentence a trader can act on; and a Retry-After longer
than the bound ends the retry instead of being slept. Under eventlet and the
dev server nothing changes: every case below is run both ways.

The refusals must never be read as data. A smart order whose position read is
refused must not place anything, and a square-off whose orders are refused
must not report success.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils import broker_backpressure as bp
from utils import runtime

os.environ.setdefault("BROKER_API_KEY", "client:::key:::secret")

REPO = Path(__file__).resolve().parents[1]
BOUND = bp.BROKER_MAX_QUEUE_WAIT_SECONDS


@pytest.fixture
def gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)


@pytest.fixture
def not_gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)


class SleepRecorder:
    """Stands in for time.sleep in one module: records instead of sleeping."""

    def __init__(self):
        self.calls: list[float] = []
        self.lock = threading.Lock()

    def __call__(self, seconds):
        with self.lock:
            self.calls.append(seconds)


def _record_sleeps(monkeypatch, module):
    recorder = SleepRecorder()
    monkeypatch.setattr(
        module,
        "time",
        SimpleNamespace(
            **{name: getattr(time, name) for name in ("time", "monotonic", "perf_counter")}
            | {"sleep": recorder}
        ),
    )
    return recorder


def _assert_trader_sentence(error):
    text = str(error)
    assert text and text[0].isupper() and text.endswith(".")
    for jargon in ("BrokerBusyError", "Exception", "429", "HTTP", "Traceback"):
        assert jargon not in text, f"{jargon!r} reached the trader: {text}"


# --- the six pacers: one far-away slot, both runtimes -------------------------


def _aliceblue(monkeypatch):
    from broker.aliceblue.api import rate_limiter as rl

    rl.reset()
    monkeypatch.setattr(rl, "_request_times", rl.deque([time.monotonic()] * 1750))
    return rl, (lambda: rl.apply_rate_limit()), (lambda: len(rl._request_times)), 900


def _flattrade(monkeypatch):
    from broker.flattrade.api import rate_limit as rl

    limiter = rl.SlidingWindowLimiter("data", max_per_second=9, max_per_minute=110)
    limiter._reserved.extend([time.time()] * 110)
    return rl, limiter.acquire, (lambda: len(limiter._reserved)), 60


def _flattrade_orders(monkeypatch):
    from broker.flattrade.api import rate_limit as rl

    limiter = rl.SlidingWindowLimiter("order", max_per_second=9, max_per_minute=38, kind="order")
    limiter._reserved.extend([time.time()] * 38)
    return rl, limiter.acquire, (lambda: len(limiter._reserved)), 60


def _dhan(monkeypatch):
    from broker.dhan.api import data

    monkeypatch.setitem(data._last_api_call_time, "quote", time.time() + 60)
    return (
        data,
        (lambda: data._apply_rate_limit("quote")),
        (lambda: round(data._last_api_call_time["quote"])),
        60,
    )


def _fyers(monkeypatch):
    from broker.fyers.api import rate_limiter as rl

    monkeypatch.setattr(rl, "_last_call_time", time.time() + 60)
    return rl, rl.apply_rate_limit, (lambda: round(rl._last_call_time)), 60


def _angel(monkeypatch):
    from broker.angel.api import data

    monkeypatch.setitem(data._last_call_ts, "history", time.time() + 60)
    return (
        data,
        (lambda: data._apply_rate_limit("history")),
        (lambda: round(data._last_call_ts["history"])),
        60,
    )


def _definedge(monkeypatch):
    from broker.definedge.api import rate_limiter as rl

    monkeypatch.setattr(rl, "_last_call_time", {"trade": time.time() + 60})
    return (
        rl,
        (lambda: rl.apply_rate_limit("trade")),
        (lambda: round(rl._last_call_time["trade"])),
        60,
    )


PACERS = {
    "aliceblue": _aliceblue,
    "flattrade-data": _flattrade,
    "flattrade-orders": _flattrade_orders,
    "dhan": _dhan,
    "fyers": _fyers,
    "angel": _angel,
    "definedge": _definedge,
}


@pytest.mark.parametrize("name", sorted(PACERS))
def test_under_gthread_a_far_away_slot_is_refused_and_books_nothing(name, gthread, monkeypatch):
    module, call, booked, _far = PACERS[name](monkeypatch)
    sleeps = _record_sleeps(monkeypatch, module)
    before = booked()

    with pytest.raises(bp.BrokerBusyError) as refused:
        call()

    assert sleeps.calls == [], "a refused caller slept anyway"
    assert booked() == before, "a refused caller still took a slot"
    assert refused.value.retry_after > BOUND
    _assert_trader_sentence(refused.value)


@pytest.mark.parametrize("name", sorted(PACERS))
def test_outside_gthread_the_same_caller_waits_as_before(name, not_gthread, monkeypatch):
    module, call, booked, far = PACERS[name](monkeypatch)
    sleeps = _record_sleeps(monkeypatch, module)

    call()

    assert len(sleeps.calls) == 1
    assert sleeps.calls[0] > far * 0.9, f"expected a long wait, slept {sleeps.calls}"


@pytest.mark.parametrize("name", sorted(PACERS))
def test_under_gthread_a_near_slot_is_still_just_paced(name, gthread, monkeypatch):
    """The quiet path is unchanged: a short wait is waited, not refused."""
    module, call, booked, _far = PACERS[name](monkeypatch)
    _record_sleeps(monkeypatch, module)
    # Undo the preload: the next slot is now at most one interval away.
    if name == "aliceblue":
        module.reset()
    elif name.startswith("flattrade"):
        call.__self__._reserved.clear()  # the limiter behind the bound acquire()
    elif name == "dhan":
        monkeypatch.setitem(module._last_api_call_time, "quote", time.time())
    elif name == "fyers":
        monkeypatch.setattr(module, "_last_call_time", time.time())
    elif name == "angel":
        monkeypatch.setitem(module._last_call_ts, "history", time.time())
    elif name == "definedge":
        monkeypatch.setattr(module, "_last_call_time", {"trade": time.time()})
    call()  # does not raise


# --- a burst from many request threads ----------------------------------------


@pytest.mark.parametrize("mode", ["gthread", "not_gthread"])
def test_a_burst_of_64_request_threads_never_waits_past_the_bound(mode, request, monkeypatch):
    """Dhan quotes pace at 1.1s: the 10th caller onwards is past the bound."""
    request.getfixturevalue(mode)
    from broker.dhan.api import data

    monkeypatch.setitem(data._last_api_call_time, "quote", 0.0)
    sleeps = _record_sleeps(monkeypatch, data)
    barrier = threading.Barrier(64)
    refused = []
    served = []
    lock = threading.Lock()

    def caller():
        barrier.wait(10)
        try:
            data._apply_rate_limit("quote")
        except bp.BrokerBusyError as busy:
            with lock:
                refused.append(busy)
        else:
            with lock:
                served.append(1)

    threads = [threading.Thread(target=caller) for _ in range(64)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    if mode == "gthread":
        assert max(sleeps.calls) <= BOUND
        assert refused, "no caller was refused"
        assert len(served) + len(refused) == 64
        # 1.1s apart: the caller at the slot now plus nine within ten seconds.
        assert len(served) == 10
    else:
        assert refused == []
        assert len(served) == 64
        assert max(sleeps.calls) > 60, "the unbounded queue should reach past a minute"


# --- Retry-After --------------------------------------------------------------


def test_a_long_retry_after_is_not_slept_under_gthread(gthread):
    from broker.definedge.api import rate_limiter as definedge
    from broker.fyers.api import rate_limiter as fyers

    with pytest.raises(bp.BrokerBusyError) as refused:
        fyers.retry_delay_from_headers({"Retry-After": "60"}, 0)
    _assert_trader_sentence(refused.value)
    with pytest.raises(bp.BrokerBusyError):
        definedge.retry_delay({"Retry-After": "60"}, 0)
    # A short one is still honoured.
    assert fyers.retry_delay_from_headers({"Retry-After": "2"}, 0) == 2.0
    assert definedge.retry_delay({"Retry-After": "2"}, 0) == 2.0


def test_a_long_retry_after_is_honoured_outside_gthread(not_gthread):
    from broker.definedge.api import rate_limiter as definedge
    from broker.fyers.api import rate_limiter as fyers

    assert fyers.retry_delay_from_headers({"Retry-After": "60"}, 0) == 60.0
    assert fyers.retry_delay_from_headers({"X-Retry-After-Ms": "90000"}, 0) == 90.0
    assert definedge.retry_delay({"Retry-After": "60"}, 0) == 60.0
    assert definedge.retry_delay({}, 2) == 4.0


# --- a refusal is never read as data --------------------------------------------


def _saturate(monkeypatch, broker_name):
    """Make the broker's next data read wait a minute."""
    if broker_name == "aliceblue":
        _aliceblue(monkeypatch)
    elif broker_name == "flattrade":
        from broker.flattrade.api import order_api

        limiter = order_api.DATA_LIMITER.__class__("data", 9, 110)
        limiter._reserved.extend([time.time()] * 110)
        monkeypatch.setattr(order_api, "DATA_LIMITER", limiter)
    elif broker_name == "fyers":
        _fyers(monkeypatch)
    elif broker_name == "definedge":
        from broker.definedge.api import rate_limiter as rl

        monkeypatch.setattr(
            rl, "_last_call_time", {"integrate.definedgesecurities.com": time.time() + 60}
        )


@pytest.mark.parametrize("broker_name", ["aliceblue", "flattrade", "fyers", "definedge"])
def test_a_refused_position_read_fails_the_smart_order_and_sends_nothing(
    broker_name, gthread, monkeypatch
):
    import importlib

    order_api = importlib.import_module(f"broker.{broker_name}.api.order_api")
    order_api._invalidate_position_cache("a:::b:::c")
    _saturate(monkeypatch, broker_name)
    placed = []
    monkeypatch.setattr(order_api, "place_order_api", lambda data, auth: placed.append(data))
    monkeypatch.setattr(order_api, "get_br_symbol", lambda symbol, exchange: symbol, raising=False)

    res, data, orderid = order_api.place_smartorder_api(
        {
            "apikey": "k",
            "strategy": "s",
            "symbol": "SBIN",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": "5",
            "position_size": "5",
            "pricetype": "MARKET",
        },
        "a:::b:::c",
    )

    assert placed == [], f"{broker_name} placed an order against a book it never read"
    assert (res.status, orderid) == (429, None)
    assert data["status"] == "error"
    _assert_trader_sentence(data["message"])


def test_flattrade_refused_orders_are_reported_not_squared_off(gthread, monkeypatch):
    from broker.flattrade.api import order_api

    limiter = order_api.ORDER_LIMITER.__class__("order", 9, 38, kind="order")
    limiter._reserved.extend([time.time()] * 38)
    monkeypatch.setattr(order_api, "ORDER_LIMITER", limiter)
    positions = [
        {"stat": "Ok", "netqty": "5", "token": "1", "exch": "NSE", "prd": "I"},
        {"stat": "Ok", "netqty": "-2", "token": "2", "exch": "NSE", "prd": "I"},
    ]
    monkeypatch.setattr(order_api, "get_positions", lambda auth: positions)
    monkeypatch.setattr(order_api, "get_symbol", lambda token, exch: f"SYM{token}")
    monkeypatch.setattr(order_api, "get_token", lambda symbol, exchange: "1")

    body, status = order_api.close_all_positions("k", "tok")

    assert status == 429
    assert body["status"] == "error"
    assert body["message"].startswith("2 of 2 open positions were not squared off")


def test_flattrade_order_placement_refusal_sends_nothing(gthread, monkeypatch):
    from broker.flattrade.api import order_api

    limiter = order_api.ORDER_LIMITER.__class__("order", 9, 38, kind="order")
    limiter._reserved.extend([time.time()] * 38)
    monkeypatch.setattr(order_api, "ORDER_LIMITER", limiter)
    sent = []
    monkeypatch.setattr(
        order_api, "get_httpx_client", lambda: SimpleNamespace(post=lambda *a, **k: sent.append(a))
    )
    monkeypatch.setattr(order_api, "get_token", lambda symbol, exchange: "1")

    res, data, orderid = order_api.place_order_api(
        {
            "apikey": "k",
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "1",
            "pricetype": "MARKET",
            "product": "MIS",
            "price": "0",
            "trigger_price": "0",
            "disclosed_quantity": "0",
        },
        "tok",
    )
    assert sent == []
    assert (res.status, orderid) == (429, None)
    _assert_trader_sentence(data["message"])


# --- under a real eventlet hub ----------------------------------------------------


@pytest.mark.skipif(
    __import__("importlib.util").util.find_spec("eventlet") is None,
    reason="eventlet is installed by the production installer, not on Windows dev",
)
def test_under_real_eventlet_a_far_slot_is_still_waited(tmp_path):
    """The production default: no bound, the long wait is taken, no refusal."""
    db = tmp_path / "db"
    db.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{(db / 'openalgo.db').as_posix()}",
            "LOG_DIR": str(tmp_path / "log"),
            "BROKER_API_KEY": "client:::key:::secret",
            "PYTHONPATH": str(REPO),
        }
    )
    script = """
    import eventlet
    eventlet.monkey_patch()
    import time
    from utils import runtime
    from utils import broker_backpressure as bp
    from broker.dhan.api import data
    from broker.flattrade.api import rate_limit
    from broker.aliceblue.api import rate_limiter as alice

    assert runtime.worker_class() == "eventlet"
    assert bp.max_queue_wait("data") is None and bp.max_queue_wait("order") is None
    slept = []
    time.sleep = slept.append  # the patched module-level sleep, in this child only
    data._last_api_call_time["quote"] = time.time() + 60
    data._apply_rate_limit("quote")
    limiter = rate_limit.SlidingWindowLimiter("order", 9, 38, kind="order")
    limiter._reserved.extend([time.time()] * 38)
    limiter.acquire()
    alice._request_times.extend([time.monotonic()] * 1750)
    alice.apply_rate_limit()
    assert len(slept) == 3 and all(s > 50 for s in slept), slept
    print("OK")
    """
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "OK" in proc.stdout, proc.stdout[-2000:] + proc.stderr[-4000:]
