# 50 - TOTP Configuration

## Overview

OpenAlgo supports Time-based One-Time Password (TOTP) for two-factor authentication. Users can enable 2FA through QR code scanning with authenticator apps like Google Authenticator, Authy, or Microsoft Authenticator.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        TOTP Configuration Architecture                        │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         TOTP Setup Flow                                      │
│                                                                              │
│  Step 1: Generate Secret                                                     │
│  ─────────────────────────                                                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  User requests 2FA setup                                             │   │
│  │           │                                                          │   │
│  │           ▼                                                          │   │
│  │  Generate base32 secret (160 bits)                                  │   │
│  │  JBSWY3DPEHPK3PXP...                                                │   │
│  │           │                                                          │   │
│  │           ▼                                                          │   │
│  │  Generate provisioning URI                                          │   │
│  │  otpauth://totp/OpenAlgo:user@example.com?secret=...&issuer=OpenAlgo│   │
│  │           │                                                          │   │
│  │           ▼                                                          │   │
│  │  Generate QR code image                                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  Step 2: User Scans QR Code                                                 │
│  ─────────────────────────────                                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │   ┌───────────────────┐      Scan with           ┌──────────────┐   │   │
│  │   │  ████████████████ │    ───────────────►      │  Authenticator│   │   │
│  │   │  █              █ │                          │  App          │   │   │
│  │   │  █  QR CODE     █ │                          │               │   │   │
│  │   │  █              █ │                          │   123456      │   │   │
│  │   │  ████████████████ │                          │   ──────      │   │   │
│  │   └───────────────────┘                          │   29 sec      │   │   │
│  │                                                  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  Step 3: Verify and Enable                                                  │
│  ──────────────────────────                                                  │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  User enters code from app                                           │   │
│  │           │                                                          │   │
│  │           ▼                                                          │   │
│  │  Verify code against secret                                         │   │
│  │           │                                                          │   │
│  │           ├──► Valid: Enable TOTP, store encrypted secret           │   │
│  │           │                                                          │   │
│  │           └──► Invalid: Show error, allow retry                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Database Schema

### TOTP Fields in users Table

```
┌────────────────────────────────────────────────────────────────┐
│                  users table (TOTP fields)                      │
├──────────────────┬──────────────┬──────────────────────────────┤
│ Column           │ Type         │ Description                  │
├──────────────────┼──────────────┼──────────────────────────────┤
│ totp_enabled     │ BOOLEAN      │ Is 2FA enabled               │
│ totp_secret      │ TEXT         │ Encrypted base32 secret      │
│ totp_setup_at    │ DATETIME     │ When 2FA was enabled         │
│ backup_codes     │ TEXT         │ Encrypted backup codes       │
└──────────────────┴──────────────┴──────────────────────────────┘
```

## TOTP Implementation

### Secret Generation

```python
import pyotp
import base64
from cryptography.fernet import Fernet

def generate_totp_secret():
    """Generate new TOTP secret"""
    # Generate 160-bit (20 bytes) random secret
    secret = pyotp.random_base32(length=32)
    return secret

def get_provisioning_uri(secret, email, issuer="OpenAlgo"):
    """Generate provisioning URI for QR code"""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(
        name=email,
        issuer_name=issuer
    )
```

### QR Code Generation

```python
import qrcode
import io
import base64

def generate_qr_code(provisioning_uri):
    """Generate QR code image as base64"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4
    )
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to base64
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    return base64.b64encode(buffer.read()).decode()
```

### Code Verification

```python
def verify_totp(secret, code, window=1):
    """Verify TOTP code"""
    if not secret or not code:
        return False

    # Decrypt secret if stored encrypted
    decrypted_secret = decrypt_totp_secret(secret)

    totp = pyotp.TOTP(decrypted_secret)

    # Verify with time window (allows for clock drift)
    # window=1 means ±30 seconds
    return totp.verify(code, valid_window=window)
```

### Secret Encryption

```python
def encrypt_totp_secret(secret):
    """Encrypt TOTP secret for storage"""
    key = get_fernet_key()
    fernet = Fernet(key)
    return fernet.encrypt(secret.encode()).decode()

def decrypt_totp_secret(encrypted_secret):
    """Decrypt TOTP secret for use"""
    key = get_fernet_key()
    fernet = Fernet(key)
    return fernet.decrypt(encrypted_secret.encode()).decode()
```

## Backup Codes

### Generation

