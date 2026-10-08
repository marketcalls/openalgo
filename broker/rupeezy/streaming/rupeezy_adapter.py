"""Rupeezy Vortex websocket adapter -> OpenAlgo unified streaming.

Resolves OpenAlgo (symbol, exchange) to a Vortex ticker, drives the
RupeezyWebSocket client, normalizes ticks to the Zerodha adapter's key set and
publishes them on the ZeroMQ bus via the inherited publish_market_data().

Ticks carry only (vortex exchange, token), so they are routed back through a
(vortex exchange, token) -> subscription map. A symbol requested in several
modes is subscribed once at the richest mode; Vortex replaces the mode when
the same ticker is subscribed again.
"""

from broker.rupeezy.mapping.exchange import build_ticker
from broker.rupeezy.streaming.rupeezy_mapping import RupeezyCapabilityRegistry
from broker.rupeezy.streaming.rupeezy_websocket import RupeezyWebSocket
from database.auth_db import get_auth_token
from database.token_db import get_symbol_info
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

# Vortex packet mode -> OpenAlgo topic suffix.
_MODE_TO_TOPIC = {"ltp": "LTP", "ohlcv": "QUOTE", "full": "DEPTH"}


class RupeezyWebSocketAdapter(BaseBrokerWebSocketAdapter):
    def __init__(self):
        super().__init__()
        self.broker_name = "rupeezy"
        self.user_id = None
        self.ws_client: RupeezyWebSocket | None = None
        self.running = False
        # (vortex_exchange, token) -> {"symbol", "exchange", "ticker", "modes": set}
        self.instruments: dict[tuple[str, int], dict] = {}

    # --- lifecycle ------------------------------------------------------

    def initialize(self, broker_name, user_id, auth_data=None):
        try:
            self.broker_name = broker_name
            self.user_id = user_id
            access_token = None
            if auth_data:
                access_token = auth_data.get("auth_token") or auth_data.get("token")
            if not access_token:
                access_token = get_auth_token(user_id, bypass_cache=True)
            if not access_token:
                return self._create_error_response(
                    "NO_AUTH_TOKEN", f"No Rupeezy auth token found for user {user_id}"
                )
            self.ws_client = RupeezyWebSocket(
                access_token, on_ticks=self._on_ticks, user_id=user_id
            )
            # The proxy decides adapter reuse on self.connected; keep it truthful.
            self.ws_client.on_connect = self._on_ws_connect
            self.ws_client.on_disconnect = self._on_ws_disconnect
            return self._create_success_response("Rupeezy adapter initialized")
        except Exception as e:
            self.logger.exception("Error initializing Rupeezy adapter")
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
            # Subscriptions made before the socket opens are replayed on open.
            self.ws_client.wait_for_connection(timeout=15.0)
            self.connected = self.ws_client.is_connected()
            return self._create_success_response("Rupeezy WebSocket connecting")
        except Exception as e:
            self.logger.exception("Error connecting Rupeezy WebSocket")
            return self._create_error_response("CONNECT_ERROR", str(e))

    def disconnect(self):
        try:
            self.running = False
            self.connected = False
            if self.ws_client:
                self.ws_client.stop()
        except Exception:
            self.logger.exception("Error disconnecting Rupeezy WebSocket")
        finally:
            self.cleanup_zmq()

    # --- subscription ---------------------------------------------------

    @staticmethod
    def _resolve(symbol, exchange):
        info = get_symbol_info(symbol, exchange)
        if not info:
            return None
        try:
            token = int(info.token)
        except (TypeError, ValueError):
            return None
        return (info.brexchange, token), build_ticker(info.brexchange, info.brsymbol)

    @staticmethod
    def _richest_mode(modes):
        vortex_modes = [RupeezyCapabilityRegistry.get_vortex_mode(m) for m in modes]
        return max(vortex_modes, key=RupeezyCapabilityRegistry.MODE_RANK.get)

    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        try:
            if not self.ws_client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")
            resolved = self._resolve(symbol, exchange)
            if not resolved:
                return self._create_error_response(
                    "TOKEN_NOT_FOUND", f"No token for {exchange}:{symbol}"
                )
            key, ticker = resolved

            entry = self.instruments.setdefault(
                key, {"symbol": symbol, "exchange": exchange, "ticker": ticker, "modes": set()}
            )
            entry["modes"].add(mode)
            self.ws_client.subscribe(ticker, self._richest_mode(entry["modes"]))

            return self._create_success_response(
                f"Subscribed {exchange}:{symbol}",
                symbol=symbol,
                exchange=exchange,
                mode=mode,
                actual_depth=RupeezyCapabilityRegistry.get_fallback_depth_level(depth_level)
                if mode == 3
                else None,
            )
        except Exception as e:
            self.logger.exception(f"Error subscribing {exchange}:{symbol}")
            return self._create_error_response("SUBSCRIBE_ERROR", str(e))

    def unsubscribe(self, symbol, exchange, mode=2):
        try:
            if not self.ws_client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")
            resolved = self._resolve(symbol, exchange)
            if not resolved:
                return self._create_error_response(
                    "TOKEN_NOT_FOUND", f"No token for {exchange}:{symbol}"
                )
            key, ticker = resolved
            entry = self.instruments.get(key)
            if entry:
                entry["modes"].discard(mode)
                if entry["modes"]:
                    self.ws_client.subscribe(ticker, self._richest_mode(entry["modes"]))
                else:
                    self.instruments.pop(key, None)
                    self.ws_client.unsubscribe(ticker)
            return self._create_success_response(f"Unsubscribed {exchange}:{symbol}")
        except Exception as e:
            self.logger.exception(f"Error unsubscribing {exchange}:{symbol}")
            return self._create_error_response("UNSUBSCRIBE_ERROR", str(e))

    # --- ticks ----------------------------------------------------------

    def _on_ticks(self, ticks):
        for tick in ticks:
            try:
                entry = self.instruments.get((tick["exchange"], tick["token"]))
                if not entry:
                    continue
                topic_mode = _MODE_TO_TOPIC.get(tick["mode"], "QUOTE")
                data = self._normalize(tick, entry["symbol"], entry["exchange"], topic_mode)
                self.publish_market_data(
                    f"{entry['exchange']}_{entry['symbol']}_{topic_mode}", data
                )
            except Exception as e:
                self.logger.error(f"Error handling Rupeezy tick: {e}")

    @staticmethod
    def _normalize(tick, symbol, exchange, topic_mode):
        """Same key set as the Zerodha adapter so the proxy and UI see one shape."""
        ltp = tick.get("ltp", 0.0)
        ltt = tick.get("ltt")
        data = {
            "symbol": symbol,
            "exchange": exchange,
            "token": str(tick.get("token", "")),
            "ltp": ltp,
            "last_price": ltp,
            "ltt": ltt * 1000 if ltt else None,
            "timestamp": (tick.get("last_update_time") or ltt or 0) * 1000 or None,
        }
        close = tick.get("close")
        if close:
            data["close"] = close
            data["prev_close"] = close
            change = ltp - close
            data["change"] = round(change, 2)
            data["change_percent"] = round(change / close * 100, 2)

        if topic_mode in ("QUOTE", "DEPTH"):
            for k in ("open", "high", "low"):
                data[k] = tick.get(k, 0.0)
            data["volume"] = tick.get("volume", 0)
        if topic_mode == "DEPTH":
            data["last_quantity"] = tick.get("ltq", 0)
            data["average_price"] = tick.get("average_price", 0.0)
            data["total_buy_quantity"] = tick.get("total_buy_quantity", 0)
            data["total_sell_quantity"] = tick.get("total_sell_quantity", 0)
            data["oi"] = tick.get("oi", 0)
            data["open_interest"] = tick.get("oi", 0)
            data["depth"] = tick.get("depth", {"buy": [], "sell": []})
            data["upper_circuit"] = tick.get("upper_limit")
            data["lower_circuit"] = tick.get("lower_limit")
        return data
