from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
import websocket
import json
import threading
from utils.logging import get_logger

logger = get_logger(__name__)

class MstockWebSocketAdapter(BaseBrokerWebSocketAdapter):
    def __init__(self):
        super().__init__()
        self.ws = None
        self.thread = None

    def initialize(self, broker_name, user_id, auth_data=None):
        self.broker_name = broker_name
        self.user_id = user_id
        self.auth_data = auth_data

    def connect(self):
        def on_message(ws, message):
            data = json.loads(message)
            # Process the message and publish to ZMQ
            # This is a placeholder, the actual topic and data will depend on the message format
            topic = f"{self.broker_name}_{data.get('symbol', 'UNKNOWN')}"
            self.publish_market_data(topic, data)

        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            logger.info("WebSocket closed")
            self.connected = False

        def on_open(ws):
            logger.info("WebSocket connection opened")
            self.connected = True
            # Subscribe to symbols upon connection
            for (symbol, exchange), mode in self.subscriptions.items():
                self.subscribe(symbol, exchange, mode)

        self.ws = websocket.WebSocketApp(
            "wss://ws.mstock.trade",
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        self.thread = threading.Thread(target=self.ws.run_forever)
        self.thread.start()

    def disconnect(self):
        if self.ws:
            self.ws.close()
        if self.thread:
            self.thread.join()

    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        if not self.connected:
            return self._create_error_response(503, "WebSocket not connected")

        # mstock's websocket uses a simple string format for subscriptions
        # Format: <EXCHANGE>|<TOKEN>#<MODE>
        # Mode: 1 for LTP, 2 for Quote, 4 for Depth
        # We'll need a way to get the token for a given symbol
        # For now, we will use a placeholder token.
        # This will be addressed in a future commit.
        placeholder_token = "12345"
        subscription_string = f"{exchange}|{placeholder_token}#{mode}"
        self.ws.send(subscription_string)
        self.subscriptions[(symbol, exchange)] = mode
        return self._create_success_response("Subscribed successfully")

    def unsubscribe(self, symbol, exchange, mode=2):
        if not self.connected:
            return self._create_error_response(503, "WebSocket not connected")

        placeholder_token = "12345"
        unsubscription_string = f"{exchange}|{placeholder_token}#0" # Mode 0 to unsubscribe
        self.ws.send(unsubscription_string)
        if (symbol, exchange) in self.subscriptions:
            del self.subscriptions[(symbol, exchange)]
        return self._create_success_response("Unsubscribed successfully")