```python
import secrets

def generate_backup_codes(count=10):
    """Generate backup recovery codes"""
    codes = []
    for _ in range(count):
        # Generate 8-character alphanumeric code
        code = secrets.token_hex(4).upper()
        # Format as XXXX-XXXX
        formatted = f"{code[:4]}-{code[4:]}"
        codes.append(formatted)
    return codes

def hash_backup_codes(codes):
    """Hash backup codes for storage"""
    import hashlib
    hashed = []
    for code in codes:
        # Remove formatting for hashing
        clean_code = code.replace('-', '')
        hashed.append(hashlib.sha256(clean_code.encode()).hexdigest())
    return hashed
```

### Usage

```python
def use_backup_code(user_id, code):
    """Use backup code for authentication"""
    user = User.query.get(user_id)

    # Get stored hashed codes
    stored_codes = json.loads(user.backup_codes or '[]')

    # Hash provided code
    clean_code = code.replace('-', '').upper()
    code_hash = hashlib.sha256(clean_code.encode()).hexdigest()

    if code_hash in stored_codes:
        # Remove used code
        stored_codes.remove(code_hash)
        user.backup_codes = json.dumps(stored_codes)
        db.session.commit()
        return True

    return False
```

## API Endpoints

### Initialize TOTP Setup

```
POST /api/auth/totp/setup
Authorization: Bearer USER_TOKEN
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "secret": "JBSWY3DPEHPK3PXP",
        "qr_code": "data:image/png;base64,iVBORw0KGgo...",
        "provisioning_uri": "otpauth://totp/OpenAlgo:user@example.com?secret=JBSWY3DPEHPK3PXP&issuer=OpenAlgo"
    }
}
```

### Enable TOTP

```
POST /api/auth/totp/enable
Content-Type: application/json
Authorization: Bearer USER_TOKEN

{
    "code": "123456",
    "secret": "JBSWY3DPEHPK3PXP"
}
```

**Response:**
```json
{
    "status": "success",
    "message": "Two-factor authentication enabled",
    "data": {
        "backup_codes": [
            "A1B2-C3D4",
            "E5F6-G7H8",
            "I9J0-K1L2",
            "M3N4-O5P6",
            "Q7R8-S9T0"
        ]
    }
}
```

### Disable TOTP

```
POST /api/auth/totp/disable
Content-Type: application/json
Authorization: Bearer USER_TOKEN

{
    "code": "123456",
    "password": "current_password"
}
```

### Verify TOTP (Login)

```
POST /api/auth/totp/verify
Content-Type: application/json

{
    "session_token": "pending_session_token",
    "code": "123456"
}
```

## Login Flow with TOTP

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        Login with TOTP Flow                                 │
│                                                                             │
│  1. User submits username/password                                         │
│           │                                                                 │
│           ▼                                                                 │
│  2. Validate credentials                                                   │
│           │                                                                 │
│           ├──► Invalid: Return error                                       │
│           │                                                                 │
│           ▼                                                                 │
│  3. Check if TOTP enabled                                                  │
│           │                                                                 │
│           ├──► Not enabled: Issue session token, login complete            │
│           │                                                                 │
│           ▼                                                                 │
│  4. TOTP enabled: Return pending session                                   │
│           │                                                                 │
│           │    {                                                            │
│           │      "status": "totp_required",                                │
│           │      "session_token": "pending_xxx"                            │
│           │    }                                                            │
│           │                                                                 │
│           ▼                                                                 │
│  5. User enters TOTP code                                                  │
│           │                                                                 │
│           ▼                                                                 │
│  6. Verify TOTP code                                                       │
│           │                                                                 │
│           ├──► Valid: Upgrade to full session, login complete              │
│           │                                                                 │
│           └──► Invalid: Allow retry (max 5 attempts)                       │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### Implementation

```python
def login_with_credentials(username, password):
    """First step: validate credentials"""
    user = authenticate_user(username, password)
    if not user:
        return {'status': 'error', 'message': 'Invalid credentials'}

    if user.totp_enabled:
        # Create pending session
        pending_token = create_pending_session(user.id)
        return {
            'status': 'totp_required',
            'session_token': pending_token
        }

    # No TOTP, complete login
    session_token = create_session(user.id)
    return {
        'status': 'success',
        'session_token': session_token
    }

def verify_totp_login(pending_token, code):
    """Second step: verify TOTP"""
    pending = get_pending_session(pending_token)
    if not pending:
        return {'status': 'error', 'message': 'Invalid session'}

    user = User.query.get(pending['user_id'])

    if verify_totp(user.totp_secret, code):
        # Upgrade to full session
        session_token = create_session(user.id)
        delete_pending_session(pending_token)
        return {
            'status': 'success',
            'session_token': session_token
        }

    return {'status': 'error', 'message': 'Invalid TOTP code'}
```

