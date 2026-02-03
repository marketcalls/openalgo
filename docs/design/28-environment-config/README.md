# 28 - Environment Configuration

## Overview

OpenAlgo uses environment variables for configuration, managed through a `.env` file with validation at startup. For cloud deployments (Railway/Render), the `start.sh` script can auto-generate `.env` from environment variables.

## Configuration Files

```
.env                # Active configuration (not in git)
.sample.env         # Reference template with all variables
```

## Environment Variables (65+ Variables)

### Version Tracking

```bash
# Configuration version - compare with .sample.env when updating
ENV_CONFIG_VERSION = '1.0.6'
```

### Core Security (Required)

```bash
# Application secret key (required, 32+ characters)
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
APP_KEY = 'your_32_character_secret_key_here'

# Security pepper for API key hashing, password hashing, token encryption
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
API_KEY_PEPPER = 'your_32_character_pepper_here'
```

### Broker Configuration

```bash
# Broker API credentials
BROKER_API_KEY = 'YOUR_BROKER_API_KEY'
BROKER_API_SECRET = 'YOUR_BROKER_API_SECRET'

# XTS API brokers only (5Paisa XTS, Jainam XTS, etc.)
BROKER_API_KEY_MARKET = 'YOUR_BROKER_MARKET_API_KEY'
BROKER_API_SECRET_MARKET = 'YOUR_BROKER_MARKET_API_SECRET'

# OAuth redirect URL
REDIRECT_URL = 'http://127.0.0.1:5000/<broker>/callback'

# Enabled brokers (comma-separated)
VALID_BROKERS = 'fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,dhan,dhan_sandbox,definedge,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,jainamxts,kotak,motilal,mstock,nubra,paytm,pocketful,samco,shoonya,tradejini,upstox,wisdom,zebu,zerodha'
```

### Database Configuration

```bash
# Main database
DATABASE_URL = 'sqlite:///db/openalgo.db'

# Additional databases
LATENCY_DATABASE_URL = 'sqlite:///db/latency.db'
LOGS_DATABASE_URL = 'sqlite:///db/logs.db'
SANDBOX_DATABASE_URL = 'sqlite:///db/sandbox.db'
HISTORIFY_DATABASE_URL = 'db/historify.duckdb'
```

### Flask Application

```bash
# Host and port
FLASK_HOST_IP = '127.0.0.1'  # Use 0.0.0.0 for external access
FLASK_PORT = '5000'

# Environment
FLASK_DEBUG = 'False'
FLASK_ENV = 'development'  # or 'production'

# Public URL
HOST_SERVER = 'http://127.0.0.1:5000'
```

### WebSocket Configuration

```bash
# WebSocket server
WEBSOCKET_HOST = '127.0.0.1'
WEBSOCKET_PORT = '8765'
WEBSOCKET_URL = 'ws://127.0.0.1:8765'

# ZeroMQ message bus
ZMQ_HOST = '127.0.0.1'
ZMQ_PORT = '5555'
```

### Connection Pooling

```bash
# Maximum symbols per WebSocket connection (default: 1000)
MAX_SYMBOLS_PER_WEBSOCKET = '1000'

# Maximum WebSocket connections per user/broker (default: 3)
# Total capacity = MAX_SYMBOLS_PER_WEBSOCKET × MAX_WEBSOCKET_CONNECTIONS
MAX_WEBSOCKET_CONNECTIONS = '3'

# Enable/disable connection pooling (default: true)
ENABLE_CONNECTION_POOLING = 'true'
```

### Ngrok Configuration

```bash
# Enable ngrok tunnel
NGROK_ALLOW = 'FALSE'
```

### Logging Configuration

```bash
# File logging
LOG_TO_FILE = 'False'
LOG_LEVEL = 'INFO'  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_DIR = 'log'
LOG_FORMAT = '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
LOG_RETENTION = '14'  # Days

# Color output
LOG_COLORS = 'True'
FORCE_COLOR = '1'
```

### Python Strategy Logging

```bash
# Maximum log files per strategy (oldest deleted first)
STRATEGY_LOG_MAX_FILES = '10'

# Maximum total log size per strategy in MB
STRATEGY_LOG_MAX_SIZE_MB = '50'

# Delete strategy logs older than N days
STRATEGY_LOG_RETENTION_DAYS = '7'
```

### Rate Limiting

```bash
# Login rate limits
LOGIN_RATE_LIMIT_MIN = '5 per minute'
LOGIN_RATE_LIMIT_HOUR = '25 per hour'
RESET_RATE_LIMIT = '15 per hour'

# API rate limits
API_RATE_LIMIT = '50 per second'
ORDER_RATE_LIMIT = '10 per second'
SMART_ORDER_RATE_LIMIT = '2 per second'

# Webhook rate limits
WEBHOOK_RATE_LIMIT = '100 per minute'
STRATEGY_RATE_LIMIT = '200 per minute'
```

### API Configuration

```bash
# Delay between multi-leg option orders (seconds)
SMART_ORDER_DELAY = '0.5'

# Session expiry time (24-hour format, IST)
SESSION_EXPIRY_TIME = '03:00'
```

### CORS Configuration

```bash
# Enable/disable CORS
CORS_ENABLED = 'TRUE'

# Allowed origins (comma-separated)
CORS_ALLOWED_ORIGINS = 'http://127.0.0.1:5000'

# Allowed HTTP methods
CORS_ALLOWED_METHODS = 'GET,POST,DELETE,PUT,PATCH'

# Allowed headers
CORS_ALLOWED_HEADERS = 'Content-Type,Authorization,X-Requested-With'

# Exposed headers
CORS_EXPOSED_HEADERS = ''

# Allow credentials (cookies, auth headers)
CORS_ALLOW_CREDENTIALS = 'FALSE'

# Preflight cache max age (seconds)
CORS_MAX_AGE = '86400'
```

