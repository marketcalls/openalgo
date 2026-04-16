# Python Strategy Management System

## Overview
A complete web-based strategy hosting and scheduling system for OpenAlgo, accessible at `/python`.

## Features
- **Upload & Manage**: Upload Python strategy scripts through web interface
- **Start/Stop**: Control strategy execution with one click
- **Schedule**: Set automatic start/stop times with day selection
- **Exchange-aware calendar**: Each strategy is tagged with an exchange (NSE / BSE / NFO / BFO / MCX / BCD / CDS / CRYPTO) and the host gates start/stop using that exchange's holiday calendar — an MCX strategy keeps running on an NSE/BSE holiday during the MCX session, a CRYPTO strategy ignores all holidays, and SPECIAL_SESSION rows (Muhurat, DR-drill) override weekend rejects
- **Process Isolation**: Each strategy runs in its own process
- **Real-time Monitoring**: View logs and strategy status
- **Parameter Configuration**: Pass custom parameters to strategies

## Installation

1. Install required packages:
```bash
pip install apscheduler psutil
```

2. The system is already integrated into OpenAlgo. Access it at:
```
http://localhost:5000/python
```

## Usage

### 1. Upload a Strategy
- Click "Add Strategy" button
- Provide a name for your strategy
- Select your Python script file
- **Pick the exchange** the strategy trades on (NSE / BSE / NFO / BFO / MCX / BCD / CDS / CRYPTO). This drives which calendar the host uses to gate scheduled start/stop. Pick CRYPTO for 24/7 strategies — the host will skip all holiday checks and pre-fill the schedule to all 7 days
- Add any parameters (will be available as environment variables)
- Click "Upload Strategy"

### 2. Start/Stop Strategy
- Click "Start" to run the strategy immediately
- Click "Stop" to terminate a running strategy
- Process ID (PID) is shown for running strategies

### 3. Schedule Strategy
- Click "Schedule" button on any strategy
- Change exchange if needed (drives the holiday calendar)
- Set start time (required)
- Set stop time (optional - leave empty to run indefinitely)
- Select days to run (defaults to weekdays for equity exchanges, all 7 days for CRYPTO)
- Click "Schedule" to save

The effective trading window is the **intersection** of:
1. Your `start..stop` time, and
2. The exchange's session for that specific date (from the market calendar DB).

So a 09:15-23:55 schedule on an MCX strategy on 14-Apr-2026 will only fire 17:00-23:55 (the partial holiday window the calendar publishes for that date), not 09:15. This is by design — you don't have to redo the schedule for every partial holiday.

### 4. View Logs
- Click "Logs" to view strategy output
- Logs are stored in `logs/strategies/` directory
- Each run creates a new timestamped log file

## Strategy Template

Your strategy should follow this structure:

```python
#!/usr/bin/env python
import os
import time
from datetime import datetime

# Get parameters from environment.
# EXCHANGE prefers OPENALGO_STRATEGY_EXCHANGE (set by /python from your
# strategy's exchange config) so the script trades on the same exchange
# the host is gating its calendar against. Falls back to EXCHANGE env
# var, then NSE — so the same script works standalone too.
SYMBOL   = os.getenv('SYMBOL', 'RELIANCE')
EXCHANGE = os.getenv(
    'OPENALGO_STRATEGY_EXCHANGE',
    os.getenv('EXCHANGE', 'NSE'),
)
API_KEY  = os.getenv('OPENALGO_API_KEY', '')
API_HOST = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')
WS_URL   = os.getenv('WEBSOCKET_URL', 'ws://127.0.0.1:8765')

def main():
    print(f"Strategy started at {datetime.now()}")
    print(f"Trading {SYMBOL} on {EXCHANGE}")
    
    while True:
        try:
            # Your strategy logic here
            # 1. Fetch market data
            # 2. Calculate indicators
            # 3. Generate signals
            # 4. Place orders via OpenAlgo API
            
            print(f"[{datetime.now()}] Running strategy...")
            time.sleep(60)  # Check every minute
            
        except KeyboardInterrupt:
            print("Strategy stopped")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
```

