# Fork Changes

This document tracks all modifications made in this fork compared to the upstream repository ([marketcalls/openalgo](https://github.com/marketcalls/openalgo)).

**Purpose**: Enable easier upstream syncing by clearly documenting what's custom to this fork.

---

## New Files (No Conflict Risk)

These files are additions that don't exist in upstream. They will **never conflict** during `git pull` from upstream.

| File | Purpose |
|------|---------|
| `broker/zerodha/credential_manager.py` | Shared credentials management - allows multiple OpenAlgo instances to share Zerodha auth tokens via a JSON file |
| `scripts/share_credentials.py` | Script to export credentials from local DB to a shared JSON file for use by other instances |
| `docs/PYVOLLIB_FIX.md` | Documentation for fixing py_vollib compatibility with Python 3.14 |
| `FORK.md` | This file - tracks fork-specific changes |
| `AGENTS.md` | AI agent guidance file (may eventually exist in upstream, but content differs) |

---

## Modified Files (Review During Upstream Sync)

These files have been modified from upstream. **Pay attention to these during `git pull`** - they may cause merge conflicts.

### `broker/zerodha/api/data.py`
**Change Type**: Feature addition  
**Conflict Risk**: Medium-High  
**Description**: Added shared credentials integration

**Specific Changes**:
1. Added import at top of file:
   ```python
   from ..credential_manager import get_shared_auth_token
   ```

2. Modified `get_api_response()` function to use shared auth token:
   ```python
   # Check for shared credentials override
   shared_auth = get_shared_auth_token(auth)
   if shared_auth:
       auth = shared_auth
   ```

**Resolution Strategy**: After pulling upstream changes, re-apply these two small additions manually if they conflict.

---

### `utils/auth_utils.py`
**Change Type**: Feature addition  
**Conflict Risk**: Medium  
**Description**: Auto-run `share_credentials.py` after successful broker login

**Specific Changes**:
1. Added imports at top of file:
   ```python
   import os
   from extensions import socketio
   ```

2. Added `run_share_credentials()` function (~25 lines):
   - Checks if `BROKER_USER_ID` env var is set
   - If set, imports and runs `scripts/share_credentials.main()`
   - Returns success/failure status and message

3. Added `async_post_login_tasks()` function (~25 lines):
   - Runs in background thread after broker auth
   - Waits 2 seconds for dashboard to load
   - Calls `run_share_credentials()` and emits SocketIO toast event
   - Calls existing `async_master_contract_download()`

4. Modified `handle_auth_success()` function:
   - Changed thread target from `async_master_contract_download` to `async_post_login_tasks`

**Resolution Strategy**: If upstream modifies `handle_auth_success()`, re-apply the thread target change and ensure the two new functions exist.

---

### `frontend/src/hooks/useSocket.ts`
**Change Type**: Feature addition  
**Conflict Risk**: Low  
**Description**: Added SocketIO listener for share credentials toast notification

**Specific Changes**:
Added event listener after `master_contract_download` handler:
```typescript
// Share credentials notification (post broker login)
socket.on('share_credentials_status', (data: { status: string; message: string }) => {
  if (data.status === 'success') {
    toast.success(data.message)
  } else {
    toast.error(data.message)
  }
})
```

**Resolution Strategy**: This is a simple addition. Re-add the event listener if it gets removed during merge.

---

## Files to NOT Track in Git

These files should remain in `.gitignore`:

| Pattern | Reason |
|---------|--------|
| `db/*.bak` | Database backups - use proper backup strategy, not Git |
| `db/*.db-shm`, `db/*.db-wal` | SQLite temp files |

---

## Environment Variables (Fork-Specific)

This fork introduces the following optional environment variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SHARED_CREDENTIALS_FILE` | Path to JSON file containing shared Zerodha credentials | Not set (disabled) |
| `BROKER_USER_ID` | User ID for auto-exporting credentials after broker login | Not set (disabled) |
| `BROKER_API_KEY` | Broker API key (used by share_credentials.py) | Not set |

**Example Usage**:
```bash
# In .env file
SHARED_CREDENTIALS_FILE=/path/to/shared/zerodha_credentials.json
BROKER_USER_ID=your_broker_user_id
BROKER_API_KEY=your_broker_api_key
```

---

## Syncing with Upstream

### Initial Setup (One Time)
```bash
# Add upstream remote if not already added
git remote add upstream https://github.com/marketcalls/openalgo.git
```

### Regular Sync Process
```bash
# 1. Fetch upstream changes
git fetch upstream

# 2. Check what's new
git log HEAD..upstream/main --oneline

# 3. Merge upstream (or rebase if you prefer)
git merge upstream/main

# 4. If conflicts occur in modified files (see list above):
#    - Review the conflict
#    - Keep upstream changes + re-apply your modifications
#    - The modifications are small and documented above

# 5. Verify new files are intact
git status
```

### After Conflict Resolution
- Verify `broker/zerodha/credential_manager.py` still exists
- Verify `scripts/share_credentials.py` still exists
- Test the shared credentials feature if you use it

---

## Feature: Shared Credentials

### Problem Solved
When running multiple OpenAlgo instances (e.g., different machines, different strategies), each instance normally needs its own Zerodha login. This fork allows:
- **Machine 1**: Login to Zerodha normally, credentials auto-exported
- **Machine 2+**: Read credentials from shared file, skip login

### How It Works

**Option A: Automatic Export (Recommended)**
1. Set `BROKER_USER_ID`, `BROKER_API_KEY`, and `SHARED_CREDENTIALS_FILE` in `.env`
2. Login to broker normally via the web UI
3. Credentials are **automatically exported** after successful broker authentication
4. A toast notification confirms "Credentials shared successfully"

**Option B: Manual Export**
1. On primary machine: `uv run python scripts/share_credentials.py`
2. This creates a JSON file with `api_key` and `access_token`

**On Secondary Machines:**
1. Set `SHARED_CREDENTIALS_FILE` env var pointing to the shared JSON
2. The `credential_manager.py` automatically uses shared credentials when available

### Files Involved
- `utils/auth_utils.py` - Auto-export trigger after broker login (modified)
- `frontend/src/hooks/useSocket.ts` - Toast notification for export status (modified)
- `broker/zerodha/credential_manager.py` - Core credential reading logic
- `scripts/share_credentials.py` - Export script (manual or auto-invoked)
- `broker/zerodha/api/data.py` - Integration point for using shared credentials (modified)

---

*Last updated: 2026-01-26*
