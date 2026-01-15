# Authentication & Security Platform

OpenAlgo implements a multi-layered security architecture with Argon2 password hashing, Fernet token encryption, intelligent API key caching, and session management with IST timezone awareness.

## Security Architecture Overview

```
+---------------------------------------------------------------------+
|                         Security Layers                              |
+---------------------------------------------------------------------+
|  Layer 1: Password Security (Argon2 + Pepper)                       |
|  Layer 2: Token Encryption (Fernet AES-128)                         |
|  Layer 3: API Key Authentication (SHA-256 + Intelligent Cache)      |
|  Layer 4: Session Management (IST 3:00 AM Expiry)                   |
|  Layer 5: Rate Limiting (10 orders/sec, 50 API calls/sec)          |
+---------------------------------------------------------------------+
```

## Password Security

### Argon2 Implementation

OpenAlgo uses Argon2id (winner of the Password Hashing Competition) with an additional pepper for defense-in-depth:

```python
# services/auth_service.py
import argon2
from argon2 import PasswordHasher

# Argon2 configuration
ph = PasswordHasher(
    time_cost=3,          # Number of iterations
    memory_cost=65536,    # 64 MB memory usage
    parallelism=4,        # Parallel threads
    hash_len=32,          # Output hash length
    salt_len=16           # Salt length
)

def hash_password(password: str) -> str:
    """Hash password with Argon2 and pepper"""
    pepper = os.getenv('API_KEY_PEPPER', '')
    peppered_password = password + pepper
    return ph.hash(peppered_password)

def verify_password(password: str, hash: str) -> bool:
    """Verify password against stored hash"""
    pepper = os.getenv('API_KEY_PEPPER', '')
    peppered_password = password + pepper

    try:
        ph.verify(hash, peppered_password)

        # Check if rehash needed (params changed)
        if ph.check_needs_rehash(hash):
            return 'NEEDS_REHASH'
        return True
    except argon2.exceptions.VerifyMismatchError:
        return False
    except argon2.exceptions.InvalidHash:
        return False
```

### Password Requirements

```python
def validate_password_strength(password: str) -> tuple[bool, str]:
    """Enforce password complexity requirements"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters"

    if not re.search(r'[A-Z]', password):
        return False, "Password must contain uppercase letter"

    if not re.search(r'[a-z]', password):
        return False, "Password must contain lowercase letter"

    if not re.search(r'\d', password):
        return False, "Password must contain a digit"

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain special character"

    return True, "Password meets requirements"
```

## Token Encryption

### Fernet Implementation

Broker tokens are encrypted at rest using Fernet (AES-128-CBC with HMAC-SHA256):

```python
# services/encryption_service.py
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

def derive_encryption_key(secret: str, salt: bytes = None) -> tuple[bytes, bytes]:
    """Derive Fernet key from secret using PBKDF2"""
    if salt is None:
        salt = os.urandom(16)

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,  # OWASP recommended minimum
    )

    key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    return key, salt

def get_fernet_instance() -> Fernet:
    """Get Fernet instance with derived key"""
    secret = os.getenv('FERNET_SECRET_KEY')
    salt = base64.b64decode(os.getenv('FERNET_SALT'))
    key, _ = derive_encryption_key(secret, salt)
    return Fernet(key)

def encrypt_token(token: str) -> str:
    """Encrypt broker token for database storage"""
    if not token:
        return None
    fernet = get_fernet_instance()
    return fernet.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Decrypt broker token from database"""
    if not encrypted_token:
        return None
    fernet = get_fernet_instance()
    return fernet.decrypt(encrypted_token.encode()).decode()
```

### Token Storage

