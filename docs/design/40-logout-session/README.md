# 40 - Logout & Session Expiry

## Overview

OpenAlgo implements automatic session expiry at a configurable time daily (default 3:00 AM IST) to ensure security and force re-authentication. When a session expires or user logs out, multiple caches are cleared and tokens are revoked.

## Session Expiry Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Session Expiry Architecture                           │
└──────────────────────────────────────────────────────────────────────────────┘

                         Every Request
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      @app.before_request                                     │
│                      check_session_expiry()                                  │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Skip for:                                                           │   │
│  │  - Static files (/static/)                                           │   │
│  │  - API endpoints (/api/)                                             │   │
│  │  - Public routes (/, /auth/login, /setup, etc.)                      │   │
│  │  - OAuth callbacks (/auth/broker/)                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                               │
│                              ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  is_session_valid()?                                                 │   │
│  │                                                                      │   │
│  │  1. Check session['logged_in'] exists                                │   │
│  │  2. Check session['login_time'] exists                               │   │
│  │  3. Compare current time with SESSION_EXPIRY_TIME                    │   │
│  │     - If now > expiry_time AND login_time < expiry_time → EXPIRED   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                               │
│                    ┌─────────┴─────────┐                                    │
│                    │                   │                                    │
│                 Valid              Expired                                   │
│                    │                   │                                    │
│                    ▼                   ▼                                    │
│              Continue            revoke_user_tokens()                       │
│              Request             session.clear()                            │
│                                  Redirect to login                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Session Expiry Logic

**Location:** `utils/session.py`

### Configuration

```bash
# .env
SESSION_EXPIRY_TIME=03:00  # 3:00 AM IST (24-hour format)
```

### Expiry Check

```python
def is_session_valid():
    """Check if the current session is valid"""
    if not session.get('logged_in'):
        return False

    if 'login_time' not in session:
        return False

    now_ist = datetime.now(pytz.timezone('Asia/Kolkata'))
    login_time = datetime.fromisoformat(session['login_time'])

    # Get configured expiry time (default 03:00)
    expiry_time = os.getenv('SESSION_EXPIRY_TIME', '03:00')
    hour, minute = map(int, expiry_time.split(':'))

    # Today's expiry time
    daily_expiry = now_ist.replace(hour=hour, minute=minute, second=0)

    # Expired if: current time > expiry AND login was before expiry
    if now_ist > daily_expiry and login_time < daily_expiry:
        return False

    return True
```

### Visual Timeline

```
Day 1                                           Day 2
  │                                               │
  │  Login at                                     │
  │  10:00 AM                                     │
  │     │                                         │
  │     ▼                                         │
  │  ───────────────────────────────────────────  │
  │                           │                   │
  │                        3:00 AM                │
  │                     (Expiry Time)             │
  │                           │                   │
  │                           ▼                   │
  │                    SESSION EXPIRED            │
  │                           │                   │
  │                    Must re-login              │
  │                                               │
```

## Token Revocation Process

When session expires or user logs out, these cleanup actions occur:

```
┌─────────────────────────────────────────────────────────────────┐
│                    revoke_user_tokens()                          │
└─────────────────────────────────────────────────────────────────┘

                         User Session
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. Clear Auth Cache                                             │
│     auth_cache[f"auth-{username}"] → delete                     │
│     feed_token_cache[f"feed-{username}"] → delete               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. Clear Symbol Cache                                           │
│     clear_cache_on_logout()                                      │
│     - Remove BrokerSymbolCache for user                         │
│     - Free memory from 100K+ symbols                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. Clear Settings Cache                                         │
│     clear_settings_cache()                                       │
│     - Remove user preferences from memory                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. Clear Strategy Cache                                         │
│     clear_strategy_cache()                                       │
│     - Remove strategy configurations                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. Clear Telegram Cache                                         │
│     clear_telegram_cache()                                       │
│     - Remove bot configurations                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. Revoke Auth Token in Database                                │
│     upsert_auth(username, "", "", revoke=True)                  │
│     - Set is_revoked = True                                     │
│     - Encrypted token becomes invalid                           │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation

### revoke_user_tokens Function

```python
def revoke_user_tokens():
    """Revoke auth tokens for the current user when session expires"""
    if 'user' in session:
        username = session.get('user')

        # 1. Clear auth caches
        cache_key_auth = f"auth-{username}"
        cache_key_feed = f"feed-{username}"
        if cache_key_auth in auth_cache:
            del auth_cache[cache_key_auth]
        if cache_key_feed in feed_token_cache:
            del feed_token_cache[cache_key_feed]

        # 2. Clear symbol cache
        from database.master_contract_cache_hook import clear_cache_on_logout
        clear_cache_on_logout()

        # 3. Clear settings cache
        from database.settings_db import clear_settings_cache
        clear_settings_cache()

        # 4. Clear strategy cache
        from database.strategy_db import clear_strategy_cache
        clear_strategy_cache()

        # 5. Clear telegram cache
        from database.telegram_db import clear_telegram_cache
        clear_telegram_cache()

        # 6. Revoke in database
        upsert_auth(username, "", "", revoke=True)
