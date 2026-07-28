# /python Strategy Resource Limits

## How strategies are isolated

Each strategy runs as a **separate subprocess** (`subprocess.Popen`). It gets its own PID, memory space, file descriptor table, and CPU time accounting. A crash or resource exhaustion in one strategy cannot directly affect another strategy or the host Flask process.

## Memory

### What a strategy actually uses

| Component | Typical RAM |
|---|---|
| Python interpreter baseline | ~20-30 MB |
| `openalgo` SDK + `requests`/`httpx` | ~5-10 MB |
| `pandas` + `numpy` (imported) | ~40-60 MB |
| Historical DataFrame (500 candles, 6 columns) | ~1-2 MB |
| Historical DataFrame (50,000 candles, 6 columns) | ~10-15 MB |
| WebSocket connection + message buffers | ~5-10 MB |

**A typical EMA/crossover strategy uses 80-120 MB.**

### The memory limit

The host enforces a per-strategy virtual memory cap via `RLIMIT_AS` (Unix/Mac only; not enforced on Windows):

```
STRATEGY_MEMORY_LIMIT_MB=1024   # default, set in .env
```

When a strategy exceeds this, the OS kills it with a `MemoryError` or `SIGKILL`. The host's dead-process reaper (runs every 60 seconds) detects it and marks the strategy as stopped.

### Recommended settings

| Server RAM | Subtract for host | Available for strategies | `STRATEGY_MEMORY_LIMIT_MB` | Max strategies |
|---|---|---|---|---|
| 2 GB | ~800 MB | ~1.2 GB | 256 | 4-5 |
| 4 GB | ~800 MB | ~3.2 GB | 512 | 6-8 |
| 8 GB | ~1 GB | ~7 GB | 1024 (default) | 6-7 |
| 16 GB+ | ~1 GB | ~15 GB | 1024 | 12-15 |

The "host" includes Flask, broker WebSocket adapter, ZeroMQ, WebSocket proxy, APScheduler, and SQLite. It typically uses 500 MB-1 GB depending on broker and number of subscribed symbols.

### Why the default is 1024 MB

Most strategies never use more than 200 MB. The 1 GB cap is generous to accommodate:
- ML model loading (scikit-learn, lightweight TF/PyTorch)
- Large historical data pulls (months of tick data)
- Memory spikes during pandas operations (merge/concat temporarily doubles usage)

If your strategies are simple signal checkers, lower it to 256-512 MB and run more strategies.

## File descriptors (FDs)

### What a strategy actually opens

| FD | Purpose |
|---|---|
| 0 | stdin (inherited, unused) |
| 1 | stdout (redirected to strategy log file) |
| 2 | stderr (merged into stdout) |
| 3-4 | HTTP connection to OpenAlgo API (socket + TLS) |
| 5-6 | WebSocket connection (if using `client.connect()`) |
| 7-8 | Occasional: imported library configs, temp files |

**A typical strategy uses 5-10 FDs.**

### The FD limit

```
RLIMIT_NOFILE = 256   # hardcoded in set_resource_limits(), Unix/Mac only
```

This is a **safety cap**, not a target. It prevents a buggy script that opens files in a loop from exhausting the OS file descriptor table (which would starve the host and all other strategies).

### Why FDs are not the bottleneck

Each strategy is a separate process with its own FD table. Strategy A's 5-10 FDs don't count against Strategy B's limit. The OS typically allows 1024+ FDs per process. The 256 cap is purely defensive.

The host process itself uses ~0 FDs per running strategy at steady state. The parent-side log handle is closed immediately after `Popen` inherits it (FD hygiene fix, commit `fa549b47f`).

## CPU time

### The limit

```
RLIMIT_CPU = 3600 seconds   # hardcoded, cumulative CPU time
```

This is **cumulative CPU seconds**, not wall clock time. A strategy sleeping 59 seconds and computing for 1 second each minute uses ~1 CPU-second per minute = 60 CPU-seconds per hour. It would take 60 hours of wall time to hit the 3600-second limit.

### When it triggers

Only pathological code hits this: infinite tight loops without sleep, runaway ML training, recursive computations. Normal strategies that `time.sleep()` between signal checks will never come close.

When triggered, the OS sends `SIGXCPU` followed by `SIGKILL`. The host reaper detects the dead process.

## Process limit

```
RLIMIT_NPROC = 256   # hardcoded, Unix/Mac only
```

Prevents a strategy from spawning unlimited child processes (fork bomb). Normal strategies that use `threading.Thread` for WebSocket listeners are unaffected — threads count against this limit only on some Linux kernels, and 256 is far more than needed.

## Log limits

Per-strategy log files are bounded by three settings:

| Setting | Default | Purpose |
|---|---|---|
| `STRATEGY_LOG_MAX_FILES` | 10 | Max log files kept per strategy |
| `STRATEGY_LOG_MAX_SIZE_MB` | 50 | Max total log size per strategy |
| `STRATEGY_LOG_RETENTION_DAYS` | 7 | Delete logs older than this |

Cleanup runs automatically when a strategy stops. One strategy's verbose logging cannot evict another's logs — limits are enforced per strategy ID.

## Platform differences

| Limit | Linux | macOS | Windows |
|---|---|---|---|
| `RLIMIT_AS` (memory) | Enforced | Enforced | Not available |
| `RLIMIT_CPU` (CPU time) | Enforced | Enforced | Not available |
| `RLIMIT_NOFILE` (FDs) | Enforced | Enforced | Not available |
| `RLIMIT_NPROC` (processes) | Enforced | Enforced | Not available |
| Process isolation | `start_new_session` | `start_new_session` | `CREATE_NEW_PROCESS_GROUP` |

On Windows, resource limits are not enforced at the OS level. Strategies can use unlimited memory/FDs/CPU. Monitor via Task Manager.

## Quick reference

```bash
# Check current defaults
grep STRATEGY_ .env

# Override in .env
STRATEGY_MEMORY_LIMIT_MB=256     # tighter cap, run more strategies
STRATEGY_LOG_MAX_FILES=5         # less disk per strategy
STRATEGY_LOG_MAX_SIZE_MB=25      # less disk per strategy
STRATEGY_LOG_RETENTION_DAYS=3    # faster cleanup
```

## Monitoring

Check a running strategy's actual resource usage:

```bash
# Memory (RSS = actual RAM used)
ps -o pid,rss,vsz,comm -p $(cat strategies/strategy_configs.json | python -c "import sys,json; [print(v.get('pid','')) for v in json.load(sys.stdin).values() if v.get('pid')]")

# Open file descriptors (Linux)
ls -la /proc/<PID>/fd | wc -l

# Open file descriptors (macOS)
lsof -p <PID> | wc -l
```

Replace `<PID>` with the strategy's process ID shown in the /python dashboard.
