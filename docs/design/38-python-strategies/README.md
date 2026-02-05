# 38 - Python Strategies Hosting

## Overview

OpenAlgo provides a cross-platform Python strategy hosting system that allows users to upload, run, schedule, and manage trading strategies. Each strategy runs in a separate process for complete isolation with support for Windows, Linux, and macOS.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    Python Strategy Hosting Architecture                       │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          Web Interface (/python)                             │
│                                                                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐       │
│  │    Upload    │ │    Start     │ │   Schedule   │ │    Delete    │       │
│  │   Strategy   │ │   Strategy   │ │   Strategy   │ │   Strategy   │       │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘       │
│         │                │                │                │                │
└─────────┴────────────────┴────────────────┴────────────────┴────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Strategy Management Layer                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  RUNNING_STRATEGIES = {}   # {strategy_id: {'process', 'started'}} │   │
│  │  STRATEGY_CONFIGS = {}     # {strategy_id: config_dict}             │   │
│  │  SCHEDULER (APScheduler)   # Background job scheduler               │   │
│  │  PROCESS_LOCK              # Thread-safe process operations         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Process Isolation Layer                                 │
│                                                                              │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐                  │
│  │  Strategy 1    │ │  Strategy 2    │ │  Strategy 3    │  ...              │
│  │  (subprocess)  │ │  (subprocess)  │ │  (subprocess)  │                  │
│  │                │ │                │ │                │                  │
│  │  - Own PID     │ │  - Own PID     │ │  - Own PID     │                  │
│  │  - Own memory  │ │  - Own memory  │ │  - Own memory  │                  │
│  │  - Own stdout  │ │  - Own stdout  │ │  - Own stdout  │                  │
│  │  - Own stderr  │ │  - Own stderr  │ │  - Own stderr  │                  │
│  └────────────────┘ └────────────────┘ └────────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           File System                                        │
│                                                                              │
│  strategies/                                                                 │
│  ├── scripts/                    # Strategy Python files                    │
│  │   ├── strategy_1.py                                                      │
│  │   ├── strategy_2.py                                                      │
│  │   └── ...                                                                │
│  └── strategy_configs.json       # Persistent configuration                 │
│                                                                              │
│  log/                                                                        │
│  └── strategies/                 # Strategy output logs                     │
│      ├── strategy_1.log                                                     │
│      ├── strategy_2.log                                                     │
│      └── ...                                                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
openalgo/
├── strategies/
│   ├── scripts/           # User uploaded strategy files
│   │   ├── my_strategy.py
│   │   └── scalper.py
│   └── strategy_configs.json  # Configuration persistence
├── log/
│   └── strategies/        # Log output from strategies
│       ├── my_strategy.log
│       └── scalper.log
└── blueprints/
    └── python_strategy.py  # Strategy hosting blueprint
```

## Key Features

### Process Isolation

Each strategy runs in a separate subprocess:

```python
RUNNING_STRATEGIES = {}  # {strategy_id: {'process': subprocess.Popen, 'started_at': datetime}}

def start_strategy(strategy_id):
    """Start a strategy in an isolated subprocess"""
    script_path = STRATEGIES_DIR / f"{strategy_id}.py"
    log_path = LOGS_DIR / f"{strategy_id}.log"

    with PROCESS_LOCK:
        # Open log file for output
        log_file = open(log_path, 'a', encoding='utf-8')

        # Start subprocess
        process = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(STRATEGIES_DIR.parent),  # Working directory
            env=os.environ.copy()
        )

        RUNNING_STRATEGIES[strategy_id] = {
            'process': process,
            'started_at': datetime.now(IST),
            'log_file': log_file
        }
```

### Cross-Platform Support

| Platform | Support | Notes |
|----------|---------|-------|
| Windows | Full | Uses subprocess |
| Linux | Full | Uses subprocess |
| macOS | Full | Uses subprocess |

```python
OS_TYPE = platform.system().lower()  # 'windows', 'linux', 'darwin'
IS_WINDOWS = OS_TYPE == 'windows'
IS_MAC = OS_TYPE == 'darwin'
IS_LINUX = OS_TYPE == 'linux'
```

## Strategy Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│                    Strategy Lifecycle                            │
└─────────────────────────────────────────────────────────────────┘

    Upload                  Start                  Running
       │                      │                      │
       ▼                      ▼                      ▼
  ┌─────────┐           ┌─────────┐           ┌─────────┐
  │ Upload  │ ────────▶ │ Pending │ ────────▶ │ Running │
  │ .py file│           │         │           │         │
  └─────────┘           └─────────┘           └─────────┘
       │                      │                      │
       │                      │ Schedule             │ Stop
       │                      ▼                      ▼
       │              ┌─────────────┐          ┌─────────┐
       │              │  Scheduled  │          │ Stopped │
       │              │ (APScheduler│          │         │
       │              └─────────────┘          └─────────┘
       │                      │                      │
       │                      │ Auto-start           │
       │                      ▼                      │
       │              ┌─────────┐                    │
       │              │ Running │ ◀─────────────────┘
       │              │(at time)│      Restart
       │              └─────────┘
       │
       │ Delete
       ▼
  ┌─────────┐
  │ Deleted │
  └─────────┘
```

