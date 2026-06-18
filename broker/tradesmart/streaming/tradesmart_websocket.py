"""
TradeSmart (Noren v2) WebSocket Client

Handles the raw connection to TradeSmart's market-data streaming API. The
protocol is the standard Noren JSON feed: connect with an ``accesstoken``,
subscribe via touchline (``t``) / depth (``d``) with ``EXCHANGE|TOKEN`` keys,
and keep alive with heartbeat (``h``).
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import websocket


class TradeSmartWebSocket:
    """TradeSmart WebSocket client for real-time market data."""

    # Connection constants
    WS_URL = "wss://v2api.tradesmartonline.in/NorenWSAPI/"
    CONNECTION_TIMEOUT = 15
    THREAD_JOIN_TIMEOUT = 5

    # Heartbeat / keepalive
    HEARTBEAT_INTERVAL = 30
    HEARTBEAT_TIMEOUT = 120
    PING_INTERVAL = 30
    PING_TIMEOUT = 10
    HEARTBEAT_JOIN_TIMEOUT = 3

    # Message types
    MSG_TYPE_CONNECT = "a"
    MSG_TYPE_HEARTBEAT = "h"
    MSG_TYPE_AUTH_ACK = "ak"
    MSG_TYPE_TOUCHLINE_SUB = "t"
    MSG_TYPE_TOUCHLINE_UNSUB = "u"
    MSG_TYPE_DEPTH_SUB = "d"
    MSG_TYPE_DEPTH_UNSUB = "ud"

    AUTH_SUCCESS = "OK"

    def __init__(
        self,
        user_id: str,
        actid: str,
        accesstoken: str,
        on_message: Callable | None = None,
        on_error: Callable | None = None,
        on_close: Callable | None = None,
        on_open: Callable | None = None,
    ):
        self.user_id = user_id
        self.actid = actid
        self.accesstoken = accesstoken

        self.ws = None
        self.ws_thread = None
        self.running = False
        self.connected = False

        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.on_open = on_open

        self._heartbeat_thread = None
        self._last_message_time = None
        self._heartbeat_lock = threading.Lock()

        self.logger = logging.getLogger("tradesmart_websocket")

    def connect(self) -> bool:
        """Establish the WebSocket connection and authenticate."""
        if self.running:
            self.logger.warning("Already connected or connecting")
            return True
        try:
            self._initialize_connection()
            return self._wait_for_connection()
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            self.stop()
            return False

    def _initialize_connection(self) -> None:
        self.running = True
        self.ws = websocket.WebSocketApp(
            self.WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self.ws_thread.start()

    def _wait_for_connection(self) -> bool:
        start_time = time.time()
        while time.time() - start_time < self.CONNECTION_TIMEOUT:
            if self.connected:
                self.logger.info("WebSocket connected successfully")
                return True
            time.sleep(0.1)
        self.logger.error("Connection timeout")
        self.stop()
        return False

    def _run_websocket(self) -> None:
        try:
            self.ws.run_forever(ping_interval=self.PING_INTERVAL, ping_timeout=self.PING_TIMEOUT)
        except Exception as e:
            self.logger.error(f"WebSocket run error: {e}")
        finally:
            self._cleanup_connection_state()

    def _cleanup_connection_state(self) -> None:
        self.connected = False
        self._stop_heartbeat()

    def stop(self) -> None:
        """Stop the connection and release resources (never join a daemon hard)."""
        self.logger.info("Stopping WebSocket connection")
        self.running = False
        self.connected = False
        self._close_websocket()
        self._wait_for_thread_completion()
        self._stop_heartbeat()

    def _close_websocket(self) -> None:
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                self.logger.error(f"Error closing WebSocket: {e}")
            finally:
                self.ws = None

    def _wait_for_thread_completion(self) -> None:
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=self.THREAD_JOIN_TIMEOUT)
            if self.ws_thread.is_alive():
                self.logger.warning("WebSocket thread did not terminate within timeout")
                return
        self.ws_thread = None

    def _on_open(self, ws) -> None:
        self.connected = True
        self._update_last_message_time()
        self.logger.info("WebSocket opened, sending authentication")
        if self._send_authentication():
            self._start_heartbeat()
            self._call_external_callback(self.on_open, ws)

    def _send_authentication(self) -> bool:
        auth_msg = {
            "t": self.MSG_TYPE_CONNECT,
            "uid": self.user_id,
            "actid": self.actid,
            "source": "API",
            "accesstoken": self.accesstoken,
        }
        try:
            self.ws.send(json.dumps(auth_msg))
            self.logger.info("Authentication message sent")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send authentication: {e}")
            return False

    def _on_message(self, ws, message: str) -> None:
        self._update_last_message_time()
        if self._handle_internal_message(message):
            return
        self._call_external_callback(self.on_message, ws, message)

    def _handle_internal_message(self, message: str) -> bool:
        try:
            data = json.loads(message)
            msg_type = data.get("t")
            if msg_type == self.MSG_TYPE_AUTH_ACK:
                return self._handle_auth_response(data)
            elif msg_type == self.MSG_TYPE_HEARTBEAT:
                self.logger.debug("Received heartbeat response")
                return True
        except (json.JSONDecodeError, KeyError):
            pass
        return False

    def _handle_auth_response(self, data: dict[str, Any]) -> bool:
        if data.get("s") == self.AUTH_SUCCESS:
            self.logger.info("Authentication successful")
        else:
            self.logger.error(f"Authentication failed: {data}")
        return True

    def _on_error(self, ws, error) -> None:
        self.logger.error(f"WebSocket error: {error}")
        self._call_external_callback(self.on_error, ws, error)

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        self.connected = False
        self.logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
        self._stop_heartbeat()
        self._call_external_callback(self.on_close, ws, close_status_code, close_msg)

    def _call_external_callback(self, callback: Callable | None, *args) -> None:
        if callback:
            try:
                callback(*args)
            except Exception as e:
                self.logger.error(f"Error in external callback: {e}")

    def _update_last_message_time(self) -> None:
        with self._heartbeat_lock:
            self._last_message_time = time.time()

    def _start_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=self.HEARTBEAT_JOIN_TIMEOUT)
            if self._heartbeat_thread.is_alive():
                self.logger.warning("Heartbeat thread did not terminate within timeout")
                return
        self._heartbeat_thread = None

    def _heartbeat_worker(self) -> None:
        while self.running and self.connected:
            try:
                time.sleep(self.HEARTBEAT_INTERVAL)
                if self.running and self.connected:
                    if not self._send_heartbeat():
                        break
                    if not self._check_connection_health():
                        break
            except Exception as e:
                self.logger.error(f"Heartbeat worker error: {e}")
                break

    def _send_heartbeat(self) -> bool:
        if not self.ws:
            return False
        try:
            self.ws.send(json.dumps({"t": self.MSG_TYPE_HEARTBEAT}))
            self.logger.debug("Sent heartbeat")
            return True
        except Exception as e:
            self.logger.error(f"Heartbeat send error: {e}")
            return False

    def _check_connection_health(self) -> bool:
        with self._heartbeat_lock:
            if self._last_message_time:
                if time.time() - self._last_message_time > self.HEARTBEAT_TIMEOUT:
                    self.logger.error("Connection timeout - no messages received")
                    self._close_websocket()
                    return False
        return True

    def subscribe_touchline(self, scrip_list: str) -> bool:
        return self._send_subscription_message(
            self.MSG_TYPE_TOUCHLINE_SUB, scrip_list, "touchline subscription"
        )

    def unsubscribe_touchline(self, scrip_list: str) -> bool:
        return self._send_subscription_message(
            self.MSG_TYPE_TOUCHLINE_UNSUB, scrip_list, "touchline unsubscription"
        )

    def subscribe_depth(self, scrip_list: str) -> bool:
        return self._send_subscription_message(
            self.MSG_TYPE_DEPTH_SUB, scrip_list, "depth subscription"
        )

    def unsubscribe_depth(self, scrip_list: str) -> bool:
        return self._send_subscription_message(
            self.MSG_TYPE_DEPTH_UNSUB, scrip_list, "depth unsubscription"
        )

    def _send_subscription_message(self, msg_type: str, scrip_list: str, operation_name: str) -> bool:
        return self._send_message({"t": msg_type, "k": scrip_list}, operation_name)

    def _send_message(self, message_dict: dict[str, Any], operation_name: str) -> bool:
        if not self._validate_connection_state(operation_name):
            return False
        try:
            self.ws.send(json.dumps(message_dict))
            self.logger.debug(f"Sent {operation_name}: {message_dict}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send {operation_name}: {e}")
            return False

    def _validate_connection_state(self, operation_name: str) -> bool:
        if not self.ws:
            self.logger.warning(f"Cannot send {operation_name}: WebSocket not initialized")
            return False
        if not self.connected:
            self.logger.warning(f"Cannot send {operation_name}: not connected")
            return False
        return True

    def is_connected(self) -> bool:
        return self.connected and self.running
