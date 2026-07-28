"""
TradeSmart (Noren v2) WebSocket Adapter for OpenAlgo

Bridges TradeSmart's JSON market-data feed to OpenAlgo's unified WebSocket proxy
via ZeroMQ. Mirrors the flattrade adapter (same Noren JSON protocol).
"""

import json
import logging
import os
import sys
import threading
import time
import uuid
from typing import Any

from broker.tradesmart.api.baseurl import parse_auth, resolve_uid
from database.auth_db import get_auth_token

# Add parent directory to path to allow imports FIRST
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

# CRITICAL: load .env (sets ZMQ_PORT) before any WebSocket server init
import utils.config  # noqa: F401  (side-effect: loads .env)

if not os.getenv("ZMQ_PORT"):
    os.environ["ZMQ_PORT"] = "5555"

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .tradesmart_mapping import TradeSmartCapabilityRegistry, TradeSmartExchangeMapper
from .tradesmart_websocket import TradeSmartWebSocket


class Config:
    MAX_RECONNECT_ATTEMPTS = 10
    BASE_RECONNECT_DELAY = 5
    MAX_RECONNECT_DELAY = 60

    MODE_LTP = 1
    MODE_QUOTE = 2
    MODE_DEPTH = 3

    MSG_AUTH = "ak"
    MSG_TOUCHLINE_FULL = "tf"
    MSG_TOUCHLINE_PARTIAL = "tk"
    MSG_DEPTH_FULL = "df"
    MSG_DEPTH_PARTIAL = "dk"


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "" or value == "-":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value is None or value == "" or value == "-":
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


