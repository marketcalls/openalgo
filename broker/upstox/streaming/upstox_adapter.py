# broker/upstox/streaming/upstox_adapter.py
import asyncio
import threading
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .upstox_client import UpstoxWebSocketClient
from database.auth_db import get_auth_token
from database.token_db import get_token, get_symbol

class UpstoxWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Upstox V3 implementation of WebSocket adapter.

    Protocol:
    - Uses UpstoxWebSocketClient for all WebSocket operations.
    - All outgoing subscription/unsubscription messages are sent as JSON text.
    - All incoming messages are decoded from protobuf to dict before being handled by this adapter.
    - All internal handlers expect dicts, never raw protobuf.
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
        self.token_to_symbol_map: Dict[str, Dict[str, str]] = {}
        # Add mapping for full instrument keys to our subscription keys
        self.instrument_key_mapping: Dict[str, str] = {}

    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Initialize the adapter with authentication data"""
        try:
            # Get auth token from database or auth_data
            auth_token = None
            if auth_data and 'auth_token' in auth_data:
                auth_token = auth_data['auth_token']
            else:
                auth_token = get_auth_token(user_id)
                
            if not auth_token:
                return self._create_error_response(
                    "AUTH_ERROR",
                    "No authentication token found"
                )

            # Initialize WebSocket client
            self.ws_client = UpstoxWebSocketClient(auth_token)
            self.ws_client.callbacks = {
                "on_message": self._on_market_data,
                "on_error": self._on_error,
                "on_close": self._on_close,
            }
            self.logger.info("UpstoxWebSocketClient initialized and callbacks set.")
            return self._create_success_response("Initialized Upstox WebSocket adapter")

        except Exception as e:
            self.logger.error(f"Initialization error: {e}")
            return self._create_error_response("INIT_ERROR", str(e))

    def _run_event_loop(self):
        """Run the event loop in a separate thread"""
        if self.event_loop is None:
            return
        asyncio.set_event_loop(self.event_loop)
        self.event_loop.run_forever()
        
    def connect(self) -> Dict[str, Any]:
        """Establish WebSocket connection"""
        try:
            if self.connected:
                self.logger.info("Already connected to Upstox WebSocket.")
                return self._create_success_response("Already connected")

            if self.ws_client is None:
                self.logger.error("WebSocket client not initialized.")
                return self._create_error_response(
                    "NOT_INITIALIZED",
                    "WebSocket client not initialized"
                )

            # Start event loop in a dedicated thread if not running
            if not self.event_loop or not self.ws_thread or not self.ws_thread.is_alive():
                self.event_loop = asyncio.new_event_loop()
                self.ws_thread = threading.Thread(
                    target=self._run_event_loop,
                    daemon=True
                )
                self.ws_thread.start()
                self.logger.info("Started new event loop thread for Upstox WebSocket.")

            if self.event_loop is None:
                self.logger.error("Event loop not initialized.")
                return self._create_error_response(
                    "EVENT_LOOP_ERROR",
                    "Event loop not initialized"
                )

            # Connect WebSocket asynchronously
            future = asyncio.run_coroutine_threadsafe(
                self.ws_client.connect(),
                self.event_loop
            )

            # Wait for connection result
            success = future.result(timeout=10)
            if success:
                self.connected = True
                self.running = True
                self.logger.info("Connected to Upstox WebSocket.")
                return self._create_success_response("Connected to Upstox WebSocket")
            else:
                self.logger.error("Failed to connect to Upstox WebSocket.")
                return self._create_error_response(
                    "CONNECTION_FAILED",
                    "Failed to connect to Upstox WebSocket"
                )

        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return self._create_error_response("CONNECTION_ERROR", str(e))

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 0) -> Dict[str, Any]:
        """Subscribe to market data for a symbol/exchange with the specified mode and depth level."""
        try:
            if not self.connected:
                return self._create_error_response(
                    "NOT_CONNECTED",
                    "WebSocket is not connected"
                )

            if not self.ws_client or not self.event_loop:
                return self._create_error_response(
                    "NOT_INITIALIZED",
                    "WebSocket client or event loop not initialized"
                )

            # Get token from symbol mapper
            token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
            if not token_info:
                return self._create_error_response(
                    "SYMBOL_NOT_FOUND",
                    f"Symbol {symbol} not found for exchange {exchange}"
                )

            token = token_info['token']
            brexchange = token_info['brexchange']

            # Create instrument key for subscription - remove duplicate exchange prefix if present
            if '|' in token:
                token = token.split('|')[-1]
            instrument_key = f"{brexchange}|{token}"

            # Store subscription info and token mapping
            self.subscriptions[instrument_key] = {
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'depth_level': depth_level,
                'token': token
            }
            self.token_to_symbol_map[token] = {
                'symbol': symbol,
                'exchange': exchange
            }

            # Also store mapping from token to subscription key for reverse lookup
            self.instrument_key_mapping[token] = instrument_key

            self.logger.info(f"Subscribing to {instrument_key} for {symbol} on {exchange} (mode={mode}, depth_level={depth_level})")

            # Send subscribe request
            future = asyncio.run_coroutine_threadsafe(
                self.ws_client.subscribe(
                    [instrument_key],
                    self._get_upstox_mode(mode, depth_level)
                ),
                self.event_loop
            )

            success = future.result(timeout=5)
            if success:
                self.logger.info(f"Successfully subscribed to {symbol} on {exchange} (instrument_key={instrument_key})")
                return self._create_success_response(
                    f"Subscribed to {symbol} on {exchange} with token {token}"
                )
            else:
                # Clean up on failure
                self.subscriptions.pop(instrument_key, None)
                self.token_to_symbol_map.pop(token, None)
                self.instrument_key_mapping.pop(token, None)
                return self._create_error_response(
                    "SUBSCRIBE_FAILED",
                    f"Failed to subscribe to {symbol} on {exchange}"
                )

        except Exception as e:
            self.logger.error(f"Subscribe error: {e}")
            return self._create_error_response("SUBSCRIBE_ERROR", str(e))

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> Dict[str, Any]:
        """Unsubscribe from market data for a symbol/exchange."""
        try:
            if not self.ws_client or not self.event_loop:
                return self._create_error_response(
                    "NOT_INITIALIZED",
                    "WebSocket client or event loop not initialized"
                )

            # Get token from symbol mapper
            token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
            if not token_info:
                return self._create_error_response(
                    "SYMBOL_NOT_FOUND",
                    f"Symbol {symbol} not found for exchange {exchange}"
                )

            token = token_info['token']
            brexchange = token_info['brexchange']

            # Create instrument key
            if '|' in token:
                token = token.split('|')[-1]
            instrument_key = f"{brexchange}|{token}"

            self.logger.info(f"Unsubscribing from {instrument_key} for {symbol} on {exchange}")

            # Send unsubscribe request
            future = asyncio.run_coroutine_threadsafe(
                self.ws_client.unsubscribe([instrument_key]),
                self.event_loop
            )

            success = future.result(timeout=5)
            if success:
                # Clean up on success
                self.subscriptions.pop(instrument_key, None)
                self.token_to_symbol_map.pop(token, None)
                self.instrument_key_mapping.pop(token, None)
                self.logger.info(f"Successfully unsubscribed from {symbol} on {exchange}")
                return self._create_success_response(
                    f"Unsubscribed from {symbol} on {exchange}"
                )
            else:
                return self._create_error_response(
                    "UNSUBSCRIBE_FAILED",
                    f"Failed to unsubscribe from {symbol} on {exchange}"
                )

        except Exception as e:
            self.logger.error(f"Unsubscribe error: {e}")
            return self._create_error_response("UNSUBSCRIBE_ERROR", str(e))

    def disconnect(self) -> None:
        """Disconnect from WebSocket, stop event loop, cleanup resources."""
        try:
            self.running = False
            self.connected = False

            if self.ws_client and self.event_loop:
                future = asyncio.run_coroutine_threadsafe(
                    self.ws_client.disconnect(),
                    self.event_loop
                )
                future.result(timeout=5)
                self.logger.info("WebSocket disconnect coroutine completed.")

            # Stop event loop
            if self.event_loop:
                self.event_loop.call_soon_threadsafe(self.event_loop.stop)
                self.logger.info("Event loop stop signal sent.")

            # Wait for thread to end
            if self.ws_thread and self.ws_thread.is_alive():
                self.ws_thread.join(timeout=5)
                self.logger.info("WebSocket thread joined.")

            # Cleanup ZMQ resources
            self.cleanup_zmq()
            self.logger.info("Disconnected from Upstox WebSocket")

        except Exception as e:
            self.logger.error(f"Disconnect error: {e}")

    def _get_upstox_mode(self, mode: int, depth_level: int) -> str:
        """Convert internal mode to Upstox mode string"""
        if mode == 1:
            return "ltpc"
        elif mode == 2:
            return "full"
        elif mode == 3:
            return "full"
        else:
            return "ltpc"  # Default to LTPC mode
            
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
            if self.ws_client is None:
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

    def _find_subscription_by_feed_key(self, feed_key: str) -> Optional[Dict[str, Any]]:
        """Find subscription info by matching the feed key from Upstox"""
        # Try exact match first
        if feed_key in self.subscriptions:
            return self.subscriptions[feed_key]
        
        # Extract token from feed key (last part after |)
        if '|' in feed_key:
            token = feed_key.split('|')[-1]
            
            # Look for subscription with matching token
            for instrument_key, sub_info in self.subscriptions.items():
                if sub_info['token'] == token:
                    return sub_info
                    
            # Also check if we have a mapping for this token
            if token in self.instrument_key_mapping:
                mapped_key = self.instrument_key_mapping[token]
                if mapped_key in self.subscriptions:
                    return self.subscriptions[mapped_key]
        
        return None

    async def _on_market_data(self, data: Dict[str, Any]):
        """Handle market data messages"""
        self.logger.debug(f"[RAW MARKET DATA] {json.dumps(data, indent=2)}")
        
        try:
            # Handle market info messages
            if data.get("type") == "market_info":
                if "marketInfo" in data:
                    self.market_status = data["marketInfo"]
                    if "segmentStatus" in self.market_status:
                        self.logger.info(f"Market status update: {json.dumps(self.market_status['segmentStatus'], indent=2)}")
                return
                
            # Process market data feeds
            feeds = data.get("feeds", {})
            if not feeds:
                return
                
            # Process each feed
            for feed_key, feed_data in feeds.items():
                try:
                    # Find subscription using improved lookup
                    sub_info = self._find_subscription_by_feed_key(feed_key)
                    if not sub_info:
                        self.logger.warning(f"No subscription found for feed key: {feed_key}")
                        continue
                        
                    symbol = sub_info['symbol']
                    exchange = sub_info['exchange']
                    mode = sub_info['mode']
                    token = sub_info['token']
                    
                    # Create topic for ZeroMQ
                    mode_str = 'LTP' if mode == 1 else 'QUOTE' if mode == 2 else 'DEPTH'
                    topic = f"{exchange}_{symbol}_{mode_str}"
                    
                    # Process based on mode
                    if mode == 1:  # LTP mode
                        market_data = self._extract_ltp_data(feed_data, symbol, exchange, token)
                    elif mode == 2:  # QUOTE mode
                        market_data = self._extract_quote_data(feed_data, symbol, exchange, token, data.get("currentTs", 0))
                    elif mode == 3:  # DEPTH mode
                        market_data = self._extract_depth_data_from_feed(feed_data, data.get("currentTs", 0))
                        # Add symbol and exchange info to depth data
                        market_data.update({
                            'symbol': symbol,
                            'exchange': exchange,
                            'token': token
                        })
                    else:
                        continue
                        
                    if market_data:
                        self.logger.debug(f"Publishing {mode_str} data for {symbol} on topic: {topic}")
                        if mode == 3:
                            self.publish_market_data(topic, {"depth": market_data})
                        else:
                            self.publish_market_data(topic, market_data)
                        
                except Exception as e:
                    self.logger.error(f"Error processing feed for {feed_key}: {e}")
                    
        except Exception as e:
            self.logger.error(f"Market data handler error: {e}")

    def _extract_ltp_data(self, feed_data: Dict, symbol: str, exchange: str, token: str) -> Dict[str, Any]:
        """Extract LTP data from feed"""
        market_data = {"symbol": symbol, "exchange": exchange, "token": token}
        
        if "ltpc" in feed_data:
            ltpc = feed_data["ltpc"]
            market_data.update({
                "ltp": float(ltpc.get("ltp", 0)),
                "ltq": int(ltpc.get("ltq", 0)),
                "ltt": int(ltpc.get("ltt", 0)),
                "cp": float(ltpc.get("cp", 0))
            })
        
        return market_data

    def _extract_quote_data(self, feed_data: Dict, symbol: str, exchange: str, token: str, current_ts: int) -> Dict[str, Any]:
        """Extract QUOTE data from feed"""
        if "fullFeed" not in feed_data:
            return {}
            
        full_feed = feed_data["fullFeed"]
        ff = full_feed.get("marketFF") or full_feed.get("indexFF", {})
        
        ltp = ff.get("ltpc", {}).get("ltp", 0)
        ohlc_list = ff.get("marketOHLC", {}).get("ohlc", [])
        
        # Prefer '1d' interval, else first available
        ohlc = next((o for o in ohlc_list if o.get("interval") == "1d"), ohlc_list[0] if ohlc_list else {})
        
        return {
            "symbol": symbol,
            "exchange": exchange,
            "token": token,
            "open": float(ohlc.get("open", 0)),
            "high": float(ohlc.get("high", 0)),
            "low": float(ohlc.get("low", 0)),
            "close": float(ohlc.get("close", 0)),
            "ltp": float(ltp),
            "timestamp": int(ohlc.get("ts", current_ts))
        }

    def _extract_depth_data_from_feed(self, feed_data: Dict, current_ts: int) -> Dict:
        """
        Extract depth data from feed and convert to standardized format:
        {
            'buy': [{'price': float, 'quantity': int, 'orders': int}, ...],
            'sell': [{'price': float, 'quantity': int, 'orders': int}, ...]
        }
        """
        self.logger.debug("=== DEPTH EXTRACTION STARTED ===")
        
        if "fullFeed" not in feed_data:
            self.logger.warning("No fullFeed in feed_data")
            return {'buy': [], 'sell': []}
            
        full_feed = feed_data["fullFeed"]
        market_ff = full_feed.get("marketFF") or full_feed.get("indexFF", {})
        market_level = market_ff.get("marketLevel", {})
        bid_ask = market_level.get("bidAskQuote", [])
        
        buy_levels = []
        sell_levels = []
        
        for level in bid_ask:
            # Process bids
            bid_price = float(level.get("bidP", 0))
            bid_qty = int(float(level.get("bidQ", 0)))
            if bid_price > 0:
                buy_levels.append({
                    'price': bid_price, 
                    'quantity': bid_qty,
                    'orders': 0
                })
            
            # Process asks
            ask_price = float(level.get("askP", 0))
            ask_qty = int(float(level.get("askQ", 0)))
            if ask_price > 0:
                sell_levels.append({
                    'price': ask_price,
                    'quantity': ask_qty,
                    'orders': 0
                })
        
        # Sort and pad levels
        buy_levels = sorted(buy_levels, key=lambda x: x['price'], reverse=True)
        sell_levels = sorted(sell_levels, key=lambda x: x['price'])
        
        # Ensure minimum 5 levels
        buy_levels.extend([{'price': 0.0, 'quantity': 0, 'orders': 0}] * (5 - len(buy_levels)))
        sell_levels.extend([{'price': 0.0, 'quantity': 0, 'orders': 0}] * (5 - len(sell_levels)))
        
        return {
            'buy': buy_levels[:5],
            'sell': sell_levels[:5],
            'timestamp': current_ts
        }

    # Additional debugging method to check ZMQ publishing
    def publish_market_data(self, topic: str, data: Dict[str, Any]):
        # """Enhanced publish method with debugging"""
        try:
            self.logger.debug(f"=== PUBLISHING TO ZMQ ===")
            self.logger.debug(f"Topic: {topic}")
            self.logger.debug(f"Data: {json.dumps(data, indent=2)}")
            
            # Call the parent method
            super().publish_market_data(topic, data)
            
            self.logger.debug(f"Successfully published to ZMQ topic: {topic}")
            
        except Exception as e:
            self.logger.error(f"Error publishing to ZMQ: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")