# Python Strategies Process Management

Complete documentation for subprocess isolation, lifecycle management, and cross-platform support.

## Overview

Each Python strategy runs in an isolated subprocess with its own Python interpreter, environment, and resource limits.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Flask Application                                    │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │              Python Strategy Blueprint (blueprints/python_strategy.py)  ││
│  │  • Strategy upload/delete                                                ││
│  │  • Start/stop control                                                    ││
│  │  • Schedule management                                                   ││
│  │  • Log streaming                                                         ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                              │                                               │
│     ┌────────────────────────┼────────────────────────┐                     │
│     ▼                        ▼                        ▼                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │  Strategy 1  │    │  Strategy 2  │    │  Strategy 3  │                  │
│  │  Subprocess  │    │  Subprocess  │    │  Subprocess  │                  │
│  │  PID: 12345  │    │  PID: 12346  │    │  PID: 12347  │                  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                  │
│         │                   │                   │                           │
│         └───────────────────┼───────────────────┘                           │
│                             ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                        Process Registry                                  ││
│  │  RUNNING_STRATEGIES = {                                                  ││
│  │    'strategy_1': {'process': <Process>, 'pid': 12345, 'start_time': ...}││
│  │    'strategy_2': {'process': <Process>, 'pid': 12346, 'start_time': ...}││
│  │  }                                                                       ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

## Process Creation

### Subprocess Launch

```python
def start_strategy(strategy_id):
    """Launch strategy in isolated subprocess"""
    config = get_strategy_config(strategy_id)
    script_path = Path(f"strategies/scripts/{config['file_path']}")

    # Prepare environment
    env = os.environ.copy()
    env['OPENALGO_APIKEY'] = get_api_key()
    env['OPENALGO_HOST'] = get_host_url()
    env['PYTHONUNBUFFERED'] = '1'  # Real-time output

    # Prepare log file
    log_file = Path(f"log/strategies/{strategy_id}.log")
    log_handle = open(log_file, 'a', buffering=1)

    # Platform-specific subprocess options
    kwargs = {
        'stdout': log_handle,
        'stderr': subprocess.STDOUT,
        'env': env,
        'cwd': str(Path.cwd()),
    }

    # Unix-specific: Create new process group
    if os.name != 'nt':
        kwargs['preexec_fn'] = os.setsid

    # Windows-specific: Create new process group
    else:
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP

    # Launch subprocess
    process = subprocess.Popen(
        [sys.executable, str(script_path)],
        **kwargs
    )

    # Register in process registry
    RUNNING_STRATEGIES[strategy_id] = {
        'process': process,
        'pid': process.pid,
        'log_handle': log_handle,
        'start_time': datetime.now(),
        'user_id': current_user_id
    }

    return process.pid
```

## Process Termination

### Graceful Shutdown

```python
def stop_strategy(strategy_id):
    """Stop strategy with graceful shutdown"""
    if strategy_id not in RUNNING_STRATEGIES:
        return False, "Strategy not running"

    info = RUNNING_STRATEGIES[strategy_id]
    process = info['process']

    try:
        if os.name != 'nt':
            # Unix: Send SIGTERM to process group
            pgid = os.getpgid(process.pid)
            os.killpg(pgid, signal.SIGTERM)
        else:
            # Windows: Send CTRL_BREAK_EVENT
            process.send_signal(signal.CTRL_BREAK_EVENT)

        # Wait for graceful termination (5 seconds)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Force kill if still running
            kill_strategy_force(strategy_id)

    except ProcessLookupError:
        # Process already terminated
        pass

    finally:
        cleanup_strategy(strategy_id)

    return True, "Strategy stopped"
```

### Force Kill

```python
def kill_strategy_force(strategy_id):
    """Force kill strategy and all child processes"""
    info = RUNNING_STRATEGIES.get(strategy_id)
    if not info:
        return

    process = info['process']

    try:
        if os.name != 'nt':
            # Unix: Kill entire process group
            pgid = os.getpgid(process.pid)
            os.killpg(pgid, signal.SIGKILL)
        else:
            # Windows: Kill process tree
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(process.pid)],
                capture_output=True
            )
    except Exception as e:
        logger.error(f"Force kill error: {e}")
```