```python
# database/auth_db.py
def store_broker_tokens(user_id: int, broker: str, tokens: dict):
    """Store encrypted broker tokens"""
    encrypted_tokens = {
        'access_token': encrypt_token(tokens.get('access_token')),
        'refresh_token': encrypt_token(tokens.get('refresh_token')),
        'feed_token': encrypt_token(tokens.get('feed_token')),
    }

    with get_db_session() as session:
        auth = session.query(AuthToken).filter(
            AuthToken.user_id == user_id,
            AuthToken.broker == broker
        ).first()

        if auth:
            for key, value in encrypted_tokens.items():
                setattr(auth, key, value)
            auth.updated_at = datetime.utcnow()
        else:
            auth = AuthToken(
                user_id=user_id,
                broker=broker,
                **encrypted_tokens
            )
            session.add(auth)

def get_broker_tokens(user_id: int, broker: str) -> dict:
    """Retrieve and decrypt broker tokens"""
    with get_db_session() as session:
        auth = session.query(AuthToken).filter(
            AuthToken.user_id == user_id,
            AuthToken.broker == broker
        ).first()

        if not auth:
            return None

        return {
            'access_token': decrypt_token(auth.access_token),
            'refresh_token': decrypt_token(auth.refresh_token),
            'feed_token': decrypt_token(auth.feed_token),
        }
```

## API Key Authentication

### Key Generation

```python
# services/apikey_service.py
import secrets
import hashlib

def generate_api_key() -> tuple[str, str]:
    """Generate new API key and its hash"""
    # Generate 32-byte random key
    raw_key = secrets.token_urlsafe(32)

    # Create hash for storage (never store raw key)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    return raw_key, key_hash

def create_api_key(user_id: int, name: str = None) -> str:
    """Create and store new API key for user"""
    raw_key, key_hash = generate_api_key()

    with get_db_session() as session:
        api_key = ApiKey(
            user_id=user_id,
            api_key=key_hash,  # Store hash only
            name=name or f"Key-{datetime.now().strftime('%Y%m%d')}",
            created_at=datetime.utcnow(),
            is_active=True
        )
        session.add(api_key)

    # Return raw key to user (only time it's visible)
    return raw_key
```

### Intelligent Caching System

OpenAlgo implements a two-tier cache to optimize authentication while preventing brute force attacks:

```python
# services/auth_cache.py
from cachetools import TTLCache

# Valid API key cache: 10 hour TTL
# Reduces database queries for legitimate requests
api_key_cache = TTLCache(maxsize=1000, ttl=36000)

# Invalid API key cache: 5 minute TTL
# Blocks repeated invalid key attempts without DB hit
invalid_key_cache = TTLCache(maxsize=10000, ttl=300)

def verify_api_key(api_key: str) -> dict | None:
    """Verify API key with intelligent caching"""

    # 1. Check invalid cache first (fast rejection)
    if api_key in invalid_key_cache:
        return None

    # 2. Check valid cache
    if api_key in api_key_cache:
        return api_key_cache[api_key]

    # 3. Database lookup
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    with get_db_session() as session:
        api_key_record = session.query(ApiKey).filter(
            ApiKey.api_key == key_hash,
            ApiKey.is_active == True
        ).first()

        if api_key_record:
            # Cache valid key with user data
            user_data = {
                'user_id': api_key_record.user_id,
                'key_id': api_key_record.id,
                'broker': get_user_broker(api_key_record.user_id)
            }
            api_key_cache[api_key] = user_data

            # Update last used timestamp
            api_key_record.last_used = datetime.utcnow()

            return user_data
        else:
            # Cache invalid key to prevent repeated lookups
            invalid_key_cache[api_key] = True
            return None
```

### Cache Flow Diagram

```
API Request with Key
        |
        v
+-------------------+
| Invalid Cache     |---- Found ----> Return 401 (no DB hit)
| Check (5min TTL)  |
+--------+----------+
         | Not Found
         v
+-------------------+
| Valid Cache       |---- Found ----> Return User Data
| Check (10hr TTL)  |
+--------+----------+
         | Not Found
         v
+-------------------+
| Database Lookup   |
+--------+----------+
         |
    +----+----+
    |         |
  Valid    Invalid
    |         |
    v         v
 Add to    Add to
 Valid     Invalid
 Cache     Cache
```

## Session Management

