# WebSocket Authentication and Symbol Mapping

This document covers the authentication service and symbol mapping components of the WebSocket proxy system. For the main architecture overview, see [websocket.md](websocket.md). For the WebSocket adapter and proxy implementation, see [websocket_implementation.md](websocket_implementation.md).

## 1. Authentication Service

The authentication service retrieves tokens and client ID from the database and validates API keys.

### 1.1 Overview

The authentication service is responsible for:
- Validating OpenAlgo API keys
- Retrieving AUTH_TOKEN and FEED_TOKEN from the database
- Getting the client ID (user_id) for Angel WebSocket authentication
- Securing WebSocket connections

### 1.2 Implementation

```python
# Authentication Service
from openalgo.database.auth_db import get_auth_token, get_feed_token, verify_api_key

class AuthService:
    def validate_api_key(self, api_key):
        """Validate OpenAlgo API key and retrieve associated tokens"""
        # Verify API key and get user_id
        result = verify_api_key(api_key)
        if not result or not result.get('valid'):
            return None
        
        user_id = result.get('user_id')
        
        # Get tokens for the user
        auth_token = get_auth_token(user_id)
        feed_token = get_feed_token(user_id)
        
        if not auth_token or not feed_token:
            return None
            
        return {
            'user_id': user_id,
            'auth_token': auth_token,
            'feed_token': feed_token
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
from openalgo.database.symbol import SymToken, db_session
from sqlalchemy import and_

class SymbolMapper:
    def __init__(self):
        # Optional: Implement caching for frequently used symbols
        self.symbol_cache = {}
        self.token_cache = {}
    
    def get_token_from_symbol(self, symbol, exchange):
        """Convert symbol and exchange to broker-specific token"""
        # Check cache first
        cache_key = f"{symbol}:{exchange}"
        if cache_key in self.symbol_cache:
            return self.symbol_cache[cache_key]
            
        # Query the symbol database
        sym_token = SymToken.query.filter(
            and_(SymToken.symbol == symbol, SymToken.exchange == exchange)
        ).first()
        
        if not sym_token:
            return None
            
        result = {
            'token': sym_token.token,
            'brsymbol': sym_token.brsymbol,
            'brexchange': sym_token.brexchange,
            'tick_size': sym_token.tick_size,
            'lotsize': sym_token.lotsize,
            'instrumenttype': sym_token.instrumenttype
        }
        
        # Cache the result
        self.symbol_cache[cache_key] = result
        
        return result
        
    def get_symbol_from_token(self, token, brexchange):
        """Convert broker-specific token back to symbol/exchange"""
        # Check cache first
        cache_key = f"{token}:{brexchange}"
        if cache_key in self.token_cache:
            return self.token_cache[cache_key]
            
        # Query the database
        sym_token = SymToken.query.filter(
            and_(SymToken.token == token, SymToken.brexchange == brexchange)
        ).first()
        
        if not sym_token:
            return None
            
        result = {
            'symbol': sym_token.symbol,
            'exchange': sym_token.exchange,
            'name': sym_token.name,
            'expiry': sym_token.expiry,
            'strike': sym_token.strike,
            'instrumenttype': sym_token.instrumenttype
        }
        
        # Cache the result
        self.token_cache[cache_key] = result
        
        return result
        
    def search_symbols(self, query, exchange=None):
        """Search for symbols using the enhanced_search_symbols function"""
        from openalgo.database.symbol import enhanced_search_symbols
        return enhanced_search_symbols(query, exchange)
```

### 2.3 Exchange Type Mapping

```python
class ExchangeMapper:
    # Angel-specific exchange type mapping
    EXCHANGE_TYPE_MAP = {
        'NSE': 1,
        'BSE': 3,
        'NFO': 2,
        'MCX': 5,
        'CDS': 13,
        'BCD': 4,
        'BFO': 4
    }
    
    # Reverse mapping
    EXCHANGE_NAME_MAP = {
        1: 'NSE',
        2: 'NFO',
        3: 'BSE',
        4: 'BFO',
        5: 'MCX',
        7: 'NCX',
        13: 'CDS'
    }
    
    @classmethod
    def get_exchange_type(cls, exchange):
        """Convert exchange name to Angel-specific exchange type"""
        return cls.EXCHANGE_TYPE_MAP.get(exchange.upper(), 1)  # Default to NSE
        
    @classmethod
    def get_exchange_name(cls, exchange_type):
        """Convert Angel-specific exchange type to exchange name"""
        return cls.EXCHANGE_NAME_MAP.get(exchange_type, 'NSE')  # Default to NSE
```

## 3. Broker Capability Mapping

This component tracks which features and depth levels are supported by each broker.

### 3.1 Capability Registry

```python
class BrokerCapabilityRegistry:
    # Supported depth levels by broker and exchange
    DEPTH_SUPPORT = {
        'angel': {
            'NSE': [5, 20],
            'BSE': [5],
            'NFO': [5, 20],
            'MCX': [5]
        },
        'zerodha': {
            'NSE': [5],
            'BSE': [5],
            'NFO': [5],
            'MCX': [5]
        },
        'fyers': {
            'NSE': [5, 20],
            'BSE': [5],
            'NFO': [5, 20],
            'MCX': [5]
        },
        'upstox': {
            'NSE': [5, 20, 30, 50],  # Upstox supports deep market depth
            'BSE': [5],
            'NFO': [5, 20],
            'MCX': [5]
        }
    }
    
    @classmethod
    def get_supported_depth_levels(cls, broker, exchange):
        """Get supported depth levels for a broker and exchange"""
        broker = broker.lower()
        if broker not in cls.DEPTH_SUPPORT:
            return [5]  # Default to basic depth
            
        exchange_support = cls.DEPTH_SUPPORT[broker]
        return exchange_support.get(exchange.upper(), [5])
        
    @classmethod
    def is_depth_level_supported(cls, broker, exchange, depth_level):
        """Check if a specific depth level is supported"""
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
