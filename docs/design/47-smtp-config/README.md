# 47 - SMTP Configuration

## Overview

OpenAlgo uses SMTP for sending email notifications, password reset links, and alerts. SMTP credentials are stored encrypted in the database for security.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         SMTP Configuration Architecture                       │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           Admin Configuration                                │
│                           /settings/smtp                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  SMTP Settings Form                                                  │   │
│  │                                                                      │   │
│  │  SMTP Server:    [smtp.gmail.com          ]                         │   │
│  │  Port:           [587                      ]                         │   │
│  │  Username:       [user@gmail.com           ]                         │   │
│  │  Password:       [••••••••••••             ]                         │   │
│  │  From Email:     [noreply@example.com      ]                         │   │
│  │  Use TLS:        [✓] Enabled                                        │   │
│  │                                                                      │   │
│  │  [Test Connection]  [Save Settings]                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     │ Save with Encryption
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Database Storage                                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  smtp_config table                                                   │   │
│  │                                                                      │   │
│  │  id │ smtp_server │ smtp_port │ username │ password_enc │ ...       │   │
│  │  ─────────────────────────────────────────────────────────────────  │   │
│  │  1  │ smtp.gmail  │ 587       │ user@... │ gAAAAB...    │           │   │
│  │                                           (Fernet encrypted)         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     │ When Email Needed
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Email Sending Service                                │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  1. Load SMTP config from database                                   │   │
│  │  2. Decrypt password using Fernet                                    │   │
│  │  3. Connect to SMTP server                                           │   │
│  │  4. Send email with TLS                                              │   │
│  │  5. Log result                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    SMTP Server                                       │   │
│  │                    (Gmail, SendGrid, etc.)                           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│                           Email Delivered                                    │
│                           to Recipient                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Database Schema

### smtp_config Table

```
┌────────────────────────────────────────────────────────────────┐
│                     smtp_config table                           │
├──────────────────┬──────────────┬──────────────────────────────┤
│ Column           │ Type         │ Description                  │
├──────────────────┼──────────────┼──────────────────────────────┤
│ id               │ INTEGER PK   │ Auto-increment               │
│ smtp_server      │ VARCHAR(255) │ SMTP server hostname         │
│ smtp_port        │ INTEGER      │ SMTP port (25/465/587)       │
│ smtp_username    │ VARCHAR(255) │ Authentication username      │
│ smtp_password    │ TEXT         │ Fernet-encrypted password    │
│ from_email       │ VARCHAR(255) │ Sender email address         │
│ from_name        │ VARCHAR(255) │ Sender display name          │
│ use_tls          │ BOOLEAN      │ Enable STARTTLS              │
│ use_ssl          │ BOOLEAN      │ Enable SSL/TLS               │
│ is_active        │ BOOLEAN      │ Configuration active         │
│ created_at       │ DATETIME     │ When created                 │
│ updated_at       │ DATETIME     │ Last modified                │
└──────────────────┴──────────────┴──────────────────────────────┘
```

## Password Encryption

### Fernet Encryption

```python
from cryptography.fernet import Fernet
from utils.env_utils import get_fernet_key

def encrypt_smtp_password(password):
    """Encrypt SMTP password for storage"""
    key = get_fernet_key()  # Derived from APP_KEY
    fernet = Fernet(key)
    return fernet.encrypt(password.encode()).decode()

def decrypt_smtp_password(encrypted_password):
    """Decrypt SMTP password for use"""
    key = get_fernet_key()
    fernet = Fernet(key)
    return fernet.decrypt(encrypted_password.encode()).decode()
```

### Key Derivation

```python
import hashlib
import base64

def get_fernet_key():
    """Derive Fernet key from APP_KEY"""
    app_key = os.environ.get('APP_KEY')
    if not app_key:
        raise ValueError("APP_KEY not configured")

    # Derive 32-byte key for Fernet
    key_bytes = hashlib.sha256(app_key.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)
```

## Email Service

### Configuration Loading

```python
def get_smtp_config():
    """Load SMTP configuration"""
    config = SmtpConfig.query.filter_by(is_active=True).first()
    if not config:
        return None

    return {
        'server': config.smtp_server,
        'port': config.smtp_port,
        'username': config.smtp_username,
        'password': decrypt_smtp_password(config.smtp_password),
        'from_email': config.from_email,
        'from_name': config.from_name,
        'use_tls': config.use_tls,
        'use_ssl': config.use_ssl
    }
```

### Send Email Function

```python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_email(to_email, subject, body, html_body=None):
    """Send email via SMTP"""
    config = get_smtp_config()
    if not config:
        logger.error("SMTP not configured")
        return False

    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{config['from_name']} <{config['from_email']}>"
        msg['To'] = to_email

        # Attach text and HTML parts
        msg.attach(MIMEText(body, 'plain'))
        if html_body:
            msg.attach(MIMEText(html_body, 'html'))

        # Connect and send
        if config['use_ssl']:
            server = smtplib.SMTP_SSL(config['server'], config['port'])
        else:
            server = smtplib.SMTP(config['server'], config['port'])
            if config['use_tls']:
                server.starttls()

        server.login(config['username'], config['password'])
        server.sendmail(config['from_email'], to_email, msg.as_string())
        server.quit()

        logger.info(f"Email sent to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False
```

### Test Connection

