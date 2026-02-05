# PRD: Python Strategies - Automated Strategy Execution

> **Status:** ✅ Stable - Fully implemented, production-ready

## Overview

Python Strategies enables traders to run custom Python trading algorithms within OpenAlgo, with process isolation, market-aware scheduling, and comprehensive lifecycle management.

## Problem Statement

Traders need to:
- Run Python-based trading strategies without infrastructure management
- Schedule strategies around market hours automatically
- Monitor strategy execution with real-time logs
- Safely test strategies in sandbox mode before live trading

## Solution

A subprocess-based strategy execution system that:
- Runs each strategy in isolated Python process
- Integrates with APScheduler for market-aware scheduling
- Provides real-time log streaming via SSE
- Supports Windows, Linux, and macOS

## Target Users

| User | Use Case |
|------|----------|
| Algo Developer | Run custom Python strategies |
| Technical Trader | Automate EMA/RSI-based systems |
| Quant Researcher | Deploy ML models for trading |

## Functional Requirements

### FR1: Strategy Management
| ID | Requirement | Priority |
|----|-------------|----------|
| FR1.1 | Upload Python strategy files | P0 |
| FR1.2 | Start/stop strategy execution | P0 |
| FR1.3 | Delete strategy and logs | P0 |
| FR1.4 | View strategy source code | P1 |
| FR1.5 | Edit strategy configuration | P1 |

### FR2: Process Isolation
| ID | Requirement | Priority |
|----|-------------|----------|
| FR2.1 | Run each strategy in subprocess | P0 |
| FR2.2 | Resource limits (memory, CPU) | P1 |
| FR2.3 | Cross-platform support (Win/Linux/Mac) | P0 |
| FR2.4 | Graceful shutdown with SIGTERM | P0 |
| FR2.5 | Kill child processes on termination | P0 |

### FR3: Scheduling
| ID | Requirement | Priority |
|----|-------------|----------|
| FR3.1 | Configure start/stop times (IST) | P0 |
| FR3.2 | Select trading days (Mon-Sat) | P0 |
| FR3.3 | Auto-stop on market holidays | P0 |
| FR3.4 | Auto-stop on weekends | P0 |
| FR3.5 | Resume on next trading day | P0 |
| FR3.6 | Persist schedules across restarts | P0 |

### FR4: Logging
| ID | Requirement | Priority |
|----|-------------|----------|
| FR4.1 | Capture stdout/stderr to log file | P0 |
| FR4.2 | Real-time log streaming (SSE) | P0 |
| FR4.3 | View historical logs | P0 |
| FR4.4 | Log file rotation | P1 |
| FR4.5 | Log cleanup (retention policy) | P1 |

### FR5: Status Monitoring
| ID | Requirement | Priority |
|----|-------------|----------|
| FR5.1 | Real-time status updates (SSE) | P0 |
| FR5.2 | Track running/stopped/error states | P0 |
| FR5.3 | Display uptime and PID | P1 |
| FR5.4 | Error message capture | P0 |

### FR6: API Integration
| ID | Requirement | Priority |
|----|-------------|----------|
| FR6.1 | OpenAlgo SDK available to strategies | P0 |
| FR6.2 | Environment variables for API key | P0 |
| FR6.3 | Access to all OpenAlgo API endpoints | P0 |

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Strategy startup time | < 5 seconds |
| Log latency (event → display) | < 1 second |
| Max concurrent strategies | 50 (system-dependent) |
| Memory per strategy | 256MB-1024MB (configurable) |
| Scheduler precision | ±1 minute |

### Docker Resource Requirements

| Container RAM | Thread Limit | Memory/Strategy | Max Strategies |
|---------------|--------------|-----------------|----------------|
| 2GB | 1 | 256MB | 5 |
| 4GB | 2 | 512MB | 5-8 |
| 8GB+ | 2-4 | 1024MB | 10+ |

