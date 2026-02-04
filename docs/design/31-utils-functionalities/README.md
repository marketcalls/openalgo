# 31 - Utils Functionalities

## Overview

The utils directory contains shared utility functions used across the OpenAlgo platform for authentication, logging, configuration, and common operations.

## Utils Directory Structure

```
utils/
├── auth_utils.py           # Authentication helpers
├── session.py              # Session management
├── security_middleware.py  # IP security
├── logging.py              # Centralized logging
├── traffic_logger.py       # HTTP traffic logging
├── ip_helper.py            # IP address resolution
├── httpx_client.py         # HTTP client pooling
├── socketio_error_handler.py # Socket.IO errors
├── latency_monitor.py      # Performance tracking
├── api_analyzer.py         # API validation
├── mpp_slab.py             # Market price protection
├── number_formatter.py     # Indian number format
├── constants.py            # Order constants
├── config.py               # Config helpers
├── env_check.py            # Environment validation
├── version.py              # Version management
├── plugin_loader.py        # Broker plugin loading
├── email_utils.py          # Email sending
├── email_debug.py          # Email debugging
├── ngrok_manager.py        # Ngrok tunnels
└── health_monitor.py       # Background health monitoring daemon
```

## Key Utilities

### 1. Authentication Utilities (auth_utils.py)

```python
# Password validation
def validate_password_strength(password):
    """Check password meets security requirements"""
    if len(password) < 8:
        return False, "Minimum 8 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Need uppercase"
    if not re.search(r'[a-z]', password):
        return False, "Need lowercase"
    if not re.search(r'[0-9]', password):
        return False, "Need number"
    if not re.search(r'[!@#$%^&*]', password):
        return False, "Need special character"
    return True, "Valid"

# Credential masking
def mask_api_credential(credential, show_chars=4):
    """Mask credentials for display"""
    # "abc123def456" → "abc1***f456"

# AJAX detection
def is_ajax_request():
    """Detect React/AJAX requests"""

# Master contract download
def async_master_contract_download(broker):
    """Background contract download"""
```

### 2. Session Management (session.py)

```python
# Session expiry
def get_session_expiry_time():
    """Get session expiry (default: 3 AM IST)"""

# Session validation decorator
@check_session_validity
def protected_route():
    """Only accessible with valid session"""

# Token revocation
def revoke_user_tokens():
    """Revoke all auth tokens on logout"""
```

### 3. IP Helper (ip_helper.py)

```python
def get_real_ip():
    """Get client IP from request"""
    # Priority:
    # 1. CF-Connecting-IP (Cloudflare)
    # 2. True-Client-IP
    # 3. X-Real-IP (nginx)
    # 4. X-Forwarded-For
    # 5. remote_addr
```

### 4. HTTP Client (httpx_client.py)

```python
def get_httpx_client():
    """Get connection-pooled HTTP client"""
    # Features:
    # - HTTP/2 support
    # - Connection pooling (20 keepalive, 50 max)
    # - 120-second timeout
    # - Latency tracking hooks

def request(method, url, **kwargs):
    """Make HTTP request with timing"""

def get(url, **kwargs):
    """HTTP GET shortcut"""

def post(url, **kwargs):
    """HTTP POST shortcut"""
```

### 5. Logging (logging.py)

```python
# Get logger instance
logger = get_logger(__name__)

# Colored console output
# Level-based formatting
# Sensitive data filtering

# Startup banner
def log_startup_banner(logger, title, url):
    """Display startup banner"""
```

### 6. Market Price Protection (mpp_slab.py)

```python
def calculate_protected_price(price, action, symbol, instrument_type, tick_size):
    """Convert MARKET to protected LIMIT price"""

# Protection slabs:
# Equity/Futures: < 100 (2%), 100-500 (1%), > 500 (0.5%)
# Options: < 10 (5%), 10-100 (3%), 100-500 (2%), > 500 (1%)

def round_to_tick_size(price, tick_size):
    """Round to valid tick size"""
```

### 7. Number Formatter (number_formatter.py)

