# 40 - Logout And Session Lifecycle

## Session Types

OpenAlgo maintains separate but related state:

| State | Meaning |
|---|---|
| Flask app session | Browser is authenticated to the local application |
| Active-session row | Device/IP/login/last-seen audit for the app session |
| Broker auth row | Installation's current broker and encrypted auth/feed tokens |
| OpenAlgo API key | External/internal service authentication that resolves the broker row |

Multiple app devices share one broker auth row and one server-side broker market-data feed.

## Login And Heartbeat

Successful app/broker login assigns `session_id` and registers an `active_sessions` row. The database caps the user at five rows, replaces an existing same-user/same-IP row, and removes the oldest at the cap.

The React app reads `/auth/session-status`. For logged-in sessions, that request touches `last_seen` at most once per 30 seconds using a timestamp in the signed Flask session. This makes the security dashboard liveness field meaningful without writing on every poll.

## Broker Token Rollover

The default daily expiry time is 03:00 IST. `DISABLE_SESSION_EXPIRY=true` supports 24/7 crypto deployments. Request guards apply expiry and revoke broker access according to this policy.

Broker expiry does not necessarily invalidate the local app session. When `/auth/session-status` finds an authenticated browser but no usable broker token, it preserves `logged_in` and returns `broker_session_expired: true`. The UI can then render broker reconnect and `/auth/broker` can admit the user.

## Multi-Device Resume

On resume, `upsert_auth()` compares decrypted broker/feed tokens plus broker and revoke state. If nothing material changed, it does not publish a teardown invalidation. This prevents a second browser login from disconnecting the feed used by the first device.

If tokens materially change or are revoked, cache/feed invalidation remains required.

## Explicit Logout

Logout removes the current active-session row, clears the Flask session, and follows the route's broker-token policy. The route is explicitly CSRF-exempt in app registration because both supported logout forms must work; other session-changing routes retain CSRF protection.

## Account Security Events

- Password change clears all active-session rows, emits `force_logout`, and clears the current cookie.
- Password reset and setup-sensitive flows clear or revoke session state according to their route logic.
- Active-session APIs under auth and security are read-only; there is no documented endpoint for remotely revoking one selected device.

## Frontend Behavior

`AuthSync` restores user, broker, API key, app mode, capabilities, and active-session count. A normal unauthenticated response clears the Zustand stores. Network errors preserve existing state for the current render rather than forcing a false logout.

## Key Files

| File | Purpose |
|---|---|
| `blueprints/auth.py` | Session status, heartbeat, login, logout, password change |
| `database/auth_db.py` | ActiveSession model, cap, last-seen, token upsert/revocation |
| `app.py` | Daily expiry request guard and CSRF exemptions |
| `utils/session.py` | Protected blueprint checks |
| `frontend/src/components/auth/AuthSync.tsx` | SPA session restoration |
| `frontend/src/stores/sessionStore.ts` | Active-session count |
