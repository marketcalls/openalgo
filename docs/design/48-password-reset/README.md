# 48 - Password Reset

## Overview

OpenAlgo provides a secure multi-step password reset flow that supports both email-based reset tokens and TOTP verification for accounts with 2FA enabled.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Password Reset Architecture                           │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         Step 1: Initiate Reset                               │
│                         /forgot-password                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  User enters email address                                           │   │
│  │                                                                      │   │
│  │  Email: [user@example.com                    ]                       │   │
│  │                                                                      │   │
│  │  [Send Reset Link]                                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│                          Validate email exists                               │
│                                    │                                         │
│              ┌─────────────────────┴─────────────────────┐                  │
│              │                                           │                   │
│         Email Found                                 Not Found                │
│              │                                           │                   │
│              ▼                                           ▼                   │
│     Generate reset token                        Show generic message         │
│     Store in database                           (prevent enumeration)        │
│     Send email with link                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     │ User clicks email link
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Step 2: Verify Identity                              │
│                         /reset-password?token=xxx                            │
│                                                                              │
│                          Validate reset token                                │
│                                    │                                         │
│              ┌─────────────────────┴─────────────────────┐                  │
│              │                                           │                   │
│       Token Valid                                  Token Invalid/Expired     │
│              │                                           │                   │
│              ▼                                           ▼                   │
│     Check if TOTP enabled                         Show error message         │
│              │                                                               │
│    ┌─────────┴─────────┐                                                    │
│    │                   │                                                     │
│ TOTP Enabled      No TOTP                                                   │
│    │                   │                                                     │
│    ▼                   ▼                                                     │
│ Show TOTP Form    Show Password Form                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     │ After verification
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Step 3: Set New Password                             │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  New Password:     [••••••••••••••••                 ]               │   │
│  │  Confirm Password: [••••••••••••••••                 ]               │   │
│  │                                                                      │   │
│  │  Requirements:                                                       │   │
│  │  ✓ At least 8 characters                                            │   │
│  │  ✓ Contains uppercase letter                                        │   │
│  │  ✓ Contains lowercase letter                                        │   │
│  │  ✓ Contains number                                                  │   │
│  │  ✓ Contains special character                                       │   │
│  │                                                                      │   │
│  │  [Reset Password]                                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│                    Hash password with Argon2 + pepper                        │
│                    Update user record                                        │
│                    Invalidate reset token                                    │
│                    Invalidate all sessions                                   │
│                    Redirect to login                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Database Schema

### password_reset_tokens Table

```
┌────────────────────────────────────────────────────────────────┐
│                password_reset_tokens table                      │
├──────────────────┬──────────────┬──────────────────────────────┤
│ Column           │ Type         │ Description                  │
├──────────────────┼──────────────┼──────────────────────────────┤
│ id               │ INTEGER PK   │ Auto-increment               │
│ user_id          │ VARCHAR(255) │ User ID reference            │
│ token_hash       │ VARCHAR(255) │ SHA-256 hash of token        │
│ created_at       │ DATETIME     │ Token creation time          │
│ expires_at       │ DATETIME     │ Expiration (1 hour)          │
│ used_at          │ DATETIME     │ When token was used          │
│ ip_address       │ VARCHAR(50)  │ Requester IP                 │
│ user_agent       │ TEXT         │ Browser user agent           │
└──────────────────┴──────────────┴──────────────────────────────┘
```

## Token Generation

### Secure Token Creation

```python
import secrets
import hashlib
from datetime import datetime, timedelta

def generate_reset_token(user_id, ip_address, user_agent):
    """Generate secure password reset token"""
    # Generate cryptographically secure token
    token = secrets.token_urlsafe(32)  # 256 bits of entropy

    # Hash token for storage (never store plaintext)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    # Create database record
    reset_record = PasswordResetToken(
        user_id=user_id,
        token_hash=token_hash,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=1),
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.session.add(reset_record)
    db.session.commit()

    # Return plaintext token (sent to user)
    return token
```

### Token Validation

