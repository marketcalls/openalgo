# 29 - Ngrok Configuration

## Overview

Ngrok creates secure tunnels to expose your local OpenAlgo instance to the internet, enabling webhook integrations from TradingView, Chartink, and other external services.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Ngrok Tunnel Architecture                           │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                        External Services                                     │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  TradingView    │  │   Chartink      │  │   GoCharting    │             │
│  │   Webhooks      │  │   Webhooks      │  │   Webhooks      │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                │                                             │
│                                ▼                                             │
│               https://your-domain.ngrok.io                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 │ Secure Tunnel
                                 │
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Ngrok Client                                        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  ngrok http 5000                                                     │   │
│  │                                                                      │   │
│  │  - Encrypted tunnel                                                  │   │
│  │  - HTTPS termination                                                 │   │
│  │  - Request inspection                                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       OpenAlgo (localhost:5000)                              │
│                                                                              │
│  POST /api/v1/placeorder                                                    │
│  POST /api/v1/webhook/{strategy_id}                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Configuration

### Environment Variables

```bash
# Enable ngrok
NGROK_ENABLED=True

# Ngrok auth token (from ngrok.com dashboard)
NGROK_AUTH_TOKEN=your_ngrok_auth_token_here

# Custom domain (optional, requires paid plan)
NGROK_DOMAIN=your-custom-domain.ngrok.io

# Or use HOST_SERVER to auto-detect custom domain
HOST_SERVER=https://your-custom-domain.ngrok.io
```

## Setup Steps

### 1. Create Ngrok Account

1. Go to https://ngrok.com
2. Sign up for free account
3. Copy your auth token

### 2. Configure OpenAlgo

```bash
# .env
NGROK_ENABLED=True
NGROK_AUTH_TOKEN=2abc123def456...
```

### 3. Start OpenAlgo

```bash
uv run app.py
```

Ngrok starts automatically and displays the public URL:

```
╭─── OpenAlgo v2.0.0 ───────────────────────────────────────────╮
│                                                               │
│ Endpoints                                                     │
│ Web App    http://127.0.0.1:5000                             │
│ WebSocket  ws://127.0.0.1:8765                               │
│ Ngrok      https://abc123.ngrok.io                           │
│                                                               │
│ Status     Ready                                              │
│                                                               │
╰───────────────────────────────────────────────────────────────╯
```

## Custom Domain (Paid Feature)

### Configuration

```bash
# Using NGROK_DOMAIN
NGROK_DOMAIN=trading.yourdomain.com

# Or using HOST_SERVER
HOST_SERVER=https://trading.yourdomain.com
```

### Benefits

- Consistent URL (doesn't change on restart)
- Professional appearance
- Better for production webhooks

## Implementation

### Manager Class

```python
# utils/ngrok_manager.py

def start_ngrok_tunnel(port):
    """Start ngrok tunnel for given port"""
    # Kill existing ngrok processes
    kill_existing_ngrok()

    # Set auth token
    conf.get_default().auth_token = NGROK_AUTH_TOKEN

    # Check for custom domain
    custom_domain = get_custom_domain()

    if custom_domain:
        # Use custom domain
        tunnel = ngrok.connect(
            port,
            domain=custom_domain
        )
    else:
        # Use random subdomain
        tunnel = ngrok.connect(port)

    return tunnel.public_url
```

### Cleanup Handling

```python
def setup_ngrok_handlers():
    """Register cleanup handlers"""
    import signal
    import atexit

    def cleanup():
        ngrok.disconnect()
        ngrok.kill()

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda s, f: cleanup())
    signal.signal(signal.SIGINT, lambda s, f: cleanup())
```

## Webhook Configuration

### TradingView Webhook URL

```
https://your-domain.ngrok.io/api/v1/placeorder
```

### Webhook Payload

```json
{
    "apikey": "your_openalgo_api_key",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 100,
    "product": "MIS",
    "pricetype": "MARKET"
}
```

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Tunnel not starting | Check NGROK_AUTH_TOKEN |
| Connection refused | Ensure OpenAlgo is running |
| URL changes on restart | Use custom domain |
| Rate limiting | Upgrade ngrok plan |

### Debug Mode

```python
import logging
logging.getLogger('pyngrok').setLevel(logging.DEBUG)
```

## Security Considerations

### HTTPS Only

Ngrok provides HTTPS by default. Always use the `https://` URL for webhooks.

### API Key Validation

All webhook requests must include valid API key:

```python
@bp.route('/api/v1/placeorder', methods=['POST'])
def place_order():
    api_key = request.json.get('apikey')
    if not validate_api_key(api_key):
        return {"status": "error"}, 403
```

### IP Filtering (Optional)

For additional security, whitelist TradingView IPs:

```python
TRADINGVIEW_IPS = [
    '52.89.214.238',
    '34.212.75.30',
    # ... more IPs
]
```

## Platform Support

### Windows

```bash
# Auth token location
%USERPROFILE%\.ngrok2\ngrok.yml
```

### macOS/Linux

```bash
# Auth token location
~/.ngrok2/ngrok.yml
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `utils/ngrok_manager.py` | Ngrok management |
| `.env` | Configuration |
| `app.py` | Startup integration |
