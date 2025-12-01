# Configuration Management

OpenAlgo uses a comprehensive configuration system with environment variables validated at startup, runtime settings in the database, and intelligent defaults. The system supports 50+ configuration options across security, broker integration, rate limiting, and more.

## Configuration Architecture

```
Startup
   |
   v
+---------------------------+
| load_and_check_env_variables() |
| (utils/env_check.py)      |
+---------------------------+
   |
   v
+---------------------------+
| Validate all 30+ required |
| environment variables     |
+---------------------------+
   |
   v
+---------------------------+
| Initialize Flask app with |
| validated configuration   |
+---------------------------+
   |
   v
+---------------------------+
| Load database settings    |
| (runtime configuration)   |
+---------------------------+
```

## Environment Files

| File | Purpose |
|------|---------|
| `.env` | Active configuration (gitignored) |
| `.sample.env` | Template with all options documented |

**Version Tracking:**
```
ENV_CONFIG_VERSION = '1.0.4'
```

Version mismatch detection ensures users update their `.env` when new options are added.

## Configuration Categories

### 1. Broker Configuration

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `BROKER_API_KEY` | String | Required | Broker API authentication key |
| `BROKER_API_SECRET` | String | Required | Broker API secret |
| `BROKER_API_KEY_MARKET` | String | Optional | Market data API key (XTS brokers) |
| `BROKER_API_SECRET_MARKET` | String | Optional | Market data API secret |
| `REDIRECT_URL` | String | Required | OAuth callback URL |
| `VALID_BROKERS` | CSV | 26 brokers | Enabled broker integrations |

**Broker-Specific Validation:**
```python
# 5paisa format: key1:::key2:::key3
# Flattrade format: client_id:::api_key
# Dhan format: client_id:::api_key
```

### 2. Security Configuration

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `APP_KEY` | String (64 chars) | Required | Flask secret key for sessions |
| `API_KEY_PEPPER` | String (64 chars) | Required | Encryption pepper for sensitive data |
| `CSRF_ENABLED` | Boolean | TRUE | Enable CSRF protection |
| `CSRF_TIME_LIMIT` | Integer | None | CSRF token TTL (seconds) |
| `SESSION_COOKIE_NAME` | String | 'session' | Custom session cookie name |
| `CSRF_COOKIE_NAME` | String | 'csrf_token' | Custom CSRF cookie name |

**Dynamic Cookie Security:**
- Auto-sets `SESSION_COOKIE_SECURE=True` for HTTPS
- Adds `__Secure-` prefix for HTTPS deployments
- `SESSION_COOKIE_HTTPONLY` always True
- `SESSION_COOKIE_SAMESITE` set to 'Lax'

### 3. Database Configuration

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `DATABASE_URL` | String | sqlite:///db/openalgo.db | Main database |
| `LATENCY_DATABASE_URL` | String | sqlite:///db/latency.db | Performance metrics |
| `LOGS_DATABASE_URL` | String | sqlite:///db/logs.db | Traffic logs |
| `SANDBOX_DATABASE_URL` | String | sqlite:///db/sandbox.db | Paper trading |

**Connection Pool Settings:**
```python
# PostgreSQL
pool_size = 50
max_overflow = 100
pool_timeout = 10

# SQLite
poolclass = NullPool
```

### 4. Flask Application

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `FLASK_HOST_IP` | String | 127.0.0.1 | Bind address |
| `FLASK_PORT` | Integer | 5000 | Bind port |
| `FLASK_DEBUG` | Boolean | False | Debug mode |
| `FLASK_ENV` | String | development | Environment |
| `HOST_SERVER` | String | http://127.0.0.1:5000 | Public URL |
| `NGROK_ALLOW` | Boolean | FALSE | Enable ngrok |

### 5. WebSocket Configuration

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `WEBSOCKET_HOST` | String | 127.0.0.1 | WebSocket bind address |
| `WEBSOCKET_PORT` | Integer | 8765 | WebSocket port |
| `WEBSOCKET_URL` | String | ws://127.0.0.1:8765 | Client WebSocket URL |
| `ZMQ_HOST` | String | 127.0.0.1 | ZeroMQ bind address |
| `ZMQ_PORT` | Integer | 5555 | ZeroMQ publisher port |

### 6. Rate Limiting

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `LOGIN_RATE_LIMIT_MIN` | String | 5 per minute | Login attempts/minute |
| `LOGIN_RATE_LIMIT_HOUR` | String | 25 per hour | Login attempts/hour |
| `RESET_RATE_LIMIT` | String | 15 per hour | Password reset limit |
| `API_RATE_LIMIT` | String | 50 per second | General API limit |
| `ORDER_RATE_LIMIT` | String | 10 per second | Order placement limit |
| `SMART_ORDER_RATE_LIMIT` | String | 2 per second | Multi-leg order limit |
| `WEBHOOK_RATE_LIMIT` | String | 100 per minute | Webhook limit |
| `STRATEGY_RATE_LIMIT` | String | 200 per minute | Strategy operations |

**Format:** `number per (second|minute|hour|day)`

### 7. Logging Configuration

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `LOG_TO_FILE` | Boolean | False | Write logs to files |
| `LOG_LEVEL` | Enum | INFO | Logging verbosity |
| `LOG_DIR` | String | log | Log directory |
| `LOG_FORMAT` | String | Standard | Log message format |
| `LOG_RETENTION` | Integer | 14 | Days to keep logs |
| `LOG_COLORS` | Boolean | True | Colored output |

### 8. Order Processing

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `SMART_ORDER_DELAY` | Float | 0.5 | Delay between multi-leg orders (seconds) |
| `SESSION_EXPIRY_TIME` | String | 03:00 | Daily session expiry (IST, HH:MM) |

