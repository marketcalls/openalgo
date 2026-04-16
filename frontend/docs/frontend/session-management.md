# Session Management

## Overview

OpenAlgo supports multi-device login with automatic session synchronization. A user can authenticate once with their broker (OAuth) and then access OpenAlgo from additional devices without repeating the broker login flow.

## Architecture

```
Device A (Desktop)                    Server                    Device B (Mobile)
     |                                  |                            |
     |-- POST /auth/login ------------>|                            |
     |   (username + password)         |                            |
     |                                 |-- Check DB for valid      |
     |                                 |   broker token            |
     |                                 |-- Validate via funds API  |
     |                                 |                            |
     |<-- {redirect: /dashboard} ------|                            |
     |   (session cookie set)          |                            |
     |                                 |                            |
     |                                 |   (Later, from mobile)     |
     |                                 |<-- POST /auth/login -------|
     |                                 |   (username + password)    |
     |                                 |-- Find existing token      |
     |                                 |-- Validate via funds API   |
     |                                 |-- Resume session (no OAuth)|
     |                                 |-----> {redirect: /dashboard}
     |                                 |                            |
     |   (Logout from any device)      |                            |
     |-- POST /auth/logout ----------->|                            |
     |                                 |-- Revoke broker token      |
     |                                 |-- Clear all sessions       |
     |                                 |-- Emit force_logout ------>|
     |                                 |                            |-- Auto-redirect
     |                                 |                            |   to /login
```

## Login Flow

### Single Device (First Login of the Day)

1. User enters username/password at `/login`
2. Server checks DB for an existing non-revoked broker token
3. **No valid token found** -> redirect to `/broker` for OAuth
4. User completes broker OAuth (Zerodha, Dhan, etc.)
5. `handle_auth_success()` stores token in DB + sets session cookie
6. User lands on `/dashboard`

### Multi-Device (Session Resume)

1. User enters username/password on a second device
2. Server finds a valid broker token in the DB (from device A's login)
3. Server validates the token with a lightweight `get_margin_data()` API call
4. **Token valid** -> `handle_auth_success()` creates a new session cookie for this device
5. Returns `{redirect: "/dashboard", broker: "dhan"}` -> user goes straight to dashboard
6. **Token invalid/expired** -> falls through to normal OAuth flow

### Token Validation

The resume flow validates the broker token by calling the broker's funds API (`get_margin_data()`). This is chosen because:
- It's lightweight (single API call, no side effects)
- It returns an empty dict `{}` if the token is expired/invalid
- It works consistently across all 24+ brokers

If the funds API returns empty or throws, the resume is aborted and the user is redirected to broker OAuth.

## Session Storage

### Flask Session (Client-Side Cookie)

- Signed by `APP_KEY` (tamper-proof, not encrypted)
- Contains: `logged_in`, `AUTH_TOKEN`, `broker`, `session_id`, `login_time`
- `HttpOnly`, `SameSite=Lax`, `Secure` (when HTTPS enabled)
- Expires daily at 3:00 AM IST (configurable via `SESSION_EXPIRY_TIME`)

### Auth Table (Server-Side)

- `auth` table stores encrypted broker token per user (single row, upserted)
- `is_revoked` flag marks invalid tokens
- Shared across all devices (devices read the same token)

### ActiveSession Table (Server-Side)

- Tracks which devices are currently logged in
- Columns: `username`, `session_id`, `device_info` (User-Agent), `ip_address`, `broker`, `login_time`, `last_seen`
- Deduplication: same `(username, ip_address)` replaces old entry
- Safety cap: maximum 5 sessions per user (oldest evicted)
- Cleared on logout and on 3 AM auto-expiry

## Logout Behavior

Logout from **any device** triggers a global logout:

1. Broker token revoked in DB (`is_revoked = True`)
2. All `ActiveSession` rows for the user are deleted
3. `force_logout` SocketIO event emitted to all connected clients
4. Other devices receive the event, show an error toast, and redirect to `/login`
5. Session cookie cleared on the requesting device

### 3 AM Auto-Expiry

- `is_session_valid()` checks if current time has passed the daily expiry (3 AM IST)
- On expiry: `revoke_user_tokens()` revokes the DB token and clears all active sessions
- Next login requires fresh broker OAuth (correct for Indian brokers with daily token validity)
- Crypto brokers can disable expiry via `DISABLE_SESSION_EXPIRY=true`

## Frontend Integration

### Zustand Auth Store

- `useAuthStore` persists `{username, broker, isLoggedIn}` to `localStorage`
- On login with resume, the backend returns `broker` in the response so the store is populated immediately (avoids Layout redirect guard)

### Active Sessions in Footer

- Initial count loaded from `GET /auth/session-status` (`active_sessions` field)
- Live updates via `active_sessions_update` SocketIO event (no polling)
- Displayed as `[Monitor icon] N sessions` badge in the footer

### Force Logout (SocketIO)

- `force_logout` event triggers immediate client-side logout
- Shows error toast: "You have been logged out from another device."
- 2-second delay before redirect so user sees the message

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/auth/login` | POST | Username/password auth + session resume attempt |
| `/auth/logout` | POST | Logout all devices, revoke broker token |
| `/auth/session-status` | GET | Session info + `active_sessions` count |
| `/auth/active-sessions` | GET | Full list of active sessions with device info |

## Security

- **Password required**: Session resume only works after valid username/password authentication
- **Token validation**: Broker token is validated with a live API call before resume
- **Session ID**: Generated with `secrets.token_hex(32)` (cryptographically secure)
- **Session cap**: Maximum 5 active sessions per user (prevents unbounded growth)
- **IP deduplication**: Repeated logins from the same IP replace the old session entry
- **Global logout**: Any device can trigger logout for all devices
- **Auto-cleanup**: 3 AM IST daily expiry clears all sessions and revokes broker tokens

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `SESSION_EXPIRY_TIME` | `03:00` | Daily session expiry time (HH:MM, IST) |
| `DISABLE_SESSION_EXPIRY` | `false` | Set to `true` for crypto brokers (24/7) |
| `APP_KEY` | (required) | Flask secret key for signing session cookies |
