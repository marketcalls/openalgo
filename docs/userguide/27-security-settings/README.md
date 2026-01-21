# 27 - Security Settings

## Introduction

Security is critical when dealing with automated trading systems. OpenAlgo provides multiple layers of security to protect your account, API keys, and trading activities.

## Security Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        OpenAlgo Security Layers                             │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 1: Authentication                                             │   │
│  │  • Username/Password login                                           │   │
│  │  • Two-Factor Authentication (TOTP)                                  │   │
│  │  • Session management                                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                            │                                                │
│                            ▼                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 2: API Security                                               │   │
│  │  • API key authentication                                            │   │
│  │  • Key hashing with pepper                                           │   │
│  │  • Rate limiting                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                            │                                                │
│                            ▼                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 3: Network Security                                           │   │
│  │  • HTTPS encryption                                                  │   │
│  │  • IP whitelisting (optional)                                        │   │
│  │  • Firewall configuration                                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                            │                                                │
│                            ▼                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 4: Broker Security                                            │   │
│  │  • OAuth2 authentication                                             │   │
│  │  • Encrypted credential storage                                      │   │
│  │  • Session token management                                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Accessing Security Settings

Navigate to **Settings** → **Security** in OpenAlgo.

## Password Security

### Strong Password Requirements

| Requirement | Minimum |
|-------------|---------|
| Length | 8 characters |
| Uppercase | 1 character |
| Lowercase | 1 character |
| Numbers | 1 digit |
| Special characters | Recommended |

### Changing Password

1. Go to **Settings** → **Security**
2. Click **Change Password**
3. Enter current password
4. Enter new password
5. Confirm new password
6. Click **Update**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Change Password                                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Current Password:                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ ••••••••••••                                                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  New Password:                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ ••••••••••••••                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  Strength: ████████░░ Strong                                                │
│                                                                              │
│  Confirm New Password:                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ ••••••••••••••                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ✓ Passwords match                                                          │
│                                                                              │
│  ┌──────────────────┐                                                       │
│  │  Update Password │                                                       │
│  └──────────────────┘                                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Password Best Practices

1. **Use unique password** - Don't reuse from other sites
2. **Use password manager** - Generate and store securely
3. **Don't share** - Never share your password
4. **Regular updates** - Change periodically

## API Key Security

### How API Keys Work

```
Your API Key: abc123xyz789...

Stored in database as:
Hash: sha256(apikey + pepper)

Pepper stored in: .env file (APP_KEY_PEPPER)
```

### Protecting API Keys

| Do | Don't |
|-----|-------|
| Store securely | Commit to Git |
| Use environment variables | Share publicly |
| Regenerate if compromised | Embed in code |
| Use separate keys per integration | Use same key everywhere |

### Regenerating API Key

If you suspect your API key is compromised:

1. Go to **API Key** page
2. Click **Regenerate**
3. Confirm action
4. Update all integrations with new key

### API Key Permissions

Configure what each key can do:

| Permission | Description |
|------------|-------------|
| Place Orders | Allow order placement |
| View Positions | Read position data |
| View Holdings | Read holdings data |
| View Orders | Read order book |
| Cancel Orders | Allow order cancellation |

## Session Security

### Session Management

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Active Sessions                                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Device          │ Location       │ Last Active    │ Action                │
│  ────────────────│────────────────│────────────────│───────                │
│  Chrome/Windows  │ Mumbai, IN     │ Now (current)  │ [This device]         │
│  Safari/macOS    │ Delhi, IN      │ 2 hours ago    │ [Revoke]              │
│  Mobile App      │ Bangalore, IN  │ 1 day ago      │ [Revoke]              │
│                                                                              │
│  ┌──────────────────────┐                                                   │
│  │  Revoke All Sessions │                                                   │
│  └──────────────────────┘                                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Session Timeout

Configure automatic logout:

| Setting | Options |
|---------|---------|
| Session Timeout | 15min, 30min, 1hr, 4hr, 8hr |
| Remember Me | Enable/Disable |
| Auto-logout on close | Enable/Disable |

## Network Security

### Production Deployment Security

When deploying via `install.sh` on Ubuntu server, most network security is **automatically configured**:

| Security Feature | Status |
|-----------------|--------|
| SSL/TLS (Let's Encrypt) | Auto-configured |
| Security Headers (HSTS, X-Frame-Options) | Auto-configured |
| Firewall (UFW - ports 22, 80, 443 only) | Auto-configured |
| Strong SSL ciphers (TLS 1.2/1.3) | Auto-configured |

The `install.sh` script handles:
- SSL certificate installation and auto-renewal
- Nginx security headers
- UFW firewall configuration
- File permissions

See [Installation Guide](../04-installation/README.md) for detailed production setup.

### HTTPS Configuration (Local Development)

For local development without `install.sh`:

```
# .env configuration
FLASK_ENV=production
USE_HTTPS=true
SSL_CERT_PATH=/path/to/cert.pem
SSL_KEY_PATH=/path/to/key.pem
```

### IP Whitelisting (Optional)

Restrict access to specific IPs:

1. Go to **Settings** → **Security**
2. Enable **IP Whitelisting**
3. Add allowed IPs:
   ```
   192.168.1.100
   10.0.0.0/24
   52.89.214.238 (TradingView)
   ```
4. Save changes

### Firewall Rules (Auto-Configured)

The `install.sh` script configures these automatically:

```bash
# Configured by install.sh
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
```

For manual configuration:
```bash
# Allow HTTPS
sudo ufw allow 443/tcp

# Allow HTTP (redirect to HTTPS)
sudo ufw allow 80/tcp

# Deny all other incoming
sudo ufw default deny incoming
```

## Broker Security

### Credential Storage

Broker credentials are:
- Encrypted at rest
- Never logged
- Session-based (not stored long-term)

### OAuth2 Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   OpenAlgo  │────▶│   Broker    │────▶│  Exchange   │
│             │     │   OAuth     │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │
       │   1. Redirect     │
       │──────────────────▶│
       │                   │
       │   2. User Login   │
       │                   │
       │   3. Auth Code    │
       │◀──────────────────│
       │                   │
       │   4. Access Token │
       │◀──────────────────│
```

### Daily Re-authentication

Most brokers require daily login:
- OAuth tokens expire daily
- Manual re-login required
- Automated login not supported (security)

## Security Checklist

### Initial Setup

- [ ] Set strong password
- [ ] Enable Two-Factor Authentication
- [ ] Generate unique API key
- [ ] Configure HTTPS
- [ ] Set session timeout

### Ongoing

- [ ] Review active sessions
- [ ] Check API key usage
- [ ] Monitor traffic logs
- [ ] Update password regularly
- [ ] Review IP whitelist

### If Compromised

- [ ] Change password immediately
- [ ] Regenerate API key
- [ ] Revoke all sessions
- [ ] Check for unauthorized trades
- [ ] Review broker activity
- [ ] Contact support if needed

## Security Alerts

### Configuring Alerts

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Security Alerts                                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ☑ Login from new device                                                   │
│  ☑ Login from new location                                                 │
│  ☑ Multiple failed login attempts                                          │
│  ☑ API key used from unknown IP                                            │
│  ☑ Password changed                                                        │
│  ☑ 2FA disabled                                                            │
│                                                                              │
│  Alert channels:                                                            │
│  ☑ Email                                                                   │
│  ☑ Telegram                                                                │
│  ☐ SMS                                                                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Example Alert

```
⚠️ SECURITY ALERT

New login detected

Device: Chrome on Windows
Location: New York, USA
IP: 203.45.67.89
Time: 2025-01-21 10:30:15 IST

If this wasn't you, please:
1. Change your password immediately
2. Review active sessions
3. Check for unauthorized activity
```

## Best Practices Summary

### 1. Use Strong Authentication

- Strong, unique password
- Enable 2FA
- Use password manager

### 2. Protect API Keys

- Don't share or commit to Git
- Use environment variables
- Regenerate if suspected compromise

### 3. Secure Your Network

- Always use HTTPS
- Configure firewall
- Consider IP whitelisting

### 4. Monitor Activity

- Review logs regularly
- Check active sessions
- Set up security alerts

### 5. Keep Updated

- Update OpenAlgo regularly
- Apply security patches
- Follow security advisories

---

**Previous**: [26 - Traffic Logs](../26-traffic-logs/README.md)

**Next**: [28 - Two-Factor Authentication](../28-two-factor-auth/README.md)
