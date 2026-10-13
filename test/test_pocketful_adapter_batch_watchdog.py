import json

# websocket_proxy imports the adapter from its package initializer.
import websocket_proxy  # noqa: F401  isort:skip

from broker.pocketful.streaming import pocketful_adapter as adapter_module
from broker.pocketful.streaming.pocketful_adapter import PocketfulWebSocketAdapter


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def close(self):
        self.closed = True


class StopAfterOneCheck:
    def __init__(self):
        self.calls = 0

    def wait(self, _seconds):
        self.calls += 1
        return self.calls > 2


def test_subscriptions_are_batched_by_feed_mode_and_exchange():
    adapter = PocketfulWebSocketAdapter()
    ws = FakeSocket()
    adapter.connected = True
    adapter.ws_client = ws
    adapter.subscription_queue = {
        "a": {"pocketful_mode": 2, "exchange_code": 1, "token": "11"},
        "b": {"pocketful_mode": 2, "exchange_code": 1, "token": "12"},
        "c": {"pocketful_mode": 4, "exchange_code": 1, "token": "13"},
        "d": {"pocketful_mode": 2, "exchange_code": 2, "token": "14"},
    }

    adapter._process_batch_subscriptions()

    assert len(ws.sent) == 3
    assert {tuple((packet["m"], tuple(map(tuple, packet["v"])))) for packet in ws.sent} == {
        ("compact_marketdata", ((1, 11), (1, 12))),
        ("full_snapquote", ((1, 13),)),
        ("compact_marketdata", ((2, 14),)),
    }


def test_batch_timer_uses_a_fixed_window(monkeypatch):
    timers = []

    class FakeTimer:
        def __init__(self, _delay, _callback):
            self.alive = False
            timers.append(self)

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

    monkeypatch.setattr(adapter_module._real_threading, "Timer", FakeTimer)
    adapter = PocketfulWebSocketAdapter()

    with adapter.lock:
        adapter._start_batch_timer_locked()
        first_timer = adapter.batch_timer
        adapter._start_batch_timer_locked()

    assert len(timers) == 1
    assert adapter.batch_timer is first_timer


def test_watchdog_closes_only_after_real_data_stalls(monkeypatch):
    adapter = PocketfulWebSocketAdapter()
    ws = FakeSocket()
    adapter.running = True
    adapter.connected = True
    adapter.ws_client = ws
    adapter._data_watchdog_armed = True
    adapter._last_data_message_time = 100

    times = iter([189, 191])
    monkeypatch.setattr(adapter_module.time, "monotonic", lambda: next(times))
    adapter._health_check_loop(StopAfterOneCheck(), ws)

    assert ws.closed


def test_data_watchdog_arms_on_spread_across_three_time_buckets(monkeypatch):
    adapter = PocketfulWebSocketAdapter()
    moments = iter([100, 101, 131, 161])
    monkeypatch.setattr(adapter_module.time, "monotonic", lambda: next(moments))
    for _ in range(4):
        adapter._record_market_data()

    assert adapter._data_watchdog_armed


def test_data_watchdog_stays_disarmed_until_three_recent_buckets(monkeypatch):
    adapter = PocketfulWebSocketAdapter()
    moments = iter([100, 101, 131, 431, 461])
    monkeypatch.setattr(adapter_module.time, "monotonic", lambda: next(moments))

    for _ in range(3):
        adapter._record_market_data()
    assert not adapter._data_watchdog_armed

    adapter._record_market_data()
    adapter._record_market_data()
    assert not adapter._data_watchdog_armed


def test_failed_batch_is_requeued_for_retry(monkeypatch):
    class FailingSocket(FakeSocket):
        def send(self, _payload):
            raise OSError("temporary send failure")

    adapter = PocketfulWebSocketAdapter()
    class FakeTimer:
        def __init__(self, *_args):
            self.alive = False

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

    monkeypatch.setattr(adapter_module._real_threading, "Timer", FakeTimer)
    adapter.connected = True
    adapter.ws_client = FailingSocket()
    sub = {"pocketful_mode": 2, "exchange_code": 1, "token": "11"}
    adapter.subscriptions["a"] = sub
    adapter.subscription_queue["a"] = sub

    adapter._process_batch_subscriptions()

    assert adapter.subscription_queue == {"a": sub}
    assert adapter.batch_timer is not None
