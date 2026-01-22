# Security Recommendations

## Overview

When deploying OpenAlgo using `install.sh` on Ubuntu server, most security measures are **automatically configured**. This document covers what's already done and what remains for you.

## What `install.sh` Already Does

### Automatically Configured (No Action Needed)

#### 1. SSL/TLS Certificates
- **Status**: Done
- Let's Encrypt certificates obtained and configured
- Auto-renewal via certbot timer

#### 2. Security Headers
- **Status**: Done
- Configured in Nginx:
  ```nginx
  add_header X-Frame-Options DENY;
  add_header X-Content-Type-Options nosniff;
  add_header X-XSS-Protection "1; mode=block";
  add_header Strict-Transport-Security "max-age=63072000" always;
  ```

#### 3. Strong SSL Configuration
- **Status**: Done
- TLS 1.2 and 1.3 only
- Strong cipher suites
- OCSP stapling enabled
- Session tickets disabled

#### 4. Firewall (UFW)
- **Status**: Done
- Default deny incoming
- Only ports 22, 80, 443 open

#### 5. Random Encryption Keys
- **Status**: Done
- APP_KEY generated: 64-character hex
- API_KEY_PEPPER generated: 64-character hex

#### 6. File Permissions
- **Status**: Done
- www-data ownership
- 755 for directories
- 700 for sensitive keys directory

#### 7. Service Isolation
- **Status**: Done
- Runs as www-data user
- Systemd service management
- Automatic restart on failure

## What You Need to Do

### Essential (Required)

#### 1. Set Strong Login Password

**When**: First login to OpenAlgo

**How**:
- Visit `https://yourdomain.com`
- Create account with strong password
- At least 12 characters
- Mix of letters, numbers, symbols

**Why**: Only defense against unauthorized dashboard access

#### 2. Enable Two-Factor Authentication

**When**: After first login

**How**:
1. Go to Settings
2. Click "Enable 2FA"
3. Scan QR code with authenticator app
4. Enter verification code

**Why**: Protects against password compromise

#### 3. Protect Your API Key

**When**: After generating API key

**How**:
- Copy once and store securely
- Use only in TradingView/Amibroker alerts
- Don't commit to git
- Don't share publicly

**Why**: API key allows placing real orders

### Recommended (Good Practice)

#### 4. Monitor Logs Periodically

**How**:
```bash
# View OpenAlgo logs
sudo journalctl -u openalgo-yourdomain-broker -f

# View Nginx access logs
sudo tail -f /var/log/nginx/access.log

# View Nginx error logs
sudo tail -f /var/log/nginx/error.log
```

**Why**: Detect unusual activity

#### 5. Keep System Updated

**How**:
```bash
# Update Ubuntu packages
sudo apt update && sudo apt upgrade -y

# Update OpenAlgo dependencies
cd /var/python/openalgo-flask/*/openalgo
sudo -u www-data uv sync
```

**Frequency**: Monthly or after security announcements

#### 6. Renew SSL Certificate

**Status**: Usually automatic via certbot timer

**Verify**:
```bash
sudo certbot certificates
```

**Manual renewal** (if needed):
```bash
sudo certbot renew
```

## Optional Enhancements

### Only If You Want Extra Security

#### 1. Restrict WebSocket CORS

**Current**: Allows all origins (`*`)
**Impact**: Low risk for single-user

**If you want to restrict**:
```python
# Edit extensions.py
socketio = SocketIO(
    cors_allowed_origins=['https://yourdomain.com']
)
```

#### 2. IP Whitelisting

**Not recommended** for most users (dynamic IPs)

**If you have static IP**:
```bash
# Add to UFW
sudo ufw allow from YOUR_IP to any port 443
sudo ufw delete allow 'Nginx Full'
sudo ufw allow 80  # Keep for cert renewal
```

#### 3. Fail2ban for SSH

**Install**:
```bash
sudo apt install fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

**Why**: Blocks repeated SSH login failures

## Not Needed (Over-Engineering)

Skip these for single-user deployment:

| Feature | Why Not Needed |
|---------|----------------|
| Redis rate limiting | In-memory sufficient |
| Request signing | API key + HTTPS is enough |
| External audit logging | Local logs sufficient |
| WAF (Web Application Firewall) | Nginx config is adequate |
| VPN access only | Impractical for webhooks |
| Hardware security keys | Overkill |

## Verification Commands

### Check SSL Certificate

```bash
# View certificate details
sudo certbot certificates

# Test SSL configuration
curl -I https://yourdomain.com
```

### Check Firewall

```bash
sudo ufw status verbose
```

Expected output:
```
Status: active
Default: deny (incoming), allow (outgoing)
To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
Nginx Full                 ALLOW       Anywhere
```

### Check Service Status

```bash
sudo systemctl status openalgo-*
sudo systemctl status nginx
```

### Check Security Headers

```bash
curl -I https://yourdomain.com | grep -E "(X-Frame|X-Content|Strict-Transport)"
```

Expected:
```
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Strict-Transport-Security: max-age=63072000
```

## Troubleshooting

### Certificate Renewal Failed

```bash
# Check certbot logs
sudo journalctl -u certbot

# Manual renewal
sudo certbot renew --dry-run
sudo certbot renew
```

### Service Not Starting

```bash
# Check logs
sudo journalctl -u openalgo-yourdomain-broker -n 50

# Restart service
sudo systemctl restart openalgo-yourdomain-broker
```

### Permission Issues

```bash
# Re-apply permissions
sudo chown -R www-data:www-data /var/python/openalgo-flask/*/
sudo chmod -R 755 /var/python/openalgo-flask/*/
```

## Security Incident Response

### If You Suspect Compromise

1. **Immediately disable the service**:
   ```bash
   sudo systemctl stop openalgo-*
   ```

2. **Revoke broker session**:
   - Log into broker's web portal
   - Revoke API access/sessions

3. **Regenerate API key**:
   - After investigation, create new API key
   - Update webhook configurations

4. **Review logs**:
   ```bash
   sudo journalctl -u openalgo-* --since "24 hours ago"
   sudo cat /var/log/nginx/access.log | tail -1000
   ```

5. **Rotate encryption keys** (if severe):
   - Edit `.env` file
   - Generate new APP_KEY and API_KEY_PEPPER
   - Re-authenticate with broker

## Summary

**Already Done by install.sh**:
- SSL/TLS (Let's Encrypt)
- Security headers
- Firewall
- Strong ciphers
- Random keys
- File permissions

**Your Tasks**:
1. Strong password
2. Enable 2FA
3. Protect API key
4. Monitor logs occasionally
5. Keep system updated

**That's it!** The install script handles the complex security configuration.

---

**Back to**: [Security Audit Overview](./README.md)
