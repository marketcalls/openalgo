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
    _fetch_orders,
    _fetch_positions,
    _fetch_trades,
    _resolve_auth_token,
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


class TestResolveAuthToken:
    @patch("database.auth_db.get_auth_token")
    def test_uses_freshly_resolved_token_when_available(self, mock_get_auth_token):
        mock_get_auth_token.return_value = "fresh-token"

        token = _resolve_auth_token("user1", "zerodha", "stale-token")

        assert token == "fresh-token"

    @patch("database.auth_db.get_auth_token")
    def test_falls_back_to_cached_token_when_db_returns_none(self, mock_get_auth_token):
        # e.g. a revoked/missing Auth row - resolving fails but must not
        # crash polling, since the cached token might still work for a
        # broker whose REST calls don't hard-require the DB row.
        mock_get_auth_token.return_value = None

        token = _resolve_auth_token("user1", "zerodha", "stale-token")

        assert token == "stale-token"

    @patch("database.auth_db.get_auth_token")
    def test_falls_back_to_cached_token_when_lookup_raises(self, mock_get_auth_token):
        mock_get_auth_token.side_effect = RuntimeError("db unavailable")

        token = _resolve_auth_token("user1", "zerodha", "stale-token")

        assert token == "stale-token"


class TestFetchFunctionsLogFailuresInsteadOfSwallowing:
    @patch("services.order_position_poller_lifecycle._resolve_auth_token")
    @patch("services.orderbook_service.get_orderbook_with_auth")
    def test_fetch_orders_logs_and_returns_empty_on_failure(
        self, mock_get_orderbook, mock_resolve, caplog
    ):
        mock_resolve.return_value = "token"
        mock_get_orderbook.return_value = (
            False,
            {"status": "error", "message": "auth expired"},
            401,
        )

        with caplog.at_level("WARNING"):
            result = _fetch_orders("user1", "zerodha", "token")

        assert result == []
        assert "auth expired" in caplog.text

    @patch("services.order_position_poller_lifecycle._resolve_auth_token")
    @patch("services.tradebook_service.get_tradebook_with_auth")
    def test_fetch_trades_logs_and_returns_empty_on_failure(
        self, mock_get_tradebook, mock_resolve, caplog
    ):
        mock_resolve.return_value = "token"
        mock_get_tradebook.return_value = (
            False,
            {"status": "error", "message": "auth expired"},
            401,
        )

        with caplog.at_level("WARNING"):
            result = _fetch_trades("user1", "zerodha", "token")

        assert result == []
        assert "auth expired" in caplog.text

    @patch("services.order_position_poller_lifecycle._resolve_auth_token")
    @patch("services.positionbook_service.get_positionbook_with_auth")
    def test_fetch_positions_logs_and_returns_empty_on_failure(
        self, mock_get_positionbook, mock_resolve, caplog
    ):
        mock_resolve.return_value = "token"
        mock_get_positionbook.return_value = (
            False,
            {"status": "error", "message": "auth expired"},
            401,
        )

        with caplog.at_level("WARNING"):
            result = _fetch_positions("user1", "zerodha", "token")

        assert result == []
        assert "auth expired" in caplog.text

    @patch("services.order_position_poller_lifecycle._resolve_auth_token")
    @patch("services.positionbook_service.get_positionbook_with_auth")
    def test_fetch_positions_uses_the_resolved_token_not_the_stale_one(
        self, mock_get_positionbook, mock_resolve
    ):
        mock_resolve.return_value = "fresh-token"
        mock_get_positionbook.return_value = (True, {"status": "success", "data": []}, 200)

        _fetch_positions("user1", "zerodha", "stale-token")

        mock_get_positionbook.assert_called_once_with("fresh-token", "zerodha")


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
