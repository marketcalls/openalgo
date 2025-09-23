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
        self.hsm_to_symbol = {}  # hsm_token -> symbol mapping (reverse lookup)
        
        # Connection state
        self.connected = False
        self.connecting = False
        
        # Threading
        self.lock = threading.Lock()
        
        # Deduplication tracking
        self.last_data = {}  # symbol -> {ltp, timestamp} for deduplication
        
        #self.logger.info(f"Fyers adapter initialized for user: {userid}")
    
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
    
    def disconnect(self, clear_mappings=True):
        """
        Disconnect from Fyers WebSocket
        
        Args:
            clear_mappings: If True, clear all mappings. If False, preserve them for reconnection.
        """
        try:
            self.connected = False
            if self.ws_client:
                self.ws_client.disconnect()
                self.ws_client = None
            
            # Only clear mappings if requested (for complete disconnect)
            if clear_mappings:
                self.active_subscriptions.clear()
                self.symbol_to_hsm.clear()
                self.hsm_to_symbol.clear()  # Clear reverse mapping too
                self.subscription_callbacks.clear()  # Clear callbacks
                self.last_data.clear()  # Clear deduplication cache
                self.logger.info("Disconnected from Fyers WebSocket (cleared all mappings)")
            else:
                # Keep mappings but clear active subscriptions for reconnection
                self.active_subscriptions.clear()
                self.subscription_callbacks.clear()
                self.last_data.clear()
                #self.logger.info(f"Disconnected from Fyers WebSocket (preserved {len(self.hsm_to_symbol)} mappings)")
                
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
                self.logger.debug(f"\n" + "="*60)
                self.logger.debug(f"SUBSCRIBING TO {len(symbols)} SYMBOLS")
                self.logger.debug(f"Data type: {data_type}")
                self.logger.info(f"Symbols to subscribe: {symbols}")
                self.logger.debug("="*60)
                
                # Store callback per symbol to prevent data mixing
                # Use a unique key for each symbol and data type combination
                for symbol_info in symbols:
                    exchange = symbol_info.get("exchange", "NSE")
                    symbol = symbol_info.get("symbol", "")
                    if symbol:
                        full_symbol = f"{exchange}:{symbol}"
                        callback_key = f"{data_type}_{full_symbol}"
                        # Store callback per symbol to ensure proper data routing
                        self.subscription_callbacks[callback_key] = callback
                        self.logger.debug(f"Stored callback for {callback_key}")
                
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
                
                self.logger.debug(f"Converting {len(valid_symbols)} OpenAlgo symbols to HSM format using database lookup...")
                
                # Convert OpenAlgo symbols directly to HSM tokens using database lookup
                hsm_tokens, token_mappings, invalid_symbols = self.token_converter.convert_openalgo_symbols_to_hsm(
                    valid_symbols, data_type
                )
                
                if invalid_symbols:
                    self.logger.warning(f"Invalid symbols: {invalid_symbols}")
                
                if not hsm_tokens:
                    self.logger.error("No valid HSM tokens generated")
                    return False
                
                # CRITICAL FIX: Ensure proper HSM token mapping
                # The tokens are generated in the same order as valid_symbols
                self.logger.debug(f"\nCreating HSM mappings for {len(hsm_tokens)} tokens...")
                self.logger.debug(f"HSM Tokens: {hsm_tokens}")
                self.logger.debug(f"Valid Symbols: {[f'{s['exchange']}:{s['symbol']}' for s in valid_symbols]}")
                
                # Primary mapping strategy: Map by order (most reliable)
                # Since convert_openalgo_symbols_to_hsm processes symbols in order
                for i, hsm_token in enumerate(hsm_tokens):
                    if i < len(valid_symbols):
                        symbol_info = valid_symbols[i]
                        full_symbol = f"{symbol_info['exchange']}:{symbol_info['symbol']}"
                        
                        # Store bidirectional mappings
                        self.symbol_to_hsm[full_symbol] = hsm_token
                        self.hsm_to_symbol[hsm_token] = full_symbol
                        
                        # Get brsymbol for logging
                        brsymbol = token_mappings.get(hsm_token, "N/A")
                        self.logger.debug(f"✅ Mapped #{i+1}: {full_symbol} <-> {hsm_token}")
                        self.logger.debug(f"   Brsymbol: {brsymbol}")
                
                # Verify all active subscriptions have mappings
                unmapped_subs = []
                for full_symbol in self.active_subscriptions:
                    if full_symbol not in self.symbol_to_hsm:
                        unmapped_subs.append(full_symbol)
                        self.logger.warning(f"⚠️ Unmapped subscription: {full_symbol}")
                
                # If there are unmapped subscriptions and unused tokens, map them
                if unmapped_subs:
                    unused_tokens = [t for t in hsm_tokens if t not in self.hsm_to_symbol]
                    if unused_tokens:
                        self.logger.debug(f"Attempting to map {len(unmapped_subs)} unmapped subscriptions...")
                        for i, full_symbol in enumerate(unmapped_subs):
                            if i < len(unused_tokens):
                                hsm_token = unused_tokens[i]
                                self.symbol_to_hsm[full_symbol] = hsm_token
                                self.hsm_to_symbol[hsm_token] = full_symbol
                                self.logger.debug(f"✅ Recovery mapped: {full_symbol} <-> {hsm_token}")
                
                # Final verification
                self.logger.debug(f"\n📊 Mapping Summary:")
                self.logger.debug(f"   Active subscriptions: {len(self.active_subscriptions)}")
                self.logger.debug(f"   HSM tokens generated: {len(hsm_tokens)}")
                self.logger.debug(f"   Mappings created: {len(self.hsm_to_symbol)}")
                self.logger.debug(f"   Forward mappings (symbol->hsm): {self.symbol_to_hsm}")
                self.logger.debug(f"   Reverse mappings (hsm->symbol): {self.hsm_to_symbol}")
                
                self.logger.debug(f"\nSubscribing to {len(hsm_tokens)} HSM tokens...")
                for token in hsm_tokens:
                    self.logger.debug(f"  ➡️ {token}")
                
                # Subscribe to HSM WebSocket with all tokens at once
                self.ws_client.subscribe_symbols(hsm_tokens, token_mappings)
                
                #self.logger.info(f"\n✅ Successfully sent subscription for {len(hsm_tokens)} HSM tokens")
                #self.logger.info(f"Expected data for {len(self.active_subscriptions)} symbols")
                #self.logger.info("="*60 + "\n")
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
            
            # Find matching subscription using HSM token or original symbol
            callback = None
            openalgo_data_type = "Quote"  # Default
            matched_subscription = None
            
            # Try to match using HSM token first (most reliable)
            hsm_token = fyers_data.get('hsm_token')
            if hsm_token:
                # Use bidirectional mapping for fast lookup
                if hsm_token in self.hsm_to_symbol:
                    full_symbol = self.hsm_to_symbol[hsm_token]
                    if full_symbol in self.active_subscriptions:
                        matched_subscription = self.active_subscriptions[full_symbol]
                        self.logger.debug(f"✅ Matched by HSM token: {hsm_token} -> {full_symbol}")
                else:
                    # Log missing mapping for debugging
                    self.logger.debug(f"HSM token {hsm_token} not in mappings")
                    self.logger.debug(f"Current HSM->Symbol mappings: {self.hsm_to_symbol}")
                    # Try fallback matching
                    for full_symbol, sub_info in self.active_subscriptions.items():
                        if full_symbol in self.symbol_to_hsm and self.symbol_to_hsm[full_symbol] == hsm_token:
                            matched_subscription = sub_info
                            # Update reverse mapping for future fast lookup
                            self.hsm_to_symbol[hsm_token] = full_symbol
                            self.logger.debug(f"✅ Matched by HSM token (fallback): {hsm_token} -> {full_symbol}")
                            break
            
            # If no match by HSM token, try matching by original_symbol field
            if not matched_subscription and 'original_symbol' in fyers_data:
                original_symbol = fyers_data.get('original_symbol', '')
                # Try exact match
                if original_symbol in self.active_subscriptions:
                    matched_subscription = self.active_subscriptions[original_symbol]
                    self.logger.debug(f"✅ Matched by original_symbol: {original_symbol}")
                else:
                    # Try to find a match in active subscriptions
                    # Handle cases like NSE:NIFTY25SEPFUT -> NFO:NIFTY30SEP25FUT
                    for full_symbol, sub_info in self.active_subscriptions.items():
                        # Check for NFO futures match
                        if sub_info['exchange'] == 'NFO' and 'NIFTY' in original_symbol and 'FUT' in original_symbol:
                            if 'NIFTY' in sub_info['symbol'] and 'FUT' in sub_info['symbol']:
                                matched_subscription = sub_info
                                self.logger.debug(f"✅ Matched NFO future by pattern: {original_symbol} -> {full_symbol}")
                                # Update the mapping for future use
                                if hsm_token and hsm_token not in self.hsm_to_symbol:
                                    self.hsm_to_symbol[hsm_token] = full_symbol
                                    self.symbol_to_hsm[full_symbol] = hsm_token
                                break
            
            # If no match by token, fall back to symbol matching from fyers data
            if not matched_subscription:
                # Try to match using the symbol from fyers_data
                fyers_symbol = fyers_data.get('symbol', '')
                if fyers_symbol:
                    # Try exact match first
                    for full_symbol, sub_info in self.active_subscriptions.items():
                        # Check various matching patterns
                        if sub_info['symbol'] in fyers_symbol or fyers_symbol.endswith(sub_info['symbol']):
                            matched_subscription = sub_info
                            self.logger.debug(f"✅ Matched by symbol name: {fyers_symbol} -> {full_symbol}")
                            # Update the mapping for future use
                            if hsm_token and hsm_token not in self.hsm_to_symbol:
                                self.hsm_to_symbol[hsm_token] = full_symbol
                                self.symbol_to_hsm[full_symbol] = hsm_token
                            break
                        # Special case for NFO futures
                        elif sub_info['exchange'] == 'NFO' and 'FUT' in sub_info['symbol']:
                            # Extract core symbol from both
                            fyers_core = fyers_symbol.replace('-EQ', '').split('FUT')[0] if 'FUT' in fyers_symbol else ''
                            sub_core = sub_info['symbol'].split('FUT')[0] if 'FUT' in sub_info['symbol'] else ''
                            if fyers_core and sub_core and fyers_core in sub_core:
                                matched_subscription = sub_info
                                self.logger.debug(f"✅ Matched NFO by core symbol: {fyers_symbol} -> {full_symbol}")
                                # Update the mapping for future use
                                if hsm_token and hsm_token not in self.hsm_to_symbol:
                                    self.hsm_to_symbol[hsm_token] = full_symbol
                                    self.symbol_to_hsm[full_symbol] = hsm_token
                                break
                
                # If still no match and only one subscription, use it
                if not matched_subscription and len(self.active_subscriptions) == 1:
                    for full_symbol, sub_info in self.active_subscriptions.items():
                        matched_subscription = sub_info
                        self.logger.debug(f"✅ Single subscription match: {full_symbol}")
                        break
            
            # Final check - if still no match, log detailed debug info and return
            if not matched_subscription:
                self.logger.warning(f"❌ No HSM token match for data. HSM token: {hsm_token}")
                self.logger.debug(f"   HSM to Symbol mappings: {self.hsm_to_symbol}")
                self.logger.debug(f"   Symbol to HSM mappings: {self.symbol_to_hsm}")
                self.logger.debug(f"   Active subscriptions: {list(self.active_subscriptions.keys())}")
                self.logger.debug(f"   Fyers symbol: {fyers_data.get('symbol', 'N/A')}")
                self.logger.debug(f"   Original symbol: {fyers_data.get('original_symbol', 'N/A')}")
                return
            
            """
            # Complex string matching logic removed - we rely on HSM token matching
            # This follows the same pattern as Angel adapter which uses token-based matching
            """
            
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
                self.logger.debug(f"🎉 {full_symbol} depth: Bid={bid1}, Ask={ask1}")
            else:
                self.logger.debug(f"🎉 {full_symbol} data: LTP={mapped_data.get('ltp', 0)}")
            
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