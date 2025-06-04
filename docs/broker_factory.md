# Broker Factory Implementation

This document describes the broker factory design that allows OpenAlgo to work with any of the 20+ supported brokers while maintaining a single common interface for the WebSocket proxy system. OpenAlgo allows one user to connect to one broker at a time, and the broker factory design ensures a consistent implementation across all supported brokers.

## 1. Broker Factory

The broker factory is responsible for creating the appropriate WebSocket adapter based on the broker name.

```python
# broker_factory.py
import importlib
import logging
from typing import Dict, Type

from websocket_adapters.base_adapter import BaseBrokerWebSocketAdapter

logger = logging.getLogger(__name__)

# Registry of all supported broker adapters
BROKER_ADAPTERS: Dict[str, Type[BaseBrokerWebSocketAdapter]] = {}

def register_adapter(broker_name: str, adapter_class: Type[BaseBrokerWebSocketAdapter]):
    """Register a broker adapter class for a specific broker"""
    BROKER_ADAPTERS[broker_name.lower()] = adapter_class
    logger.info(f"Registered adapter for broker: {broker_name}")

def create_broker_adapter(broker_name: str) -> BaseBrokerWebSocketAdapter:
    """Create an instance of the appropriate broker adapter"""
    broker_name = broker_name.lower()
    
    # Check if adapter is registered
    if broker_name in BROKER_ADAPTERS:
        logger.info(f"Creating adapter for broker: {broker_name}")
        return BROKER_ADAPTERS[broker_name]()
    
    # Try dynamic import if not registered
    try:
        # Convert broker name to module name (e.g., 'angel' -> 'angel_adapter')
        module_name = f"websocket_adapters.{broker_name}_adapter"
        class_name = f"{broker_name.capitalize()}WebSocketAdapter"
        
        # Import the module
        module = importlib.import_module(module_name)
        
        # Get the adapter class
        adapter_class = getattr(module, class_name)
        
        # Register the adapter for future use
        register_adapter(broker_name, adapter_class)
        
        # Create and return an instance
        return adapter_class()
    
    except (ImportError, AttributeError) as e:
        logger.error(f"Failed to load adapter for broker {broker_name}: {e}")
        raise ValueError(f"Unsupported broker: {broker_name}. No adapter available.")
```

## 2. Adapter Registration

Each broker adapter needs to register itself with the factory.

```python
# Angel broker adapter registration
from websocket_adapters.angel_adapter import AngelWebSocketAdapter
from broker_factory import register_adapter

# Register the Angel adapter
register_adapter("angel", AngelWebSocketAdapter)

# Register other adapters
# register_adapter("zerodha", ZerodhaWebSocketAdapter)
# register_adapter("upstox", UpstoxWebSocketAdapter)
# ...
```

## 3. Broker-Specific Adapter Example: Angel

Here's the Angel WebSocket adapter implementation that handles Angel Broking's specific WebSocket format and price scaling:

> **Important Note**: Angel broker sends prices in paise (1/100th of a rupee), and the adapter automatically normalizes these values by dividing by 100 to get the actual price in rupees. This conversion is handled in the `_normalize_market_data` method.

