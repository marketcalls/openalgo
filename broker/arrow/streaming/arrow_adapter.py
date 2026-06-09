"""Arrow WebSocket adapter -> OpenAlgo unified streaming.

Subclasses BaseBrokerWebSocketAdapter. Resolves OpenAlgo (symbol, exchange) to
Arrow integer tokens, drives the ArrowWebSocket client, normalizes ticks, and
publishes them to the ZeroMQ bus via the inherited publish_market_data().

NSE_INDEX / BSE_INDEX are first-class here: the websocket is token-based, so
indices subscribe exactly like any other instrument (their tokens come from the
master contract). The publish topic EXCHANGE_SYMBOL_MODE keeps the OpenAlgo
exchange (e.g. NSE_INDEX) -- the proxy already recognizes NSE_INDEX/BSE_INDEX as
two-segment prefixes when splitting topics.
"""

import os

from broker.arrow.streaming.arrow_mapping import ArrowCapabilityRegistry
from broker.arrow.streaming.arrow_websocket import ArrowWebSocket
from database.auth_db import get_auth_token
from database.token_db import get_token
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

# Arrow subscription mode -> OpenAlgo topic suffix. The proxy fans a higher mode
# down to lower-mode subscribers, so publishing to the tick's own mode topic is
# sufficient.
_MODE_TO_TOPIC = {
    "ltp": "LTP",
    "ltpc": "LTP",
    "quote": "QUOTE",
    "full": "DEPTH",
}


class ArrowWebSocketAdapter(BaseBrokerWebSocketAdapter):
    def __init__(self):
        super().__init__()
        self.broker_name = "arrow"
        self.user_id = None
        self.ws_client: ArrowWebSocket | None = None
        self.running = False
        # token(int) -> {"symbol", "exchange", "mode"(numeric)}
        self.token_info: dict[int, dict] = {}

    # --- lifecycle ------------------------------------------------------

    def initialize(self, broker_name, user_id, auth_data=None):
        try:
            self.broker_name = broker_name
            self.user_id = user_id

            app_id = os.getenv("BROKER_API_KEY")
            if auth_data and auth_data.get("token"):
                access_token = auth_data["token"]
            else:
                access_token = get_auth_token(user_id, bypass_cache=True)

            if not access_token:
                return self._create_error_response(
                    "NO_AUTH_TOKEN", f"No Arrow auth token found for user {user_id}"
                )
            if not app_id:
                return self._create_error_response(
                    "NO_APP_ID", "BROKER_API_KEY (appID) not configured"
                )

            self.ws_client = ArrowWebSocket(
                app_id=app_id,
                access_token=access_token,
                on_ticks=self._on_ticks,
                user_id=user_id,
            )
            self.logger.info(f"Arrow adapter initialized for user {user_id}")
            return self._create_success_response("Arrow adapter initialized")
        except Exception as e:
            self.logger.exception(f"Error initializing Arrow adapter: {e}")
            return self._create_error_response("INIT_ERROR", str(e))

    def connect(self):
        try:
            if not self.ws_client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")
            self.ws_client.start()
            self.running = True
            # Best-effort wait; subscriptions queue until connected regardless.
            self.ws_client.wait_for_connection(timeout=15.0)
            return self._create_success_response("Arrow WebSocket connecting")
        except Exception as e:
            self.logger.exception(f"Error connecting Arrow WebSocket: {e}")
            return self._create_error_response("CONNECT_ERROR", str(e))

    def disconnect(self):
        try:
            self.running = False
            if self.ws_client:
                self.ws_client.stop()
        except Exception as e:
            self.logger.exception(f"Error disconnecting Arrow WebSocket: {e}")
        finally:
            # Always release ZMQ resources (FD hygiene).
            self.cleanup_zmq()

    # --- subscription ---------------------------------------------------

    def _resolve_token(self, symbol, exchange):
        token = get_token(symbol, exchange)
        if token is None:
            return None
        try:
            return int(token)
        except (ValueError, TypeError):
            self.logger.error(f"Non-integer Arrow token for {exchange}:{symbol}: {token!r}")
            return None

    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        try:
            if not self.ws_client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")

            token = self._resolve_token(symbol, exchange)
            if token is None:
                return self._create_error_response(
                    "TOKEN_NOT_FOUND", f"No token for {exchange}:{symbol}"
                )

            arrow_mode = ArrowCapabilityRegistry.get_arrow_mode_for_numeric(mode)

            self.token_info[token] = {"symbol": symbol, "exchange": exchange, "mode": mode}
            self.ws_client.set_token_exchange_mapping({token: exchange})
            self.ws_client.subscribe_tokens([token], arrow_mode)

            # Arrow supports 5-level depth only; advertise the actual depth so the
            # proxy reports it back to the client.
            actual_depth = ArrowCapabilityRegistry.get_fallback_depth_level(depth_level, exchange)
            return self._create_success_response(
                f"Subscribed {exchange}:{symbol}",
                symbol=symbol,
                exchange=exchange,
                mode=mode,
                actual_depth=actual_depth if mode == 3 else None,
            )
        except Exception as e:
            self.logger.exception(f"Error subscribing {exchange}:{symbol}: {e}")
            return self._create_error_response("SUBSCRIBE_ERROR", str(e))

    def unsubscribe(self, symbol, exchange, mode=2):
        try:
            if not self.ws_client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")
            token = self._resolve_token(symbol, exchange)
            if token is None:
                return self._create_error_response(
                    "TOKEN_NOT_FOUND", f"No token for {exchange}:{symbol}"
                )
            self.ws_client.unsubscribe([token])
            self.token_info.pop(token, None)
            return self._create_success_response(f"Unsubscribed {exchange}:{symbol}")
        except Exception as e:
            self.logger.exception(f"Error unsubscribing {exchange}:{symbol}: {e}")
            return self._create_error_response("UNSUBSCRIBE_ERROR", str(e))

    # --- tick handling --------------------------------------------------

    def _on_ticks(self, ticks):
        for tick in ticks:
            try:
                token = tick.get("token")
                info = self.token_info.get(token)
                if not info:
                    continue
                symbol = info["symbol"]
                exchange = info["exchange"]
                arrow_mode = tick.get("mode", "quote")
                topic_mode = _MODE_TO_TOPIC.get(arrow_mode, "QUOTE")

                data = self._normalize(tick, symbol, exchange, topic_mode)
                topic = f"{exchange}_{symbol}_{topic_mode}"
                self.publish_market_data(topic, data)
            except Exception as e:
                self.logger.error(f"Error handling Arrow tick: {e}")

    def _normalize(self, tick, symbol, exchange, topic_mode):
        """Build the OpenAlgo normalized tick. Currently emits LTP (+prev close);
        OHLC/volume/depth are filled once the quote/full binary offsets are
        confirmed (see arrow_websocket._parse_packet TODO)."""
        data = {
            "symbol": symbol,
            "exchange": exchange,
            "token": str(tick.get("token", "")),
            "ltp": tick.get("ltp", 0),
            "last_price": tick.get("ltp", 0),
            "timestamp": tick.get("timestamp"),
        }
        if "close" in tick:
            data["prev_close"] = tick["close"]
            data["close"] = tick["close"]

        if topic_mode in ("QUOTE", "DEPTH"):
            # Placeholders until quote/full offsets are confirmed.
            for k in ("open", "high", "low", "volume", "average_price",
                      "total_buy_quantity", "total_sell_quantity", "oi"):
                if k in tick:
                    data[k] = tick[k]
        if topic_mode == "DEPTH" and "depth" in tick:
            data["depth"] = tick["depth"]

        return data
