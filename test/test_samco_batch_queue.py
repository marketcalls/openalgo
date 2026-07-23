"""Unit tests for the Samco WebSocket batch subscription and auth-fail short-circuit."""

import os
import sys
import time
from unittest.mock import MagicMock, patch

# Make the project root importable when pytest runs from the test/ directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The auth database requires these at import time.
os.environ.setdefault("API_KEY_PEPPER", "a" * 64)
os.environ.setdefault("DATABASE_URL", "sqlite:///test_openalgo.db")

# Importing the package first bootstraps the broker adapters cleanly.
import websocket_proxy  # noqa: E402
from broker.samco.streaming.samco_adapter import SamcoWebSocketAdapter  # noqa: E402
from broker.samco.streaming.samcoWebSocket import SamcoWebSocket  # noqa: E402


def test_batch_subscriptions_are_queued_and_flushed():
    """Multiple subscribe() calls should be coalesced into one batched request."""
    from broker.samco.streaming import samco_adapter as adapter_module

    adapter = SamcoWebSocketAdapter()
    adapter.connected = True
    adapter.ws_client = MagicMock()
    adapter.user_id = "test_user"

    # Reduce batch delay so the test runs fast.
    adapter.batch_delay = 0.05

    with patch.object(
        adapter_module.SymbolMapper, "get_token_from_symbol"
    ) as mock_get_token:
        mock_get_token.return_value = {"token": "12345", "brexchange": "NSE"}
        adapter.subscribe("RELIANCE", "NSE", mode=2)
        adapter.subscribe("TCS", "NSE", mode=2)
        adapter.subscribe("GOLD", "MCX", mode=1)

    assert len(adapter.subscription_queue) == 3
    assert adapter.batch_timer is not None

    # Wait for the timer to fire.
    time.sleep(adapter.batch_delay + 0.05)

    assert len(adapter.subscription_queue) == 0
    assert adapter.ws_client.subscribe.call_count >= 1

    # The first call should batch the NSE symbols in mode 2.
    first_call = adapter.ws_client.subscribe.call_args_list[0]
    _, mode, token_list = first_call.args
    assert mode == 2
    exchanges = {g["exchangeType"]: g["tokens"] for g in token_list}
    assert "NSE" in exchanges
    assert set(exchanges["NSE"]) == {"12345"}


def test_auth_error_stops_reconnect_from_ws_error():
    """A 401/403 error from the WebSocket should set the auth-failed flag."""
    ws = SamcoWebSocket(session_token="dummy", user_id="test_user")
    ws.running = True
    ws.connected = True

    with patch.object(ws, "_close_websocket") as mock_close, patch.object(
        ws, "_stop_heartbeat"
    ) as mock_stop:
        ws._on_error(None, "HTTP 401 unauthorized")

    assert ws._auth_failed is True
    assert ws.running is False
    mock_close.assert_called_once()
    mock_stop.assert_called_once()


def test_auth_error_stops_reconnect_from_message():
    """An auth failure message should short-circuit further processing."""
    ws = SamcoWebSocket(session_token="dummy", user_id="test_user")
    ws.running = True
    ws.connected = True

    with patch.object(ws, "_close_websocket") as mock_close, patch.object(
        ws, "_stop_heartbeat"
    ) as mock_stop:
        ws._on_message(None, '{"status":"failed","message":"unauthenticated"}')

    assert ws._auth_failed is True
    assert ws.running is False
    mock_close.assert_called_once()
    mock_stop.assert_called_once()


def test_auth_error_stops_reconnect_from_close_reason():
    """A close reason containing an auth error should set the auth-failed flag."""
    ws = SamcoWebSocket(session_token="dummy", user_id="test_user")
    ws.running = True
    ws.connected = True

    with patch.object(ws, "_stop_heartbeat") as mock_stop:
        ws._on_close(None, close_status_code=403, close_msg="forbidden")

    assert ws._auth_failed is True
    assert ws.running is False
    mock_stop.assert_called_once()


def test_adapter_on_close_does_not_reconnect_after_auth_failure():
    """Once the client flags an auth failure, the adapter must not reconnect."""
    adapter = SamcoWebSocketAdapter()
    adapter.running = True
    adapter.ws_client = MagicMock()
    adapter.ws_client._auth_failed = True

    with patch.object(adapter, "_connect_with_retry") as mock_reconnect:
        adapter._on_close(None)

    assert adapter.running is False
    mock_reconnect.assert_not_called()