### IST Timezone Session Expiry

Sessions expire at 3:00 AM IST daily (market session boundary):

```python
# services/session_service.py
import pytz
from datetime import datetime, timedelta

IST = pytz.timezone('Asia/Kolkata')

def get_session_expiry() -> datetime:
    """Calculate session expiry time (3:00 AM IST)"""
    now = datetime.now(IST)

    # Next 3:00 AM IST
    expiry = now.replace(hour=3, minute=0, second=0, microsecond=0)

    if now.hour >= 3:
        # Already past 3 AM, expire tomorrow
        expiry += timedelta(days=1)

    return expiry

def create_session(user_id: int) -> str:
    """Create new user session"""
    session_id = secrets.token_urlsafe(32)
    expiry = get_session_expiry()

    session_data = {
        'user_id': user_id,
        'created_at': datetime.now(IST).isoformat(),
        'expires_at': expiry.isoformat()
    }

    # Store in session cache/database
    session_store[session_id] = session_data

    return session_id

def validate_session(session_id: str) -> dict | None:
    """Validate session and check expiry"""
    session_data = session_store.get(session_id)

    if not session_data:
        return None

    expiry = datetime.fromisoformat(session_data['expires_at'])
    if datetime.now(IST) > expiry:
        # Session expired
        del session_store[session_id]
        return None

    return session_data
```

### Session Token Format

```python
# Flask session configuration
from flask import Flask

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv('FLASK_SECRET_KEY'),
    SESSION_COOKIE_NAME='openalgo_session',
    SESSION_COOKIE_SECURE=True,          # HTTPS only
    SESSION_COOKIE_HTTPONLY=True,        # No JavaScript access
    SESSION_COOKIE_SAMESITE='Lax',       # CSRF protection
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24)
)
```

## Authentication Decorators

### API Key Decorator

```python
# utils/auth_decorators.py
from functools import wraps
from flask import request, jsonify

def require_api_key(f):
    """Decorator to require valid API key"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check header first, then request body
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            api_key = request.json.get('apikey') if request.is_json else None

        if not api_key:
            return jsonify({
                'status': 'error',
                'message': 'API key required'
            }), 401

        user_data = verify_api_key(api_key)
        if not user_data:
            return jsonify({
                'status': 'error',
                'message': 'Invalid API key'
            }), 401

        # Add user data to request context
        request.user_data = user_data
        return f(*args, **kwargs)

    return decorated
```

### Session Decorator

```python
def require_session(f):
    """Decorator to require valid session"""
    @wraps(f)
    def decorated(*args, **kwargs):
        session_id = request.cookies.get('openalgo_session')

        if not session_id:
            return redirect('/login')

        session_data = validate_session(session_id)
        if not session_data:
            return redirect('/login?expired=true')

        request.session_data = session_data
        return f(*args, **kwargs)

    return decorated
```

### Combined Authentication

```python
def require_auth(f):
    """Accept either API key or session authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Try API key first
        api_key = request.headers.get('X-API-Key')
        if api_key:
            user_data = verify_api_key(api_key)
            if user_data:
                request.auth_type = 'api_key'
                request.user_data = user_data
                return f(*args, **kwargs)

        # Try session
        session_id = request.cookies.get('openalgo_session')
        if session_id:
            session_data = validate_session(session_id)
            if session_data:
                request.auth_type = 'session'
                request.user_data = {'user_id': session_data['user_id']}
                return f(*args, **kwargs)

        return jsonify({
            'status': 'error',
            'message': 'Authentication required'
        }), 401

    return decorated
```

## Rate Limiting

### Configuration

```python
# services/rate_limiter.py
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_api_key_or_ip,
    default_limits=["50 per second"],
    storage_uri="memory://"
)

# Endpoint-specific limits
ORDER_LIMIT = "10 per second"
API_LIMIT = "50 per second"
LOGIN_LIMIT = "5 per minute"
```

### Rate Limit Decorators

