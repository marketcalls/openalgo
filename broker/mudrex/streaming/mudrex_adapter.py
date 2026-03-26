"""
OpenAlgo WebSocket adapter for Mudrex.

Mudrex does not provide a WebSocket API.  Market-data streaming is sourced
from the Bybit public v5 linear WebSocket feed, which uses the same symbol
naming convention as Mudrex (e.g. BTCUSDT, ETHUSDT).

Channels:
    orderbook.1.{SYMBOL}  — 1-level orderbook snapshot (best bid/ask)
    publicTrade.{SYMBOL}  — public trades (last price + volume)
    tickers.{SYMBOL}      — 24h ticker (OHLCV, mark price, OI)

Bybit sends a ``ping`` frame every 20 s; we reply with ``pong`` via the
websocket-client library's built-in handler.  Auto-reconnect is managed
by a blocking retry loop with exponential back-off.

NOTE: Order / position updates cannot come from Bybit WS and must be
REST-polled from Mudrex.
"""

import json
import logging
import os
import sys
import threading
import time
from typing import Any

import websocket

from database.auth_db import get_auth_token
from database.token_db import get_br_symbol

sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"


class MudrexWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Bybit-backed WebSocket adapter for the Mudrex broker plugin."""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("mudrex_websocket_adapter")
        self.ws: websocket.WebSocketApp | None = None
        self.user_id: str | None = None
        self.broker_name = "mudrex"
        self.running = False
        self._lock = threading.Lock()
        self.last_values: dict[str, dict] = {}
        self._max_retries = 5
        self._retry_delay = 5
        self._retry_multiplier = 2

    # ── BaseBrokerWebSocketAdapter interface ─────────────────────────────

    def initialize(
        self,
        broker_name: str,
        user_id: str,
        auth_data: dict | None = None,
        **kwargs,
    ) -> None:
        self.user_id = user_id
        self.broker_name = broker_name
        self.running = True
        self.logger.info("MudrexWebSocketAdapter initialised for user %s", user_id)

    def connect(self) -> None:
        """Start the Bybit WS connection in a daemon thread with auto-reconnect."""
        threading.Thread(target=self._connect_loop, daemon=True).start()

    def _connect_loop(self) -> None:
        attempt = 0
        delay = self._retry_delay

        while self.running and attempt < self._max_retries:
            try:
                self.ws = websocket.WebSocketApp(
                    BYBIT_WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_ping=self._on_ping,
                )
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:
                self.logger.error("WS connection error: %s", exc)

            if not self.running:
                break
            attempt += 1
            self.logger.warning("Reconnecting in %ds (attempt %d/%d)", delay, attempt, self._max_retries)
            time.sleep(delay)
            delay = min(delay * self._retry_multiplier, 60)

    def disconnect(self) -> None:
        self.running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.cleanup_zmq()

    def subscribe(
        self,
        symbol: str,
        exchange: str,
        mode: int = 2,
        depth_level: int = 1,
    ) -> dict[str, Any]:
        br_symbol = get_br_symbol(symbol, exchange) or symbol
        corr_id = f"{symbol}_{exchange}_{mode}"

        with self._lock:
            self.subscriptions[corr_id] = {
                "symbol": symbol,
                "exchange": exchange,
                "br_symbol": br_symbol,
                "mode": mode,
            }

        topics = self._topics_for_symbol(br_symbol, mode)
        self._send_subscribe(topics)

        return self._create_success_response(
            f"Subscribed to {symbol}.{exchange}",
            symbol=symbol, exchange=exchange, mode=mode,
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        corr_id = f"{symbol}_{exchange}_{mode}"
        br_symbol: str = symbol

        with self._lock:
            stored = self.subscriptions.pop(corr_id, None)
            br_symbol = (stored or {}).get("br_symbol") or symbol
            if not self.subscriptions:
                self.disconnect()
                return self._create_success_response(f"Unsubscribed from {symbol}.{exchange}")

        topics = self._topics_for_symbol(br_symbol, mode)
        self._send_unsubscribe(topics)

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol, exchange=exchange, mode=mode,
        )

    # ── internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _topics_for_symbol(br_symbol: str, mode: int) -> list[str]:
        if mode == 3:
            return [f"orderbook.1.{br_symbol}"]
        return [f"tickers.{br_symbol}", f"publicTrade.{br_symbol}"]

    def _send_subscribe(self, topics: list[str]) -> None:
        if self.ws and self.ws.sock and self.ws.sock.connected:
            msg = json.dumps({"op": "subscribe", "args": topics})
            self.ws.send(msg)
            self.logger.info("Bybit WS subscribe: %s", topics)

    def _send_unsubscribe(self, topics: list[str]) -> None:
        if self.ws and self.ws.sock and self.ws.sock.connected:
            msg = json.dumps({"op": "unsubscribe", "args": topics})
            self.ws.send(msg)
            self.logger.info("Bybit WS unsubscribe: %s", topics)

    # ── WS callbacks ─────────────────────────────────────────────────────

    def _on_open(self, wsapp) -> None:
        self.logger.info("Bybit WS connected")
        self.connected = True

        with self._lock:
            all_topics: list[str] = []
            for sub in self.subscriptions.values():
                all_topics.extend(self._topics_for_symbol(sub["br_symbol"], sub["mode"]))
        if all_topics:
            self._send_subscribe(all_topics)

    def _on_error(self, wsapp, error) -> None:
        self.logger.error("Bybit WS error: %s", error)

    def _on_close(self, wsapp, close_status_code=None, close_msg=None) -> None:
        self.logger.info("Bybit WS closed (code=%s)", close_status_code)
        self.connected = False

    def _on_ping(self, wsapp, data) -> None:
        if self.ws:
            self.ws.send("", opcode=0xA)

    def _on_message(self, wsapp, raw_msg: str) -> None:
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError:
            return

        topic = msg.get("topic", "")
        data = msg.get("data")
        if not topic or not data:
            return

        if topic.startswith("tickers."):
            self._handle_ticker(topic, data)
        elif topic.startswith("publicTrade."):
            self._handle_trade(topic, data)
        elif topic.startswith("orderbook."):
            self._handle_orderbook(topic, data)

    # ── data normalization + ZMQ publish ──────────────────────────────────

    def _resolve_symbol(self, br_symbol: str) -> tuple[str, str] | None:
        """Find the OpenAlgo (symbol, exchange) for a Bybit br_symbol."""
        with self._lock:
            for sub in self.subscriptions.values():
                if sub.get("br_symbol") == br_symbol:
                    return sub["symbol"], sub["exchange"]
        return None

    def _handle_ticker(self, topic: str, data: dict) -> None:
        br_symbol = topic.split(".", 1)[1] if "." in topic else ""
        resolved = self._resolve_symbol(br_symbol)
        if not resolved:
            return
        symbol, exchange = resolved
        cache_key = f"{symbol}_{exchange}"

        ltp = float(data.get("lastPrice", 0) or 0)
        if ltp <= 0:
            return

        prev = self.last_values.get(cache_key, {})
        tick = {
            "symbol": symbol,
            "exchange": exchange,
            "ltp": ltp,
            "open": float(data.get("prevPrice24h", prev.get("open", 0)) or 0),
            "high": float(data.get("highPrice24h", prev.get("high", 0)) or 0),
            "low": float(data.get("lowPrice24h", prev.get("low", 0)) or 0),
            "close": ltp,
            "volume": int(float(data.get("volume24h", 0) or 0)),
            "oi": float(data.get("openInterest", 0) or 0),
            "bid": float(data.get("bid1Price", 0) or 0),
            "ask": float(data.get("ask1Price", 0) or 0),
        }
        self.last_values[cache_key] = tick
        self.publish_market_data(f"tick.{symbol}.{exchange}", tick)

    def _handle_trade(self, topic: str, data) -> None:
        if isinstance(data, list) and data:
            trade = data[0]
        elif isinstance(data, dict):
            trade = data
        else:
            return

        br_symbol = topic.split(".", 1)[1] if "." in topic else ""
        resolved = self._resolve_symbol(br_symbol)
        if not resolved:
            return
        symbol, exchange = resolved
        cache_key = f"{symbol}_{exchange}"

        ltp = float(trade.get("p", 0) or 0)
        if ltp <= 0:
            return

        prev = self.last_values.get(cache_key, {})
        tick = {**prev, "symbol": symbol, "exchange": exchange, "ltp": ltp, "close": ltp}
        self.last_values[cache_key] = tick
        self.publish_market_data(f"tick.{symbol}.{exchange}", tick)

    def _handle_orderbook(self, topic: str, data: dict) -> None:
        parts = topic.split(".")
        br_symbol = parts[2] if len(parts) > 2 else ""
        resolved = self._resolve_symbol(br_symbol)
        if not resolved:
            return
        symbol, exchange = resolved

        bids = [{"price": float(b[0]), "quantity": float(b[1])} for b in (data.get("b") or [])[:5]]
        asks = [{"price": float(a[0]), "quantity": float(a[1])} for a in (data.get("a") or [])[:5]]

        depth = {
            "symbol": symbol,
            "exchange": exchange,
            "bids": bids,
            "asks": asks,
        }
        self.publish_market_data(f"depth.{symbol}.{exchange}", depth)
