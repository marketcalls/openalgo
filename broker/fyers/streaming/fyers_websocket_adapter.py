"""
Fyers WebSocket Adapter for OpenAlgo WebSocket Proxy
Integrates with the OpenAlgo WebSocket proxy system
"""

import json
import threading
import logging
import time
import zmq
from typing import Dict, Any, Optional

# Import base adapter
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

try:
    from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
    from websocket_proxy.mapping import SymbolMapper
except ImportError:
    # Direct import if websocket_proxy module has issues
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '../../../websocket_proxy'))
    sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))
    from base_adapter import BaseBrokerWebSocketAdapter
    from mapping import SymbolMapper
from database.auth_db import get_auth_token

# Import our HSM implementation
from .fyers_adapter import FyersAdapter


class FyersWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Fyers-specific implementation of the WebSocket adapter for OpenAlgo proxy"""
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("fyers_websocket_adapter")
        self.fyers_adapter = None
        self.user_id = None
        self.broker_name = "fyers"
        self.access_token = None
        self.running = False
        self.lock = threading.Lock()
        self.symbol_mapper = SymbolMapper()
        
        # Add deduplication cache to prevent duplicate data publishing
        self.last_data_cache = {}  # Format: {symbol_exchange_mode: {ltp, timestamp}}
        
        self.logger.info("Fyers WebSocket Adapter initialized")
    
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Fyers HSM WebSocket API
        
        Args:
            broker_name: Name of the broker (always 'fyers' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB
        
        Raises:
            ValueError: If required authentication tokens are not found
        """
        try:
            self.user_id = user_id
            self.broker_name = broker_name
            
            #self.logger.info(f"Initializing Fyers adapter for user: {user_id}")
            
            # Get access token from auth_data or database
            if auth_data and 'access_token' in auth_data:
                self.access_token = auth_data['access_token']
                self.logger.debug("Using access token from auth_data")
            else:
                # Get from database
                auth_token = get_auth_token(user_id)
                if not auth_token:
                    raise ValueError(f"No auth token found for user {user_id}")
                
                # For Fyers, the auth token IS the access token
                self.access_token = auth_token
                self.logger.debug("Retrieved access token from database")
            
            if not self.access_token:
                raise ValueError("Fyers access token is required")
            
            # Initialize Fyers HSM adapter
            self.fyers_adapter = FyersAdapter(self.access_token, user_id)
            
            self.logger.info("Fyers adapter initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Fyers adapter: {e}")
            raise
    
    def connect(self):
        """Establish connection to the Fyers HSM WebSocket"""
        try:
            # Only reinitialize adapter if it doesn't exist
            if not self.fyers_adapter:
                self.logger.debug("Initializing new Fyers adapter...")
                self.fyers_adapter = FyersAdapter(self.access_token, self.user_id)
            else:
                self.logger.debug("Using existing Fyers adapter instance")
            
            # Reinitialize ZMQ if needed
            if not self.socket:
                self.logger.debug("Reinitializing ZeroMQ socket...")
                self.setup_zmq()
            
            #self.logger.info("Connecting to Fyers HSM WebSocket...")
            
            # Connect to Fyers
            success = self.fyers_adapter.connect()
            if not success:
                raise ConnectionError("Failed to connect to Fyers WebSocket")
            
            self.connected = True
            self.running = True
            
            #self.logger.info("Successfully connected to Fyers HSM WebSocket")
            return {"status": "success", "message": "Connected to Fyers WebSocket"}
            
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            self.connected = False
            return {"status": "error", "message": str(e)}
    
    def disconnect(self):
        """Disconnect from the Fyers WebSocket and cleanup all resources"""
        try:
            #self.logger.info("Starting Fyers WebSocket disconnect and cleanup...")
            
            # Set flags to stop operations
            self.running = False
            self.connected = False
            
            # Clear all active subscriptions and callbacks
            with self.lock:
                subscription_count = len(self.subscriptions)
                self.subscriptions.clear()
                
                # Clear active callbacks
                if hasattr(self, 'active_callbacks'):
                    callback_count = len(self.active_callbacks)
                    self.active_callbacks.clear()
                    if callback_count > 0:
                        self.logger.debug(f"Cleared {callback_count} active callbacks")
                
                # Clear deduplication cache
                if hasattr(self, 'last_data_cache'):
                    cache_count = len(self.last_data_cache)
                    self.last_data_cache.clear()
                    if cache_count > 0:
                        self.logger.debug(f"Cleared {cache_count} cached data entries")
                
                if subscription_count > 0:
                    self.logger.debug(f"Cleared {subscription_count} active subscriptions")
            
            # Disconnect from Fyers HSM WebSocket
            if self.fyers_adapter:
                try:
                    # Full disconnect with clearing all mappings
                    self.fyers_adapter.disconnect(clear_mappings=True)
                    self.logger.info("Fyers HSM adapter disconnected")
                except Exception as e:
                    self.logger.error(f"Error disconnecting Fyers adapter: {e}")
                finally:
                    self.fyers_adapter = None
            
            # Cleanup ZeroMQ resources (socket and port)
            try:
                self.cleanup_zmq()
                self.logger.info("ZeroMQ resources cleaned up successfully")
            except Exception as e:
                self.logger.error(f"Error cleaning up ZeroMQ: {e}")
            
            self.logger.info("Fyers WebSocket disconnect and cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during disconnect: {e}")
        finally:
            # Ensure flags are set even if cleanup fails
            self.running = False
            self.connected = False
    
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5):
        """
        Subscribe to market data with the specified mode and depth level
        
        Args:
            symbol: Symbol to subscribe to
            exchange: Exchange name
            mode: Subscription mode (1=LTP, 2=Quote, 3=Depth)
            depth_level: Depth level for order book (not used in Fyers)
        """
        try:
            # Auto-reconnect if disconnected
            if not self.connected or not self.fyers_adapter:
                self.logger.info("Not connected to Fyers - attempting to reconnect...")
                connect_result = self.connect()
                if not connect_result or connect_result.get("status") != "success":
                    self.logger.error("Failed to reconnect to Fyers WebSocket")
                    return {
                        "status": "error",
                        "message": "Failed to reconnect to Fyers WebSocket"
                    }
                self.logger.info("Successfully reconnected to Fyers WebSocket")
            
            # Ensure adapter is properly connected
            if self.fyers_adapter and not self.fyers_adapter.connected:
                self.logger.info("Fyers adapter exists but not connected, reconnecting...")
                if not self.fyers_adapter.connect():
                    self.logger.error("Failed to reconnect Fyers adapter")
                    return {
                        "status": "error",
                        "message": "Failed to reconnect Fyers adapter"
                    }
            
            with self.lock:
                # Convert to OpenAlgo format
                symbol_info = [{"exchange": exchange, "symbol": symbol}]
                
                # Create a unique callback for this specific subscription
                # Capture the original subscription details
                original_symbol = symbol
                original_exchange = exchange
                original_mode = mode
                subscription_key = f"{exchange}:{symbol}:{mode}"
                
                # Store callback reference for cleanup
                if not hasattr(self, 'active_callbacks'):
                    self.active_callbacks = {}
                
                def data_callback(data):
                    """Handle market data and send via ZeroMQ"""
                    try:
                        # Check if this subscription is still active
                        if subscription_key not in self.subscriptions:
                            # Subscription has been removed, don't process data
                            # Also remove from active callbacks
                            if subscription_key in self.active_callbacks:
                                del self.active_callbacks[subscription_key]
                            return
                            
                        # Data is already properly mapped by FyersAdapter and FyersDataMapper
                        # Just ensure we have the subscription info for proper topic generation
                        if data:
                            # Override with the original subscription details to ensure correct topic
                            # This fixes the mismatch between NFO subscription and NSE data
                            data['symbol'] = original_symbol
                            data['exchange'] = original_exchange
                            data['subscription_mode'] = original_mode
                            
                            # Send via ZeroMQ with the original subscription details
                            self._send_data(data)
                    except Exception as e:
                        self.logger.error(f"Error processing data callback: {e}")
                
                # Store the callback
                self.active_callbacks[subscription_key] = data_callback
                
                # Subscribe based on mode
                if mode == 1:  # LTP
                    success = self.fyers_adapter.subscribe_ltp(symbol_info, data_callback)
                elif mode == 2:  # Quote
                    success = self.fyers_adapter.subscribe_quote(symbol_info, data_callback)
                elif mode == 3:  # Depth
                    success = self.fyers_adapter.subscribe_depth(symbol_info, data_callback)
                else:
                    self.logger.error(f"Unsupported subscription mode: {mode}")
                    return {
                        "status": "error",
                        "message": f"Unsupported subscription mode: {mode}"
                    }
                
                if success:
                    # Track subscription
                    key = f"{exchange}:{symbol}:{mode}"
                    self.subscriptions[key] = {
                        "symbol": symbol,
                        "exchange": exchange,
                        "mode": mode,
                        "subscribed_at": time.time()
                    }
                    
                    self.logger.debug(f"Subscribed to {exchange}:{symbol} (mode: {mode})")
                    return {
                        "status": "success",
                        "message": f"Subscribed to {exchange}:{symbol}",
                        "mode": mode
                    }
                else:
                    self.logger.error(f"Failed to subscribe to {exchange}:{symbol}")
                    return {
                        "status": "error", 
                        "message": f"Failed to subscribe to {exchange}:{symbol}"
                    }
                    
        except Exception as e:
            self.logger.error(f"Subscription error: {e}")
            return {
                "status": "error",
                "message": f"Subscription failed: {str(e)}"
            }
    
    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2):
        """
        Unsubscribe from market data
        
        Args:
            symbol: Symbol to unsubscribe from
            exchange: Exchange name
            mode: Subscription mode
            
        Returns:
            dict: Response with status
        """
        try:
            with self.lock:
                key = f"{exchange}:{symbol}:{mode}"
                
                if key in self.subscriptions:
                    # Remove from our subscription tracking
                    subscription_info = self.subscriptions.pop(key)
                    
                    self.logger.info(f"Unsubscribe for {exchange}:{symbol} (mode: {mode})")
                    #self.logger.warning("Note: Fyers HSM doesn't support selective unsubscription - data will stop publishing but HSM will continue receiving in background")
                    
                    # Remove the callback reference if it exists
                    if hasattr(self, 'active_callbacks') and key in self.active_callbacks:
                        del self.active_callbacks[key]
                    
                    # If no more subscriptions, disconnect completely to stop background data
                    # This is needed for Fyers HSM which doesn't support selective unsubscription
                    if len(self.subscriptions) == 0:
                        self.logger.debug("No active subscriptions remaining - disconnecting from Fyers to stop all background data")
                        
                        # Disconnect from Fyers WebSocket but keep adapter instance and mappings
                        try:
                            if self.fyers_adapter:
                                # Disconnect without clearing mappings for potential reuse
                                self.fyers_adapter.disconnect(clear_mappings=False)
                                # Don't set to None - keep the adapter instance for reuse
                                # self.fyers_adapter = None
                            self.connected = False
                            
                            # Clear all callbacks
                            if hasattr(self, 'active_callbacks'):
                                self.active_callbacks.clear()
                            
                            self.logger.info("Disconnected from Fyers HSM WebSocket - all background data stopped")
                            
                            return {
                                "status": "success",
                                "message": f"Unsubscribed from {exchange}:{symbol} and disconnected (no active subscriptions)",
                                "disconnected": True,
                                "active_subscriptions": 0
                            }
                        except Exception as e:
                            self.logger.error(f"Error disconnecting from Fyers: {e}")
                    
                    return {
                        "status": "success",
                        "message": f"Unsubscribed from {exchange}:{symbol}",
                        "active_subscriptions": len(self.subscriptions)
                    }
                else:
                    self.logger.warning(f"No active subscription found for {exchange}:{symbol}:{mode}")
                    return {
                        "status": "warning",
                        "message": f"No active subscription found for {exchange}:{symbol}:{mode}"
                    }
                    
        except Exception as e:
            self.logger.error(f"Unsubscription error: {e}")
            return {
                "status": "error",
                "message": f"Unsubscription failed: {str(e)}"
            }
    
    def _convert_price_to_rupees(self, price_value: float, fyers_data: Dict[str, Any]) -> float:
        """
        Convert Fyers price based on instrument type:
        - Indices: Keep raw values (no division)
        - Stocks/Futures/Options: Divide by 100 (paise to rupees)
        
        Args:
            price_value: Raw price value from Fyers
            fyers_data: Fyers data containing symbol and exchange info
            
        Returns:
            Price converted appropriately
        """
        try:
            if price_value == 0:
                return 0.0
            
            # Check if this is an index based on symbol or type
            symbol = fyers_data.get("symbol", "")
            original_symbol = fyers_data.get("original_symbol", "")
            fyers_type = fyers_data.get("type", "")
            
            # Identify indices - they should keep raw values
            is_index = (
                "-INDEX" in symbol or 
                "-INDEX" in original_symbol or
                "INDEX" in symbol.upper() or
                fyers_type == "if"  # Index feed type in HSM
            )
            
            if is_index:
                # Indices: Keep raw values, just round to 2 decimal places
                return round(price_value, 2)
            else:
                # Stocks, Futures, Options: Convert paise to rupees (divide by 100)
                # For NSE, NFO, MCX, BSE, BFO instruments
                return round(price_value / 100.0, 2)
            
        except Exception as e:
            self.logger.error(f"Error converting price {price_value}: {e}")
            # Fallback: assume stock/future, divide by 100
            return round(price_value / 100.0, 2)

    def _map_fyers_to_openalgo(self, fyers_data: Dict[str, Any], mode: int) -> Optional[Dict[str, Any]]:
        """
        Map Fyers data to OpenAlgo WebSocket format
        
        Args:
            fyers_data: Data from Fyers
            mode: Subscription mode
            
        Returns:
            Mapped data in OpenAlgo format
        """
        try:
            if not fyers_data:
                return None
            
            # Extract symbol and exchange
            symbol = fyers_data.get("symbol", "")
            if ":" in symbol:
                exchange, symbol_name = symbol.split(":", 1)
            else:
                exchange = fyers_data.get("exchange", "NSE")
                symbol_name = symbol
            
            # Base OpenAlgo format
            openalgo_data = {
                "symbol": symbol_name,
                "exchange": exchange,
                "token": fyers_data.get("token", ""),
                "timestamp": fyers_data.get("timestamp", int(time.time()))
            }
            
            # Add data based on mode
            if mode == 1:  # LTP
                raw_ltp = fyers_data.get("ltp", 0)
                converted_ltp = self._convert_price_to_rupees(raw_ltp, fyers_data)
                openalgo_data.update({
                    "ltp": converted_ltp,
                    "data_type": "LTP"
                })
            elif mode == 2:  # Quote  
                # Convert all price fields from paise to rupees using correct field names
                raw_ltp = fyers_data.get("ltp", 0)
                raw_open = fyers_data.get("open_price", 0)
                raw_high = fyers_data.get("high_price", 0)
                raw_low = fyers_data.get("low_price", 0)
                raw_close = fyers_data.get("prev_close_price", 0)
                raw_bid = fyers_data.get("bid_price", 0)
                raw_ask = fyers_data.get("ask_price", 0)
                
                # Data is already properly mapped by FyersDataMapper with OHLC fields
                # Debug log to see if we have the proper data now
                ltp = fyers_data.get("ltp", 0)
                open_price = fyers_data.get("open", 0)  
                high_price = fyers_data.get("high", 0)
                low_price = fyers_data.get("low", 0) 
                close_price = fyers_data.get("close", 0)
                
                self.logger.debug(f"Mapped Quote data: ltp={ltp}, open={open_price}, high={high_price}, low={low_price}, close={close_price}")
                
                # Return the already mapped data (no additional processing needed)
                return fyers_data
            elif mode == 3:  # Depth
                openalgo_data.update({
                    "ltp": fyers_data.get("ltp", 0),
                    "depth": fyers_data.get("depth", {"buy": [], "sell": []}),
                    "data_type": "Depth"
                })
            
            return openalgo_data
            
        except Exception as e:
            self.logger.error(f"Error mapping Fyers data: {e}")
            return None
    
    def _send_data(self, data: Dict[str, Any]):
        """
        Send data via ZeroMQ socket using proper topic-data format
        
        Args:
            data: Data to send
        """
        try:
            if self.socket:
                # Create topic string for proper ZeroMQ multipart message
                symbol = data.get("symbol", "")
                exchange = data.get("exchange", "")
                
                # Ensure we have valid symbol and exchange
                if not symbol or not exchange:
                    self.logger.warning(f"Invalid symbol or exchange: symbol='{symbol}', exchange='{exchange}'")
                    return
                
                # Map subscription mode to mode string (same as Angel adapter)
                subscription_mode = data.get('subscription_mode', 1)
                mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}.get(subscription_mode, 'QUOTE')
                
                # Format: EXCHANGE_SYMBOL_MODE (following Angel adapter pattern)
                topic = f"{exchange}_{symbol}_{mode_str}"
                
                # Use the base adapter's publish_market_data method like Angel does
                self.publish_market_data(topic, data)
                
                # Debug log for all data types
                if subscription_mode == 3:  # Depth data
                    depth = data.get('depth', {})
                    buy_levels = depth.get('buy', [])
                    sell_levels = depth.get('sell', [])
                    bid1 = buy_levels[0]['price'] if buy_levels else 'N/A'
                    ask1 = sell_levels[0]['price'] if sell_levels else 'N/A'
                    self.logger.debug(f"Published {exchange} depth: {symbol} - Bid={bid1}, Ask={ask1} (topic: {topic})")
                else:  # LTP or Quote data
                    ltp = data.get('ltp', 'N/A')
                    self.logger.debug(f"Published {exchange} data: {symbol} = {ltp} (topic: {topic})")
                
        except Exception as e:
            self.logger.error(f"Error sending data via ZeroMQ: {e}")
            self.logger.error(f"Data causing error: {data}")
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Get connection status"""
        status = {
            "connected": self.connected,
            "broker": self.broker_name,
            "user_id": self.user_id,
            "subscriptions": len(self.subscriptions),
            "zmq_port": getattr(self, 'zmq_port', None)
        }
        
        if self.fyers_adapter:
            fyers_status = self.fyers_adapter.get_connection_status()
            status.update({
                "fyers_connected": fyers_status.get("connected", False),
                "fyers_authenticated": fyers_status.get("authenticated", False),
                "protocol": fyers_status.get("protocol", "HSM Binary")
            })
        
        return status
    
    def get_subscriptions(self) -> Dict[str, Any]:
        """Get current subscriptions"""
        return {
            "total": len(self.subscriptions),
            "subscriptions": dict(self.subscriptions)
        }
    
    def __del__(self):
        """
        Destructor to ensure proper cleanup of resources when adapter is destroyed
        """
        try:
            self.logger.info("FyersWebSocketAdapter destructor called - cleaning up resources")
            self.disconnect()
        except Exception as e:
            # Can't rely on self.logger being available during destruction
            import logging
            logger = logging.getLogger("fyers_websocket_adapter")
            logger.error(f"Error in FyersWebSocketAdapter destructor: {e}")
            
    def cleanup_all_resources(self):
        """
        Comprehensive cleanup method for manual resource cleanup
        """
        try:
            self.logger.debug("Starting comprehensive resource cleanup...")
            
            # Stop all operations
            self.running = False
            self.connected = False
            
            # Clear subscriptions
            with self.lock:
                self.subscriptions.clear()
            
            # Cleanup Fyers adapter
            if self.fyers_adapter:
                try:
                    self.fyers_adapter.disconnect(clear_mappings=True)
                except Exception as e:
                    self.logger.error(f"Error cleaning up Fyers adapter: {e}")
                finally:
                    self.fyers_adapter = None
            
            # Cleanup ZMQ
            try:
                self.cleanup_zmq()
            except Exception as e:
                self.logger.error(f"Error in ZMQ cleanup: {e}")
            
            # Reset all variables
            self.access_token = None
            self.user_id = None
            
            self.logger.info("Comprehensive resource cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error in comprehensive cleanup: {e}")
            
    def force_cleanup(self):
        """
        Force cleanup of all resources (for emergency situations)
        """
        try:
            # Force close everything without error checking
            self.running = False
            self.connected = False
            
            if hasattr(self, 'subscriptions'):
                self.subscriptions.clear()
                
            if hasattr(self, 'fyers_adapter') and self.fyers_adapter:
                try:
                    self.fyers_adapter.disconnect(clear_mappings=True)
                except:
                    pass
                self.fyers_adapter = None
            
            # Force cleanup ZMQ
            try:
                if hasattr(self, 'socket') and self.socket:
                    self.socket.close(linger=0)
                    
                if hasattr(self, 'zmq_port'):
                    with self._port_lock:
                        self._bound_ports.discard(self.zmq_port)
            except:
                pass
                
            #print("Force cleanup completed")
            
        except:
            pass  # Suppress all errors in force cleanup