> **Note**: Thread limits (`OPENBLAS_NUM_THREADS`, etc.) prevent RLIMIT_NPROC exhaustion when using NumPy/SciPy/Numba. See [Issue #822](https://github.com/marketcalls/openalgo/issues/822).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Flask Application                         │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Python Strategy Blueprint                    ││
│  │  Routes: /python/new, /start, /stop, /schedule, /logs   ││
│  └─────────────────────────────────────────────────────────┘│
│                           │                                  │
│     ┌─────────────────────┼─────────────────────┐           │
│     ▼                     ▼                     ▼           │
│  ┌──────────┐      ┌────────────┐       ┌────────────┐     │
│  │ Process  │      │ APScheduler│       │ SSE Server │     │
│  │ Manager  │      │  (IST TZ)  │       │  (Status)  │     │
│  └────┬─────┘      └─────┬──────┘       └────────────┘     │
│       │                  │                                  │
│       ▼                  ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                 Strategy Subprocess                   │  │
│  │  • Isolated Python process                            │  │
│  │  • Resource limits (Unix)                             │  │
│  │  • Unbuffered stdout for real-time logs               │  │
│  └───────────────────────┬──────────────────────────────┘  │
│                          │                                  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              OpenAlgo SDK (openalgo)                   │  │
│  │  • client.placesmartorder()                           │  │
│  │  • client.history()                                   │  │
│  │  • client.quotes()                                    │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Strategy Template

```python
#!/usr/bin/env python
"""
Simple EMA Crossover Strategy Template
"""
import os
import time
from openalgo import api

# Configuration
API_KEY = os.getenv('OPENALGO_APIKEY')
HOST = os.getenv('OPENALGO_HOST', 'http://127.0.0.1:5000')
SYMBOL = 'SBIN'
EXCHANGE = 'NSE'
QUANTITY = 1

# Initialize client
client = api(api_key=API_KEY, host=HOST)

def calculate_ema(prices, period):
    """Calculate EMA for given prices"""
    multiplier = 2 / (period + 1)
    ema = [prices[0]]
    for price in prices[1:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema

def main():
    print(f"Starting strategy for {SYMBOL}")

    while True:
        try:
            # Fetch historical data
            df = client.history(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                interval='5m',
                start_date='2024-01-01',
                end_date='2024-12-31'
            )

            # Calculate EMAs
            closes = df['close'].tolist()
            ema_fast = calculate_ema(closes, 5)[-1]
            ema_slow = calculate_ema(closes, 10)[-1]

            # Generate signal
            if ema_fast > ema_slow:
                print(f"BUY signal: EMA5={ema_fast:.2f} > EMA10={ema_slow:.2f}")
                client.placesmartorder(
                    strategy='ema_crossover',
                    symbol=SYMBOL,
                    action='BUY',
                    exchange=EXCHANGE,
                    price_type='MARKET',
                    product='MIS',
                    quantity=QUANTITY,
                    position_size=QUANTITY
                )
            elif ema_fast < ema_slow:
                print(f"SELL signal: EMA5={ema_fast:.2f} < EMA10={ema_slow:.2f}")
                client.placesmartorder(
                    strategy='ema_crossover',
                    symbol=SYMBOL,
                    action='SELL',
                    exchange=EXCHANGE,
                    price_type='MARKET',
                    product='MIS',
                    quantity=QUANTITY,
                    position_size=QUANTITY
                )

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(15)  # Check every 15 seconds

if __name__ == '__main__':
    main()
```

## Schedule Configuration

```json
{
  "strategy_id": "ema_crossover_20260115",
  "schedule": {
    "start_time": "09:20",
    "stop_time": "15:15",
    "days": ["mon", "tue", "wed", "thu", "fri"],
    "timezone": "Asia/Kolkata"
  }
}
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/python/new` | POST | Upload strategy file |
| `/python/start/<id>` | POST | Start execution |
| `/python/stop/<id>` | POST | Stop execution |
| `/python/delete/<id>` | POST | Delete strategy |
| `/python/schedule/<id>` | POST | Configure schedule |
| `/python/logs/<id>` | GET | View logs |
| `/python/api/strategies` | POST | List all strategies |

## Database Schema

```
strategy_configs.json (file-based)
├── strategy_id → {
│     name: str,
│     file_path: str,
│     user_id: str,
│     is_running: bool,
│     is_scheduled: bool,
│     schedule_start: 'HH:MM',
│     schedule_stop: 'HH:MM',
│     schedule_days: ['mon',...],
│     last_started: datetime,
│     last_stopped: datetime,
│     pid: int,
│     manually_stopped: bool
│   }
```

## Directory Structure

```
openalgo/
├── strategies/
│   ├── scripts/           # User-uploaded strategies
│   ├── examples/          # Template strategies
│   └── strategy_configs.json
├── log/
│   └── strategies/        # Strategy output logs
└── blueprints/
    └── python_strategy.py # Strategy hosting (~2680 lines)
```

## Related Documentation

| Document | Description |
|----------|-------------|
| [Process Management](./python-strategies-process-management.md) | Subprocess handling and lifecycle |
| [Scheduling Guide](./python-strategies-scheduling.md) | Market-aware scheduling with APScheduler |
| [API Reference](./python-strategies-api-reference.md) | Complete API documentation |

## Key Files Reference

| File | Purpose | Lines |
|------|---------|-------|
| `blueprints/python_strategy.py` | Main implementation with routes, process management, scheduling | ~2680 |
| `strategies/scripts/` | User-uploaded strategy Python files | - |
| `strategies/examples/` | Template strategies for users | - |
| `strategies/strategy_configs.json` | Strategy configuration storage | - |
| `log/strategies/` | Strategy execution log files | - |

> **Note:** React frontend for strategy management is served via the Flask backend's Jinja2 templates. The strategy list, upload, and log viewing are available at `/python/*` routes.

## Success Metrics

| Metric | Target |
|--------|--------|
| Strategy uptime | > 99% during market hours |
| Schedule accuracy | ±1 minute |
| Log delivery latency | < 1 second |
| Process isolation | 0 cross-contamination |