## Scheduling with APScheduler

### Scheduler Configuration

```python
IST = pytz.timezone('Asia/Kolkata')

def init_scheduler():
    """Initialize the APScheduler with IST timezone"""
    global SCHEDULER
    SCHEDULER = BackgroundScheduler(daemon=True, timezone=IST)
    SCHEDULER.start()

    # Daily trading day check - runs at 00:01 IST
    SCHEDULER.add_job(
        func=daily_trading_day_check,
        trigger=CronTrigger(hour=0, minute=1, timezone=IST),
        id='daily_trading_day_check',
        replace_existing=True
    )

    # Market hours enforcer - runs every minute
    SCHEDULER.add_job(
        func=market_hours_enforcer,
        trigger='interval',
        minutes=1,
        id='market_hours_enforcer',
        replace_existing=True
    )
```

### Schedule Options

| Schedule Type | Description | Example |
|---------------|-------------|---------|
| One-time | Start at specific time | 09:15 IST |
| Interval | Repeat at fixed interval | Every 5 minutes |
| Cron | Complex scheduling | Weekdays at 09:15 |
| Market Hours | Only during trading | 09:15 - 15:30 |

### Market-Aware Scheduling

```python
def daily_trading_day_check():
    """Stop scheduled strategies on weekends/holidays"""
    if is_market_holiday(date.today()) or not is_market_open():
        for strategy_id in list(RUNNING_STRATEGIES.keys()):
            config = STRATEGY_CONFIGS.get(strategy_id, {})
            if config.get('scheduled'):
                stop_strategy(strategy_id)

def market_hours_enforcer():
    """Stop scheduled strategies when market closes"""
    status = get_market_hours_status()
    if status['status'] == 'closed':
        for strategy_id in list(RUNNING_STRATEGIES.keys()):
            config = STRATEGY_CONFIGS.get(strategy_id, {})
            if config.get('stop_at_market_close'):
                stop_strategy(strategy_id)
```

## User Ownership & Security

### Strategy Ownership Verification

```python
def verify_strategy_ownership(strategy_id, user_id, return_config=False):
    """Verify that a user owns a strategy"""

    # Reject path traversal attempts
    if '..' in strategy_id or '/' in strategy_id or '\\' in strategy_id:
        return False, (jsonify({'error': 'Invalid strategy ID'}), 400)

    if strategy_id not in STRATEGY_CONFIGS:
        return False, (jsonify({'error': 'Strategy not found'}), 404)

    config = STRATEGY_CONFIGS[strategy_id]
    strategy_owner = config.get('user_id')

    # Check ownership
    if strategy_owner and strategy_owner != user_id:
        return False, (jsonify({'error': 'Unauthorized'}), 403)

    return True, config if return_config else None
```

### Security Features

| Feature | Implementation |
|---------|----------------|
| User isolation | Each user sees only their strategies |
| Path traversal protection | Reject `..`, `/`, `\` in strategy IDs |
| Secure filename | `werkzeug.utils.secure_filename()` |
| Process isolation | Separate subprocess per strategy |

## Server-Sent Events (SSE)

Real-time status updates via SSE:

```python
SSE_SUBSCRIBERS = []  # List of Queue objects for SSE clients

def broadcast_status_update(strategy_id: str, status: str, message: str = None):
    """Broadcast strategy status update to all SSE subscribers"""
    event_data = {
        'strategy_id': strategy_id,
        'status': status,
        'message': message,
        'timestamp': datetime.now(IST).isoformat()
    }

    with SSE_LOCK:
        for q in SSE_SUBSCRIBERS:
            try:
                q.put_nowait(f"data: {json.dumps(event_data)}\n\n")
            except:
                pass  # Queue full or dead
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/python/` | GET | List all strategies |
| `/python/upload` | POST | Upload new strategy |
| `/python/start/<id>` | POST | Start a strategy |
| `/python/stop/<id>` | POST | Stop a strategy |
| `/python/schedule/<id>` | POST | Schedule a strategy |
| `/python/delete/<id>` | DELETE | Delete a strategy |
| `/python/logs/<id>` | GET | Get strategy logs |
| `/python/status/<id>` | GET | Get strategy status |
| `/python/events` | GET | SSE status stream |

## Configuration Persistence

```python
CONFIG_FILE = Path('strategies') / 'strategy_configs.json'

