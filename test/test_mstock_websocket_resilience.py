"""mStock WebSocket recovery: dropped subscribes, dead tokens, prompt teardown.

Pins the three recovery defects reported in marketcalls/openalgo#1978. Each one
fails silently in production -- the feed looks connected and the API reports
success while no data arrives -- so each is asserted on observable behaviour
rather than on the shape of the source.

A dropped subscribe was permanent. `subscribe()` wrote `token_modes[token]`
before any send, so with the socket down it recorded success and returned.
Nothing could retry: that branch tests `max_mode > token_modes[token]` and
never fired again, and the reconnect path replays the SDK's own dict, which
never received the entry. The batched flush had the same hole -- a batch
dropped as "not connected" cleared the queue while `token_modes` still claimed
success. Recovery required a process restart. `token_modes` now means
"confirmed by the broker", written only after a frame is actually sent, and
`_resync_subscriptions()` replays the adapter's *desired* state on every login.

A dead token was treated as a network fault. Every retry was another rejected
handshake; after ten backoff attempts the feed died until restart, with
`token_provider` and `_refresh_auth_token()` sitting unused. Indian broker
tokens roll over daily at ~3 AM IST, so this is a scheduled event, not an edge
case.

Teardown waited out the backoff. The delay was a plain `time.sleep()` of up to
60 seconds, so a disconnect left the thread parked before it could notice.
"""

import importlib
import os
import threading
import time

import pytest
import websocket as ws_module

# websocket_proxy first: its __init__ imports every streaming adapter, so
# importing the mstock adapter directly would re-enter a partially initialised
# module. app.py imports it in this order for the same reason.
import websocket_proxy  # noqa: F401  isort:skip

import broker.mstock.api.mstockwebsocket as ws_mod
from broker.mstock.api.mstockwebsocket import MstockWebSocket
from broker.mstock.streaming.mstock_adapter import MstockWebSocketAdapter
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper


def auth_check(text):
    """The predicate the adapter passes in, unbound from the base adapter."""
    return BaseBrokerWebSocketAdapter.is_auth_error(None, text)


class FakeWs:
    def __init__(self, *args, **kwargs):
        self.sent = []
        self.closed = False

    def send(self, payload):
        import json

        self.sent.append(json.loads(payload))

    def close(self):
        self.closed = True


class FakeApp:
    """Stands in for WebSocketApp; run_forever returns at once."""

    def __init__(self, url, **kwargs):
        self.closed = False

    def run_forever(self, **kwargs):
        return False

    def close(self):
        self.closed = True


# Symbol -> token for the fixture's fake instrument master.
TOKENS = {"S": "22", "T": "33", "A": "22", "B": "33"}


@pytest.fixture
def adapter(monkeypatch):
    """An adapter wired to a fake socket, bypassing initialize() and ZMQ.

    Symbol lookup is stubbed so tests can call the real subscribe() and
    unsubscribe(); writing adapter state directly would let a regression in
    those methods pass unnoticed.
    """
    monkeypatch.setattr(
        SymbolMapper,
        "get_token_from_symbol",
        staticmethod(lambda symbol, exchange: {"token": TOKENS[symbol], "brexchange": exchange}),
    )

    a = MstockWebSocketAdapter.__new__(MstockWebSocketAdapter)
    a.logger = ws_mod.logger
    a.lock = threading.Lock()
    a.subscriptions, a.token_modes, a.token_correlation_ids = {}, {}, {}
    a.subscription_queue, a.batch_timer, a.batch_delay = [], None, 0.05
    a.running, a.connected = True, True
    a.ws_client = MstockWebSocket(auth_token="t")
    a.ws_client.ws = FakeWs()
    a.ws_client._connected = True
    a.ws_client.is_connected = lambda: True
    return a


def want(a, symbol, token=None, mode=3):
    """Subscribe through the real code path."""
    result = a.subscribe(symbol, "NSE", mode=mode)
    assert result["status"] == "success", result
    return result


def subscribe_frames(a):
    return [f for f in a.ws_client.ws.sent if f["action"] == 1]


# --------------------------------------------------------------------------
# a dropped subscribe must stay recoverable
# --------------------------------------------------------------------------
def test_subscribe_with_socket_down_is_recovered_on_login(adapter):
    """THE DEFECT: this was unrecoverable without a process restart."""
    adapter.ws_client.is_connected = lambda: False
    want(adapter, "S")

    # Nothing may claim the broker has it.
    assert adapter.token_modes == {}, "an unsent subscribe must not be confirmed"

    adapter.ws_client.is_connected = lambda: True
    adapter._resync_subscriptions()
    time.sleep(0.25)

    frames = subscribe_frames(adapter)
    assert len(frames) == 1
    assert frames[0]["params"]["tokenList"] == [{"exchangeType": 1, "tokens": ["22"]}]
    assert adapter.token_modes == {"22": 3}