```python
@app.route('/api/v1/placeorder', methods=['POST'])
@limiter.limit(ORDER_LIMIT)
@require_api_key
def place_order():
    """Place order with rate limiting"""
    pass

@app.route('/login', methods=['POST'])
@limiter.limit(LOGIN_LIMIT)
def login():
    """Login with strict rate limiting"""
    pass
```

### Rate Limit Headers

```python
@app.after_request
def add_rate_limit_headers(response):
    """Add rate limit info to response headers"""
    if hasattr(g, 'rate_limit'):
        response.headers['X-RateLimit-Limit'] = g.rate_limit.limit
        response.headers['X-RateLimit-Remaining'] = g.rate_limit.remaining
        response.headers['X-RateLimit-Reset'] = g.rate_limit.reset
    return response
```

## Broker OAuth Flow

### OAuth Authorization

```python
# blueprints/auth.py
@auth_bp.route('/broker/<broker>/authorize')
@require_session
def broker_authorize(broker):
    """Initiate broker OAuth flow"""
    adapter = get_broker_adapter(broker)

    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state

    auth_url = adapter.get_authorization_url(
        redirect_uri=url_for('auth.broker_callback', broker=broker, _external=True),
        state=state
    )

    return redirect(auth_url)

@auth_bp.route('/broker/<broker>/callback')
@require_session
def broker_callback(broker):
    """Handle broker OAuth callback"""
    # Verify state token
    state = request.args.get('state')
    if state != session.get('oauth_state'):
        return jsonify({'error': 'Invalid state'}), 400

    # Exchange code for tokens
    adapter = get_broker_adapter(broker)
    code = request.args.get('code') or request.args.get('request_token')

    tokens = adapter.exchange_code_for_tokens(code)

    # Store encrypted tokens
    store_broker_tokens(
        user_id=session['user_id'],
        broker=broker,
        tokens=tokens
    )

    return redirect('/dashboard?broker_linked=true')
```

## Security Best Practices

### Environment Variables

```bash
# Required security environment variables
FLASK_SECRET_KEY=<random-64-byte-string>
API_KEY_PEPPER=<random-32-byte-string>
FERNET_SECRET_KEY=<random-32-byte-string>
FERNET_SALT=<base64-encoded-16-byte-salt>

# Generate secure values
python -c "import secrets; print(secrets.token_urlsafe(64))"
python -c "import os, base64; print(base64.b64encode(os.urandom(16)).decode())"
```

### Security Headers

```python
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    return response
```

### Input Validation

```python
def sanitize_input(data: dict, schema: dict) -> dict:
    """Validate and sanitize input data"""
    cleaned = {}

    for field, rules in schema.items():
        value = data.get(field)

        # Required field check
        if rules.get('required') and value is None:
            raise ValidationError(f"{field} is required")

        # Type validation
        expected_type = rules.get('type')
        if value is not None and not isinstance(value, expected_type):
            raise ValidationError(f"{field} must be {expected_type.__name__}")

        # Pattern validation
        if 'pattern' in rules and value:
            if not re.match(rules['pattern'], str(value)):
                raise ValidationError(f"{field} format invalid")

        # Sanitize strings
        if isinstance(value, str):
            value = html.escape(value.strip())

        cleaned[field] = value

    return cleaned
```

## Audit Logging

```python
def log_auth_event(event_type: str, user_id: int = None, **kwargs):
    """Log authentication events for security audit"""
    from database.logs_db import insert_auth_log

    insert_auth_log({
        'event_type': event_type,  # login/logout/api_key_created/failed_login
        'user_id': user_id,
        'ip_address': request.remote_addr,
        'user_agent': request.headers.get('User-Agent'),
        'timestamp': datetime.utcnow(),
        'details': json.dumps(kwargs)
    })
```

## Related Documentation

- [API Layer](./02_api_layer.md) - API authentication endpoints
- [Database Layer](./04_database_layer.md) - Token and key storage
- [Configuration](./07_configuration.md) - Security configuration options
- [Logging System](./10_logging_system.md) - Security audit logs
