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
| `database/strategy_state_db.py` | Database access layer for `strategy_state.db` - queries Python strategy execution states |
| `blueprints/strategy_state.py` | Flask blueprint providing `/api/strategy-state` endpoints (GET all, GET by ID, DELETE) |
| `frontend/src/types/strategy-state.ts` | TypeScript interfaces for strategy state data structures |
| `frontend/src/api/strategy-state.ts` | API client for strategy state endpoints |
| `frontend/src/pages/StrategyPositions.tsx` | React page component - displays strategy positions in accordion format with delete confirmation |

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

### `app.py`
**Change Type**: Feature addition  
**Conflict Risk**: Low  
**Description**: Registered Strategy State blueprint

**Specific Changes**:
1. Added import:
   ```python
   from blueprints.strategy_state import strategy_state_bp
   ```

2. Added blueprint registration in `create_app()`:
   ```python
   app.register_blueprint(strategy_state_bp)
   ```

**Resolution Strategy**: If upstream modifies blueprint registrations, re-add these two lines.

---

### `frontend/src/App.tsx`
**Change Type**: Feature addition  
**Conflict Risk**: Low  
**Description**: Added route for Strategy Positions page

**Specific Changes**:
1. Added lazy import:
   ```typescript
   const StrategyPositions = lazy(() => import('@/pages/StrategyPositions'))
   ```

2. Added route:
   ```typescript
   <Route path="/strategy-positions" element={<StrategyPositions />} />
   ```

**Resolution Strategy**: Re-add the lazy import and route if removed during merge.

---

### `frontend/src/config/navigation.ts`
**Change Type**: Feature addition  
**Conflict Risk**: Low  
**Description**: Added Strategy Positions to profile menu navigation

**Specific Changes**:
1. Added `LineChart` to lucide-react imports
2. Added menu item to `profileMenuItems` array:
   ```typescript
   { href: '/strategy-positions', label: 'Strategy Positions', icon: LineChart },
   ```

**Resolution Strategy**: Re-add the import and menu item if removed during merge.

---

### `frontend/src/hooks/useLivePrice.ts`
**Change Type**: Bug fix + diagnostic improvements  
**Conflict Risk**: Medium  
**Description**: Improved live LTP selection logic and added optional debug logging

**Specific Changes**:
1. Added `debug_live_price` localStorage flag to emit detailed `console.debug` logs for MultiQuotes requests/responses and LTP source selection.
2. Adjusted LTP selection logic to better handle screens that *do not* provide `quantity`/`average_price` (e.g., Strategy legs).
3. Added a safeguard: when an item explicitly has `quantity` and `quantity === 0`, preserve REST values (avoid updating LTP / recalculating P&L for closed positions).

**Resolution Strategy**: If upstream touches this hook, re-apply the debug flag + the `quantity === 0` REST-preservation guard.

---

### `frontend/src/pages/StrategyPositions.tsx`
**Change Type**: Feature enhancement  
**Conflict Risk**: Medium  
**Description**: Expanded Strategy Positions UI (live LTP, auto-refresh preferences, leg breakdown, inline SL/Target editing)

**Specific Changes** (high level):
- Added auto-refresh toggle + interval (5–300s) persisted in localStorage
- Added a single `useLivePrice()` subscription for all active legs (shows live LTP)
- Added unrealized/realized/total P&L computation and a per-leg P&L breakdown
- Added inline editing for `sl_price` / `target_price` (calls `createStrategyOverride`)
- Improved delete confirmation by requiring typing the strategy name

**Resolution Strategy**: If upstream changes this page, re-apply the above feature blocks (especially the live-price subscription and auto-refresh prefs).

---

### `frontend/dist/index.html`
**Change Type**: Build artifact update  
**Conflict Risk**: Low  
**Description**: Vite build output changed hashed asset filenames.

**Notes**:
- This file is generated by `frontend` build (`npm run build`), so it will naturally change when bundling changes.
- Avoid hand-editing.

**Resolution Strategy**: Treat as generated output; regenerate via `npm run build` after resolving merges.

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

## Feature: Strategy Positions Viewer

### Problem Solved
When running Python trading strategies with state persistence (`strategy_state.db`), users had no way to view their strategy positions, trade history, and P&L through the UI. This feature provides:
- **Visual dashboard** for all Python strategies with state persistence
- **Position tracking** showing open and exited positions per strategy
- **Trade history** with entry/exit prices, times, and P&L
- **Strategy management** with delete functionality

### How It Works

1. Navigate to **Profile Menu → Strategy Positions** (or `/strategy-positions`)
2. View all strategies in accordion format with:
   - Strategy name, status (RUNNING/COMPLETED/etc.), underlying, expiry
   - Summary stats: Open positions count, total trades, realized/unrealized P&L
   - **Current Positions table**: Leg, Symbol, Side, Qty, Entry Price, LTP, SL, Target, Status, P&L
   - **Trade History table**: Entry/Exit prices and times, Exit type (SL_HIT/TARGET_HIT), P&L
3. Delete strategies by clicking the trash icon and typing the strategy name to confirm

### Live SL/Target Override (UI Integration)

For positions with `IN_POSITION` status, users can **inline edit** Stop Loss and Target prices:

1. **Click** on the SL or Target cell in the Current Positions table
2. **Enter** the new value in the input field
3. Press **Enter** to save (or **Escape** to cancel)
4. A toast notification confirms: "Sl Price override created. Will be applied within 5 seconds."

**Validation Rules:**
- For **BUY** positions: SL must be below entry price, Target must be above entry price
- For **SELL** positions: SL must be above entry price, Target must be below entry price

**How It Works (Backend):**
- UI creates a record in the `strategy_overrides` table with `applied=FALSE`
- The running Python strategy polls `get_pending_overrides()` within its `POLL_INTERVAL` (default 5s)
- Strategy applies the override with its own validation and calls `mark_override_applied()`

**`strategy_overrides` Table Schema:**

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key (auto-increment) |
| instance_id | VARCHAR(100) | Strategy instance ID |
| leg_key | VARCHAR(100) | Leg identifier (e.g., "CE_SPREAD_CE_SELL") |
| override_type | VARCHAR(20) | `sl_price` or `target_price` |
| new_value | FLOAT | New price value |
| applied | BOOLEAN | Whether applied (default: FALSE) |
| created_at | DATETIME | When override was created |
| applied_at | DATETIME | When override was applied |

### Files Involved
- `database/strategy_state_db.py` - Database queries for `strategy_state.db`
- `blueprints/strategy_state.py` - REST API endpoints
- `frontend/src/pages/StrategyPositions.tsx` - Main UI component
- `frontend/src/api/strategy-state.ts` - API client
- `frontend/src/types/strategy-state.ts` - TypeScript types
- `app.py` - Blueprint registration (modified)
- `frontend/src/App.tsx` - Route registration (modified)
- `frontend/src/config/navigation.ts` - Navigation menu (modified)

### TODO
- **LTP Integration**: Currently using entry_price as placeholder for LTP. Future enhancement to fetch real-time LTP via WebSocket or Quotes API.

---

*Last updated: 2026-01-29*
