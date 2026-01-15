# Utilities Module

OpenAlgo provides 19 utility modules with 80+ functions covering logging, authentication, validation, HTTP clients, security middleware, and more. These utilities promote code reuse and separation of concerns.

## Utility Modules Overview

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `api_analyzer.py` | Request validation | `generate_order_id`, `analyze_api_request` |
| `auth_utils.py` | Auth operations | `validate_password_strength`, `handle_auth_success` |
| `config.py` | Env config access | `get_broker_api_key`, `get_login_rate_limit_min` |
| `constants.py` | Static values | `VALID_EXCHANGES`, `VALID_ACTIONS` |
| `email_debug.py` | SMTP debugging | `debug_smtp_connection` |
| `email_utils.py` | Email sending | `send_test_email`, `send_password_reset_email` |
| `env_check.py` | Env validation | `load_and_check_env_variables` |
| `httpx_client.py` | HTTP client | `get_httpx_client`, `request`, `get`, `post` |
| `ip_helper.py` | IP resolution | `get_real_ip` |
| `latency_monitor.py` | Performance tracking | `LatencyTracker`, `@track_latency` |
| `logging.py` | Logging setup | `setup_logging`, `get_logger` |
| `number_formatter.py` | Indian formatting | `format_indian_number`, `format_indian_currency` |
| `plugin_loader.py` | Broker loading | `load_broker_auth_functions` |
| `security_middleware.py` | IP banning | `SecurityMiddleware`, `@check_ip_ban` |
| `session.py` | Session management | `@check_session_validity`, `is_session_valid` |
| `socketio_error_handler.py` | WebSocket errors | `init_socketio_error_handling` |
| `traffic_logger.py` | Traffic logging | `TrafficLoggerMiddleware` |
| `version.py` | Version info | `VERSION`, `get_version` |

## Core Utilities

### API Analyzer (`api_analyzer.py`)

Request validation and order ID generation:

```python
def generate_order_id() -> str:
    """Generate sequential order ID in YYMMDDXXXXX format"""
    # Example: 24120100001

def analyze_api_request(order_data: dict) -> tuple[bool, str]:
    """Validate place order request"""
    # Validates: symbol, exchange, action, quantity, product, price_type

def analyze_smart_order_request(order_data: dict) -> tuple[bool, str]:
    """Validate smart order (multi-leg) request"""

def analyze_cancel_order_request(order_data: dict) -> tuple[bool, str]:
    """Validate cancel order request"""

def check_rate_limits(user_id: str) -> bool:
    """Check if rate limits exceeded in past 5 minutes"""

def validate_symbol(symbol: str, exchange: str) -> bool:
    """Validate symbol exists in database"""

def get_analyzer_stats() -> dict:
    """Get 24-hour analytics (requests, issues, symbols)"""
```

### Authentication Utilities (`auth_utils.py`)

```python
def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password requirements"""
    # - Minimum 8 characters
    # - At least 1 uppercase (A-Z)
    # - At least 1 lowercase (a-z)
    # - At least 1 number (0-9)
    # - At least 1 special character (!@#$%^&*)

def mask_api_credential(credential: str, show_chars: int = 4) -> str:
    """Mask credentials for display"""
    # "abc123xyz789" -> "abc1****"

def handle_auth_success(auth_token, user_session_key, broker, feed_token, user_id):
    """Post-login setup: store tokens, download contracts"""

def handle_auth_failure(error_message: str, forward_url: str):
    """Post-login failure handling"""

def get_feed_token() -> str:
    """Retrieve feed token from session/database"""

async def async_master_contract_download(broker: str):
    """Async download of master contracts"""
```

### Constants (`constants.py`)

```python
# Valid values for order validation
VALID_EXCHANGES = ['NSE', 'NFO', 'CDS', 'BSE', 'BFO', 'BCD',
                   'MCX', 'NCDEX', 'NSE_INDEX', 'BSE_INDEX']

VALID_PRODUCTS = ['CNC', 'NRML', 'MIS']

VALID_PRICE_TYPES = ['MARKET', 'LIMIT', 'SL', 'SL-M']

VALID_ACTIONS = ['BUY', 'SELL']

# Required fields for different order types
REQUIRED_ORDER_FIELDS = ['symbol', 'exchange', 'action', 'quantity']
REQUIRED_SMART_ORDER_FIELDS = ['symbol', 'exchange', 'action', 'quantity', 'position_size']
REQUIRED_CANCEL_FIELDS = ['orderid']
REQUIRED_CLOSE_POSITION_FIELDS = ['symbol', 'exchange', 'product']
REQUIRED_MODIFY_FIELDS = ['orderid', 'quantity']

# Default values
DEFAULT_PRODUCT = 'MIS'
DEFAULT_PRICE_TYPE = 'MARKET'
DEFAULT_PRICE = 0
DEFAULT_TRIGGER_PRICE = 0
DEFAULT_DISCLOSED_QTY = 0

# UI badge colors for exchanges
EXCHANGE_BADGE_COLORS = {
    'NSE': 'badge-primary',
    'BSE': 'badge-secondary',
    'NFO': 'badge-success',
    'MCX': 'badge-warning'
}
```

