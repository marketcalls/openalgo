# WebSocket Authentication and Symbol Mapping

This document covers the authentication service, symbol mapping, and broker capability registry components for the WebSocket streaming system. For the main architecture overview, see [websocket.md](websocket.md). For implementation details on the broker-agnostic WebSocket adapters, see [websocket_implementation.md](websocket_implementation.md) and [broker_factory.md](broker_factory.md). For the WebSocket adapter and proxy implementation, see [websocket_implementation.md](websocket_implementation.md).

## 1. Authentication Service

The authentication service retrieves tokens and client ID from the database and validates API keys.

### 1.1 Overview

The authentication service is responsible for:
- Validating OpenAlgo API keys
- Retrieving broker-specific authentication tokens from the database
- Getting the client ID (user_id) for broker WebSocket authentication
- Determining the user's active broker
- Securing WebSocket connections

### 1.2 Implementation

```python
# Authentication Service
from openalgo.database.auth_db import get_user_tokens, verify_api_key, get_user_profile

class AuthService:
    def validate_api_key(self, api_key):
        """Validate OpenAlgo API key and retrieve associated tokens"""
        # Verify API key and get user_id
        result = verify_api_key(api_key)
        if not result or not result.get('valid'):
            return None
        
        user_id = result.get('user_id')
        
        # Get tokens for the user
        auth_token = get_user_tokens(user_id)
        if not auth_token:
            return None
            
        return {
            'user_id': user_id,
            'auth_token': auth_token,
        }
        
    def check_subscription_permissions(self, user_id, symbol, exchange, mode, depth_level=None):
        """Check if user has permission for the requested subscription"""
        # This would check user permissions from the database
        # For example, some users might not have access to depth data
        # or might be limited to certain exchanges
        
        # Example implementation
        return {
            'allowed': True,  # Whether subscription is allowed
            'max_depth_level': 50,  # Maximum depth level for this user
            'allowed_modes': [1, 2, 4]  # Allowed subscription modes
        }
```

## 2. Symbol/Token Mapping

The symbol/token mapping component converts between user-friendly symbols and broker-specific tokens using the database.

### 2.1 Overview

This component uses the SymToken model from `openalgo.database.symbol` to:
- Convert symbol+exchange to broker-specific token
- Convert token back to symbol+exchange
- Provide additional symbol information (tick size, lot size, etc.)

### 2.2 Symbol Mapper Implementation

```python
# Symbol/Token Mapper
from sqlalchemy import and_
from openalgo.database.symbol import SymToken, db_session

class SymbolMapper:
    @staticmethod
    def get_token_from_symbol(symbol, exchange):
        """Convert user-friendly symbol to broker-specific token
        
        Args:
            symbol (str): Trading symbol (e.g., 'RELIANCE')
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')
            
        Returns:
            dict: Token data with 'token' and 'brexchange' or None if not found
            
        Notes:
            This method uses the SymToken model from the database schema
            defined in openalgo.database.symbol.
        """
        try:
            sym_token = SymToken.query.filter(
                and_(SymToken.symbol == symbol, SymToken.exchange == exchange)
            ).first()
            
            if not sym_token:
                return None
                
            return {
                'token': sym_token.token,
                'brexchange': sym_token.broker_exchange,
                'tradingsymbol': sym_token.trading_symbol  # Broker-specific trading symbol
            }
        except Exception as e:
            import logging
            logging.getLogger("symbol_mapper").error(f"Error retrieving symbol: {e}")
            return None
            
    @staticmethod
    def get_symbol_from_token(token, broker_exchange):
        """Convert broker-specific token to user-friendly symbol
        
        Args:
            token (str): Broker-specific token
            broker_exchange (str): Broker-specific exchange code
            
        Returns:
            dict: Symbol data with 'symbol' and 'exchange' or None if not found
        """
        try:
            sym_token = SymToken.query.filter(
                and_(SymToken.token == token, SymToken.broker_exchange == broker_exchange)
            ).first()
            
            if not sym_token:
                return None
                
            return {
                'symbol': sym_token.symbol,
                'exchange': sym_token.exchange
            }
        except Exception as e:
            import logging
            logging.getLogger("symbol_mapper").error(f"Error retrieving token: {e}")
            return None
```