> **Reading `OPENALGO_STRATEGY_EXCHANGE` is optional but strongly recommended.** If your script hardcodes `exchange = "NSE"`, the host will still gate it correctly per its config (e.g. host runs your script during MCX evening session because `exchange=MCX`), but your `client.placeorder(exchange="NSE", ...)` calls will still send NSE orders — and the broker will reject them. Wiring the env var keeps host calendar and script orders aligned.

## Environment Variables

### Injected by the platform

These are set directly on each strategy subprocess:

- `STRATEGY_ID` — unique identifier for the strategy
- `STRATEGY_NAME` — name of the strategy
- `OPENALGO_STRATEGY_EXCHANGE` — the exchange picked at upload/edit time (`NSE` / `BSE` / `NFO` / `BFO` / `MCX` / `BCD` / `CDS` / `CRYPTO`). Read this in your script so its trading calls match the calendar the host is gating against
- `OPENALGO_API_KEY` — decrypted API key for this user
- `OPENALGO_HOST` — OpenAlgo host URL (defaults to `http://127.0.0.1:5000`; kept as a documented alias of `HOST_SERVER`)

### Inherited from `.env`

Strategies also inherit every variable defined in OpenAlgo's `.env`, so the following can be read directly:

- `HOST_SERVER` — e.g. `http://127.0.0.1:5000` (preferred over `OPENALGO_HOST`)
- `WEBSOCKET_URL` — e.g. `ws://127.0.0.1:8765`
- `WEBSOCKET_HOST` / `WEBSOCKET_PORT` — raw components if you prefer to build the URL yourself
- Any other key in `.env`

Prefer `HOST_SERVER` and `WEBSOCKET_URL` in new strategies — they match the variable names used by OpenAlgo's own configuration, so the same `.env` drives both the server and your strategies.

### Per-strategy parameters

Plus any custom parameters you define in the strategy upload form — these become additional environment variables.

## Directory Structure

```
strategies/
├── scripts/          # Uploaded strategy files
├── examples/         # Example strategies
├── configs.json      # Strategy configurations
└── requirements.txt  # Python dependencies

logs/
└── strategies/       # Strategy log files
```

## API Integration

Example of integrating with OpenAlgo API in your strategy:

```python
import os
import requests

class OpenAlgoAPI:
    def __init__(self, host=None, api_key=None):
        self.host = host or os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')
        self.api_key = api_key or os.getenv('OPENALGO_API_KEY', '')
        self.headers = {'X-API-KEY': self.api_key}

    def place_order(self, symbol, exchange, action, quantity):
        data = {
            'symbol': symbol,
            'exchange': exchange,
            'action': action,
            'quantity': quantity,
            'order_type': 'MARKET',
            'product': 'MIS'
        }
        response = requests.post(
            f"{self.host}/api/v1/placeorder",
            headers=self.headers,
            json=data
        )
        return response.json()
```

## Scheduling

Strategies can be scheduled to run automatically:

- **Exchange**: Drives the holiday calendar. Defaults to NSE for legacy strategies (auto-backfilled at startup)
- **Start Time**: When to start the strategy (24-hour format, IST)
- **Stop Time**: When to stop the strategy (optional, IST)
- **Days**: Which days to run (Mon-Sun)

Example: NSE EMA strategy → Start 09:15, stop 15:30, Monday-Friday.
Example: MCX evening strategy → exchange=MCX, start 17:00, stop 23:55, Monday-Friday.
Example: CRYPTO arb → exchange=CRYPTO, start 00:00, stop 23:59, all 7 days.

### How exchange-aware gating works

Three things run on the host:

1. **Cron job** — fires `start_<sid>` at your `start_time` on each day in `schedule_days`.
2. **Daily check** at 00:01 IST — for each scheduled strategy, looks up `get_market_status(config["exchange"])`. If the exchange has no session today (closed weekend / full holiday), the strategy is stopped and marked `paused_reason=holiday|weekend`.
3. **Per-minute enforcer** — same per-strategy check. When the exchange reopens (or a special session starts), previously-paused strategies are auto-resumed (unless `manually_stopped`).

