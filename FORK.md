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

## Files to NOT Track in Git

These files should remain in `.gitignore`:

| Pattern | Reason |
|---------|--------|
| `db/*.bak` | Database backups - use proper backup strategy, not Git |
| `db/*.db-shm`, `db/*.db-wal` | SQLite temp files |

---

## Environment Variables (Fork-Specific)

This fork introduces the following optional environment variable:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SHARED_CREDENTIALS_FILE` | Path to JSON file containing shared Zerodha credentials | Not set (disabled) |

**Example Usage**:
```bash
# In .env file
SHARED_CREDENTIALS_FILE=/path/to/shared/zerodha_credentials.json
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
- **Machine 1**: Login to Zerodha normally, export credentials
- **Machine 2+**: Read credentials from shared file, skip login

### How It Works
1. On primary machine: `uv run python scripts/share_credentials.py`
2. This creates a JSON file with `api_key` and `access_token`
3. On secondary machines: Set `SHARED_CREDENTIALS_FILE` env var pointing to this JSON
4. The `credential_manager.py` automatically uses shared credentials when available

### Files Involved
- `broker/zerodha/credential_manager.py` - Core logic
- `scripts/share_credentials.py` - Export script
- `broker/zerodha/api/data.py` - Integration point (modified)

---

*Last updated: 2026-01-25*
