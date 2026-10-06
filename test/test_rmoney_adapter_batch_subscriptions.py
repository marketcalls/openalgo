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


def test_failed_batch_is_requeued_for_retry(monkeypatch):
    class FakeTimer:
        def __init__(self, *_args):
            self.alive = False

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

    class FailingClient:
        def subscribe_batch(self, *_args):
            raise OSError("temporary request failure")

    monkeypatch.setattr(adapter_module._real_threading, "Timer", FakeTimer)
    adapter = RMoneyWebSocketAdapter()
    adapter.connected = True
    adapter.ws_client = FailingClient()
    sub = _subscription(1, 2)
    adapter.subscriptions = {"SYM1_NSE_2": sub}
    adapter.subscription_queue = {"SYM1_NSE_2": sub}

    adapter._process_batch_subscriptions()

    assert adapter.subscription_queue == {"SYM1_NSE_2": sub}
    assert adapter.batch_timer is not None


def test_unsubscribe_removes_both_depth_level_entries(monkeypatch):
    calls = []

    class Client:
        def unsubscribe(self, *args):
            calls.append(args)
            return True

    monkeypatch.setattr(
        adapter_module.SymbolMapper,
        "get_token_from_symbol",
        lambda *_args: {"token": "123", "brexchange": "NSECM"},
    )
    adapter = RMoneyWebSocketAdapter()
    adapter.connected = True
    adapter.ws_client = Client()
    adapter.disconnect = lambda: None
    adapter.subscriptions = {
        "SYM_NSE_3_5": {"symbol": "SYM", "exchange": "NSE", "mode": 3},
        "SYM_NSE_3_20": {"symbol": "SYM", "exchange": "NSE", "mode": 3},
    }

    response = adapter.unsubscribe("SYM", "NSE", 3)

    assert response is not None
    assert adapter.subscriptions == {}
    assert len(calls) == 1


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


def test_websocket_client_caps_each_request_at_fifty_instruments():
    class FakeResponse:
        status_code = 200
        text = ""

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
        (f"SYM{i}_NSE_2", [{"exchangeSegment": 1, "exchangeInstrumentID": i}])
        for i in range(51)
    ]

    client.subscribe_batch("batch", 2, subscriptions)

    requests = [kwargs["json"]["instruments"] for _, kwargs in client._http_session.calls]
    assert [len(items) for items in requests] == [50, 1]
    assert set(client.subscriptions) == {correlation_id for correlation_id, _ in subscriptions}


def test_duplicate_in_batch_retries_instruments_individually():
    class FakeResponse:
        def __init__(self, duplicate):
            self.status_code = 400 if duplicate else 200
            self.text = "Instrument Already Subscribed" if duplicate else ""

        def json(self):
            return {"type": "success"}

        def close(self):
            pass

    class FakeSession:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append(kwargs["json"])
            return FakeResponse(duplicate=len(self.calls) in (1, 2))

    client = RMoneyWebSocketClient("key", "secret", "user", "https://example.test")
    client.connected = True
    client.market_data_token = "token"
    client._http_session = FakeSession()
    subscriptions = [
        ("A_NSE_2", [{"exchangeSegment": 1, "exchangeInstrumentID": 1}]),
        ("B_NSE_2", [{"exchangeSegment": 1, "exchangeInstrumentID": 2}]),
    ]

    client.subscribe_batch("batch", 2, subscriptions)

    assert [len(call["instruments"]) for call in client._http_session.calls] == [2, 1, 1]
    assert set(client.subscriptions) == {"A_NSE_2", "B_NSE_2"}
