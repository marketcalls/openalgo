# 37 - API Key & Playground

## Overview

OpenAlgo provides a secure API key management system and an interactive API Playground for testing REST API and WebSocket endpoints. API keys are hashed using Argon2 with pepper for storage and encrypted using Fernet for retrieval.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        API Key Architecture                                   │
└──────────────────────────────────────────────────────────────────────────────┘

                      Generate API Key Request
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         API Key Generation                                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  api_key = secrets.token_hex(32)  # 64 character hex string         │   │
│  │                                                                      │   │
│  │  Example: a1b2c3d4e5f6...789012345678901234567890abcdef12345678     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Dual Storage Strategy                                │
│                                                                              │
│  ┌──────────────────────────────┐  ┌──────────────────────────────────────┐│
│  │   Hashed (Argon2 + Pepper)   │  │  Encrypted (Fernet)                  ││
│  │   For API authentication     │  │  For TradingView integration         ││
│  │                              │  │                                       ││
│  │  hash = argon2.hash(        │  │  encrypted = fernet.encrypt(         ││
│  │    api_key + pepper         │  │    api_key                            ││
│  │  )                          │  │  )                                    ││
│  │                              │  │                                       ││
│  │  → Stored in api_key_hash   │  │  → Stored in encrypted_api_key        ││
│  └──────────────────────────────┘  └──────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         api_keys Table (SQLite)                              │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  id | user_id | api_key_hash | encrypted_api_key | order_mode      │   │
│  │  ───┼─────────┼──────────────┼───────────────────┼─────────────────│   │
│  │  1  | admin   | $argon2id... | gAAAAA...         | auto            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## API Key Generation

**Location:** `blueprints/apikey.py`

```python
import secrets

def generate_api_key():
    """Generate a secure random API key"""
    # Generate 32 bytes of random data and encode as hex
    return secrets.token_hex(32)
```

### Key Properties

| Property | Value |
|----------|-------|
| Length | 64 characters (hex) |
| Entropy | 256 bits |
| Format | Hexadecimal (0-9, a-f) |
| Generation | `secrets.token_hex(32)` |

## API Key Storage

### Dual Storage for Different Use Cases

```python
# database/auth_db.py
def upsert_api_key(user_id: str, api_key: str) -> int:
    """Store API key with both hash (auth) and encryption (retrieval)"""

    # 1. Hash for authentication verification
    api_key_with_pepper = api_key + API_KEY_PEPPER
    api_key_hash = ph.hash(api_key_with_pepper)

    # 2. Encrypt for TradingView integration (needs plain key)
    encrypted_api_key = encrypt_token(api_key)

    # Store both in database
    api_key_obj = ApiKey(
        user_id=user_id,
        api_key_hash=api_key_hash,
        encrypted_api_key=encrypted_api_key,
        order_mode='auto'
    )
```

### Three-Level Verification

```
API Request with Key
        │
        ▼
┌───────────────────┐
│ 1. Cache Lookup   │───→ Found → Validate hash → Allow/Deny
│    (TTLCache)     │
└─────────┬─────────┘
          │ Not found
          ▼
┌───────────────────┐
│ 2. Database Hash  │───→ Valid → Update cache → Allow
│    Verification   │───→ Invalid → Deny
└─────────┬─────────┘
          │ No hash found
          ▼
┌───────────────────┐
│ 3. Legacy Check   │───→ Plain text match → Allow (deprecated)
│    (Fallback)     │───→ No match → Deny
└───────────────────┘
```

## Order Mode

### Auto vs Semi-Auto Mode

| Mode | Description | Use Case |
|------|-------------|----------|
| `auto` | Orders execute immediately | Personal trading |
| `semi_auto` | Orders require manual approval | Managed accounts |

```python
@api_key_bp.route('/apikey/mode', methods=['POST'])
@check_session_validity
def update_api_key_mode():
    """Update order mode (auto/semi_auto) for a user"""
    user_id = request.json.get('user_id')
    mode = request.json.get('mode')  # 'auto' or 'semi_auto'

    if mode not in ['auto', 'semi_auto']:
        return jsonify({'error': 'Invalid mode'}), 400

    success = update_order_mode(user_id, mode)
    return jsonify({'mode': mode})
```

## API Playground

**Location:** `blueprints/playground.py`

### Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        API Playground Architecture                            │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          Frontend (React/Jinja2)                             │
│                                                                              │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐   │
│  │   Account     │ │   Orders      │ │    Data       │ │  WebSocket    │   │
│  │   Endpoints   │ │   Endpoints   │ │   Endpoints   │ │   Testing     │   │
│  │               │ │               │ │               │ │               │   │
│  │ - Funds       │ │ - PlaceOrder  │ │ - Quotes      │ │ - Subscribe   │   │
│  │ - OrderBook   │ │ - ModifyOrder │ │ - Depth       │ │ - Unsubscribe │   │
│  │ - TradeBook   │ │ - CancelOrder │ │ - History     │ │ - Messages    │   │
│  │ - Positions   │ │ - SmartOrder  │ │ - Intervals   │ │               │   │
│  │ - Holdings    │ │ - SplitOrder  │ │ - Symbol      │ │               │   │
│  └───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Bruno Collection Parser                                  │
│                                                                              │
│  Parses .bru files from collections/ directory                              │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  def parse_bru_file(filepath):                                       │   │
│  │      # Extract: name, method, path, body, params                     │   │
│  │      # Supports: HTTP (GET, POST, PUT, DELETE) and WebSocket        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Endpoint Categories

```python
def categorize_endpoint(path):
    """Categorize an endpoint based on its path"""

    # Account endpoints
    if any(x in path for x in ['/funds', '/orderbook', '/tradebook',
                                '/positionbook', '/holdings']):
        return 'account'

    # Order endpoints
    if any(x in path for x in ['/placeorder', '/modifyorder',
                                '/cancelorder', '/placesmartorder']):
        return 'orders'

    # Data endpoints
    if any(x in path for x in ['/quotes', '/multiquotes', '/depth',
                                '/history', '/intervals']):
        return 'data'

    return 'utilities'
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/playground/` | GET | Render playground UI |
| `/playground/api-key` | GET | Get user's API key |
| `/playground/collections` | GET | Get Postman/Bruno collections |
| `/playground/endpoints` | GET | Get structured endpoint list |

## WebSocket Testing

### WebSocket Endpoint Format in Bruno

```
meta {
  name: Subscribe Symbols
  type: websocket
  seq: 1
}

websocket {
  url: ws://localhost:8765
  description: Subscribe to real-time market data
}

message:json {
  {
    "action": "subscribe",
    "symbols": ["NSE:SBIN-EQ", "NSE:RELIANCE-EQ"]
  }
}
```

### WebSocket Actions

| Action | Description |
|--------|-------------|
| `subscribe` | Subscribe to symbols |
| `unsubscribe` | Unsubscribe from symbols |

## API Usage Examples

### Using API Key in Requests

```python
import requests

API_KEY = "your_64_character_api_key_here"
BASE_URL = "http://localhost:5000/api/v1"

# Using POST with body
response = requests.post(
    f"{BASE_URL}/quotes",
    json={
        "apikey": API_KEY,
        "symbol": "SBIN",
        "exchange": "NSE"
    }
)

# Using header authentication
response = requests.post(
    f"{BASE_URL}/quotes",
    json={
        "apikey": API_KEY,
        "symbol": "SBIN",
        "exchange": "NSE"
    }
)
```

### TradingView Integration

```python
# TradingView webhook URL format
# http://your-domain/api/v1/placeorder

# Webhook payload with API key
{
    "apikey": "your_api_key",
    "symbol": "{{ticker}}",
    "exchange": "NSE",
    "action": "{{strategy.order.action}}",
    "quantity": 1,
    "product": "MIS",
    "pricetype": "MARKET"
}
```

## Security Considerations

### API Key Protection

| Layer | Protection |
|-------|------------|
| Storage | Argon2 hash + Fernet encryption |
| Transit | HTTPS recommended |
| Verification | Pepper + constant-time comparison |
| Caching | TTLCache (expires after broker logout) |

### Playground Security

- Session authentication required
- CSRF protection (exempted for API endpoints)
- API key auto-populated from session
- No API key logging

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/apikey.py` | API key CRUD operations |
| `blueprints/playground.py` | API testing playground |
| `database/auth_db.py` | API key storage/verification |
| `collections/**/*.bru` | Bruno endpoint definitions |
| `templates/playground.html` | Playground UI template |
| `frontend/src/pages/ApiKey.tsx` | React API key page |