```

## Session Decorator

```python
def check_session_validity(f):
    """Decorator to check session validity before executing route"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            # Revoke tokens before clearing session
            revoke_user_tokens()
            session.clear()

            # Handle AJAX vs browser requests
            if is_ajax_request():
                return jsonify({
                    'status': 'error',
                    'error': 'session_expired',
                    'message': 'Your session has expired. Please log in again.'
                }), 401

            return redirect(url_for('auth.login'))

        return f(*args, **kwargs)
    return decorated_function
```

## Manual Logout

When user clicks logout:

```python
# blueprints/auth.py
@auth_bp.route('/logout')
def logout():
    """Handle user logout"""
    if 'user' in session:
        username = session.get('user')

        # Revoke tokens
        revoke_user_tokens()

        # Clear session
        session.clear()

        flash('You have been logged out successfully', 'success')

    return redirect(url_for('auth.login'))
```

## What Gets Cleared

| Cache/Data | Location | Purpose | Cleared On |
|------------|----------|---------|------------|
| Auth Token Cache | `auth_cache` (TTLCache) | Broker auth tokens | Logout/Expiry |
| Feed Token Cache | `feed_token_cache` (TTLCache) | WebSocket tokens | Logout/Expiry |
| Symbol Cache | `BrokerSymbolCache` | 100K+ symbols | Logout/Expiry |
| Settings Cache | `settings_cache` | User preferences | Logout/Expiry |
| Strategy Cache | `strategy_cache` | Strategy configs | Logout/Expiry |
| Telegram Cache | `telegram_cache` | Bot settings | Logout/Expiry |
| Database Token | `auth` table | `is_revoked=True` | Logout/Expiry |
| Flask Session | Server-side | All session data | Logout/Expiry |

## Why 3:00 AM IST?

The default expiry time is set to 3:00 AM IST for several reasons:

1. **Market Closed**: Indian markets are closed (NSE: 9:15 AM - 3:30 PM)
2. **Low Activity**: Minimal user activity during this time
3. **Daily Reset**: Forces fresh authentication each trading day
4. **Security**: Limits exposure if credentials are compromised
5. **Token Refresh**: Ensures broker tokens are refreshed daily

## Configuration Options

```bash
# .env configuration
SESSION_EXPIRY_TIME=03:00    # Default: 3:00 AM IST

# Alternative configurations
SESSION_EXPIRY_TIME=03:30    # 3:30 AM IST (after broker token refresh)
SESSION_EXPIRY_TIME=00:00    # Midnight
SESSION_EXPIRY_TIME=15:45    # After market close
```

## Session Lifetime Calculation

```python
def get_session_expiry_time():
    """Get session expiry time set to configured time next occurrence"""
    now_ist = datetime.now(pytz.timezone('Asia/Kolkata'))

    # Get configured expiry time
    expiry_time = os.getenv('SESSION_EXPIRY_TIME', '03:00')
    hour, minute = map(int, expiry_time.split(':'))

    target_time_ist = now_ist.replace(hour=hour, minute=minute, second=0)

    # If current time is past target, set to next day
    if now_ist > target_time_ist:
        target_time_ist += timedelta(days=1)

    remaining_time = target_time_ist - now_ist
    return remaining_time
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `utils/session.py` | Session validation and token revocation |
| `blueprints/auth.py` | Login/logout endpoints |
| `app.py` | `check_session_expiry` before_request hook |
| `database/auth_db.py` | Auth token storage |
| `database/master_contract_cache_hook.py` | Symbol cache clearing |
| `database/settings_db.py` | Settings cache |
| `database/strategy_db.py` | Strategy cache |
| `database/telegram_db.py` | Telegram cache |