```python
# websocket_adapters/angel_adapter.py
import threading
import json
import logging
from broker.angel.streaming.smartWebSocketV2 import SmartWebSocketV2

from websocket_adapters.base_adapter import BaseBrokerWebSocketAdapter
from websocket_auth_and_mapping import ExchangeMapper, SymbolMapper, BrokerCapabilityRegistry
from database.symbol import SymToken
from database.auth_db import get_user_tokens

class AngelWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Angel-specific implementation of the WebSocket adapter"""
    
    def initialize(self, broker_name, user_id, auth_data=None):
        """Initialize connection with Angel WebSocket API
        
        Arguments:
            broker_name (str): Name of the broker (always 'angel' in this case)
            user_id (str): Client ID/user ID
            auth_data (dict, optional): If provided, use these credentials instead of fetching from DB
        """
        self.user_id = user_id
        self.broker_name = broker_name
        self.logger = logging.getLogger(f"{broker_name}_websocket")
        
        # Get tokens from database if not provided
        if not auth_data:
            # Fetch authentication tokens from database
            user_tokens = get_user_tokens(user_id, broker_name)
            if not user_tokens:
                self.logger.error(f"No authentication tokens found for user {user_id}")
                raise ValueError(f"No authentication tokens found for user {user_id}")
                
            auth_token = user_tokens.get('auth_token')
            feed_token = user_tokens.get('feed_token')
            api_key = user_tokens.get('api_key')
        else:
            # Use provided tokens
            auth_token = auth_data.get('auth_token')
            feed_token = auth_data.get('feed_token')
            api_key = auth_data.get('api_key')
        
        # Create SmartWebSocketV2 instance
        self.ws_client = SmartWebSocketV2(
            auth_token, 
            api_key, 
            user_id,  # client_code is the user_id
            feed_token,
            max_retry_attempt=5
        )
        
        # Set callbacks
        self.ws_client.on_open = self.on_open
        self.ws_client.on_data = self.on_data
        self.ws_client.on_error = self.on_error
        self.ws_client.on_close = self.on_close
        
    def connect(self):
        """Establish connection to Angel WebSocket"""
        threading.Thread(target=self.ws_client.connect).start()
        
    def disconnect(self):
        """Disconnect from Angel WebSocket"""
        if hasattr(self, 'ws_client'):
            self.ws_client.close_connection()
            
    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        """Subscribe to market data with Angel-specific implementation
        
        Arguments:
            symbol (str): Trading symbol (e.g., 'RELIANCE')
            exchange (str): Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode (int): Subscription mode - 1:LTP, 2:Quote, 4:Depth
            depth_level (int): Market depth level (5, 20, 30)
            
        Returns:
            dict: Response with status and error message if applicable
        """
        # Implementation for Angel subscription
        # First validate the mode
        if mode not in [1, 2, 4]:
            return self._create_error_response("INVALID_MODE", 
                                              f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 4 (Depth)")
                                              
        # If depth mode, check if supported depth level
        if mode == 4 and depth_level not in [5, 20, 30]:
            return self._create_error_response("INVALID_DEPTH", 
                                              f"Invalid depth level {depth_level}. Must be 5, 20, or 30")
        
        # Map symbol to token using SymToken from database
        # Note: This uses the symbol module described in openalgo.database.symbol
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND", 
                                              f"Symbol {symbol} not found for exchange {exchange}")
            
        token = token_info['token']
        brexchange = token_info['brexchange']
        
        # Create token list for Angel API
        token_list = [{
            "exchangeType": ExchangeMapper.get_exchange_type(brexchange),
            "tokens": [token]
        }]
        
        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        # Store subscription for reconnection
        self.subscriptions[correlation_id] = {
            'symbol': symbol,
            'exchange': exchange,
            'token': token,
            'mode': mode,
            'token_list': token_list
        }
        
        # If depth mode, handle depth levels
        if mode == 4 and depth_level > 5:
            depth_result = self._handle_depth_level(exchange, depth_level)
            self.subscriptions[correlation_id].update(depth_result)
            
        # Subscribe if connected
        if self.connected:
            self.ws_client.subscribe(correlation_id, mode, token_list)
        
        return {
            'status': 'success',
            'symbol': symbol,
            'exchange': exchange,
            'mode': mode,
            'message': 'Subscription requested'
        }
    
    def unsubscribe(self, symbol, exchange, mode=2):
        """Unsubscribe from market data"""
        # Implementation for Angel unsubscription
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        if correlation_id in self.subscriptions:
            token_list = self.subscriptions[correlation_id]['token_list']
            
            if self.connected:
                self.ws_client.unsubscribe(correlation_id, mode, token_list)
                
            del self.subscriptions[correlation_id]
            
            return {
                'status': 'success',
                'message': f"Unsubscribed from {symbol}.{exchange} mode {mode}"
            }
        
        return {
            'status': 'error',
            'code': 'NOT_SUBSCRIBED',
            'message': f"Not subscribed to {symbol}.{exchange} mode {mode}"
        }
        
    def _handle_depth_level(self, exchange, depth_level):
        """Handle depth level support for Angel
        
        This method checks if the requested depth level is supported for the given exchange.
        The support levels are defined in the BrokerCapabilityRegistry:
        - 5-level depth is supported for all exchanges
        - 20-level depth is supported only for NSE and NFO
        - 30-level depth has limited support and may not be available
        
        Arguments:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')
            depth_level (int): Requested market depth level
            
        Returns:
            dict: Response with depth information and fallback status
        """
        # Get supported depths for this broker and exchange
        supported_depths = BrokerCapabilityRegistry.get_supported_depth_levels(
            self.broker_name, exchange
        )
        
        self.logger.info(f"Supported depth levels for {exchange}: {supported_depths}")
        
        # Handle NSE & NFO specially since they support higher depth levels in Angel
        if exchange in ['NSE', 'NFO'] and depth_level <= 20:
            # NSE & NFO support 20-level depth
            return {
                'depth_level': depth_level,
                'actual_depth': depth_level,
                'is_fallback': False,
                'message': f"{depth_level}-level depth supported for {exchange}"
            }
        elif exchange in ['NSE'] and depth_level <= 30:
            # Only NSE supports 30-level depth in very few brokers
            # Angel may not support this, so we should confirm and handle accordingly
            return {
                'depth_level': depth_level,
                'actual_depth': depth_level,
                'is_fallback': False,
                'message': f"{depth_level}-level depth supported for {exchange}"
            }
        elif depth_level > 5:
            # For other exchanges or higher levels, fall back to maximum supported
            max_supported = max([d for d in supported_depths if d <= depth_level], default=5)
            return {
                'depth_level': depth_level,
                'actual_depth': max_supported,
                'is_fallback': True,
                'message': f"{depth_level}-level depth not supported for {exchange}, falling back to {max_supported}-level"
            }
            
        # Default case - 5-level depth is supported everywhere
        return {
            'depth_level': depth_level,
            'actual_depth': depth_level,
            'is_fallback': False,
            'message': f"{depth_level}-level depth supported for {exchange}"
        }
        
    def _create_error_response(self, code, message):
        """Create a standardized error response"""
        return {
            'status': 'error',
            'code': code,
            'message': message
        }
```

