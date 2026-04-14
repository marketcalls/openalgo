# OpenAlgo Security Audit Report

## Executive Summary

This security audit was conducted on OpenAlgo, a **single-user, self-hosted** algorithmic trading platform. When deployed using the official `install.sh` script on Ubuntu server, most production security measures are **automatically configured**.

### Deployment Model

```
┌────────────────────────────────────────────────────────────────┐
│                    Your Ubuntu Server                           │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   OpenAlgo (install.sh)                   │  │
│  │  • Nginx with SSL (Let's Encrypt)                         │  │
│  │  • Security headers (HSTS, X-Frame-Options, etc.)         │  │
│  │  • Firewall (UFW)                                         │  │
│  │  • Gunicorn + WebSocket                                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│               ┌──────────────┴──────────────┐                  │
│               │                              │                  │
│      Internal Access              Webhook Endpoint              │
│   (Browser: https://domain)     (API: https://domain/api)      │
└───────────────────────────────────────────────────────────────-┘
                                        ▲
                                        │ (Optional: ngrok tunnel
                                        │  for webhook-only access)
                        ┌───────────────┴───────────────┐
                        │     External Webhook Sources   │
                        │  • TradingView                 │
                        │  • GoCharting                  │
                        │  • Chartink                    │
                        │  • Flow                        │
                        └────────────────────────────────┘
```

### Important: Ngrok Usage

**Ngrok is for webhooks only, not for running the app.**

| Use Case | Recommended Method |
|----------|-------------------|
| Running OpenAlgo | Ubuntu server with `install.sh` |
| Accessing dashboard | `https://yourdomain.com` (Nginx) |
| TradingView webhooks | `https://yourdomain.com` OR ngrok tunnel |
| GoCharting/Chartink | `https://yourdomain.com` OR ngrok tunnel |

Ngrok should only be used if:
- You don't have a static IP/domain
- You need temporary webhook access
- Testing webhook integration

### Overall Security Posture: **STRONG**

| Category | Risk Level | Status |
|----------|------------|--------|
| [Broker Credential Security](./secrets-management.md) | Critical | Good |
| [HTTPS/TLS](./recommendations.md) | Critical | Auto-configured |
| [Authentication](./authentication.md) | Medium | Strong |
| [API Key Protection](./api-security.md) | Medium | Good |
| [Security Headers](./xss-csrf.md) | Medium | Auto-configured |
| [SQL Injection](./sql-injection.md) | Low | Protected |
| [XSS & CSRF Protection](./xss-csrf.md) | Low | Good |
| [WebSocket Security](./websocket-security.md) | Low | Good |
| [File Operations](./file-operations.md) | Low | Acceptable |
| [Dependencies](./dependencies.md) | Low | Monitor |

## What `install.sh` Does for Security

### Automatic SSL/TLS Configuration

```bash
# Certbot obtains and configures Let's Encrypt certificates
sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos
```

**Result**: HTTPS enabled with automatic certificate renewal.

### Security Headers (Nginx)

The install script configures these headers automatically:

```nginx
add_header X-Frame-Options DENY;
add_header X-Content-Type-Options nosniff;
add_header X-XSS-Protection "1; mode=block";
add_header Strict-Transport-Security "max-age=63072000" always;
```

### Strong SSL Configuration

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers on;
ssl_ciphers EECDH+AESGCM:EDH+AESGCM;
ssl_session_tickets off;
ssl_stapling on;
ssl_stapling_verify on;
```

### Firewall (UFW)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
```

### Random Key Generation

```bash
# Secure random keys generated during installation
APP_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
API_KEY_PEPPER=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

### File Permissions

```bash
sudo chown -R www-data:www-data $BASE_PATH
sudo chmod -R 755 $BASE_PATH
sudo chmod 700 $OPENALGO_PATH/keys  # Restrictive for sensitive files
```

## What You Still Need to Do

### Essential (After Installation)

1. **Set a strong login password**
   - First login creates your account
   - Use 12+ characters, mix of letters/numbers/symbols

2. **Enable 2FA** (Recommended)
   - Go to Settings in OpenAlgo
   - Enable two-factor authentication
   - Scan QR with authenticator app

3. **Keep your API key secret**
   - Used for TradingView/GoCharting/Chartink webhooks
   - Don't share publicly

### For Webhook Integration

4. **Configure webhooks to use your domain**
   - TradingView: `https://yourdomain.com/api/v1/placeorder`
   - Include API key in webhook payload
   - Don't use ngrok for permanent webhook setup

## Security Layers Summary

| Layer | Protection | Configured By |
|-------|------------|---------------|
| Network | Firewall (UFW) | install.sh |
| Transport | TLS 1.2/1.3 | install.sh |
| Headers | HSTS, X-Frame-Options, etc. | install.sh |
| Application | CSRF, XSS prevention | OpenAlgo code |
| Authentication | Argon2, 2FA | OpenAlgo code |
| Data at Rest | Fernet encryption | OpenAlgo code |
| API | Key hashing with pepper | OpenAlgo code |

## Quick Security Checklist

### Automatic (Done by install.sh)

- [x] SSL/TLS certificates configured
- [x] Security headers added
- [x] Firewall enabled
- [x] Strong SSL ciphers
- [x] Random encryption keys generated
- [x] File permissions set
- [x] Service isolation (systemd)

### Manual (Your Responsibility)

- [ ] Strong login password set
- [ ] 2FA enabled (recommended)
- [ ] API key kept secret
- [ ] Broker credentials configured
- [ ] Webhooks configured to use domain URL (not ngrok)

## Webhook Security

### TradingView/GoCharting/Chartink Integration

When setting up webhooks:

```json
// Webhook payload example
{
    "apikey": "your_openalgo_api_key",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 1
}
```

**Security measures**:
1. **API key required** - Validates every request
2. **HTTPS encryption** - Data encrypted in transit
3. **Rate limiting** - 100 webhooks per minute

### Ngrok Considerations

If using ngrok temporarily for webhooks:
- Ngrok provides HTTPS automatically
- URL is temporary (changes on restart)
- Don't use for dashboard access
- Update webhook URLs when ngrok restarts

## Documentation Structure

| File | Description |
|------|-------------|
| [authentication.md](./authentication.md) | Login security, 2FA, session management |
| [api-security.md](./api-security.md) | API key protection, webhook security |
| [secrets-management.md](./secrets-management.md) | Broker credentials, encryption |
| [websocket-security.md](./websocket-security.md) | Real-time data security |
| [sql-injection.md](./sql-injection.md) | Database security |
| [xss-csrf.md](./xss-csrf.md) | Browser security protections |
| [file-operations.md](./file-operations.md) | File handling security |
| [dependencies.md](./dependencies.md) | Third-party package security |
| [recommendations.md](./recommendations.md) | Remaining improvements |
| [ci-cd-audit.md](./ci-cd-audit.md) | CI/CD pipeline and code quality audit |

## Bottom Line

**Using `install.sh` on Ubuntu**: OpenAlgo is deployed with production-grade security. The script handles SSL, headers, firewall, and key generation automatically.

**Ngrok**: Use only for webhooks if you don't have a domain. Don't run the entire app over ngrok.

**Your only tasks**: Set a strong password, enable 2FA, and keep your API key private.

---

**Audit Date**: January 2026
**Context**: Single-user production deployment via install.sh
