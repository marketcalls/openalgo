# OpenAlgo Security Audit Report

Date: 2026-04-08
Commit: c71d875fe2ae6de4bb858d422da911cab4ad77ae
Auditor: Claude Code

## Summary

[To be filled after all phases]

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High | 3 |
| Medium | 3 |
| Low | 2 |

## Critical Findings

### VULN-001: Hardcoded Default SECRET_KEY and Pepper in Sample Environment File

Severity: Critical
File: .sample.env (lines 29, 37)
CWE: CWE-798

What: The `.sample.env` file ships with pre-generated, deterministic values for both `APP_KEY` (`3daa0403ce...`) and `API_KEY_PEPPER` (`a25d94718...`). These are not placeholder strings like `YOUR_BROKER_API_KEY` but fully valid hex secrets. If a user copies `.sample.env` to `.env` without changing these values (which the setup instructions say to do: `cp .sample.env .env`), the application will start successfully with publicly known secrets. There is no runtime check that `APP_KEY` or `API_KEY_PEPPER` still match the sample defaults.

Risk: Anyone who reads the open-source repository knows both secrets. An attacker can forge Flask session cookies (using the known `APP_KEY`), impersonate any user, and decrypt all stored broker auth tokens and API keys (using the known `API_KEY_PEPPER` via the Fernet KDF). This is a complete authentication bypass for any deployment using the default values.

Fix: Add a startup validation in `utils/env_check.py` that reads the hardcoded sample values and compares them to the loaded `.env` values. If `APP_KEY` or `API_KEY_PEPPER` matches the sample file defaults, refuse to start and print an error instructing the user to generate new values with `secrets.token_hex(32)`.

---

## High Findings

### VULN-002: Session Fixation - No Session Regeneration After Login

Severity: High
File: blueprints/auth.py (lines 133-137), utils/auth_utils.py (lines 340-356)
CWE: CWE-384

What: When a user successfully authenticates at the `/auth/login` endpoint, the code sets `session["user"] = username` without regenerating the session ID. Similarly, `handle_auth_success()` in `utils/auth_utils.py` sets `session["logged_in"] = True` and other session keys without calling `session.regenerate()` or clearing and recreating the session. Flask's default server-side session does not automatically regenerate the session cookie upon privilege elevation.

Risk: An attacker who can pre-set or learn a victim's session ID before login (e.g., via a network-level man-in-the-middle on HTTP deployments, or by injecting a session cookie) can hijack the authenticated session after the victim logs in. The attacker's pre-existing session cookie becomes authenticated without the attacker ever knowing the password.

Fix: Clear and regenerate the session immediately after successful authentication. Before setting `session["user"]`, call `session.clear()` then `session.regenerate()` (or manually create a fresh session by clearing and re-populating), ensuring the session ID changes upon login.

---

### VULN-003: Password Reset Token Has No Expiration and Is Stored Only in Session

Severity: High
File: blueprints/auth.py (lines 218-254, 260-297, 302-332)
CWE: CWE-640

What: Password reset tokens (generated via `secrets.token_urlsafe(32)`) are stored in the Flask session (`session["reset_token"]`) with no explicit expiration. The token remains valid for as long as the session exists, which can be up to the next 3:00 AM IST (potentially 24+ hours). Furthermore, when using the email-based reset flow, the reset link embeds the token in the URL, but validation only checks `session.get("reset_token")` -- meaning the reset link only works in the same browser session that requested it, which is a usability problem, and the token persists indefinitely within that session.

Risk: A password reset token obtained through any session leak (e.g., XSS, shared computer, session cookie theft) can be replayed hours later. There is no time-bound invalidation, and the token is not single-use since it persists in the session even after inspection via the email link route (`reset_password_email`) -- it is only cleared after the password is actually changed.

Fix: Add a timestamp to the reset token (`session["reset_token_created"]`) and enforce a short expiration window (e.g., 15 minutes). Validate the timestamp in the `step == "password"` handler. Additionally, invalidate the token immediately after successful password change (already done) and also on any failed attempt.

---

### VULN-004: TOTP Secret Exposed via Profile API Endpoint

Severity: High
File: blueprints/auth.py (lines 805, 816)
CWE: CWE-200

What: The `/auth/profile-data` endpoint returns the raw TOTP secret (`user.totp_secret`) in plaintext as part of the JSON response to any authenticated user. The TOTP secret is the seed from which all TOTP codes are derived. While the QR code is also returned (which encodes the same secret), explicitly returning the raw secret string in an API response increases the attack surface.

Risk: If an attacker gains access to a single authenticated session (via session hijack, XSS, or a compromised browser extension), they can call `/auth/profile-data` and extract the TOTP secret. This allows the attacker to generate valid TOTP codes indefinitely, even after the session is terminated, enabling persistent password reset capability (since TOTP is used for password reset verification).

Fix: Do not return `totp_secret` in the API response. The QR code already contains the provisioning URI. If the user needs to manually enter the secret, mask it or require re-authentication (current password) before displaying it.

---

## Medium Findings

### VULN-005: Plaintext API Key Used as Cache Key in `broker_cache`

Severity: Medium
File: database/auth_db.py (lines 589-600)
CWE: CWE-312