```python
def validate_reset_token(token):
    """Validate password reset token"""
    # Hash provided token
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    # Find matching record
    record = PasswordResetToken.query.filter_by(
        token_hash=token_hash,
        used_at=None
    ).first()

    if not record:
        return None, "Invalid token"

    # Check expiration
    if datetime.utcnow() > record.expires_at:
        return None, "Token expired"

    return record, None
```

## Password Security

### Argon2 Hashing with Pepper

```python
from argon2 import PasswordHasher
import os

def hash_password(password):
    """Hash password with Argon2 and pepper"""
    pepper = os.environ.get('API_KEY_PEPPER')
    peppered_password = password + pepper

    ph = PasswordHasher(
        time_cost=2,        # 2 iterations
        memory_cost=65536,  # 64 MB
        parallelism=1,      # 1 thread
        hash_len=32,        # 32 byte hash
        salt_len=16         # 16 byte salt
    )

    return ph.hash(peppered_password)

def verify_password(stored_hash, password):
    """Verify password against stored hash"""
    pepper = os.environ.get('API_KEY_PEPPER')
    peppered_password = password + pepper

    ph = PasswordHasher()
    try:
        ph.verify(stored_hash, peppered_password)
        return True
    except:
        return False
```

### Password Requirements

```python
import re

def validate_password_strength(password):
    """Validate password meets security requirements"""
    errors = []

    if len(password) < 8:
        errors.append("Password must be at least 8 characters")

    if not re.search(r'[A-Z]', password):
        errors.append("Password must contain an uppercase letter")

    if not re.search(r'[a-z]', password):
        errors.append("Password must contain a lowercase letter")

    if not re.search(r'[0-9]', password):
        errors.append("Password must contain a number")

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append("Password must contain a special character")

    return len(errors) == 0, errors
```

## TOTP Integration

### Reset with 2FA

```python
def process_reset_with_totp(user_id, totp_code, new_password):
    """Process password reset for TOTP-enabled account"""
    user = User.query.get(user_id)

    # Verify TOTP code
    if not verify_totp(user.totp_secret, totp_code):
        return False, "Invalid TOTP code"

    # Validate password strength
    valid, errors = validate_password_strength(new_password)
    if not valid:
        return False, errors

    # Update password
    user.password_hash = hash_password(new_password)
    user.updated_at = datetime.utcnow()
    db.session.commit()

    # Invalidate all sessions
    invalidate_user_sessions(user_id)

    return True, "Password reset successful"
```

## API Endpoints

### Request Reset

```
POST /api/auth/forgot-password
Content-Type: application/json

{
    "email": "user@example.com"
}
```

**Response:**
```json
{
    "status": "success",
    "message": "If an account exists with this email, a reset link has been sent."
}
```

### Validate Token

```
GET /api/auth/reset-password/validate?token=abc123
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "valid": true,
        "totp_required": true,
        "email": "u***@example.com"
    }
}
```

### Reset Password

```
POST /api/auth/reset-password
Content-Type: application/json

{
    "token": "abc123...",
    "totp_code": "123456",  // Optional, only if TOTP enabled
    "new_password": "NewSecurePass123!",
    "confirm_password": "NewSecurePass123!"
}
```

**Response:**
```json
{
    "status": "success",
    "message": "Password reset successful. Please login with your new password."
}
```

## Reset Flow Implementation

### Full Reset Service

```python
def initiate_password_reset(email, ip_address, user_agent):
    """Initiate password reset process"""
    # Find user (don't reveal if exists)
    user = User.query.filter_by(email=email.lower()).first()

    if not user:
        # Log attempt but don't reveal
        logger.info(f"Reset requested for non-existent email: {email}")
        return True  # Always return success

    # Rate limit: max 3 requests per hour
    recent_tokens = PasswordResetToken.query.filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.created_at > datetime.utcnow() - timedelta(hours=1)
    ).count()

    if recent_tokens >= 3:
        logger.warning(f"Rate limit exceeded for password reset: {email}")
        return True  # Still return success to prevent enumeration

    # Generate and send token
    token = generate_reset_token(user.id, ip_address, user_agent)
    send_password_reset_email(email, token)

    return True

def complete_password_reset(token, new_password, totp_code=None):
    """Complete password reset process"""
    # Validate token
    record, error = validate_reset_token(token)
    if error:
        return False, error

    user = User.query.get(record.user_id)

    # Check if TOTP required
    if user.totp_enabled:
        if not totp_code:
            return False, "TOTP code required"
        if not verify_totp(user.totp_secret, totp_code):
            return False, "Invalid TOTP code"

    # Validate password
    valid, errors = validate_password_strength(new_password)
    if not valid:
        return False, errors

    # Check password not same as current
    if verify_password(user.password_hash, new_password):
        return False, "New password must be different from current password"

    # Update password
    user.password_hash = hash_password(new_password)
    user.updated_at = datetime.utcnow()

    # Mark token as used
    record.used_at = datetime.utcnow()

    db.session.commit()

    # Invalidate all sessions
    invalidate_user_sessions(user.id)

    # Send confirmation email
    send_password_changed_email(user.email)

    return True, "Password reset successful"
```

