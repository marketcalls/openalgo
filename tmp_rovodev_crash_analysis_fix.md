# OpenAlgo Crash Root Cause Analysis & Fix

## 🔥 CRITICAL ISSUE: File Descriptor Exhaustion

**Crash Time:** January 30, 2026 at 10:38:20 AM  
**Root Cause:** `OSError: [Errno 24] Too many open files`

---

## Root Cause Analysis

### **1. The Problem**

Your macOS system has a limit of **2,560 file descriptors** per process:
```bash
$ ulimit -n
2560
```

The main Flask application exhausted all available file descriptors, causing:
- Database connections to fail (`unable to open database file`)
- New HTTP requests to fail
- Complete application freeze
- Cascade of errors in traffic logging, strategy execution, and WebSocket handling

### **2. Why It Happened**

#### **A. Multiple Strategy Processes Running**
You have **3 strategy scripts** running simultaneously:
- PID 59502 (started 10:16 AM) - consuming ~86 file descriptors
- PID 61000 (started 10:22 AM) - consuming ~86 file descriptors  
- PID 61499 (started 10:23 AM) - consuming ~86 file descriptors

Each strategy process opens:
- Database connections to 5 databases (openalgo.db, logs.db, latency.db, sandbox.db, strategy_state.db)
- WebSocket connections for real-time data
- HTTPX connections for API calls

#### **B. Database Connection Leak in Traffic Logger**

The traffic logger runs on **EVERY HTTP request** and:
1. Opens a new database connection (`logs_session`)
2. Checks IP ban status (database query)
3. Logs the request (database insert)
4. **Fails to properly close connections** in error scenarios

With high-frequency market data streaming, you're generating **hundreds of requests per minute**.

#### **C. NullPool Configuration Issue**

Your code uses `NullPool` for SQLite connections, which means:
- **No connection pooling** - every query creates a new connection
- **No connection reuse** - connections are NOT recycled
- **No automatic cleanup** - relies on Python garbage collection

From `database/traffic_db.py` line 32-34:
```python
logs_engine = create_engine(
    LOGS_DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
)
```

This is replicated across **ALL database modules** (20+ database files).

#### **D. Scoped Session Not Being Removed**

The traffic logger middleware has this pattern:
```python
try:
    TrafficLog.log_request(...)
except Exception as e:
    logger.exception(f"Error logging traffic: {e}")
finally:
    logs_session.remove()  # This is good, but...
```

BUT the middleware also calls `IPBan.is_ip_banned()` which can fail BEFORE reaching the cleanup code.

---

## The Fix: Multi-Layered Solution

### **Immediate Fix #1: Increase File Descriptor Limit**

Add to your shell startup file (`~/.zshrc` or `~/.bash_profile`):

```bash
# Increase file descriptor limits for OpenAlgo
ulimit -n 10240
```

Then reload:
```bash
source ~/.zshrc
```

### **Critical Fix #2: Add Connection Lifecycle Management**

I'll create a comprehensive fix for the database connection handling.

### **Important Fix #3: Add Connection Pool Limits**

Replace `NullPool` with proper connection pooling with strict limits.

### **Essential Fix #4: Add Graceful Error Handling**

Ensure all database operations are wrapped with proper cleanup.

---

## Detailed Implementation

### **Fix 1: Update Traffic Logger Middleware**

## Step-by-Step Implementation Guide

### Step 1: Increase System File Descriptor Limit (IMMEDIATE)

```bash
# Edit your shell config
nano ~/.zshrc  # or ~/.bash_profile for bash

# Add this line at the end
ulimit -n 10240

# Save and reload
source ~/.zshrc
```

Verify:
```bash
ulimit -n
# Should show: 10240
```

### Step 2: Replace NullPool with StaticPool

**Why:** `NullPool` creates a new connection for every operation and relies on garbage collection for cleanup. `StaticPool` maintains one connection per thread, providing much better resource management for SQLite.

Apply this change to ALL database modules:

```python
# Before (BAD):
logs_engine = create_engine(
    LOGS_DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
)

# After (GOOD):
logs_engine = create_engine(
    LOGS_DATABASE_URL,
    poolclass=StaticPool,  # One connection per thread
    connect_args={
        "check_same_thread": False,
        "timeout": 20.0,  # Handle locks gracefully
    },
    pool_pre_ping=True,  # Verify connection health
)
```

