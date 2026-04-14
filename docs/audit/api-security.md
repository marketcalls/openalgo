# API Security Assessment

## Overview

This assessment covers the security of OpenAlgo's REST API, focusing on protecting your trading operations from unauthorized access via webhooks.

**Risk Level**: Medium
**Status**: Good

## Deployment Context

OpenAlgo API is accessed in two scenarios:

| Scenario | Access Method | Security |
|----------|---------------|----------|
| Internal use | `https://yourdomain.com` | Full Nginx SSL |
| Webhook (TradingView, etc.) | `https://yourdomain.com/api/v1/*` | Full Nginx SSL |
| Webhook (ngrok temporary) | `https://xyz.ngrok.io/api/v1/*` | Ngrok SSL |

**Recommended**: Use your domain for webhooks. Ngrok should only be temporary.

## API Key Authentication

### Every Webhook Requires API Key

All `/api/v1/` endpoints require your API key:

```json
// TradingView webhook payload
{
    "apikey": "your_api_key_here",
    "symbol": "{{ticker}}",
    "exchange": "NSE",
    "action": "{{strategy.order.action}}",
    "quantity": 1
}
```

**Without valid API key**: Request rejected with 403 Forbidden

### API Key Storage

Your API key is protected with dual storage:

| Storage Type | Purpose | Can Be Reversed? |
|--------------|---------|------------------|
| SHA256 Hash + Pepper | Authentication | No |
| Fernet Encrypted | Broker operations | Yes (with APP_KEY) |

This means:
- Database breach doesn't expose plaintext keys
- Key can still be used for broker API calls when needed

## Webhook Security

### Supported Webhook Sources

| Platform | Webhook URL |
|----------|-------------|
| TradingView | `https://yourdomain.com/api/v1/placeorder` |
| GoCharting | `https://yourdomain.com/api/v1/placeorder` |
| Chartink | `https://yourdomain.com/api/v1/placeorder` |
| Flow | `https://yourdomain.com/api/v1/placeorder` |
| Amibroker | `https://yourdomain.com/api/v1/placeorder` |

### Webhook Flow

```
TradingView Alert Triggers
          │
          ▼
POST https://yourdomain.com/api/v1/placeorder
{
    "apikey": "your_key",
    "symbol": "RELIANCE",
    "action": "BUY",
    "quantity": 1
}
          │
          ▼
┌─────────────────────────────────────┐
│           Nginx                      │
│  • SSL/TLS termination               │
│  • Security headers                  │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│         OpenAlgo API                 │
│  1. Validate API key (hash compare)  │
│  2. Validate input (Marshmallow)     │
│  3. Check rate limits                │
│  4. Place order with broker          │
└─────────────────────────────────────┘
          │
          ▼
Response: {"status": "success", "orderid": "..."}
```

### Why Not Use Ngrok Permanently?

| Aspect | Domain (Recommended) | Ngrok |
|--------|---------------------|-------|
| URL stability | Permanent | Changes on restart |
| SSL certificate | Let's Encrypt (2 years HSTS) | Ngrok-provided |
| Uptime | Your server uptime | Depends on ngrok |
| Rate limits | Your control | Ngrok's limits |
| Security headers | Configured by install.sh | Basic |

## Input Validation

### Marshmallow Schema Validation

**Location**: `restx_api/schemas.py`

Every API request is validated:

```python
class PlaceOrderSchema(Schema):
    apikey = fields.String(required=True)
    symbol = fields.String(required=True, validate=validate.Length(min=1, max=50))
    exchange = fields.String(required=True, validate=validate.OneOf(VALID_EXCHANGES))
    action = fields.String(required=True, validate=validate.OneOf(['BUY', 'SELL']))
    quantity = fields.Integer(required=True, validate=validate.Range(min=1))
    price_type = fields.String(validate=validate.OneOf(['MARKET', 'LIMIT', 'SL', 'SL-M']))
```

**Protections**:
- Required fields enforced
- Type validation (string, integer, etc.)
- Range limits (quantity > 0)
- Enumeration validation (valid exchanges only)

### What Gets Rejected

| Invalid Input | Result |
|---------------|--------|
| Missing API key | 403 Forbidden |
| Invalid exchange code | 400 Bad Request |
| Negative quantity | 400 Bad Request |
| Missing required fields | 400 Bad Request |

## Rate Limiting

### Current Implementation

**Location**: `utils/rate_limiter.py`

| Endpoint Type | Limit | Purpose |
|---------------|-------|---------|
| Order Management | 10/second | Prevent runaway scripts |
| Smart Orders | 2/second | Position-aware limits |
| General APIs | 50/second | Normal usage |
| Webhooks | 100/minute | TradingView/GoCharting/Chartink |

### Why Rate Limiting Matters

Even for single-user:
1. **Prevent self-DoS** - Buggy TradingView alerts won't overwhelm system
2. **Match broker limits** - Brokers have their own rate limits
3. **Resource protection** - Keep system responsive

## Endpoint Security Summary

### Order Management (High Value - Webhook Targets)

| Endpoint | Auth | Validation | Rate Limit |
|----------|------|------------|------------|
| `/placeorder` | API Key | Full schema | 10/s |
| `/placesmartorder` | API Key | Full schema | 2/s |
| `/modifyorder` | API Key | Full schema | 10/s |
| `/cancelorder` | API Key | Basic | 10/s |
| `/closeposition` | API Key | Basic | 10/s |

### Market Data (Read-Only)

| Endpoint | Auth | Rate Limit |
|----------|------|------------|
| `/quotes` | API Key | 50/s |
| `/depth` | API Key | 50/s |
| `/history` | API Key | 50/s |

### Account Info (Read-Only)

| Endpoint | Auth | Rate Limit |
|----------|------|------------|
| `/funds` | API Key | 50/s |
| `/positions` | API Key | 50/s |
| `/holdings` | API Key | 50/s |

## Security Checklist

### Auto-Configured (install.sh)

- [x] HTTPS encryption
- [x] Security headers
- [x] Firewall rules

### Built into OpenAlgo

- [x] API key required for all endpoints
- [x] API keys hashed in database
- [x] Input validation with schemas
- [x] Rate limiting
- [x] Consistent error responses

### Your Responsibility

- [ ] Protect your API key (don't share publicly)
- [ ] Use domain URL for permanent webhooks (not ngrok)
- [ ] Test webhook payloads before going live
- [ ] Monitor order logs for unexpected activity

## TradingView Webhook Setup

### Correct Configuration

```
URL: https://yourdomain.com/api/v1/placeorder

Message:
{
    "apikey": "your_openalgo_api_key",
    "symbol": "{{ticker}}",
    "exchange": "NSE",
    "action": "{{strategy.order.action}}",
    "quantity": 1,
    "product_type": "MIS",
    "price_type": "MARKET"
}
```

### Security Best Practices

1. **Use your domain** - Not ngrok for permanent setup
2. **Test in sandbox first** - Use analyzer mode
3. **Start with small quantities** - Verify webhook works
4. **Monitor order log** - Check for unexpected orders

## Summary

**API Security**: Strong

**Auto-configured (install.sh)**:
- HTTPS with Let's Encrypt
- Security headers
- Firewall

**Built-in (OpenAlgo)**:
- API key authentication
- Input validation
- Rate limiting

**Your tasks**:
- Keep API key private
- Use domain URL for webhooks
- Monitor for unexpected activity

---

**Back to**: [Security Audit Overview](./README.md)
