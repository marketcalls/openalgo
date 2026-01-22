# 03 - Login and Broker Login Flow

## Overview

OpenAlgo implements a two-phase authentication system:
1. **User Authentication** - Username/password login to OpenAlgo
2. **Broker Authentication** - OAuth2/TOTP/API-based login to trading broker

This design ensures users first authenticate with OpenAlgo before connecting to their broker account.

## Authentication Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         Complete Authentication Flow                             │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│   User      │     │   Login     │     │   Broker    │     │   Dashboard     │
│   Browser   │     │   Page      │     │   Select    │     │   (Protected)   │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └────────┬────────┘
       │                   │                   │                      │
       │  1. GET /         │                   │                      │
       ├──────────────────►│                   │                      │
       │                   │                   │                      │
       │  2. Check Setup   │                   │                      │
       │◄──────────────────┤                   │                      │
       │  (No users? → /setup)                 │                      │
       │                   │                   │                      │
       │  3. POST /auth/login                  │                      │
       │  {username, password}                 │                      │
       ├──────────────────►│                   │                      │
       │                   │                   │                      │
       │  4. Argon2 verify │                   │                      │
       │  Set session['user']                  │                      │
       │◄──────────────────┤                   │                      │
       │                   │                   │                      │
       │  5. Redirect /broker                  │                      │
       ├───────────────────┼──────────────────►│                      │
       │                   │                   │                      │
       │  6. Select Broker │                   │                      │
       │  (OAuth/TOTP/API) │                   │                      │
       │◄──────────────────┼───────────────────┤                      │
       │                   │                   │                      │
       │  7. Broker Auth   │                   │                      │
       │  /{broker}/callback                   │                      │
       ├───────────────────┼──────────────────►│                      │
       │                   │                   │                      │
       │  8. handle_auth_success()             │                      │
       │  - Set session['logged_in'] = True    │                      │
       │  - Store auth_token (encrypted)       │                      │
       │  - Start master contract download     │                      │
       │◄──────────────────┼───────────────────┤                      │
       │                   │                   │                      │
       │  9. Redirect /dashboard               │                      │
       ├───────────────────┼───────────────────┼─────────────────────►│
       │                   │                   │                      │
       └───────────────────┴───────────────────┴──────────────────────┘
```

## Phase 1: User Authentication

### Initial Setup Check

On first access, the system checks if any users exist:

```python
# blueprints/auth.py
@auth_bp.route('/check-setup', methods=['GET'])
def check_setup_required():
    """Check if initial setup is required (no users exist)."""
    needs_setup = find_user_by_username() is None
    return jsonify({
        'status': 'success',
        'needs_setup': needs_setup
    })
