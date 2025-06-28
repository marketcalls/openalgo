
"""
ICICI Breeze WebSocket adapter for OpenAlgo.
Wraps breeze-connect WebSocket interface and implements the expected adapter contract.
"""

import logging
import threading
import os
from breeze_connect import BreezeConnect
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)

class ICICIWebSocketAdapter(BaseBrokerWebSocketAdapter):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("icici_websocket_adapter")
        self.ws_client = None
        self.breeze = None
        self.running = False
        self.connected = False
        self.subscribed_symbols = {}
        self.token_to_symbol = {}
        self.lock = threading.RLock()
        self.api_key = os.getenv("BROKER_API_KEY")
        self.api_secret = os.getenv("BROKER_API_SECRET")

    def initialize(self, broker_name, user_id, **kwargs):
        self.logger.info("Initializing ICICI WebSocket adapter")
        try:
            self.breeze = BreezeConnect(api_key=self.api_key)
            self.breeze.generate_session(api_secret=self.api_secret)
            self.logger.info("Session generated")
            return {"status": "success", "message": "ICICI adapter initialized"}
        except Exception as e:
            self.logger.error(f"Initialization failed: {str(e)}")
            return {"status": "error", "message": str(e)}

    def connect(self):
        try:
            self.breeze.ws_connect(on_ticks=self._on_ticks)
            self.connected = True
            self.running = True
            self.logger.info("Connected to ICICI WebSocket")
            return {"status": "success", "message": "WebSocket connected"}
        except Exception as e:
            self.logger.error(f"WebSocket connection error: {str(e)}")
            return {"status": "error", "message": str(e)}

    def disconnect(self):
        try:
            self.running = False
            self.connected = False
            self.logger.info("Disconnected from ICICI WebSocket")
            return {"status": "success", "message": "Disconnected"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def subscribe(self, symbol, exchange, mode=1, depth_level=5):
        try:
            token = get_token(symbol, exchange)
            self.breeze.subscribe_feeds(
                exchange_code=exchange,
                stock_code=symbol,
                product_type="cash",
                token=token
            )
            with self.lock:
                self.subscribed_symbols[symbol] = {
                    "exchange": exchange,
                    "token": token,
                    "mode": mode
                }
                self.token_to_symbol[str(token)] = (symbol, exchange)
            return {"status": "success", "message": f"Subscribed to {symbol}"}
        except Exception as e:
            self.logger.error(f"Subscribe error: {e}")
            return {"status": "error", "message": str(e)}

    def unsubscribe(self, symbol, exchange, mode=None):
        try:
            token = self.subscribed_symbols.get(symbol, {}).get("token")
            if token:
                self.breeze.unsubscribe_feeds([token])
                with self.lock:
                    del self.subscribed_symbols[symbol]
            return {"status": "success", "message": f"Unsubscribed from {symbol}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _on_ticks(self, ticks):
        for tick in ticks:
            token = tick.get("stock_token")
            symbol_exchange = self.token_to_symbol.get(str(token))
            if not symbol_exchange:
                continue
            symbol, exchange = symbol_exchange
            tick_data = {
                "symbol": symbol,
                "exchange": exchange,
                "ltp": tick.get("last_traded_price", 0),
                "open": tick.get("open", 0),
                "high": tick.get("high", 0),
                "low": tick.get("low", 0),
                "close": tick.get("close", 0),
                "volume": tick.get("volume", 0),
                "mode": "LTP"
            }
            topic = f"{self.broker_name}_{exchange}_{symbol}_LTP"
            self.publish_market_data(topic, tick_data)

    def is_connected(self):
        return self.connected