## 4. Broker-Specific Adapter Example: Zerodha

Here's an example for Zerodha to demonstrate the different implementations:

```python
# websocket_adapters/zerodha_adapter.py
import threading
import json
from kiteconnect import KiteTicker

from websocket_adapters.base_adapter import BaseBrokerWebSocketAdapter

class ZerodhaWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Zerodha-specific implementation of the WebSocket adapter"""
    
    def initialize(self, broker_name, user_id, auth_data):
        """Initialize connection with Zerodha WebSocket API"""
        self.user_id = user_id
        self.broker_name = broker_name
        
        # Extract authentication data
        api_key = auth_data.get('api_key')
        access_token = auth_data.get('auth_token')
        
        # Create KiteTicker instance
        self.ws_client = KiteTicker(api_key, access_token)
        
        # Set callbacks
        self.ws_client.on_connect = self.on_open
        self.ws_client.on_close = self.on_close
        self.ws_client.on_error = self.on_error
        self.ws_client.on_message = self.on_message
        self.ws_client.on_reconnect = self.on_reconnect
        self.ws_client.on_noreconnect = self.on_noreconnect
        
    def connect(self):
        """Establish connection to Zerodha WebSocket"""
        threading.Thread(target=self.ws_client.connect).start()
        
    def disconnect(self):
        """Disconnect from Zerodha WebSocket"""
        if hasattr(self, 'ws_client'):
            self.ws_client.close()
            
    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        """Subscribe to market data with Zerodha-specific implementation"""
        # Implementation for Zerodha subscription
        # Map symbol to instrument token
        token_info = self.symbol_mapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND", 
                                              f"Symbol {symbol} not found for exchange {exchange}")
        
        instrument_token = int(token_info['token'])
        
        # Determine the mode (FULL/QUOTE/LTP)
        kite_mode = "LTP"
        if mode == 2:
            kite_mode = "QUOTE"
        elif mode == 4:
            kite_mode = "FULL"  # Includes market depth
            
        # Store subscription
        correlation_id = f"{symbol}_{exchange}_{mode}"
        self.subscriptions[correlation_id] = {
            'symbol': symbol,
            'exchange': exchange,
            'token': instrument_token,
            'mode': mode,
            'zerodha_mode': kite_mode
        }
        
        # Subscribe if connected
        if self.connected:
            self.ws_client.subscribe([instrument_token])
            self.ws_client.set_mode(self.ws_client.MODE_FULL, [instrument_token])
            
        return {
            'status': 'success',
            'symbol': symbol,
            'exchange': exchange,
            'mode': mode,
            'message': 'Subscription requested'
        }
    
    def unsubscribe(self, symbol, exchange, mode=2):
        """Unsubscribe from market data"""
        # Implementation for Zerodha unsubscription
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        if correlation_id in self.subscriptions:
            instrument_token = self.subscriptions[correlation_id]['token']
            
            if self.connected:
                self.ws_client.unsubscribe([instrument_token])
                
            del self.subscriptions[correlation_id]
            
            return {
                'status': 'success',
                'message': f"Unsubscribed from {symbol}.{exchange} mode {mode}"
            }
        
        return {
            'status': 'error',
            'code': 'NOT_SUBSCRIBED',
            'message': f"Not subscribed to {symbol}.{exchange} mode {mode}"
        }
        
    def on_message(self, ws, data):
        """Handle incoming message from Zerodha WebSocket"""
        try:
            for tick in data:
                # Get the instrument token
                instrument_token = tick.get('instrument_token')
                
                # Find corresponding subscription
                sub_info = None
                for sub_id, sub in self.subscriptions.items():
                    if sub['token'] == instrument_token:
                        sub_info = sub
                        break
                        
                if not sub_info:
                    continue
                    
                # Extract symbol and exchange
                symbol = sub_info['symbol']
                exchange = sub_info['exchange']
                mode = sub_info['mode']
                
                # Format data based on mode
                if mode == 1:  # LTP mode
                    formatted_data = {
                        'symbol': symbol,
                        'exchange': exchange,
                        'ltp': tick.get('last_price', 0),
                        'timestamp': tick.get('last_trade_time', '').isoformat()
                    }
                    
                elif mode == 2:  # QUOTE mode
                    formatted_data = {
                        'symbol': symbol,
                        'exchange': exchange,
                        'ltp': tick.get('last_price', 0),
                        'open': tick.get('ohlc', {}).get('open', 0),
                        'high': tick.get('ohlc', {}).get('high', 0),
                        'low': tick.get('ohlc', {}).get('low', 0),
                        'close': tick.get('ohlc', {}).get('close', 0),
                        'volume': tick.get('volume', 0),
                        'timestamp': tick.get('last_trade_time', '').isoformat()
                    }
                    
                elif mode == 4:  # DEPTH mode
                    # Format market depth
                    depth = {
                        'buy': [],
                        'sell': []
                    }
                    
                    # Process buy depth
                    for i, level in enumerate(tick.get('depth', {}).get('buy', [])):
                        depth['buy'].append({
                            'price': level.get('price', 0),
                            'quantity': level.get('quantity', 0),
                            'orders': level.get('orders', 0)
                        })
                        
                    # Process sell depth
                    for i, level in enumerate(tick.get('depth', {}).get('sell', [])):
                        depth['sell'].append({
                            'price': level.get('price', 0),
                            'quantity': level.get('quantity', 0),
                            'orders': level.get('orders', 0)
                        })
                    
                    formatted_data = {
                        'symbol': symbol,
                        'exchange': exchange,
                        'ltp': tick.get('last_price', 0),
                        'depth': depth,
                        'timestamp': tick.get('last_trade_time', '').isoformat()
                    }
                    
                # Create market data message
                market_data = {
                    'type': 'market_data',
                    'mode': mode,
                    'topic': f"{symbol}.{exchange}",
                    'data': formatted_data
                }
                
                # Publish to ZeroMQ
                topic = f"{symbol}.{exchange}.{mode}"
                self.socket.send_multipart([
                    topic.encode('utf-8'),
                    json.dumps(market_data).encode('utf-8')
                ])
                
        except Exception as e:
            self.logger.error(f"Error processing Zerodha message: {e}")
```

