# OpenAlgo Password Reset System

## Overview

OpenAlgo provides a comprehensive dual-mode password reset system that allows users to recover their accounts through either:
1. **TOTP (Time-based One-Time Password)** authentication
2. **Email verification** (requires SMTP configuration)

This system is designed with security best practices and provides fallback options for different scenarios.

## Table of Contents

- [System Architecture](#system-architecture)
- [Authentication Methods](#authentication-methods)
- [Setup Requirements](#setup-requirements)
- [User Flow](#user-flow)
- [Configuration Guide](#configuration-guide)
- [Security Features](#security-features)
- [Troubleshooting](#troubleshooting)
- [API Endpoints](#api-endpoints)
- [Rate Limiting](#rate-limiting)

## System Architecture

The password reset system follows a secure token-based approach with multiple verification methods:

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   User Request  │    │  Method Selection │    │  Verification   │
│                 │───▶│                  │───▶│                 │
│ Enter Email     │    │ TOTP or Email    │    │ Code/Link Check │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                          │
                       ┌─────────────────┐               │
                       │  Password Reset │◀──────────────┘
                       │                 │
                       │ New Password    │
                       └─────────────────┘
```

## Authentication Methods

### 1. TOTP Authentication (Recommended)

**Advantages:**
- Works offline
- No external dependencies
- Immediate verification
- Always available

**Requirements:**
- User must have TOTP configured
- Authenticator app (Google Authenticator, Authy, etc.)

**Flow:**
1. User enters email address
2. User selects "TOTP Authentication"
3. User enters TOTP code from authenticator app
4. System validates code and allows password reset

### 2. Email Verification

**Advantages:**
- User-friendly
- No additional app required
- Secure email delivery

**Requirements:**
- SMTP configuration must be completed
- User has access to their email

**Flow:**
1. User enters email address
2. User selects "Email Verification"
3. System sends reset link to user's email
4. User clicks link and resets password

## Setup Requirements

### TOTP Setup (Always Available)
TOTP is automatically configured during account creation. Each user gets:
- Unique TOTP secret key
- QR code for easy setup
- Backup secret for manual entry

### SMTP Configuration (Required for Email Reset)

**Personal Gmail Configuration:**
```
SMTP Server: smtp.gmail.com
Port: 587 (STARTTLS) or 465 (SSL/TLS)
Username: your-email@gmail.com
Password: [App Password - NOT regular password]
HELO Hostname: smtp.gmail.com
Use TLS: Yes
```

**Gmail Workspace Configuration:**
```
SMTP Server: smtp-relay.gmail.com
Port: 465 (SSL/TLS)
Username: your-email@yourdomain.com
Password: [App Password]
HELO Hostname: smtp.gmail.com
Use TLS: Yes
```

**App Password Setup for Gmail:**
1. Go to Google Account Settings
2. Navigate to Security → 2-Step Verification
3. Select "App passwords"
4. Generate a new app password for "Mail"
5. Use this password in SMTP configuration

## User Flow

### Password Reset Process

1. **Initial Request**
   - User visits `/auth/reset-password`
   - Enters email address
   - System validates email format (client-side and server-side)

2. **Method Selection**
   - System presents two verification options:
     - TOTP Authentication (always available)
     - Email Verification (if SMTP configured)
   - User selects preferred method

3. **TOTP Verification Path**
   - User enters TOTP code from authenticator app
   - System validates code against user's TOTP secret
   - If valid, generates secure reset token
   - User proceeds to password reset form

4. **Email Verification Path**
   - System generates secure reset token
   - Sends password reset email with secure link
   - User clicks link in email
   - System validates token and shows password reset form

5. **Password Reset**
   - User enters new password
   - System validates password meets requirements:
     - Minimum 8 characters
     - At least 1 uppercase letter (A-Z)
     - At least 1 lowercase letter (a-z)
     - At least 1 number (0-9)
     - At least 1 special character (@#$%^&*)
   - Password is hashed and stored securely
   - All reset tokens are invalidated

## Configuration Guide

### SMTP Configuration

Access SMTP settings at `/auth/change` → "SMTP Configuration" tab:

1. **Server Settings**
   - Enter SMTP server hostname
   - Set appropriate port (587 for STARTTLS, 465 for SSL/TLS)
   - Configure HELO hostname

2. **Authentication**
   - Enter username (usually email address)
   - Enter App Password (not regular password for Gmail)
   - Set from email address

3. **Security**
   - Enable TLS/SSL encryption
   - Test configuration before saving

4. **Testing**
   - Use "Send Test" to verify configuration
   - Use "Debug" for detailed connection diagnostics

### TOTP Configuration

Access TOTP settings at `/auth/change` → "TOTP Authentication" tab:

1. **QR Code Setup**
   - Scan QR code with authenticator app
   - Or manually enter the secret key

2. **Supported Apps**
   - Google Authenticator
   - Authy
   - Microsoft Authenticator
   - 1Password
   - Bitwarden

3. **Backup**
   - Save secret key in secure location
   - Test TOTP generation before relying on it

## Security Features

### Token Security
- **Cryptographically secure tokens**: 32-byte URL-safe tokens
- **Session-based validation**: Tokens stored in server-side sessions
- **Single-use tokens**: Tokens invalidated after successful use
- **Time-limited validity**: Email tokens expire with session
- **Secure transmission**: HTTPS-only token delivery

### Anti-Enumeration Protection
- **Consistent responses**: Same response regardless of email existence
- **Information leakage prevention**: No indication if email is registered
- **Rate limiting**: Prevents brute force attacks

### Additional Security Measures
- **CSRF protection**: All forms protected with CSRF tokens
- **Input validation**: Email format and password strength validation
- **Secure password hashing**: Bcrypt with proper salt rounds
- **Session security**: Secure session cookie configuration

## Troubleshooting

### Common SMTP Issues

**Gmail Authentication Failed**
```
Error: SMTP Authentication failed
Solution: Use App Password instead of regular password
Steps: Google Account → Security → 2-Step Verification → App passwords
```

**Gmail Workspace Relay Denied**
```
Error: Mail relay denied
Solution 1: Register server IP in Google Admin Console
Solution 2: Switch to personal Gmail settings (smtp.gmail.com:587)
```

**Connection Timeout**
```
Error: Connection timeout
Check: Firewall blocking SMTP ports (587, 465)
Check: Network connectivity to SMTP server
```

**SSL/TLS Errors**
```
Error: SSL handshake failed
Solution: Verify port configuration (587=STARTTLS, 465=SSL/TLS)
Check: Certificate validation settings
```

### Common TOTP Issues

**Invalid TOTP Code**
```
Issue: Code not accepted
Check: Time synchronization on device
Check: Code not expired (30-second window)
Solution: Manually sync time in authenticator app
```

**Lost Authenticator Device**
```
Issue: Cannot generate TOTP codes
Solution: Use backup secret key to reconfigure
Fallback: Contact administrator for manual reset
```

### Email Delivery Issues

**Email Not Received**
```
Check: Spam/junk folder
Check: Email address typos
Check: SMTP server logs
Verify: Test email functionality works
```

**Reset Link Expired**
```
Issue: "Invalid or expired reset link"
Cause: Session expired or link already used
Solution: Request new password reset
```

## ⚠️ Nuclear Option: Complete Database Reset

### When All Else Fails

If you cannot access your OpenAlgo account through any method (TOTP broken, email not working, lost credentials), you can perform a complete database reset. **This will delete ALL data.**

### What You Will Lose

⚠️ **WARNING: This action is irreversible and will permanently delete:**

- **User accounts and passwords**
- **All trading logs and history**
- **API access logs and analytics**
- **Strategy configurations and backtests**
- **SMTP/email settings**
- **Rate limiting history**
- **System settings and preferences**
- **Custom configurations**
- **Latency monitoring data**
- **Traffic monitoring logs**

### Database Reset Procedure

#### Step 1: Stop OpenAlgo Application

```bash
# If using systemd service
sudo systemctl stop openalgo

# If running manually (find and kill process)
pkill -f "python app.py"

# If using PM2
pm2 stop openalgo

# If using Docker
docker stop openalgo-container
```

#### Step 2: Backup Current Database (Optional)

```bash
# Navigate to OpenAlgo directory
cd /path/to/your/openalgo

# Create backup with timestamp
mkdir backup_$(date +%Y%m%d_%H%M%S)
cp db/openalgo.db backup_*/
cp db/logs.db backup_*/ 2>/dev/null || true
cp db/latency.db backup_*/ 2>/dev/null || true

# Backup your .env file as well
cp .env backup_*/
```

#### Step 3: Delete Database Files

```bash
# Delete main database (contains user accounts, settings, logs)
rm db/openalgo.db

# Optionally delete other databases
rm db/logs.db 2>/dev/null || true      # API and system logs
rm db/latency.db 2>/dev/null || true   # Performance monitoring data
```

#### Step 4: Restart Application

```bash
# Start OpenAlgo (it will recreate databases automatically)
# If using systemd service
sudo systemctl start openalgo

# If running manually
python app.py &

# If using PM2
pm2 start openalgo

# If using Docker
docker start openalgo-container
```

#### Step 5: Initial Setup

1. **Visit your OpenAlgo URL** (e.g., http://localhost:5000)
2. **You'll be redirected to `/setup`** (fresh installation flow)
3. **Create new admin account** with username and password
4. **Set up TOTP authentication** (scan QR code with authenticator app)
5. **Configure broker credentials** in your `.env` file if needed
6. **Set up SMTP settings** in Profile → SMTP Configuration
7. **Test password reset functionality** to ensure it works

### Post-Reset Checklist

After database reset, you'll need to reconfigure:

- [ ] **Admin account created** and TOTP set up
- [ ] **Broker API keys** configured in `.env` file  
- [ ] **SMTP email settings** configured and tested
- [ ] **Rate limiting settings** verified
- [ ] **Master contract data** downloaded (if applicable)
- [ ] **Strategy configurations** recreated
- [ ] **API keys** regenerated for external access
- [ ] **System backups** scheduled for future

### Prevention for Future

To avoid needing database reset:

1. **Save TOTP Secret Key**: Store authenticator backup codes securely
2. **Configure SMTP Early**: Set up email recovery before you need it
3. **Document Credentials**: Keep encrypted record of important settings
4. **Regular Backups**: Schedule automatic database backups
5. **Test Recovery**: Periodically test password reset functionality

### Alternative Recovery Methods

Before resorting to database reset, try these:

1. **TOTP Secret Recovery**: If you saved the original secret key, re-add to authenticator
2. **Database Editing**: Advanced users can directly edit SQLite database to reset passwords
3. **Python Script Recovery**: Create custom script to reset user password in database
4. **Backup Restoration**: If you have recent database backup, restore it instead

### Support After Reset

If you encounter issues after database reset:

- **Setup Problems**: Check `/docs/INSTALL.md` for initial setup
- **SMTP Issues**: Review `/docs/SMTP_SETUP.md` for email configuration  
- **Broker Integration**: Verify `.env` file broker settings
- **Performance Issues**: Monitor logs for errors during startup

## API Endpoints

### Reset Password Endpoints

**GET/POST `/auth/reset-password`**
- Main password reset page
- Handles all reset flow steps
- Rate limited: 15 requests per hour

**GET `/auth/reset-password-email/<token>`**
- Email reset link handler
- Validates token and shows password form
- Single-use token validation

**POST `/auth/test-smtp`**
- Test SMTP configuration
- Requires authentication
- Returns JSON response

**POST `/auth/debug-smtp`**
- Debug SMTP connection
- Requires authentication
- Returns detailed diagnostic information

### Request/Response Examples

**Password Reset Request:**
```bash
curl -X POST http://localhost:5000/auth/reset-password \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "step=email&email=user@example.com"
```

**TOTP Verification:**
```bash
curl -X POST http://localhost:5000/auth/reset-password \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "step=totp&email=user@example.com&totp_code=123456"
```

**Test SMTP:**
```bash
curl -X POST http://localhost:5000/auth/test-smtp \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-CSRFToken: <csrf_token>" \
  -d "test_email=test@example.com"
```

## Rate Limiting

The password reset system implements rate limiting to prevent abuse:

### Configuration
```env
# Login rate limits (applied to reset password as well)
LOGIN_RATE_LIMIT_MIN=5 per minute
LOGIN_RATE_LIMIT_HOUR=25 per hour

# Password reset specific limit
RESET_RATE_LIMIT=15 per hour
```

### Limits Applied
- **Password reset requests**: 15 per hour per IP
- **SMTP test requests**: Inherits from login limits
- **Failed authentication attempts**: Tracked separately

### Rate Limit Headers
When rate limited, responses include:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Requests remaining in window
- `X-RateLimit-Reset`: Time when limit resets

## Best Practices

### For Users
1. **TOTP Setup**: Always configure TOTP as primary recovery method
2. **Backup Codes**: Save TOTP secret key securely
3. **Email Security**: Use secure email provider with 2FA
4. **Strong Passwords**: Follow password requirements strictly

### For Administrators
1. **SMTP Security**: Use App Passwords, never regular passwords
2. **Monitoring**: Monitor failed reset attempts
3. **Documentation**: Keep SMTP settings documented
4. **Testing**: Regularly test both reset methods

### For Developers
1. **Token Security**: Always use cryptographically secure tokens
2. **Session Management**: Properly invalidate tokens after use
3. **Error Handling**: Don't expose sensitive information in errors
4. **Logging**: Log security events without exposing credentials

## Security Considerations

### Data Protection
- **PII Handling**: Email addresses handled with care
- **Token Storage**: Tokens stored in server-side sessions only
- **Password Hashing**: Bcrypt with appropriate cost factor
- **Secure Transmission**: HTTPS enforced for all sensitive operations

### Attack Prevention
- **Brute Force**: Rate limiting prevents credential stuffing
- **Token Prediction**: Cryptographically random tokens
- **Session Fixation**: Session regeneration after authentication
- **CSRF**: All state-changing operations protected

### Compliance
- **GDPR**: Minimal data collection and processing
- **Security Standards**: Follows OWASP guidelines
- **Password Policy**: Enforces strong password requirements
- **Audit Logging**: Security events logged for compliance

## Monitoring and Logging

### Key Events Logged
- Password reset requests (with email hash)
- Successful/failed TOTP verifications
- Email send success/failure
- SMTP configuration changes
- Rate limit violations

### Log Levels
- **INFO**: Normal operations (reset requests, successful resets)
- **WARNING**: Failed attempts, rate limiting
- **ERROR**: System errors, SMTP failures
- **DEBUG**: Detailed SMTP debugging (when enabled)

### Monitoring Alerts
Set up alerts for:
- High number of failed reset attempts
- SMTP delivery failures
- Unusual password reset patterns
- Rate limit threshold breaches

---

## Support

For additional support:
- Check logs at `/auth/logs` (if accessible)
- Use SMTP debug functionality
- Review error messages in browser console
- Contact system administrator for manual intervention

## Version History

- **v1.0.3**: Dual-mode password reset system
- **v1.0.2**: Enhanced SMTP configuration
- **v1.0.1**: Basic email reset functionality
- **v1.0.0**: TOTP-only password reset