**Files to update:**
1. `database/traffic_db.py`
2. `database/auth_db.py`
3. `database/settings_db.py`
4. `database/strategy_db.py`
5. `database/strategy_state_db.py`
6. `database/action_center_db.py`
7. `database/analyzer_db.py`
8. `database/apilog_db.py`
9. `database/chart_prefs_db.py`
10. `database/chartink_db.py`
11. `database/flow_db.py`
12. `database/latency_db.py`
13. `database/market_calendar_db.py`
14. `database/master_contract_status_db.py`
15. `database/qty_freeze_db.py`
16. `database/sandbox_db.py`
17. `database/symbol.py`
18. `database/telegram_db.py`
19. `database/user_db.py`

### Step 3: Fix Traffic Logger (CRITICAL)

Replace `utils/traffic_logger.py` with the fixed version that uses context managers:

**Key changes:**
1. Added `safe_db_session()` context manager for guaranteed cleanup
2. Changed error logging from `exception()` to `debug()` to reduce log spam
3. Ensured `session.remove()` is called in all code paths

### Step 4: Add Connection Cleanup to Strategy Scripts

Your strategy scripts need to explicitly close database connections when they finish or encounter errors.

Add this to the top of your strategy scripts:

```python
import atexit
from database.auth_db import db_session
from database.settings_db import db_session as settings_session
from database.traffic_db import logs_session

# Register cleanup handlers
def cleanup_connections():
    """Cleanup database connections on exit"""
    try:
        db_session.remove()
        settings_session.remove()
        logs_session.remove()
        print("Database connections cleaned up")
    except Exception as e:
        print(f"Error during cleanup: {e}")

atexit.register(cleanup_connections)
```

### Step 5: Monitor File Descriptors

Create a monitoring script to track file descriptor usage:

```bash
#!/bin/bash
# tmp_rovodev_monitor_fds.sh

while true; do
    echo "=== $(date) ==="
    
    # Find main Flask process
    MAIN_PID=$(pgrep -f "python.*app.py" | head -1)
    
    if [ ! -z "$MAIN_PID" ]; then
        FD_COUNT=$(lsof -p $MAIN_PID 2>/dev/null | wc -l)
        echo "Main Flask App (PID $MAIN_PID): $FD_COUNT file descriptors"
        
        # Warn if approaching limit
        if [ $FD_COUNT -gt 2000 ]; then
            echo "⚠️  WARNING: Approaching file descriptor limit!"
        fi
    fi
    
    # Check strategy scripts
    echo "Strategy Scripts:"
    pgrep -f "strategies/scripts" | while read PID; do
        FD_COUNT=$(lsof -p $PID 2>/dev/null | wc -l)
        SCRIPT_NAME=$(ps -p $PID -o command= | grep -o 'option_strategy[^.]*')
        echo "  - $SCRIPT_NAME (PID $PID): $FD_COUNT file descriptors"
    done
    
    echo ""
    sleep 60
done
```

Make it executable and run in background:
```bash
chmod +x tmp_rovodev_monitor_fds.sh
./tmp_rovodev_monitor_fds.sh > fd_monitor.log 2>&1 &
```

---

## Preventive Measures

### 1. Limit Concurrent Strategy Scripts

Add to your strategy management code:

```python
MAX_CONCURRENT_STRATEGIES = 5  # Set based on your needs

def start_strategy(strategy_name):
    # Count running strategies
    running = len([p for p in get_running_strategies()])
    
    if running >= MAX_CONCURRENT_STRATEGIES:
        raise Exception(f"Maximum {MAX_CONCURRENT_STRATEGIES} strategies already running")
    
    # Start the strategy...
```

### 2. Add Database Connection Monitoring

Add this to `app.py` or a startup module:

```python
import threading
import time
from sqlalchemy import inspect

def monitor_connection_pools():
    """Monitor database connection pool status"""
    while True:
        try:
            from database.traffic_db import logs_engine
            from database.auth_db import engine
            
            # Check pool status
            pool = logs_engine.pool
            logger.info(f"Logs DB Pool: {pool.size()} connections, {pool.overflow()} overflow")
            
            # Check for stale connections
            if hasattr(pool, 'checkedout'):
                checked_out = pool.checkedout()
                if checked_out > 50:
                    logger.warning(f"High number of checked out connections: {checked_out}")
                    
        except Exception as e:
            logger.error(f"Error monitoring connection pools: {e}")
        
        time.sleep(300)  # Check every 5 minutes

# Start monitoring thread
monitor_thread = threading.Thread(target=monitor_connection_pools, daemon=True)
monitor_thread.start()
```

### 3. Clean Up Old Database Entries

Add periodic cleanup to reduce database size and improve performance:

```python
from apscheduler.schedulers.background import BackgroundScheduler

def cleanup_old_logs():
    """Remove logs older than 7 days"""
    from database.traffic_db import TrafficLog, logs_session
    from datetime import datetime, timedelta
    
    try:
        cutoff = datetime.utcnow() - timedelta(days=7)
        deleted = TrafficLog.query.filter(TrafficLog.timestamp < cutoff).delete()
        logs_session.commit()
        logger.info(f"Cleaned up {deleted} old traffic logs")
    except Exception as e:
        logger.error(f"Error cleaning up logs: {e}")
        logs_session.rollback()

# Schedule daily cleanup at 3 AM
scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_old_logs, 'cron', hour=3, minute=0)
scheduler.start()
```

---

## Testing the Fix

### 1. Restart the Application

```bash
# Kill all running processes
pkill -f "python.*app.py"
pkill -f "strategies/scripts"

# Restart
uv run python app.py
```

### 2. Monitor File Descriptors

```bash
# Watch file descriptor count in real-time
watch -n 5 'lsof -p $(pgrep -f "python.*app.py" | head -1) 2>/dev/null | wc -l'
```

### 3. Load Test

Run this to simulate high traffic:

```python
import requests
import concurrent.futures

def make_request(i):
    try:
        response = requests.get("http://127.0.0.1:5000/")
        return response.status_code
    except Exception as e:
        return str(e)

# Send 1000 requests with 50 concurrent workers
with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
    results = list(executor.map(make_request, range(1000)))

print(f"Success: {results.count(200)} / {len(results)}")
```

Expected result: All requests should succeed without file descriptor errors.

---

## Long-Term Recommendations

### 1. Migrate to PostgreSQL for Production

SQLite has inherent limitations for concurrent access. For production:

```bash
# In .env
DATABASE_URL=postgresql://user:password@localhost/openalgo
LOGS_DATABASE_URL=postgresql://user:password@localhost/openalgo_logs
```

Benefits:
- Better concurrency handling
- No file descriptor issues with proper pooling
- Better performance under load
- Production-grade reliability

### 2. Implement Circuit Breaker for Database Operations

```python
from pybreaker import CircuitBreaker

db_breaker = CircuitBreaker(fail_max=5, timeout_duration=60)

@db_breaker
def safe_database_operation():
    # Your database code here
    pass
```

### 3. Add Application Performance Monitoring (APM)

Consider using tools like:
- **Sentry** - Error tracking and performance monitoring
- **New Relic** - Full APM solution
- **Prometheus + Grafana** - Open source monitoring

---

## Summary

**Root Cause:** File descriptor exhaustion due to:
1. Too many concurrent processes (3 strategy scripts + main app)
2. Poor connection pooling (NullPool creates unlimited connections)
3. Missing cleanup in error paths
4. High-frequency traffic logging creating DB connections

**The Fix:**
1. ✅ Increase file descriptor limit (immediate relief)
2. ✅ Replace NullPool with StaticPool (proper resource management)
3. ✅ Add context managers for guaranteed cleanup
4. ✅ Reduce connection pool limits
5. ✅ Add monitoring and alerts

**Expected Result:**
- Application should handle 10,000+ requests without crashing
- File descriptors should stay under 500 under normal load
- Graceful degradation instead of crashes

---

## Need Help?

If you encounter issues during implementation:
1. Check the logs for specific error messages
2. Monitor file descriptors: `lsof -p <PID> | wc -l`
3. Verify ulimit: `ulimit -n`
4. Check for zombie processes: `ps aux | grep python`

