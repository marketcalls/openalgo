# 23 - IP Security

## Overview

OpenAlgo implements IP-based security measures to protect against brute-force attacks, bot abuse, and unauthorized access through automatic detection and banning mechanisms.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          IP Security Architecture                            │
└──────────────────────────────────────────────────────────────────────────────┘

                             Incoming Request
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Security Middleware                                   │
│                        (WSGI Layer)                                          │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  1. Get Real IP (check proxy headers)                                │   │
│  │     CF-Connecting-IP → X-Real-IP → X-Forwarded-For → remote_addr    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  2. Check IP Ban List                                                │   │
│  │     - Is IP in ip_bans table?                                        │   │
│  │     - Is ban expired?                                                │   │
│  │     - Is ban permanent?                                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│              ┌─────────────────────┴─────────────────────┐                  │
│              │                                           │                   │
│           Banned                                    Not Banned               │
│              │                                           │                   │
│              ▼                                           ▼                   │
│         Return 403                               Continue to App            │
│         Forbidden                                                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Detection Mechanisms

### 1. 404 Error Tracking

Detects bots probing for vulnerabilities.

```
┌────────────────────────────────────────────────────────────────┐
│                    404 Error Detection                          │
│                                                                 │
│  Request → 404 Response → Track IP                             │
│                              │                                  │
│                              ▼                                  │
│           ┌──────────────────────────────────┐                 │
│           │ error_404_tracker table           │                 │
│           │                                   │                 │
│           │ - ip_address                      │                 │
│           │ - error_count                     │                 │
│           │ - first_error_at                  │                 │
│           │ - last_error_at                   │                 │
│           │ - paths_attempted (JSON)          │                 │
│           └──────────────────┬───────────────┘                 │
│                              │                                  │
│                     Count >= 20/day?                           │
│                              │                                  │
│              ┌───────────────┴───────────────┐                 │
│              │                               │                  │
│             Yes                             No                  │
│              │                               │                  │
│              ▼                               ▼                  │
│         Auto-Ban IP                      Continue               │
│         (24 hours)                       Monitoring             │
└────────────────────────────────────────────────────────────────┘
```

### 2. Invalid API Key Tracking

Detects brute-force API key attacks.

```
┌────────────────────────────────────────────────────────────────┐
│                 API Key Attack Detection                        │
│                                                                 │
│  Invalid API Key → Track Attempt                               │
│                         │                                       │
│                         ▼                                       │
│       ┌──────────────────────────────────────┐                 │
│       │ invalid_api_key_tracker table         │                 │
│       │                                       │                 │
│       │ - ip_address                          │                 │
│       │ - attempt_count                       │                 │
│       │ - first_attempt_at                    │                 │
│       │ - last_attempt_at                     │                 │
│       │ - api_keys_tried (JSON hashes)        │                 │
│       └──────────────────┬───────────────────┘                 │
│                          │                                      │
│                 Count >= 10/day?                               │
│                          │                                      │
│             ┌────────────┴────────────┐                        │
│             │                         │                         │
│            Yes                       No                         │
│             │                         │                         │
│             ▼                         ▼                         │
│        Auto-Ban IP               Continue                       │
│        (48 hours)                Monitoring                     │
└────────────────────────────────────────────────────────────────┘
```

## Configuration

### Security Thresholds

```bash
# .env or settings table
SECURITY_404_THRESHOLD=20        # 404 errors before ban
SECURITY_404_BAN_DURATION=24     # Ban duration in hours
SECURITY_API_THRESHOLD=10        # Invalid API attempts before ban
SECURITY_API_BAN_DURATION=48     # Ban duration in hours
SECURITY_REPEAT_OFFENDER_LIMIT=3 # Bans before permanent
```

## Database Schema

### ip_bans Table

```
┌────────────────────────────────────────────────────┐
│                   ip_bans table                     │
├──────────────┬──────────────┬──────────────────────┤
│ Column       │ Type         │ Description          │
├──────────────┼──────────────┼──────────────────────┤
│ id           │ INTEGER PK   │ Auto-increment       │
│ ip_address   │ VARCHAR(50)  │ Banned IP (unique)   │
│ ban_reason   │ VARCHAR(200) │ Reason for ban       │
│ ban_count    │ INTEGER      │ Number of offenses   │
│ banned_at    │ DATETIME     │ Ban timestamp        │
│ expires_at   │ DATETIME     │ Expiry (NULL=perm)   │
│ is_permanent │ BOOLEAN      │ Permanent flag       │
│ created_by   │ VARCHAR(50)  │ system / manual      │
└──────────────┴──────────────┴──────────────────────┘
```

