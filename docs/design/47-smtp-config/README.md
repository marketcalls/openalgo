# 47 - SMTP Configuration

## Storage

SMTP settings are fields on the main `Settings` row in `database/settings_db.py`; there is no separate SMTP database or email service module. Stored fields cover server, port, username, encrypted password, TLS, from address, and optional HELO hostname.

New password writes use a Fernet key derived by `_get_smtp_fernet()`. A legacy decrypt fallback supports values written before the current derivation. Decrypted passwords must never be returned by profile/admin APIs or logged.

## Authenticated Routes

`blueprints/auth.py` exposes:

| Method/path | Purpose |
|---|---|
| `POST /auth/smtp-config` | Update settings; blank password preserves the existing secret |
| `POST /auth/test-smtp` | Validate recipient and send a test message |
| `POST /auth/debug-smtp` | Run connection/auth diagnostics |
| `GET /auth/profile-data` | Return non-secret config and password-present state |

The React configuration UI is the SMTP tab in `frontend/src/pages/Profile.tsx`.

## Delivery

`utils/email_utils.py` sends test and password-reset mail. Port 465 uses `SMTP_SSL`; other configured TLS flows use STARTTLS. The optional HELO hostname controls EHLO/HELO behavior. `utils/email_debug.py` performs staged diagnostics.

## Security Rules

- Require a valid app session and CSRF token for changes.
- Preserve the existing password when the form leaves it blank.
- Return password presence only, never ciphertext or plaintext.
- Do not include credentials in SMTP errors or logs.
- Prefer provider app passwords and TLS/SSL.
- Treat debug output as authenticated operational data.

## Key Files

| File | Purpose |
|---|---|
| `database/settings_db.py` | Settings and SMTP encryption |
| `utils/email_utils.py` | Test/reset/general delivery |
| `utils/email_debug.py` | Connection diagnostics |
| `blueprints/auth.py` | Configuration routes |
| `frontend/src/pages/Profile.tsx` | SMTP form |
