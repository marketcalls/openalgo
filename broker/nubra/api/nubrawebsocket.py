# openalgo/broker/nubra/api/nubrawebsocket.py
"""
Nubra WebSocket client for real-time market data.

Replicates the core functionality of Nubra's official SDK (NubraDataSocket)
using synchronous websocket-client (standard OpenAlgo dependency) instead of aiohttp.

Architecture:
- Uses websocket-client in a background thread
- Connects to wss://api.nubra.io/apibatch/ws (production)
- Receives binary protobuf messages (Any -> inner Any -> dispatch by type_url)
- Caches latest index + orderbook data in thread-safe dicts
- Exposes synchronous subscribe/unsubscribe/get_* methods
"""
import json
import logging
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

import websocket

from google.protobuf.any_pb2 import Any as ProtoAny

# Import the Nubra protobuf definitions (copied from SDK)
import sys
import os
# Add broker/nubra to sys.path so protos package is importable
_nubra_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _nubra_dir not in sys.path:
    sys.path.insert(0, _nubra_dir)

from protos import nubrafrontend_pb2

logger = logging.getLogger("NubraWebSocket")

# Production WebSocket URL
WS_URL = "wss://api.nubra.io/apibatch/ws"

# Map WebSocket "indexname" (Description) -> "symbol" (Subscription/DB Token)
# Derived from Nubra public CSV: https://api.nubra.io/public/indexes?format=csv
INDEX_NAME_MAP = {
    "NIFTY 50": "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY FINANCIAL SERVICES": "FINNIFTY",
    "BSE SENSEX": "SENSEX",
    "BSE SENSEX 50": "SENSEX50",
}

# Map "symbol" (DB Token) -> "indexname" (Subscription Key)
# Inverse/Cleanup of above, used for sending subscriptions
SUBSCRIPTION_MAP = {
    "NIFTY": "Nifty 50",
    "BANKNIFTY": "Nifty Bank",
    "FINNIFTY": "Nifty Financial Services",
    "SENSEX": "Bse Sensex",
    "SENSEX50": "Bse Sensex 50",
}


