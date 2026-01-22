# XSS & CSRF Protection Assessment

## Overview

This assessment covers protection against Cross-Site Scripting (XSS) and Cross-Site Request Forgery (CSRF) attacks.

**Risk Level**: Low
**Status**: Good (Security headers auto-configured by install.sh)

## What `install.sh` Configures

When deploying via `install.sh`, Nginx is configured with security headers:

```nginx
# Automatically added by install.sh
add_header X-Frame-Options DENY;
add_header X-Content-Type-Options nosniff;
add_header X-XSS-Protection "1; mode=block";
add_header Strict-Transport-Security "max-age=63072000" always;
```

### Header Explanations

| Header | Value | Protection |
|--------|-------|------------|
| X-Frame-Options | DENY | Prevents clickjacking (embedding in iframes) |
| X-Content-Type-Options | nosniff | Prevents MIME-type sniffing attacks |
| X-XSS-Protection | 1; mode=block | Browser XSS filter (legacy browsers) |
| Strict-Transport-Security | max-age=63072000 | Forces HTTPS for 2 years |

## CSRF Protection

### Implementation

**Location**: `app.py`, `extensions.py`

```python
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()
csrf.init_app(app)
```

**Status**: Enabled globally for all forms

### How It Works

1. Server generates CSRF token per session
2. Token included in HTML forms:
   ```html
   <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
   ```
3. Token validated on form submission
4. Invalid tokens rejected with 400 error

### API Endpoints

API endpoints (`/api/v1/*`) are exempt from CSRF because:
- Use API key authentication instead
- Called by external services (TradingView, scripts)
- Not submitted via browser forms

**This is secure** - API key provides equivalent protection.

### SameSite Cookies

```python
SESSION_COOKIE_SAMESITE = 'Lax'
```

Browser won't send session cookies on cross-site POST requests.

## XSS Protection

### Template Auto-Escaping

**Jinja2** (Flask templates):
```python
# Auto-escaping enabled by default
{{ user_input }}  # HTML entities escaped automatically
```

**React** (Frontend):
```jsx
// React escapes by default
return <div>{userInput}</div>;  // Safe from XSS
```

### Content Security Policy

**Location**: `csp.py`

```python
CSP_POLICY = {
    'default-src': ["'self'"],
    'script-src': ["'self'", "'unsafe-inline'"],
    'style-src': ["'self'", "'unsafe-inline'"],
    'img-src': ["'self'", "data:", "https:"],
    'connect-src': ["'self'", "ws:", "wss:"],
}
```

**Protections**:
- Scripts only from same origin
- No external script loading
- WebSocket connections controlled

### The `unsafe-inline` Note

CSP includes `'unsafe-inline'` for scripts:
- Required for some UI functionality
- Risk is minimal for single-user
- Would need existing XSS to exploit
- No untrusted user content displayed

## Security Headers Verification

After installation, verify headers are working:

```bash
curl -I https://yourdomain.com
```

Expected output includes:
```
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=63072000
```

## Attack Scenarios (Mitigated)

### Scenario 1: Clickjacking

**Attack**: Embed OpenAlgo in hidden iframe, trick user into clicking
**Protection**: `X-Frame-Options: DENY` - Browser refuses to render in iframe

### Scenario 2: XSS via Input

**Attack**: Inject `<script>` tag in form field
**Protection**: Jinja2/React auto-escaping converts to `&lt;script&gt;`

### Scenario 3: CSRF Order Placement

**Attack**: Malicious site submits order form
**Protection**: CSRF token required (missing from malicious request)

### Scenario 4: Malicious Webhook

**Attack**: Send crafted webhook without API key
**Protection**: API key validation rejects request

## Security Checklist

### Auto-Configured (install.sh)

- [x] X-Frame-Options header
- [x] X-Content-Type-Options header
- [x] Strict-Transport-Security (HSTS)
- [x] X-XSS-Protection header

### Built into OpenAlgo

- [x] CSRF protection on forms
- [x] Template auto-escaping
- [x] Content Security Policy
- [x] API key for webhooks
- [x] SameSite cookies

### Your Responsibility

- [ ] Don't disable security features
- [ ] Keep OpenAlgo updated

## Single-User Context

These protections exceed what's strictly necessary for single-user, but provide defense in depth:

| Attack Type | Multi-User Risk | Single-User Risk |
|-------------|-----------------|------------------|
| XSS stealing data | Steal other users' data | Only your data |
| CSRF actions | Act as another user | You're the only user |
| Clickjacking | Trick any user | Only you could be tricked |

Protection is still valuable because:
- Malicious websites could target you specifically
- Browser extensions could exploit vulnerabilities
- Defense in depth is good practice

## Summary

**Protection Status**: Strong

**Automatic (install.sh)**:
- X-Frame-Options: DENY
- X-Content-Type-Options: nosniff
- Strict-Transport-Security
- X-XSS-Protection

**Built-in (OpenAlgo code)**:
- CSRF tokens on forms
- Auto-escaping templates
- Content Security Policy
- API key authentication

**No action required** - security is configured automatically.

---

**Back to**: [Security Audit Overview](./README.md)
