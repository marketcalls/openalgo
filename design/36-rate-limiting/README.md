# 36 - Rate Limiting Guide

## Overview

OpenAlgo uses Flask-Limiter with a moving-window strategy to protect endpoints from abuse. Different rate limits apply to different endpoint categories based on their sensitivity and resource usage.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Rate Limiting Architecture                            │
└──────────────────────────────────────────────────────────────────────────────┘

                           Incoming Request
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Flask-Limiter                                         │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                      Configuration                                       │ │
│  │  key_func = get_remote_address   (Rate limit by IP)                     │ │
│  │  storage_uri = "memory://"       (In-memory storage)                    │ │
│  │  strategy = "moving-window"      (Sliding window algorithm)             │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    Endpoint Category Detection                               │
│                                                                               │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │   Login     │ │   API       │ │   Order     │ │  Webhook    │           │
│  │ Endpoints   │ │ Endpoints   │ │ Endpoints   │ │ Endpoints   │           │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘           │
│         │               │               │               │                   │
│         ▼               ▼               ▼               ▼                   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ 5/min       │ │ 50/sec      │ │ 10/sec      │ │ 100/min     │           │
│  │ 25/hour     │ │             │ │             │ │             │           │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘           │
└──────────────────────────────────────────────────────────────────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
              Under Limit                  Over Limit
                    │                           │
                    ▼                           ▼
           ┌───────────────┐          ┌───────────────┐
           │   Process     │          │   429 Error   │
           │   Request     │          │ Too Many Reqs │
           └───────────────┘          └───────────────┘
```

## Rate Limit Categories

### Environment Variables

```bash
# Login endpoints (authentication security)
LOGIN_RATE_LIMIT_MIN=5 per minute
LOGIN_RATE_LIMIT_HOUR=25 per hour

# General API endpoints (data queries)
API_RATE_LIMIT=50 per second

# Order endpoints (trading operations)
ORDER_RATE_LIMIT=10 per second

# Smart order endpoints (AI/automated trading)
SMART_ORDER_RATE_LIMIT=2 per second

# Webhook endpoints (external integrations)
WEBHOOK_RATE_LIMIT=100 per minute

# Strategy endpoints
STRATEGY_RATE_LIMIT=200 per minute
```

### Limit Breakdown

| Category | Rate Limit | Endpoints | Purpose |
|----------|------------|-----------|---------|
| **Login** | 5/min, 25/hr | `/auth/login`, `/auth/reset-password` | Prevent brute force |
| **API** | 50/sec | `/api/v1/quotes`, `/api/v1/positions`, etc. | General data access |
| **Order** | 10/sec | `/api/v1/placeorder`, `/api/v1/modifyorder`, `/api/v1/cancelorder` | Trading rate control |
| **Smart Order** | 2/sec | `/api/v1/placesmartorder` | Prevent automated abuse |
| **Webhook** | 100/min | `/chartink/webhook`, `/strategy/webhook` | External integrations |
| **Strategy** | 200/min | Strategy-related operations | Strategy execution |

## Implementation

### Limiter Initialization

**Location:** `limiter.py`

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,  # Rate limit by client IP
    storage_uri="memory://",       # In-memory storage
    strategy="moving-window"       # Sliding window algorithm
)
```

### Applying Rate Limits

**Login Endpoint Example:**

```python
# blueprints/auth.py
from limiter import limiter

LOGIN_RATE_LIMIT_MIN = os.getenv('LOGIN_RATE_LIMIT_MIN', '5 per minute')
LOGIN_RATE_LIMIT_HOUR = os.getenv('LOGIN_RATE_LIMIT_HOUR', '25 per hour')

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def login():
    # Multiple limits can stack (both must pass)
    ...
```

**Order Endpoint Example:**

```python
# restx_api/place_order.py
from limiter import limiter

ORDER_RATE_LIMIT = os.getenv('ORDER_RATE_LIMIT', '10 per second')

@api.route('/', strict_slashes=False)
class PlaceOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """Place an order with the broker"""
        ...
```

**API Endpoint Example:**

```python
# restx_api/quotes.py
from limiter import limiter

API_RATE_LIMIT = os.getenv('API_RATE_LIMIT', '50 per second')

@api.route('/', strict_slashes=False)
class Quotes(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get real-time quotes"""
        ...
```

## Rate Limit Format

```
<number> per <timeunit>
```

### Valid Timeunits

| Timeunit | Alias |
|----------|-------|
| `second` | `s` |
| `minute` | `m` |
| `hour` | `h` |
| `day` | `d` |

### Examples

```bash
# Valid formats
5 per minute
10 per second
100 per hour
1000 per day

# Invalid formats (will fail validation)
5/minute        # Wrong separator
5 per minutes   # Wrong timeunit
five per minute # Must be number
```

## Error Handling

### 429 Response Handler

**Location:** `app.py`

```python
@app.errorhandler(429)
def rate_limit_exceeded(e):
    """Custom handler for 429 Too Many Requests"""
    from flask import redirect, request

    # Log rate limit hit
    logger.warning(f"Rate limit exceeded for {request.remote_addr}: {request.path}")

    # For API requests, return JSON response
    if request.path.startswith('/api/'):
        return {
            'status': 'error',
            'message': 'Rate limit exceeded. Please slow down your requests.',
            'retry_after': 60
        }, 429

    # For web requests, redirect to React rate-limited page
    return redirect('/rate-limited')
```

### Client-Side Handling