class NubraWebSocket:
    """
    WebSocket client for streaming Nubra market data.
    """

    def __init__(self, auth_token: str, device_id: str = "OPENALGO"):
        self.bt = auth_token
        self.device_id = device_id
        self.url = WS_URL
        self.ws: Optional[websocket.WebSocketApp] = None
        
        # Thread management
        self.wst: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._connected_event = threading.Event()
        
        # Data caches (thread-safe by GIL)
        self.last_quotes: Dict[Tuple[str, str], dict] = {}
        self.last_depth: Dict[int, dict] = {}
        
        # Track subscriptions for reconnect
        self.subscriptions_batch: Set[Tuple] = set()

    @property
    def is_connected(self) -> bool:
        try:
            return self._connected_event.is_set() and self.ws and self.ws.sock and self.ws.sock.connected
        except (AttributeError, OSError):
            return False

    def connect(self):
        """Start the WebSocket connection in a background thread."""
        if self.wst and self.wst.is_alive():
            return

        self._stop_event.clear()
        self.wst = threading.Thread(
            target=self._run_forever, daemon=True, name="NubraWS"
        )
        self.wst.start()

    def _run_forever(self):
        """Main WebSocket loop with auto-reconnect and exponential backoff."""
        reconnect_attempts = 0
        max_reconnect_attempts = 50
        base_delay = 2.0
        max_delay = 60.0

        while not self._stop_event.is_set():
            try:
                logger.info(f"Connecting to Nubra WebSocket (attempt {reconnect_attempts + 1})...")

                # Close old socket before creating new one (prevent FD leak)
                if self.ws:
                    try:
                        self.ws.close()
                    except Exception:
                        pass
                    self.ws = None

                # Headers are required for strict auth channels (like Orderbook)
                headers = {
                    "Authorization": f"Bearer {self.bt}",
                    "x-device-id": self.device_id
                }

                self.ws = websocket.WebSocketApp(
                    self.url,
                    header=headers,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )

                # Run blocking call (blocking until close)
                # SDK uses 20s ping interval
                self.ws.run_forever(ping_interval=20, ping_timeout=10)

            except Exception as e:
                logger.error(f"WebSocket run error: {e}")

            if self._stop_event.is_set():
                break

            reconnect_attempts += 1
            if reconnect_attempts >= max_reconnect_attempts:
                logger.error(f"Max reconnect attempts ({max_reconnect_attempts}) reached. Giving up.")
                break

            # Exponential backoff: 2s, 4s, 8s, ... capped at 60s
            delay = min(base_delay * (2 ** min(reconnect_attempts - 1, 5)), max_delay)
            logger.info(f"WebSocket disconnected. Reconnecting in {delay:.0f}s (attempt {reconnect_attempts}/{max_reconnect_attempts})...")
            self._connected_event.clear()
            # Clear stale cached data on disconnect
            self.last_quotes.clear()
            self.last_depth.clear()
            self._stop_event.wait(timeout=delay)  # Interruptible sleep

    def _on_open(self, ws):
        """Called when connection is established."""
        logger.info("Connected to Nubra WebSocket")
        self._connected_event.set()

        # Re-subscribe on reconnect
        if self.subscriptions_batch:
            logger.info(f"Resubscribing to {len(self.subscriptions_batch)} items")
            for item in self.subscriptions_batch.copy():
                # Handle different tuple lengths
                symbols = item[0]
                data_type = item[1]
                exchange = item[2]
                
                symbols_list = list(symbols)
                
                if data_type == "index":
                    self._send_subscribe_batch(
                        data_type="index",
                        index_symbol=symbols_list,
                        exchange=exchange
                    )
                elif data_type == "orderbook":
                    ref_ids = [int(s) for s in symbols_list if str(s).isdigit()]
                    self._send_subscribe_batch(
                        data_type="orderbook",
                        ref_ids=ref_ids
                    )
                elif data_type == "greeks":
                    ref_ids = [int(s) for s in symbols_list if str(s).isdigit()]
                    self._send_subscribe_batch(
                        data_type="greeks",
                        ref_ids=ref_ids
                    )
                elif data_type == "ohlcv":
                    interval = item[3]
                    self._send_subscribe_batch(
                        data_type="ohlcv",
                        index_symbol=symbols_list,
                        exchange=exchange,
                        interval=interval
                    )

    def _on_message(self, ws, message):
        """Handle incoming messages (binary or text)."""
        try:
            if isinstance(message, bytes):
                self._decode_protobuf(message)
            else:
                # Text message
                data = message.strip()
                if data == "Invalid Token":
                    logger.error("Token expired / invalid")
                    self.close()
                elif "Error" in data or "Exception" in data or "Failed" in data:
                    logger.error(f"WebSocket error message: {data}")
                else:
                    logger.debug(f"Text message: {data}")
        except Exception as e:
            logger.error(f"Message processing error: {e}")

    def _on_error(self, ws, error):
        logger.error(f"WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        logger.info(f"WebSocket closed: {close_status_code} {close_msg}")
        self._connected_event.clear()

    # ─── Decode Logic (Same as SDK) ─────────────────────────────────────

    def _decode_protobuf(self, raw: bytes):
        try:
            wrapper = ProtoAny()
            wrapper.ParseFromString(raw)
            
            inner = ProtoAny()
            inner.ParseFromString(wrapper.value)
            
            logger.info(f"Received Protobuf Message: {inner.type_url}")

            if inner.type_url.endswith("BatchWebSocketIndexMessage"):
                msg = nubrafrontend_pb2.BatchWebSocketIndexMessage()
                inner.Unpack(msg)
                self._process_index_batch(msg)
                
            elif inner.type_url.endswith("BatchWebSocketOrderbookMessage"):
                msg = nubrafrontend_pb2.BatchWebSocketOrderbookMessage()
                inner.Unpack(msg)
                self._process_orderbook_batch(msg)
            
            elif inner.type_url.endswith("BatchWebSocketIndexBucketMessage"):
                msg = nubrafrontend_pb2.BatchWebSocketIndexBucketMessage()
                inner.Unpack(msg)
                self._process_index_bucket_batch(msg)

            elif inner.type_url.endswith("BatchWebSocketGreeksMessage"):
                msg = nubrafrontend_pb2.BatchWebSocketGreeksMessage()
                inner.Unpack(msg)
                self._process_greeks_batch(msg)

        except Exception as e:
            logger.error(f"Protobuf decode error: {e}")

    def _process_index_batch(self, msg):
        if len(msg.indexes) > 0:
            logger.info(f"Received {len(msg.indexes)} index updates: {[i.indexname for i in msg.indexes]}")
        
        for obj in msg.indexes:
            self._cache_index_data(obj)
        for obj in msg.instruments:
            self._cache_index_data(obj)

    def _cache_index_data(self, obj):
        exchange = obj.exchange if obj.exchange else "NSE"
        name = obj.indexname if obj.indexname else ""
        if not name:
            return
        
        # Normalize name to upercase for consistent caching
        name = name.upper()
        
        # Apply standard mapping (e.g. "NIFTY 50" -> "NIFTY")
        # Because we subscribe with "NIFTY" but receive data as "Nifty 50"
        if name in INDEX_NAME_MAP:
            name = INDEX_NAME_MAP[name]
        
        if "NIFTY" in name:
             logger.info(f"Caching index: name={name}, exch={exchange}, val={obj.index_value}")

        # Preserve open/close from OHLCV cache (OHLCV may arrive before index data)
        key = (exchange, name)
        existing = self.last_quotes.get(key, {})

        self.last_quotes[key] = {
            "ltp": obj.index_value / 100.0 if obj.index_value else 0,
            "high": obj.high_index_value / 100.0 if obj.high_index_value else 0,
            "low": obj.low_index_value / 100.0 if obj.low_index_value else 0,
            "volume": obj.volume if obj.volume else 0,
            "changepercent": obj.changepercent if obj.changepercent else 0.0,
            "prev_close": obj.prev_close / 100.0 if obj.prev_close else 0,
            "volume_oi": obj.volume_oi if obj.volume_oi else 0,
            "timestamp": obj.timestamp if obj.timestamp else 0,
            "bid": 0,
            "ask": 0,
            "open": existing.get("open", 0),
            "close": existing.get("close", 0),
            "_has_index": True,
        }

    def _process_orderbook_batch(self, msg):
        logger.info(f"Received orderbook batch with {len(msg.instruments)} instruments")
        for obj in msg.instruments:
            self._cache_orderbook_data(obj)

    def _cache_orderbook_data(self, obj):
        # Use ref_id if available, else fall back to inst_id
        ref_id = obj.ref_id if obj.ref_id else 0
        inst_id = obj.inst_id if obj.inst_id else 0
        logger.info(f"Orderbook data received: inst_id={inst_id}, ref_id={ref_id}, bids={len(obj.bids)}, asks={len(obj.asks)}, ltp={obj.ltp}")
        
        if not ref_id:
            if inst_id:
                logger.warning(f"ref_id is 0, using inst_id={inst_id} as key")
                ref_id = inst_id
            else:
                logger.warning("Both ref_id and inst_id are 0, skipping")
                return

        bids = [{"price": (b.price/100.0 if b.price else 0), "quantity": b.quantity or 0, "orders": b.orders or 0} for b in obj.bids]
        asks = [{"price": (a.price/100.0 if a.price else 0), "quantity": a.quantity or 0, "orders": a.orders or 0} for a in obj.asks]

        # Pad to exactly 5 levels
        while len(bids) < 5:
            bids.append({"price": 0, "quantity": 0, "orders": 0})
        while len(asks) < 5:
            asks.append({"price": 0, "quantity": 0, "orders": 0})

        totalbuyqty = sum(b["quantity"] for b in bids)
        totalsellqty = sum(a["quantity"] for a in asks)

        # Preserve OI fields from greeks channel (orderbook doesn't carry OI)
        existing = self.last_depth.get(ref_id, {})

        existing.update({
            "ltp": obj.ltp / 100.0 if obj.ltp else 0,
            "ltq": obj.ltq if obj.ltq else 0,
            "volume": obj.volume if obj.volume else 0,
            "bids": bids[:5],
            "asks": asks[:5],
            "totalbuyqty": totalbuyqty,
            "totalsellqty": totalsellqty,
            "timestamp": obj.timestamp if obj.timestamp else 0,
            "ref_id": ref_id,
        })
        self.last_depth[ref_id] = existing

    def _process_greeks_batch(self, msg):
        """Process greeks data (WebSocketMsgOptionChainItem) and merge OI into orderbook cache."""
        logger.info(f"Received greeks batch with {len(msg.instruments)} instruments")
        for obj in msg.instruments:
            ref_id = obj.ref_id if obj.ref_id else 0
            if not ref_id:
                continue

            oi_val = obj.oi if obj.oi else 0
            prev_oi = obj.prev_oi if obj.prev_oi else 0
            ltp = obj.ltp / 100.0 if obj.ltp else 0
            volume = obj.volume if obj.volume else 0

            logger.info(f"Greeks data: ref_id={ref_id}, oi={oi_val}, prev_oi={prev_oi}, ltp={ltp}")

            # Merge into existing orderbook cache if present, otherwise create entry
            existing = self.last_depth.get(ref_id, {})
            existing["oi"] = oi_val
            existing["prev_oi"] = prev_oi
            # Fill ltp/volume from greeks if orderbook hasn't arrived yet
            if not existing.get("ltp"):
                existing["ltp"] = ltp
            if not existing.get("volume"):
                existing["volume"] = volume
            self.last_depth[ref_id] = existing

    def _process_index_bucket_batch(self, msg):
        """Process OHLVC candles (IndexBucket) and update quotes."""
        if len(msg.indexes) > 0:
             logger.info(f"Received {len(msg.indexes)} OHLVC updates")
        
        for obj in msg.indexes:
            self._cache_ohlcv_data(obj)
        for obj in msg.instruments:
            self._cache_ohlcv_data(obj)

    def _cache_ohlcv_data(self, obj):
        exchange = obj.exchange if obj.exchange else "NSE"
        name = obj.indexname if obj.indexname else ""
        if not name:
            return

        name = name.upper()
        if name in INDEX_NAME_MAP:
            name = INDEX_NAME_MAP[name]

        if "NIFTY" in name:
             logger.info(f"Caching OHLVC: name={name}, open={obj.open}, close={obj.close}")

        # Merge OHLCV into existing quote.
        # Index channel provides: ltp, high, low, prev_close, changepercent
        # OHLCV channel provides: open, high, low, close, volume
        # When only OHLCV is subscribed (e.g., index requests), close serves as LTP.
        # If index channel is active (_has_index flag), it is authoritative for
        # ltp/high/low/volume/timestamp — OHLCV only contributes open/close.
        # If OHLCV is the sole source, refresh all fields on every message.
        key = (exchange, name)
        existing = self.last_quotes.get(key, {})
        has_index = existing.get("_has_index", False)
        close_val = obj.close / 100.0 if obj.close else 0
        existing["open"] = obj.open / 100.0 if obj.open else existing.get("open", 0)
        existing["close"] = close_val or existing.get("close", 0)
        if not has_index:
            # OHLCV is the only data source — always refresh
            if close_val:
                existing["ltp"] = close_val
            if obj.high:
                existing["high"] = obj.high / 100.0
            if obj.low:
                existing["low"] = obj.low / 100.0
            existing["volume"] = obj.cumulative_volume if obj.cumulative_volume else (obj.bucket_volume or 0)
            if obj.timestamp:
                existing["timestamp"] = obj.timestamp
        self.last_quotes[key] = existing

    # ─── Public Methods ──────────────────────────────────────────────────

    def subscribe_ohlcv(self, symbols: List[str], interval: str, exchange: str = "NSE") -> bool:
        """Subscribe to index_bucket (OHLVC) channel."""
        if not self.is_connected:
            return False
            
        key = (tuple(symbols), "ohlcv", exchange, interval)
        self.subscriptions_batch.add(key)
        
        return self._send_subscribe_batch("ohlcv", index_symbol=symbols, exchange=exchange, interval=interval)

    def unsubscribe_ohlcv(self, symbols: List[str], interval: str, exchange: str = "NSE") -> bool:
        """Unsubscribe from index_bucket channel."""
        if not self.is_connected:
            return False
            
        key = (tuple(symbols), "ohlcv", exchange, interval)
        self.subscriptions_batch.discard(key)
        
        return self._send_unsubscribe_batch("ohlcv", index_symbol=symbols, exchange=exchange, interval=interval)

    def subscribe_index(self, symbols: List[str], exchange: str = "NSE") -> bool:
        """Subscribe to index channel."""
        if not self.is_connected:
            return False
            
        key = (tuple(symbols), "index", exchange)
        self.subscriptions_batch.add(key)
        
        return self._send_subscribe_batch("index", index_symbol=symbols, exchange=exchange)

    def unsubscribe_index(self, symbols: List[str], exchange: str = "NSE") -> bool:
        """Unsubscribe from index channel."""
        if not self.is_connected:
            return False

        key = (tuple(symbols), "index", exchange)
        self.subscriptions_batch.discard(key)

        # Clear _has_index flag so OHLCV channel resumes full updates
        for sym in symbols:
            cache_key = (exchange, sym.upper())
            cached = self.last_quotes.get(cache_key)
            if cached:
                cached.pop("_has_index", None)

        return self._send_unsubscribe_batch("index", index_symbol=symbols, exchange=exchange)

    def subscribe_orderbook(self, ref_ids: List[int]) -> bool:
        """Subscribe to orderbook channel."""
        if not self.is_connected:
            return False
            
        key = (tuple(str(r) for r in ref_ids), "orderbook", None)
        self.subscriptions_batch.add(key)
        
        return self._send_subscribe_batch("orderbook", ref_ids=ref_ids)

    def unsubscribe_orderbook(self, ref_ids: List[int]) -> bool:
        """Unsubscribe from orderbook channel."""
        if not self.is_connected:
            return False

        key = (tuple(str(r) for r in ref_ids), "orderbook", None)
        self.subscriptions_batch.discard(key)

        return self._send_unsubscribe_batch("orderbook", ref_ids=ref_ids)

    def subscribe_greeks(self, ref_ids: List[int]) -> bool:
        """Subscribe to greeks channel (provides OI, IV, Greeks for options)."""
        if not self.is_connected:
            return False

        key = (tuple(str(r) for r in ref_ids), "greeks", None)
        self.subscriptions_batch.add(key)

        return self._send_subscribe_batch("greeks", ref_ids=ref_ids)

    def unsubscribe_greeks(self, ref_ids: List[int]) -> bool:
        """Unsubscribe from greeks channel."""
        if not self.is_connected:
            return False

        key = (tuple(str(r) for r in ref_ids), "greeks", None)
        self.subscriptions_batch.discard(key)

        return self._send_unsubscribe_batch("greeks", ref_ids=ref_ids)

    def get_quote(self, exchange: str, symbol: str) -> Optional[dict]:
        # Normalize symbol to upper
        symbol = symbol.upper()
        res = self.last_quotes.get((exchange, symbol))
        if not res and "NIFTY" in symbol:
             logger.debug(f"get_quote failed for {exchange}:{symbol}. Available keys: {list(self.last_quotes.keys())}")
        return res

    def get_market_depth(self, ref_id: int) -> Optional[dict]:
        return self.last_depth.get(ref_id)

    def close(self):
        """Close connection and stop thread."""
        self._stop_event.set()
        self._connected_event.clear()
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
        if self.wst and self.wst.is_alive():
            self.wst.join(timeout=5)
            if self.wst.is_alive():
                logger.warning("NubraWS thread did not terminate within 5s timeout")
        self.wst = None
        self.last_quotes.clear()
        self.last_depth.clear()

    def __del__(self):
        """Safety net destructor to ensure resources are cleaned up."""
        try:
            self.close()
        except Exception:
            pass

    # ─── Internal Send Methods ───────────────────────────────────────────

    def _send_subscribe_batch(self, data_type: str, ref_ids=None, index_symbol=None, exchange=None, interval=None) -> bool:
        try:
            ws = self.ws  # Capture local ref to avoid TOCTOU race
            if not ws or not ws.sock:
                return False

            payload = {
                "instruments": ref_ids or [],
                "indexes": index_symbol or []
            }

            if data_type == "index":
                msg = f"batch_subscribe {self.bt} index {json.dumps(payload, separators=(',', ':'))} {exchange or 'NSE'}"
                logger.info(f"Subscribing to INDEX: {msg}")
            elif data_type == "ohlcv":
                msg = f"batch_subscribe {self.bt} index_bucket {json.dumps(payload, separators=(',', ':'))} {interval} {exchange or 'NSE'}"
                logger.info(f"Subscribing to OHLVC: {msg}")
            else:
                msg = f"batch_subscribe {self.bt} {data_type} {json.dumps(payload, separators=(',', ':'))}"
                logger.info(f"Subscribing to {data_type}: {msg}")

            ws.send(msg)
            return True
        except Exception as e:
            logger.error(f"Send subscribe failed: {e}")
            return False

    def change_orderbook_depth(self, depth: int = 5) -> bool:
        """Set the orderbook depth level (default 5, max 20)."""
        try:
            ws = self.ws  # Capture local ref to avoid TOCTOU race
            if not ws or not ws.sock:
                return False
            msg = f"batch_subscribe {self.bt} orderbook_depth {depth}"
            logger.info(f"Setting orderbook depth: {msg}")
            ws.send(msg)
            return True
        except Exception as e:
            logger.error(f"Failed to set orderbook depth: {e}")
            return False

    def _send_unsubscribe_batch(self, data_type: str, ref_ids=None, index_symbol=None, exchange=None, interval=None) -> bool:
        try:
            ws = self.ws  # Capture local ref to avoid TOCTOU race
            if not ws or not ws.sock:
                return False

            payload = {
                "instruments": ref_ids or [],
                "indexes": index_symbol or []
            }

            if data_type == "index":
                msg = f"batch_unsubscribe {self.bt} index {json.dumps(payload, separators=(',', ':'))} {exchange or 'NSE'}"
            elif data_type == "ohlcv":
                msg = f"batch_unsubscribe {self.bt} index_bucket {json.dumps(payload, separators=(',', ':'))} {interval} {exchange or 'NSE'}"
            else:
                msg = f"batch_unsubscribe {self.bt} {data_type} {json.dumps(payload, separators=(',', ':'))}"

            ws.send(msg)
            return True
        except Exception as e:
            logger.error(f"Send unsubscribe failed: {e}")
            return False
