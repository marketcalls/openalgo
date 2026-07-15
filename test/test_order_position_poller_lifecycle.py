"""
Tests for services.order_position_poller_lifecycle.

start_poller_for_session / stop_poller_for_session are called from
database.auth_db.upsert_auth, gated by the same token_changed-or-revoke
check that already guards the WS market-data adapter pool teardown - a
2nd-device login resuming an unchanged token must not restart the
poller. Broker REST calls, the poller thread, and ZMQ publishing are all
mocked here; only the wiring/orchestration is under test.
"""

from unittest.mock import MagicMock, patch

import pytest

from services.order_position_poller_lifecycle import (
    start_poller_for_session,
    stop_poller_for_session,
)
from services.order_position_poller_service import (
    DEFAULT_ORDER_POLL_NORMAL_MS,
    DEFAULT_POSITION_POLL_MS,
    get_poller,
    unregister_poller,
)


class TestStartPollerForSession:
    def teardown_method(self):
        unregister_poller("zerodha", "user1")

    @patch("services.order_position_poller_lifecycle.OrderPositionPoller")
    def test_registers_and_starts_a_poller(self, mock_poller_cls):
        mock_poller = MagicMock()
        mock_poller.broker = "zerodha"
        mock_poller.user_id = "user1"
        mock_poller_cls.return_value = mock_poller

        start_poller_for_session("zerodha", "user1", "auth-token-123")

        mock_poller.start.assert_called_once()
        assert get_poller("zerodha", "user1") is mock_poller

    @patch("services.order_position_poller_lifecycle.OrderPositionPoller")
    def test_stops_any_existing_poller_before_starting_a_new_one(self, mock_poller_cls):
        old_poller = MagicMock()
        old_poller.broker = "zerodha"
        old_poller.user_id = "user1"
        new_poller = MagicMock()
        new_poller.broker = "zerodha"
        new_poller.user_id = "user1"
        mock_poller_cls.side_effect = [old_poller, new_poller]

        start_poller_for_session("zerodha", "user1", "auth-token-123")
        start_poller_for_session("zerodha", "user1", "auth-token-456")

        old_poller.stop.assert_called_once()
        assert get_poller("zerodha", "user1") is new_poller


class TestConfigurableIntervals:
    def teardown_method(self):
        unregister_poller("zerodha", "user1")

    @patch("services.order_position_poller_lifecycle.OrderPositionPoller")
    def test_reads_poll_intervals_from_env(self, mock_poller_cls, monkeypatch):
        monkeypatch.setenv("ORDER_POLL_NORMAL_MS", "500")
        monkeypatch.setenv("ORDER_POLL_FAST_MS", "150")
        monkeypatch.setenv("TRADE_POLL_NORMAL_MS", "500")
        monkeypatch.setenv("TRADE_POLL_FAST_MS", "150")
        monkeypatch.setenv("POSITION_POLL_MS", "800")
        monkeypatch.setenv("FAST_MODE_TIMEOUT_SEC", "45")
        mock_poller = MagicMock()
        mock_poller.broker = "zerodha"
        mock_poller.user_id = "user1"
        mock_poller_cls.return_value = mock_poller

        start_poller_for_session("zerodha", "user1", "auth-token-123")

        _, kwargs = mock_poller_cls.call_args
        assert kwargs["order_poll_normal_ms"] == 500
        assert kwargs["order_poll_fast_ms"] == 150
        assert kwargs["trade_poll_normal_ms"] == 500
        assert kwargs["trade_poll_fast_ms"] == 150
        assert kwargs["position_poll_ms"] == 800
        assert kwargs["fast_mode_timeout_sec"] == 45

    @patch("services.order_position_poller_lifecycle.OrderPositionPoller")
    def test_falls_back_to_defaults_when_env_unset(self, mock_poller_cls, monkeypatch):
        for var in (
            "ORDER_POLL_NORMAL_MS",
            "ORDER_POLL_FAST_MS",
            "TRADE_POLL_NORMAL_MS",
            "TRADE_POLL_FAST_MS",
            "POSITION_POLL_MS",
            "FAST_MODE_TIMEOUT_SEC",
        ):
            monkeypatch.delenv(var, raising=False)
        mock_poller = MagicMock()
        mock_poller.broker = "zerodha"
        mock_poller.user_id = "user1"
        mock_poller_cls.return_value = mock_poller

        start_poller_for_session("zerodha", "user1", "auth-token-123")

        _, kwargs = mock_poller_cls.call_args
        assert kwargs["order_poll_normal_ms"] == DEFAULT_ORDER_POLL_NORMAL_MS
        assert kwargs["position_poll_ms"] == DEFAULT_POSITION_POLL_MS


class TestStopPollerForSession:
    def teardown_method(self):
        unregister_poller("zerodha", "user1")

    @patch("services.order_position_poller_lifecycle.OrderPositionPoller")
    def test_stops_and_unregisters_the_poller(self, mock_poller_cls):
        mock_poller = MagicMock()
        mock_poller.broker = "zerodha"
        mock_poller.user_id = "user1"
        mock_poller_cls.return_value = mock_poller
        start_poller_for_session("zerodha", "user1", "auth-token-123")

        stop_poller_for_session("zerodha", "user1")

        mock_poller.stop.assert_called_once()
        assert get_poller("zerodha", "user1") is None

    def test_stopping_a_session_with_no_poller_is_a_noop(self):
        stop_poller_for_session("dhan", "user2")  # must not raise
