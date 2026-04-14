# 24 - Browser Security

## Overview

OpenAlgo implements browser-side security measures including session management, CSRF protection, secure cookies, and content security policies.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                       Browser Security Architecture                          │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           Security Layers                                    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 1: Session Security                                           │   │
│  │  - Session-based authentication                                      │   │
│  │  - Auto-expiry at 3 AM IST (configurable)                           │   │
│  │  - Token revocation on logout                                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 2: Cookie Security                                            │   │
│  │  - Secure flag (HTTPS only)                                          │   │
│  │  - HttpOnly flag (no JS access)                                      │   │
│  │  - SameSite=Lax (CSRF protection)                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 3: Authentication Flow                                        │   │
│  │  - Argon2 password hashing                                           │   │
│  │  - TOTP support for 2FA                                              │   │
│  │  - Rate limiting on login                                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Session Management

### Session Lifecycle

```
┌────────────────────────────────────────────────────────────────┐
│                    Session Lifecycle                            │
│                                                                 │
│  Login → Create Session → Set Expiry → Validate on Request    │
│                                            │                    │
│              ┌─────────────────────────────┴───────┐           │
│              │                                     │            │
│           Valid                               Expired           │
│              │                                     │            │
│              ▼                                     ▼            │
│         Continue                            Redirect to         │
│         Request                             Login Page          │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### Session Expiry Configuration

```bash
# .env
SESSION_EXPIRY_TIME=03:00  # 3 AM IST daily expiry
```

### Session Validation

```python
from utils.session import check_session_validity

@bp.route('/dashboard')
@check_session_validity
def dashboard():
    # Only accessible with valid session
    return render_template('dashboard.html')
```

## Cookie Security

### Secure Cookie Settings

```python
# Flask session configuration
app.config.update(
    SESSION_COOKIE_SECURE=True,      # HTTPS only
    SESSION_COOKIE_HTTPONLY=True,    # No JavaScript access
    SESSION_COOKIE_SAMESITE='Lax',   # CSRF protection
    SESSION_COOKIE_NAME='openalgo_session',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24)
)
```

### Cookie Flags Explained

| Flag | Purpose |
|------|---------|
| Secure | Only sent over HTTPS |
| HttpOnly | Cannot be read by JavaScript |
| SameSite=Lax | Prevents CSRF in most cases |

## Password Security

### Argon2 Hashing

```python
from argon2 import PasswordHasher

ph = PasswordHasher()

def hash_password(password):
    """Hash password with Argon2"""
    peppered = password + APP_KEY[:32]
    return ph.hash(peppered)

def verify_password(password, hash):
    """Verify password against hash"""
    peppered = password + APP_KEY[:32]
    try:
        ph.verify(hash, peppered)
        return True
    except:
        return False
```

### Password Requirements

```python
def validate_password_strength(password):
    """Check password meets requirements"""
    if len(password) < 8:
        return False, "Minimum 8 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Need uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Need lowercase letter"
    if not re.search(r'[0-9]', password):
        return False, "Need number"
    if not re.search(r'[!@#$%^&*]', password):
        return False, "Need special character"
    return True, "Valid"
```

## Login Rate Limiting

### Configuration

```bash
# .env
LOGIN_RATE_LIMIT_MIN=5 per minute
LOGIN_RATE_LIMIT_HOUR=25 per hour
```

### Implementation

```python
from flask_limiter import Limiter

limiter = Limiter(key_func=get_real_ip)

@bp.route('/auth/login', methods=['POST'])
@limiter.limit(get_login_rate_limit_min)
@limiter.limit(get_login_rate_limit_hour)
def login():
    # Rate-limited login
    pass
```

## TOTP Two-Factor Authentication

### Setup Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    2FA Setup Flow                                │
│                                                                  │
│  1. User enables 2FA in settings                                │
│  2. Generate TOTP secret                                        │
│  3. Display QR code for authenticator app                       │
│  4. User enters code to verify                                  │
│  5. Store encrypted secret in database                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### TOTP Validation

```python
import pyotp

def verify_totp(secret, code):
    """Verify TOTP code"""
    totp = pyotp.TOTP(secret)
    return totp.verify(code)
```

## Token Revocation

### On Logout

```python
def revoke_user_tokens():
    """Revoke all tokens on logout"""
    # Clear session
    session.clear()

    # Revoke auth tokens in database
    Auth.query.filter_by(
        name=current_user
    ).update({'is_revoked': True})

    # Clear caches
    clear_auth_cache(current_user)
```

### On Session Expiry

```python
@check_session_validity
def protected_route():
    """Automatically revokes tokens if session expired"""
    pass
```

## React Frontend Security

### API Key Handling

```typescript
// Never expose API key in browser
// Use session-based auth for web UI
// API keys only for external integrations

// Secure API call
const response = await fetch('/api/v1/positions', {
    method: 'POST',
    credentials: 'include',  // Send session cookie
    headers: {
        'Content-Type': 'application/json'
    }
});
```

### AJAX Request Detection

```python
def is_ajax_request():
    """Detect React/AJAX requests"""
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        'application/json' in request.headers.get('Accept', '')
    )
```

## Security Headers

### Recommended Headers

```python
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response
```

## Session Storage

### What's Stored

```python
# Session data (server-side)
session['logged_in'] = True
session['user'] = username
session['login_time'] = datetime.now(IST)
session['login_time_ist'] = formatted_ist_time
```

### What's NOT Stored

- Passwords (only hashes in DB)
- API keys in session (encrypted in DB)
- Auth tokens in session (encrypted in DB)

## Credential Masking

### Display Masking

```python
def mask_api_credential(credential, show_chars=4):
    """Mask credentials for safe display"""
    if len(credential) <= show_chars * 2:
        return '*' * len(credential)
    return credential[:show_chars] + '***' + credential[-show_chars:]

# Example: "abc123def456" → "abc1***f456"
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `utils/session.py` | Session management |
| `utils/auth_utils.py` | Auth utilities |
| `database/user_db.py` | User model |
| `blueprints/auth.py` | Auth routes |
| `frontend/src/api/` | Secure API calls |
