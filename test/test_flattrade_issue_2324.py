"""Regression contracts for GitHub issue #2324 (Flattrade feed never recovers).

Issue #2324 reports the market-data feed staying dead for the rest of the day
after a network drop, with only a restart of app.py bringing it back. Two paths
in the adapter ended the reconnect loop for good:

  1. After Config.MAX_RECONNECT_ATTEMPTS failed connects in a row (about seven
     minutes of outage with the 5/10/20/40/60s waits), _schedule_reconnection()
     set running=False. Nothing ever set it back, and the ConnectionPool still
     reported the feed connected, so a reconnecting client was handed the dead
     one.
  2. An exception inside _attempt_reconnection() before a socket was opened
     (a database error reading the token, for example) was logged and nothing
     scheduled the next attempt, because no socket meant no close callback.
     running stayed True and the feed sat idle with no give-up message.

A network outage must now retry forever at MAX_RECONNECT_DELAY. An auth
rejection still gives up after its own small budget, so a dead token is not
retried against the broker all day.

These tests are self-contained: no socket, port or broker call, and the
reconnect timer is replaced so nothing waits.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _adapter_module():
    """Import the adapter through the package, after websocket_proxy.

    websocket_proxy.__init__ imports every broker adapter and each adapter
    imports websocket_proxy back, so the order matters (same as
    test_flattrade_issue_1965.py).
    """
    pytest.importorskip("sqlalchemy")
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    importlib.import_module("websocket_proxy")
    return importlib.import_module("broker.flattrade.streaming.flattrade_adapter")


class _RecordingTimer:
    """Stands in for threading.Timer: records the delay, never fires."""

    created: list[_RecordingTimer] = []

    def __init__(self, delay, function):
        self.delay = delay
        self.function = function
        self.daemon = False
        self.started = False
        self.cancelled = False
        _RecordingTimer.created.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


class _Client:
    """Stands in for FlattradeWebSocket. connect() reports failure without
    calling the adapter back, the case where no close callback follows."""

    def __init__(self, connects=False):
        self._connects = connects
        self.auth_failed = False
        self.auth_failure_message = ""

    def connect(self):
        return self._connects

    def stop(self):
        pass


@pytest.fixture
def module():
    return _adapter_module()


@pytest.fixture
def adapter(module, monkeypatch):
    """Adapter with connection state only; __init__'s ZeroMQ setup is skipped."""
    _RecordingTimer.created = []
    monkeypatch.setattr(module.threading, "Timer", _RecordingTimer)

    instance = module.FlattradeWebSocketAdapter.__new__(module.FlattradeWebSocketAdapter)
    instance.logger = module.get_logger("flattrade_test_2324")
    instance._setup_adapter()
    instance._setup_market_cache()
    instance._setup_connection_management()
    instance.running = True
    instance.actid = "UID"
    instance.user_id = "user"
    instance.accesstoken = "tok"
    instance.ws_client = None
    return instance


def _pending(adapter):
    timer = adapter._reconnect_timer
    return timer if timer is not None and timer.started and not timer.cancelled else None


class TestALongOutageNeverStopsTheFeed:
    def test_retries_continue_past_the_old_give_up_limit(self, adapter, module):
        config = module.Config

        for attempt in range(config.MAX_RECONNECT_ATTEMPTS * 3):
            adapter.reconnect_attempts = attempt
            adapter._schedule_reconnection()

            assert adapter.running, (
                f"the adapter stopped after {attempt} failed attempts - a network "
                "outage must keep retrying until the broker is reachable"
            )
            assert _pending(adapter) is not None, f"no retry scheduled after attempt {attempt}"

        assert _pending(adapter).delay == config.MAX_RECONNECT_DELAY

    def test_the_delay_is_capped(self, adapter, module):
        config = module.Config
        adapter.reconnect_attempts = 500  # a whole day of 60s retries, and more

        adapter._schedule_reconnection()

        assert _pending(adapter).delay == config.MAX_RECONNECT_DELAY

    def test_a_long_outage_is_reported_once(self, adapter, module, caplog):
        config = module.Config

        with caplog.at_level("ERROR", logger="flattrade_test_2324"):
            for attempt in range(config.MAX_RECONNECT_ATTEMPTS, config.MAX_RECONNECT_ATTEMPTS + 5):
                adapter.reconnect_attempts = attempt
                adapter._schedule_reconnection()

        reports = [r for r in caplog.records if "still disconnected" in r.getMessage()]
        assert len(reports) == 1, f"expected one outage report, got {len(reports)}"
        assert "Maximum reconnection attempts reached" not in caplog.text

    def test_a_reconnect_clears_the_outage_report(self, adapter, module, monkeypatch):
        monkeypatch.setattr(module, "get_auth_token", lambda *a, **k: "fresh")
        monkeypatch.setattr(module, "FlattradeWebSocket", lambda **kw: _Client(connects=True))
        adapter._long_outage_logged = True
        adapter.reconnect_attempts = module.Config.MAX_RECONNECT_ATTEMPTS + 3

        adapter._attempt_reconnection()

        assert adapter.connected
        assert adapter.reconnect_attempts == 0
        assert adapter._long_outage_logged is False
        assert _pending(adapter) is None, "a successful reconnect must not schedule another"


class TestEveryFailedAttemptSchedulesTheNext:
    def test_an_error_before_the_socket_opens(self, adapter, module, monkeypatch):
        def locked(*_a, **_k):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(module, "get_auth_token", locked)

        adapter._attempt_reconnection()

        assert adapter.running
        assert _pending(adapter) is not None, (
            "an error inside the reconnect left nothing scheduled - the feed "
            "would stay down for the day with running still True"
        )

    def test_a_failed_connect_with_no_close_callback(self, adapter, module, monkeypatch):
        monkeypatch.setattr(module, "get_auth_token", lambda *a, **k: "fresh")
        monkeypatch.setattr(module, "FlattradeWebSocket", lambda **kw: _Client(connects=False))

        adapter._attempt_reconnection()

        assert adapter.running
        assert _pending(adapter) is not None

    def test_only_one_attempt_is_ever_pending(self, adapter, module, monkeypatch):
        """The failing socket's close callback schedules a retry while the
        connect is still running; the attempt's own retry must replace it, not
        run beside it."""

        class _ClosingClient(_Client):
            def connect(self):
                adapter._schedule_reconnection()  # the reader thread's on_close
                return False

        monkeypatch.setattr(module, "get_auth_token", lambda *a, **k: "fresh")
        monkeypatch.setattr(module, "FlattradeWebSocket", lambda **kw: _ClosingClient())

        adapter._attempt_reconnection()

        live = [t for t in _RecordingTimer.created if t.started and not t.cancelled]
        assert len(live) == 1, f"{len(live)} reconnects pending at once"

    def test_a_stopped_adapter_schedules_nothing(self, adapter, module, monkeypatch):
        monkeypatch.setattr(module, "get_auth_token", lambda *a, **k: "fresh")
        adapter.running = False

        adapter._attempt_reconnection()

        assert _pending(adapter) is None


class TestAuthFailuresStillGiveUp:
    def test_a_rejected_token_stops_after_its_budget(self, adapter):
        """A dead token must not be retried against the broker all day."""
        adapter.auth_refresh_retries = adapter.max_auth_refresh_retries

        adapter._handle_auth_failure("Invalid Session Key")

        assert adapter.running is False
