# broker/upstox/streaming/upstox_adapter.py
import asyncio
import threading
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .upstox_client import UpstoxWebSocketClient
from database.auth_db import get_auth_token


class UpstoxWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Upstox V3 WebSocket adapter implementation.
    
    Features:
    - Handles all WebSocket operations through UpstoxWebSocketClient
    - Processes protobuf messages decoded to dict format
    - Manages subscriptions and market data publishing
    """
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("upstox_websocket")
        self.ws_client: Optional[UpstoxWebSocketClient] = None
        self.event_loop: Optional[asyncio.AbstractEventLoop] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.subscriptions: Dict[str, Dict[str, Any]] = {}
        self.market_status: Dict[str, Any] = {}
        self.connected = False
        self.running = False
        self.lock = threading.Lock()  # Add threading lock for subscription management

    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Initialize the adapter with authentication data"""
        try:
            auth_token = self._get_auth_token(auth_data, user_id)
            if not auth_token:
                return self._create_error_response("AUTH_ERROR", "No authentication token found")

            self.ws_client = UpstoxWebSocketClient(auth_token)
            self.ws_client.callbacks = {
                "on_message": self._on_market_data,
                "on_error": self._on_error,
                "on_close": self._on_close,
            }
            
            self.logger.info("UpstoxWebSocketClient initialized successfully")
            return self._create_success_response("Initialized Upstox WebSocket adapter")

        except Exception as e:
            self.logger.error(f"Initialization error: {e}")
            return self._create_error_response("INIT_ERROR", str(e))

    def connect(self) -> Dict[str, Any]:
        """Establish WebSocket connection"""
        try:
            if self.connected:
                return self._create_success_response("Already connected")

            if not self.ws_client:
                return self._create_error_response("NOT_INITIALIZED", "WebSocket client not initialized")

            self._start_event_loop()
            success = self._connect_websocket()
            
            if success:
                self.connected = True
                self.running = True
                self.logger.info("Connected to Upstox WebSocket")
                return self._create_success_response("Connected to Upstox WebSocket")
            else:
                return self._create_error_response("CONNECTION_FAILED", "Failed to connect to Upstox WebSocket")

        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return self._create_error_response("CONNECTION_ERROR", str(e))

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 0) -> Dict[str, Any]:
        """Subscribe to market data with Upstox-specific implementation following Angel's pattern"""
        # Validate mode
        if mode not in [1, 2, 3]:
            return self._create_error_response("INVALID_MODE", 
                                              f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)")
        
        # Check connection status
        if not self.connected:
            return self._create_error_response("NOT_CONNECTED", "WebSocket is not connected")

        if not self.ws_client or not self.event_loop:
            return self._create_error_response("NOT_INITIALIZED", "WebSocket client not initialized")

        # Get token info
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}")

        instrument_key = self._create_instrument_key(token_info)
        
        # Generate unique correlation ID like Angel does
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        # Check for duplicate subscriptions using correlation_id
        with self.lock:
            if correlation_id in self.subscriptions:
                self.logger.info(f"Already subscribed to {symbol} on {exchange} with mode {mode}")
                return self._create_success_response(f"Already subscribed to {symbol} on {exchange}")
        
        subscription_info = {
            'symbol': symbol,
            'exchange': exchange,
            'mode': mode,
            'depth_level': depth_level,
            'token': token_info['token'],
            'instrument_key': instrument_key
        }

        # Store subscription before sending request (Angel pattern)
        with self.lock:
            self.subscriptions[correlation_id] = subscription_info
            self.logger.info(f"Stored subscription: {correlation_id} -> {subscription_info}")
        
        # Subscribe if connected (Angel pattern)
        if self.connected and self.ws_client:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.ws_client.subscribe([instrument_key], self._get_upstox_mode(mode, depth_level)),
                    self.event_loop
                )
                
                # Use shorter timeout like Angel (no retry loop in subscribe method)
                if future.result(timeout=5):
                    self.logger.info(f"Subscribed to {symbol} on {exchange} (key={instrument_key})")
                    return self._create_success_response(f"Subscribed to {symbol} on {exchange}")
                else:
                    # Clean up on failure
                    with self.lock:
                        self.subscriptions.pop(correlation_id, None)
                    return self._create_error_response("SUBSCRIBE_FAILED", f"Failed to subscribe to {symbol} on {exchange}")
                    
            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                # Clean up on error
                with self.lock:
                    self.subscriptions.pop(correlation_id, None)
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))
        
        # Return success response (subscription will be processed when connected)
        return self._create_success_response(
            f"Subscription requested for {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> Dict[str, Any]:
        """Unsubscribe from market data for a symbol/exchange"""
        try:
            if not self.ws_client or not self.event_loop:
                return self._create_error_response("NOT_INITIALIZED", "WebSocket client not initialized")

            # Get token info
            token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
            if not token_info:
                return self._create_error_response("SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}")

            instrument_key = self._create_instrument_key(token_info)
            
            # Generate unique correlation ID like Angel does
            correlation_id = f"{symbol}_{exchange}_{mode}"
            
            # Check for subscription using correlation_id
            with self.lock:
                if correlation_id not in self.subscriptions:
                    self.logger.info(f"Not subscribed to {symbol} on {exchange} with mode {mode}")
                    return self._create_success_response(f"Not subscribed to {symbol} on {exchange}")
        
            # Send unsubscription request
            future = asyncio.run_coroutine_threadsafe(
                self.ws_client.unsubscribe([instrument_key]),
                self.event_loop
            )

            if future.result(timeout=5):
                with self.lock:
                    self.subscriptions.pop(correlation_id, None)
                self.logger.info(f"Unsubscribed from {symbol} on {exchange}")
                return self._create_success_response(f"Unsubscribed from {symbol} on {exchange}")
            else:
                return self._create_error_response("UNSUBSCRIBE_FAILED", f"Failed to unsubscribe from {symbol} on {exchange}")

        except Exception as e:
            self.logger.error(f"Unsubscribe error: {e}")
            return self._create_error_response("UNSUBSCRIBE_ERROR", str(e))

    def disconnect(self) -> None:
        """Disconnect from WebSocket and cleanup resources"""
        try:
            self.running = False
            self.connected = False

            if self.ws_client and self.event_loop:
                future = asyncio.run_coroutine_threadsafe(
                    self.ws_client.disconnect(),
                    self.event_loop
                )
                future.result(timeout=5)

            self._stop_event_loop()
            self.cleanup_zmq()
            self.logger.info("Disconnected from Upstox WebSocket")

        except Exception as e:
            self.logger.error(f"Disconnect error: {e}")

    # Private helper methods
    def _get_auth_token(self, auth_data: Optional[Dict[str, Any]], user_id: str) -> Optional[str]:
        """Get authentication token from auth_data or database"""
        if auth_data and 'auth_token' in auth_data:
            return auth_data['auth_token']
        return get_auth_token(user_id)

    def _start_event_loop(self):
        """Start event loop in a separate thread"""
        if not self.event_loop or not self.ws_thread or not self.ws_thread.is_alive():
            self.event_loop = asyncio.new_event_loop()
            self.ws_thread = threading.Thread(target=self._run_event_loop, daemon=True)
            self.ws_thread.start()
            self.logger.info("Started event loop thread")

    def _run_event_loop(self):
        """Run the event loop in a separate thread"""
        if self.event_loop:
            asyncio.set_event_loop(self.event_loop)
            self.event_loop.run_forever()

    def _connect_websocket(self) -> bool:
        """Connect to WebSocket and return success status"""
        if not self.event_loop:
            return False
            
        future = asyncio.run_coroutine_threadsafe(
            self.ws_client.connect(),
            self.event_loop
        )
        return future.result(timeout=10)

    def _stop_event_loop(self):
        """Stop event loop and wait for thread to finish"""
        if self.event_loop:
            self.event_loop.call_soon_threadsafe(self.event_loop.stop)
            
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=5)

    def _create_instrument_key(self, token_info: Dict[str, Any]) -> str:
        """Create instrument key from token info"""
        token = token_info['token']
        brexchange = token_info['brexchange']
        
        # Remove duplicate exchange prefix if present
        if '|' in token:
            token = token.split('|')[-1]
            
        return f"{brexchange}|{token}"

    def _get_upstox_mode(self, mode: int, depth_level: int) -> str:
        """Convert internal mode to Upstox mode string"""
        mode_map = {1: "ltpc", 2: "full", 3: "full"}
        return mode_map.get(mode, "ltpc")

    def _find_subscription_by_feed_key(self, feed_key: str) -> Optional[Dict[str, Any]]:
        """Find subscription info by matching the feed key to stored instrument_key"""
        with self.lock:
            self.logger.debug(f"Looking for feed_key: {feed_key}")
            self.logger.debug(f"Available subscriptions: {list(self.subscriptions.keys())}")
            
            # Check all subscriptions to find matching instrument_key
            for correlation_id, sub_info in self.subscriptions.items():
                self.logger.debug(f"Checking {correlation_id}: instrument_key={sub_info.get('instrument_key')}")
                if sub_info.get('instrument_key') == feed_key:
                    self.logger.info(f"Found subscription match: {correlation_id} for feed_key: {feed_key}")
                    return sub_info
            
            # Fallback: Extract token and try to match
            if '|' in feed_key:
                token = feed_key.split('|')[-1]
                self.logger.debug(f"Trying token fallback with token: {token}")
                for correlation_id, sub_info in self.subscriptions.items():
                    if sub_info.get('token') == token:
                        self.logger.info(f"Found token match: {correlation_id} for token: {token}")
                        return sub_info
        
        self.logger.warning(f"No subscription found for feed key: {feed_key}")
        return None

    def _create_topic(self, exchange: str, symbol: str, mode: int) -> str:
        """Create ZMQ topic for publishing"""
        mode_map = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}
        mode_str = mode_map.get(mode, 'QUOTE')
        return f"{exchange}_{symbol}_{mode_str}"

    # WebSocket event handlers
    async def _on_open(self):
        """Callback when WebSocket connection is opened"""
        self.logger.info("Upstox WebSocket connection opened")
        self.connected = True
        
        # Resubscribe to existing subscriptions on reconnection (Angel pattern)
        with self.lock:
            for correlation_id, sub in self.subscriptions.items():
                try:
                    instrument_key = sub['instrument_key']
                    mode = sub['mode']
                    depth_level = sub['depth_level']
                    
                    future = asyncio.run_coroutine_threadsafe(
                        self.ws_client.subscribe([instrument_key], self._get_upstox_mode(mode, depth_level)),
                        self.event_loop
                    )
                    
                    if future.result(timeout=5):
                        self.logger.info(f"Resubscribed to {sub['symbol']}.{sub['exchange']}")
                    else:
                        self.logger.warning(f"Failed to resubscribe to {sub['symbol']}.{sub['exchange']}")
                        
                except Exception as e:
                    self.logger.error(f"Error resubscribing to {sub['symbol']}.{sub['exchange']}: {e}")

    async def _on_error(self, error: str):
        """Handle WebSocket errors"""
        self.logger.error(f"WebSocket error: {error}")
        self.connected = False
        
        if self.running:
            await self._attempt_reconnect()

    async def _on_close(self):
        """Handle WebSocket closure"""
        self.logger.info("WebSocket connection closed")
        self.connected = False
        
        if self.running:
            await self._attempt_reconnect()

    async def _attempt_reconnect(self):
        """Attempt to reconnect WebSocket"""
        try:
            if not self.ws_client:
                self.logger.error("Cannot reconnect: WebSocket client not initialized")
                return

            self.logger.info("Attempting to reconnect...")
            success = await self.ws_client.connect()
            
            if success:
                self.connected = True
                self.logger.info("Reconnected successfully")
                
                # Resubscribe to all instruments
                for instrument_key, sub_info in self.subscriptions.items():
                    await self.ws_client.subscribe(
                        [instrument_key],
                        self._get_upstox_mode(sub_info['mode'], sub_info['depth_level'])
                    )
            else:
                self.logger.error("Reconnection failed")
                
        except Exception as e:
            self.logger.error(f"Reconnection error: {e}")

    async def _on_market_data(self, data: Dict[str, Any]):
        """Handle market data messages"""
        try:
            # Handle market info messages
            if data.get("type") == "market_info":
                self._handle_market_info(data)
                return
                
            # Process market data feeds
            feeds = data.get("feeds", {})
            if not feeds:
                return
                
            current_ts = data.get("currentTs", 0)
            
            for feed_key, feed_data in feeds.items():
                self._process_feed(feed_key, feed_data, current_ts)
                
        except Exception as e:
            self.logger.error(f"Market data handler error: {e}")

    def _handle_market_info(self, data: Dict[str, Any]):
        """Handle market info messages"""
        if "marketInfo" in data:
            self.market_status = data["marketInfo"]
            if "segmentStatus" in self.market_status:
                self.logger.info(f"Market status update: {self.market_status['segmentStatus']}")

    def _process_feed(self, feed_key: str, feed_data: Dict[str, Any], current_ts: int):
        """Process individual feed data"""
        try:
            # Find all subscriptions that match this feed key (could be multiple modes)
            matching_subscriptions = []
            with self.lock:
                self.logger.debug(f"Looking for matches for feed_key: {feed_key}")
                self.logger.debug(f"Available subscriptions: {list(self.subscriptions.keys())}")
                
                for correlation_id, sub_info in self.subscriptions.items():
                    # Check instrument_key match
                    if sub_info.get('instrument_key') == feed_key:
                        matching_subscriptions.append((correlation_id, sub_info))
                        self.logger.debug(f"Matched by instrument_key: {correlation_id}")
                    # Check token match as fallback
                    elif '|' in feed_key:
                        token = feed_key.split('|')[-1]
                        if sub_info.get('token') == token or sub_info.get('token') == feed_key:
                            matching_subscriptions.append((correlation_id, sub_info))
                            self.logger.debug(f"Matched by token: {correlation_id}")
                
                self.logger.info(f"Found {len(matching_subscriptions)} matching subscriptions for {feed_key}")
            
            if not matching_subscriptions:
                self.logger.warning(f"No subscription found for feed key: {feed_key}")
                return
            
            # Process data for each matching subscription (different modes)
            for correlation_id, sub_info in matching_subscriptions:
                symbol = sub_info['symbol']
                exchange = sub_info['exchange']
                mode = sub_info['mode']
                token = sub_info['token']
                
                topic = self._create_topic(exchange, symbol, mode)
                market_data = self._extract_market_data(feed_data, sub_info, current_ts)
                
                if market_data:
                    self.logger.info(f"Publishing data for {symbol} mode {mode} on topic: {topic}")
                    if mode == 2:  # Quote mode - show the complete data structure
                        self.logger.info(f"QUOTE DATA: {market_data}")
                    
                    if mode == 3:  # Depth mode
                        # For depth mode, structure the data properly with LTP at top level
                        depth_data = market_data.copy()
                        depth_levels = {
                            'buy': depth_data.pop('buy', []),
                            'sell': depth_data.pop('sell', []),
                            'timestamp': depth_data.get('timestamp', current_ts)
                        }
                        # Keep LTP and other data at top level, put depth levels in 'depth' key
                        depth_data['depth'] = depth_levels
                        self.publish_market_data(topic, depth_data)
                    else:
                        self.publish_market_data(topic, market_data)
                    
        except Exception as e:
            self.logger.error(f"Error processing feed for {feed_key}: {e}")

    def _extract_market_data(self, feed_data: Dict[str, Any], sub_info: Dict[str, Any], current_ts: int) -> Dict[str, Any]:
        """Extract market data based on subscription mode"""
        mode = sub_info['mode']
        symbol = sub_info['symbol']
        exchange = sub_info['exchange']
        token = sub_info['token']
        
        base_data = {"symbol": symbol, "exchange": exchange, "token": token}
        
        if mode == 1:  # LTP mode
            return self._extract_ltp_data(feed_data, base_data)
        elif mode == 2:  # QUOTE mode
            return self._extract_quote_data(feed_data, base_data, current_ts)
        elif mode == 3:  # DEPTH mode
            depth_data = self._extract_depth_data(feed_data, current_ts)
            depth_data.update(base_data)
            return depth_data
        
        return {}

    def _extract_ltp_data(self, feed_data: Dict[str, Any], base_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract LTP data from feed"""
        market_data = base_data.copy()
        
        if "ltpc" in feed_data:
            ltpc = feed_data["ltpc"]
            market_data.update({
                "ltp": float(ltpc.get("ltp", 0)),
                "ltq": int(ltpc.get("ltq", 0)),
                "ltt": int(ltpc.get("ltt", 0)),
                "cp": float(ltpc.get("cp", 0))
            })
        
        return market_data

    def _extract_quote_data(self, feed_data: Dict[str, Any], base_data: Dict[str, Any], current_ts: int) -> Dict[str, Any]:
        """Extract QUOTE data from feed"""
        if "fullFeed" not in feed_data:
            return {}
            
        full_feed = feed_data["fullFeed"]
        ff = full_feed.get("marketFF") or full_feed.get("indexFF", {})
        
        # Log the full feed structure to understand available fields
        self.logger.info(f"Full feed structure for quote extraction: {list(ff.keys())}")
        
        # Extract LTP and quantity data
        ltpc = ff.get("ltpc", {})
        ltp = ltpc.get("ltp", 0)
        ltq = ltpc.get("ltq", 0)  # Last traded quantity
        
        # Extract OHLC data
        ohlc_list = ff.get("marketOHLC", {}).get("ohlc", [])
        ohlc = next((o for o in ohlc_list if o.get("interval") == "1d"), ohlc_list[0] if ohlc_list else {})
        
        # Extract market level data - try different possible field names
        market_level = ff.get("marketLevel", {})
        self.logger.info(f"Market level keys: {list(market_level.keys()) if market_level else 'None'}")
        
        # Also check what's in OHLC
        self.logger.info(f"OHLC keys: {list(ohlc.keys()) if ohlc else 'None'}")
        
        # Check if there are other sections with volume data
        if "marketStatus" in ff:
            self.logger.info(f"Market status keys: {list(ff['marketStatus'].keys())}")
        if "optionGreeks" in ff:
            self.logger.info(f"Option Greeks keys: {list(ff['optionGreeks'].keys())}")
        
        # Extract volume from OHLC (confirmed working)
        volume = ohlc.get("vol", 0) if ohlc else 0
        
        # Extract average price from 'atp' field (Average Traded Price)
        avg_price = float(ff.get("atp", 0))
        
        # Extract buy/sell quantities from 'tbq' and 'tsq' fields
        total_buy_qty = int(ff.get("tbq", 0))  # Total Buy Quantity
        total_sell_qty = int(ff.get("tsq", 0))  # Total Sell Quantity
        
        self.logger.debug(f"Extracted values - volume: {volume}, atp: {avg_price}, tbq: {total_buy_qty}, tsq: {total_sell_qty}")
        
        market_data = base_data.copy()
        market_data.update({
            "open": float(ohlc.get("open", 0)),
            "high": float(ohlc.get("high", 0)),
            "low": float(ohlc.get("low", 0)),
            "close": float(ohlc.get("close", 0)),
            "ltp": float(ltp),
            "last_quantity": int(ltq),
            "volume": int(volume),
            "average_price": float(avg_price),
            "total_buy_quantity": int(total_buy_qty),
            "total_sell_quantity": int(total_sell_qty),
            "timestamp": int(ohlc.get("ts", current_ts))
        })
        
        return market_data

    def _extract_depth_data(self, feed_data: Dict[str, Any], current_ts: int) -> Dict[str, Any]:
        """Extract depth data from feed"""
        if "fullFeed" not in feed_data:
            return {'buy': [], 'sell': [], 'timestamp': current_ts, 'ltp': 0}
        
        full_feed = feed_data["fullFeed"]
        market_ff = full_feed.get("marketFF") or full_feed.get("indexFF", {})
        market_level = market_ff.get("marketLevel", {})
        bid_ask = market_level.get("bidAskQuote", [])
        
        # Extract LTP data from ltpc field
        ltpc = market_ff.get("ltpc", {})
        ltp = float(ltpc.get("ltp", 0))
        
        buy_levels = []
        sell_levels = []
        
        for level in bid_ask:
            # Process bids
            bid_price = float(level.get("bidP", 0))
            bid_qty = int(float(level.get("bidQ", 0)))
            if bid_price > 0:
                buy_levels.append({'price': bid_price, 'quantity': bid_qty, 'orders': 0})
            
            # Process asks
            ask_price = float(level.get("askP", 0))
            ask_qty = int(float(level.get("askQ", 0)))
            if ask_price > 0:
                sell_levels.append({'price': ask_price, 'quantity': ask_qty, 'orders': 0})
        
        # Sort and ensure minimum 5 levels
        buy_levels = sorted(buy_levels, key=lambda x: x['price'], reverse=True)
        sell_levels = sorted(sell_levels, key=lambda x: x['price'])
        
        buy_levels.extend([{'price': 0.0, 'quantity': 0, 'orders': 0}] * (5 - len(buy_levels)))
        sell_levels.extend([{'price': 0.0, 'quantity': 0, 'orders': 0}] * (5 - len(sell_levels)))
        
        return {
            'buy': buy_levels[:5],
            'sell': sell_levels[:5],
            'timestamp': current_ts,
            'ltp': ltp  # Include LTP in the depth data
        }