## Frontend Components

### TOTP Setup Component

```typescript
function TOTPSetup() {
  const [step, setStep] = useState<'init' | 'verify' | 'backup'>('init');
  const [secret, setSecret] = useState('');
  const [qrCode, setQrCode] = useState('');
  const [code, setCode] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);

  const initSetup = async () => {
    const data = await api.initTOTPSetup();
    setSecret(data.secret);
    setQrCode(data.qr_code);
    setStep('verify');
  };

  const verifyAndEnable = async () => {
    const data = await api.enableTOTP(code, secret);
    setBackupCodes(data.backup_codes);
    setStep('backup');
  };

  if (step === 'init') {
    return (
      <div className="text-center">
        <h2>Enable Two-Factor Authentication</h2>
        <p>Add an extra layer of security to your account</p>
        <button onClick={initSetup} className="btn btn-primary">
          Get Started
        </button>
      </div>
    );
  }

  if (step === 'verify') {
    return (
      <div className="space-y-4">
        <h2>Scan QR Code</h2>
        <p>Scan with your authenticator app</p>

        <div className="flex justify-center">
          <img src={`data:image/png;base64,${qrCode}`} alt="TOTP QR Code" />
        </div>

        <div className="text-sm">
          <p>Can't scan? Enter manually:</p>
          <code className="bg-base-200 px-2 py-1 rounded">{secret}</code>
        </div>

        <div>
          <label>Enter code from app</label>
          <input
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            maxLength={6}
            className="input input-bordered"
            placeholder="000000"
          />
        </div>

        <button onClick={verifyAndEnable} className="btn btn-primary">
          Verify & Enable
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h2>Save Backup Codes</h2>
      <p className="text-warning">
        Save these codes securely. You'll need them if you lose access to your authenticator.
      </p>

      <div className="grid grid-cols-2 gap-2 bg-base-200 p-4 rounded">
        {backupCodes.map((code, i) => (
          <code key={i} className="font-mono">{code}</code>
        ))}
      </div>

      <button
        onClick={() => downloadBackupCodes(backupCodes)}
        className="btn btn-secondary"
      >
        Download Codes
      </button>

      <button onClick={onComplete} className="btn btn-primary">
        Done
      </button>
    </div>
  );
}
```

### TOTP Login Component

```typescript
function TOTPVerification({ sessionToken, onSuccess }: Props) {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');

  const handleVerify = async () => {
    try {
      const result = await api.verifyTOTP(sessionToken, code);
      onSuccess(result.session_token);
    } catch (e) {
      setError('Invalid code. Please try again.');
      setCode('');
    }
  };

  return (
    <div className="space-y-4">
      <h2>Two-Factor Authentication</h2>
      <p>Enter the code from your authenticator app</p>

      {error && <div className="alert alert-error">{error}</div>}

      <input
        type="text"
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
        maxLength={6}
        className="input input-bordered text-center text-2xl tracking-widest"
        placeholder="000000"
        autoFocus
      />

      <button
        onClick={handleVerify}
        disabled={code.length !== 6}
        className="btn btn-primary w-full"
      >
        Verify
      </button>

      <button className="btn btn-link">
        Use backup code instead
      </button>
    </div>
  );
}
```

## Security Considerations

| Aspect | Implementation |
|--------|---------------|
| Secret storage | Fernet encrypted in database |
| Code validity | 30 seconds (RFC 6238) |
| Clock drift | ±1 window (±30 seconds) |
| Rate limiting | Max 5 attempts per pending session |
| Backup codes | One-time use, SHA-256 hashed |
| Recovery | Email reset requires TOTP or backup code |

## Key Files Reference

| File | Purpose |
|------|---------|
| `database/user_db.py` | User model with TOTP methods (`get_totp_uri()`, `verify_totp()`) |
| `blueprints/auth.py` | TOTP endpoints (reset-password with TOTP) |
| `frontend/src/pages/TwoFactorSettings.tsx` | Setup UI |
| `frontend/src/components/TOTPVerification.tsx` | Login verification |

> **Note**: TOTP functionality is integrated directly into the `User` model in `database/user_db.py`. The model includes:
> - `totp_secret` field - stores the TOTP secret
> - `get_totp_uri()` method - generates provisioning URI for QR codes using `pyotp`
> - `verify_totp()` method - verifies TOTP tokens
>
> There are no separate `services/totp_service.py` or `utils/totp_utils.py` files. QR code generation uses the `pyotp` library's `provisioning_uri()` method.
