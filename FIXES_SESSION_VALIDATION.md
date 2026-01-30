# Session Validation Issues - Fixes Applied

## Overview
This document details the critical session validation issues identified and fixed in the OpenAlgo authentication flow, particularly affecting Kotak broker integration.

## Issues Identified

### Issue 1: Missing "user" Key Check in Logout Endpoint
**Severity:** Critical
**Affected File:** `blueprints/auth.py:708-750`

**Problem:**
- Logout endpoint assumed `session["user"]` exists when `logged_in=True`
- Caused `KeyError` and logout to hang
- Incomplete cache cleanup
- Corrupted session state

**Root Cause:** Inconsistent session key usage between login (`session["user"]`) and broker auth (`session["user_session_key"]`)

---

### Issue 2: Auto-Login Without Credentials
**Severity:** Critical (Security)
**Affected File:** `blueprints/auth.py:503-550`

**Problem:**
- Session status endpoint returned `authenticated: true` when `session["user"]` exists but `logged_in=False`
- Frontend interpreted this as valid session
- Master contract showed "success" from previous session
- Users could access dashboard without re-authentication

**Root Cause:** Session status endpoint didn't clear stale sessions when broker wasn't connected

---

### Issue 3: Session Deactivates During Trading Day (Ubuntu Server)
**Severity:** High
**Affected Files:** `utils/session.py:76-157`, `database/auth_db.py:203-261`

**Problem:**
- Token revocation race condition between cache clear and DB update
- ZeroMQ cache invalidation could fail in multi-process deployments
- Kotak baseUrl changes mid-session causing auth failures

**Root Cause:** Cache was cleared BEFORE database token revocation, allowing race condition

---

### Issue 4: Master Contract Not Re-downloaded After Re-login
**Severity:** High (Kotak-specific)
**Affected Files:** `utils/auth_utils.py:158-214`, `utils/session.py`

**Problem:**
- Master contract status not reset on logout or session expiry
- `is_ready` flag remained true from previous session
- Frontend showed "downloading" but backend never initiated download

**Root Cause:** Master contract status persisted across sessions

---

### Issue 5: Kotak baseUrl Missing on Re-authentication
**Severity:** Critical (Kotak-specific)
**Affected File:** `broker/kotak/api/auth_api.py:135-139`

**Problem:**
- Kotak returns dynamic `baseUrl` from MPIN validation
- Missing baseUrl causes ALL API calls to fail
- Only logged as warning, not error

**Root Cause:** No validation or error handling for missing baseUrl

---

## Fixes Applied

### Fix 1: Logout Endpoint Session Key Fallback
**File:** `blueprints/auth.py`

**Changes:**
```python
# Use fallback for username - check both possible session keys
username = session.get("user") or session.get("user_session_key")

if not username:
    logger.warning("Logout called without valid user session key")
    session.clear()
    return jsonify({"status": "success", "message": "Session cleared"})
```

**Benefits:**
- Handles missing `session["user"]` gracefully
- Prevents logout hanging
- Ensures complete cache cleanup

---

### Fix 2: Session Status Endpoint Logic
**File:** `blueprints/auth.py`

**Changes:**
```python
# Check both session keys
username = session.get("user") or session.get("user_session_key")

# If user exists but not logged in with broker, clear stale session
if not session.get("logged_in"):
    logger.info(f"Clearing stale session for user {username}")
    session.clear()
    return jsonify({"authenticated": False, "logged_in": False})
```

**Benefits:**
- Fixes auto-login issue
- Clears stale sessions immediately
- Prevents unauthorized access

---

### Fix 3: Atomic Token Revocation
**File:** `utils/session.py`

**Changes:**
```python
# Revoke token in database FIRST (atomic operation)
if revoke_db_tokens:
    inserted_id = upsert_auth(username, "", "", revoke=True)

# Clear cache AFTER database update (prevents race condition)
del auth_cache[cache_key_auth]
del feed_token_cache[cache_key_feed]
```

**Benefits:**
- Eliminates race condition
- Ensures token is revoked before cache clear
- Prevents stale token reuse

---

### Fix 4: Master Contract Status Reset
**Files:** `blueprints/auth.py`, `utils/session.py`

**Changes:**
```python
# Reset master contract status on logout
if broker:
    from database.master_contract_status_db import update_status
    update_status(broker, "pending", "User logged out - master contract needs re-download")
```

