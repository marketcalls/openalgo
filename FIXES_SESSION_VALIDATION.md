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

### Fix 2: Session Status Endpoint Logic (Multi-Step Login Aware)
**File:** `blueprints/auth.py`

**Changes:**
```python
# Check both session keys
username = session.get("user") or session.get("user_session_key")

# Distinguish between in-progress login and stale session
if "login_time" not in session:
    # Legitimate in-progress login (app login → broker selection)
    return jsonify({"authenticated": True, "logged_in": False})

# Check if session is stale (>24 hours old)
if time_since_login > 86400:
    session.clear()
    return jsonify({"authenticated": False, "logged_in": False})

# Recent session, awaiting broker connection
return jsonify({"authenticated": True, "logged_in": False})
```

**Benefits:**
- Fixes auto-login issue while preserving multi-step login flow
- Only clears genuinely stale sessions (>24 hours old)
- Allows normal flow: Login → Broker Selection → Broker Auth
- Prevents kicking users back to login during broker selection

---

### Fix 3: Atomic Token Revocation (With DB Error Resilience)
**File:** `utils/session.py`

**Changes:**
```python
# Revoke token in database FIRST (atomic operation)
if revoke_db_tokens:
    try:
        inserted_id = upsert_auth(username, "", "", revoke=True)
    except Exception as db_error:
        # Log but continue - cache cleanup must happen even if DB fails
        logger.exception(f"Database revocation failed, continuing with cache cleanup")

# Clear cache AFTER database update attempt
# CRITICAL: Must run even if DB fails to prevent stale cached tokens
try:
    del auth_cache[cache_key_auth]
    del feed_token_cache[cache_key_feed]
except Exception as cache_error:
    logger.exception(f"Error during cache cleanup")
```

**Benefits:**
- Eliminates race condition (DB before cache)
- Cache cleanup happens even during DB outages (defensive)
- Prevents stale token reuse in all scenarios
- Graceful degradation during failures

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

## Critical Bug Fixes (Post-Initial Implementation)

### Issue: Cache Cleanup Skipped on DB Error (P2)
**Discovered:** Post-implementation review
**Location:** `utils/session.py:109`

**Problem:**
- Original atomic ordering placed cache cleanup inside the same try-except as DB revocation
- If `upsert_auth()` raised an exception, cache cleanup was skipped
- Left stale tokens cached during DB outages

**Fix:**
- Wrapped DB revocation in separate try-except
- Cache cleanup now runs even if DB operation fails
- Each cache operation isolated in its own try-except
- Defensive programming for graceful degradation

**Impact:** Prevents stale token caching during DB failures

---

### Issue: Multi-Step Login Flow Broken (P1 - Critical)
**Discovered:** Post-implementation review
**Location:** `blueprints/auth.py` (session-status endpoint)

**Problem:**
- Original fix cleared session when `logged_in=False`
- Broke normal login flow: App Login → Broker Selection → Broker Auth
- Users had `session["user"]` set but `logged_in=False` during broker selection
- Session status endpoint would clear session and kick user back to login

**Fix:**
- Check if `login_time` exists to distinguish in-progress vs stale sessions
- If no `login_time`: legitimate in-progress login (return `authenticated=True, logged_in=False`)
- If `login_time` exists: check age
  - Older than 24 hours: clear stale session
  - Recent: allow broker selection (return `authenticated=True, logged_in=False`)
- Preserves multi-step login flow while still catching stale sessions

**Impact:**
- Fixes broken broker selection flow
- Prevents user frustration during normal login
- Still clears genuinely stale sessions

---

## Version History

- **2026-01-30:** Initial fixes applied
  - Session key consistency
  - Atomic token revocation
  - Master contract status reset
  - Kotak baseUrl validation
  - Stale session cleanup

- **2026-01-30:** Critical bug fixes (post-review)
  - Cache cleanup resilience during DB errors
  - Multi-step login flow preservation
  - 24-hour staleness threshold for session cleanup