## 5. Using the Factory in the Main Application

```python
# In the main application:
from broker_factory import create_broker_adapter
from database.auth_db import get_user_profile
from websocket_auth_and_mapping import BrokerCapabilityRegistry

def initialize_websocket_system(user_id):
    # Get user's active broker from the database
    user_profile = get_user_profile(user_id)
    if not user_profile:
        raise ValueError(f"User profile not found for user_id: {user_id}")
        
    active_broker = user_profile.get('active_broker')
    if not active_broker:
        raise ValueError(f"No active broker set for user_id: {user_id}")
    
    # Create the appropriate adapter using the factory
    adapter = create_broker_adapter(active_broker)
    
    # Initialize adapter with user_id - it will fetch tokens from DB
    adapter.initialize(
        broker_name=active_broker,
        user_id=user_id
    )
    
    # Connect to the WebSocket
    adapter.connect()
    
    # Log the supported features for this broker
    log_broker_capabilities(active_broker)
    
    return adapter
    
def log_broker_capabilities(broker_name):
    """Log the capabilities of the specified broker"""
    logger = logging.getLogger("websocket_system")
    logger.info(f"Active broker: {broker_name}")
    
    # Log supported exchange capabilities
    exchanges = BrokerCapabilityRegistry.get_supported_exchanges(broker_name)
    logger.info(f"Supported exchanges for {broker_name}: {exchanges}")
    
    # Log supported depth levels for each exchange
    for exchange in exchanges:
        depths = BrokerCapabilityRegistry.get_supported_depth_levels(broker_name, exchange)
        logger.info(f"Supported depth levels for {broker_name} on {exchange}: {depths}")
        
    # Log subscription modes
    modes = BrokerCapabilityRegistry.get_supported_modes(broker_name)
    logger.info(f"Supported subscription modes for {broker_name}: {modes}")
```

## 6. Registering All Supported Brokers

You can define a registry initialization function that registers all supported brokers:

```python
def initialize_broker_registry():
    """Register all supported broker adapters"""
    from websocket_adapters.angel_adapter import AngelWebSocketAdapter
    from websocket_adapters.zerodha_adapter import ZerodhaWebSocketAdapter
    from websocket_adapters.upstox_adapter import UpstoxWebSocketAdapter
    from websocket_adapters.fyers_adapter import FyersWebSocketAdapter
    # Import more adapters here
    
    # Register all adapters
    register_adapter("angel", AngelWebSocketAdapter)
    register_adapter("zerodha", ZerodhaWebSocketAdapter)
    register_adapter("upstox", UpstoxWebSocketAdapter)
    register_adapter("fyers", FyersWebSocketAdapter)
    # Register more adapters here
```

This broker factory design allows OpenAlgo to support all 20+ brokers while maintaining a clean, common interface for the WebSocket proxy system.
