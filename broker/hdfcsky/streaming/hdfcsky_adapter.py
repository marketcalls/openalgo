"""HDFC Sky WebSocket adapter -> OpenAlgo unified streaming.

Subclasses BaseBrokerWebSocketAdapter. Resolves OpenAlgo (symbol, exchange) to
HDFC Sky scripIds, drives the HDFCSkyWebSocket client, normalizes protobuf
ticks and publishes them to the ZeroMQ bus via the inherited
publish_market_data().

NSE_INDEX / BSE_INDEX are first-class: the feed has dedicated NSE_INDEX_ /
BSE_INDEX_ scripId prefixes, and the publish topic keeps the OpenAlgo exchange
(the proxy already recognizes both as two-segment prefixes when splitting
topics).
"""

from broker.hdfcsky.mapping.exchange import ws_scrip_id
from broker.hdfcsky.streaming.hdfcsky_mapping import HDFCSkyCapabilityRegistry
from broker.hdfcsky.streaming.hdfcsky_websocket import HDFCSkyWebSocket
from database.auth_db import get_auth_token
from database.token_db import get_token
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

# OpenAlgo numeric mode -> topic suffix. The proxy fans a higher mode down to
# lower-mode subscribers, so publishing to the tick's own mode topic suffices.
_MODE_TO_TOPIC = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}


class HDFCSkyWebSocketAdapter(BaseBrokerWebSocketAdapter):
    def __init__(self):
        super().__init__()
        self.broker_name = "hdfcsky"
        self.user_id = None
        self.ws_client: HDFCSkyWebSocket | None = None
        self.running = False
        # token(int) -> {"symbol", "exchange", "mode", "scrip_id"}
        self.token_info: dict[int, dict] = {}

    # --- lifecycle ------------------------------------------------------

    def initialize(self, broker_name, user_id, auth_data=None):
        try:
            self.broker_name = broker_name
            self.user_id = user_id

            if auth_data and auth_data.get("token"):
                access_token = auth_data["token"]
            else:
                access_token = get_auth_token(user_id, bypass_cache=True)

            if not access_token:
                return self._create_error_response(
                    "NO_AUTH_TOKEN", f"No HDFC Sky auth token found for user {user_id}"
                )

            self.ws_client = HDFCSkyWebSocket(
                access_token=access_token,
                on_ticks=self._on_ticks,
                user_id=user_id,
            )
            # Keep self.connected truthful: the proxy gates adapter reuse on it
            # (server.py getattr(adapter, "connected", ...)); without these
            # hooks healthy adapters read as dead and get evicted/rebuilt.
            self.ws_client.on_connect = self._on_ws_connect
            self.ws_client.on_disconnect = self._on_ws_disconnect
            self.logger.info(f"HDFC Sky adapter initialized for user {user_id}")
            return self._create_success_response("HDFC Sky adapter initialized")
        except Exception as e:
            self.logger.exception(f"Error initializing HDFC Sky adapter: {e}")
            return self._create_error_response("INIT_ERROR", str(e))

    def _on_ws_connect(self):
        self.connected = True

    def _on_ws_disconnect(self):
        self.connected = False

    def connect(self):
        try:
            if not self.ws_client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")
            self.ws_client.start()
            self.running = True
            # Best-effort wait; subscriptions queue until connected regardless.
            self.ws_client.wait_for_connection(timeout=15.0)
            self.connected = self.ws_client.is_connected()
            return self._create_success_response("HDFC Sky WebSocket connecting")
        except Exception as e:
            self.logger.exception(f"Error connecting HDFC Sky WebSocket: {e}")
            return self._create_error_response("CONNECT_ERROR", str(e))

    def disconnect(self):
        try:
            self.running = False
            self.connected = False
            if self.ws_client:
                self.ws_client.stop()
        except Exception as e:
            self.logger.exception(f"Error disconnecting HDFC Sky WebSocket: {e}")
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
            self.logger.error(f"Non-integer HDFC Sky token for {exchange}:{symbol}: {token!r}")
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

            scrip_id = ws_scrip_id(exchange, token)
            subscription_type = HDFCSkyCapabilityRegistry.get_subscription_type_for_numeric(mode)

            self.token_info[token] = {
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
                "scrip_id": scrip_id,
            }
            self.ws_client.subscribe_scrips([scrip_id], subscription_type)

            # HDFC Sky publishes 5-level depth only; advertise the actual depth
            # so the proxy reports it back to the client.
            actual_depth = HDFCSkyCapabilityRegistry.get_fallback_depth_level(
                depth_level, exchange
            )
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
            self.ws_client.unsubscribe([ws_scrip_id(exchange, token)])
            self.token_info.pop(token, None)
            return self._create_success_response(f"Unsubscribed {exchange}:{symbol}")
        except Exception as e:
            self.logger.exception(f"Error unsubscribing {exchange}:{symbol}: {e}")
            return self._create_error_response("UNSUBSCRIBE_ERROR", str(e))

    # --- tick handling --------------------------------------------------

    def _on_ticks(self, ticks):
        for tick in ticks:
            try:
                info = self.token_info.get(tick.get("token"))
                if not info:
                    continue
                # Greek packets have no price fields; they arrive alongside the
                # MBP stream for options and are not part of the OpenAlgo tick
                # contract, so they are dropped here.
                if tick.get("kind") == "greek":
                    continue

                symbol = info["symbol"]
                exchange = info["exchange"]
                topic_mode = _MODE_TO_TOPIC.get(info["mode"], "QUOTE")

                data = self._normalize(tick, symbol, exchange, topic_mode)
                self.publish_market_data(f"{exchange}_{symbol}_{topic_mode}", data)
            except Exception as e:
                self.logger.error(f"Error handling HDFC Sky tick: {e}")

    def _normalize(self, tick, symbol, exchange, topic_mode):
        """Build the OpenAlgo normalized tick (same key set as the Zerodha
        adapter so the proxy/UI see one shape across brokers)."""
        ltp = tick.get("ltp", 0)
        data = {
            "symbol": symbol,
            "exchange": exchange,
            "token": str(tick.get("token", "")),
            "ltp": ltp,
            "last_price": ltp,
            "ltt": tick.get("ltt", tick.get("timestamp")),
            "timestamp": tick.get("timestamp"),
        }

        close = tick.get("close")
        if close is not None:
            data["close"] = close
            data["prev_close"] = close
            if close:
                change = ltp - close
                data["change"] = round(change, 2)
                data["change_percent"] = round(change / close * 100, 2)

        if topic_mode in ("QUOTE", "DEPTH"):
            data["volume"] = tick.get("volume", 0)
            data["last_quantity"] = tick.get("ltq", 0)
            data["average_price"] = tick.get("average_price", 0)
            data["total_buy_quantity"] = tick.get("total_buy_quantity", 0)
            data["total_sell_quantity"] = tick.get("total_sell_quantity", 0)
            for key in ("open", "high", "low"):
                if key in tick:
                    data[key] = tick[key]
            if "oi" in tick:
                data["oi"] = tick["oi"]
                data["open_interest"] = tick["oi"]

        if topic_mode == "DEPTH":
            if "depth" in tick:
                data["depth"] = tick["depth"]
            if "upper_limit" in tick:
                data["upper_circuit"] = tick["upper_limit"]
                data["lower_circuit"] = tick["lower_limit"]

        return data
