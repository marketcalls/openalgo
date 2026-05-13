"""
IIFL Capital WebSocket adapter — connects OpenAlgo's WebSocket proxy to the
IIFL Capital market-data feed over MQTT v3.1.1 (TLS port 8883).

Replaces the earlier REST-polling stub. The on-wire protocol is implemented
in-tree (`iiflcapital_mqtt.py`, `iiflcapital_websocket.py`) — no external SDK
dependency on `bridgePy` or `paho-mqtt`.

Shape mirrors the Zerodha adapter (broker/zerodha/streaming/zerodha_adapter.py)
so it plugs into the same ConnectionPool / BaseBrokerWebSocketAdapter
plumbing without special-casing.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from database.token_db import get_brexchange, get_token
from utils.logging import get_logger
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

from .iiflcapital_mapping import (
    is_index_exchange,
    normalize_segment,
    supports_open_interest,
)
from .iiflcapital_websocket import (
    MODE_FULL,
    MODE_LTP,
    MODE_QUOTE,
    IiflcapitalWebSocket,
)

logger = get_logger(__name__)


class IiflcapitalWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    OpenAlgo broker adapter for IIFL Capital's MQTT market-data feed.

    Mode contract (mirrors Zerodha):
        1 → LTP   (publish only `ltp` and `ltt`)
        2 → Quote (OHLC + LTP + bid/ask totals)
        3 → Depth (Quote + L5 depth)

    The IIFL broker only emits one packet shape per stream (188-byte
    MWBOCombined), so we subscribe once at the broker layer and slice the
    decoded dict into three OpenAlgo-shaped payloads on the way out, exactly
    like Zerodha's `full` → `ltp/quote/full` fan-out.
    """

    # OpenAlgo mode ints → internal IIFL feed mode strings.
    _MODE_OA_TO_IIFL = {1: MODE_LTP, 2: MODE_QUOTE, 3: MODE_FULL}

    def __init__(self) -> None:
        super().__init__()
        self.logger = get_logger("iiflcapital_websocket")
        self.broker_name = "iiflcapital"

        self.user_id: str | None = None
        self.auth_token: str | None = None
        self.ws_client: IiflcapitalWebSocket | None = None

        self.running = False
        self.connected = False
        self.lock = threading.Lock()

        # Subscription tracking, keyed by f"{exchange}:{symbol}":
        # {
        #   "exchange": str,           # OpenAlgo exchange (e.g. NSE_INDEX)
        #   "symbol": str,
        #   "segment": str,            # IIFL brexchange (NSEEQ, NSEFO, …)
        #   "token": str,
        #   "mode": int,               # OpenAlgo mode int (1/2/3)
        #   "is_index": bool,
        # }
        self.subscribed_symbols: dict[str, dict] = {}

        # Reverse lookup: f"{segment}/{token}" → (symbol, exchange) — used to
        # rebuild the OpenAlgo topic when a tick comes back from the broker.
        self._key_to_symbol: dict[str, tuple[str, str]] = {}

    # ----------------------------------------------------------------- lifecycle
    def initialize(
        self,
        broker_name: str,
        user_id: str,
        auth_data: dict[str, str] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Pull the user's IIFL session token and wire up the feed client."""
        if broker_name and broker_name.lower() != self.broker_name:
            return {"status": "error", "message": f"Invalid broker name: {broker_name}"}

        self.user_id = user_id

        # auth_data wins if supplied; otherwise pull from the DB. `force`
        # bypasses the cache so a stale daily-rolled token is not reused.
        auth_token = None
        if auth_data:
            auth_token = auth_data.get("auth_token")
        if force or not auth_token:
            auth_token = self.get_auth_token_for_user(user_id, bypass_cache=force)

        if not auth_token:
            return {
                "status": "error",
                "code": "AUTHENTICATION_ERROR",
                "message": f"No authentication token found for user {user_id}",
            }

        self.auth_token = auth_token

        # If initialize() is called a second time (e.g. issue #765 force re-init
        # after a token refresh) we must stop the previous feed client first.
        # Just dropping the reference is not enough: its reader/keepalive
        # threads hold a back-reference to the IiflMqttClient via `self`,
        # which would keep the old TLS socket and threads alive indefinitely.
        if self.ws_client is not None:
            try:
                self.ws_client.stop()
            except Exception as e:
                self.logger.debug(f"Error stopping previous IIFL feed client: {e}")
            self.ws_client = None

        try:
            self.ws_client = IiflcapitalWebSocket(
                user_session=auth_token,
                on_ticks=self._handle_ticks,
            )
            self.ws_client.on_connect = self._on_connect
            self.ws_client.on_disconnect = self._on_disconnect
            self.ws_client.on_error = self._on_error
        except Exception as e:
            self.logger.exception(f"Failed to create IIFL feed client: {e}")
            return {"status": "error", "message": str(e)}

        self.logger.info(f"IIFL Capital adapter initialized for user {user_id}")
        return {"status": "success", "message": "Adapter initialized successfully"}

    def connect(self) -> dict[str, Any]:
        if not self.ws_client:
            return {"status": "error", "message": "Adapter not initialized — call initialize() first"}

        with self.lock:
            if self.running and self.connected:
                return {"status": "success", "message": "Already connected"}

            started = self.ws_client.start()

            if started and self.ws_client.wait_for_connection(timeout=15.0):
                # Only flip running/connected once we know the broker
                # session is live. Leaving running=True on failure would
                # let subscribe() — which only checks self.running — push
                # work into a dead client and return success to the caller.
                self.running = True
                self.connected = True
                return {"status": "success", "message": "Connected"}

            # Connection failed: make sure no half-started state survives,
            # so the next subscribe() correctly rejects with "not connected".
            self.running = False
            self.connected = False
            # Best-effort teardown of any threads start() may have spawned
            # (reader/keepalive run only on accepted CONNACK, but reconnect
            # workers can be running after a transient timeout).
            try:
                self.ws_client.stop()
            except Exception as e:
                self.logger.debug(f"Error stopping ws_client after failed connect: {e}")

            if self.ws_client._fatal_error:  # noqa: SLF001 — surface auth failure quickly
                return {
                    "status": "error",
                    "message": f"IIFL auth failed: {self.ws_client._fatal_error_message}",  # noqa: SLF001
                }

            return {"status": "error", "message": "Connection timeout"}

    def disconnect(self) -> dict[str, Any]:
        try:
            with self.lock:
                if self.ws_client is not None:
                    try:
                        self.ws_client.stop()
                    except Exception as e:
                        self.logger.debug(f"Error stopping IIFL feed client: {e}")
                    self.ws_client = None

                self.running = False
                self.connected = False
                self.subscribed_symbols.clear()
                self._key_to_symbol.clear()

            self.cleanup_zmq()
            return {"status": "success", "message": "Disconnected"}
        except Exception as e:
            self.logger.exception(f"Error during disconnect: {e}")
            try:
                self.cleanup_zmq()
            except Exception:
                pass
            return {"status": "error", "message": str(e)}

    # ----------------------------------------------------------------- subscribe
    def subscribe(
        self,
        symbol: str,
        exchange: str,
        mode: int = 2,
        depth_level: int = 5,
    ) -> dict[str, Any]:
        """
        Subscribe a (symbol, exchange) at the requested mode.

        IIFL emits L5 depth natively; depth_level=20 is not supported and is
        clamped to 5 (we still echo `actual_depth: 5` in the response).
        """
        if mode not in self._MODE_OA_TO_IIFL:
            return {
                "status": "error",
                "code": "INVALID_MODE",
                "message": f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)",
            }

        if not self.ws_client or not self.running:
            return {"status": "error", "message": "WebSocket not connected. Call connect() first."}

        # Resolve the broker-side segment and token via the master contract DB.
        token = get_token(symbol, exchange)
        brexchange = get_brexchange(symbol, exchange)
        if not token or not brexchange:
            return {
                "status": "error",
                "message": f"Token / brexchange not found for {exchange}:{symbol}",
            }

        token = str(token).strip()
        segment = brexchange.strip()  # store uppercase; lower-casing happens in the feed client

        is_index = is_index_exchange(exchange)
        feed_mode = self._MODE_OA_TO_IIFL[mode]
        # OI is only meaningful for derivatives — see iiflcapital_mapping.
        include_oi = mode != 1 and supports_open_interest(exchange) and not is_index

        key = f"{exchange}:{symbol}"
        topic_suffix = f"{normalize_segment(segment)}/{token}"

        with self.lock:
            self.subscribed_symbols[key] = {
                "exchange": exchange,
                "symbol": symbol,
                "segment": segment,
                "token": token,
                "mode": mode,
                "is_index": is_index,
            }
            self._key_to_symbol[topic_suffix] = (symbol, exchange)

        try:
            self.ws_client.subscribe_instruments(
                instruments=[(segment, token)],
                mode=feed_mode,
                is_index=is_index,
                include_oi=include_oi,
            )
        except Exception as e:
            self.logger.exception(f"IIFL subscribe failed for {exchange}:{symbol}: {e}")
            return {"status": "error", "message": str(e)}

        self.logger.info(f"Subscribed to IIFL {exchange}:{symbol} (segment={segment} token=[REDACTED] mode={mode})")
        return {
            "status": "success",
            "symbol": symbol,
            "exchange": exchange,
            "mode": mode,
            "actual_depth": 5,
            "message": f"Subscribed to {symbol}",
        }

    def unsubscribe(
        self,
        symbol: str,
        exchange: str,
        mode: int | None = None,
        depth_level: int | None = None,
    ) -> dict[str, Any]:
        key = f"{exchange}:{symbol}"
        with self.lock:
            sub = self.subscribed_symbols.pop(key, None)
        if sub is None:
            return {"status": "error", "message": f"Not subscribed to {symbol}"}

        topic_suffix = f"{normalize_segment(sub['segment'])}/{sub['token']}"
        with self.lock:
            self._key_to_symbol.pop(topic_suffix, None)

        if self.ws_client:
            try:
                self.ws_client.unsubscribe_instruments([(sub["segment"], sub["token"])])
            except Exception as e:
                self.logger.exception(f"IIFL unsubscribe failed for {exchange}:{symbol}: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "success", "message": f"Unsubscribed from {symbol}"}

    # ----------------------------------------------------------------- ticks
    def _handle_ticks(self, ticks: list[dict]) -> None:
        """
        Receive decoded ticks from the IIFL feed client and fan them out to
        the OpenAlgo ZeroMQ bus, slicing the single broker packet into LTP /
        Quote / Depth topics as needed.
        """
        if not ticks:
            return

        for tick in ticks:
            try:
                segment = tick.get("segment", "")
                token = tick.get("token", "")
                suffix = f"{segment}/{token}"

                with self.lock:
                    symbol_info = self._key_to_symbol.get(suffix)
                    sub_info = None
                    if symbol_info:
                        key = f"{symbol_info[1]}:{symbol_info[0]}"
                        sub_info = self.subscribed_symbols.get(key)

                if not symbol_info or not sub_info:
                    self.logger.debug(f"No active subscription for IIFL tick {suffix}")
                    continue

                symbol, exchange = symbol_info
                sub_mode = sub_info["mode"]

                # The feed client always returns the full decoded packet; we
                # produce per-mode payloads from the same source dict.
                base = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "ltp": tick.get("ltp", 0),
                    "ltt": tick.get("ltt", 0),
                    "timestamp": tick.get("timestamp", int(time.time() * 1000)),
                }

                if sub_mode == 1:
                    payload = {**base, "mode": "ltp"}
                    self._publish(symbol, exchange, "LTP", payload)
                    continue

                # Quote / Depth share the OHLC + bid/ask + volume block.
                payload = {
                    **base,
                    "open": tick.get("open", 0),
                    "high": tick.get("high", 0),
                    "low": tick.get("low", 0),
                    "close": tick.get("close", 0),
                    "volume": tick.get("volume", 0),
                    "last_quantity": tick.get("last_traded_quantity", 0),
                    "average_price": tick.get("average_price", 0),
                    "total_buy_quantity": tick.get("total_buy_quantity", 0),
                    "total_sell_quantity": tick.get("total_sell_quantity", 0),
                    "bid": tick.get("best_bid_price", 0),
                    "ask": tick.get("best_ask_price", 0),
                    "bid_quantity": tick.get("best_bid_quantity", 0),
                    "ask_quantity": tick.get("best_ask_quantity", 0),
                }

                # Open interest is only carried on the tick when the feed
                # client merged it in (derivatives, non-LTP modes). Surfaced
                # as both `oi` and `open_interest` for client compatibility.
                if "open_interest" in tick:
                    payload["oi"] = tick["open_interest"]
                    payload["open_interest"] = tick["open_interest"]

                if sub_mode == 2:
                    payload["mode"] = "quote"
                    self._publish(symbol, exchange, "QUOTE", payload)
                else:  # mode 3 — depth
                    payload["mode"] = "full"
                    payload["depth"] = tick.get("depth", {"buy": [], "sell": []})
                    self._publish(symbol, exchange, "DEPTH", payload)

            except Exception as e:
                self.logger.exception(f"Error processing IIFL tick: {e}")

    def _publish(self, symbol: str, exchange: str, mode_str: str, data: dict) -> None:
        topic = f"{exchange}_{symbol}_{mode_str}"
        self.publish_market_data(topic, data)

    # ----------------------------------------------------------------- callbacks
    def _on_connect(self) -> None:
        self.connected = True
        self.logger.info("IIFL Capital MQTT connection established")

    def _on_disconnect(self) -> None:
        self.connected = False
        self.logger.warning("IIFL Capital MQTT connection dropped")

    def _on_error(self, error: Exception) -> None:
        self.logger.error(f"IIFL Capital MQTT error: {error}")