## HTTP Client (`httpx_client.py`)

High-performance HTTP client with connection pooling:

```python
def get_httpx_client() -> httpx.Client:
    """Get globally cached httpx client"""
    # Features:
    # - HTTP/2 auto-negotiation (disabled in Docker)
    # - Connection limits: max 20 keepalive, 50 total
    # - 120-second timeout
    # - Event hooks for latency tracking

def request(method: str, url: str, **kwargs) -> httpx.Response:
    """Make HTTP request with protocol negotiation"""

def get(url: str, **kwargs) -> httpx.Response:
    """HTTP GET request"""

def post(url: str, **kwargs) -> httpx.Response:
    """HTTP POST request"""

def put(url: str, **kwargs) -> httpx.Response:
    """HTTP PUT request"""

def delete(url: str, **kwargs) -> httpx.Response:
    """HTTP DELETE request"""

def cleanup_httpx_client():
    """Close and release client resources"""
```

## Session Management (`session.py`)

IST timezone-aware session handling:

```python
def get_session_expiry_time() -> timedelta:
    """Returns timedelta to 3 AM IST (or configured time)"""
    # Reads SESSION_EXPIRY_TIME from env (default: "03:00")

def set_session_login_time():
    """Store login time as ISO string in IST"""

def is_session_valid() -> bool:
    """Check if session exists and hasn't expired past daily threshold"""

def revoke_user_tokens():
    """Clear auth, symbol, settings, strategy, telegram caches"""
    """Revoke database tokens"""

@check_session_validity
def protected_route():
    """Decorator checking session validity"""
    # Redirects to /login or returns JSON 401

@invalidate_session_if_invalid
def route():
    """Decorator clearing invalid sessions without redirect"""
```

## IP Resolution (`ip_helper.py`)

Client IP detection with proxy support:

```python
def get_real_ip() -> str:
    """Get client IP from request headers"""
    # Checks in order:
    # 1. CF-Connecting-IP (Cloudflare)
    # 2. True-Client-IP (Cloudflare Enterprise)
    # 3. X-Real-IP (nginx)
    # 4. X-Forwarded-For (proxies, first IP)
    # 5. X-Client-IP (some proxies)
    # 6. request.remote_addr (fallback)

def get_real_ip_from_environ(environ: dict) -> str:
    """Same logic from WSGI environ dict"""
```

## Latency Monitoring (`latency_monitor.py`)

Performance tracking for API endpoints:

```python
class LatencyTracker:
    """Track execution stages"""

    def start_stage(self, stage_name: str):
        """Begin timing a stage"""

    def end_stage(self):
        """End timing, store in milliseconds"""

    def get_total_time(self) -> float:
        """Total elapsed time"""

    def get_rtt(self) -> float:
        """Round-trip time (Postman-comparable)"""

    def get_overhead(self) -> float:
        """Platform processing time"""

@track_latency(api_type='place_order')
def place_order_endpoint():
    """Decorator for API endpoints with latency logging"""

def wrap_resource_methods(resource_class, api_type: str):
    """Wrap RESTX resource methods"""

def init_latency_monitoring(app):
    """Initialize database and wrap all API endpoints"""
```

## Security Middleware (`security_middleware.py`)

IP banning and security checks:

```python
class SecurityMiddleware:
    """WSGI middleware checking IP bans"""

    def __call__(self, environ, start_response):
        ip = get_real_ip_from_environ(environ)
        if is_ip_banned(ip):
            return forbidden_response()
        return self.app(environ, start_response)

@check_ip_ban
def protected_route():
    """Decorator to check if IP is banned (returns 403)"""

def init_security_middleware(app):
    """Initialize IP ban checks and error handlers"""
```

## Number Formatting (`number_formatter.py`)

Indian number formatting (Crores/Lakhs):

```python
def format_indian_number(value: float) -> str:
    """Format numbers in Cr/L format"""
    # 10,000,000+ = Crores (1.00Cr)
    # 100,000+ = Lakhs (99.78L)
    # Below = decimals (10000.00)

def format_indian_currency(value: float) -> str:
    """Same as above with Rs. prefix"""
    # Rs. 1.50Cr, Rs. 25.00L
```