```

**Flow:**
- No users → Redirect to `/setup` for first-time configuration
- Users exist → Show login page

### Login Endpoint

**Endpoint:** `POST /auth/login`

**Rate Limits:**
- `5 per minute`
- `25 per hour`

```python
# blueprints/auth.py
@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if authenticate_user(username, password):
            session['user'] = username  # Set username in session
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401
```

### Password Validation

Passwords must meet these requirements:

```python
# utils/auth_utils.py
def validate_password_strength(password):
    """
    Requirements:
    - Minimum 8 characters
    - At least 1 uppercase letter (A-Z)
    - At least 1 lowercase letter (a-z)
    - At least 1 number (0-9)
    - At least 1 special character (!@#$%^&*)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    # ... additional checks
```

### Password Hashing

User passwords are hashed using Argon2 with pepper:

```python
# database/user_db.py
class User:
    def set_password(self, password):
        # Add pepper from environment
        pepper = os.getenv('API_KEY_PEPPER')
        peppered_password = f"{password}{pepper}"
        # Hash with Argon2
        self.password_hash = argon2_hasher.hash(peppered_password)

    def check_password(self, password):
        pepper = os.getenv('API_KEY_PEPPER')
        peppered_password = f"{password}{pepper}"
        return argon2_hasher.verify(self.password_hash, peppered_password)
```

## Phase 2: Broker Authentication

### Broker Types and Auth Methods

OpenAlgo supports 24+ brokers with different authentication methods:

| Auth Type | Brokers | Flow |
|-----------|---------|------|
| **OAuth2** | Zerodha, Fyers, Flattrade, Dhan, ICICI, Pocketful | Redirect → Callback with code |
| **TOTP** | Angel, 5Paisa, Kotak, Shoonya, Firstock, AliceBlue, Motilal | Form + TOTP code |
| **OTP** | Definedge | Email/SMS OTP verification |
| **API Key** | Dhan (direct), Groww, IndMoney | Direct token auth |
| **XTS** | 5PaisaXTS, JainamXTS, IIFL, Wisdom | Server-to-server token |

### OAuth2 Flow (e.g., Zerodha)

```
┌─────────────────────────────────────────────────────────────────┐
│                     OAuth2 Authentication                        │
└─────────────────────────────────────────────────────────────────┘

User                    OpenAlgo                    Broker OAuth
  │                        │                            │
  │  1. Select Zerodha     │                            │
  ├───────────────────────►│                            │
  │                        │                            │
  │  2. Redirect to broker OAuth URL                    │
  │◄───────────────────────┤                            │
  │                        │                            │
  │  3. Browser redirects to broker                     │
  ├────────────────────────┼───────────────────────────►│
  │                        │                            │
  │  4. User logs in at broker                          │
  │◄───────────────────────┼────────────────────────────┤
  │                        │                            │
  │  5. Broker redirects with auth_code                 │
  │     GET /zerodha/callback?request_token=xxx         │
  ├───────────────────────►│                            │
  │                        │                            │
  │                        │  6. Exchange code for token│
  │                        ├───────────────────────────►│
  │                        │                            │
  │                        │  7. Return access_token    │
  │                        │◄───────────────────────────┤
  │                        │                            │
  │  8. Store token, redirect to dashboard              │
  │◄───────────────────────┤                            │
  │                        │                            │
```

### TOTP Flow (e.g., Angel)

```
┌─────────────────────────────────────────────────────────────────┐
│                     TOTP Authentication                          │
└─────────────────────────────────────────────────────────────────┘

User                    OpenAlgo                    Broker API
  │                        │                            │
  │  1. Select Angel       │                            │
  ├───────────────────────►│                            │
  │                        │                            │
  │  2. Show TOTP form     │                            │
  │◄───────────────────────┤                            │
  │  (userid, pin, totp)   │                            │
  │                        │                            │
  │  3. POST /angel/callback                            │
  │  {userid, pin, totp}   │                            │
  ├───────────────────────►│                            │
  │                        │                            │
  │                        │  4. Call broker auth API   │
  │                        │  authenticate_broker()     │
  │                        ├───────────────────────────►│
  │                        │                            │
  │                        │  5. Return auth_token,     │
  │                        │     feed_token             │
  │                        │◄───────────────────────────┤
  │                        │                            │
  │  6. Store tokens, redirect                          │
  │◄───────────────────────┤                            │
  │                        │                            │
```

### Broker Callback Handler

The universal callback handler processes all broker authentication:

```python
# blueprints/brlogin.py
@brlogin_bp.route('/<broker>/callback', methods=['POST','GET'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def broker_callback(broker):
    # 1. Check session validity
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    # 2. Get broker-specific auth function
    broker_auth_functions = app.broker_auth_functions
    auth_function = broker_auth_functions.get(f'{broker}_auth')

    # 3. Handle broker-specific authentication
    if broker == 'angel':
        clientcode = request.form.get('userid')
        broker_pin = request.form.get('pin')
        totp_code = request.form.get('totp')
        auth_token, feed_token, error = auth_function(clientcode, broker_pin, totp_code)

    elif broker == 'zerodha':
        code = request.args.get('request_token')
        auth_token, error = auth_function(code)
        auth_token = f'{BROKER_API_KEY}:{auth_token}'  # Zerodha format

    # ... broker-specific handling

    # 4. Handle success or failure
    if auth_token:
        return handle_auth_success(auth_token, session['user'], broker, feed_token)
    else:
        return handle_auth_failure(error)
```

### Authentication Success Handler

After successful broker authentication:

```python
# utils/auth_utils.py
def handle_auth_success(auth_token, user_session_key, broker, feed_token=None, user_id=None):
    """
    Handles common tasks after successful authentication.
    """
    # 1. Set session parameters
    session['logged_in'] = True
    session['AUTH_TOKEN'] = auth_token
    session['broker'] = broker
    if feed_token:
        session['FEED_TOKEN'] = feed_token
    if user_id:
        session['USER_ID'] = user_id

    # 2. Set session expiry (3:30 AM IST)
    app.config['PERMANENT_SESSION_LIFETIME'] = get_session_expiry_time()
    session.permanent = True
    set_session_login_time()

    # 3. Store auth token in database (encrypted with Fernet)
    inserted_id = upsert_auth(user_session_key, auth_token, broker, feed_token, user_id)

    # 4. Start async master contract download
    if inserted_id:
        init_broker_status(broker)
        thread = Thread(target=async_master_contract_download, args=(broker,))
        thread.start()

    # 5. Return appropriate response
    if is_ajax_request():
        return jsonify({"status": "success", "redirect": "/dashboard"}), 200
    else:
        return redirect(url_for('dashboard_bp.dashboard'))
```

## Session Management

### Session Data Structure

```python
session = {
    'user': 'username',           # Set after user login
    'logged_in': True,            # Set after broker auth
    'AUTH_TOKEN': 'encrypted...',  # Broker auth token
    'FEED_TOKEN': '...',          # WebSocket feed token (if available)
    'USER_ID': '...',             # Broker user ID (if available)
    'broker': 'zerodha',          # Current broker name
    'user_session_key': '...'     # Session key for DB lookup
}
```

### Session Expiry

Sessions expire daily at 3:30 AM IST to align with market schedules:

```python
# utils/session.py
def get_session_expiry_time():
    """Calculate session expiry to 3:30 AM IST next day"""
    now_utc = datetime.now(timezone.utc)
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = now_utc.astimezone(ist)

    # Calculate next 3:30 AM IST
    target_time = now_ist.replace(hour=3, minute=30, second=0, microsecond=0)
    if now_ist >= target_time:
        target_time += timedelta(days=1)

    return target_time - now_ist
```

### Session Cookie Security

```python
# app.py
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,      # Prevent XSS access
    SESSION_COOKIE_SAMESITE='Lax',     # CSRF protection
    SESSION_COOKIE_SECURE=USE_HTTPS,   # HTTPS only when configured
    SESSION_COOKIE_NAME='session'       # Cookie name
)

# HTTPS environments get secure prefix
if USE_HTTPS:
    app.config['SESSION_COOKIE_NAME'] = f'__Secure-{session_cookie_name}'
```

## Token Storage

### Auth Token Encryption

Broker auth tokens are encrypted before database storage:

```python
# database/auth_db.py
def get_encryption_key():
    """Generate Fernet key from pepper using PBKDF2"""
    pepper = os.getenv('API_KEY_PEPPER').encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'openalgo_salt_v1',
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(pepper))

def encrypt_token(token):
    """Encrypt auth token with Fernet"""
    fernet = Fernet(get_encryption_key())
    return fernet.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token):
    """Decrypt auth token"""
    fernet = Fernet(get_encryption_key())
    return fernet.decrypt(encrypted_token.encode()).decode()
```

### Database Schema (Auth)

```sql
CREATE TABLE auth (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    auth_token TEXT,           -- Encrypted with Fernet
    broker TEXT,
    feed_token TEXT,           -- For WebSocket streaming
    user_id TEXT,              -- Broker-specific user ID
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    revoked BOOLEAN DEFAULT FALSE
);
```

## Password Reset Flow

### Reset Methods

1. **TOTP-based** - Using authenticator app
2. **Email-based** - Reset link sent to registered email

```
┌─────────────────────────────────────────────────────────────────┐
│                    Password Reset Flow                           │
└─────────────────────────────────────────────────────────────────┘

                    ┌──────────────────┐
                    │  Enter Email     │
                    └────────┬─────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
    ┌─────────────────┐           ┌─────────────────┐
    │  TOTP Method    │           │  Email Method   │
    │  (Authenticator)│           │  (SMTP)         │
    └────────┬────────┘           └────────┬────────┘
             │                             │
             ▼                             ▼
    ┌─────────────────┐           ┌─────────────────┐
    │  Enter 6-digit  │           │  Click reset    │
    │  TOTP code      │           │  link in email  │
    └────────┬────────┘           └────────┬────────┘
             │                             │
             └──────────────┬──────────────┘
                            ▼
                  ┌─────────────────┐
                  │  Enter new      │
                  │  password       │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │  Password       │
                  │  updated        │
                  └─────────────────┘
```

### Reset Endpoint

```python
# blueprints/auth.py
@auth_bp.route('/reset-password', methods=['POST'])
@limiter.limit(RESET_RATE_LIMIT)  # 15 per hour
def reset_password():
    step = request.get_json().get('step')

    if step == 'email':
        # Verify email exists (always return success to prevent enumeration)
        user = find_user_by_email(email)
        if user:
            session['reset_email'] = email
        return jsonify({'status': 'success', 'message': 'Email verified'})

    elif step == 'totp':
        user = find_user_by_email(email)
        if user and user.verify_totp(totp_code):
            token = secrets.token_urlsafe(32)
            session['reset_token'] = token
            return jsonify({'status': 'success', 'token': token})

    elif step == 'password':
        # Validate token and update password
        if token == session.get('reset_token'):
            user.set_password(password)
            db_session.commit()
            return jsonify({'status': 'success'})
```

## Frontend Session Sync

### React AuthSync Component

The React frontend synchronizes with Flask session state:

```typescript
// components/auth/AuthSync.tsx
useEffect(() => {
  const checkSession = async () => {
    const response = await fetch('/auth/session-status')
    const data = await response.json()

    if (data.authenticated) {
      authStore.setUser({
        username: data.user,
        broker: data.broker,
        isLoggedIn: data.logged_in
      })
      if (data.api_key) {
        authStore.setApiKey(data.api_key)
      }
    }
  }
  checkSession()
}, [])
```

### Session Status Endpoint

```python
# blueprints/auth.py
@auth_bp.route('/session-status', methods=['GET'])
def get_session_status():
    """Return current session status for React SPA."""
    if 'user' not in session:
        return jsonify({'authenticated': False}), 401

    # Validate auth token exists if logged_in
    if session.get('logged_in') and session.get('broker'):
        auth_token = get_auth_token(session.get('user'))
        if auth_token is None:
            session.clear()  # Clear stale session
            return jsonify({'authenticated': False}), 401

    return jsonify({
        'authenticated': True,
        'logged_in': session.get('logged_in', False),
        'user': session.get('user'),
        'broker': session.get('broker'),
        'api_key': get_api_key_for_tradingview(session.get('user'))
    })
```

## Logout Flow

```python
# blueprints/auth.py
@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    if session.get('logged_in'):
        username = session['user']

        # 1. Clear caches
        del auth_cache[f"auth-{username}"]
        del feed_token_cache[f"feed-{username}"]
        clear_cache_on_logout()  # Symbol cache

        # 2. Revoke auth in database
        upsert_auth(username, "", "", revoke=True)

        # 3. Clear session
        session.clear()

    if request.method == 'POST':
        return jsonify({'status': 'success'})
    return redirect(url_for('auth.login'))
```

## Security Considerations

### Rate Limiting

| Endpoint | Limit |
|----------|-------|
| `/auth/login` | 5/min, 25/hour |
| `/{broker}/callback` | 5/min, 25/hour |
| `/auth/reset-password` | 15/hour |

### User Enumeration Prevention

Password reset always returns success regardless of email existence:

```python
# Always show the same response to prevent user enumeration
if user:
    session['reset_email'] = email
return jsonify({'status': 'success', 'message': 'Email verified'})
```

### CSRF Protection

All POST endpoints (except webhooks) require CSRF tokens:

```python
# Frontend fetches token before requests
const csrfToken = await fetch('/auth/csrf-token')
headers['X-CSRFToken'] = csrfToken
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/auth.py` | User authentication endpoints |
| `blueprints/brlogin.py` | Broker callback handlers |
| `utils/auth_utils.py` | Auth helpers, password validation |
| `database/auth_db.py` | Auth token storage with encryption |
| `database/user_db.py` | User model with Argon2 hashing |
| `utils/session.py` | Session expiry calculation |
| `frontend/src/stores/authStore.ts` | Client-side auth state |
| `frontend/src/components/auth/AuthSync.tsx` | Session synchronization |