```python
def format_indian_number(value):
    """Format using Indian numbering"""
    # 10000000 → 1.00Cr
    # 9978000 → 99.78L

def format_indian_currency(value):
    """Format as Indian currency"""
    # 10000000 → ₹1.00Cr
```

### 8. Constants (constants.py)

```python
# Valid exchanges
VALID_EXCHANGES = [
    'NSE', 'NFO', 'CDS', 'BSE', 'BFO',
    'BCD', 'MCX', 'NCDEX', 'NSE_INDEX', 'BSE_INDEX'
]

# Valid products
VALID_PRODUCTS = ['CNC', 'NRML', 'MIS']

# Valid price types
VALID_PRICE_TYPES = ['MARKET', 'LIMIT', 'SL', 'SLM']

# Valid actions
VALID_ACTIONS = ['BUY', 'SELL']

# Required fields for orders
REQUIRED_ORDER_FIELDS = [
    'apikey', 'strategy', 'symbol',
    'exchange', 'action', 'quantity'
]
```

### 9. Environment Validation (env_check.py)

```python
def load_and_check_env_variables():
    """Validate .env configuration"""
    # Checks:
    # - Required variables present
    # - Valid formats (rate limits, ports)
    # - Version compatibility
    # - Broker API key formats
```

### 10. Latency Monitor (latency_monitor.py)

```python
class LatencyTracker:
    """Track API latency at multiple stages"""

    def mark_validation_start(self):
        pass

    def mark_broker_start(self):
        pass

    def get_metrics(self):
        return {
            'validation_ms': ...,
            'rtt_ms': ...,
            'total_ms': ...
        }

@track_latency('placeorder')
def api_endpoint():
    """Decorator for latency tracking"""
```

### 11. Plugin Loader (plugin_loader.py)

```python
def load_broker_auth_functions(broker_directory):
    """Dynamically load broker modules"""
    for broker in os.listdir(broker_directory):
        module = import_module(f'broker.{broker}.api.auth_api')
        yield broker, module
```

### 12. Ngrok Manager (ngrok_manager.py)

```python
def start_ngrok_tunnel(port):
    """Start ngrok tunnel"""
    # Kill existing processes
    # Set auth token
    # Connect with optional custom domain

def get_ngrok_url():
    """Get current ngrok URL"""

def cleanup_ngrok():
    """Gracefully disconnect tunnel"""
```

### 13. Email Utilities (email_utils.py)

```python
def send_test_email(recipient_email, sender_name):
    """Send test email for SMTP verification"""
    # Modern HTML template
    # Returns success/error with details
```

### 14. API Analyzer (api_analyzer.py)

```python
def generate_order_id():
    """Generate sequential order ID"""
    # Format: YYMMDDXXXXX

def validate_symbol(symbol, exchange):
    """Check symbol exists in database"""

def analyze_api_request(order_data):
    """Validate API request before processing"""
```

## Usage Examples

### Using Logger

```python
from utils.logging import get_logger

logger = get_logger(__name__)

logger.info("Order placed successfully")
logger.error("Broker connection failed")
logger.debug("Request data: %s", data)
```

### Using Session Decorator

```python
from utils.session import check_session_validity

@bp.route('/dashboard')
@check_session_validity
def dashboard():
    return render_template('dashboard.html')
```

### Using HTTP Client

```python
from utils.httpx_client import get_httpx_client

client = get_httpx_client()
response = client.post(url, json=data)
```

### Using Constants

```python
from utils.constants import VALID_EXCHANGES, VALID_ACTIONS

def validate_order(data):
    if data['exchange'] not in VALID_EXCHANGES:
        return False, "Invalid exchange"
    if data['action'].upper() not in VALID_ACTIONS:
        return False, "Invalid action"
    return True, "Valid"
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `auth_utils.py` | Authentication helpers |
| `session.py` | Session management |
| `logging.py` | Logging configuration |
| `httpx_client.py` | HTTP client |
| `constants.py` | Order constants |
| `config.py` | Config helpers |
| `ip_helper.py` | IP resolution |
| `latency_monitor.py` | Performance tracking |
