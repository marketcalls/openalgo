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


def wait_until(predicate, timeout=5.0, interval=0.01):
    """Poll until predicate() is truthy; return its final value.

    Almost everything here is completed by a background thread or a 0.05s
    batch timer, so a fixed sleep is a bet on the scheduler. Waiting on the
    state the test is about to assert makes the timeout the only slow path and
    leaves the assertion itself unchanged: a genuine regression still fails on
    the real value rather than on a timing message.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


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
    a.send_retries, a.max_send_retries = {}, 3
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


def batch_flushed(a):
    """True once the armed batch timer has fired and drained the queue.

    _process_batch_subscriptions() clears batch_timer under the lock as its
    first act, so this is the observable edge the negative tests need: it says
    the flush ran, which is the only way "nothing was sent" means anything.
    """
    return a.batch_timer is None


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
    wait_until(lambda: adapter.token_modes)

    frames = subscribe_frames(adapter)
    assert len(frames) == 1
    assert frames[0]["params"]["tokenList"] == [{"exchangeType": 1, "tokens": ["22"]}]
    assert adapter.token_modes == {"22": 3}


def test_dropped_batch_leaves_the_token_unconfirmed(adapter):
    want(adapter, "S")
    adapter.ws_client.is_connected = lambda: False  # drops inside the window
    assert wait_until(lambda: batch_flushed(adapter)), "the batch timer never fired"

    assert adapter.ws_client.ws.sent == []
    assert adapter.token_modes == {}, "a dropped batch must not claim success"

    adapter.ws_client.is_connected = lambda: True
    adapter._resync_subscriptions()
    wait_until(lambda: adapter.token_modes)

    assert len(subscribe_frames(adapter)) == 1
    assert adapter.token_modes == {"22": 3}


def test_refused_send_leaves_the_token_retryable(adapter):
    refused = []

    def refuse(subs, mode):
        refused.append((subs, mode))
        return False

    adapter.ws_client.subscribe_batch = refuse
    want(adapter, "S")
    # The refusal itself is the wait target: batch_flushed() turns True before
    # the send is even attempted, so it would prove nothing here.
    assert wait_until(lambda: refused), "the batch was never offered to the broker"

    assert adapter.token_modes == {}, "a refused send must not be confirmed"


def test_a_permanently_refused_send_stops_retrying(adapter):
    """A refused send is retried, but must not re-arm the timer forever.

    Requeuing without a budget spun the batch timer every batch_delay and
    logged a warning each time, for as long as the socket kept refusing while
    still reporting itself connected.
    """
    attempts = []

    def always_refuse(subs, mode):
        attempts.append(mode)
        return False

    adapter.ws_client.subscribe_batch = always_refuse

    want(adapter, "S")
    # Wait on the attempt count, not on the queue draining: the flush clears
    # the queue and the timer as its first act, so a poll landing in that gap
    # would return before the send was even recorded.
    wait_until(lambda: len(attempts) == 1 + adapter.max_send_retries)

    assert len(attempts) == 1 + adapter.max_send_retries, "one send plus its retry budget"
    assert adapter.batch_timer is None, "the timer must not stay armed"
    assert adapter.subscription_queue == []
    assert adapter.token_modes == {}, "left unconfirmed so the resync recovers it"


def test_a_transient_refusal_still_recovers(adapter):
    """The budget must not cost recovery from a couple of failed sends."""
    calls = {"n": 0}

    def flaky(subs, mode):
        calls["n"] += 1
        return calls["n"] > 2

    adapter.ws_client.subscribe_batch = flaky

    want(adapter, "S")
    wait_until(lambda: adapter.token_modes)

    assert adapter.token_modes == {"22": 3}
    assert adapter.send_retries == {}, "the budget resets once the send lands"


def test_resync_uses_the_highest_requested_mode(adapter):
    want(adapter, "S", mode=1)
    want(adapter, "S", mode=3)
    want(adapter, "T", mode=2)
    assert wait_until(lambda: adapter.token_modes == {"22": 3, "33": 2}), (
        f"the initial subscribes never settled: {adapter.token_modes}"
    )
    adapter.ws_client.ws.sent.clear()

    adapter._resync_subscriptions()
    wait_until(lambda: adapter.token_modes == {"22": 3, "33": 2})

    by_mode = {f["params"]["mode"]: f["params"]["tokenList"] for f in subscribe_frames(adapter)}
    assert by_mode.get(3) == [{"exchangeType": 1, "tokens": ["22"]}]
    assert by_mode.get(2) == [{"exchangeType": 1, "tokens": ["33"]}]
    assert 1 not in by_mode, "the lower mode for token 22 is redundant"


def test_successful_send_confirms_state(adapter):
    want(adapter, "S")
    wait_until(lambda: adapter.token_modes)

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
    assert wait_until(lambda: batch_flushed(adapter)), "the batch timer never fired"

    assert subscribe_frames(adapter) == []
    assert adapter.subscription_queue == []


def test_unsubscribe_leaves_other_queued_tokens_alone(adapter):
    want(adapter, "A")
    want(adapter, "B")
    adapter.unsubscribe("A", "NSE", 3)
    wait_until(lambda: subscribe_frames(adapter))

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
    # auth_failed is cleared after _refresh_auth_token() has swapped the token,
    # so it is the later of the two writes and safe to wait on.
    wait_until(lambda: c.auth_failed is False)
    try:
        assert c.auth_token == "fresh"
        assert c.auth_failed is False
    finally:
        c.running = False
        c.disconnect_stream()
        thread.join(timeout=6)


def test_every_terminal_exit_reports_the_feed_dead(monkeypatch):
    """THE DEFECT: only the auth path told the owner.

    A client whose reconnect budget is spent is just as dead as one holding an
    expired credential - the thread exits and nothing reconnects - but the
    adapter kept reporting connected=True, so the proxy served a cached feed
    that could never produce another tick.
    """
    monkeypatch.setattr(ws_module, "WebSocketApp", FakeApp)
    monkeypatch.setattr(ws_mod, "RECONNECT_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(ws_mod, "RECONNECT_BASE_DELAY", 0.01)
    monkeypatch.setattr(ws_mod, "RECONNECT_MAX_DELAY", 0.02)

    for label, arm in (
        ("auth stand-down", lambda c: setattr(c, "auth_failed", True)),
        ("max attempts", lambda c: None),
    ):
        fired = []
        c = MstockWebSocket(auth_token="t", token_provider=lambda: "t", auth_error_check=auth_check)
        # Bind per iteration: a bare closure would capture the loop's name.
        c.auth_failure_callback = lambda seen=fired: seen.append(1)
        c.running, c._generation, c.ws = True, 1, FakeApp("u")
        c._stop_event.clear()
        c._feed_dead = False
        arm(c)

        thread = threading.Thread(target=c._run_websocket, args=(1, c.ws), daemon=True)
        thread.start()
        thread.join(timeout=10)

        assert thread.is_alive() is False, label
        assert fired == [1], f"{label}: the owner must be told exactly once"
        assert c._connected is False, label


def test_a_retiring_generation_cannot_kill_the_live_stream():
    """THE DEFECT: a worker retiring after a restart tore down the new feed.

    connect_stream() resets _feed_dead, so the old worker's terminal path
    passed the idempotency guard and cleared the flags - and fired the
    callback - of the connection that had just replaced it.
    """
    fired = []
    c = MstockWebSocket(auth_token="t")
    c.auth_failure_callback = lambda: fired.append(1)
    c._generation = 2  # a newer connect_stream() has already run
    c.running, c._connected, c._feed_dead = True, True, False

    c._notify_feed_dead("generation 1 gave up", generation=1)

    assert c.running is True, "the live stream must survive an old worker retiring"
    assert c._connected is True
    assert fired == []

    c._notify_feed_dead("generation 2 gave up", generation=2)
    assert c.running is False, "the current generation is still honoured"
    assert fired == [1]


def test_a_feed_that_dies_during_connect_leaves_the_adapter_disconnected(monkeypatch, adapter):
    """connect() set connected=True after starting the thread, so a connection
    that failed outright had its False overwritten and the proxy cached a feed
    whose worker had already exited."""

    class DyingApp:
        def __init__(self, url, **kwargs):
            self.closed = False

        def run_forever(self, **kwargs):
            return False

        def close(self):
            self.closed = True

    monkeypatch.setattr(ws_module, "WebSocketApp", DyingApp)
    monkeypatch.setattr(ws_mod, "RECONNECT_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(ws_mod, "RECONNECT_BASE_DELAY", 0.01)
    monkeypatch.setattr(ws_mod, "RECONNECT_MAX_DELAY", 0.02)

    adapter.ws_client = MstockWebSocket(auth_token="t")
    adapter.running = True
    adapter.connect()
    wait_until(lambda: adapter.ws_client.running is False)

    assert adapter.connected is False, "a dead feed must not be advertised as connected"


def test_unsubscribing_restores_the_retry_budget(adapter):
    """An exhausted token came back already spent, so a later subscribe got
    its one send and no retry, and the dict grew an entry per token seen."""
    attempts = []

    def refuse(subs, mode):
        attempts.append(mode)
        return False

    adapter.ws_client.subscribe_batch = refuse

    want(adapter, "S")
    wait_until(lambda: len(attempts) == 1 + adapter.max_send_retries)
    assert adapter.send_retries == {"22": 3}

    adapter.unsubscribe("S", "NSE", 3)
    assert adapter.send_retries == {}, "the budget goes with the subscription"

    attempts.clear()
    want(adapter, "S")
    wait_until(lambda: len(attempts) == 1 + adapter.max_send_retries)
    assert len(attempts) == 1 + adapter.max_send_retries, "a fresh budget, not a spent one"


def test_a_deliberate_disconnect_is_not_a_dead_feed(monkeypatch):
    """Teardown is not a failure; the owner already knows it asked to stop."""
    monkeypatch.setattr(ws_module, "WebSocketApp", FakeApp)
    monkeypatch.setattr(ws_mod, "RECONNECT_BASE_DELAY", 2.0)
    monkeypatch.setattr(ws_mod, "RECONNECT_MAX_DELAY", 5.0)

    fired = []
    c = MstockWebSocket(auth_token="t")
    c.auth_failure_callback = lambda: fired.append(1)
    c.running, c._generation, c.ws = True, 1, FakeApp("u")
    c._stop_event.clear()
    c._feed_dead = False

    thread = threading.Thread(target=c._run_websocket, args=(1, c.ws), daemon=True)
    thread.start()
    wait_until(lambda: c._reconnect_attempts >= 1)
    c.disconnect_stream()
    thread.join(timeout=5)

    assert fired == [], "a requested teardown must not look like a dead feed"


def test_the_dead_feed_notice_is_idempotent():
    fired = []
    c = MstockWebSocket(auth_token="t")
    c.auth_failure_callback = lambda: fired.append(1)

    c._notify_feed_dead("first")
    c._notify_feed_dead("second")

    assert fired == [1]


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
    # The attempt counter is bumped immediately before the backoff wait, so it
    # is the signal that the thread has reached it. The delay is 3s, far longer
    # than the bound below, so a prompt teardown is still the only way to pass.
    assert wait_until(lambda: c._reconnect_attempts >= 1), "never entered the backoff"

    started = time.monotonic()
    c.disconnect_stream()
    thread.join(timeout=5)
    elapsed = time.monotonic() - started

    assert thread.is_alive() is False
    assert elapsed < 2.0, f"teardown took {elapsed:.2f}s; the backoff was not interrupted"


def test_uninterrupted_backoff_still_elapses(monkeypatch):
    """The delay must remain a real delay when nobody asks to stop."""
    monkeypatch.setattr(ws_module, "WebSocketApp", FakeApp)
    c = MstockWebSocket(auth_token="t")
    c.running, c._generation, c.ws = True, 1, FakeApp("u")
    c._stop_event.clear()

    thread = threading.Thread(target=c._run_websocket, args=(1, c.ws), daemon=True)
    thread.start()
    # A real sleep on purpose: the assertion is that the thread is STILL parked
    # after it, so there is no state to poll for. Polling for the negative would
    # test nothing. The first backoff is 3s, so 1.0s leaves ample margin.
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


# --------------------------------------------------------------------------
# the session must become usable without an acknowledgement
# --------------------------------------------------------------------------
class SilentBroker:
    """mStock as observed: accepts LOGIN and never sends a text reply."""

    def __init__(self, url, on_open=None, on_message=None, on_error=None, on_close=None):
        self.on_open, self.on_message = on_open, on_message
        self.sent = []
        self.closed = False

    def run_forever(self, **kwargs):
        self.on_open(self)
        while not self.closed:
            time.sleep(0.01)
        return False

    def send(self, payload):
        self.sent.append(payload)

    def close(self):
        self.closed = True


def test_session_is_usable_once_login_is_sent(monkeypatch):
    """THE DEFECT: readiness waited on an ACK mStock does not send.

    The Market Data WebSocket page documents no reply to LOGIN and states that
    every response is binary, so is_connected() stayed False for the life of
    the connection: every subscribe was held locally and no tick ever arrived,
    which is the "LTP shows ---" symptom on /websocket/test.
    """
    monkeypatch.setattr(ws_module, "WebSocketApp", SilentBroker)
    c = MstockWebSocket(auth_token="tok")

    c.connect_stream(lambda quote: None)
    try:
        wait_until(c.is_connected)
        assert c.is_connected() is True, "no ACK arrives; LOGIN itself is the handshake"
        assert any(p.startswith("LOGIN:") for p in c.ws.sent)
    finally:
        c.disconnect_stream()


def test_a_failed_login_send_leaves_the_session_unusable(monkeypatch):
    """Without LOGIN the broker drops the socket, so do not subscribe into it."""

    class RefusingBroker(SilentBroker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Records that LOGIN was actually attempted, so the assertion below
            # cannot pass simply by running before the client got that far.
            self.attempted = threading.Event()

        def send(self, payload):
            self.attempted.set()
            raise OSError("broken pipe")

    monkeypatch.setattr(ws_module, "WebSocketApp", RefusingBroker)
    c = MstockWebSocket(auth_token="tok")

    c.connect_stream(lambda quote: None)
    try:
        assert wait_until(c.ws.attempted.is_set), "LOGIN was never attempted"
        assert c.is_connected() is False
    finally:
        c.disconnect_stream()


def test_resync_runs_once_per_connection(monkeypatch):
    """Marking the session live is idempotent; later frames must not re-resync."""
    monkeypatch.setattr(ws_module, "WebSocketApp", SilentBroker)
    calls = []
    c = MstockWebSocket(auth_token="tok")

    c.connect_stream(lambda quote: None, resync_callback=lambda: calls.append(1))
    try:
        assert wait_until(lambda: calls), "the first resync never fired"
        c._on_ws_message(c.ws, "some text")
        c._on_ws_message(c.ws, b"\x00" * 51)
        assert calls == [1], "resync must fire once, not on every frame"
    finally:
        c.disconnect_stream()