def test_dropped_batch_leaves_the_token_unconfirmed(adapter):
    want(adapter, "S")
    adapter.ws_client.is_connected = lambda: False  # drops inside the window
    time.sleep(0.25)

    assert adapter.ws_client.ws.sent == []
    assert adapter.token_modes == {}, "a dropped batch must not claim success"

    adapter.ws_client.is_connected = lambda: True
    adapter._resync_subscriptions()
    time.sleep(0.25)

    assert len(subscribe_frames(adapter)) == 1
    assert adapter.token_modes == {"22": 3}


def test_refused_send_leaves_the_token_retryable(adapter):
    adapter.ws_client.subscribe_batch = lambda subs, mode: False
    want(adapter, "S")
    time.sleep(0.25)

    assert adapter.token_modes == {}, "a refused send must not be confirmed"


def test_resync_uses_the_highest_requested_mode(adapter):
    want(adapter, "S", mode=1)
    want(adapter, "S", mode=3)
    want(adapter, "T", mode=2)
    time.sleep(0.25)
    adapter.ws_client.ws.sent.clear()

    adapter._resync_subscriptions()
    time.sleep(0.25)

    by_mode = {f["params"]["mode"]: f["params"]["tokenList"] for f in subscribe_frames(adapter)}
    assert by_mode.get(3) == [{"exchangeType": 1, "tokens": ["22"]}]
    assert by_mode.get(2) == [{"exchangeType": 1, "tokens": ["33"]}]
    assert 1 not in by_mode, "the lower mode for token 22 is redundant"


def test_successful_send_confirms_state(adapter):
    want(adapter, "S")
    time.sleep(0.25)

    assert adapter.token_modes == {"22": 3}
    assert adapter.token_correlation_ids == {"22": "mstock_22_3"}


def test_unsubscribe_prunes_the_pending_entry_immediately(adapter):
    """unsubscribe() must drop the queued entry itself, before any flush.

    Asserted synchronously: the flush also revalidates against live
    subscriptions, so waiting for the timer would pass on that second defence
    alone and say nothing about the prune.
    """
    want(adapter, "S")
    assert adapter.subscription_queue != [], "precondition: the subscribe is queued"

    adapter.unsubscribe("S", "NSE", 3)

    assert adapter.subscription_queue == [], "the queued entry must be pruned at once"


def test_unsubscribe_inside_the_window_cancels_the_queued_subscribe(adapter):
    """A subscribe cancelled before the flush must never reach the broker."""
    want(adapter, "S")
    adapter.unsubscribe("S", "NSE", 3)
    time.sleep(0.25)

    assert subscribe_frames(adapter) == []
    assert adapter.subscription_queue == []


def test_unsubscribe_leaves_other_queued_tokens_alone(adapter):
    want(adapter, "A")
    want(adapter, "B")
    adapter.unsubscribe("A", "NSE", 3)
    time.sleep(0.25)

    frames = subscribe_frames(adapter)
    assert len(frames) == 1
    assert frames[0]["params"]["tokenList"] == [{"exchangeType": 1, "tokens": ["33"]}]


# --------------------------------------------------------------------------
# a dead credential must stand down, not retry
# --------------------------------------------------------------------------
def test_dead_token_stops_the_reconnect_loop(monkeypatch):
    """THE DEFECT: this burned ten backoff attempts, then died until restart."""
    monkeypatch.setattr(ws_module, "WebSocketApp", FakeApp)
    c = MstockWebSocket(
        auth_token="same", token_provider=lambda: "same", auth_error_check=auth_check
    )
    c.running, c._generation, c.ws = True, 1, FakeApp("u")
    c.auth_failed = True
    c.auth_failure_reason = "401 Unauthorized"

    thread = threading.Thread(target=c._run_websocket, args=(1, c.ws), daemon=True)
    thread.start()
    thread.join(timeout=5)

    assert thread.is_alive() is False
    assert c._reconnect_attempts == 0, "no backoff budget may be spent on a dead token"
    assert c.running is False


def test_dead_token_retries_once_when_a_fresh_one_exists(monkeypatch):
    """The ~3 AM rollover case: the database may already hold a live token."""
    monkeypatch.setattr(ws_module, "WebSocketApp", FakeApp)
    c = MstockWebSocket(
        auth_token="stale", token_provider=lambda: "fresh", auth_error_check=auth_check
    )
    c.running, c._generation, c.ws = True, 1, FakeApp("u")
    c.auth_failed = True

    thread = threading.Thread(target=c._run_websocket, args=(1, c.ws), daemon=True)
    thread.start()
    time.sleep(0.4)
    try:
        assert c.auth_token == "fresh"
        assert c.auth_failed is False
    finally:
        c.running = False
        c.disconnect_stream()
        thread.join(timeout=6)


@pytest.mark.parametrize(
    "detail,expected",
    [
        ("401 Unauthorized", True),
        ("HTTP 403 Forbidden", True),
        ("token expired", True),
        ("session expired", True),
        ("invalid credentials", True),
        ("Connection reset by peer", False),
        ("timed out", False),
    ],
)
def test_auth_errors_are_recognised(detail, expected):
    c = MstockWebSocket(auth_token="t", auth_error_check=auth_check)
    c._on_ws_error(None, detail)
    assert c.auth_failed is expected


