import websocket
import threading
import json
import time
import os
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from database.symbol import SymToken
from utils.logging import get_logger

class MstockWebSocketAdapter(BaseBrokerWebSocketAdapter):
    def __init__(self):
        super().__init__()
        self.logger = get_logger("MstockWebSocketAdapter")
        self.ws_url = "wss://ws.mstock.trade"
        self.ws_client = None
        self.ws_thread = None
        self.api_key = None
        self.access_token = None

    def initialize(self, broker_name, user_id, auth_data=None):
        self.logger.info("Initializing mstock WebSocket adapter")
        self.broker_name = broker_name
        self.user_id = user_id

        if auth_data:
            self.api_key = auth_data.get('api_key')
            self.access_token = auth_data.get('access_token')
        else:
            self.logger.error("Auth data not provided for mstock WebSocket adapter.")
            # In a real scenario, you might try to fetch it, but for now, we'll require it.
            raise ValueError("Authentication data is required for mstock WebSocket.")

        if not self.api_key or not self.access_token:
            raise ValueError("API key and access token are required for mstock WebSocket.")

    def connect(self):
        self.logger.info("Connecting to mstock WebSocket")
        self.ws_client = websocket.WebSocketApp(self.ws_url,
                                                on_open=self._on_open,
                                                on_message=self._on_message,
                                                on_error=self._on_error,
                                                on_close=self._on_close)
        self.ws_thread = threading.Thread(target=self.ws_client.run_forever)
        self.ws_thread.daemon = True
        self.ws_thread.start()

    def disconnect(self):
        self.logger.info("Disconnecting from mstock WebSocket")
        if self.ws_client:
            self.ws_client.close()
        if self.ws_thread:
            self.ws_thread.join()
        self.connected = False

    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        self.logger.info(f"Subscribing to {symbol} on {exchange}")
        # This is a placeholder implementation as mstock WebSocket protocol is not documented.
        token_info = SymToken.get_token_from_symbol(symbol=symbol, exchange=exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for {exchange}")

        instrument_token = token_info['token']

        sub_message = {
            "action": "subscribe",
            "params": {
                "instrument_keys": [f"{exchange}:{instrument_token}"],
                "mode": self._map_mode(mode)
            }
        }

        if self.connected:
            self.ws_client.send(json.dumps(sub_message))

        correlation_id = f"{symbol}_{exchange}_{mode}"
        self.subscriptions[correlation_id] = {'token': instrument_token, 'symbol': symbol, 'exchange': exchange, 'mode': mode}

        return self._create_success_response(f"Subscription request for {symbol} sent.")

    def unsubscribe(self, symbol, exchange, mode=2):
        self.logger.info(f"Unsubscribing from {symbol} on {exchange}")
        correlation_id = f"{symbol}_{exchange}_{mode}"
        if correlation_id not in self.subscriptions:
            return self._create_error_response("NOT_SUBSCRIBED", "Not subscribed to this instrument.")

        instrument_token = self.subscriptions[correlation_id]['token']

        unsub_message = {
            "action": "unsubscribe",
            "params": {
                "instrument_keys": [f"{exchange}:{instrument_token}"],
            }
        }

        if self.connected:
            self.ws_client.send(json.dumps(unsub_message))

        del self.subscriptions[correlation_id]
        return self._create_success_response(f"Unsubscription request for {symbol} sent.")

    def _on_open(self, ws):
        self.logger.info("mstock WebSocket connection opened.")
        self.connected = True
        auth_message = {
            "action": "authorize",
            "params": { "api_key": self.api_key, "access_token": self.access_token }
        }
        ws.send(json.dumps(auth_message))

        self.logger.info("Resubscribing to existing subscriptions...")
        for sub in self.subscriptions.values():
             self.subscribe(sub['symbol'], sub['exchange'], sub['mode'])

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            if "type" in data and data["type"] == "market_data":
                topic = f"{data['exchange']}_{data['symbol']}_{self._reverse_map_mode(data['mode'])}"
                self.publish_market_data(topic, data)
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    def _on_error(self, ws, error):
        self.logger.error(f"mstock WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        self.logger.info("mstock WebSocket connection closed.")
        self.connected = False

    def _map_mode(self, mode):
        if mode == 1: return "ltp"
        if mode == 2: return "quote"
        if mode == 4: return "full"
        return "quote"

    def _reverse_map_mode(self, mode_str):
        if mode_str == "ltp": return 1
        if mode_str == "quote": return 2
        if mode_str == "full": return 4
        return 2