### 9. CORS Configuration

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `CORS_ENABLED` | Boolean | TRUE | Enable CORS |
| `CORS_ALLOWED_ORIGINS` | CSV | http://127.0.0.1:5000 | Allowed origins |
| `CORS_ALLOWED_METHODS` | CSV | GET,POST,DELETE,PUT,PATCH | Allowed methods |
| `CORS_ALLOWED_HEADERS` | CSV | Content-Type,Authorization,X-Requested-With | Allowed headers |
| `CORS_ALLOW_CREDENTIALS` | Boolean | FALSE | Allow credentials |
| `CORS_MAX_AGE` | Integer | 86400 | Preflight cache (seconds) |

### 10. Content Security Policy (CSP)

| Variable | Type | Default |
|----------|------|---------|
| `CSP_ENABLED` | Boolean | TRUE |
| `CSP_REPORT_ONLY` | Boolean | FALSE |
| `CSP_DEFAULT_SRC` | String | 'self' |
| `CSP_SCRIPT_SRC` | String | 'self' 'unsafe-inline' https://cdn.socket.io |
| `CSP_STYLE_SRC` | String | 'self' 'unsafe-inline' |
| `CSP_IMG_SRC` | String | 'self' data: |
| `CSP_CONNECT_SRC` | String | 'self' wss: ws: |
| `CSP_FRAME_ANCESTORS` | String | 'self' |

## Database-Stored Settings

Runtime-modifiable configuration in the `Settings` table:

### Analyze Mode
```python
analyze_mode: Boolean  # Toggle Live/Analyze mode
# Modified via: /settings/analyze-mode/<mode>
```

### SMTP Configuration
```python
smtp_server: String
smtp_port: Integer
smtp_username: String
smtp_password_encrypted: Text  # Fernet encrypted
smtp_use_tls: Boolean
smtp_from_email: String
smtp_helo_hostname: String
```

### Security Settings
```python
security_404_threshold: Integer = 20      # 404 errors/day before ban
security_404_ban_duration: Integer = 24   # Ban duration (hours)
security_api_threshold: Integer = 10      # Invalid API attempts before ban
security_api_ban_duration: Integer = 48   # Ban duration (hours)
security_repeat_offender_limit: Integer = 3  # Bans before permanent
```

## Validation Rules

### Required Variables (30+)
System will not start without these:
- `BROKER_API_KEY`, `BROKER_API_SECRET`
- `REDIRECT_URL`
- `APP_KEY`, `API_KEY_PEPPER`
- `DATABASE_URL`
- All rate limit variables
- All WebSocket variables
- All logging variables

### Validation Checks

**Port Validation:**
```python
0 <= port <= 65535
```

**Rate Limit Format:**
```python
pattern = r'^\d+\s+per\s+(second|minute|hour|day)$'
# Valid: "5 per minute", "10 per second"
```

**Session Expiry Time:**
```python
pattern = r'^([01]?\d|2[0-3]):([0-5]\d)$'
# Valid: "03:00", "15:30"
```

**WebSocket URL:**
```python
must start with 'ws://' or 'wss://'
```

**REDIRECT_URL:**
```python
pattern = r'http(s)?://[^/]+:\d+/\w+/callback'
# Broker name must exist in VALID_BROKERS
```

## Configuration Caching

```python
from cachetools import TTLCache

# Settings cached for 1 hour to reduce DB queries
settings_cache = TTLCache(maxsize=100, ttl=3600)

# Cache invalidated on settings update
def update_setting(key, value):
    db.update(key, value)
    settings_cache.clear()  # Invalidate cache
```

## Environment-Specific Configuration

### Development
```bash
FLASK_DEBUG=True
FLASK_ENV=development
HOST_SERVER=http://127.0.0.1:5000
WEBSOCKET_URL=ws://127.0.0.1:8765
```

### Production
```bash
FLASK_DEBUG=False
FLASK_ENV=production
HOST_SERVER=https://yourdomain.com
WEBSOCKET_URL=wss://yourdomain.com:8765
```

### Docker
```bash
FLASK_HOST_IP=0.0.0.0
WEBSOCKET_HOST=0.0.0.0
# WebSocket server runs separately via start.sh
```

## Initialization Order

1. **Pre-application** (`app.py` line 1-3)
   - Load and validate environment variables
   - Exit with error if validation fails

2. **Logging initialization**
   - Setup based on LOG_* configuration

3. **Flask app creation**
   - Load APP_KEY, DATABASE_URL, security configs
   - Configure cookie security based on HOST_SERVER

4. **Security middleware**
   - CSRF, CSP, CORS, Rate limiter

5. **Database initialization**
   - Create tables, initialize settings

6. **Blueprint registration**
   - Register routes with rate limits

7. **WebSocket proxy startup**
   - Start on configured host:port

8. **Background services**
   - Telegram bot, latency monitoring

## Configuration Helpers

```python
# utils/config.py
def get_broker_api_key():
    return os.getenv('BROKER_API_KEY')

def get_broker_api_secret():
    return os.getenv('BROKER_API_SECRET')

def get_login_rate_limit_min():
    return os.getenv('LOGIN_RATE_LIMIT_MIN', '5 per minute')

def get_host_server():
    return os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')
```

## Generating Secure Keys

```bash
# Generate APP_KEY (64 characters)
python -c "import secrets; print(secrets.token_hex(32))"

# Generate API_KEY_PEPPER (64 characters)
python -c "import secrets; print(secrets.token_hex(32))"
```

## Related Documentation

- [Authentication Platform](./06_authentication_platform.md) - Security configuration usage
- [Database Layer](./04_database_layer.md) - Database URL configuration
- [Logging System](./10_logging_system.md) - Logging configuration
- [WebSocket Architecture](./09_websocket_architecture.md) - WebSocket configuration