The "session today" lookup uses the same calendar DB that powers `/api/v1/market/holidays` — see admin → Holidays to add SPECIAL_SESSION rows for events like Muhurat trading or NSE DR-drill weekends.

### Worked example: 14-Apr-2026 (Ambedkar Jayanti)

| Exchange | Calendar says | Strategy behavior |
|---|---|---|
| NSE / BSE / NFO / BFO / CDS / BCD | Closed all day | All scheduled strategies stopped at 00:01 IST |
| MCX | Open 17:00-23:55 IST (partial holiday) | MCX strategies stay armed; auto-start at 17:00, run within user's `start..stop ∩ 17:00-23:55` |
| CRYPTO | 24/7 | Unaffected |

### Worked example: 8-Nov-2026 (Sunday Diwali Muhurat)

| Exchange | Calendar says | Strategy behavior |
|---|---|---|
| NSE / BSE / NFO / BFO / CDS / BCD | SPECIAL_SESSION 18:00-19:15 | Strategy runs only inside that window, even though it's Sunday |
| MCX | SPECIAL_SESSION 18:00-00:15 next day | Same; user's `schedule_stop` should be 23:59 to honor most of the window |
| CRYPTO | 24/7 | Unaffected |

## Safety Features

- Process isolation prevents strategy crashes from affecting the system
- Automatic cleanup of dead processes
- Graceful shutdown with SIGTERM signal
- Log rotation with timestamped files
- Configuration persistence across restarts

## Troubleshooting

1. **Strategy won't start**: Check logs for errors, ensure Python script is valid
2. **Schedule not working**: Verify APScheduler is running, check system time
3. **Can't stop strategy**: Process may be stuck, use system task manager if needed
4. **Parameters not working**: Ensure parameter names are valid environment variable names
5. **Strategy didn't run on a partial holiday (e.g., MCX evening on NSE holiday)**:
   - Open the strategy → Schedule → confirm `Exchange` is set to the right market (legacy strategies default to `NSE` after the upgrade and need a one-time edit if they trade MCX/CRYPTO/etc.)
   - Confirm the date has a row in admin → Holidays with the partial-open window for your exchange
   - Confirm your `schedule_start..schedule_stop` overlaps the calendar window — they intersect, so a 09:15-15:30 schedule will NOT fire during a 17:00-23:55 partial session
6. **Strategy ran on a Sunday/Saturday (special session)**: that's by design — the calendar's SPECIAL_SESSION row overrides the weekend reject. To opt out, remove the day from `schedule_days`
7. **Strategy paused with `paused_reason=holiday`** but you think today is open: check `get_market_status(exchange)` — the exchange's session may differ from another exchange's. Each strategy is gated by its own exchange
8. **Orders rejected with "market closed" while host says strategy is running**: your script's hardcoded `exchange="NSE"` doesn't match the host's `exchange="MCX"`. Read `OPENALGO_STRATEGY_EXCHANGE` in your script (see Strategy Template)

## Migration notes (existing deployments)

When upgrading to the exchange-aware /python:

- **No data migration required.** `load_configs()` writes `"exchange": "NSE"` into any legacy entry missing the field, on the first read after restart.
- **No strategy is force-restarted or force-stopped by the upgrade itself.** Running PIDs are reaped and re-evaluated normally.
- Strategies that should trade something other than NSE need a one-time UI edit (Schedule → pick exchange → Save). Otherwise they'll behave exactly as before, gated on NSE's calendar.
- `manually_stopped` strategies stay manually stopped — the upgrade does not auto-resume them.
- Forward-compatible: rolling back to the previous code reads the same JSON and ignores the new `exchange` field.

## Example Strategy

See `examples/simple_ema_strategy.py` for a complete working example that:
- Implements EMA crossover logic
- Integrates with OpenAlgo API
- Handles errors gracefully
- Uses environment parameters