# broker/upstox/streaming/upstox_client.py
"""
Synchronous Upstox V3 WebSocket client using websocket-client library.

Uses the same sync pattern as Angel/Dhan adapters to avoid asyncio event loop
conflicts with eventlet in gunicorn deployments.
"""
import json
import logging
import ssl
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import requests
import websocket
from google.protobuf.json_format import MessageToDict

from . import MarketDataFeedV3_pb2


class UpstoxWebSocketClient:
    """
    Upstox V3 WebSocket client implementation (synchronous).

    Uses websocket-client (sync) instead of websockets (async) to avoid
    creating a second asyncio event loop which conflicts with eventlet
    in gunicorn+eventlet deployments.
    """

    API_URL = "https://api.upstox.com/v3"
    AUTH_ENDPOINT = f"{API_URL}/feed/market-data-feed/authorize"

    # HTTP request timeout
    HTTP_TIMEOUT = 10

    # Health check settings - detect silent stalls
    HEALTH_CHECK_INTERVAL = 30
    DATA_TIMEOUT = 90

    def __init__(self, auth_token: str):
        self.auth_token = auth_token
        self.ws: websocket.WebSocketApp | None = None
        self.logger = logging.getLogger("upstox_websocket")
        self._subscriptions: set = set()
        self.running = False
        self._ws_thread: threading.Thread | None = None
        self._health_check_thread: threading.Thread | None = None
        self._last_message_time: float | None = None
        self._connected = False
        self.callbacks: dict[str, Callable | None] = {
            "on_connect": None,
            "on_message": None,
            "on_error": None,
            "on_close": None,
        }
        self._reconnect_config = {"max_attempts": 5, "base_delay": 2, "max_delay": 30}

        # SSL context
        self._ssl_context = ssl.create_default_context()
        self._ssl_context.check_hostname = False
        self._ssl_context.verify_mode = ssl.CERT_NONE

    def connect(self) -> bool:
        """Establish WebSocket connection in a background thread.

        Returns immediately after starting the connection thread (same as Angel).
        The actual connection happens asynchronously - do NOT block with wait()
        as that causes eventlet timeout issues in gunicorn+eventlet deployments.
        """
        if not self._is_valid_auth_token():
            self._trigger_error("Invalid or missing access token")
            return False

        ws_url = self._get_websocket_url()
        if not ws_url:
            self._trigger_error("Failed to get WebSocket URL")
            return False

        self.running = True

        # Create WebSocketApp with callbacks
        # Use on_message only (not on_data) — on_message receives both
        # text (str) and binary (bytes) messages reliably
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
        )

        # Run WebSocket in a daemon thread (same pattern as Angel/Dhan)
        # Return immediately - connection happens in background
        self._ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self._ws_thread.start()

        self.logger.info("Upstox WebSocket connection thread started")
        return True

    def _run_websocket(self):
        """Run the WebSocket connection with reconnection logic"""
        self._reconnect_attempts = 0
        while self.running:
            try:
                # Enable keepalive pings (same as Dhan/Flattrade which work reliably).
                # websocket-client needs explicit pings to keep the connection alive,
                # unlike the async websockets library which has internal keepalive.
                self.ws.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_NONE},
                    ping_interval=30,
                    ping_timeout=10,
                )
            except Exception as e:
                self.logger.error(f"WebSocket run_forever error: {e}")

            self._connected = False

            if not self.running:
                break

            self._reconnect_attempts += 1
            if self._reconnect_attempts >= self._reconnect_config["max_attempts"]:
                self.logger.error("Max reconnect attempts reached")
                self._trigger_error("Max reconnect attempts reached")
                break

            delay = self._calculate_backoff_delay(self._reconnect_attempts)
            self.logger.info(f"Reconnecting in {delay}s (attempt {self._reconnect_attempts})...")
            time.sleep(delay)

            # Re-fetch WebSocket URL for reconnection
            ws_url = self._get_websocket_url()
            if ws_url:
                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_open=self._on_ws_open,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close,
                )

    def subscribe(self, instrument_keys: list[str], mode: str = "ltpc") -> bool:
        """Subscribe to market data for given instrument keys"""
        if not self._connected or not self.ws:
            self.logger.error("WebSocket not connected")
            return False

        try:
            message = self._create_subscription_message(instrument_keys, mode, "sub")
            # Send as binary frame — original async code used:
            # await websocket.send(json.dumps(msg).encode("utf-8"))
            self.ws.send(json.dumps(message).encode("utf-8"), opcode=websocket.ABNF.OPCODE_BINARY)
            self._subscriptions.update(instrument_keys)
            self.logger.info(f"Subscribed to {len(instrument_keys)} instruments in {mode} mode")
            return True
        except Exception as e:
            self.logger.error(f"Subscribe error: {e}")
            return False

    def unsubscribe(self, instrument_keys: list[str]) -> bool:
        """Unsubscribe from market data"""
        if not self._connected or not self.ws:
            return False

        try:
            message = self._create_subscription_message(instrument_keys, method="unsub")
            self.ws.send(json.dumps(message).encode("utf-8"), opcode=websocket.ABNF.OPCODE_BINARY)
            self._subscriptions.difference_update(instrument_keys)
            self.logger.info(f"Unsubscribed from {len(instrument_keys)} instruments")
            return True
        except Exception as e:
            self.logger.error(f"Unsubscribe error: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from WebSocket.

        Sets flags and closes the socket — does NOT join threads.
        Thread.join() under eventlet causes Timeout exceptions because
        eventlet converts joins to green waits. Daemon threads will
        terminate naturally when the flags are set.
        """
        self.running = False
        self._connected = False

        # Close WebSocket — this will cause run_forever() to return
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                self.logger.debug(f"Error closing WebSocket: {e}")

        # Don't join threads — daemon threads will stop on their own
        # join() causes eventlet.timeout.Timeout in gunicorn+eventlet
        self._health_check_thread = None
        self._ws_thread = None

        self._subscriptions.clear()
        self._last_message_time = None
        self.logger.info("Disconnected from WebSocket")

    # WebSocket callbacks
    def _on_ws_open(self, ws):
        """Called when WebSocket connection is opened"""
        self.logger.info("Upstox WebSocket connection opened")
        self._connected = True
        self._reconnect_attempts = 0
        self._last_message_time = time.time()

        # Start health check thread
        self._start_health_check()

        # Notify adapter
        if self.callbacks.get("on_connect"):
            self.callbacks["on_connect"]()

    def _on_ws_message(self, ws, message):
        """Called for both binary (protobuf) and text (JSON) messages"""
        self._last_message_time = time.time()
        self.logger.debug(f"Received message: type={type(message).__name__}, size={len(message) if message else 0}")
        if isinstance(message, bytes):
            self._process_binary_message(message)
        else:
            self._process_text_message(message)

    def _on_ws_error(self, ws, error):
        """Called on WebSocket error"""
        self.logger.error(f"WebSocket error: {error}")
        self._connected = False
        self._trigger_error(str(error))

    def _on_ws_close(self, ws, close_status_code, close_msg):
        """Called when WebSocket is closed"""
        self.logger.info(f"WebSocket closed (code={close_status_code}, msg={close_msg})")
        self._connected = False
        if self.callbacks.get("on_close"):
            self.callbacks["on_close"]()

    # Health check
    def _start_health_check(self):
        """Start health check thread to detect silent stalls"""
        if self._health_check_thread and self._health_check_thread.is_alive():
            return

        self._health_check_thread = threading.Thread(
            target=self._health_check_loop, daemon=True
        )
        self._health_check_thread.start()

    def _health_check_loop(self):
        """Health check loop - detects silent stalls"""
        self.logger.debug("Health check started")
        while self.running and self._connected:
            time.sleep(self.HEALTH_CHECK_INTERVAL)

            if not self.running or not self._connected:
                break

            if self._last_message_time:
                elapsed = time.time() - self._last_message_time
                if elapsed > self.DATA_TIMEOUT:
                    self.logger.error(
                        f"Data stall detected - no data for {elapsed:.1f}s. Forcing reconnect..."
                    )
                    self._force_reconnect()
                    break
                else:
                    self.logger.debug(f"Health check OK - last data {elapsed:.1f}s ago")

        self.logger.debug("Health check loop exited")

    def _force_reconnect(self):
        """Force reconnection by closing the current WebSocket"""
        self.logger.info("Forcing WebSocket reconnection...")
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                self.logger.warning(f"Error closing WebSocket during force reconnect: {e}")

    # Message processing
    def _process_binary_message(self, message: bytes):
        """Process binary (protobuf) message"""
        try:
            data = self._decode_protobuf_to_dict(message)
            self.logger.debug(f"Decoded protobuf message")
            if self.callbacks.get("on_message"):
                self.callbacks["on_message"](data)
        except Exception as e:
            self.logger.error(f"Failed to process binary message: {e}")

    def _process_text_message(self, message: str):
        """Process text (JSON) message"""
        try:
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            data = json.loads(message)
            self.logger.debug(f"Received JSON message")

            if data.get("status") == "failed" and data.get("error"):
                method = data.get("method", "unknown")
                self._trigger_error(f"{method} failed: {data['error']}")
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON message: {e}")

    def _decode_protobuf_to_dict(self, buffer: bytes) -> dict[str, Any]:
        """Decode protobuf FeedResponse to dictionary"""
        feed_response = MarketDataFeedV3_pb2.FeedResponse()
        feed_response.ParseFromString(buffer)
        return MessageToDict(feed_response)

    # Helpers
    def _is_valid_auth_token(self) -> bool:
        return bool(
            self.auth_token and isinstance(self.auth_token, str) and len(self.auth_token) >= 10
        )

    def _get_websocket_url(self) -> str | None:
        """Get WebSocket URL from Upstox authorization endpoint"""
        try:
            headers = {"Accept": "application/json", "Authorization": f"Bearer {self.auth_token}"}
            response = requests.get(
                self.AUTH_ENDPOINT, headers=headers, timeout=self.HTTP_TIMEOUT
            )
            response.raise_for_status()
            auth_data = response.json()
            ws_url = auth_data.get("data", {}).get("authorized_redirect_uri")
            if ws_url:
                self.logger.info(f"Received WebSocket URL: {ws_url}")
                return ws_url
            else:
                self.logger.error("No WebSocket URL in auth response")
                return None
        except requests.Timeout:
            self.logger.error(f"Timeout getting WebSocket authorization")
            return None
        except Exception as e:
            self.logger.error(f"Failed to get WebSocket authorization: {e}")
            return None

    def _calculate_backoff_delay(self, attempt: int) -> int:
        delay = self._reconnect_config["base_delay"] * (2 ** (attempt - 1))
        return min(delay, self._reconnect_config["max_delay"])

    def _create_subscription_message(
        self, instrument_keys: list[str], mode: str = None, method: str = "sub"
    ) -> dict[str, Any]:
        message = {
            "guid": str(uuid.uuid4()).replace("-", "")[:20],
            "method": method,
            "data": {"instrumentKeys": instrument_keys},
        }
        if mode and method == "sub":
            message["data"]["mode"] = mode
        return message

    def _trigger_error(self, error_message: str):
        """Trigger error callback"""
        self.logger.error(error_message)
        if self.callbacks.get("on_error"):
            self.callbacks["on_error"](error_message)
