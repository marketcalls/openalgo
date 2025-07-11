from utils.logging import get_logger

"""
Flattrade WebSocket client for OpenAlgo integration
Handles connection, authentication, subscription, and message parsing.
"""
import json
import threading
import websocket
import time

class FlattradeWebSocket:
    WS_URL = "wss://piconnect.flattrade.in/PiConnectWSTp/"

    def __init__(self, user_id, actid, susertoken, on_message=None, on_error=None, on_close=None, on_open=None):
        self.user_id = user_id
        self.actid = actid
        self.susertoken = susertoken
        self.ws = None
        self.connected = False
        self.logger = get_logger("flattrade_websocket")
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.on_open = on_open
        self._thread = None
        self._stop_event = threading.Event()

    def connect(self):
        """Establishes the WebSocket connection and waits for it to be opened."""
        self.logger.info("Attempting to connect to WebSocket...")
        self.ws = websocket.WebSocketApp(
            self.WS_URL,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open
        )
        self._thread = threading.Thread(target=self.ws.run_forever, daemon=True, name="FlattradeWSThread")
        self.logger.debug("Starting WebSocket run_forever thread.")
        self._thread.start()

        # Wait for connection with a timeout
        self.logger.debug("Waiting for connection to be established...")
        for _ in range(50):  # 10 seconds timeout (50 * 0.2s)
            if self.connected:
                # self.logger.info("WebSocket connection successfully established.") is logged in _on_open
                return True
            if not self._thread.is_alive():
                self.logger.error("WebSocket thread terminated unexpectedly during connection attempt.")
                return False
            time.sleep(0.2)

        self.logger.error("WebSocket connection attempt timed out after 10 seconds.")
        self.stop()  # Clean up the lingering thread and websocket object
        return False

    def stop(self):
        """Stops the WebSocket client and waits for the thread to terminate."""
        self.logger.info("Stopping Flattrade WebSocket client...")
        if self.ws:
            self.ws.close()  # This will trigger _on_close and stop run_forever

        if self._thread and self._thread.is_alive():
            self.logger.info("Waiting for WebSocket thread to terminate...")
            self._thread.join(timeout=5)  # Wait for the thread to finish
            if self._thread.is_alive():
                self.logger.warning("WebSocket thread did not terminate in time.")
            else:
                self.logger.info("WebSocket thread terminated successfully.")

        self.connected = False
        self.ws = None
        self._thread = None
        self.logger.info("Flattrade WebSocket client stopped.")

    def _on_open(self, ws):
        self.connected = True
        self.logger.info("WebSocket connection opened. Sending authentication request...")
        auth_msg = {
            "t": "c",
            "uid": self.user_id,
            "actid": self.actid,
            "source": "API",
            "susertoken": self.susertoken
        }
        self.logger.debug(f"Sending auth message: {auth_msg}")
        ws.send(json.dumps(auth_msg))
        if self.on_open:
            try:
                self.logger.debug("Calling on_open callback in adapter.")
                self.on_open(ws)
            except Exception:
                self.logger.exception("Exception in on_open callback.")

    def _on_message(self, ws, message):
        self.logger.debug(f"Raw message received: {message}")
        # Log authentication status explicitly
        try:
            data = json.loads(message)
            if data.get('t') == 'ck':  # Connection acknowledgement
                self.logger.info(f"Received connection acknowledgement: {data}")
                if data.get('s') == 'OK':
                    self.logger.info("Authentication successful.")
                else:
                    self.logger.error(f"Authentication failed: {data}")
        except (json.JSONDecodeError, AttributeError):
            pass  # Not a JSON message or doesn't have 't', not an auth response

        if self.on_message:
            try:
                self.on_message(ws, message)
            except Exception:
                self.logger.exception("Exception in on_message callback.")

    def _on_error(self, ws, error):
        self.logger.error(f"WebSocket error received: {error}")
        if isinstance(error, ConnectionRefusedError):
            self.logger.error("Connection was refused. Is the server running? Is the port correct?")
        if self.on_error:
            self.on_error(ws, error)

    def _on_close(self, ws, close_status_code, close_msg):
        self.connected = False
        self.logger.warning(f"WebSocket connection closed. Code: {close_status_code}, Message: {close_msg}")
        if self.on_close:
            self.on_close(ws, close_status_code, close_msg)

    def subscribe_touchline(self, scrip_list):
        msg = {"t": "t", "k": scrip_list}
        self._send(msg)

    def unsubscribe_touchline(self, scrip_list):
        msg = {"t": "u", "k": scrip_list}
        self._send(msg)

    def subscribe_depth(self, scrip_list):
        msg = {"t": "d", "k": scrip_list}
        self._send(msg)

    def unsubscribe_depth(self, scrip_list):
        msg = {"t": "ud", "k": scrip_list}
        self._send(msg)

    def _send(self, msg):
        if self.ws and self.connected:
            try:
                self.ws.send(json.dumps(msg))
                self.logger.debug(f"[SEND] {msg}")
            except Exception:
                self.logger.exception(f"Failed to send message: {msg}")
        else:
            self.logger.warning(f"WebSocket not connected. Cannot send message: {msg}")