## Security Measures

### Rate Limiting

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         Rate Limiting Rules                                 │
│                                                                             │
│  Per Email:                                                                 │
│  • Max 3 reset requests per hour                                           │
│  • Max 10 reset requests per day                                           │
│                                                                             │
│  Per IP Address:                                                            │
│  • Max 10 reset requests per hour                                          │
│  • Max 50 reset requests per day                                           │
│                                                                             │
│  Global:                                                                    │
│  • Max 100 reset requests per minute                                       │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### Audit Logging

```python
def log_password_reset_event(user_id, event_type, ip_address, success):
    """Log password reset events for security audit"""
    AuditLog.create(
        user_id=user_id,
        event_type=f"password_reset_{event_type}",
        ip_address=ip_address,
        success=success,
        timestamp=datetime.utcnow()
    )
```

### Token Security

| Measure | Implementation |
|---------|---------------|
| Token entropy | 256 bits (secrets.token_urlsafe(32)) |
| Token storage | SHA-256 hash only |
| Expiration | 1 hour |
| Single use | Marked used after completion |
| IP logging | Request IP recorded |

## Frontend Components

### Forgot Password Form

```typescript
function ForgotPasswordForm() {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    await api.requestPasswordReset(email);
    setSubmitted(true);
  };

  if (submitted) {
    return (
      <div className="text-center">
        <h2>Check Your Email</h2>
        <p>If an account exists with {email}, you'll receive a reset link.</p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Enter your email"
        required
      />
      <button type="submit">Send Reset Link</button>
    </form>
  );
}
```

### Reset Password Form

```typescript
function ResetPasswordForm({ token }: { token: string }) {
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [totpRequired, setTotpRequired] = useState(false);

  // Validate token on mount
  useEffect(() => {
    api.validateResetToken(token)
      .then(data => setTotpRequired(data.totp_required))
      .catch(() => navigate('/forgot-password'));
  }, [token]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    if (password !== confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }

    await api.resetPassword({
      token,
      new_password: password,
      confirm_password: confirmPassword,
      totp_code: totpRequired ? totpCode : undefined
    });

    toast.success('Password reset successful');
    navigate('/login');
  };

  return (
    <form onSubmit={handleSubmit}>
      <PasswordInput
        value={password}
        onChange={setPassword}
        showRequirements
      />
      <PasswordInput
        value={confirmPassword}
        onChange={setConfirmPassword}
        label="Confirm Password"
      />
      {totpRequired && (
        <input
          type="text"
          value={totpCode}
          onChange={(e) => setTotpCode(e.target.value)}
          placeholder="Enter TOTP code"
          maxLength={6}
        />
      )}
      <button type="submit">Reset Password</button>
    </form>
  );
}
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/auth.py` | Reset endpoints and core logic |
| `database/user_db.py` | User model with password hash |
| `utils/email_utils.py` | Password reset email sending |
| `database/settings_db.py` | SMTP settings for email |
| `frontend/src/pages/ForgotPassword.tsx` | Request form |
| `frontend/src/pages/ResetPassword.tsx` | Reset form |

> **Note**: Password reset logic is implemented directly in `blueprints/auth.py`. There are no separate `password_reset_db.py` or `password_reset_service.py` files. Reset tokens are stored in the session rather than a dedicated database table.
