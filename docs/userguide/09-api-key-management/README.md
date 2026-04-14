# 09 - API Key Management

## Introduction

Your API key is the authentication token that allows external systems (TradingView, Amibroker, Python scripts) to place orders through OpenAlgo. Managing it properly is crucial for both functionality and security.

## What is an API Key?

Think of your API key as a special password:

```
API Key: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
         └─────────────────────────────────┘
              32 character unique identifier
```

**It allows**:
- External platforms to send orders
- Your scripts to communicate with OpenAlgo
- Webhooks to trigger trades

**It does NOT**:
- Give access to OpenAlgo web interface (that's your password)
- Give direct access to your broker (that's broker credentials)

## Generating Your API Key

### Step 1: Navigate to API Key Page

1. Login to OpenAlgo
2. Go to **API Key** in sidebar
3. Or visit: `http://127.0.0.1:5000/apikey`

### Step 2: Generate New Key

1. Click **Generate New Key**
2. Your key appears:
   ```
   ┌────────────────────────────────────────────────────────────┐
   │  a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6            [Copy] [👁️]   │
   └────────────────────────────────────────────────────────────┘
   ```
3. Click **Copy** to copy to clipboard

### Step 3: Save Your Key

**Important**: The full key is only shown once!

Save it somewhere secure:
- Password manager (recommended)
- Secure notes app
- Encrypted document

## API Key Settings

### Order Mode

```
┌─────────────────────────────────────────────────────────────────┐
│  Order Mode                                                      │
│                                                                  │
│  ◉ Auto Mode                                                    │
│    Orders execute immediately with your broker                  │
│                                                                  │
│  ○ Semi-Auto Mode                                               │
│    Orders wait in Action Center for your approval               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

| Mode | Behavior | Best For |
|------|----------|----------|
| **Auto** | Instant execution | Personal trading, fast strategies |
| **Semi-Auto** | Requires approval | Managed accounts, review trades |

### Changing Order Mode

1. Go to API Key page
2. Select desired mode
3. Click **Save**

Orders in-flight continue with their original mode.

## Using Your API Key

### In Webhooks (TradingView, ChartInk)

Include your API key in the JSON body:

```json
{
  "apikey": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "strategy": "MyStrategy",
  "symbol": "SBIN",
  "action": "BUY",
  "quantity": "100"
}
```

### In HTTP Headers

For API calls, include in X-API-KEY header:

```
X-API-KEY: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

Or include in request body (recommended):

```json
{
    "apikey": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
    "symbol": "SBIN",
    "exchange": "NSE"
}
```

**Note:** Bearer token authentication is NOT supported.

### In Python Scripts

```python
from openalgo import api

# Initialize with your API key
client = api(
    api_key="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
    host="http://127.0.0.1:5000"
)

# Place an order
result = client.place_order(
    symbol="SBIN",
    exchange="NSE",
    action="BUY",
    quantity=100,
    price_type="MARKET",
    product="MIS"
)
```

### In Node.js Scripts

```javascript
const OpenAlgo = require('openalgo-node');

const client = new OpenAlgo({
  apiKey: 'a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6',
  host: 'http://127.0.0.1:5000'
});

// Place an order
const result = await client.placeOrder({
  symbol: 'SBIN',
  exchange: 'NSE',
  action: 'BUY',
  quantity: 100,
  priceType: 'MARKET',
  product: 'MIS'
});
```

## Regenerating Your API Key

If your key is compromised or you want a fresh one:

### Step 1: Revoke Old Key

1. Go to API Key page
2. Click **Regenerate Key**
3. Confirm the action

### Step 2: Update All Integrations

After regenerating, update your key in:
- [ ] TradingView webhooks
- [ ] Amibroker settings
- [ ] Python scripts
- [ ] Any other integrations

**Warning**: Old key stops working immediately!

## Security Best Practices

### DO ✅

| Practice | Why |
|----------|-----|
| Store securely | Prevent unauthorized access |
| Use environment variables | Don't hardcode in scripts |
| Regenerate periodically | Limit exposure time |
| Use HTTPS | Encrypt in transit |
| Monitor traffic logs | Detect misuse |

### DON'T ❌

| Practice | Risk |
|----------|------|
| Share publicly | Anyone can trade your account |
| Commit to Git | Exposed in repository |
| Send via email | Insecure transmission |
| Use on untrusted systems | Key theft |
| Ignore suspicious activity | Ongoing misuse |

### Environment Variables (Recommended)

Instead of hardcoding:

**Bad**:
```python
api_key = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
```

**Good**:
```python
import os
api_key = os.environ.get('OPENALGO_API_KEY')
```

Then set the environment variable:
```bash
export OPENALGO_API_KEY="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
```

## API Key Permissions

Your API key allows these operations:

### Full Access
- Place orders
- Modify orders
- Cancel orders
- View positions
- View holdings
- View order book
- View trade book
- Get funds
- Get quotes
- Get market depth

### Not Accessible via API Key
- Change OpenAlgo password
- Change broker credentials
- Access admin settings
- View other users' data

## Troubleshooting

### Issue: "Invalid API key"

**Causes**:
- Typo in API key
- Key was regenerated
- Extra spaces

**Solution**:
- Copy key directly from OpenAlgo
- Ensure no spaces before/after
- Check if key was regenerated

### Issue: "API key not authorized"

**Causes**:
- Wrong key for this instance
- Key revoked

**Solution**:
- Verify key matches your OpenAlgo instance
- Generate new key if needed

### Issue: "Rate limit exceeded"

**Causes**:
- Too many requests per second
- Possible script loop

**Solution**:
- Add delays between requests
- Check for infinite loops
- Review rate limits

## Rate Limits

OpenAlgo applies rate limits to prevent abuse:

| Endpoint Type | Default Limit |
|---------------|---------------|
| Order placement | 10/second |
| Data queries | 30/second |
| Webhook | 20/minute |

Exceeding limits returns HTTP 429 error.

## Monitoring API Key Usage

### Traffic Logs

View all API activity at **Traffic Logs**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Recent API Calls                                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  Time     │ Endpoint      │ Status │ IP Address   │ Response Time          │
│───────────│───────────────│────────│──────────────│────────────────────────│
│  10:30:15 │ /placeorder   │ 200    │ 192.168.1.10 │ 125ms                  │
│  10:30:16 │ /positions    │ 200    │ 192.168.1.10 │ 85ms                   │
│  10:30:45 │ /placeorder   │ 400    │ 103.25.x.x   │ 15ms                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### What to Watch For

| Indicator | Possible Issue |
|-----------|---------------|
| Unknown IP addresses | Unauthorized access |
| High error rate | Misconfiguration or attack |
| Unusual times | Unauthorized use |
| High volume | Script errors or abuse |

## Quick Reference

### API Key Checklist

Before going live:

- [ ] API key generated
- [ ] Key stored securely
- [ ] Key configured in external platforms
- [ ] Order mode set correctly (Auto/Semi-Auto)
- [ ] Test order placed (in Analyzer mode)
- [ ] Traffic logs reviewed

### Key Information

| Property | Details |
|----------|---------|
| Length | 32 characters |
| Format | Alphanumeric |
| Validity | Until regenerated |
| Scope | Single OpenAlgo instance |
| Regeneration | Manual only |

---

**Previous**: [08 - Understanding the Interface](../08-understanding-interface/README.md)

**Next**: [10 - Placing Your First Order](../10-placing-first-order/README.md)
