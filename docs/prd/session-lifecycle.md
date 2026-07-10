# Session Lifecycle PRD

## Purpose

OpenAlgo separates device-specific application sessions from the installation-wide active broker session. This lets a user reconnect one device without unnecessarily interrupting the shared broker market-data feed used by other devices.

## Requirements

- An authenticated login creates an `active_sessions` row identified by a session ID.
- A new session for the same user and IP replaces the prior row.
- At most five active-session rows are retained per user; older rows are removed.
- SPA session-status polling reports the current active-session count.
- `last_seen` updates are throttled to at most once every 30 seconds per session.
- A valid app session survives broker-token expiry and receives `broker_session_expired` so the UI can offer reconnect.
- Re-authentication compares decrypted broker and feed tokens. Unchanged plaintext tokens must not trigger cross-process feed teardown merely because Fernet ciphertext changed.
- Password changes revoke every active device session and emit a force-logout event.
- Normal logout clears the current app session without claiming that it revokes every other device.

## Ownership

| Area | Source |
|---|---|
| Session rows, cap, heartbeat, token equality | `database/auth_db.py` |
| Login, status, reconnect, password change, logout | `blueprints/auth.py` |
| Browser session client | `frontend/src` auth/session code |

## Acceptance Coverage

See `docs/bdd/session_lifecycle.feature` and `docs/bdd/auth_and_setup.feature`.
