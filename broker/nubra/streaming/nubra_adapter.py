"""
Nubra WebSocket streaming adapter for OpenAlgo.

Extends BaseBrokerWebSocketAdapter to provide real-time market data
from Nubra's WebSocket API via ZeroMQ.

Uses the existing NubraWebSocket from broker/nubra/api/nubrawebsocket.py
with a streaming subclass that fires callbacks on each tick.

Channel strategy (per Nubra API docs):
  - index channel: LTP, volume, change% for BOTH indices AND instruments
    -> Used for mode 1 (LTP) and mode 2 (Quote) for ALL symbols
  - orderbook channel: Market depth with bid/ask levels + LTP
    -> Used for mode 3 (Depth) for instruments only

Data Flow:
    Nubra WS -> NubraWebSocket (protobuf decode) -> callback override
      -> nubra_adapter.py (transform to OpenAlgo format)
      -> BaseBrokerWebSocketAdapter.publish_market_data(topic, data)
      -> ZeroMQ -> websocket_proxy/server.py -> WebSocket clients
"""

import os
import sys
import threading
import time
from typing import Any, Dict, Set, Tuple

from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_token
from utils.logging import get_logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

from .nubra_mapping import NubraCapabilityRegistry, NubraExchangeMapper

# Import the existing working Nubra WebSocket client
from broker.nubra.api.nubrawebsocket import (
    INDEX_NAME_MAP,
    SUBSCRIPTION_MAP,
    NubraWebSocket,
)

logger = get_logger(__name__)


class _StreamingNubraWebSocket(NubraWebSocket):
    """
    Extends the existing NubraWebSocket to invoke callbacks on each tick
    in addition to caching data. This allows the streaming adapter to
    push data to ZeroMQ without modifying the original working class.
    """

    def __init__(
        self,
        auth_token,
        on_index_data=None,
        on_orderbook_data=None,
        on_ohlcv_data=None,
        **kwargs,
    ):
        super().__init__(auth_token, **kwargs)
        self._on_index_data_cb = on_index_data
        self._on_orderbook_data_cb = on_orderbook_data
        self._on_ohlcv_data_cb = on_ohlcv_data

    def _cache_index_data(self, obj):
        """Override to invoke callback after caching."""
        super()._cache_index_data(obj)
        if self._on_index_data_cb:
            self._on_index_data_cb(obj)

    def _cache_orderbook_data(self, obj):
        """Override to invoke callback after caching."""
        super()._cache_orderbook_data(obj)
        if self._on_orderbook_data_cb:
            self._on_orderbook_data_cb(obj)

    def _cache_ohlcv_data(self, obj):
        """Override to invoke callback after caching."""
        super()._cache_ohlcv_data(obj)
        if self._on_ohlcv_data_cb:
            self._on_ohlcv_data_cb(obj)

    def wait_for_connection(self, timeout: float = 15.0) -> bool:
        """Wait for the WebSocket to connect."""
        return self._connected_event.wait(timeout=timeout)


class NubraWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Nubra-specific implementation of the WebSocket adapter."""

    def __init__(self):
        super().__init__()
        self.logger = get_logger("nubra_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "nubra"
        self.running = False
        self.lock = threading.Lock()

        # Subscription tracking
        self.subscribed_symbols: Dict[str, dict] = {}  # "exchange:symbol" -> info

        # Reverse maps for incoming data routing
        # Index channel: maps uppercased subscription name -> (symbol, exchange)
        self.index_name_to_sub: Dict[str, Tuple[str, str]] = {}
        # Orderbook channel: maps ref_id -> (symbol, exchange)
        self.ref_id_to_symbol: Dict[int, Tuple[str, str]] = {}

        # Track which modes each symbol is subscribed to
        self.symbol_modes: Dict[str, Set[int]] = {}  # "exchange:symbol" -> {mode_ints}

        # Track whether index channel is already subscribed per symbol
        self.index_channel_subscribed: Set[str] = set()  # "exchange:symbol"
        # Track whether orderbook channel is already subscribed per ref_id
        self.orderbook_subscribed: Set[int] = set()  # ref_ids
        # Track OHLCV subscriptions per nubra exchange
        self.ohlcv_channel_subscribed: Set[str] = set()  # "exchange:symbol"

        # Cache OHLCV open values keyed by uppercased symbol name
        self.ohlcv_cache: Dict[str, dict] = {}  # "NAME" -> {"open": ..., "close": ...}

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Initialize with Nubra credentials."""
        try:
            self.user_id = user_id
            self.broker_name = broker_name

            # Get auth token from database
            auth_token = get_auth_token(user_id)
            if not auth_token:
                return self._create_error_response(
                    "AUTH_ERROR", "Authentication token not found"
                )

            # Create streaming WebSocket client (extends existing NubraWebSocket)
            self.ws_client = _StreamingNubraWebSocket(
                auth_token=auth_token,
                on_index_data=self._on_index_data,
                on_orderbook_data=self._on_orderbook_data,
                on_ohlcv_data=self._on_ohlcv_data,
            )

            self.running = True
            self.logger.info(f"Nubra adapter initialized for user {user_id}")
            return self._create_success_response("Adapter initialized successfully")

        except Exception as e:
            self.logger.error(f"Error initializing adapter: {e}")
            return self._create_error_response("INIT_ERROR", str(e))

    def connect(self) -> dict[str, Any]:
        """Connect to Nubra WebSocket."""
        if not self.ws_client:
            return self._create_error_response(
                "NOT_INITIALIZED", "Call initialize() first"
            )

        try:
            with self.lock:
                if self.running and self.connected:
                    return self._create_success_response("Already connected")

            self.ws_client.connect()

            self.logger.info("Waiting for WebSocket connection...")
            if self.ws_client.wait_for_connection(timeout=15.0):
                self.connected = True
                self.logger.info("WebSocket connected successfully")
                return self._create_success_response("Connected successfully")
            else:
                return self._create_error_response("TIMEOUT", "Connection timeout")

        except Exception as e:
            self.logger.error(f"Error connecting: {e}")
            return self._create_error_response("CONNECT_ERROR", str(e))

    def disconnect(self) -> dict[str, Any]:
        """Disconnect and clean up."""
        try:
            with self.lock:
                self.running = False
                self.connected = False

                if self.ws_client:
                    self.ws_client.close()
                    self.ws_client = None

                self.subscribed_symbols.clear()
                self.index_name_to_sub.clear()
                self.ref_id_to_symbol.clear()
                self.symbol_modes.clear()
                self.index_channel_subscribed.clear()
                self.orderbook_subscribed.clear()
                self.ohlcv_channel_subscribed.clear()
                self.ohlcv_cache.clear()

            self.cleanup_zmq()
            self.logger.info("Nubra adapter disconnected")
            return self._create_success_response(
                "Disconnected successfully and resources cleaned up"
            )

        except Exception as e:
            self.logger.error(f"Error disconnecting: {e}")
            try:
                self.cleanup_zmq()
            except Exception:
                pass
            return self._create_error_response("DISCONNECT_ERROR", str(e))

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5
    ) -> dict[str, Any]:
        """
        Subscribe to market data.

        Channel strategy:
          - Mode 1 (LTP) / Mode 2 (Quote): Use index channel for ALL symbols
            (Nubra index channel supports both indices and instruments)
          - Mode 3 (Depth): Use orderbook channel (instruments only)

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE', 'NIFTY')
            exchange: Exchange code (e.g., 'NSE', 'NSE_INDEX', 'NFO')
            mode: 1=LTP, 2=Quote, 3=Depth
            depth_level: Market depth level (5 for Nubra orderbook)
        """
        if not self.ws_client:
            return self._create_error_response(
                "NOT_INITIALIZED", "WebSocket not initialized"
            )

        if not self.running:
            return self._create_error_response(
                "NOT_CONNECTED", "WebSocket not connected. Call connect() first."
            )

        if mode not in [1, 2, 3]:
            return self._create_error_response(
                "INVALID_MODE",
                f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)",
            )

        is_index = NubraExchangeMapper.is_index_exchange(exchange)

        # Depth mode not supported for indices
        if mode == 3 and is_index:
            return self._create_error_response(
                "UNSUPPORTED", "Depth mode not supported for index symbols"
            )

        try:
            key = f"{exchange}:{symbol}"

            if mode in (1, 2):
                # LTP / Quote -> use index channel for ALL symbols
                return self._subscribe_via_index_channel(
                    symbol, exchange, mode, key, is_index
                )
            else:
                # Depth -> use orderbook channel
                return self._subscribe_via_orderbook_channel(
                    symbol, exchange, mode, depth_level, key
                )

        except Exception as e:
            self.logger.error(f"Error subscribing to {exchange}:{symbol}: {e}")
            return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

    def _subscribe_via_index_channel(
        self,
        symbol: str,
        exchange: str,
        mode: int,
        key: str,
        is_index: bool,
    ) -> dict[str, Any]:
        """
        Subscribe via the index channel for LTP/Quote data.

        Per Nubra API docs, the index channel accepts both index symbols
        AND instrument symbols in the "indexes" array:
            batch_subscribe [token] index {"indexes":["BANKNIFTY","TCS","RELIANCE"]} NSE
        """
        nubra_exchange = NubraExchangeMapper.to_nubra_exchange(exchange)

        if is_index:
            # For index symbols, use SUBSCRIPTION_MAP name (e.g., "Nifty 50")
            sub_name = SUBSCRIPTION_MAP.get(symbol)
            if not sub_name:
                sub_name = get_br_symbol(symbol, exchange)
                if not sub_name:
                    return self._create_error_response(
                        "SYMBOL_NOT_FOUND",
                        f"No index mapping for {symbol}",
                    )
        else:
            # For instruments, use the symbol name directly
            # (API docs show "TCS", "RELIANCE" in the indexes array)
            sub_name = symbol

        # Hold lock for entire subscribe + tracking to prevent race with callbacks
        with self.lock:
            if not self.ws_client:
                return self._create_error_response(
                    "NOT_CONNECTED", "WebSocket client disconnected"
                )

            # Only send WebSocket subscription if not already on index channel
            if key not in self.index_channel_subscribed:
                self.ws_client.subscribe_index([sub_name], exchange=nubra_exchange)
                self.index_channel_subscribed.add(key)

            # Also subscribe to index_bucket (OHLCV) to get open/close values
            if key not in self.ohlcv_channel_subscribed:
                self.ws_client.subscribe_ohlcv(
                    [sub_name], interval="1d", exchange=nubra_exchange
                )
                self.ohlcv_channel_subscribed.add(key)

            # Register the subscription name for data routing
            self.index_name_to_sub[sub_name.upper()] = (symbol, exchange)

            # For known indices, also register all name variations
            if is_index:
                for ws_name, oa_sym in INDEX_NAME_MAP.items():
                    if oa_sym == symbol:
                        self.index_name_to_sub[ws_name] = (symbol, exchange)

            if key not in self.symbol_modes:
                self.symbol_modes[key] = set()
            self.symbol_modes[key].add(mode)

            self.subscribed_symbols[key] = {
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
                "is_index": is_index,
                "sub_name": sub_name,
                "nubra_exchange": nubra_exchange,
            }

        self.logger.info(
            f"Subscribed to {exchange}:{symbol} via index channel "
            f"(sub_name: {sub_name}, mode: {mode})"
        )
        return self._create_success_response(
            f"Subscribed to {symbol}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
        )

    def _subscribe_via_orderbook_channel(
        self,
        symbol: str,
        exchange: str,
        mode: int,
        depth_level: int,
        key: str,
    ) -> dict[str, Any]:
        """Subscribe via the orderbook channel for Depth data (mode 3)."""
        token_data = get_token(symbol, exchange)
        if not token_data:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND",
                f"Token not found for {symbol} on {exchange}",
            )

        # Extract numeric ref_id from token
        if isinstance(token_data, str):
            if "::::" in token_data:
                token_str = token_data.split("::::")[0]
            elif ":" in token_data:
                token_str = token_data.split(":")[0]
            else:
                token_str = token_data
        else:
            token_str = str(token_data)

        try:
            ref_id = int(token_str)
        except ValueError:
            return self._create_error_response(
                "INVALID_TOKEN", f"Invalid token format: {token_str}"
            )

        # Check depth level support
        is_fallback = False
        actual_depth = depth_level
        if not NubraCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
            actual_depth = NubraCapabilityRegistry.get_fallback_depth_level(
                exchange, depth_level
            )
            is_fallback = True

        # Hold lock for entire subscribe + tracking to prevent race with callbacks
        with self.lock:
            if not self.ws_client:
                return self._create_error_response(
                    "NOT_CONNECTED", "WebSocket client disconnected"
                )

            # Subscribe to orderbook channel if not already
            if ref_id not in self.orderbook_subscribed:
                self.ws_client.subscribe_orderbook([ref_id])
                self.orderbook_subscribed.add(ref_id)

            self.ref_id_to_symbol[ref_id] = (symbol, exchange)

            if key not in self.symbol_modes:
                self.symbol_modes[key] = set()
            self.symbol_modes[key].add(mode)

            self.subscribed_symbols[key] = {
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
                "is_index": False,
                "ref_id": ref_id,
            }

        self.logger.info(
            f"Subscribed to {exchange}:{symbol} via orderbook channel "
            f"(ref_id: {ref_id}, mode: {mode})"
        )
        return self._create_success_response(
            "Subscription requested"
            if not is_fallback
            else f"Using depth level {actual_depth} instead of {depth_level}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            requested_depth=depth_level,
            actual_depth=actual_depth,
            is_fallback=is_fallback,
        )

    def unsubscribe(
        self, symbol: str, exchange: str, mode: int = 2
    ) -> dict[str, Any]:
        """Unsubscribe from market data."""
        try:
            key = f"{exchange}:{symbol}"
            is_index = NubraExchangeMapper.is_index_exchange(exchange)

            with self.lock:
                if key not in self.subscribed_symbols:
                    return self._create_error_response(
                        "NOT_SUBSCRIBED", f"Not subscribed to {symbol}"
                    )

                sub_info = self.subscribed_symbols[key]

                # Remove mode
                if key in self.symbol_modes:
                    self.symbol_modes[key].discard(mode)

                    # If no more modes, fully unsubscribe
                    if not self.symbol_modes[key]:
                        del self.symbol_modes[key]
                        del self.subscribed_symbols[key]

                        # Capture ws_client ref inside lock (safe from disconnect race)
                        ws = self.ws_client

                        # Unsubscribe from index channel
                        if key in self.index_channel_subscribed:
                            sub_name = sub_info.get("sub_name", symbol)
                            nubra_exchange = sub_info.get(
                                "nubra_exchange",
                                NubraExchangeMapper.to_nubra_exchange(exchange),
                            )
                            if ws:
                                ws.unsubscribe_index(
                                    [sub_name], exchange=nubra_exchange
                                )
                            self.index_channel_subscribed.discard(key)

                        # Unsubscribe from index_bucket (OHLCV) channel
                        if key in self.ohlcv_channel_subscribed:
                            sub_name = sub_info.get("sub_name", symbol)
                            nubra_exchange = sub_info.get(
                                "nubra_exchange",
                                NubraExchangeMapper.to_nubra_exchange(exchange),
                            )
                            if ws:
                                ws.unsubscribe_ohlcv(
                                    [sub_name],
                                    interval="1d",
                                    exchange=nubra_exchange,
                                )
                            self.ohlcv_channel_subscribed.discard(key)

                            # Clean up name mappings
                            keys_to_remove = [
                                k
                                for k, v in self.index_name_to_sub.items()
                                if v == (symbol, exchange)
                            ]
                            for k in keys_to_remove:
                                del self.index_name_to_sub[k]

                        # Unsubscribe from orderbook channel
                        ref_id = sub_info.get("ref_id")
                        if ref_id is not None:
                            if ws:
                                ws.unsubscribe_orderbook([ref_id])
                            self.ref_id_to_symbol.pop(ref_id, None)
                            self.orderbook_subscribed.discard(ref_id)

            self.logger.info(f"Unsubscribed from {exchange}:{symbol} (mode: {mode})")
            return self._create_success_response(
                f"Unsubscribed from {symbol}",
                symbol=symbol,
                exchange=exchange,
                mode=mode,
            )

        except Exception as e:
            self.logger.error(f"Error unsubscribing from {exchange}:{symbol}: {e}")
            return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))

    # --- Tick Callbacks ---

    def _on_index_data(self, obj):
        """
        Handle incoming index data from Nubra WebSocket.

        This callback fires for BOTH index and instrument symbols subscribed
        via the index channel. Transforms to OpenAlgo format and publishes
        to ZMQ topic: {exchange}_{symbol}_{LTP|QUOTE}
        """
        try:
            name = obj.indexname if obj.indexname else ""
            if not name:
                return

            name_upper = name.upper()

            # Single lock acquisition for all lookups
            with self.lock:
                # Route 1: Check INDEX_NAME_MAP for known index names
                # e.g., "NIFTY 50" -> "NIFTY", "NIFTY BANK" -> "BANKNIFTY"
                mapped_symbol = INDEX_NAME_MAP.get(name_upper)
                if mapped_symbol:
                    symbol = mapped_symbol
                    exchange = None
                    for ex in ("NSE_INDEX", "BSE_INDEX"):
                        key = f"{ex}:{symbol}"
                        if key in self.symbol_modes:
                            exchange = ex
                            break
                    if not exchange:
                        return
                else:
                    # Route 2: Direct lookup from our subscription map
                    # e.g., "INFY" -> ("INFY", "NSE")
                    lookup = self.index_name_to_sub.get(name_upper)
                    if not lookup:
                        return
                    symbol, exchange = lookup

                key = f"{exchange}:{symbol}"
                modes = self.symbol_modes.get(key, set()).copy()
                ohlcv = self.ohlcv_cache.get(name_upper, {}).copy()

            if not modes:
                return

            # Extract data from protobuf (no lock needed - read-only on obj)
            ltp = obj.index_value / 100.0 if obj.index_value else 0
            prev_close = obj.prev_close / 100.0 if obj.prev_close else 0
            timestamp = obj.timestamp if obj.timestamp else int(time.time() * 1000)

            # Get open/close from OHLCV cache (already captured under lock)
            open_price = ohlcv.get("open", 0)
            close_price = ohlcv.get("close", prev_close)

            # Publish for Quote mode (mode 2)
            if 2 in modes:
                quote_data = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "mode": "quote",
                    "ltp": ltp,
                    "open": open_price,
                    "high": obj.high_index_value / 100.0 if obj.high_index_value else 0,
                    "low": obj.low_index_value / 100.0 if obj.low_index_value else 0,
                    "close": close_price,
                    "volume": obj.volume if obj.volume else 0,
                    "prev_close": prev_close,
                    "timestamp": timestamp,
                }
                topic = f"{exchange}_{symbol}_QUOTE"
                self.publish_market_data(topic, quote_data)

            # Publish for LTP mode (mode 1)
            if 1 in modes:
                ltp_data = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "mode": "ltp",
                    "ltp": ltp,
                    "timestamp": timestamp,
                }
                topic = f"{exchange}_{symbol}_LTP"
                self.publish_market_data(topic, ltp_data)

        except Exception as e:
            self.logger.error(f"Error processing index data: {e}", exc_info=True)

    def _on_ohlcv_data(self, obj):
        """
        Handle incoming OHLCV (index_bucket) data from Nubra WebSocket.

        Caches open/close values so _on_index_data can merge them into quotes.
        OHLCV values are int64 in paise (same as index channel), so divide by 100.
        """
        try:
            name = obj.indexname if obj.indexname else ""
            if not name:
                return

            name_upper = name.upper()

            # Also store under mapped name (e.g., "NIFTY 50" -> "NIFTY")
            mapped = INDEX_NAME_MAP.get(name_upper)

            ohlcv_entry = {
                "open": obj.open / 100.0 if obj.open else 0,
                "close": obj.close / 100.0 if obj.close else 0,
            }

            with self.lock:
                self.ohlcv_cache[name_upper] = ohlcv_entry
                if mapped:
                    self.ohlcv_cache[mapped] = ohlcv_entry

        except Exception as e:
            self.logger.error(f"Error processing OHLCV data: {e}", exc_info=True)

    def _on_orderbook_data(self, obj):
        """
        Handle incoming orderbook data from Nubra WebSocket.

        This callback fires for instruments subscribed via the orderbook
        channel (mode 3 / Depth). Transforms to OpenAlgo format and publishes
        to ZMQ topic: {exchange}_{symbol}_DEPTH
        """
        try:
            ref_id = obj.ref_id if obj.ref_id else (obj.inst_id if obj.inst_id else 0)
            if not ref_id:
                return

            # Single lock acquisition for all lookups
            with self.lock:
                symbol_info = self.ref_id_to_symbol.get(ref_id)
                if not symbol_info:
                    return
                symbol, exchange = symbol_info
                key = f"{exchange}:{symbol}"
                modes = self.symbol_modes.get(key, set()).copy()

            if not modes or 3 not in modes:
                return

            # Extract common data
            ltp = obj.ltp / 100.0 if obj.ltp else 0
            volume = obj.volume if obj.volume else 0
            timestamp = obj.timestamp if obj.timestamp else int(time.time() * 1000)

            # Build depth data
            bids = [
                {
                    "price": b.price / 100.0 if b.price else 0,
                    "quantity": b.quantity or 0,
                    "orders": b.orders or 0,
                }
                for b in obj.bids
            ]
            asks = [
                {
                    "price": a.price / 100.0 if a.price else 0,
                    "quantity": a.quantity or 0,
                    "orders": a.orders or 0,
                }
                for a in obj.asks
            ]

            # Pad to 5 levels
            while len(bids) < 5:
                bids.append({"price": 0, "quantity": 0, "orders": 0})
            while len(asks) < 5:
                asks.append({"price": 0, "quantity": 0, "orders": 0})

            totalbuyqty = sum(b["quantity"] for b in bids[:5])
            totalsellqty = sum(a["quantity"] for a in asks[:5])

            # Publish Depth data
            depth_data = {
                "symbol": symbol,
                "exchange": exchange,
                "mode": "full",
                "ltp": ltp,
                "volume": volume,
                "timestamp": timestamp,
                "total_buy_quantity": totalbuyqty,
                "total_sell_quantity": totalsellqty,
                "depth": {
                    "buy": bids[:5],
                    "sell": asks[:5],
                },
            }
            topic = f"{exchange}_{symbol}_DEPTH"
            self.publish_market_data(topic, depth_data)

        except Exception as e:
            self.logger.error(f"Error processing orderbook data: {e}", exc_info=True)

    # --- Connection Callbacks (tracked via ws_client events) ---

    def cleanup(self):
        """Clean up all resources. Delegates to disconnect() to avoid duplication."""
        try:
            self.disconnect()
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            # Last resort: ensure ZMQ is cleaned up
            try:
                self.cleanup_zmq()
            except Exception:
                pass

    def __del__(self):
        """Safety net destructor."""
        try:
            self.cleanup()
        except Exception:
            pass
