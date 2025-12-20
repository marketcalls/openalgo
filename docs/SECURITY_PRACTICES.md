# OpenAlgo Security Practices Report

**Version:** 1.0
**Date:** December 2025
**Overall Security Rating:** 7.5 / 10

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Password & Credential Security](#1-password--credential-security)
3. [API Key Security](#2-api-key-security)
4. [Encryption](#3-encryption)
5. [Session Security](#4-session-security)
6. [CSRF Protection](#5-csrf-protection)
7. [Rate Limiting](#6-rate-limiting)
8. [Input Validation](#7-input-validation)
9. [SQL Injection Prevention](#8-sql-injection-prevention)
10. [XSS Prevention](#9-xss-prevention-content-security-policy)
11. [IP Security & Banning](#10-ip-security--banning)
12. [Logging & Audit Trails](#11-logging--audit-trails)
13. [Docker Security](#12-docker-security)
14. [CORS Configuration](#13-cors-configuration)
15. [Security Headers](#14-security-headers)
16. [Multi-Factor Authentication](#15-multi-factor-authentication)
17. [Vulnerability Management](#16-vulnerability-management)
18. [Security Libraries](#17-security-libraries)

---

## Executive Summary

OpenAlgo implements **enterprise-grade security** with a defense-in-depth approach across all layers of the application. This document details all strong security practices currently implemented in the codebase.

### Key Security Highlights

| Category | Implementation |
|----------|----------------|
| Password Hashing | Argon2 with pepper |
| Token Encryption | Fernet (AES-128-CBC) |
| Session Protection | HTTPOnly, SameSite, Secure cookies |
| API Security | Dual-storage (hashed + encrypted) |
| Input Validation | Marshmallow schema validation |
| SQL Prevention | SQLAlchemy ORM (parameterized queries) |
| XSS Prevention | Content Security Policy headers |
| Rate Limiting | Flask-Limiter with configurable limits |
| Threat Detection | IP banning, 404 tracking, invalid key tracking |

---

## 1. Password & Credential Security

### Argon2 Password Hashing

OpenAlgo uses Argon2, the winner of the Password Hashing Competition, for all password storage.

| Practice | Implementation | Location |
|----------|----------------|----------|
| Argon2 Hashing | Memory-hard hashing algorithm | `database/user_db.py:74-77` |
| Mandatory Pepper | 32+ character pepper required at startup | `database/auth_db.py:27-41` |
| Auto-Rehashing | Passwords rehashed on verification if needed | `database/user_db.py:84-87` |

### Password Strength Requirements

All passwords must meet the following criteria:

```
- Minimum 8 characters
- At least 1 uppercase letter (A-Z)
- At least 1 lowercase letter (a-z)
- At least 1 number (0-9)
- At least 1 special character (!@#$%^&*)
```

**Location:** `utils/auth_utils.py:13-48`

### Credential Masking

Sensitive credentials are masked in UI displays showing only the first 4 characters.

**Location:** `utils/auth_utils.py:50-64`

---

## 2. API Key Security

### Dual-Storage Approach

API keys are stored using a dual approach for maximum security:

| Storage Method | Purpose | Location |
|----------------|---------|----------|
| Argon2 Hash | Verification without exposing key | `database/auth_db.py:334-336` |
| Fernet Encrypted | Secure retrieval when needed | `database/auth_db.py:339` |

### Intelligent Caching

| Key Type | Cache TTL | Rationale |
|----------|-----------|-----------|
| Valid Keys | 10 hours | Reduce database load |
| Invalid Keys | 5 minutes | Prevent cache poisoning |

**Location:** `database/auth_db.py:105-106`

### Security Features

- **Cache Invalidation:** Automatic invalidation on key regeneration (`database/auth_db.py:354-355`)
- **Invalid Key Tracking:** Per-IP tracking of failed attempts (`database/traffic_db.py:349-456`)
- **SHA256 Cache Keys:** API keys never stored as cache keys in plaintext (`database/auth_db.py:397`)

---

## 3. Encryption

### Fernet Token Encryption

All sensitive tokens are encrypted using Fernet (symmetric authenticated encryption).

| Component | Implementation | Location |
|-----------|----------------|----------|
| Algorithm | Fernet (AES-128-CBC + HMAC) | `database/auth_db.py:43-56` |
| Key Derivation | PBKDF2-HMAC-SHA256 | `database/auth_db.py:46-50` |
| Iterations | 100,000 | `database/auth_db.py:50` |

### Encrypted Data

- Broker authentication tokens
- API keys (encrypted copy for retrieval)
- SMTP passwords (if email reset enabled)

---

## 4. Session Security

### Cookie Configuration

| Setting | Value | Location |
|---------|-------|----------|
| HTTPOnly | `True` | `app.py:142` |
| SameSite | `Lax` | `app.py:143` |
| Secure | HTTPS-conditional | `app.py:144` |
| Name Prefix | `__Secure-` (HTTPS) | `app.py:150-151` |

### Session Expiry

- **Daily Expiry:** Configurable auto-expiry time (default 3:00 AM IST)
- **Validation Decorator:** `check_session_validity()` validates each request
- **Token Revocation:** Automatic on session expiry

**Location:** `utils/session.py:68-118`

---

## 5. CSRF Protection

### Flask-WTF Integration

| Setting | Value | Location |
|---------|-------|----------|
| CSRF Enabled | `True` | `app.py:154-155` |
| Cookie HTTPOnly | `True` | `app.py:160` |
| Cookie SameSite | `Lax` | `app.py:161` |
| Cookie Secure | HTTPS-conditional | `app.py:162` |

### API Exemption

REST API endpoints (`/api/v1/*`) are exempt from CSRF as they use API key authentication instead.

**Location:** `app.py:184`

---

## 6. Rate Limiting

### Configured Limits

| Endpoint | Limit | Location |
|----------|-------|----------|
| Login | 5/minute, 25/hour | `blueprints/auth.py:30-31` |
| Password Reset | 15/hour | `blueprints/auth.py:84` |
| API Requests | 50/second | `.sample.env:82` |
| Order Placement | 10/second | `.sample.env:84` |
| Smart Orders | 2/second | `.sample.env:86` |
| Webhooks | 100/minute | `.sample.env:88` |
| WebSocket | 100/minute | `.sample.env:90` |

### Implementation

- **Library:** Flask-Limiter with moving-window strategy
- **Storage:** Memory-based (configurable)
- **Per-IP:** Rate limits applied per client IP

**Location:** `limiter.py`

---

## 7. Input Validation

### Marshmallow Schema Validation

All API endpoints use Marshmallow schemas for strict input validation.

| Schema | Validations | Location |
|--------|-------------|----------|
| OrderSchema | Action (BUY/SELL), quantity (min 1), price (min 0), product, pricetype | `restx_api/schemas.py:3-15` |
| ModifyOrderSchema | Order fields with validation | `restx_api/schemas.py:31-43` |
| CancelOrderSchema | orderid required | `restx_api/schemas.py:45-48` |
| BasketOrderSchema | Nested order validation | `restx_api/schemas.py:69-72` |
| SplitOrderSchema | Splitsize (positive int) | `restx_api/schemas.py:74-86` |
| OptionsOrderSchema | Strike, expiry, offset validation | `restx_api/schemas.py:88-104` |
| OptionsMultiOrderSchema | Array length 1-20 | `restx_api/schemas.py:120-132` |
| MarginCalculatorSchema | Array length 1-50 | `restx_api/schemas.py:152-159` |

### Validation Features

```python
# Example validations used
validate.OneOf(["BUY", "SELL"])     # Enum validation
validate.Range(min=1)               # Numeric range
validate.Length(min=1, max=20)      # Array length
fields.Nested()                     # Complex object validation
```

---

## 8. SQL Injection Prevention

### SQLAlchemy ORM

All database queries use SQLAlchemy ORM with parameterized queries.

| Practice | Implementation |
|----------|----------------|
| ORM Usage | 100% of queries via SQLAlchemy |
| Parameterized Queries | `filter_by()` for all lookups |
| No String Concatenation | Zero raw SQL string building |

### Example Safe Query

```python
# Safe - parameterized query
user = User.query.filter_by(username=username).first()

# Never used - unsafe string concatenation
# cursor.execute(f"SELECT * FROM users WHERE username='{username}'")
```

**Locations:** `database/auth_db.py`, `database/user_db.py`, `database/traffic_db.py`

---

## 9. XSS Prevention (Content Security Policy)

### CSP Directives

| Directive | Value | Purpose |
|-----------|-------|---------|
| default-src | 'self' | Restrict all to same-origin |
| script-src | 'self' 'unsafe-inline' cdn.socket.io | Scripts from self + Socket.IO |
| style-src | 'self' 'unsafe-inline' | Styles from self |
| img-src | 'self' data: | Images from self + data URIs |
| connect-src | 'self' wss: ws: | WebSocket connections |
| font-src | 'self' | Fonts from same-origin |
| object-src | 'none' | No plugins allowed |
| frame-ancestors | 'self' | Clickjacking protection |
| form-action | 'self' | Form submission restriction |
| base-uri | 'self' | Base tag restriction |

**Location:** `csp.py:139-186`

### Configuration

```env
CSP_ENABLED = TRUE
CSP_REPORT_ONLY = FALSE
CSP_REPORT_URI = ""
CSP_UPGRADE_INSECURE_REQUESTS = FALSE
```

---

## 10. IP Security & Banning

### IP Ban System

| Feature | Implementation | Location |
|---------|----------------|----------|
| Temporary Bans | Configurable duration (default 24h) | `database/traffic_db.py:185` |
| Permanent Bans | After repeat offenses | `database/traffic_db.py:178-182` |
| Repeat Tracking | Ban count incremented per violation | `database/traffic_db.py:173-181` |
| Localhost Protection | Never ban 127.0.0.1, ::1 | `database/traffic_db.py:162-164` |

### Threat Detection

| Feature | Description | Location |
|---------|-------------|----------|
| 404 Tracking | Detect bot scanning | `database/traffic_db.py:242-347` |
| Invalid API Key Tracking | Track brute-force attempts | `database/traffic_db.py:349-456` |
| Auto-Escalation | Temp ban → Permanent after 3 offenses | `database/traffic_db.py:179-182` |

### Proxy IP Detection

Supports multiple proxy headers in priority order:

1. CF-Connecting-IP (Cloudflare)
2. True-Client-IP (Cloudflare Enterprise)
3. X-Real-IP
4. X-Forwarded-For
5. X-Client-IP
6. request.remote_addr (fallback)

**Location:** `utils/ip_helper.py:1-108`

---

## 11. Logging & Audit Trails

### Traffic Logging

All HTTP requests are logged (except static files).

| Field | Description |
|-------|-------------|
| IP Address | Client IP (proxy-aware) |
| Method | HTTP method |
| Path | Request path |
| Status Code | Response status |
| Duration | Request duration (ms) |
| User ID | Authenticated user (if available) |
| Error | Error message (if any) |

**Location:** `utils/traffic_logger.py:35-44`

### Sensitive Data Redaction

The following patterns are automatically redacted from logs:

```python
- api_key, apikey, api-key
- password, passwd
- token, access_token, refresh_token
- secret, client_secret
- authorization header
- Bearer tokens
```

**Location:** `utils/logging.py:28-80`

### Log Retention

- **Rotating Files:** Configurable rotation
- **Default Retention:** 14 days
- **Separate Log Database:** `LOGS_DATABASE_URL` for traffic logs

---

## 12. Docker Security

### Dockerfile Hardening

| Practice | Implementation | Location |
|----------|----------------|----------|
| Multi-Stage Build | Separate builder/production stages | `Dockerfile:2-17` |
| Slim Base Image | `python:3.12-slim-bullseye` | `Dockerfile:17` |
| Non-Root User | Runs as `appuser` | `Dockerfile:24,46` |
| Cache Cleanup | `rm -rf /root/.cache` | `Dockerfile:14` |

### Directory Permissions

| Directory | Permission | Purpose |
|-----------|------------|---------|
| /app/strategies | 755 | Strategy scripts |
| /app/keys | 700 | Private keys (owner only) |
| /app/log | 755 | Application logs |

### Docker Compose Security

| Practice | Implementation | Location |
|----------|----------------|----------|
| Named Volumes | Persistent data isolation | `docker-compose.yaml:31-40` |
| Read-Only .env | Config mounted as `:ro` | `docker-compose.yaml:20` |
| Restart Policy | `unless-stopped` | `docker-compose.yaml:27` |

---

## 13. CORS Configuration

### Default Configuration

| Setting | Default | Location |
|---------|---------|----------|
| CORS_ENABLED | FALSE | `.sample.env:104` |
| CORS_ALLOWED_ORIGINS | Specific only | `.sample.env:109` |
| CORS_ALLOW_CREDENTIALS | FALSE | `.sample.env:124` |
| CORS_MAX_AGE | 86400 (24h) | `.sample.env:128` |

### Security Features

- **Disabled by Default:** Must be explicitly enabled
- **No Wildcard Origins:** Specific origins required
- **API Routes Only:** Applied only to `/api/*`

**Location:** `cors.py`, `app.py:117-119`

---

## 14. Security Headers

### Additional Headers

| Header | Value | Location |
|--------|-------|----------|
| Referrer-Policy | strict-origin-when-cross-origin | `csp.py:127` |
| Permissions-Policy | Restrictive defaults | `csp.py:132` |

### Permissions Policy

```
camera=()
microphone=()
geolocation=()
payment=()
usb=()
screen-wake-lock=()
web-share=()
```

---

## 15. Multi-Factor Authentication

### TOTP Support

| Feature | Implementation | Location |
|---------|----------------|----------|
| TOTP Generation | pyotp library | `database/user_db.py:99-102` |
| QR Code Setup | Scannable QR for authenticator apps | `blueprints/auth.py:321-334` |
| Password Reset | TOTP or Email options | `blueprints/auth.py:83-269` |

### User Enumeration Prevention

Password reset returns the same response regardless of whether the email exists.

**Location:** `blueprints/auth.py:98-106`

---

## 16. Vulnerability Management

### GitHub Dependabot Integration

| Practice | Status |
|----------|--------|
| CVE Monitoring | Active via Dependabot alerts |
| Regular Updates | Security patches applied regularly |
| Dependency Tracking | Automated vulnerability detection |

### Security Response

- Regular CVE vulnerability fixes from Dependabot alerts
- Timely security patches for dependencies
- Supply chain security monitoring

---

## 17. Security Libraries

### Core Security Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| argon2-cffi | 23.1.0 | Password hashing |
| cryptography | 44.0.1 | Fernet encryption |
| Flask-WTF | 1.2.1 | CSRF protection |
| Flask-Limiter | 3.7.0 | Rate limiting |
| Flask-Cors | 6.0.0 | CORS management |
| pyotp | 2.9.0 | TOTP authentication |
| Flask-SQLAlchemy | 3.1.1 | SQL injection prevention |
| bcrypt | 4.1.3 | Legacy password support |

---

## Security Architecture Diagram

```
                    ┌─────────────────────────────────────────┐
                    │              INTERNET                    │
                    └─────────────────┬───────────────────────┘
                                      │
                    ┌─────────────────▼───────────────────────┐
                    │         NGINX REVERSE PROXY              │
                    │  - SSL/TLS Termination                   │
                    │  - Rate Limiting                         │
                    │  - Security Headers                      │
                    └─────────────────┬───────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  IP Ban Check   │      │  Rate Limiter   │      │  CSRF Check     │
│  (Middleware)   │      │  (Flask-Limiter)│      │  (Flask-WTF)    │
└────────┬────────┘      └────────┬────────┘      └────────┬────────┘
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  │
                    ┌─────────────▼───────────────────────┐
                    │         INPUT VALIDATION             │
                    │      (Marshmallow Schemas)           │
                    └─────────────┬───────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Session Auth   │    │   API Key Auth  │    │   TOTP Auth     │
│  (Cookies)      │    │   (Argon2)      │    │   (pyotp)       │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │
                    ┌───────────▼─────────────────────────┐
                    │           APPLICATION               │
                    │  - SQLAlchemy ORM (SQL Prevention)  │
                    │  - Fernet Encryption (Tokens)       │
                    │  - Audit Logging (Traffic)          │
                    └───────────┬─────────────────────────┘
                                │
                    ┌───────────▼─────────────────────────┐
                    │           DATABASE                  │
                    │  - Encrypted Tokens                 │
                    │  - Hashed Passwords (Argon2)        │
                    │  - Hashed API Keys                  │
                    └─────────────────────────────────────┘
```

---

## Summary

OpenAlgo implements comprehensive security controls across all application layers:

| Layer | Controls |
|-------|----------|
| **Network** | CORS, CSP, Security Headers, Rate Limiting |
| **Authentication** | Argon2, TOTP, Session Security |
| **Authorization** | CSRF, API Key Verification |
| **Data** | Fernet Encryption, Input Validation |
| **Database** | SQLAlchemy ORM, Parameterized Queries |
| **Monitoring** | Traffic Logging, IP Banning, Audit Trails |
| **Infrastructure** | Docker Hardening, Non-Root User |
| **Supply Chain** | Dependabot CVE Monitoring |

---

*This document is maintained as part of OpenAlgo's security documentation. For security concerns, please report to the maintainers.*
