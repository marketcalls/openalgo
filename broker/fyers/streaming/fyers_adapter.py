"""
Fyers WebSocket Adapter for OpenAlgo
Handles WebSocket streaming for all exchanges: NSE, NFO, BSE, BFO, MCX
Uses HSM binary protocol for real-time data
"""

import logging
import time
import threading
from typing import Dict, List, Any, Optional, Callable
from collections import defaultdict

from .fyers_hsm_websocket import FyersHSMWebSocket
from .fyers_token_converter import FyersTokenConverter
from .fyers_mapping import FyersDataMapper

class FyersAdapter:
    """
    Fyers WebSocket adapter for OpenAlgo streaming service
    Follows OpenAlgo adapter pattern similar to Angel, Zerodha etc.
    """
    
    def __init__(self, access_token: str, userid: str):
        """
        Initialize Fyers adapter
        
        Args:
            access_token: Fyers access token
            userid: User ID
        """
        self.access_token = access_token
        self.userid = userid
        self.logger = logging.getLogger("fyers_adapter")
        
        # Initialize components
        self.token_converter = FyersTokenConverter(access_token)
        self.data_mapper = FyersDataMapper()
        self.ws_client = None
        
        # Subscription tracking
        self.active_subscriptions = {}  # symbol -> subscription_info
        self.subscription_callbacks = {}  # data_type -> callback
        self.symbol_to_hsm = {}  # symbol -> hsm_token mapping
        
        # Connection state
        self.connected = False
        self.connecting = False
        
        # Threading
        self.lock = threading.Lock()
        
        # Deduplication tracking
        self.last_data = {}  # symbol -> {ltp, timestamp} for deduplication
        
        self.logger.info(f"Fyers adapter initialized for user: {userid}")
    
    def connect(self) -> bool:
        """
        Connect to Fyers HSM WebSocket
        
        Returns:
            True if connection successful, False otherwise
        """
        if self.connected:
            self.logger.warning("Already connected to Fyers WebSocket")
            return True
        
        if self.connecting:
            self.logger.warning("Connection already in progress")
            return False
        
        try:
            self.connecting = True
            self.logger.info("Connecting to Fyers HSM WebSocket...")
            
            # Initialize WebSocket client
            self.ws_client = FyersHSMWebSocket(
                access_token=self.access_token,
                log_path=""
            )
            
            # Set callbacks
            self.ws_client.set_callbacks(
                on_message=self._on_message,
                on_error=self._on_error,
                on_open=self._on_open,
                on_close=self._on_close
            )
            
            # Connect
            self.ws_client.connect()
            
            # Wait for authentication
            timeout = 15
            start_time = time.time()
            while not self.ws_client.is_connected() and time.time() - start_time < timeout:
                time.sleep(0.1)
            
            if self.ws_client.is_connected():
                self.connected = True
                self.logger.info("✅ Connected to Fyers HSM WebSocket")
                return True
            else:
                self.logger.error("❌ Failed to authenticate with Fyers HSM WebSocket")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Connection error: {e}")
            return False
        finally:
            self.connecting = False
    
    def disconnect(self):
        """Disconnect from Fyers WebSocket"""
        try:
            self.connected = False
            if self.ws_client:
                self.ws_client.disconnect()
                self.ws_client = None
            self.active_subscriptions.clear()
            self.symbol_to_hsm.clear()
            self.logger.info("Disconnected from Fyers WebSocket")
        except Exception as e:
            self.logger.error(f"Error during disconnect: {e}")
    
    def subscribe_symbols(self, symbols: List[Dict[str, str]], data_type: str, callback: Callable):
        """
        Subscribe to symbols for market data
        
        Args:
            symbols: List of symbol dicts with 'exchange' and 'symbol' keys
            data_type: Type of data ("SymbolUpdate", "DepthUpdate")
            callback: Callback function to receive data
        """
        if not self.connected:
            self.logger.error("Not connected to Fyers WebSocket")
            return False
        
        try:
            with self.lock:
                # Store callback per symbol to prevent data mixing
                for symbol_info in symbols:
                    exchange = symbol_info.get("exchange", "NSE")
                    symbol = symbol_info.get("symbol", "")
                    if symbol:
                        full_symbol = f"{exchange}:{symbol}"
                        # Store callback per symbol
                        self.subscription_callbacks[f"{data_type}_{full_symbol}"] = callback
                
                # Store subscription info for tracking
                valid_symbols = []
                for symbol_info in symbols:
                    exchange = symbol_info.get("exchange", "NSE")
                    symbol = symbol_info.get("symbol", "")
                    
                    if not symbol:
                        continue
                    
                    valid_symbols.append({"exchange": exchange, "symbol": symbol})
                    
                    # Store subscription info
                    full_symbol = f"{exchange}:{symbol}"
                    self.active_subscriptions[full_symbol] = {
                        "exchange": exchange,
                        "symbol": symbol,
                        "data_type": data_type,
                        "subscribed_at": time.time()
                    }
                
                if not valid_symbols:
                    self.logger.warning("No valid symbols to subscribe")
                    return False
                
                self.logger.info(f"Converting {len(valid_symbols)} OpenAlgo symbols to HSM format using database lookup...")
                
                # Convert OpenAlgo symbols directly to HSM tokens using database lookup
                hsm_tokens, token_mappings, invalid_symbols = self.token_converter.convert_openalgo_symbols_to_hsm(
                    valid_symbols, data_type
                )
                
                if invalid_symbols:
                    self.logger.warning(f"Invalid symbols: {invalid_symbols}")
                
                if not hsm_tokens:
                    self.logger.error("No valid HSM tokens generated")
                    return False
                
                # Store HSM mappings for reverse lookup
                for hsm_token, brsymbol in token_mappings.items():
                    # Map HSM token back to OpenAlgo symbol
                    # The token_mappings now contains brsymbol format
                    for full_symbol, sub_info in self.active_subscriptions.items():
                        expected_brsymbol = f"{sub_info['exchange']}:{sub_info['symbol']}"
                        # Check if this brsymbol matches
                        if brsymbol == expected_brsymbol or brsymbol.endswith(sub_info['symbol']):
                            self.symbol_to_hsm[full_symbol] = hsm_token
                            self.logger.info(f"Mapped HSM token: {full_symbol} -> {hsm_token}")
                            break
                
                self.logger.info(f"Subscribing to {len(hsm_tokens)} HSM tokens...")
                
                # Subscribe to HSM WebSocket
                self.ws_client.subscribe_symbols(hsm_tokens, token_mappings)
                
                self.logger.info(f"✅ Subscription sent for {len(symbols)} symbols")
                return True
                
        except Exception as e:
            self.logger.error(f"Subscription error: {e}")
            return False
    
    def subscribe_ltp(self, symbols: List[Dict[str, str]], callback: Callable):
        """Subscribe to LTP data"""
        return self.subscribe_symbols(symbols, "SymbolUpdate", callback)
    
    def subscribe_quote(self, symbols: List[Dict[str, str]], callback: Callable):
        """Subscribe to Quote data"""
        return self.subscribe_symbols(symbols, "SymbolUpdate", callback)
    
    def subscribe_depth(self, symbols: List[Dict[str, str]], callback: Callable):
        """Subscribe to Depth data"""
        return self.subscribe_symbols(symbols, "DepthUpdate", callback)
    
    def unsubscribe_symbols(self, symbols: List[Dict[str, str]]):
        """
        Unsubscribe from symbols
        Note: HSM protocol doesn't support individual unsubscription easily
        This would require reconnection for full unsubscribe
        """
        self.logger.warning("HSM protocol doesn't support selective unsubscription")
        self.logger.info("To unsubscribe, disconnect and reconnect with new symbol list")
    
    def _on_open(self):
        """Handle WebSocket connection open"""
        self.logger.info("Fyers WebSocket connection opened")
    
    def _on_close(self):
        """Handle WebSocket connection close"""
        self.connected = False
        self.logger.info("Fyers WebSocket connection closed")
    
    def _on_error(self, error):
        """Handle WebSocket error"""
        self.logger.error(f"Fyers WebSocket error: {error}")
    
    def _on_message(self, fyers_data: Dict[str, Any]):
        """
        Handle incoming market data from Fyers
        
        Args:
            fyers_data: Raw data from Fyers HSM WebSocket
        """
        try:
            if not fyers_data:
                return
            
            # Determine data type and get appropriate callback
            fyers_type = fyers_data.get("type", "sf")
            update_type = fyers_data.get("update_type", "snapshot")
            
            # Map to OpenAlgo format first to get symbol info
            mapped_data = self.data_mapper.map_fyers_data(fyers_data, "Quote")
            if not mapped_data:
                return
            
            # Extract symbol information from mapped data
            symbol_str = mapped_data.get("symbol", "")
            if not symbol_str:
                return
            
            # Find matching subscription and callback
            callback = None
            openalgo_data_type = "Quote"  # Default
            matched_subscription = None
            
            # Debug: Log what we're trying to match
            self.logger.info(f"🔍 Trying to match symbol_str='{symbol_str}' against subscriptions:")
            for fs, si in self.active_subscriptions.items():
                self.logger.info(f"  - {fs}: {si['exchange']}:{si['symbol']}")
            
            # Look for matching subscription based on symbol
            for full_symbol, sub_info in self.active_subscriptions.items():
                expected_symbol = f"{sub_info['exchange']}:{sub_info['symbol']}"
                
                # Try exact match first
                if symbol_str == expected_symbol:
                    matched_subscription = sub_info
                    self.logger.info(f"✅ Exact match: {symbol_str} -> {full_symbol}")
                    break
                
                # Try alternative formats for the same symbol
                # Handle exchange and format mismatches
                
                # Case 1: Equity symbols - NSE:TCS-EQ should match NSE:TCS
                if symbol_str.startswith("NSE:") and sub_info['exchange'] == 'NSE':
                    symbol_part = symbol_str.split(':', 1)[1]
                    if symbol_part == f"{sub_info['symbol']}-EQ":
                        matched_subscription = sub_info
                        self.logger.info(f"✅ Equity match: {symbol_str} -> {full_symbol}")
                        break
                
                # Case 2: Index symbols - NSE:NIFTY50 should match NSE_INDEX:NIFTY
                if symbol_str.startswith("NSE:") and sub_info['exchange'] == 'NSE_INDEX':
                    symbol_part = symbol_str.split(':', 1)[1]
                    if (symbol_part == 'NIFTY50' and sub_info['symbol'] == 'NIFTY') or \
                       (symbol_part.replace('-INDEX', '') == sub_info['symbol']):
                        matched_subscription = sub_info
                        self.logger.info(f"✅ Index match: {symbol_str} -> {full_symbol}")
                        break
                
                # Case 3: Options - NSE:NIFTY25AUG25550PE should match NFO:NIFTY28AUG2525550PE
                if symbol_str.startswith("NSE:") and sub_info['exchange'] == 'NFO':
                    symbol_part = symbol_str.split(':', 1)[1]
                    sub_symbol = sub_info['symbol']
                    
                    # Extract core parts for comparison
                    # NSE:NIFTY25AUG25550PE vs NFO:NIFTY28AUG2525550PE
                    if 'NIFTY' in symbol_part and 'NIFTY' in sub_symbol:
                        # Extract strike and expiry info
                        if '25550' in symbol_part and '25550' in sub_symbol:
                            matched_subscription = sub_info
                            self.logger.info(f"✅ Options match: {symbol_str} -> {full_symbol}")
                            break
            
            if not matched_subscription:
                return
            
            # Get the appropriate callback for this specific symbol
            full_symbol = f"{matched_subscription['exchange']}:{matched_subscription['symbol']}"
            
            if fyers_type == "dp":
                callback = self.subscription_callbacks.get(f"DepthUpdate_{full_symbol}")
                openalgo_data_type = "Depth"
            elif fyers_type == "if":
                # Check if we have depth subscription for this symbol
                depth_callback = self.subscription_callbacks.get(f"DepthUpdate_{full_symbol}")
                if depth_callback:
                    callback = depth_callback
                    openalgo_data_type = "Depth"
                else:
                    callback = self.subscription_callbacks.get(f"SymbolUpdate_{full_symbol}")
                    openalgo_data_type = "Quote"
            else:
                callback = self.subscription_callbacks.get(f"SymbolUpdate_{full_symbol}")
                openalgo_data_type = "Quote"
            
            if not callback:
                return
            
            # Re-map data with correct type if needed
            if openalgo_data_type == "Depth":
                mapped_data = self.data_mapper.map_fyers_data(fyers_data, "Depth")
                if not mapped_data:
                    return
            
            # Override symbol and exchange with subscription details to ensure consistency
            mapped_data["symbol"] = matched_subscription['symbol']
            mapped_data["exchange"] = matched_subscription['exchange']
            mapped_data["update_type"] = update_type
            mapped_data["timestamp"] = int(time.time())
            
            # Deduplication check
            symbol_key = f"{matched_subscription['exchange']}:{matched_subscription['symbol']}"
            current_ltp = mapped_data.get('ltp', 0)
            
            # Check if this is duplicate data
            if symbol_key in self.last_data:
                last_ltp = self.last_data[symbol_key].get('ltp', 0)
                last_time = self.last_data[symbol_key].get('timestamp', 0)
                
                # Skip if same LTP within 100ms (likely duplicate)
                if (current_ltp == last_ltp and 
                    abs(mapped_data["timestamp"] - last_time) < 0.1):
                    return
            
            # Update last data for deduplication
            self.last_data[symbol_key] = {
                'ltp': current_ltp,
                'timestamp': mapped_data["timestamp"]
            }
            
            # Debug logging
            if openalgo_data_type == "Depth":
                depth = mapped_data.get('depth', {})
                buy_levels = depth.get('buy', [])
                sell_levels = depth.get('sell', [])
                bid1 = buy_levels[0]['price'] if buy_levels else 'N/A'
                ask1 = sell_levels[0]['price'] if sell_levels else 'N/A'
                self.logger.info(f"🎉 {full_symbol} depth: Bid={bid1}, Ask={ask1}")
            else:
                self.logger.info(f"🎉 {full_symbol} data: LTP={mapped_data.get('ltp', 0)}")
            
            # Send to symbol-specific callback
            callback(mapped_data)
            
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            self.logger.debug(f"Raw data: {fyers_data}")
    
    def get_connection_status(self) -> Dict[str, Any]:
        """
        Get connection status information
        
        Returns:
            Dict with connection status details
        """
        return {
            "connected": self.connected,
            "authenticated": self.ws_client.is_connected() if self.ws_client else False,
            "active_subscriptions": len(self.active_subscriptions),
            "websocket_url": FyersHSMWebSocket.HSM_URL,
            "protocol": "HSM Binary",
            "user_id": self.userid
        }
    
    def get_subscriptions(self) -> Dict[str, Any]:
        """
        Get current subscriptions
        
        Returns:
            Dict with subscription details
        """
        return {
            "total_subscriptions": len(self.active_subscriptions),
            "subscriptions": dict(self.active_subscriptions),
            "hsm_mappings": dict(self.symbol_to_hsm)
        }
    
    def is_connected(self) -> bool:
        """Check if adapter is connected and ready"""
        return self.connected and (self.ws_client.is_connected() if self.ws_client else False)