### Content Security Policy (CSP)

```bash
# Enable/disable CSP
CSP_ENABLED = 'TRUE'

# Report-only mode (testing)
CSP_REPORT_ONLY = 'FALSE'

# CSP directives
CSP_DEFAULT_SRC = "'self'"
CSP_SCRIPT_SRC = "'self' 'unsafe-inline' https://cdn.socket.io https://static.cloudflareinsights.com"
CSP_STYLE_SRC = "'self' 'unsafe-inline'"
CSP_IMG_SRC = "'self' data:"
CSP_CONNECT_SRC = "'self' wss: ws: https://cdn.socket.io"
CSP_FONT_SRC = "'self'"
CSP_OBJECT_SRC = "'none'"
CSP_MEDIA_SRC = "'self' data: https://*.amazonaws.com https://*.cloudfront.net"
CSP_FRAME_SRC = "'self'"
CSP_FORM_ACTION = "'self'"
CSP_FRAME_ANCESTORS = "'self'"
CSP_BASE_URI = "'self'"
CSP_UPGRADE_INSECURE_REQUESTS = 'FALSE'
CSP_REPORT_URI = ''
```

### CSRF Protection

```bash
# Enable/disable CSRF protection
CSRF_ENABLED = 'TRUE'

# Token time limit (seconds, empty = no limit)
CSRF_TIME_LIMIT = ''
```

### Cookie Configuration

```bash
# Cookie names (customize for multiple instances)
SESSION_COOKIE_NAME = 'session'
CSRF_COOKIE_NAME = 'csrf_token'
```

## Railway/Cloud Deployment

When deploying to Railway or Render, set these environment variables in the platform dashboard:

### Required Variables

| Variable | Description |
|----------|-------------|
| `HOST_SERVER` | Your app URL (e.g., `https://your-app.up.railway.app`) |
| `REDIRECT_URL` | Broker OAuth callback URL |
| `BROKER_API_KEY` | Broker API key |
| `BROKER_API_SECRET` | Broker API secret |
| `APP_KEY` | Generated secret key |
| `API_KEY_PEPPER` | Generated pepper |

### Auto-Generated by start.sh

When `HOST_SERVER` is set and no `.env` exists, `start.sh` automatically generates `.env` with:
- All security settings
- CORS configured for your domain
- CSP with secure WebSocket URLs
- Railway's `PORT` environment variable support

## Validation

### Startup Validation

```python
from utils.env_check import load_and_check_env_variables

def validate_env():
    """Run on app startup"""
    errors = load_and_check_env_variables()
    if errors:
        for error in errors:
            logger.error(error)
        sys.exit(1)
```

### Validation Rules

| Variable | Validation |
|----------|------------|
| `APP_KEY` | Must be 32+ characters |
| `API_KEY_PEPPER` | Must be 32+ characters |
| `*_PORT` | 0-65535 |
| `*_RATE_LIMIT*` | Format: "X per Y" |
| `SESSION_EXPIRY_TIME` | Format: HH:MM |
| `WEBSOCKET_URL` | Starts with ws:// or wss:// |
| `LOG_LEVEL` | DEBUG/INFO/WARNING/ERROR/CRITICAL |

## Generating Secrets

```bash
# Generate 32-character hex key for APP_KEY and API_KEY_PEPPER
python -c "import secrets; print(secrets.token_hex(32))"

# Output example:
# a1b2c3d4e5f6789012345678901234567890123456789012345678901234
```

## Environment Comparison

### Development

```bash
FLASK_DEBUG = 'True'
FLASK_ENV = 'development'
LOG_LEVEL = 'DEBUG'
HOST_SERVER = 'http://127.0.0.1:5000'
FLASK_HOST_IP = '127.0.0.1'
CSP_UPGRADE_INSECURE_REQUESTS = 'FALSE'
```

### Production (Local)

```bash
FLASK_DEBUG = 'False'
FLASK_ENV = 'production'
LOG_LEVEL = 'INFO'
HOST_SERVER = 'https://your-domain.com'
FLASK_HOST_IP = '0.0.0.0'
CSP_UPGRADE_INSECURE_REQUESTS = 'TRUE'
```

### Production (Railway)

```bash
# Set in Railway dashboard, start.sh generates .env:
HOST_SERVER = 'https://your-app.up.railway.app'
FLASK_HOST_IP = '0.0.0.0'  # Auto-set
FLASK_PORT = '${PORT}'  # Railway's PORT
WEBSOCKET_HOST = '0.0.0.0'  # Auto-set
ZMQ_HOST = '0.0.0.0'  # Auto-set
```

## Security Best Practices

### File Permissions

```bash
# Restrict .env access
chmod 600 .env
```

### Never Commit Secrets

```gitignore
# .gitignore
.env
*.pem
*.key
```

### Version Check

Compare `ENV_CONFIG_VERSION` in your `.env` with `.sample.env` after updates. If they differ, copy new variables from the sample.

## Key Files Reference

| File | Purpose |
|------|---------|
| `.env` | Active configuration |
| `.sample.env` | Reference template |
| `start.sh` | Auto-generates .env for cloud |
| `utils/env_check.py` | Validation logic |
| `utils/config.py` | Config helpers |