```python
def test_smtp_connection():
    """Test SMTP configuration"""
    config = get_smtp_config()
    if not config:
        return False, "SMTP not configured"

    try:
        if config['use_ssl']:
            server = smtplib.SMTP_SSL(config['server'], config['port'], timeout=10)
        else:
            server = smtplib.SMTP(config['server'], config['port'], timeout=10)
            if config['use_tls']:
                server.starttls()

        server.login(config['username'], config['password'])
        server.quit()

        return True, "Connection successful"

    except smtplib.SMTPAuthenticationError:
        return False, "Authentication failed"
    except smtplib.SMTPConnectError:
        return False, "Could not connect to server"
    except Exception as e:
        return False, str(e)
```

## API Endpoints

### Save Configuration

```
POST /api/settings/smtp
Content-Type: application/json
Authorization: Bearer ADMIN_TOKEN

{
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_username": "user@gmail.com",
    "smtp_password": "app_password",
    "from_email": "noreply@example.com",
    "from_name": "OpenAlgo",
    "use_tls": true,
    "use_ssl": false
}
```

**Response:**
```json
{
    "status": "success",
    "message": "SMTP configuration saved"
}
```

### Test Configuration

```
POST /api/settings/smtp/test
Authorization: Bearer ADMIN_TOKEN
```

**Response:**
```json
{
    "status": "success",
    "message": "Connection successful"
}
```

### Get Configuration (Masked)

```
GET /api/settings/smtp
Authorization: Bearer ADMIN_TOKEN
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_username": "user@gmail.com",
        "smtp_password": "••••••••",
        "from_email": "noreply@example.com",
        "use_tls": true
    }
}
```

## Common SMTP Providers

### Gmail

```python
GMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'use_tls': True,
    'use_ssl': False
    # Note: Requires App Password with 2FA enabled
}
```

### SendGrid

```python
SENDGRID_CONFIG = {
    'smtp_server': 'smtp.sendgrid.net',
    'smtp_port': 587,
    'use_tls': True,
    'use_ssl': False
    # Username: 'apikey'
    # Password: Your SendGrid API key
}
```

### Amazon SES

```python
SES_CONFIG = {
    'smtp_server': 'email-smtp.{region}.amazonaws.com',
    'smtp_port': 587,
    'use_tls': True,
    'use_ssl': False
}
```

## Email Templates

### Password Reset Email

```python
def send_password_reset_email(user_email, reset_token):
    """Send password reset email"""
    reset_url = f"{get_base_url()}/reset-password?token={reset_token}"

    subject = "Reset Your OpenAlgo Password"

    body = f"""
Hello,

You requested to reset your OpenAlgo password.

Click the link below to reset your password:
{reset_url}

This link expires in 1 hour.

If you didn't request this, please ignore this email.

Best regards,
OpenAlgo Team
"""

    html_body = f"""
<html>
<body>
    <h2>Reset Your Password</h2>
    <p>You requested to reset your OpenAlgo password.</p>
    <p><a href="{reset_url}" style="
        display: inline-block;
        padding: 12px 24px;
        background-color: #4F46E5;
        color: white;
        text-decoration: none;
        border-radius: 6px;
    ">Reset Password</a></p>
    <p>This link expires in 1 hour.</p>
    <p>If you didn't request this, please ignore this email.</p>
</body>
</html>
"""

    return send_email(user_email, subject, body, html_body)
```

### Order Notification Email

```python
def send_order_notification(user_email, order_details):
    """Send order execution notification"""
    subject = f"Order Executed: {order_details['action']} {order_details['symbol']}"

    body = f"""
Order Executed

Symbol: {order_details['symbol']}
Action: {order_details['action']}
Quantity: {order_details['quantity']}
Price: ₹{order_details['price']}
Order ID: {order_details['order_id']}
Time: {order_details['time']}
"""

    return send_email(user_email, subject, body)
```

## Security Considerations

### Password Storage

```
┌────────────────────────────────────────────────────────────────────────────┐
│                     SMTP Password Security                                  │
│                                                                             │
│  1. Password entered in admin UI                                           │
│           │                                                                 │
│           ▼                                                                 │
│  2. Encrypted with Fernet (AES-128-CBC)                                    │
│     Key derived from APP_KEY via SHA-256                                   │
│           │                                                                 │
│           ▼                                                                 │
│  3. Stored as encrypted blob in database                                   │
│     gAAAAABh...   (base64 encoded)                                         │
│           │                                                                 │
│           ▼                                                                 │
│  4. Decrypted only when needed to send email                               │
│     Password never logged or displayed                                      │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### Best Practices

| Practice | Implementation |
|----------|---------------|
| Use App Passwords | Gmail requires app-specific passwords |
| Enable TLS | Always use STARTTLS on port 587 |
| Rate Limiting | Limit emails per minute |
| Error Masking | Don't expose SMTP errors to users |
| Audit Logging | Log all email attempts (without content) |

## Key Files Reference

| File | Purpose |
|------|---------|
| `database/smtp_db.py` | SMTP configuration model |
| `services/email_service.py` | Email sending logic |
| `utils/encryption_utils.py` | Fernet encryption helpers |
| `blueprints/settings.py` | SMTP configuration routes |
| `frontend/src/pages/SmtpSettings.tsx` | Configuration UI |