### Child Process Handling

```
┌─────────────────────────────────────────────────────────────┐
│  Strategy Process (PID: 12345)                              │
│     │                                                        │
│     ├── Child Thread 1 (WebSocket listener)                 │
│     ├── Child Thread 2 (Data fetcher)                       │
│     └── Child Process (subprocess.run)                      │
│            └── Grandchild Process                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  On stop_strategy():                                         │
│  1. SIGTERM sent to process group (pgid)                    │
│  2. All processes in group receive signal                   │
│  3. Threads terminate when main process exits               │
│  4. Resources cleaned up                                     │
└─────────────────────────────────────────────────────────────┘
```

## Resource Limits (Unix)

```python
# Configurable via environment variable (default: 1024MB)
STRATEGY_MEMORY_LIMIT_MB = int(os.environ.get('STRATEGY_MEMORY_LIMIT_MB', '1024'))

def set_resource_limits():
    """Set resource limits for subprocess (Unix only)"""
    import resource

    # Memory limit: configurable (default 1024MB)
    memory_limit = STRATEGY_MEMORY_LIMIT_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

    # CPU time limit: No limit (managed by scheduler)
    # resource.setrlimit(resource.RLIMIT_CPU, (unlimited, unlimited))

    # File descriptor limit: 1024
    resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
```

### Docker Thread Limiting

When running in Docker, numerical libraries (OpenBLAS, NumPy, Numba) must be thread-limited to prevent `RLIMIT_NPROC` exhaustion:

| Variable | Purpose | Recommended Value |
|----------|---------|-------------------|
| `OPENBLAS_NUM_THREADS` | OpenBLAS threads | 1-2 |
| `OMP_NUM_THREADS` | OpenMP threads | 1-2 |
| `MKL_NUM_THREADS` | Intel MKL threads | 1-2 |
| `NUMEXPR_NUM_THREADS` | NumExpr threads | 1-2 |
| `NUMBA_NUM_THREADS` | Numba JIT threads | 1-2 |

### Resource Scaling Guidelines

| Container RAM | Thread Limit | Memory/Strategy | Max Strategies |
|---------------|--------------|-----------------|----------------|
| 2GB | 1 | 256MB | 5 |
| 4GB | 2 | 512MB | 5-8 |
| 8GB+ | 2-4 | 1024MB | 10+ |

