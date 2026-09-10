"""Regression contracts for GitHub issue #1965 (Flattrade WebSocket flapping).

Issue #1965 reports the market-data socket closing with code 1000 right after a
successful authentication, over and over, with 5-10 second live-data gaps and
"Heartbeat thread did not terminate within timeout" in between.

The eviction itself is the single-session constraint already documented in
test_flattrade_issue_1806.py: PiConnect permits one session per
{uid, accesstoken}, and #1961 removed OpenAlgo's own second socket (the
order-update adapter now polls REST by default). What #1961 did NOT fix, and
what this file pins, is everything that made each eviction expensive and
endless:

  1. A close left the heartbeat worker asleep on an interval-long wait, so
     _stop_heartbeat() blocked the websocket-client reader thread for the full
     HEARTBEAT_JOIN_TIMEOUT, logged the warning from the issue, and STILL left
     the worker running. That stall sat in front of the adapter's reconnect
     scheduling, i.e. it was pure feed downtime on every drop.
  2. The adapter called ws_client.stop() while holding self.lock, and stop()
     joins the reader thread that runs the adapter's own _on_close, which takes
     that same lock - so teardown and reconnect each waited out a join timeout.

These tests are self-contained: no socket, port or broker call. Threads are
real (the bugs are threading bugs) but bounded and joined.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_websocket_module():
    """Load flattrade_websocket.py by path.

    broker.flattrade.streaming.__init__ imports the adapter, which imports
    websocket_proxy, which imports the adapter back - a cycle that only resolves
    through the package's normal import order. The websocket client itself has
    no such dependency, so load the file directly and keep this test free of the
    proxy stack.
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    path = REPO_ROOT / "broker" / "flattrade" / "streaming" / "flattrade_websocket.py"
    spec = importlib.util.spec_from_file_location("flattrade_websocket_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ws_module = _load_websocket_module()
FlattradeWebSocket = ws_module.FlattradeWebSocket


def _adapter_module():
    """Import the adapter through the package, not by path.

    websocket_proxy.__init__ imports every broker adapter and each adapter
    imports websocket_proxy back, so the adapter module can only be imported
    once websocket_proxy has been imported first - same dance as
    test_flattrade_issue_1806.py.
    """
    pytest.importorskip("sqlalchemy")
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    importlib.import_module("websocket_proxy")
    return importlib.import_module("broker.flattrade.streaming.flattrade_adapter")


@pytest.fixture
def live_client():
    """A client with a running heartbeat worker and no real socket."""
    client = FlattradeWebSocket(user_id="UID", actid="UID", accesstoken="tok")
    client.running = True
    client.connected = True
    client._update_last_message_time()
    client._start_heartbeat()

    # The worker must actually reach its wait() before the assertions run,
    # otherwise a fast exit would pass for the wrong reason.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not client._heartbeat_thread.is_alive():
        time.sleep(0.01)
    assert client._heartbeat_thread.is_alive()

    yield client

    client.running = False
    client.connected = False
    client._stop_heartbeat()


class TestHeartbeatShutdown:
    def test_close_does_not_block_on_the_heartbeat_interval(self, live_client):
        """_on_close must return immediately, not wait out HEARTBEAT_JOIN_TIMEOUT.

        The reader thread runs _on_close, and the adapter's reconnect is
        scheduled from the on_close callback at the end of it. Every second
        spent here is a second of missing market data.
        """
        worker = live_client._heartbeat_thread

        started = time.monotonic()
        live_client._on_close(None, 1000, "goodbye")
        elapsed = time.monotonic() - started

        assert elapsed < FlattradeWebSocket.HEARTBEAT_JOIN_TIMEOUT, (
            f"_on_close blocked for {elapsed:.2f}s - the heartbeat worker was not "
            "woken before the join"
        )
        worker.join(timeout=2)
        assert not worker.is_alive(), "heartbeat worker outlived the socket it belonged to"

    def test_close_does_not_log_the_join_timeout_warning(self, live_client, caplog):
        """The exact warning quoted in issue #1965 must not appear on a close."""
        with caplog.at_level("WARNING", logger="flattrade_websocket"):
            live_client._on_close(None, 1000, "goodbye")

        assert "Heartbeat thread did not terminate within timeout" not in caplog.text

    def test_reconnect_does_not_leave_a_second_worker_heartbeating(self, live_client):
        """One live worker per client, no matter how often the socket flaps.

        The worker used to sleep on the shared self._stop_event, which only
        stop() ever set. A worker orphaned by a close kept the old client's
        `running`/`connected` in scope and resumed heartbeating whenever those
        flipped back to True.
        """
        first_worker = live_client._heartbeat_thread

        live_client._on_close(None, 1000, "goodbye")
        first_worker.join(timeout=2)

        # Reconnect on the same client object, exactly as a flap would.
        live_client.connected = True
        live_client._update_last_message_time()
        live_client._start_heartbeat()
        second_worker = live_client._heartbeat_thread

        assert second_worker is not first_worker
        assert not first_worker.is_alive()
        alive = [t for t in (first_worker, second_worker) if t.is_alive()]
        assert len(alive) == 1, f"{len(alive)} heartbeat workers alive after a reconnect"

    def test_worker_is_bound_to_its_own_stop_event(self, live_client):
        """A worker sleeps on the Event it was started with, not on the attribute.

        _start_heartbeat() rebinds self._heartbeat_stop per connection. If the
        worker read that attribute instead of its own event, a new connection
        would hand a stale worker a fresh, unset event and resurrect it.
        """
        first_worker = live_client._heartbeat_thread
        first_event = live_client._heartbeat_stop

        live_client._on_close(None, 1000, "goodbye")
        assert first_event.is_set()
        first_worker.join(timeout=2)

        live_client.connected = True
        live_client._start_heartbeat()

        assert live_client._heartbeat_stop is not first_event
        assert not live_client._heartbeat_stop.is_set()
        assert not first_worker.is_alive()

    def test_stop_heartbeat_from_the_worker_thread_does_not_join_itself(self):
        """_check_connection_health() can route back into _stop_heartbeat().

        It closes the socket from inside the worker; a self-join would raise
        RuntimeError ("cannot join current thread") and kill the worker's own
        cleanup path.
        """
        client = FlattradeWebSocket(user_id="UID", actid="UID", accesstoken="tok")
        client.running = True
        client.connected = True
        error: list[BaseException] = []

        def call_from_worker():
            try:
                client._stop_heartbeat()
            except BaseException as exc:  # noqa: BLE001 - recorded and re-raised below
                error.append(exc)

        worker = threading.Thread(target=call_from_worker, daemon=True)
        client._heartbeat_thread = worker
        worker.start()
        worker.join(timeout=2)

        assert not worker.is_alive()
        assert not error, f"_stop_heartbeat() raised on its own thread: {error!r}"


class _StubWebSocketClient:
    """Stands in for FlattradeWebSocket, reproducing the one behaviour that
    matters here: stop() joins a reader thread that calls the adapter back.

    The outcome is RECORDED on the instance, never asserted inline. The old
    _attempt_reconnection() ran its whole body inside `try: ... except
    Exception`, which swallows AssertionError - an assert raised from here was
    caught by the code under test and logged as "Reconnection error", so the
    test passed against the very bug it was written to catch.
    """

    JOIN_TIMEOUT = 3

    def __init__(self, adapter):
        self._adapter = adapter
        self.stopped = False
        self.connect_called = False
        self.reader_finished = None  # None = stop() never ran
        self.stop_seconds = None

    def stop(self):
        self.stopped = True
        # The real stop() closes the socket, which makes websocket-client run
        # _on_close on the reader thread, and then joins that thread.
        reader = threading.Thread(
            target=self._adapter._on_close, args=(None, 1000, "goodbye"), daemon=True
        )
        started = time.monotonic()
        reader.start()
        reader.join(timeout=self.JOIN_TIMEOUT)
        self.stop_seconds = time.monotonic() - started
        self.reader_finished = not reader.is_alive()

    def connect(self):
        self.connect_called = True
        return True


@pytest.fixture
def adapter():
    """Adapter instance with the socket/ZMQ plumbing left out.

    __init__ binds a ZeroMQ port through BaseBrokerWebSocketAdapter, which this
    test has no use for, so the connection-management state is set up directly
    on a bare instance.
    """
    module = _adapter_module()
    instance = module.FlattradeWebSocketAdapter.__new__(module.FlattradeWebSocketAdapter)
    instance.logger = module.get_logger("flattrade_test")
    instance._setup_adapter()
    instance._setup_market_cache()
    instance._setup_connection_management()
    instance.running = True
    return instance


class TestAdapterLockIsNotHeldAcrossBlockingCalls:
    def test_disconnect_releases_the_lock_before_stopping_the_client(self, adapter):
        adapter.ws_client = _StubWebSocketClient(adapter)
        adapter.cleanup_zmq = lambda: None

        client = adapter.ws_client

        adapter.disconnect()

        assert client.stopped
        assert client.reader_finished, (
            f"the reader thread could not finish _on_close in {client.stop_seconds:.2f}s - "
            "self.lock is still held across ws_client.stop()"
        )
        assert adapter.ws_client is None
        assert not adapter.running

    def test_reconnect_releases_the_lock_before_stopping_the_old_client(self, adapter, monkeypatch):
        module = _adapter_module()
        old_client = _StubWebSocketClient(adapter)
        adapter.ws_client = old_client
        adapter.actid = "UID"
        adapter.user_id = "user"
        adapter.accesstoken = "tok"

        monkeypatch.setattr(module, "get_auth_token", lambda *a, **k: "fresh")
        new_clients: list[_StubWebSocketClient] = []

        def make_client(**kwargs):
            client = _StubWebSocketClient(adapter)
            new_clients.append(client)
            return client

        monkeypatch.setattr(module, "FlattradeWebSocket", make_client)

        adapter._attempt_reconnection()

        assert old_client.stopped
        assert old_client.reader_finished, (
            f"the reader thread could not finish _on_close in "
            f"{old_client.stop_seconds:.2f}s - self.lock is still held across "
            "ws_client.stop()"
        )
        assert len(new_clients) == 1
        assert new_clients[0].connect_called
        # Published before connect(): _on_open -> _resubscribe_all() sends
        # through self.ws_client on the reader thread.
        assert adapter.ws_client is new_clients[0]
