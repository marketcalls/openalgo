# Zero-Config Modifications Required

## Overview

This document outlines the specific modifications required in broker authentication files and the brlogin.py blueprint to implement the zero-config broker setup system.

## Key Files Requiring Modifications

### 1. Broker Authentication Files

#### Angel Broker (`broker/angel/api/auth_api.py`)
**Current Implementation:**
- Line 10: `api_key = os.getenv('BROKER_API_KEY')`
- Hardcoded to read from environment variables

**Required Changes:**
```python
def authenticate_broker(clientcode, broker_pin, totp_code, api_key=None, api_secret=None):
    """
    Authenticate with the broker and return the auth token.
    
    Args:
        clientcode: Client ID for Angel broker
        broker_pin: Password/PIN
        totp_code: TOTP code
        api_key: API key (optional, falls back to env)
        api_secret: API secret (optional, not used by Angel but kept for consistency)
    """
    # Use provided api_key or fall back to environment
    if not api_key:
        api_key = os.getenv('BROKER_API_KEY')
```

#### Dhan Broker (`broker/dhan/api/auth_api.py`)
**Current Implementation:**
- Lines 11-13: Reads `BROKER_API_KEY`, `BROKER_API_SECRET`, `REDIRECT_URL` from env
- Line 20: Returns API secret directly (placeholder implementation)

**Required Changes:**
```python
def authenticate_broker(code, api_key=None, api_secret=None, redirect_url=None):
    """
    Authenticate with the broker and return the auth token.
    
    Args:
        code: Authentication code
        api_key: API key (optional, falls back to env)
        api_secret: API secret (optional, falls back to env)
        redirect_url: Redirect URL (optional, falls back to env)
    """
    # Use provided credentials or fall back to environment
    BROKER_API_KEY = api_key or os.getenv('BROKER_API_KEY')
    BROKER_API_SECRET = api_secret or os.getenv('BROKER_API_SECRET')
    REDIRECT_URL = redirect_url or os.getenv('REDIRECT_URL')
```

### 2. Data API Files

#### Angel Data API (`broker/angel/api/data.py`)
**Current Implementation:**
- Line 17: `api_key = os.getenv('BROKER_API_KEY')`

**Required Changes:**
- Pass API key through function parameters
- Modify `get_api_response` to accept api_key parameter

#### Dhan Data API (`broker/dhan/api/data.py`)
**Current Implementation:**
- Line 19: `client_id = os.getenv('BROKER_API_KEY')`

**Required Changes:**
- Pass client_id through function parameters
- Modify `get_api_response` to accept client_id parameter

### 3. Blueprint Modifications (`blueprints/brlogin.py`)

**Current Implementation:**
- Lines 16-17: Reads broker API key at module level
- Lines 281-298: Dhan authentication flow
- Lines 71-82: Angel authentication flow

**Required Changes:**

#### 1. Dynamic Credential Loading
```python
from utils.broker_credentials import get_broker_credentials, is_xts_broker

@brlogin_bp.route('/<broker>/callback', methods=['POST','GET'])
def broker_callback(broker, para=None):
    # ... existing code ...
    
    # Load credentials from database
    user_id = session.get('user')
    broker_creds = get_broker_credentials(user_id, broker)
    
    if not broker_creds:
        # Fall back to environment variables
        broker_creds = {
            'api_key': get_broker_api_key(),
            'api_secret': get_broker_api_secret(),
            'redirect_url': os.getenv('REDIRECT_URL')
        }
        
        # Add market data credentials for XTS brokers
        if is_xts_broker(broker):
            broker_creds['market_api_key'] = os.getenv('BROKER_API_KEY_MARKET')
            broker_creds['market_api_secret'] = os.getenv('BROKER_API_SECRET_MARKET')
```

#### 2. Update Angel Authentication
```python
elif broker == 'angel':
    if request.method == 'GET':
        return render_template('angel.html')
    
    elif request.method == 'POST':
        clientcode = request.form.get('clientid')
        broker_pin = request.form.get('pin')
        totp_code = request.form.get('totp')
        user_id = clientcode
        
        # Pass credentials to auth function
        auth_token, feed_token, error_message = auth_function(
            clientcode, broker_pin, totp_code,
            api_key=broker_creds.get('api_key'),
            api_secret=broker_creds.get('api_secret')
        )
```

#### 3. Update Dhan Authentication
```python
elif broker=='dhan':
    code = 'dhan'
    logger.debug(f'Dhan broker - The code is {code}')
    
    # Pass credentials to auth function
    auth_token, error_message = auth_function(
        code,
        api_key=broker_creds.get('api_key'),
        api_secret=broker_creds.get('api_secret'),
        redirect_url=broker_creds.get('redirect_url')
    )
```

#### 4. Update XTS Broker Authentication (e.g., IIFL)
```python
elif broker=='iifl':
    code = 'iifl'
    logger.debug(f'IIFL broker - The code is {code}')  
           
    # Pass both trading and market data credentials
    auth_token, feed_token, user_id, error_message = auth_function(
        code,
        api_key=broker_creds.get('api_key'),
        api_secret=broker_creds.get('api_secret'),
        market_api_key=broker_creds.get('market_api_key'),
        market_api_secret=broker_creds.get('market_api_secret')
    )
```

### 4. New Utility Functions Required

