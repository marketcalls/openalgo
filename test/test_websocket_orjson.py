"""
Tests for orjson integration in OpenAlgo's WebSocket proxy and streaming handlers.
"""

import json
import orjson
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.connection_manager import SharedZmqPublisher
from websocket_proxy.server import WebSocketProxy
from services.websocket_client import WebSocketClient


class DummyAdapter(BaseBrokerWebSocketAdapter):
    """Minimal concrete adapter implementation for testing."""
    def initialize(self):
        return True

    def connect(self):
        return True

    def disconnect(self):
        return True

    def subscribe(self, symbol, exchange, mode, depth_level=None):
        return {"status": "success"}

    def unsubscribe(self, symbol, exchange, mode):
        return {"status": "success"}


def test_base_adapter_publishes_orjson_bytes():
    """Verify that BaseBrokerWebSocketAdapter.publish sends valid orjson bytes via ZMQ."""
    adapter = DummyAdapter()
    adapter.socket = MagicMock()
    adapter._uses_shared_zmq = False

    payload = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "ltp": 2500.50,
        "volume": 100000,
        "mode": "LTP",
    }

    adapter.publish_market_data("NSE_RELIANCE_LTP", payload)

    adapter.socket.send_multipart.assert_called_once()
    topic_bytes, data_bytes = adapter.socket.send_multipart.call_args[0][0]

    assert topic_bytes == b"NSE_RELIANCE_LTP"
    assert isinstance(data_bytes, bytes)
    assert orjson.loads(data_bytes) == payload


def test_shared_zmq_publisher_publishes_orjson_bytes():
    """Verify that SharedZmqPublisher.publish sends valid orjson bytes."""
    publisher = SharedZmqPublisher()
    publisher.socket = MagicMock()
    publisher._connected = True

    payload = {
        "symbol": "INFY",
        "exchange": "NSE",
        "ltp": 1600.25,
        "mode": "Quote",
    }

    publisher.publish("NSE_INFY_QUOTE", payload)

    publisher.socket.send_multipart.assert_called_once()
    topic_bytes, data_bytes = publisher.socket.send_multipart.call_args[0][0]

    assert topic_bytes == b"NSE_INFY_QUOTE"
    assert isinstance(data_bytes, bytes)
    assert orjson.loads(data_bytes) == payload


@pytest.mark.anyio
async def test_server_send_message_encodes_with_orjson():
    """Verify that WebSocketProxy.send_message sends text frames encoded via orjson."""
    server = WebSocketProxy()
    mock_ws = AsyncMock()
    client_id = "client_1"
    server.clients[client_id] = mock_ws

    msg = {
        "type": "market_data",
        "symbol": "TCS",
        "exchange": "NSE",
        "ltp": 3500.0,
    }

    await server.send_message(client_id, msg)

    mock_ws.send.assert_called_once()
    sent_text = mock_ws.send.call_args[0][0]
    assert isinstance(sent_text, str)
    assert orjson.loads(sent_text) == msg


@pytest.mark.anyio
async def test_server_process_client_message_with_orjson():
    """Verify that WebSocketProxy.process_client_message parses incoming client messages."""
    server = WebSocketProxy()
    server.handle_ping = AsyncMock()

    client_id = "client_1"
    raw_message = orjson.dumps({"action": "ping", "data": 12345}).decode("utf-8")

    await server.process_client_message(client_id, raw_message)
    server.handle_ping.assert_called_once_with(client_id, {"action": "ping", "data": 12345})


@pytest.mark.anyio
async def test_server_process_invalid_json_does_not_crash():
    """Verify that invalid JSON produces a clean error response without crashing."""
    server = WebSocketProxy()
    server.send_error = AsyncMock()

    client_id = "client_1"
    await server.process_client_message(client_id, "{malformed: json")
    server.send_error.assert_called_once_with(client_id, "INVALID_JSON", "Invalid JSON message")


@pytest.mark.anyio
async def test_websocket_client_handle_message_orjson():
    """Verify that internal WebSocketClient parses incoming messages using orjson."""
    client = WebSocketClient(api_key="dummy_api_key")
    received = []

    client.register_callback("market_data", lambda data: received.append(data))

    market_msg = orjson.dumps({
        "type": "market_data",
        "symbol": "SBIN",
        "exchange": "NSE",
        "ltp": 600.0,
    }).decode("utf-8")

    await client._handle_message(market_msg)

    assert len(received) == 1
    assert received[0]["symbol"] == "SBIN"
    assert received[0]["ltp"] == 600.0


@pytest.mark.anyio
async def test_websocket_client_handle_invalid_json():
    """Verify that invalid JSON in WebSocketClient is logged and handled without raising uncaught exceptions."""
    client = WebSocketClient(api_key="dummy_api_key")
    # Should not raise exception
    await client._handle_message("invalid json content")


def test_orjson_equivalence_and_speed():
    """Verify serialization equivalence between orjson and json on typical full depth market payloads."""
    depth_payload = {
        "symbol": "NIFTY26FEB24000CE",
        "exchange": "NFO",
        "mode": 3,
        "data": {
            "ltp": 142.50,
            "ltq": 75,
            "ltt": 1723875600,
            "vtt": 2500000,
            "open": 110.0,
            "high": 165.0,
            "low": 95.0,
            "close": 105.0,
            "bids": [{"price": 142.45, "qty": 150, "orders": 2} for _ in range(5)],
            "asks": [{"price": 142.55, "qty": 225, "orders": 3} for _ in range(5)],
            "oi": 1540000,
            "poi": 1420000,
        },
    }

    # Verify identical data representation
    orjson_bytes = orjson.dumps(depth_payload)
    decoded_dict = orjson.loads(orjson_bytes)
    assert decoded_dict == depth_payload

    # Verify json.loads and orjson.loads match
    std_json_str = json.dumps(depth_payload)
    assert orjson.loads(std_json_str) == json.loads(std_json_str)