## 3. Broker Capability Registry

The Broker Capability Registry keeps track of the features supported by each broker, including exchange support, subscription modes, and market depth levels.

```python
# Broker capability registry
class BrokerCapabilityRegistry:
    # Static registry of broker capabilities
    _capabilities = {
        'angel': {
            'exchanges': ['NSE', 'BSE', 'NFO', 'MCX', 'CDS'],
            'subscription_modes': [1, 2, 4],  # 1: LTP, 2: Quote, 4: Depth
            'depth_support': {
                'NSE': [5, 20, 30],   # NSE supports up to 30 levels (limited)
                'BSE': [5],           # BSE supports only 5 levels
                'NFO': [5, 20],       # NFO supports up to 20 levels
                'MCX': [5],           # MCX supports only 5 levels
                'CDS': [5]            # CDS supports only 5 levels
            }
        },
        'zerodha': {
            'exchanges': ['NSE', 'BSE', 'NFO', 'MCX', 'CDS'],
            'subscription_modes': [1, 2, 4],  # LTP, Quote, Depth
            'depth_support': {
                'NSE': [5, 20],       # NSE supports up to 20 levels in Zerodha
                'BSE': [5],           # BSE supports only 5 levels
                'NFO': [5],           # NFO supports only 5 levels
                'MCX': [5],           # MCX supports only 5 levels
                'CDS': [5]            # CDS supports only 5 levels
            }
        },
        # Add more brokers as they are integrated
    }
    
    @classmethod
    def get_supported_depth_levels(cls, broker, exchange):
        """Get supported depth levels for a broker and exchange
        
        Args:
            broker (str): Broker name (e.g., 'angel', 'zerodha')
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')
            
        Returns:
            list: List of supported depth levels (e.g., [5, 20, 30])
        """
        try:
            return cls._capabilities[broker]['depth_support'].get(exchange, [5])
        except KeyError:
            return [5]  # Default to 5 levels if broker or exchange not found
            
        supported_depths = cls.get_supported_depth_levels(broker, exchange)
        return depth_level in supported_depths
        
    @classmethod
    def get_fallback_depth_level(cls, broker, exchange, requested_depth):
        """Get the best available depth level as a fallback"""
        supported_depths = cls.get_supported_depth_levels(broker, exchange)
        # Find the highest supported depth that's less than or equal to requested depth
        fallbacks = [d for d in supported_depths if d <= requested_depth]
        if fallbacks:
            return max(fallbacks)
        return 5  # Default to basic depth
```

## 4. Configuration and Initialization

### 4.1 Component Initialization

```python
def initialize_services():
    """Initialize authentication and mapping services"""
    auth_service = AuthService()
    symbol_mapper = SymbolMapper()
    return auth_service, symbol_mapper
```

## 5. Error Handling

### 5.1 Authentication Errors

```python
class AuthenticationError(Exception):
    """Exception raised for authentication errors"""
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(self.message)
        
    def to_json(self):
        return {
            "type": "error",
            "code": self.code,
            "message": self.message
        }
```

### 5.2 Symbol Mapping Errors

```python
class SymbolMappingError(Exception):
    """Exception raised for symbol mapping errors"""
    def __init__(self, code, message, symbol=None, exchange=None):
        self.code = code
        self.message = message
        self.symbol = symbol
        self.exchange = exchange
        super().__init__(self.message)
        
    def to_json(self):
        result = {
            "type": "error",
            "code": self.code,
            "message": self.message
        }
        if self.symbol:
            result["symbol"] = self.symbol
        if self.exchange:
            result["exchange"] = self.exchange
        return result
```

This implementation provides a solid foundation for the authentication and symbol mapping components of your WebSocket proxy system.
