import websocket_proxy  # noqa: F401  isort:skip

from broker.rmoney.streaming import rmoney_adapter as adapter_module
from broker.rmoney.streaming.rmoney_adapter import RMoneyWebSocketAdapter
from broker.rmoney.streaming.rmoney_websocket import RMoneyWebSocketClient


class FakeWebSocketClient:
    def __init__(self):
        self.calls = []

    def subscribe_batch(self, batch_id, mode, subscriptions):
        instruments = [item for _, items in subscriptions for item in items]
        self.calls.append((batch_id, mode, subscriptions, instruments))


def _subscription(index, mode):
    return {
        "symbol": f"SYM{index}",
        "exchange": "NSE",
        "token": str(index),
        "mode": mode,
        "instruments": [
            {"exchangeSegment": 1, "exchangeInstrumentID": index}
        ],
    }


def test_reconnect_subscriptions_batch_all_saved_symbols_by_mode():
    adapter = RMoneyWebSocketAdapter()
    adapter.connected = True
    adapter.ws_client = FakeWebSocketClient()
    adapter.subscriptions = {
        f"SYM{index}_NSE_{mode}": _subscription(index, mode)
        for mode, count, offset in ((1, 120, 0), (3, 55, 1000))
        for index in range(offset, offset + count)
    }
    adapter.subscription_queue.update(adapter.subscriptions)

    adapter._process_batch_subscriptions()

    calls = adapter.ws_client.calls
    assert len(calls) == 2
    assert {mode for _, mode, _, _ in calls} == {1, 3}
    assert sum(len(items) for _, mode, _, items in calls if mode == 1) == 120
    assert sum(len(items) for _, mode, _, items in calls if mode == 3) == 55


def test_batch_timer_keeps_a_fixed_coalescing_window(monkeypatch):
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
    adapter = RMoneyWebSocketAdapter()

    with adapter.lock:
        adapter._start_batch_timer_locked()
        timer = adapter.batch_timer
        adapter._start_batch_timer_locked()

    assert len(timers) == 1
    assert adapter.batch_timer is timer


def test_websocket_client_keeps_individual_ids_for_a_batch():
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"type": "success"}

        def close(self):
            pass

    class FakeSession:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return FakeResponse()

    client = RMoneyWebSocketClient("key", "secret", "user", "https://example.test")
    client.connected = True
    client.market_data_token = "token"
    client._http_session = FakeSession()
    subscriptions = [
        ("RELIANCE_NSE_2", [{"exchangeSegment": 1, "exchangeInstrumentID": 2885}]),
        ("TCS_NSE_2", [{"exchangeSegment": 1, "exchangeInstrumentID": 11536}]),
    ]

    client.subscribe_batch("__openalgo_batch_2_0", 2, subscriptions)

    assert len(client._http_session.calls) == 1
    request = client._http_session.calls[0][1]["json"]
    assert request["xtsMessageCode"] == 1501
    assert [item["exchangeInstrumentID"] for item in request["instruments"]] == [2885, 11536]
    assert set(client.subscriptions) == {"RELIANCE_NSE_2", "TCS_NSE_2"}