def save_configs():
    """Save strategy configurations to file"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(STRATEGY_CONFIGS, f, indent=2, default=str)

# Example config structure
{
    "my_strategy": {
        "user_id": "admin",
        "filename": "my_strategy.py",
        "created_at": "2024-01-15T09:00:00+05:30",
        "scheduled": true,
        "start_time": "09:15",
        "stop_time": "15:30",
        "stop_at_market_close": true,
        "market_days_only": true
    }
}
```

## Operational Guidelines

### Best Practices

1. **Keep strategies stateless** - Don't rely on global state between runs
2. **Use logging** - Write to stdout/stderr for log capture
3. **Handle graceful shutdown** - Catch SIGTERM/SIGINT
4. **Use OpenAlgo API** - Don't bypass the API layer

### Example Strategy Template

```python
#!/usr/bin/env python
"""
Example OpenAlgo Strategy
"""
import requests
import time
import signal
import sys

# Configuration
API_KEY = "your_api_key_here"
BASE_URL = "http://localhost:5000/api/v1"

running = True

def signal_handler(sig, frame):
    global running
    print("Shutdown signal received")
    running = False

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def get_quote(symbol, exchange):
    response = requests.post(
        f"{BASE_URL}/quotes",
        json={
            "apikey": API_KEY,
            "symbol": symbol,
            "exchange": exchange
        }
    )
    return response.json()

def place_order(symbol, exchange, action, quantity):
    response = requests.post(
        f"{BASE_URL}/placeorder",
        json={
            "apikey": API_KEY,
            "symbol": symbol,
            "exchange": exchange,
            "action": action,
            "quantity": quantity,
            "product": "MIS",
            "pricetype": "MARKET"
        }
    )
    return response.json()

def main():
    print("Strategy started")

    while running:
        try:
            # Your trading logic here
            quote = get_quote("SBIN", "NSE")
            print(f"SBIN LTP: {quote.get('ltp')}")

            time.sleep(60)  # Check every minute

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)

    print("Strategy stopped")

if __name__ == "__main__":
    main()
```

### Log Monitoring

```bash
# View live logs
tail -f log/strategies/my_strategy.log

# View recent logs
cat log/strategies/my_strategy.log | tail -100
```

## Resource Configuration

### Memory Limits

Each strategy subprocess has a configurable memory limit to prevent runaway strategies from crashing the system:

```python
# Default: 1024MB, configurable via environment variable
STRATEGY_MEMORY_LIMIT_MB = int(os.environ.get('STRATEGY_MEMORY_LIMIT_MB', '1024'))
```

| Container RAM | Recommended Limit | Max Concurrent Strategies |
|---------------|-------------------|---------------------------|
| 2GB | 256MB | 5 |
| 4GB | 512MB | 5-8 |
| 8GB+ | 1024MB (default) | 10+ |

### Thread Limiting for Docker

When running strategies with numerical libraries (NumPy, SciPy, Numba) in Docker, thread limits prevent `RLIMIT_NPROC` exhaustion:

| Variable | Purpose |
|----------|---------|
| `OPENBLAS_NUM_THREADS` | OpenBLAS thread limit |
| `OMP_NUM_THREADS` | OpenMP thread limit |
| `MKL_NUM_THREADS` | Intel MKL thread limit |
| `NUMEXPR_NUM_THREADS` | NumExpr thread limit |
| `NUMBA_NUM_THREADS` | Numba JIT thread limit |

For 2GB containers, set all to `1`. For 4GB+, use `2`. See [Docker Configuration](../11-docker/README.md) for details.

> **Reference**: [GitHub Issue #822](https://github.com/marketcalls/openalgo/issues/822)

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/python_strategy.py` | Strategy hosting blueprint |
| `strategies/scripts/` | User strategy files |
| `strategies/strategy_configs.json` | Configuration persistence |
| `log/strategies/` | Strategy log output |
| `database/market_calendar_db.py` | Market hours/holidays |