def test_status_code_401_403_on_the_error_object_is_caught():
    class Err(Exception):
        status_code = 403

    c = MstockWebSocket(auth_token="t", auth_error_check=auth_check)
    c._on_ws_error(None, Err("handshake refused"))
    assert c.auth_failed is True


def test_close_frame_carrying_an_auth_reason_flags_it():
    c = MstockWebSocket(auth_token="t", auth_error_check=auth_check)
    c._on_ws_close(None, 1008, "invalid token")
    assert c.auth_failed is True

    ordinary = MstockWebSocket(auth_token="t", auth_error_check=auth_check)
    ordinary._on_ws_close(None, 1006, "abnormal closure")
    assert ordinary.auth_failed is False


def test_successful_login_clears_the_auth_flag():
    c = MstockWebSocket(auth_token="t", auth_error_check=auth_check)
    c.auth_failed, c.auth_failure_reason, c._reconnect_attempts = True, "401", 7
    c.data_callback = lambda q: None

    c._on_ws_message(None, "login ok")

    assert c.auth_failed is False
    assert c.auth_failure_reason is None
    assert c._reconnect_attempts == 0


def test_no_predicate_means_no_auth_verdict():
    """Without a checker nothing may be mistaken for an auth failure."""
    c = MstockWebSocket(auth_token="t")
    c._on_ws_error(None, "401 Unauthorized")
    assert c.auth_failed is False


# --------------------------------------------------------------------------
# teardown must not wait out the backoff
# --------------------------------------------------------------------------
def test_disconnect_during_backoff_is_prompt(monkeypatch):
    """THE DEFECT: teardown blocked for the remaining delay, up to 60s."""
    monkeypatch.setattr(ws_module, "WebSocketApp", FakeApp)
    c = MstockWebSocket(auth_token="t")
    c.running, c._generation, c.ws = True, 1, FakeApp("u")
    c._stop_event.clear()

    thread = threading.Thread(target=c._run_websocket, args=(1, c.ws), daemon=True)
    thread.start()
    time.sleep(0.3)  # now parked in the backoff

    started = time.monotonic()
    c.disconnect_stream()
    thread.join(timeout=5)
    elapsed = time.monotonic() - started

    assert thread.is_alive() is False
    assert elapsed < 1.0, f"teardown took {elapsed:.2f}s; the backoff was not interrupted"


def test_uninterrupted_backoff_still_elapses(monkeypatch):
    """The delay must remain a real delay when nobody asks to stop."""
    monkeypatch.setattr(ws_module, "WebSocketApp", FakeApp)
    c = MstockWebSocket(auth_token="t")
    c.running, c._generation, c.ws = True, 1, FakeApp("u")
    c._stop_event.clear()

    thread = threading.Thread(target=c._run_websocket, args=(1, c.ws), daemon=True)
    thread.start()
    time.sleep(1.0)
    try:
        assert thread.is_alive() is True, "the backoff must not be skipped"
    finally:
        c.disconnect_stream()
        thread.join(timeout=5)


# --------------------------------------------------------------------------
# tuning knobs
# --------------------------------------------------------------------------
def test_defaults_match_the_previous_hardcoded_values():
    assert ws_mod.RECONNECT_MAX_ATTEMPTS == 10
    assert ws_mod.RECONNECT_MAX_DELAY == 60.0
    assert ws_mod.RECONNECT_BASE_DELAY == 2.0
    assert ws_mod.PING_INTERVAL == 20.0
    assert ws_mod.PING_TIMEOUT == 10.0


def test_env_overrides_are_honoured(monkeypatch):
    monkeypatch.setenv("MSTOCK_WS_MAX_RECONNECT_ATTEMPTS", "3")
    monkeypatch.setenv("MSTOCK_WS_RECONNECT_MAX_DELAY", "5")
    monkeypatch.setenv("MSTOCK_WS_PING_INTERVAL", "7.5")

    reloaded = importlib.reload(ws_mod)
    try:
        assert reloaded.RECONNECT_MAX_ATTEMPTS == 3
        assert reloaded.RECONNECT_MAX_DELAY == 5.0
        assert reloaded.PING_INTERVAL == 7.5
    finally:
        for key in (
            "MSTOCK_WS_MAX_RECONNECT_ATTEMPTS",
            "MSTOCK_WS_RECONNECT_MAX_DELAY",
            "MSTOCK_WS_PING_INTERVAL",
        ):
            os.environ.pop(key, None)
        importlib.reload(ws_mod)


def test_a_malformed_knob_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("MSTOCK_WS_PING_TIMEOUT", "not-a-number")

    reloaded = importlib.reload(ws_mod)
    try:
        assert reloaded.PING_TIMEOUT == 10.0
    finally:
        os.environ.pop("MSTOCK_WS_PING_TIMEOUT", None)
        importlib.reload(ws_mod)
