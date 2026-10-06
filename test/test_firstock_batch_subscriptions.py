import websocket_proxy  # noqa: F401  isort:skip

from broker.firstock.streaming import firstock_adapter as adapter_module
from broker.firstock.streaming.firstock_adapter import FirstockWebSocketAdapter
from broker.firstock.streaming.firstock_websocket import FirstockWebSocket


class FakeSocketApp:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)


def test_unsubscribe_retires_batched_tracking_only_after_last_token():
    client = FirstockWebSocket("user", "token")
    client.connection_state = client.CONNECTED
    client.authenticated = True
    client.wsapp = FakeSocketApp()
    batch_id = "batch-1"
    client.subscribe(
        batch_id,
        2,
        [{"exchangeType": "NSE", "tokens": ["1", "2"]}],
    )

    client.unsubscribe("SYM1_NSE_2", 2, [{"exchangeType": "NSE", "tokens": ["1"]}])
    assert client.get_subscriptions() == [batch_id]

    client.unsubscribe("SYM2_NSE_2", 2, [{"exchangeType": "NSE", "tokens": ["2"]}])
    assert client.get_subscriptions() == []


def test_connection_close_clears_batch_tracking_before_reconnect():
    client = FirstockWebSocket("user", "token")
    client.subscriptions.add("old-batch")
    client._subscription_tokens["old-batch"] = {"NSE:1"}

    client._on_close(None)

    assert client.get_subscriptions() == []
    assert client._subscription_tokens == {}


def test_failed_batch_is_requeued_for_retry(monkeypatch):
    class FakeTimer:
        def __init__(self, *_args):
            self.alive = False

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

    class FailingClient:
        authenticated = True
        is_running = True

        def is_connected(self):
            return True

        def subscribe(self, *_args):
            raise OSError("temporary send failure")

    monkeypatch.setattr(adapter_module._real_threading, "Timer", FakeTimer)
    adapter = FirstockWebSocketAdapter()
    adapter.connected = True
    adapter.ws_client = FailingClient()
    item = {"brexchange": "NSE", "token": "1", "subscription_token": "NSE:1"}
    adapter.ws_subscription_refs = {"NSE:1": {"mode_2": 1}}
    adapter.subscription_queue = [item]

    adapter._process_subscription_batch()

    assert adapter.subscription_queue == [item]
    assert adapter.batch_timer is not None