What: The `get_broker_name()` function uses the plaintext API key directly as the dictionary key for `broker_cache`: `broker_cache[provided_api_key] = auth_obj.broker`. This contrasts with `verify_api_key()` and `get_auth_token_broker()`, which correctly use `hashlib.sha256(provided_api_key.encode()).hexdigest()` as the cache key. Storing the plaintext API key in an in-memory cache dictionary means the actual API key value is held as a Python string object that could be exposed through memory dumps, debug endpoints, or process inspection.

Risk: If an attacker gains access to the process memory (via a debug endpoint, core dump, or memory disclosure vulnerability), they can extract plaintext API keys from the `broker_cache` dictionary keys. This undermines the otherwise careful hashing approach used elsewhere.

Fix: Change `get_broker_name()` to use a SHA256 hash of the API key as the cache key, consistent with the pattern used in `verify_api_key()` and `get_auth_token_broker()`.

---

### VULN-006: Static Salt in Fernet Key Derivation Reduces KDF Diversity

Severity: Medium
File: database/auth_db.py (lines 58-65)
CWE: CWE-760

What: The `get_encryption_key()` function derives a Fernet encryption key using PBKDF2HMAC with a hardcoded, static salt: `salt=b"openalgo_static_salt"`. This salt is the same across all deployments and is visible in the public source code. The purpose of a salt in a KDF is to ensure that the same password/pepper produces different derived keys across different installations; a static salt defeats this purpose entirely.

Risk: If two deployments use the same `API_KEY_PEPPER` (which is more likely given the hardcoded default in `.sample.env` per VULN-001), their Fernet encryption keys will be identical, enabling cross-deployment token decryption. Even with unique peppers, the static salt means pre-computed rainbow tables for common pepper values can be built once and applied to all OpenAlgo deployments.

Fix: Generate a random salt during initial setup, store it alongside the encrypted data or in the `.env` file as a separate configuration value (e.g., `ENCRYPTION_SALT`). Use this stored salt in the KDF instead of the hardcoded string.

---

### VULN-007: CSRF Protection Is Configurable and Can Be Disabled via Environment Variable

Severity: Medium
File: app.py (lines 279-280), .sample.env (line 235)
CWE: CWE-352

What: CSRF protection is controlled by the `CSRF_ENABLED` environment variable: `csrf_enabled = os.getenv("CSRF_ENABLED", "TRUE").upper() == "TRUE"`. Setting `CSRF_ENABLED=FALSE` in `.env` completely disables CSRF protection for the entire application. While the default is `TRUE`, making a critical security control configurable via an environment variable that any administrator might toggle for "debugging" purposes is risky. There is no warning logged when CSRF is disabled.

Risk: If an administrator sets `CSRF_ENABLED=FALSE` (perhaps during troubleshooting), the entire application becomes vulnerable to CSRF attacks. An attacker could craft malicious pages that submit orders, change passwords, modify settings, or revoke API keys using the victim's authenticated session.

Fix: Log a prominent warning at startup when CSRF is disabled. Consider removing the ability to fully disable CSRF, or at minimum require `FLASK_ENV=development` for CSRF to be disableable. Add a startup log message: "CRITICAL WARNING: CSRF protection is DISABLED. This should never be done in production."

---

## Low Findings

### VULN-008: REDIRECT_URL Leaked to Unauthenticated Users

Severity: Low
File: blueprints/auth.py (lines 86-93)
CWE: CWE-200

What: The `/auth/broker-config` endpoint returns the full `REDIRECT_URL` (e.g., `http://127.0.0.1:5000/zerodha/callback`) to unauthenticated users. While `broker_api_key` is set to `None` for unauthenticated requests, the `redirect_url` field is always populated from the environment variable. The code comments say "return broker name only so the login button is visible" but the implementation also includes the redirect URL.

Risk: The redirect URL reveals the internal server address, port, and broker name to anyone who queries this endpoint without authentication. This is information disclosure that aids reconnaissance. For production deployments behind reverse proxies or with custom domains, it may expose the internal topology.

Fix: Set `redirect_url` to `None` in the unauthenticated response branch, matching the comment's stated intent. Only return the `broker_name` for unauthenticated users.

---

### VULN-009: CSRF Time Limit Defaults to None (No Expiration)

Severity: Low
File: app.py (lines 296-303), .sample.env (lines 239-240)
CWE: CWE-613

What: The CSRF token time limit is configured as: if `CSRF_TIME_LIMIT` is empty or unset, `WTF_CSRF_TIME_LIMIT` is set to `None`, meaning CSRF tokens never expire. The `.sample.env` ships with `CSRF_TIME_LIMIT = ''` (empty), so the default installation has indefinite CSRF tokens. While Flask-WTF ties tokens to the session, tokens that never expire increase the window for token theft and replay.

Risk: A stolen or leaked CSRF token remains valid for the entire duration of the user's session (which can be up to 24 hours until the 3:00 AM IST cutoff). This gives an attacker a wider window to use a captured CSRF token for cross-site request forgery attacks.

Fix: Set a reasonable default CSRF time limit (e.g., 3600 seconds / 1 hour) in the `.sample.env` file instead of leaving it empty. Change the fallback in `app.py` from `None` to a sensible default like `3600`.

---

## Recommendations
