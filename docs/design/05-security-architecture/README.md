# 05 - Security Architecture

## Overview

OpenAlgo implements defense-in-depth security with multiple layers protecting the application from various attack vectors. The security architecture covers authentication, authorization, transport security, input validation, and monitoring.

## Security Layers Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Security Architecture                                │
└──────────────────────────────────────────────────────────────────────────────┘

                              Internet
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 1: Transport Security                                                  │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  HTTPS (TLS 1.2+) │ WSS for WebSocket │ Secure Cookies (__Secure-)     │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 2: Network Security                                                    │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  IP Banning (SecurityMiddleware) │ Rate Limiting (Flask-Limiter)       │  │
│  │  404 Tracking (Error404Tracker)  │ Invalid API Key Tracking            │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 3: Browser Security                                                    │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  CSP Headers │ CORS Policy │ Referrer Policy │ Permissions Policy      │  │
│  │  Clickjacking (frame-ancestors) │ XSS Protection                       │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 4: Application Security                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  CSRF Protection │ Session Management │ Password Hashing (Argon2)      │  │
│  │  API Key Hashing │ Token Encryption (Fernet) │ Input Validation        │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 5: Data Security                                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  Encrypted Auth Tokens │ Peppered Hashes │ Secure Key Storage          │  │
│  │  Database Isolation (5 DBs) │ Sensitive Data Redaction                 │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Layer 1: Transport Security

### HTTPS Configuration

```python
# app.py
HOST_SERVER = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')
USE_HTTPS = HOST_SERVER.startswith('https://')

# Dynamic cookie security based on HTTPS
app.config.update(
    SESSION_COOKIE_SECURE=USE_HTTPS,
    WTF_CSRF_COOKIE_SECURE=USE_HTTPS,
)

# Secure cookie prefix for HTTPS
if USE_HTTPS:
    app.config['SESSION_COOKIE_NAME'] = f'__Secure-{session_cookie_name}'
```

### Cookie Security Attributes

| Attribute | Value | Purpose |
|-----------|-------|---------|
| `HttpOnly` | True | Prevents JavaScript access (XSS protection) |
| `SameSite` | Lax | CSRF protection while allowing top-level navigation |
| `Secure` | True (HTTPS) | Cookies only sent over HTTPS |
| `__Secure-` prefix | HTTPS only | Additional browser validation |

## Layer 2: Network Security

### IP Banning System

**Location:** `utils/security_middleware.py`

```python
class SecurityMiddleware:
    """WSGI middleware to check for banned IPs"""

    def __call__(self, environ, start_response):
        client_ip = get_real_ip_from_environ(environ)

        if IPBan.is_ip_banned(client_ip):
            # Return 403 Forbidden for banned IPs
            status = '403 Forbidden'
            headers = [('Content-Type', 'text/plain')]
            start_response(status, headers)
            logger.warning(f"Blocked banned IP: {client_ip}")
            return [b'Access Denied: Your IP has been banned']

        return self.app(environ, start_response)
```

**IP Ban Model:**
```python
# database/traffic_db.py
class IPBan(LogBase):
    __tablename__ = 'ip_bans'

    id = Column(Integer, primary_key=True)
    ip_address = Column(String(50), unique=True, index=True)
    ban_reason = Column(String(200))
    ban_count = Column(Integer, default=1)      # Track repeat offenses
    banned_at = Column(DateTime)
    expires_at = Column(DateTime)               # NULL = permanent
    is_permanent = Column(Boolean, default=False)
    created_by = Column(String(50))             # 'system' or 'manual'

    @staticmethod
    def is_ip_banned(ip_address):
        """Check if IP is currently banned"""
        ban = IPBan.query.filter_by(ip_address=ip_address).first()
        if not ban:
            return False
        if ban.is_permanent:
            return True
        if ban.expires_at and datetime.utcnow() < ban.expires_at:
            return True
        return False
```

### Rate Limiting

