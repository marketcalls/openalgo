"""
Zebu WebSocket Client Implementation
Handles connection to Zebu's market data streaming API
Based on Noren WebSocket API (same as Flattrade)
"""

import json
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Dict, Optional

import websocket

from utils.logging import get_logger


class ZebuWebSocket:
    """Zebu WebSocket client for real-time market data"""

    # Connection constants
    # Try different URL patterns based on other Noren brokers:
    # - Shoonya: wss://api.shoonya.com/NorenWSTP/
    # - Flattrade: wss://piconnect.flattrade.in/PiConnectWSAPI/
    # - AliceBlue: wss://ws1.aliceblueonline.com/NorenWS/
    # - DefinEdge: wss://trade.definedgesecurities.com/NorenWSTRTP/
    WS_URL = "wss://go.mynt.in/NorenWSAPI/"  # Zebu OAuth WebSocket endpoint
    CONNECTION_TIMEOUT = 15
    THREAD_JOIN_TIMEOUT = 5

    # Heartbeat constants
    HEARTBEAT_INTERVAL = 30
    HEARTBEAT_TIMEOUT = 120
    PING_INTERVAL = 30
    PING_TIMEOUT = 10
    HEARTBEAT_JOIN_TIMEOUT = 3

    # Market-data silence watchdog (issue #2075, same defect as Flattrade and
    # Shoonya). A Noren session that keeps answering heartbeats while
    # delivering no ticks is indistinguishable from a healthy one on
    # _last_message_time alone, because every inbound frame stamps it -
    # heartbeat acks included. Tick flow therefore gets its own clock, and the
    # watchdog only arms once data has been arriving over time: frames in
    # DATA_ARM_BUCKETS distinct buckets of DATA_ARM_BUCKET seconds, all within
    # DATA_ARM_WINDOW. See _update_last_data_time for why spread matters and a
    # frame count does not.
    DATA_SILENCE_TIMEOUT = 180
    DATA_ARM_BUCKET = 30
    DATA_ARM_BUCKETS = 3
    DATA_ARM_WINDOW = 300

    # Message types (OAuth WebSocket API)
    MSG_TYPE_CONNECT = "a"
    MSG_TYPE_HEARTBEAT = "h"
    # The doc's heartbeat ack is "hk"; "h" is kept because some Noren
    # deployments echo the request type back instead. Only "h" was matched
    # before, so an "hk" ack fell through to the market-data path - harmless
    # while nothing read it, but it would have counted as a tick and defeated
    # the silence watchdog below.
    MSG_TYPE_HEARTBEAT_ACK = "hk"
    MSG_TYPE_AUTH_ACK = "ak"
    MSG_TYPE_TOUCHLINE_SUB = "t"
    MSG_TYPE_TOUCHLINE_UNSUB = "u"
    MSG_TYPE_DEPTH_SUB = "d"
    MSG_TYPE_DEPTH_UNSUB = "ud"

    # Authentication response
    AUTH_SUCCESS = "OK"

    def __init__(
        self,
        user_id: str,
        actid: str,
        susertoken: str,
        on_message: Callable | None = None,
        on_error: Callable | None = None,
        on_close: Callable | None = None,
        on_open: Callable | None = None,
    ):
        """
        Initialize Zebu WebSocket client

        Args:
            user_id: User ID for authentication
            actid: Account ID for authentication
            susertoken: Session token for authentication
            on_message: Callback for incoming messages
            on_error: Callback for connection errors
            on_close: Callback for connection close
            on_open: Callback for connection open
        """
        # Authentication credentials
        self.user_id = user_id
        self.actid = actid
        self.susertoken = susertoken

        # Connection state
        self.ws = None
        self.ws_thread = None
        self.running = False
        self.connected = False

        # Callbacks
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.on_open = on_open

        # Heartbeat management
        self._heartbeat_thread = None
        self._last_message_time = None
        self._heartbeat_lock = threading.Lock()

        # Market-data liveness, kept apart from _last_message_time above so a
        # socket that only answers heartbeats cannot pass for a live feed.
        # Per connection: _reset_data_liveness() clears all three on open.
        self._last_data_message_time = None
        self._data_watchdog_armed = False
        self._data_bucket_starts = deque(maxlen=self.DATA_ARM_BUCKETS)

        # Logging
        self.logger = get_logger("zebu_websocket")

    def connect(self) -> bool:
        """
        Establish WebSocket connection with authentication

        Returns:
            bool: True if connection successful, False otherwise
        """
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
        """Initialize WebSocket connection and start thread"""
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
        """
        Wait for WebSocket connection to be established

        Returns:
            bool: True if connected within timeout, False otherwise
        """
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
        """Run the WebSocket connection with proper error handling"""
        try:
            self.ws.run_forever(ping_interval=self.PING_INTERVAL, ping_timeout=self.PING_TIMEOUT)
        except Exception as e:
            self.logger.error(f"WebSocket run error: {e}")
        finally:
            self._cleanup_connection_state()

    def _cleanup_connection_state(self) -> None:
        """Clean up connection state"""
        self.connected = False
        self._stop_heartbeat()

    def stop(self) -> None:
        """Stop the WebSocket connection and cleanup resources"""
        self.logger.info("Stopping WebSocket connection")

        self.running = False
        self.connected = False

        self._close_websocket()
        self._wait_for_thread_completion()
        self._stop_heartbeat()

    def _close_websocket(self) -> None:
        """Close WebSocket connection"""
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                self.logger.error(f"Error closing WebSocket: {e}")
            finally:
                self.ws = None

    def _wait_for_thread_completion(self) -> None:
        """Wait for WebSocket thread to complete"""
        ws_thread = self.ws_thread
        if ws_thread and ws_thread.is_alive():
            ws_thread.join(timeout=self.THREAD_JOIN_TIMEOUT)
            if ws_thread.is_alive():
                self.logger.warning("WebSocket thread did not terminate within timeout")
        self.ws_thread = None

    # WebSocket Event Handlers
    def _on_open(self, ws) -> None:
        """Handle WebSocket connection open event"""
        self.connected = True
        self._update_last_message_time()
        self._reset_data_liveness()

        self.logger.info("WebSocket connection opened, sending authentication")

        if self._send_authentication():
            self._start_heartbeat()
            self._call_external_callback(self.on_open, ws)

    def _send_authentication(self) -> bool:
        """
        Send authentication message to server

        Returns:
            bool: True if authentication sent successfully, False otherwise
        """
        auth_msg = {
            "t": self.MSG_TYPE_CONNECT,
            "uid": self.user_id,
            "actid": self.actid,
            "source": "API",
            "accesstoken": self.susertoken,
        }

        # Log the authentication message for debugging (mask the token)
        debug_msg = auth_msg.copy()
        token_val = debug_msg.get("accesstoken", "")
        if token_val:
            debug_msg["accesstoken"] = (
                token_val[:10] + "..." if len(token_val) > 10 else "***"
            )
        self.logger.info(f"Sending auth message: {debug_msg}")

        try:
            self.ws.send(json.dumps(auth_msg))
            self.logger.info("Authentication message sent")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send authentication: {e}")
            return False

    def _on_message(self, ws, message: str) -> None:
        """Handle incoming WebSocket messages"""
        self._update_last_message_time()

        if self._handle_internal_message(message):
            return

        # Everything that is not an auth ack or a heartbeat ack is a market
        # data frame (tk/tf/dk/df), so this is the point where the feed - as
        # opposed to the socket - proves it is alive. Issue #2075.
        self._update_last_data_time()

        self._call_external_callback(self.on_message, ws, message)

    def _handle_internal_message(self, message: str) -> bool:
        """
        Handle internal messages (auth, heartbeat)

        Args:
            message: Incoming message string

        Returns:
            bool: True if message was handled internally, False otherwise
        """
        try:
            data = json.loads(message)
            msg_type = data.get("t")

            if msg_type == self.MSG_TYPE_AUTH_ACK:
                return self._handle_auth_response(data)
            elif msg_type in (self.MSG_TYPE_HEARTBEAT_ACK, self.MSG_TYPE_HEARTBEAT):
                self.logger.debug("Received heartbeat response")
                return True

        except (json.JSONDecodeError, KeyError):
            # Not a JSON message or doesn't have expected structure
            pass

        return False

    def _handle_auth_response(self, data: dict[str, Any]) -> bool:
        """
        Handle authentication response

        Args:
            data: Authentication response data

        Returns:
            bool: True (message handled)
        """
        if data.get("s", "").lower() == self.AUTH_SUCCESS.lower():
            self.logger.info("Authentication successful")
        else:
            self.logger.error(f"Authentication failed: {data}")

        return True

    def _on_error(self, ws, error) -> None:
        """Handle WebSocket connection errors"""
        self.logger.error(f"WebSocket error: {error}")
        self._call_external_callback(self.on_error, ws, error)

    def _on_close(self, ws, close_status_code: int | None, close_msg: str | None) -> None:
        """Handle WebSocket connection close event"""
        self.connected = False
        self.logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")

        self._stop_heartbeat()
        self._call_external_callback(self.on_close, ws, close_status_code, close_msg)

    def _call_external_callback(self, callback: Callable | None, *args) -> None:
        """
        Safely call external callback with error handling

        Args:
            callback: Callback function to call
            *args: Arguments to pass to callback
        """
        if callback:
            try:
                callback(*args)
            except Exception as e:
                self.logger.error(f"Error in external callback: {e}")

    # Heartbeat Management
    def _update_last_data_time(self) -> None:
        """Record a market-data frame and arm the data-silence watchdog.

        Arming asks that data arrived *spread over time*, not that a lot of it
        arrived. Noren answers every subscribe with a snapshot frame, so a
        session opened overnight receives one frame per subscribed scrip
        within a second of connecting - fifty symbols is fifty frames. Any
        rule counting frames would arm on that burst and then recycle the
        socket every DATA_SILENCE_TIMEOUT until the market opened, which on a
        Noren gateway also risks a server-side session cooldown.

        Bucketing is what separates the two. A burst lands in one bucket (two
        if it straddles a boundary), while a live feed keeps producing frames
        bucket after bucket. Requiring DATA_ARM_BUCKETS distinct buckets means
        at least a couple of DATA_ARM_BUCKET-second spans of real flow before
        the watchdog can fire, and DATA_ARM_WINDOW stops stray after-hours
        ticks hours apart from accumulating into a false arm.

        Arming lasts only for this connection. If the market closes while the
        watchdog is armed, the feed falls silent, the socket is recycled once,
        and the replacement starts disarmed - so the cost of a wrong guess is
        bounded at one reconnect rather than a loop against the adapter's
        reconnect budget.
        """
        now = time.time()
        newly_armed = False

        with self._heartbeat_lock:
            self._last_data_message_time = now

            if not self._data_watchdog_armed:
                bucket_start = now - (now % self.DATA_ARM_BUCKET)
                if not self._data_bucket_starts or self._data_bucket_starts[-1] != bucket_start:
                    self._data_bucket_starts.append(bucket_start)

                if (
                    len(self._data_bucket_starts) == self._data_bucket_starts.maxlen
                    and now - self._data_bucket_starts[0] <= self.DATA_ARM_WINDOW
                ):
                    self._data_watchdog_armed = True
                    newly_armed = True

        if newly_armed:
            self.logger.info("Market data is flowing; watching for tick silence from here on")

    def _reset_data_liveness(self) -> None:
        """Clear the per-connection market-data liveness state."""
        with self._heartbeat_lock:
            self._last_data_message_time = None
            self._data_watchdog_armed = False
            self._data_bucket_starts.clear()

    def _update_last_message_time(self) -> None:
        """Update the timestamp of the last received message"""
        with self._heartbeat_lock:
            self._last_message_time = time.time()

    def _start_heartbeat(self) -> None:
        """Start heartbeat monitoring thread"""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        self._heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
        self._heartbeat_thread.start()
        self.logger.debug("Heartbeat thread started")

    def _stop_heartbeat(self) -> None:
        """Stop heartbeat monitoring thread and wait for it to terminate"""
        hb_thread = self._heartbeat_thread
        if hb_thread and hb_thread.is_alive():
            self.logger.debug("Waiting for heartbeat thread to stop")
            hb_thread.join(timeout=self.HEARTBEAT_JOIN_TIMEOUT)
            if hb_thread.is_alive():
                self.logger.warning("Heartbeat thread did not terminate within timeout")
        self._heartbeat_thread = None

    def _heartbeat_worker(self) -> None:
        """Heartbeat worker thread - sends periodic heartbeats and monitors connection"""
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
        """
        Send heartbeat message to server

        Returns:
            bool: True if heartbeat sent successfully, False otherwise
        """
        if not self.ws:
            return False

        try:
            heartbeat_msg = {"t": self.MSG_TYPE_HEARTBEAT}
            self.ws.send(json.dumps(heartbeat_msg))
            self.logger.debug("Sent heartbeat")
            return True
        except Exception as e:
            self.logger.error(f"Heartbeat send error: {e}")
            return False

    def _check_connection_health(self) -> bool:
        """Recycle the socket when the session has stopped being useful.

        Two independent timeouts, because a Noren session fails in two ways:

        * HEARTBEAT_TIMEOUT catches a socket that has gone quiet altogether.
        * DATA_SILENCE_TIMEOUT catches one that still answers heartbeats while
          delivering no market data. That case used to be invisible here - the
          heartbeat ack itself refreshed _last_message_time - so the feed could
          stay dead for the rest of the session with the app still reporting a
          healthy connection, and nothing downstream that runs on ticks (stop
          losses, sandbox order triggers, Flow conditions) would fire. Checked
          only once the watchdog is armed; see _update_last_data_time.
          Issue #2075.

        Returns:
            bool: True if connection is healthy, False if it was recycled
        """
        now = time.time()
        reason = None

        with self._heartbeat_lock:
            if self._last_message_time and now - self._last_message_time > self.HEARTBEAT_TIMEOUT:
                reason = "no messages received"
            elif (
                self._data_watchdog_armed
                and self._last_data_message_time
                and now - self._last_data_message_time > self.DATA_SILENCE_TIMEOUT
            ):
                silent_for = now - self._last_data_message_time
                reason = (
                    f"no market data for {silent_for:.0f}s while the session kept "
                    "answering heartbeats"
                )

        if reason is None:
            return True

        # Closed outside the lock: the reader thread runs _on_close, which can
        # route back through _stop_heartbeat on this very thread.
        self.logger.error(f"Connection timeout - {reason}")
        self._close_websocket()
        return False

    # Subscription Management
    def subscribe_touchline(self, scrip_list: str) -> bool:
        """
        Subscribe to touchline data for complete quote information

        Args:
            scrip_list: Comma or hash-separated list of scrips

        Returns:
            bool: True if subscription sent successfully, False otherwise
        """
        return self._send_subscription_message(
            self.MSG_TYPE_TOUCHLINE_SUB, scrip_list, "touchline subscription"
        )

    def unsubscribe_touchline(self, scrip_list: str) -> bool:
        """
        Unsubscribe from touchline data

        Args:
            scrip_list: Comma or hash-separated list of scrips

        Returns:
            bool: True if unsubscription sent successfully, False otherwise
        """
        return self._send_subscription_message(
            self.MSG_TYPE_TOUCHLINE_UNSUB, scrip_list, "touchline unsubscription"
        )

    def subscribe_depth(self, scrip_list: str) -> bool:
        """
        Subscribe to market depth data

        Args:
            scrip_list: Comma or hash-separated list of scrips

        Returns:
            bool: True if subscription sent successfully, False otherwise
        """
        return self._send_subscription_message(
            self.MSG_TYPE_DEPTH_SUB, scrip_list, "depth subscription"
        )

    def unsubscribe_depth(self, scrip_list: str) -> bool:
        """
        Unsubscribe from market depth data

        Args:
            scrip_list: Comma or hash-separated list of scrips

        Returns:
            bool: True if unsubscription sent successfully, False otherwise
        """
        return self._send_subscription_message(
            self.MSG_TYPE_DEPTH_UNSUB, scrip_list, "depth unsubscription"
        )

    def _send_subscription_message(
        self, msg_type: str, scrip_list: str, operation_name: str
    ) -> bool:
        """
        Send subscription/unsubscription message

        Args:
            msg_type: Message type for the operation
            scrip_list: List of scrips to subscribe/unsubscribe
            operation_name: Human-readable operation name for logging

        Returns:
            bool: True if message sent successfully, False otherwise
        """
        message_dict = {"t": msg_type, "k": scrip_list}
        return self._send_message(message_dict, operation_name)

    def _send_message(self, message_dict: dict[str, Any], operation_name: str) -> bool:
        """
        Send message with comprehensive error handling and validation

        Args:
            message_dict: Message data to send
            operation_name: Human-readable operation name for logging

        Returns:
            bool: True if message sent successfully, False otherwise
        """
        if not self._validate_connection_state(operation_name):
            return False

        try:
            message_json = json.dumps(message_dict)
            self.ws.send(message_json)
            self.logger.debug(f"Sent {operation_name}: {message_dict}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send {operation_name}: {e}")
            return False

    def _validate_connection_state(self, operation_name: str) -> bool:
        """
        Validate that connection is ready for sending messages

        Args:
            operation_name: Operation name for logging

        Returns:
            bool: True if connection is ready, False otherwise
        """
        if not self.ws:
            self.logger.warning(f"Cannot send {operation_name}: WebSocket not initialized")
            return False

        if not self.connected:
            self.logger.warning(f"Cannot send {operation_name}: not connected")
            return False

        return True

    # Utility Methods
    def is_connected(self) -> bool:
        """
        Check if WebSocket is currently connected

        Returns:
            bool: True if connected, False otherwise
        """
        return self.connected and self.running

    def get_connection_info(self) -> dict[str, Any]:
        """
        Get connection information for debugging

        Returns:
            Dict: Connection state information
        """
        return {
            "connected": self.connected,
            "running": self.running,
            "user_id": self.user_id,
            "actid": self.actid,
            "ws_url": self.WS_URL,
            "last_message_time": self._last_message_time,
            "heartbeat_thread_alive": self._heartbeat_thread.is_alive()
            if self._heartbeat_thread
            else False,
            "ws_thread_alive": self.ws_thread.is_alive() if self.ws_thread else False,
        }
