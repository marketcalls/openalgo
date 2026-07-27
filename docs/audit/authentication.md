# Authentication & Session Management

## Overview

OpenAlgo implements authentication to protect access to your personal trading dashboard and prevent unauthorized order placement.

**Risk Level**: Medium (for single-user context)
**Status**: Strong

## Why Authentication Matters (Single-User)

Even as a single-user application, authentication protects:

1. **Unauthorized access** - If someone gains access to your machine/network
2. **Webhook abuse** - External services need valid API keys
3. **Accidental exposure** - If ngrok URL is accidentally shared

## Password Security

### Password Hashing

**Location**: `database/auth_db.py`, `database/user_db.py`

OpenAlgo uses Argon2id - the winner of the Password Hashing Competition and OWASP's top recommendation.

```python
from argon2 import PasswordHasher

ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64MB
    parallelism=4,
    hash_len=32,
    salt_len=16
)
```

**What This Means**:
- Your password cannot be recovered from the database
- Even if someone copies your database, they can't login
- Brute-force attacks are computationally expensive

### Password Pepper

An additional secret (`API_KEY_PEPPER` from `.env`) is added to passwords before hashing:

```python
def hash_password(password):
    pepper = os.environ.get('API_KEY_PEPPER', '')
    return ph.hash(password + pepper)
```

**Benefit**: Even identical passwords produce different hashes across installations.

## Two-Factor Authentication (2FA)

### TOTP Implementation

**Location**: `database/auth_db.py`, `blueprints/auth.py`

OpenAlgo supports time-based one-time passwords (TOTP) compatible with:
- Google Authenticator
- Authy
- Microsoft Authenticator
- Any TOTP app

**When to Enable 2FA**:
- Recommended if accessing remotely
- Recommended if running on VPS/cloud
- Optional for local-only use

### How It Works

1. Enable 2FA in settings
2. Scan QR code with authenticator app
3. Enter 6-digit code at login
4. Code changes every 30 seconds

## Session Management

### Session Security

**Configuration** (`app.py`):

| Setting | Value | Purpose |
|---------|-------|---------|
| `SESSION_COOKIE_HTTPONLY` | True | JavaScript can't access cookie |
| `SESSION_COOKIE_SAMESITE` | Lax | Prevents cross-site request attacks |
| `SESSION_COOKIE_SECURE` | True (prod) | Cookie only sent over HTTPS |
| `PERMANENT_SESSION_LIFETIME` | 24 hours | Auto-logout after inactivity |

### Session Storage

- Sessions stored server-side (filesystem)
- Only session ID in browser cookie
- Session destroyed on logout

### For Single-User

Session management is simpler since:
- No need to isolate sessions between users
- No session enumeration concerns
- No concurrent session limits needed

## API Key Authentication

### Purpose

API keys authenticate external requests:
- TradingView webhooks
- Amibroker signals
- Python scripts
- Custom integrations

### How API Keys Are Protected

**Location**: `database/apikey_db.py`

```
User creates API key
        ↓
Key shown once (copy it!)
        ↓
Key hashed with SHA256 + pepper → stored for authentication
Key encrypted with Fernet → stored for broker operations
        ↓
Original key never stored in plaintext
```

**Verification Process**:
1. Webhook includes API key
2. Server hashes the provided key
3. Compares hash against stored hash
4. If match, request is authenticated

### Best Practices

1. **Keep API key secret** - Treat like a password
2. **Regenerate if compromised** - Creates new key, invalidates old
3. **Use different keys** - If integrating multiple services (future feature)

## Login Security

### Brute Force Protection

**Location**: `blueprints/auth.py`, `utils/traffic.py`

- Failed login attempts tracked
- IP-based rate limiting
- Automatic lockout after repeated failures

### Login Flow

```
Enter username/password
        ↓
Validate credentials (Argon2)
        ↓
If 2FA enabled → Enter TOTP code
        ↓
Create session
        ↓
Redirect to dashboard
```

## Recommendations for Single-User

### Essential

1. **Use a strong password**
   - At least 12 characters
   - Mix of letters, numbers, symbols
   - Not used elsewhere

2. **Keep `.env` secure**
   - Contains `APP_KEY` and `API_KEY_PEPPER`
   - Don't commit to git (already in `.gitignore`)
   - Back up securely

### If Exposing Externally

3. **Enable 2FA**
   - Adds second layer of protection
   - Mitigates password compromise

4. **Use HTTPS**
   - Prevents password interception
   - Required for secure cookies

### Optional Improvements

5. **Change default credentials**
   - If using any default setup values

6. **Review session timeout**
   - Adjust based on your usage pattern
   - Shorter timeout = more secure but less convenient

## Security Checklist

| Item | Status | Action |
|------|--------|--------|
| Password hashing | Done | Argon2id implemented |
| Password pepper | Done | From environment |
| 2FA available | Done | Enable in settings |
| Session security | Done | HttpOnly, SameSite |
| API key hashing | Done | SHA256 + pepper |
| Brute force protection | Done | Rate limiting |

## What You Don't Need to Worry About

As a single-user app:

- **User enumeration** - Only one user exists
- **Privilege escalation** - No role hierarchy
- **Session fixation attacks** - No other users to attack
- **Account takeover of others** - You're the only account

---

**Back to**: [Security Audit Overview](./README.md)