```python
# Python client example
import requests
import time

def place_order_with_retry(order_data, max_retries=3):
    for attempt in range(max_retries):
        response = requests.post(
            'http://localhost:5000/api/v1/placeorder',
            json=order_data,
            headers={'Authorization': f'Bearer {api_key}'}
        )

        if response.status_code == 429:
            retry_after = response.json().get('retry_after', 60)
            print(f"Rate limited. Waiting {retry_after}s...")
            time.sleep(retry_after)
            continue

        return response

    raise Exception("Max retries exceeded")
```

## Endpoint Limits Map

### REST API Endpoints

| Endpoint | Rate Limit Variable | Default |
|----------|---------------------|---------|
| `/api/v1/placeorder` | ORDER_RATE_LIMIT | 10/sec |
| `/api/v1/modifyorder` | ORDER_RATE_LIMIT | 10/sec |
| `/api/v1/cancelorder` | ORDER_RATE_LIMIT | 10/sec |
| `/api/v1/cancelallorder` | API_RATE_LIMIT | 50/sec |
| `/api/v1/placesmartorder` | SMART_ORDER_RATE_LIMIT | 2/sec |
| `/api/v1/quotes` | API_RATE_LIMIT | 50/sec |
| `/api/v1/multiquotes` | API_RATE_LIMIT | 50/sec |
| `/api/v1/positions` | API_RATE_LIMIT | 50/sec |
| `/api/v1/orderbook` | API_RATE_LIMIT | 50/sec |
| `/api/v1/tradebook` | API_RATE_LIMIT | 50/sec |
| `/api/v1/holdings` | API_RATE_LIMIT | 50/sec |
| `/api/v1/funds` | API_RATE_LIMIT | 50/sec |
| `/api/v1/history` | API_RATE_LIMIT | 50/sec |
| `/api/v1/depth` | API_RATE_LIMIT | 50/sec |
| `/api/v1/ping` | API_RATE_LIMIT | 50/sec |
| `/api/v1/intervals` | API_RATE_LIMIT | 50/sec |
| `/api/v1/options/multiorder` | ORDER_RATE_LIMIT | 10/sec |

### Authentication Endpoints

| Endpoint | Rate Limit Variable | Default |
|----------|---------------------|---------|
| `/auth/login` | LOGIN_RATE_LIMIT_MIN + HOUR | 5/min, 25/hr |
| `/auth/reset-password` | LOGIN_RATE_LIMIT_HOUR | 25/hr |
| `/<broker>/callback` | LOGIN_RATE_LIMIT_MIN + HOUR | 5/min, 25/hr |

### Webhook Endpoints

| Endpoint | Rate Limit Variable | Default |
|----------|---------------------|---------|
| `/chartink/webhook` | WEBHOOK_RATE_LIMIT | 100/min |
| `/strategy/webhook` | STRATEGY_RATE_LIMIT | 200/min |
| `/flow/trigger/*` | WEBHOOK_RATE_LIMIT | 100/min |

## Moving Window Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                    Moving Window Strategy                        │
└─────────────────────────────────────────────────────────────────┘

Time →  |-------- 1 minute window --------|
        ↓                                  ↓
        [==============================]
                                       ↑
                                   Current time

As time advances, the window slides:
        |-------- 1 minute window --------|
                 ↓                         ↓
             [==============================]

Old requests fall out, new ones enter.
More accurate than fixed-window approach.
```

### Algorithm Benefits

| Aspect | Moving Window | Fixed Window |
|--------|---------------|--------------|
| Accuracy | Higher | Lower |
| Burst protection | Better | Prone to bursts at boundaries |
| Memory | Slightly higher | Lower |
| Implementation | More complex | Simpler |

## Configuration Validation

**Location:** `utils/env_check.py`

```python
import re

rate_limit_vars = [
    'LOGIN_RATE_LIMIT_MIN',
    'LOGIN_RATE_LIMIT_HOUR',
    'API_RATE_LIMIT',
    'ORDER_RATE_LIMIT',
    'SMART_ORDER_RATE_LIMIT',
    'WEBHOOK_RATE_LIMIT',
    'STRATEGY_RATE_LIMIT'
]

rate_limit_pattern = re.compile(r'^\d+\s+per\s+(second|minute|hour|day)$')

for var in rate_limit_vars:
    value = os.getenv(var, '')
    if not rate_limit_pattern.match(value):
        print(f"Error: Invalid {var} format.")
        print("Format should be: 'number per timeunit'")
        print("Example: '5 per minute', '10 per second'")
        sys.exit(1)
```

## Tuning Recommendations

### For High-Frequency Trading

```bash
# Increase order limits for HFT
ORDER_RATE_LIMIT=50 per second
SMART_ORDER_RATE_LIMIT=10 per second
API_RATE_LIMIT=200 per second
```

### For Webhook-Heavy Usage

```bash
# Increase webhook limits for multiple signal sources
WEBHOOK_RATE_LIMIT=500 per minute
STRATEGY_RATE_LIMIT=1000 per minute
```

### For Multi-User Deployments

Consider using Redis for distributed rate limiting:

```python
# limiter.py (with Redis)
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="redis://localhost:6379",
    strategy="moving-window"
)
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `limiter.py` | Flask-Limiter initialization |
| `utils/env_check.py` | Rate limit validation |
| `restx_api/*.py` | API endpoint rate limits |
| `blueprints/auth.py` | Login rate limits |
| `blueprints/chartink.py` | Webhook rate limits |
| `blueprints/strategy.py` | Strategy rate limits |
| `app.py` | 429 error handler |
