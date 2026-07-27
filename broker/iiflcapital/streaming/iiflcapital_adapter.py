import os
import threading
import time
from typing import Any

from broker.iiflcapital.api.data import BrokerData
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter


class IiflcapitalWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    IIFL Capital WebSocket adapter.

    The broker currently exposes reliable REST market-data APIs, so this adapter
    provides WebSocket compatibility by polling quote/depth endpoints and
    publishing updates to the existing ZeroMQ pipeline.
    """

    MODE_LTP = 1
    MODE_QUOTE = 2
    MODE_DEPTH = 3

    def __init__(self):
        super().__init__()
        self.broker_name = "iiflcapital"
        self.user_id = None
        self.auth_token = None
        self.data_handler = None
        self.connected = False

        self.poll_interval = float(os.getenv("IIFLCAPITAL_POLL_INTERVAL", "0.8"))
        self._stop_event = threading.Event()
        self._poll_thread = None
        self._sub_lock = threading.Lock()
        self.subscriptions = {}

    def initialize(self, broker_name, user_id, auth_data=None, force=False):
        self.user_id = user_id
        self.broker_name = broker_name or self.broker_name

        auth_token = None
        if auth_data:
            auth_token = auth_data.get("auth_token")

        if force or not auth_token:
            auth_token = self.get_auth_token_for_user(user_id, bypass_cache=force)

        if not auth_token:
            return self._create_error_response(
                "AUTHENTICATION_ERROR", f"No authentication token found for user {user_id}"
            )

        self.auth_token = auth_token
        self.data_handler = BrokerData(auth_token=auth_token, user_id=user_id)
        self._stop_event.clear()
        return self._create_success_response("IIFL Capital adapter initialized")

    def connect(self):
        if not self.data_handler:
            return self._create_error_response(
                "NOT_INITIALIZED", "Adapter not initialized. Call initialize() first."
            )

        if self.connected:
            return self._create_success_response("Already connected")

        self.connected = True
        self._stop_event.clear()

        if not self._poll_thread or not self._poll_thread.is_alive():
            self._poll_thread = threading.Thread(target=self._poll_market_data, daemon=True)
            self._poll_thread.start()

        return self._create_success_response("Connected")

    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        if mode not in (self.MODE_LTP, self.MODE_QUOTE, self.MODE_DEPTH):
            return self._create_error_response(
                "INVALID_MODE",
                f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)",
            )

        if mode == self.MODE_DEPTH and depth_level not in (5, 20):
            return self._create_error_response(
                "INVALID_DEPTH", f"Invalid depth level {depth_level}. Must be 5 or 20"
            )

        with self._sub_lock:
            key = f"{exchange}:{symbol}"
            subscription = self.subscriptions.get(
                key,
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "modes": set(),
                    "depth_level": 5,
                },
            )
            subscription["modes"].add(mode)
            subscription["depth_level"] = depth_level if mode == self.MODE_DEPTH else 5
            self.subscriptions[key] = subscription

        return self._create_success_response(
            f"Subscribed to {symbol} on {exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            actual_depth=depth_level if mode == self.MODE_DEPTH else 5,
        )

    def unsubscribe(self, symbol, exchange, mode=2):
        with self._sub_lock:
            key = f"{exchange}:{symbol}"
            if key not in self.subscriptions:
                return self._create_success_response(
                    f"No active subscription for {symbol} on {exchange}",
                    symbol=symbol,
                    exchange=exchange,
                    mode=mode,
                )

            subscription = self.subscriptions[key]
            subscription["modes"].discard(mode)
            if not subscription["modes"]:
                del self.subscriptions[key]
            else:
                self.subscriptions[key] = subscription

        return self._create_success_response(
            f"Unsubscribed from {symbol} on {exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
        )

    def unsubscribe_all(self):
        with self._sub_lock:
            self.subscriptions.clear()
        return self._create_success_response("Unsubscribed from all symbols")

    def disconnect(self):
        self.connected = False
        self._stop_event.set()

        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=2)

        self.cleanup_zmq()
        return self._create_success_response("Disconnected")

    def _poll_market_data(self):
        while not self._stop_event.is_set():
            if not self.connected or not self.data_handler:
                self._stop_event.wait(self.poll_interval)
                continue

            with self._sub_lock:
                subscriptions_snapshot = [
                    {
                        "symbol": item["symbol"],
                        "exchange": item["exchange"],
                        "modes": set(item["modes"]),
                    }
                    for item in self.subscriptions.values()
                ]

            for sub in subscriptions_snapshot:
                symbol = sub["symbol"]
                exchange = sub["exchange"]
                modes = sub["modes"]

                quote_data = None
                depth_data = None

                try:
                    if self.MODE_LTP in modes or self.MODE_QUOTE in modes:
                        quote_data = self.data_handler.get_quotes(symbol, exchange)

                    if self.MODE_DEPTH in modes:
                        depth_data = self.data_handler.get_depth(symbol, exchange)
                except Exception as exc:
                    self.logger.debug(f"IIFL Capital poll failed for {exchange}:{symbol}: {exc}")
                    continue

                if self.MODE_LTP in modes and quote_data:
                    self._publish(symbol, exchange, self.MODE_LTP, self._as_ltp_payload(quote_data))

                if self.MODE_QUOTE in modes and quote_data:
                    self._publish(
                        symbol,
                        exchange,
                        self.MODE_QUOTE,
                        self._as_quote_payload(quote_data),
                    )

                if self.MODE_DEPTH in modes and depth_data:
                    self._publish(
                        symbol,
                        exchange,
                        self.MODE_DEPTH,
                        self._as_depth_payload(depth_data),
                    )

            self._stop_event.wait(self.poll_interval)

    def _publish(self, symbol: str, exchange: str, mode: int, data: dict[str, Any]):
        mode_str = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}.get(mode, "QUOTE")
        topic = f"{exchange}_{symbol}_{mode_str}"
        self.publish_market_data(topic, data)

    def _as_ltp_payload(self, quote: dict[str, Any]) -> dict[str, Any]:
        return {
            "ltp": quote.get("ltp", 0),
            "volume": quote.get("volume", 0),
            "timestamp": int(time.time()),
        }

    def _as_quote_payload(self, quote: dict[str, Any]) -> dict[str, Any]:
        prev_close = quote.get("prev_close", 0) or 0
        ltp = quote.get("ltp", 0) or 0
        change = float(ltp) - float(prev_close) if prev_close else 0
        change_pct = (change / float(prev_close) * 100) if prev_close else 0
        return {
            "open": quote.get("open", 0),
            "high": quote.get("high", 0),
            "low": quote.get("low", 0),
            "close": prev_close,
            "ltp": ltp,
            "volume": quote.get("volume", 0),
            "bid": quote.get("bid", 0),
            "ask": quote.get("ask", 0),
            "oi": quote.get("oi", 0),
            "change": change,
            "change_percent": change_pct,
            "timestamp": int(time.time()),
        }

    def _as_depth_payload(self, depth: dict[str, Any]) -> dict[str, Any]:
        buy = depth.get("buy") or depth.get("bids") or []
        sell = depth.get("sell") or depth.get("asks") or []

        # Convert bids/asks to market-data-service compatible buy/sell levels.
        buy_levels = [
            {
                "price": level.get("price", 0),
                "quantity": level.get("quantity", 0),
                "orders": level.get("orders", 0),
            }
            for level in buy[:20]
            if isinstance(level, dict)
        ]
        sell_levels = [
            {
                "price": level.get("price", 0),
                "quantity": level.get("quantity", 0),
                "orders": level.get("orders", 0),
            }
            for level in sell[:20]
            if isinstance(level, dict)
        ]

        return {
            "ltp": depth.get("ltp", 0),
            "open": depth.get("open", 0),
            "high": depth.get("high", 0),
            "low": depth.get("low", 0),
            "close": depth.get("prev_close", depth.get("close", 0)),
            "volume": depth.get("volume", 0),
            "depth": {"buy": buy_levels, "sell": sell_levels},
            "timestamp": int(time.time()),
        }
