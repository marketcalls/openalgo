# 50 - TOTP Configuration

## Model

The local `User` model stores an encrypted `totp_secret` plus a master switch and three purpose flags:

| Field | Meaning |
|---|---|
| `totp_enabled` | Master TOTP switch |
| `totp_required_for_login` | Require TOTP after password login |
| `totp_required_for_mcp` | Require fresh TOTP for sensitive Remote MCP consent |
| `totp_required_for_password_reset` | Require TOTP on the reset path |

When the master switch is false, `is_totp_required_for()` returns false for every purpose. The current implementation has no backup-code model or backup-code verification path.

## Secret Lifecycle

Initial user setup generates a base32 secret and stores Fernet ciphertext. `get_totp_secret()` is the only supported plaintext accessor and includes legacy fallback behavior. `get_totp_uri()` creates the authenticator provisioning URI through `pyotp`; `verify_totp()` checks submitted codes.

The Profile page can display the QR code and plaintext secret to the authenticated user for enrollment. That response is sensitive and must never be cached or logged.

## Login Flow

When login TOTP is enabled, a correct password creates a short-lived `pending_totp_user` and does not establish the authenticated user session. `/auth/login/totp` validates the six-digit code inside the pending window, promotes the session, records `totp_verified_at`, and then attempts broker-session resume.

Bad codes are rate limited through the login limit. One bad code does not immediately clear the pending marker; the five-minute freshness window bounds the flow.

## Configuration API

| Method/path | Purpose |
|---|---|
| `GET /auth/2fa/status` | Read master/purpose flags and last verification time |
| `POST /auth/2fa/configure` | Atomically set master and purpose flags |

Changing TOTP policy requires a valid current TOTP code, including disabling it. Disabling the master switch forces all purpose flags false.

## Password Reset And MCP

The password-reset route offers TOTP when configured for that purpose and verifies through the same user model. Remote MCP authorization can require recent `totp_verified_at` before granting write scope; freshness rules belong to `blueprints/mcp_oauth.py`.

## Security Rules

- Never read the ciphertext column directly where plaintext is required; use `get_totp_secret()`.
- Never log the secret, provisioning URI, QR payload, or submitted code.
- TOTP proves possession of the configured authenticator, not broker authorization.
- Purpose flags are effective only while the master switch is on.
- Do not document backup codes until an actual persisted and verified implementation exists.

## Key Files

| File | Purpose |
|---|---|
| `database/user_db.py` | Encrypted secret, flags, URI, verification |
| `blueprints/auth.py` | Login, status/config, reset integration |
| `blueprints/mcp_oauth.py` | Fresh-TOTP check for OAuth consent |
| `frontend/src/pages/Profile.tsx` | Enrollment/policy UI |
| `frontend/src/pages/Login.tsx` | Pending-login verification |