**Examples:**
| Input | Output |
|-------|--------|
| 10000000 | 1.00Cr |
| 999800 | 9.99L |
| 5000 | 5000.00 |
| -5000000 | -50.00L |

## Plugin Loader (`plugin_loader.py`)

Dynamic broker module loading:

```python
def load_broker_auth_functions(broker_directory: str = 'broker') -> dict:
    """Dynamically import all broker auth modules"""
    # Returns: {'angel': authenticate_broker, 'zerodha': authenticate_broker, ...}

    # Scans broker/{broker_name}/api/auth_api.py
    # Imports authenticate_broker function from each
```

## Email Utilities (`email_utils.py`)

Email sending functionality:

```python
def send_test_email(recipient_email: str, sender_name: str) -> bool:
    """Send HTML test email"""

def send_password_reset_email(recipient_email: str, reset_link: str, user_name: str) -> bool:
    """Send password reset link email"""

def send_email(recipient_email: str, subject: str, text_content: str,
               html_content: str, smtp_settings: dict) -> bool:
    """Generic email sender with TLS/SSL support"""

def validate_smtp_settings(smtp_settings: dict) -> tuple[bool, str]:
    """Test SMTP connection without sending"""
```

## Environment Validation (`env_check.py`)

Comprehensive startup validation:

```python
def check_env_version_compatibility() -> bool:
    """Compare .env vs .sample.env versions"""

def load_and_check_env_variables() -> bool:
    """Validate all required env vars"""
    # Validates:
    # - Broker API key format (5paisa, Flattrade, Dhan)
    # - Port number ranges (0-65535)
    # - Rate limit format ("number per timeunit")
    # - Session expiry time format (HH:MM)
    # - REDIRECT_URL format and broker name
    # - WebSocket URL format (ws:// or wss://)
    # - Logging configuration
```

## Traffic Logger (`traffic_logger.py`)

HTTP traffic logging middleware:

```python
class TrafficLoggerMiddleware:
    """WSGI middleware logging all requests"""

    def __call__(self, environ, start_response):
        # Skips: static files, favicon, traffic endpoints
        # Tracks: duration_ms, status_code, client_ip, method, path, host

def init_traffic_logging(app):
    """Wrap app with middleware"""
```

## WebSocket Error Handler (`socketio_error_handler.py`)

```python
@handle_disconnected_session
def websocket_handler():
    """Decorator catching 'Session is disconnected' errors"""

def init_socketio_error_handling(socketio_instance):
    """Set default error handler for all namespaces"""
```

## Version Management (`version.py`)

```python
VERSION = '1.0.0.39'

def get_version() -> str:
    """Return current version string"""
```

## Decorators Summary

| Decorator | Module | Purpose |
|-----------|--------|---------|
| `@check_session_validity` | session.py | Validate session before route |
| `@invalidate_session_if_invalid` | session.py | Clear invalid sessions |
| `@check_ip_ban` | security_middleware.py | Check if IP is banned |
| `@track_latency(api_type)` | latency_monitor.py | Track endpoint performance |
| `@handle_disconnected_session` | socketio_error_handler.py | Handle Socket.IO disconnections |

## Middleware Summary

| Middleware | Module | Purpose |
|------------|--------|---------|
| `SecurityMiddleware` | security_middleware.py | IP ban checking |
| `TrafficLoggerMiddleware` | traffic_logger.py | HTTP traffic logging |
| `SensitiveDataFilter` | logging.py | Credential redaction in logs |
| `ColoredFormatter` | logging.py | Colored log output |

## Common Usage Patterns

```python
# Logging (used in almost every module)
from utils.logging import get_logger
logger = get_logger(__name__)

# API validation
from utils.api_analyzer import analyze_request
from utils.constants import VALID_EXCHANGES
is_valid, error = analyze_request(order_data, 'placeorder')

# Session checking
from utils.session import check_session_validity
@check_session_validity
def dashboard():
    pass

# IP detection
from utils.ip_helper import get_real_ip
client_ip = get_real_ip()

# HTTP requests
from utils.httpx_client import request
response = request('POST', url, json=data)

# Configuration
from utils.config import get_broker_api_key
api_key = get_broker_api_key()
```

## Related Documentation

- [Logging System](./10_logging_system.md) - Detailed logging configuration
- [Authentication Platform](./06_authentication_platform.md) - Auth utility usage
- [Configuration](./07_configuration.md) - Environment validation
- [API Layer](./02_api_layer.md) - API analyzer usage