**Benefits:**
- Forces master contract re-download on re-login
- Clears stale `is_ready` flag
- Ensures fresh data after session expiry

---

### Fix 5: Kotak baseUrl Validation
**File:** `broker/kotak/api/auth_api.py`

**Changes:**
```python
if not base_url:
    logger.error("CRITICAL: baseUrl not found in MPIN response")
    return None, "Authentication incomplete: baseUrl not received"
```

**Benefits:**
- Prevents incomplete authentication
- Fails fast with clear error message
- Protects against API call failures

---

### Fix 6: Session Key Consistency
**File:** `utils/auth_utils.py`

**Changes:**
```python
# Set both session keys for consistency
session["user"] = user_session_key  # Primary key
session["user_session_key"] = user_session_key  # Backward compatibility
```

**Benefits:**
- Ensures consistency across all endpoints
- Prevents session key mismatches
- Maintains backward compatibility

---

## Testing Checklist

### Manual Testing Required:

1. **Logout Flow:**
   - [ ] User logs in successfully
   - [ ] User logs out - verify session clears completely
   - [ ] Check master contract status reset to "pending"
   - [ ] Verify cache cleared (auth, feed, symbol caches)

2. **Re-login Flow:**
   - [ ] User logs out and logs back in
   - [ ] Master contract downloads start automatically
   - [ ] No stale "success" status from previous session
   - [ ] Kotak: Verify baseUrl is captured

3. **Session Expiry (3 AM IST):**
   - [ ] Session expires at configured time
   - [ ] Tokens revoked in database
   - [ ] Master contract status reset
   - [ ] Re-login triggers fresh download

4. **Auto-Login Prevention:**
   - [ ] Logout from broker (not full logout)
   - [ ] Refresh page
   - [ ] Verify redirected to login page (not dashboard)
   - [ ] No auto-authentication

5. **Kotak-Specific:**
   - [ ] TOTP authentication succeeds
   - [ ] baseUrl captured from MPIN response
   - [ ] Authentication fails gracefully if baseUrl missing
   - [ ] Master contract download uses correct baseUrl

6. **Ubuntu Server Deployment:**
   - [ ] Multi-process (Gunicorn workers) deployment
   - [ ] ZeroMQ cache invalidation working
   - [ ] Token revocation across all workers
   - [ ] No mid-session deactivations

---

## Files Modified

1. `blueprints/auth.py` - Logout and session status endpoints
2. `utils/session.py` - Token revocation and session expiry logic
3. `utils/auth_utils.py` - Session key consistency in broker auth
4. `broker/kotak/api/auth_api.py` - baseUrl validation
5. `database/master_contract_status_db.py` - Status management (no changes, used by fixes)

---

## Deployment Notes

### Breaking Changes: None
All changes are backward compatible.

### Configuration Required: None
Uses existing `.env` configuration.

### Database Migrations: None
No schema changes required.

### Restart Required: Yes
Application restart needed to load new code.

---

## Monitoring Recommendations

1. **Log Monitoring:**
   - Watch for "Clearing stale session" messages
   - Monitor "Reset master contract status" on logout/expiry
   - Check for Kotak baseUrl validation errors

2. **Metrics to Track:**
   - Session expiry events at 3 AM IST
   - Master contract download success rate after re-login
   - Logout completion time (should be faster)
   - Auto-login prevention (should be zero)

3. **Kotak-Specific Monitoring:**
   - baseUrl capture success rate
   - Authentication failures due to missing baseUrl
   - Master contract download failures

---

## Rollback Plan

If issues occur after deployment:

1. **Immediate Rollback:**
   ```bash
   git checkout main
   systemctl restart openalgo
   ```

2. **Partial Rollback (per file):**
   - Revert specific files if needed
   - Test each change independently

3. **Emergency Fix:**
   - All changes are defensive (add checks, don't remove logic)
   - Safe to rollback without data loss

---

## Related Issues

- Issue #765: ZeroMQ cache invalidation for multi-process deployments
- Kotak broker authentication flow (TOTP + MPIN)
- Session expiry at 3 AM IST (configurable via `SESSION_EXPIRY_TIME`)

---

## Contributors

- Analysis and fixes by Claude Code
- Testing required by OpenAlgo team

---

## Version History

- **2026-01-30:** Initial fixes applied
  - Session key consistency
  - Atomic token revocation
  - Master contract status reset
  - Kotak baseUrl validation
  - Stale session cleanup