**Location:** `limiter.py`

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    strategy="moving-window"
)
```

**Rate Limit Configuration:**

| Endpoint | Limit | Purpose |
|----------|-------|---------|
| `/auth/login` | 5/min, 25/hour | Brute force protection |
| `/{broker}/callback` | 5/min, 25/hour | OAuth abuse prevention |
| `/auth/reset-password` | 15/hour | Password reset spam |
| `/api/v1/*` | Per-endpoint | API abuse prevention |

**Usage Example:**
```python
@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
@limiter.limit("25 per hour")
def login():
    # Login logic
    pass
```

### 404 Error Tracking

Tracks suspicious 404 errors for potential attack detection:

```python
class Error404Tracker(LogBase):
    __tablename__ = 'error_404_tracker'

    id = Column(Integer, primary_key=True)
    ip_address = Column(String(50), index=True)
    requested_path = Column(String(500))
    timestamp = Column(DateTime)
    user_agent = Column(String(500))
    referrer = Column(String(500))
```

## Layer 3: Browser Security

### Content Security Policy (CSP)

**Location:** `csp.py`

```python
def get_csp_config():
    """Get CSP configuration from environment variables"""
    return {
        'default-src': os.getenv('CSP_DEFAULT_SRC', "'self'"),
        'script-src': os.getenv('CSP_SCRIPT_SRC', "'self' https://cdn.socket.io"),
        'style-src': os.getenv('CSP_STYLE_SRC', "'self' 'unsafe-inline'"),
        'img-src': os.getenv('CSP_IMG_SRC', "'self' data:"),
        'connect-src': os.getenv('CSP_CONNECT_SRC', "'self' wss: ws:"),
        'font-src': os.getenv('CSP_FONT_SRC', "'self'"),
        'object-src': os.getenv('CSP_OBJECT_SRC', "'none'"),
        'frame-ancestors': os.getenv('CSP_FRAME_ANCESTORS', "'self'"),
        'form-action': os.getenv('CSP_FORM_ACTION', "'self'"),
        'base-uri': os.getenv('CSP_BASE_URI', "'self'"),
    }

@app.after_request
def add_security_headers(response):
    csp_header = build_csp_header(get_csp_config())
    response.headers['Content-Security-Policy'] = csp_header
    return response
```

**CSP Directives:**

| Directive | Default Value | Purpose |
|-----------|---------------|---------|
| `default-src` | 'self' | Fallback for all resources |
| `script-src` | 'self' https://cdn.socket.io | JavaScript sources |
| `style-src` | 'self' 'unsafe-inline' | CSS sources |
| `connect-src` | 'self' wss: ws: | API and WebSocket connections |
| `img-src` | 'self' data: | Image sources |
| `object-src` | 'none' | Block plugins (Flash, etc.) |
| `frame-ancestors` | 'self' | Clickjacking protection |

### CORS Configuration

**Location:** `cors.py`

```python
def get_cors_config():
    cors_config = {}

    if os.getenv('CORS_ENABLED', 'FALSE').upper() == 'TRUE':
        cors_config['origins'] = os.getenv('CORS_ALLOWED_ORIGINS', '').split(',')
        cors_config['methods'] = os.getenv('CORS_ALLOWED_METHODS', 'GET,POST').split(',')
        cors_config['allow_headers'] = os.getenv('CORS_ALLOWED_HEADERS', '').split(',')
        cors_config['supports_credentials'] = os.getenv('CORS_ALLOW_CREDENTIALS') == 'TRUE'

    return cors_config

cors = CORS(resources={r"/api/*": get_cors_config()})
```

### Additional Security Headers

```python
def get_security_headers():
    return {
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()'
    }
```

## Layer 4: Application Security

### CSRF Protection

**Location:** `app.py`

```python
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect(app)

# CSRF configuration
app.config.update(
    WTF_CSRF_ENABLED=True,
    WTF_CSRF_COOKIE_HTTPONLY=True,
    WTF_CSRF_COOKIE_SAMESITE='Lax',
)
```

**CSRF Token Flow:**
```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  React Client   │────►│ GET /auth/      │────►│ Return CSRF     │
│                 │     │ csrf-token      │     │ Token           │
└────────┬────────┘     └─────────────────┘     └─────────────────┘
         │
         │ Include X-CSRFToken header
         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  POST /api/...  │────►│ CSRF Validation │────►│ Process Request │
│                 │     │                 │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Frontend Implementation:**
```typescript
// api/client.ts
webClient.interceptors.request.use(async (config) => {
  if (['post', 'put', 'delete'].includes(config.method)) {
    const csrfToken = await fetchCSRFToken()
    config.headers['X-CSRFToken'] = csrfToken
  }
  return config
})
```

### Password Security

**Argon2 Hashing with Pepper:**

```python
# database/user_db.py
from argon2 import PasswordHasher

PEPPER = os.getenv('API_KEY_PEPPER')  # Minimum 32 characters

class User:
    def set_password(self, password):
        peppered = f"{password}{PEPPER}"
        self.password_hash = PasswordHasher().hash(peppered)

    def check_password(self, password):
        peppered = f"{password}{PEPPER}"
        try:
            return PasswordHasher().verify(self.password_hash, peppered)
        except:
            return False
```

**Password Requirements:**
```python
def validate_password_strength(password):
    """
    Requirements:
    - Minimum 8 characters
    - At least 1 uppercase letter (A-Z)
    - At least 1 lowercase letter (a-z)
    - At least 1 number (0-9)
    - At least 1 special character (!@#$%^&*)
    """
```

### API Key Security

**Three-Level Verification:**
```
1. Check invalid_api_key_cache (5min TTL) → Fast rejection
2. Check verified_api_key_cache (10hr TTL) → Fast acceptance
3. Database Argon2 verification → Expensive but secure
```

```python
# database/auth_db.py
def verify_api_key(api_key: str) -> Optional[str]:
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # Level 1: Invalid cache (fast rejection)
    if key_hash in invalid_api_key_cache:
        return None

    # Level 2: Valid cache (fast acceptance)
    if key_hash in verified_api_key_cache:
        return verified_api_key_cache[key_hash]

    # Level 3: Database verification
    user_id = db_verify_api_key_argon2(api_key)

    if user_id:
        verified_api_key_cache[key_hash] = user_id
    else:
        invalid_api_key_cache[key_hash] = True

    return user_id
```

### Session Security

```python
# app.py
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,    # No JavaScript access
    SESSION_COOKIE_SAMESITE='Lax',   # CSRF protection
    SESSION_COOKIE_SECURE=USE_HTTPS, # HTTPS only
)

# Session expiry at 3:30 AM IST
app.config['PERMANENT_SESSION_LIFETIME'] = get_session_expiry_time()
session.permanent = True
```

## Layer 5: Data Security

### Auth Token Encryption

**Fernet Encryption for Broker Tokens:**

```python
# database/auth_db.py
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def get_encryption_key():
    """Generate Fernet key from pepper"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'openalgo_static_salt',
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(PEPPER.encode()))
    return Fernet(key)

fernet = get_encryption_key()

def encrypt_token(token):
    return fernet.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token):
    return fernet.decrypt(encrypted_token.encode()).decode()
```

### Database Isolation

Five separate databases prevent cross-contamination:

| Database | Contents | Sensitivity |
|----------|----------|-------------|
| `openalgo.db` | Users, auth tokens, orders | High |
| `logs.db` | Traffic logs, IP bans | Medium |
| `latency.db` | Performance metrics | Low |
| `sandbox.db` | Paper trading data | Medium |
| `historify.duckdb` | Historical market data | Low |

### Sensitive Data Protection

**Log Redaction:**
```python
# Sensitive fields never logged in plaintext
SENSITIVE_FIELDS = ['password', 'api_key', 'auth_token', 'access_token']

def redact_sensitive_data(data):
    for field in SENSITIVE_FIELDS:
        if field in data:
            data[field] = '***REDACTED***'
    return data
```

## Security Configuration Summary

### Environment Variables

```bash
# Required Security Keys
APP_KEY=<32+ character secret key>
API_KEY_PEPPER=<32+ character pepper>

# HTTPS Configuration
HOST_SERVER=https://your-domain.com

# Session
SESSION_EXPIRY_TIME=03:00
SESSION_COOKIE_NAME=session

# CSRF
CSRF_ENABLED=TRUE

# CSP
CSP_ENABLED=TRUE
CSP_DEFAULT_SRC='self'
CSP_SCRIPT_SRC='self' https://cdn.socket.io

# CORS
CORS_ENABLED=FALSE
CORS_ALLOWED_ORIGINS=https://your-domain.com

# Rate Limiting
LOGIN_RATE_LIMIT_MIN=5 per minute
LOGIN_RATE_LIMIT_HOUR=25 per hour
```

## Security Checklist

### Startup Validation

```python
# database/auth_db.py
# Fails fast if security requirements not met

if not os.getenv('API_KEY_PEPPER'):
    raise RuntimeError("CRITICAL: API_KEY_PEPPER not set")

if len(os.getenv('API_KEY_PEPPER')) < 32:
    raise RuntimeError("CRITICAL: API_KEY_PEPPER must be at least 32 characters")
```

### Security Best Practices

1. **Always use HTTPS in production**
2. **Never log sensitive data (passwords, tokens)**
3. **Use rate limiting on all authentication endpoints**
4. **Implement IP banning for abusive IPs**
5. **Keep API_KEY_PEPPER secure and backed up**
6. **Monitor 404 errors for attack detection**
7. **Use secure cookie attributes**
8. **Implement proper CSRF protection**

## Key Files Reference

| File | Purpose |
|------|---------|
| `app.py` | Security initialization |
| `csp.py` | Content Security Policy |
| `cors.py` | CORS configuration |
| `limiter.py` | Rate limiting |
| `utils/security_middleware.py` | IP banning middleware |
| `database/auth_db.py` | Password/API key hashing |
| `database/traffic_db.py` | IP ban model |