#### `utils/broker_credentials.py` (New File)
```python
from database.broker_config_db import get_broker_config
from utils.logging import get_logger

logger = get_logger(__name__)

def get_broker_credentials(user_id, broker_name):
    """
    Get broker credentials from database or environment
    
    Args:
        user_id: User identifier
        broker_name: Broker name (dhan, angel, etc.)
    
    Returns:
        dict: Credentials dictionary or None
    """
    try:
        # Try to get from database first
        config = get_broker_config(user_id, broker_name)
        if config:
            return {
                'api_key': config.get('api_key'),
                'api_secret': config.get('api_secret'),
                'market_api_key': config.get('market_api_key'),
                'market_api_secret': config.get('market_api_secret'),
                'redirect_url': config.get('redirect_url')
            }
    except Exception as e:
        logger.warning(f"Failed to get credentials from database: {e}")
    
    # Fall back to environment variables
    return None

def is_xts_broker(broker_name):
    """
    Check if broker is XTS-based
    
    Args:
        broker_name: Broker identifier
    
    Returns:
        bool: True if XTS broker
    """
    xts_brokers = ['fivepaisaxts', 'compositedge', 'ibulls', 'iifl', 'jainam', 'jainampro', 'wisdom']
    return broker_name in xts_brokers
```

### 5. XTS-Based Brokers Market Data API

**XTS-Based Brokers** (requiring additional market data credentials):
- `fivepaisaxts`
- `compositedge`
- `ibulls`
- `iifl`
- `jainam`
- `jainampro`
- `wisdom`

**Additional Environment Variables for XTS Brokers:**
```
BROKER_API_KEY_MARKET = 'YOUR_BROKER_MARKET_API_KEY'
BROKER_API_SECRET_MARKET = 'YOUR_BROKER_MARKET_API_SECRET'
```

**Required Modifications for XTS Brokers:**

#### Example: IIFL Broker Authentication
```python
def authenticate_broker(code, api_key=None, api_secret=None, 
                       market_api_key=None, market_api_secret=None):
    """
    Authenticate with XTS-based broker
    
    Args:
        code: Authentication code
        api_key: Trading API key
        api_secret: Trading API secret
        market_api_key: Market data API key (XTS brokers only)
        market_api_secret: Market data API secret (XTS brokers only)
    """
    # Trading credentials
    BROKER_API_KEY = api_key or os.getenv('BROKER_API_KEY')
    BROKER_API_SECRET = api_secret or os.getenv('BROKER_API_SECRET')
    
    # Market data credentials for XTS brokers
    BROKER_API_KEY_MARKET = market_api_key or os.getenv('BROKER_API_KEY_MARKET')
    BROKER_API_SECRET_MARKET = market_api_secret or os.getenv('BROKER_API_SECRET_MARKET')
```

### 6. Pattern for All Broker Files

**General Pattern for All Brokers:**

1. **Authentication Functions**: Add optional parameters for credentials
2. **API Functions**: Pass credentials through function calls
3. **Headers Construction**: Use passed credentials instead of env vars
4. **Market Data**: XTS brokers need additional market credentials

**Example Pattern:**
```python
# Before
api_key = os.getenv('BROKER_API_KEY')

# After
def some_api_function(auth_token, api_key=None, market_api_key=None):
    api_key = api_key or os.getenv('BROKER_API_KEY')
    # For XTS brokers
    market_api_key = market_api_key or os.getenv('BROKER_API_KEY_MARKET')
```

### 6. Other Brokers Needing Similar Updates

Based on the pattern, these brokers will need similar modifications:
- `broker/zerodha/api/*`
- `broker/upstox/api/*`
- `broker/kotak/api/*`
- `broker/fyers/api/*`
- `broker/aliceblue/api/*`
- `broker/shoonya/api/*`
- `broker/flattrade/api/*`
- All other brokers in the `broker/` directory

### 7. Testing Requirements

#### Unit Tests for Modified Functions
```python
def test_angel_auth_with_db_credentials():
    """Test Angel authentication with database credentials"""
    # Mock database credentials
    mock_creds = {
        'api_key': 'test_key',
        'api_secret': 'test_secret'
    }
    
    # Test authentication
    auth_token, feed_token, error = authenticate_broker(
        'client123', 'pin123', 'totp123',
        api_key=mock_creds['api_key']
    )
    
    assert auth_token is not None

def test_fallback_to_env():
    """Test fallback to environment variables"""
    # Don't pass credentials
    auth_token, error = authenticate_broker('dhan')
    
    # Should use env variables
    assert auth_token is not None
```

## Implementation Priority

### Phase 1: Core Brokers (Week 1)
1. Dhan - Most straightforward implementation
2. Angel - Requires TOTP handling
3. Zerodha - Popular broker with OAuth flow

### Phase 2: Additional Brokers (Week 2)
4. Upstox
5. Kotak
6. Fyers
7. Others

### Phase 3: Testing and Validation (Week 3)
- Comprehensive testing of all brokers
- Migration script testing
- Performance validation

## Backward Compatibility

All modifications maintain backward compatibility:
1. Optional parameters default to None
2. Fall back to environment variables when database credentials not available
3. No breaking changes to existing API signatures
4. Gradual migration path for users

## Security Considerations

1. **Credential Encryption**: All database credentials are encrypted
2. **Access Control**: Credentials isolated per user
3. **Audit Logging**: All credential access is logged
4. **Rate Limiting**: Credential retrieval is rate-limited
5. **Cache Security**: Cached credentials have short TTL

## Performance Optimization

1. **Caching**: Broker credentials cached for 5 minutes
2. **Connection Pooling**: Reuse database connections
3. **Lazy Loading**: Only load credentials when needed
4. **Batch Operations**: Load all user's brokers in one query

This modification plan ensures a smooth transition to the zero-config system while maintaining full backward compatibility and security.