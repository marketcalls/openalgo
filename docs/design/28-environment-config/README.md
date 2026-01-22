# 28 - Environment Configuration

## Overview

OpenAlgo uses environment variables for configuration, managed through a `.env` file with validation at startup.

## Configuration File

### Location
```
.env (root directory)
```

### Template
```
.sample.env (reference template)
```

## Environment Variables

### Core Application

```bash
# Application secret key (required)
APP_KEY=your_32_character_secret_key_here

# API key encryption pepper (required)
API_KEY_PEPPER=your_32_character_pepper_here

# Flask debug mode
FLASK_DEBUG=False

# Application host and port
HOST_SERVER=http://127.0.0.1:5000
```

### Database Configuration

```bash
# Main database
MAIN_DATABASE_URL=sqlite:///db/openalgo.db

# Logs database
LOGS_DATABASE_URL=sqlite:///db/logs.db

# Latency database
LATENCY_DATABASE_URL=sqlite:///db/latency.db

# Sandbox database
SANDBOX_DATABASE_URL=sqlite:///db/sandbox.db

# Historical data (DuckDB)
HISTORIFY_DATABASE_PATH=db/historify.duckdb
```

### Broker Configuration

```bash
# Enabled brokers
VALID_BROKERS=zerodha,dhan,angel,shoonya,firstock

# Broker API credentials
BROKER_API_KEY=your_broker_api_key
BROKER_API_SECRET=your_broker_api_secret

# Redirect URL for OAuth brokers
REDIRECT_URL=http://127.0.0.1:5000
```

### WebSocket Configuration

```bash
# WebSocket server
WEBSOCKET_HOST=127.0.0.1
WEBSOCKET_PORT=8765
WEBSOCKET_URL=ws://127.0.0.1:8765

# Connection limits
MAX_SYMBOLS_PER_WEBSOCKET=1000
MAX_WEBSOCKET_CONNECTIONS=3
```

### Rate Limiting

```bash
# API rate limits
API_RATE_LIMIT=50 per second
ORDER_RATE_LIMIT=10 per second

# Login rate limits
LOGIN_RATE_LIMIT_MIN=5 per minute
LOGIN_RATE_LIMIT_HOUR=25 per hour
```

### Session Configuration

```bash
# Session expiry time (24-hour format)
SESSION_EXPIRY_TIME=03:00
```

### Logging Configuration

```bash
# Enable file logging
LOG_TO_FILE=True

# Log level
LOG_LEVEL=INFO

# Log directory
LOG_DIR=log

# Log retention (days)
LOG_RETENTION=14
```

### Security Settings

```bash
# 404 error threshold for IP ban
SECURITY_404_THRESHOLD=20
SECURITY_404_BAN_DURATION=24

# API abuse threshold
SECURITY_API_THRESHOLD=10
SECURITY_API_BAN_DURATION=48

# Repeat offender limit
SECURITY_REPEAT_OFFENDER_LIMIT=3
```

### Ngrok Configuration

```bash
# Enable ngrok tunnel
NGROK_ENABLED=False
NGROK_AUTH_TOKEN=your_ngrok_auth_token

# Custom domain (optional)
NGROK_DOMAIN=your-custom-domain.ngrok.io
```

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
| APP_KEY | Must be 32+ characters |
| API_KEY_PEPPER | Must be 32+ characters |
| PORT | 0-65535 |
| RATE_LIMIT | Format: "X per Y" |
| SESSION_EXPIRY_TIME | Format: HH:MM |
| WEBSOCKET_URL | Starts with ws:// or wss:// |
| LOG_LEVEL | DEBUG/INFO/WARNING/ERROR/CRITICAL |

## Version Compatibility

### Version Check

```python
def check_env_version_compatibility():
    """Ensure .env matches .sample.env version"""
    env_version = get_env_version('.env')
    sample_version = get_env_version('.sample.env')

    if env_version != sample_version:
        logger.warning(
            f"Environment version mismatch: "
            f".env={env_version}, .sample.env={sample_version}"
        )
```

## Generating Secrets

### App Key and Pepper

```bash
# Generate 32-character hex key
python -c "import secrets; print(secrets.token_hex(32))"
```

### Example Output
```
a1b2c3d4e5f6789012345678901234567890123456789012345678901234
```

## Broker-Specific Configuration

### Zerodha

```bash
BROKER_API_KEY=your_kite_api_key
BROKER_API_SECRET=your_kite_api_secret
```

### Dhan

```bash
BROKER_API_KEY=your_dhan_client_id
BROKER_API_SECRET=your_dhan_access_token
```

### Angel One

```bash
BROKER_API_KEY=your_angel_api_key
BROKER_API_SECRET=your_angel_secret
```

### 5Paisa

```bash
BROKER_API_KEY=AppName:UserId:EncryptionKey
BROKER_API_SECRET=password
```

## Environment Helpers

### Accessing Config

```python
from utils.config import (
    get_broker_api_key,
    get_broker_api_secret,
    get_host_server
)

api_key = get_broker_api_key()
api_secret = get_broker_api_secret()
host = get_host_server()
```

### Default Values

```python
import os

# With default fallback
port = int(os.getenv('PORT', '5000'))
debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
```

## Production vs Development

### Development (.env)

```bash
FLASK_DEBUG=True
LOG_LEVEL=DEBUG
NGROK_ENABLED=True
HOST_SERVER=http://127.0.0.1:5000
```

### Production (.env)

```bash
FLASK_DEBUG=False
LOG_LEVEL=INFO
NGROK_ENABLED=False
HOST_SERVER=https://your-domain.com
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

### Use Environment Variables in Production

```bash
# Export instead of .env file
export APP_KEY="your_secret_key"
export BROKER_API_KEY="your_api_key"
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `.env` | Environment configuration |
| `.sample.env` | Template file |
| `utils/env_check.py` | Validation logic |
| `utils/config.py` | Config helpers |