class MarketDataCache:
    """Thread-safe cache that merges partial Noren updates into full snapshots."""

    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def update(self, token: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            cached = self._cache.get(token, {})
            merged = cached.copy()
            for key, value in data.items():
                # Preserve a good cached OHLC/ap when a partial sends zero/blank
                if key in ("o", "h", "l", "c", "ap") and value in (None, "", "0", 0, "0.0", 0.0):
                    if cached.get(key) not in (None, "", "0", 0, "0.0", 0.0):
                        continue
                merged[key] = value
            for key, value in cached.items():
                if key not in data:
                    merged[key] = value
            self._cache[token] = merged
            return merged.copy()

    def clear(self, token: str = None) -> None:
        with self._lock:
            if token:
                self._cache.pop(token, None)
            else:
                self._cache.clear()


class TradeSmartWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """TradeSmart WebSocket adapter."""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("tradesmart_websocket")

        self.user_id = None
        self.broker_name = "tradesmart"
        self.actid = None
        self.accesstoken = None
        self.ws_client = None

        self.market_cache = MarketDataCache()
        self.subscriptions = {}
        self.token_to_symbol = {}
        self.ws_subscription_refs = {}

        self.running = False
        self.connected = False
        self.lock = threading.Lock()
        self.reconnect_attempts = 0
        self._reconnect_timer = None

        # Batch subscription coalescing
        self.subscription_queue = []
        self.batch_timer = None
        self.batch_delay = 0.5

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> None:
        self.user_id = user_id
        self.broker_name = broker_name

        # The stored token may be a composite "<uid>:::<access_token>". Split it:
        # the WS connect needs the bare access token and the client id (actid).
        stored_token = get_auth_token(user_id, bypass_cache=True)
        token_uid, self.accesstoken = parse_auth(stored_token)
        self.actid = token_uid or resolve_uid(stored_token) or user_id

        if not self.actid or not self.accesstoken:
            self.logger.error(f"Missing TradeSmart credentials for user {user_id}")
            raise ValueError(f"Missing TradeSmart credentials for user {user_id}")

        self.ws_client = TradeSmartWebSocket(
            user_id=self.actid,
            actid=self.actid,
            accesstoken=self.accesstoken,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )
        self.running = True

    def connect(self) -> None:
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return
        self.logger.info("Connecting to TradeSmart WebSocket...")
        if self.ws_client.connect():
            self.connected = True
            self.reconnect_attempts = 0
            self.logger.info("Connected to TradeSmart WebSocket successfully")
        else:
            raise ConnectionError("Failed to connect to TradeSmart WebSocket")

    def disconnect(self) -> None:
        with self.lock:
            self.running = False
            if self._reconnect_timer:
                self._reconnect_timer.cancel()
                self._reconnect_timer = None
            if self.batch_timer:
                self.batch_timer.cancel()
                self.batch_timer = None
            self.subscription_queue.clear()
            if self.ws_client:
                self.ws_client.stop()
                self.ws_client = None

        self.market_cache.clear()
        self.cleanup_zmq()
        self.connected = False
        self.logger.info("Disconnected from TradeSmart WebSocket")

    def __del__(self):
        try:
            self.cleanup_zmq()
        except Exception:
            pass

    def subscribe(
        self, symbol: str, exchange: str, mode: int = Config.MODE_QUOTE, depth_level: int = 5
    ) -> dict[str, Any]:
        try:
            if not self._validate_subscription_params(symbol, exchange, mode):
                return self._create_error_response(
                    "INVALID_PARAMS", "Invalid subscription parameters"
                )

            token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
            if not token_info:
                return self._create_error_response("SYMBOL_NOT_FOUND", f"Symbol {symbol} not found")

            subscription = self._create_subscription(
                symbol, exchange, mode, depth_level, token_info
            )
            unique_id = str(uuid.uuid4())[:8]
            correlation_id = f"{symbol}_{exchange}_{mode}_{unique_id}"
            base_correlation_id = f"{symbol}_{exchange}_{mode}"

            with self.lock:
                already_ws_subscribed = any(
                    cid.startswith(base_correlation_id) for cid in self.subscriptions.keys()
                )
                self.subscriptions[correlation_id] = subscription
                self.token_to_symbol[subscription["token"]] = (
                    subscription["symbol"],
                    subscription["exchange"],
                )
                if self.connected and not already_ws_subscribed:
                    self._websocket_subscribe(subscription)

            return self._create_success_response(
                f"Subscribed to {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
            )
        except Exception as e:
            self.logger.error(f"Subscription error for {symbol}.{exchange}: {e}")
            return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

    def unsubscribe(
        self, symbol: str, exchange: str, mode: int = Config.MODE_QUOTE
    ) -> dict[str, Any]:
        base_correlation_id = f"{symbol}_{exchange}_{mode}"
        with self.lock:
            matching = [
                (cid, sub)
                for cid, sub in self.subscriptions.items()
                if cid.startswith(base_correlation_id)
            ]
            if not matching:
                return self._create_error_response(
                    "NOT_SUBSCRIBED", f"Not subscribed to {symbol}.{exchange}"
                )

            correlation_id, subscription = matching[0]
            is_last = len(matching) == 1
            del self.subscriptions[correlation_id]

            token = subscription["token"]
            if not any(sub["token"] == token for sub in self.subscriptions.values()):
                self.token_to_symbol.pop(token, None)

            if is_last:
                self._websocket_unsubscribe(subscription)

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
        )

    def _validate_subscription_params(self, symbol: str, exchange: str, mode: int) -> bool:
        return bool(symbol) and bool(exchange) and mode in (
            Config.MODE_LTP,
            Config.MODE_QUOTE,
            Config.MODE_DEPTH,
        )

    def _create_subscription(
        self, symbol: str, exchange: str, mode: int, depth_level: int, token_info: dict
    ) -> dict:
        token = token_info["token"]
        brexchange = token_info["brexchange"]
        ts_exchange = TradeSmartExchangeMapper.to_tradesmart_exchange(brexchange)
        scrip = f"{ts_exchange}|{token}"
        return {
            "symbol": symbol,
            "exchange": exchange,
            "mode": mode,
            "depth_level": depth_level,
            "token": token,
            "scrip": scrip,
        }

    def _websocket_subscribe(self, subscription: dict) -> None:
        """Reference-count a scrip and queue it for a batched subscribe. Holds self.lock."""
        scrip = subscription["scrip"]
        mode = subscription["mode"]
        if scrip not in self.ws_subscription_refs:
            self.ws_subscription_refs[scrip] = {"touchline_count": 0, "depth_count": 0}

        if mode in (Config.MODE_LTP, Config.MODE_QUOTE):
            if self.ws_subscription_refs[scrip]["touchline_count"] == 0:
                self._queue_subscription(scrip, "touchline")
            self.ws_subscription_refs[scrip]["touchline_count"] += 1
        elif mode == Config.MODE_DEPTH:
            if self.ws_subscription_refs[scrip]["depth_count"] == 0:
                self._queue_subscription(scrip, "depth")
            self.ws_subscription_refs[scrip]["depth_count"] += 1

    def _queue_subscription(self, scrip: str, sub_type: str) -> None:
        self.subscription_queue.append({"scrip": scrip, "type": sub_type})
        if len(self.subscription_queue) == 1:
            self._start_batch_timer()

    def _start_batch_timer(self) -> None:
        if self.batch_timer:
            self.batch_timer.cancel()
        self.batch_timer = threading.Timer(self.batch_delay, self._process_batch_subscriptions)
        self.batch_timer.daemon = True
        self.batch_timer.start()

    def _process_batch_subscriptions(self) -> None:
        with self.lock:
            self.batch_timer = None
            if not self.subscription_queue:
                return
            touchline_scrips, depth_scrips = [], []
            seen_t, seen_d = set(), set()
            for sub in self.subscription_queue:
                scrip = sub["scrip"]
                if sub["type"] == "touchline" and scrip not in seen_t:
                    seen_t.add(scrip)
                    touchline_scrips.append(scrip)
                elif sub["type"] == "depth" and scrip not in seen_d:
                    seen_d.add(scrip)
                    depth_scrips.append(scrip)
            self.subscription_queue.clear()
            ws_client = self.ws_client
            connected = self.connected

        if not ws_client or not connected:
            self.logger.warning("Skipping batch flush - not connected; resubscribe handles it")
            return

        if touchline_scrips:
            try:
                ws_client.subscribe_touchline("#".join(touchline_scrips))
            except Exception as e:
                self.logger.error(f"Batch touchline subscription failed: {e}")
        if depth_scrips:
            try:
                ws_client.subscribe_depth("#".join(depth_scrips))
            except Exception as e:
                self.logger.error(f"Batch depth subscription failed: {e}")

    def _websocket_unsubscribe(self, subscription: dict) -> None:
        scrip = subscription["scrip"]
        mode = subscription["mode"]
        if scrip not in self.ws_subscription_refs:
            return
        if mode in (Config.MODE_LTP, Config.MODE_QUOTE):
            self.ws_subscription_refs[scrip]["touchline_count"] -= 1
            if self.ws_subscription_refs[scrip]["touchline_count"] <= 0:
                if self.ws_client:
                    self.ws_client.unsubscribe_touchline(scrip)
                self.ws_subscription_refs[scrip]["touchline_count"] = 0
        elif mode == Config.MODE_DEPTH:
            self.ws_subscription_refs[scrip]["depth_count"] -= 1
            if self.ws_subscription_refs[scrip]["depth_count"] <= 0:
                if self.ws_client:
                    self.ws_client.unsubscribe_depth(scrip)
                self.ws_subscription_refs[scrip]["depth_count"] = 0

    def _on_open(self, ws):
        self.logger.info("Connected to TradeSmart WebSocket")
        self.connected = True
        self._resubscribe_all()

    def _on_error(self, ws, error):
        self.logger.error(f"TradeSmart WebSocket error: {error}")
        if self.running:
            self._schedule_reconnection()

    def _on_close(self, ws, close_status_code, close_msg):
        self.logger.info(f"TradeSmart WebSocket closed: {close_status_code} - {close_msg}")
        self.connected = False
        with self.lock:
            if self.batch_timer:
                self.batch_timer.cancel()
                self.batch_timer = None
            self.subscription_queue.clear()
        if self.running:
            self._schedule_reconnection()

    def _schedule_reconnection(self) -> None:
        with self.lock:
            if not self.running:
                return
            if self.reconnect_attempts >= Config.MAX_RECONNECT_ATTEMPTS:
                self.logger.error("Maximum reconnection attempts reached")
                self.running = False
                return
            delay = min(
                Config.BASE_RECONNECT_DELAY * (2**self.reconnect_attempts),
                Config.MAX_RECONNECT_DELAY,
            )
            self.logger.info(f"Reconnecting in {delay}s (attempt {self.reconnect_attempts + 1})")
            if self._reconnect_timer:
                self._reconnect_timer.cancel()
            self._reconnect_timer = threading.Timer(delay, self._attempt_reconnection)
            self._reconnect_timer.daemon = True
            self._reconnect_timer.start()

    def _attempt_reconnection(self) -> None:
        with self.lock:
            self._reconnect_timer = None
            if not self.running:
                return
            self.reconnect_attempts += 1
            try:
                if self.ws_client:
                    try:
                        self.ws_client.stop()
                    except Exception as cleanup_err:
                        self.logger.warning(f"Error cleaning up old WebSocket: {cleanup_err}")
                    self.ws_client = None

                # Re-read a fresh token — TradeSmart tokens roll over daily ~3 AM IST
                fresh_token = get_auth_token(self.user_id, bypass_cache=True)
                if fresh_token:
                    fresh_uid, self.accesstoken = parse_auth(fresh_token)
                    if fresh_uid:
                        self.actid = fresh_uid

                self.ws_client = TradeSmartWebSocket(
                    user_id=self.actid,
                    actid=self.actid,
                    accesstoken=self.accesstoken,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                )
                if self.ws_client.connect():
                    self.connected = True
                    self.reconnect_attempts = 0
                    self.logger.info("Reconnected successfully")
                else:
                    self.logger.error("Reconnection failed")
            except Exception as e:
                self.logger.error(f"Reconnection error: {e}")

    def _resubscribe_all(self):
        with self.lock:
            self.ws_subscription_refs = {}
            touchline_scrips, depth_scrips = set(), set()
            for subscription in self.subscriptions.values():
                scrip = subscription["scrip"]
                mode = subscription["mode"]
                if scrip not in self.ws_subscription_refs:
                    self.ws_subscription_refs[scrip] = {"touchline_count": 0, "depth_count": 0}
                if mode in (Config.MODE_LTP, Config.MODE_QUOTE):
                    touchline_scrips.add(scrip)
                    self.ws_subscription_refs[scrip]["touchline_count"] += 1
                elif mode == Config.MODE_DEPTH:
                    depth_scrips.add(scrip)
                    self.ws_subscription_refs[scrip]["depth_count"] += 1

            if touchline_scrips and self.ws_client:
                self.ws_client.subscribe_touchline("#".join(touchline_scrips))
            if depth_scrips and self.ws_client:
                self.ws_client.subscribe_depth("#".join(depth_scrips))

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            msg_type = data.get("t")
            if msg_type == Config.MSG_AUTH:
                self.logger.info(f"Authentication response: {data}")
                return
            if msg_type in (
                Config.MSG_TOUCHLINE_FULL,
                Config.MSG_TOUCHLINE_PARTIAL,
                Config.MSG_DEPTH_FULL,
                Config.MSG_DEPTH_PARTIAL,
            ):
                self._process_market_message(data)
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}, message: {message}")
        except Exception as e:
            self.logger.error(f"Message processing error: {e}", exc_info=True)

    def _process_market_message(self, data: dict[str, Any]) -> None:
        msg_type = data.get("t")
        token = data.get("tk")
        if not msg_type or not token or token not in self.token_to_symbol:
            return

        symbol, exchange = self.token_to_symbol.get(token, (None, None))
        if not symbol:
            return

        with self.lock:
            matching = [sub for sub in self.subscriptions.values() if sub["token"] == token]

        for subscription in matching:
            if self._should_process_message(msg_type, subscription["mode"]):
                self._publish_subscription(data, subscription, symbol, exchange)

    def _should_process_message(self, msg_type: str, mode: int) -> bool:
        touchline = {Config.MSG_TOUCHLINE_FULL, Config.MSG_TOUCHLINE_PARTIAL}
        depth = {Config.MSG_DEPTH_FULL, Config.MSG_DEPTH_PARTIAL}
        if mode in (Config.MODE_LTP, Config.MODE_QUOTE):
            return msg_type in touchline
        if mode == Config.MODE_DEPTH:
            return msg_type in depth
        return False

    def _publish_subscription(self, data: dict, subscription: dict, symbol: str, exchange: str):
        mode = subscription["mode"]
        msg_type = data.get("t")
        normalized = self._normalize_market_data(data, msg_type, mode)
        normalized.update(
            {"symbol": symbol, "exchange": exchange, "timestamp": int(time.time() * 1000)}
        )
        mode_str = {Config.MODE_LTP: "LTP", Config.MODE_QUOTE: "QUOTE", Config.MODE_DEPTH: "DEPTH"}[
            mode
        ]
        topic = f"{exchange}_{symbol}_{mode_str}"
        try:
            self.publish_market_data(topic, normalized)
        except Exception as e:
            self.logger.error(f"Failed to publish data: {e}")

    def _normalize_market_data(self, data, msg_type, mode):
        token = data.get("tk")
        if token:
            data = self.market_cache.update(token, data)

        if mode == Config.MODE_LTP:
            return {
                "mode": Config.MODE_LTP,
                "ltp": safe_float(data.get("lp")),
                "tradesmart_timestamp": safe_int(data.get("ft")),
            }

        result = {
            "mode": mode,
            "ltp": safe_float(data.get("lp")),
            "volume": safe_int(data.get("v")),
            "open": safe_float(data.get("o")),
            "high": safe_float(data.get("h")),
            "low": safe_float(data.get("l")),
            "close": safe_float(data.get("c")),
            "average_price": safe_float(data.get("ap")),
            "percent_change": safe_float(data.get("pc")),
            "last_quantity": safe_int(data.get("ltq")),
            "last_trade_time": data.get("ltt"),
            "total_buy_quantity": safe_int(data.get("tbq")),
            "total_sell_quantity": safe_int(data.get("tsq")),
            "oi": safe_int(data.get("oi")),
            "tradesmart_timestamp": safe_int(data.get("ft")),
        }

        if mode == Config.MODE_DEPTH:
            result["depth"] = {
                "buy": [
                    {
                        "price": safe_float(data.get(f"bp{i}")),
                        "quantity": safe_int(data.get(f"bq{i}")),
                        "orders": safe_int(data.get(f"bo{i}")),
                    }
                    for i in range(1, 6)
                ],
                "sell": [
                    {
                        "price": safe_float(data.get(f"sp{i}")),
                        "quantity": safe_int(data.get(f"sq{i}")),
                        "orders": safe_int(data.get(f"so{i}")),
                    }
                    for i in range(1, 6)
                ],
            }
            result["depth_level"] = 5
            result.update(
                {
                    "upper_circuit": safe_float(data.get("uc")),
                    "lower_circuit": safe_float(data.get("lc")),
                    "52_week_high": safe_float(data.get("52h")),
                    "52_week_low": safe_float(data.get("52l")),
                }
            )

        return result

    def unsubscribe_all(self) -> dict[str, Any]:
        try:
            with self.lock:
                if not self.connected or not self.ws_client:
                    return self._create_error_response("NOT_CONNECTED", "WebSocket not connected")

                touchline_scrips, depth_scrips = set(), set()
                for subscription in self.subscriptions.values():
                    scrip = subscription["scrip"]
                    if subscription["mode"] in (Config.MODE_LTP, Config.MODE_QUOTE):
                        touchline_scrips.add(scrip)
                    elif subscription["mode"] == Config.MODE_DEPTH:
                        depth_scrips.add(scrip)

                if touchline_scrips:
                    self.ws_client.unsubscribe_touchline("#".join(touchline_scrips))
                if depth_scrips:
                    self.ws_client.unsubscribe_depth("#".join(depth_scrips))

                if self.batch_timer:
                    self.batch_timer.cancel()
                    self.batch_timer = None
                self.subscription_queue.clear()

                count = len(self.subscriptions)
                self.subscriptions.clear()
                self.token_to_symbol.clear()
                self.ws_subscription_refs.clear()
                self.market_cache.clear()

            return self._create_success_response(
                f"Unsubscribed from all {count} subscriptions. Connection kept alive.",
                unsubscribed_count=count,
                connection_status="active",
            )
        except Exception as e:
            self.logger.error(f"Error in unsubscribe_all: {e}")
            return self._create_error_response("UNSUBSCRIBE_ALL_ERROR", str(e))