### error_404_tracker Table

```
┌────────────────────────────────────────────────────┐
│             error_404_tracker table                 │
├──────────────────┬──────────────┬──────────────────┤
│ Column           │ Type         │ Description      │
├──────────────────┼──────────────┼──────────────────┤
│ id               │ INTEGER PK   │ Auto-increment   │
│ ip_address       │ VARCHAR(50)  │ Client IP        │
│ error_count      │ INTEGER      │ Count in 24h     │
│ first_error_at   │ DATETIME     │ First error      │
│ last_error_at    │ DATETIME     │ Last error       │
│ paths_attempted  │ TEXT         │ JSON array       │
└──────────────────┴──────────────┴──────────────────┘
```

## IP Resolution

### Proxy Header Priority

```python
def get_real_ip():
    """Get client IP from request, handling proxies"""
    headers_to_check = [
        'CF-Connecting-IP',      # Cloudflare
        'True-Client-IP',        # Cloudflare Enterprise
        'X-Real-IP',             # nginx
        'X-Forwarded-For',       # Standard proxy
        'X-Client-IP'            # Some proxies
    ]

    for header in headers_to_check:
        ip = request.headers.get(header)
        if ip:
            return ip.split(',')[0].strip()

    return request.remote_addr
```

## Security Middleware

### WSGI Implementation

```python
class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        ip = get_real_ip_from_environ(environ)

        if is_ip_banned(ip):
            # Return 403 Forbidden
            start_response('403 Forbidden', [])
            return [b'IP Banned']

        return self.app(environ, start_response)
```

### Route Decorator

```python
@bp.route('/api/v1/placeorder')
@check_ip_ban
def place_order():
    # Only reached if IP not banned
    pass
```

## Admin Interface

### Security Dashboard

**Route:** `/logs/security`

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         Security Dashboard                                  │
│                                                                             │
│  Active Bans: 15          Permanent: 3          24h Violations: 47         │
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ IP Address      │ Reason          │ Expires      │ Count │ Actions     ││
│ ├─────────────────┼─────────────────┼──────────────┼───────┼─────────────┤│
│ │ 192.168.1.100   │ 404 abuse       │ 24h          │ 2     │ [Unban]     ││
│ │ 10.0.0.50       │ API brute force │ Permanent    │ 3     │ [Unban]     ││
│ │ 172.16.0.25     │ Manual ban      │ 48h          │ 1     │ [Unban]     ││
│ └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
│ [Add Manual Ban]                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Manual Ban/Unban

```python
# Ban an IP manually
add_ip_ban(
    ip_address='192.168.1.100',
    reason='Suspicious activity',
    duration_hours=24,
    created_by='admin'
)

# Unban an IP
remove_ip_ban('192.168.1.100')
```

## Repeat Offender Escalation

```
┌─────────────────────────────────────────────────────────────────┐
│                    Escalation Policy                             │
│                                                                  │
│  Ban #1 → Temporary (24h or 48h based on violation type)        │
│                              │                                   │
│  Ban #2 → Temporary (doubled duration)                          │
│                              │                                   │
│  Ban #3 → PERMANENT                                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Best Practices

### Rate Limiting Integration

IP bans work alongside rate limiting:

```python
# Rate limiting (first line of defense)
@limiter.limit("10 per second")
def api_endpoint():
    pass

# IP ban (for persistent abuse)
if repeated_violations(ip):
    ban_ip(ip)
```

### Whitelisting

For trusted IPs:

```python
WHITELIST = ['127.0.0.1', '10.0.0.0/8']

def is_whitelisted(ip):
    return any(ip_in_range(ip, range) for range in WHITELIST)
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `utils/security_middleware.py` | WSGI middleware |
| `utils/ip_helper.py` | IP resolution |
| `database/traffic_db.py` | Ban tables |
| `blueprints/security.py` | Security dashboard and routes |
