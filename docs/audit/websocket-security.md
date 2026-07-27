# WebSocket Security Assessment

## Overview

OpenAlgo uses WebSockets for real-time market data streaming. When deployed via `install.sh`, WebSocket traffic is secured through Nginx reverse proxy with TLS.

**Risk Level**: Low
**Status**: Good

## WebSocket Architecture (Production)

```
Client Browser
      │
      │ wss://yourdomain.com/ws (Encrypted)
      ▼
┌─────────────────────────────────────┐
│            Nginx                     │
│  • TLS termination                   │
│  • WebSocket upgrade handling        │
│  • Extended timeouts (24h)           │
└─────────────────────────────────────┘
      │
      │ ws://127.0.0.1:8765 (Internal)
      ▼
┌─────────────────────────────────────┐
│      WebSocket Proxy Server          │
│  • Market data streaming             │
│  • LTP, Quote, Depth feeds           │
└─────────────────────────────────────┘
```

## What `install.sh` Configures

### TLS Encryption

WebSocket traffic is encrypted via Nginx:

```nginx
# WebSocket location block (from install.sh)
location = /ws {
    proxy_pass http://127.0.0.1:8765;
    proxy_http_version 1.1;

    # Extended timeouts for long-running connections
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;

    # Disable buffering for real-time data
    proxy_buffering off;

    # WebSocket upgrade headers
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### Security Features

| Feature | Status | Details |
|---------|--------|---------|
| TLS encryption | Yes | Via Nginx (wss://) |
| Extended timeouts | Yes | 24 hours for market data |
| Buffering disabled | Yes | Real-time data delivery |
| Proper headers | Yes | Upgrade, Connection, etc. |

## Two WebSocket Systems

### 1. Flask-SocketIO (Port 5000)

**Purpose**: Real-time UI updates
- Order notifications
- Position changes
- Log streaming

**Authentication**: Session-based (must be logged in)

```python
@socketio.on('connect')
def handle_connect():
    if not current_user.is_authenticated:
        return False  # Reject connection
```

### 2. WebSocket Proxy (Port 8765)

**Purpose**: Market data streaming
- LTP (Last Traded Price)
- Quote (OHLCV)
- Depth (Order book)

**Access**: Via Nginx reverse proxy at `/ws`

## CORS Configuration

### Current Setting

```python
# extensions.py
socketio = SocketIO(cors_allowed_origins='*')
```

### Why This Is Acceptable

For single-user production deployment:

1. **TLS encryption**: All traffic encrypted via Nginx
2. **Single user**: Only you access the WebSocket
3. **Session auth**: Flask-SocketIO requires login
4. **Market data only**: WebSocket proxy serves public data

### Optional: Restrict Origins

If you want additional restriction:

```python
# extensions.py
import os

ALLOWED_ORIGINS = os.environ.get(
    'SOCKETIO_ORIGINS',
    'https://yourdomain.com'
).split(',')

socketio = SocketIO(cors_allowed_origins=ALLOWED_ORIGINS)
```

Add to `.env`:
```bash
SOCKETIO_ORIGINS=https://yourdomain.com
```

**Priority**: Low - current configuration is secure for single-user.

## Data Security

### What Flows Over WebSocket

| Data Type | Sensitivity | Protection |
|-----------|-------------|------------|
| LTP (price) | Public data | TLS encrypted |
| OHLCV quotes | Public data | TLS encrypted |
| Market depth | Public data | TLS encrypted |
| Order updates | Medium | Session auth + TLS |
| Position changes | Medium | Session auth + TLS |

### No Sensitive Data Transmitted

- Broker credentials: Never sent over WebSocket
- API keys: Never sent over WebSocket
- Passwords: Never sent over WebSocket

## Connection Limits

**Configuration** (`.env`):

```bash
MAX_SYMBOLS_PER_WEBSOCKET=1000
MAX_WEBSOCKET_CONNECTIONS=3
```

**Purpose**: Prevent resource exhaustion

## Verification

### Test WebSocket Connection

```bash
# Using websocat (install: cargo install websocat)
websocat wss://yourdomain.com/ws

# Or using curl to check upgrade
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Key: test" \
  -H "Sec-WebSocket-Version: 13" \
  https://yourdomain.com/ws
```

### Check Nginx WebSocket Config

```bash
sudo nginx -T | grep -A 20 "location = /ws"
```

## Security Checklist

### Auto-Configured (install.sh)

- [x] TLS encryption (wss://)
- [x] Extended timeouts
- [x] Proper WebSocket headers
- [x] Reverse proxy isolation

### Built into OpenAlgo

- [x] Flask-SocketIO session auth
- [x] Connection limits
- [x] Error handling
- [x] No sensitive data in streams

### Optional (Not Required)

- [ ] Restrict CORS origins (low priority)
- [ ] WebSocket message logging (for debugging)

## Troubleshooting

### WebSocket Not Connecting

1. **Check Nginx config**:
   ```bash
   sudo nginx -t
   ```

2. **Check WebSocket proxy**:
   ```bash
   sudo systemctl status openalgo-*
   ```

3. **Check logs**:
   ```bash
   sudo journalctl -u openalgo-* | grep -i websocket
   ```

### Connection Drops

- Normal: Market data pauses after market hours
- Check timeout settings in Nginx
- Verify proxy_read_timeout is 86400s

## Summary

**WebSocket Security**: Strong

**Automatic (install.sh)**:
- TLS encryption via Nginx
- Extended timeouts for market data
- Proper WebSocket upgrade handling
- Reverse proxy isolation

**Built-in (OpenAlgo)**:
- Session authentication for UI updates
- Connection limits
- Public market data only

**No action required** - WebSocket security is production-ready.

---

**Back to**: [Security Audit Overview](./README.md)
