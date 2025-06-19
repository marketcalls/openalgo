"""
Flattrade WebSocket client for OpenAlgo integration
Handles connection, authentication, subscription, and message parsing.
"""
import json
import threading
import websocket
import logging
import time

class FlattradeWebSocket:
    WS_URL = "wss://piconnect.flattrade.in/PiConnectWSTp/"

    def __init__(self, user_id, actid, susertoken, on_message=None, on_error=None, on_close=None, on_open=None):
        self.user_id = user_id
        self.actid = actid
        self.susertoken = susertoken
        self.ws = None
        self.connected = False
        self.logger = logging.getLogger("flattrade_websocket")
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.on_open = on_open
        self._thread = None
        self._stop_event = threading.Event()

    def connect(self):
        self.ws = websocket.WebSocketApp(
            self.WS_URL,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open
        )
        self._thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self._thread.start()
        # Wait for connection
        for _ in range(30):
            if self.connected:
                return True
            time.sleep(0.2)
        return False

    def disconnect(self):
        self._stop_event.set()
        if self.ws:
            self.ws.close()
        self.connected = False

    def _on_open(self, ws):
        self.connected = True
        self.logger.info("WebSocket connection opened. Sending authentication...")
        auth_msg = {
            "t": "c",
            "uid": self.user_id,
            "actid": self.actid,
            "source": "API",
            "susertoken": self.susertoken
        }
        ws.send(json.dumps(auth_msg))
        if self.on_open:
            self.on_open(ws)

    def _on_message(self, ws, message):
        print(f"[FlattradeWebSocket] Received: {message}")  # Debug print
        if self.on_message:
            self.on_message(ws, message)

    def _on_error(self, ws, error):
        self.logger.error(f"WebSocket error: {error}")
        if self.on_error:
            self.on_error(ws, error)

    def _on_close(self, ws, close_status_code, close_msg):
        self.connected = False
        self.logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
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
            print(f"[FlattradeWebSocket] Sending: {msg}")  # Debug print
            self.ws.send(json.dumps(msg))