> **Reference**: [GitHub Issue #822](https://github.com/marketcalls/openalgo/issues/822) documents the RLIMIT_NPROC fix.

## Process Monitoring

### Health Check

```python
def check_strategy_health():
    """Check health of all running strategies"""
    for strategy_id, info in list(RUNNING_STRATEGIES.items()):
        process = info['process']

        # Check if process is alive
        poll_result = process.poll()

        if poll_result is not None:
            # Process has terminated
            exit_code = poll_result
            logger.warning(f"Strategy {strategy_id} terminated with code {exit_code}")

            # Update config
            update_strategy_status(strategy_id, 'stopped', exit_code)

            # Cleanup
            cleanup_strategy(strategy_id)

            # Emit status update
            emit_strategy_status(strategy_id, {
                'status': 'stopped',
                'exit_code': exit_code,
                'message': 'Process terminated unexpectedly'
            })
```

### Auto-Restart (Optional)

```python
def auto_restart_strategy(strategy_id):
    """Auto-restart crashed strategy if configured"""
    config = get_strategy_config(strategy_id)

    if config.get('auto_restart', False):
        restart_count = config.get('restart_count', 0)

        if restart_count < MAX_RESTARTS:
            logger.info(f"Auto-restarting {strategy_id}")
            time.sleep(5)  # Backoff
            start_strategy(strategy_id)
            update_config(strategy_id, {'restart_count': restart_count + 1})
```

## Log Streaming

### Real-Time Log Output

```python
def stream_logs(strategy_id):
    """Stream logs via SSE (Server-Sent Events)"""
    log_file = Path(f"log/strategies/{strategy_id}.log")

    def generate():
        with open(log_file, 'r') as f:
            # Start from end of file
            f.seek(0, 2)

            while True:
                line = f.readline()
                if line:
                    yield f"data: {json.dumps({'log': line.strip()})}\n\n"
                else:
                    time.sleep(0.1)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache'}
    )
```

### Log File Management

```python
def setup_log_rotation(strategy_id):
    """Setup log rotation for strategy"""
    log_file = Path(f"log/strategies/{strategy_id}.log")

    # Rotate if > 10MB
    if log_file.exists() and log_file.stat().st_size > 10 * 1024 * 1024:
        # Rename to .log.1, .log.2, etc.
        for i in range(4, 0, -1):
            old_log = log_file.with_suffix(f'.log.{i}')
            new_log = log_file.with_suffix(f'.log.{i+1}')
            if old_log.exists():
                old_log.rename(new_log)

        log_file.rename(log_file.with_suffix('.log.1'))
```

## Directory Structure

```
openalgo/
├── strategies/
│   ├── scripts/                    # User-uploaded strategies
│   │   ├── ema_crossover.py
│   │   ├── rsi_strategy.py
│   │   └── my_custom_strategy.py
│   ├── examples/                   # Template strategies
│   │   ├── simple_ema.py
│   │   └── webhook_handler.py
│   └── strategy_configs.json       # Strategy configurations
├── log/
│   └── strategies/                 # Strategy output logs
│       ├── ema_crossover.log
│       ├── ema_crossover.log.1     # Rotated logs
│       └── rsi_strategy.log
└── blueprints/
    └── python_strategy.py          # Main blueprint (2500+ lines)
```

## Configuration Schema

```json
{
  "strategy_id": {
    "name": "EMA Crossover",
    "file_path": "ema_crossover.py",
    "user_id": "user123",
    "is_running": false,
    "is_scheduled": true,
    "schedule_start": "09:20",
    "schedule_stop": "15:15",
    "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
    "last_started": "2024-01-15T09:20:00",
    "last_stopped": "2024-01-15T15:15:00",
    "pid": null,
    "manually_stopped": false,
    "auto_restart": false,
    "restart_count": 0
  }
}
```

## Cross-Platform Compatibility

| Feature | Unix (Linux/macOS) | Windows |
|---------|-------------------|---------|
| Process groups | `os.setsid()` | `CREATE_NEW_PROCESS_GROUP` |
| Graceful stop | `SIGTERM` to pgid | `CTRL_BREAK_EVENT` |
| Force kill | `SIGKILL` to pgid | `taskkill /F /T` |
| Resource limits | `resource.setrlimit()` | Not supported |
| Log streaming | Unbuffered stdout | Unbuffered stdout |

## Error Handling

### Common Errors

| Error | Cause | Resolution |
|-------|-------|------------|
| `ProcessLookupError` | Process already terminated | Clean up registry |
| `PermissionError` | Cannot signal process | Check process ownership |
| `FileNotFoundError` | Script file missing | Re-upload strategy |
| `OSError: [Errno 12]` | Cannot fork (memory) | Free system resources |

### Recovery Procedures

```python
def recover_orphan_processes():
    """Find and clean up orphan strategy processes on startup"""
    for config_id, config in load_all_configs().items():
        if config.get('is_running') and config.get('pid'):
            pid = config['pid']

            # Check if process exists
            try:
                os.kill(pid, 0)  # Doesn't kill, just checks
                logger.info(f"Found running strategy: {config_id} (PID: {pid})")
                # Re-register in RUNNING_STRATEGIES if needed
            except ProcessLookupError:
                logger.warning(f"Orphan config found: {config_id}")
                update_strategy_status(config_id, 'stopped')
```

## Related Documentation

| Document | Description |
|----------|-------------|
| [Python Strategies PRD](./python-strategies.md) | Product requirements |
| [Scheduling Guide](./python-strategies-scheduling.md) | Market-aware scheduling |
| [API Reference](./python-strategies-api-reference.md) | Complete API documentation |
