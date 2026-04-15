# Python Strategy Management System

## Overview
A complete web-based strategy hosting and scheduling system for OpenAlgo, accessible at `/python`.

## Features
- **Upload & Manage**: Upload Python strategy scripts through web interface
- **Start/Stop**: Control strategy execution with one click
- **Schedule**: Set automatic start/stop times with day selection
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
- Add any parameters (will be available as environment variables)
- Click "Upload Strategy"

### 2. Start/Stop Strategy
- Click "Start" to run the strategy immediately
- Click "Stop" to terminate a running strategy
- Process ID (PID) is shown for running strategies

### 3. Schedule Strategy
- Click "Schedule" button on any strategy
- Set start time (required)
- Set stop time (optional - leave empty to run indefinitely)
- Select days to run (defaults to weekdays)
- Click "Schedule" to save

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

# Get parameters from environment
SYMBOL   = os.getenv('SYMBOL', 'RELIANCE')
EXCHANGE = os.getenv('EXCHANGE', 'NSE')
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

## Environment Variables

### Injected by the platform

These are set directly on each strategy subprocess:

- `STRATEGY_ID` — unique identifier for the strategy
- `STRATEGY_NAME` — name of the strategy
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

- **Start Time**: When to start the strategy (24-hour format)
- **Stop Time**: When to stop the strategy (optional)
- **Days**: Which days to run (Mon-Sat)

Example: Start at 09:15, stop at 15:30, run Monday-Friday

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

## Example Strategy

See `examples/simple_ema_strategy.py` for a complete working example that:
- Implements EMA crossover logic
- Integrates with OpenAlgo API
- Handles errors gracefully
- Uses environment parameters