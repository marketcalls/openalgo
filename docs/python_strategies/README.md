# Python Strategy Management System

## Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Usage Guide](#usage-guide)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

## Overview

The Python Strategy Management System is a comprehensive solution for hosting, executing, and managing Python-based trading strategies within OpenAlgo. It provides a web-based interface for strategy lifecycle management with complete process isolation and cross-platform support.

### Key Capabilities
- 🚀 **Process Isolation**: Each strategy runs in a separate process
- ⏰ **Automated Scheduling**: Schedule strategies to run at specific times (IST)
- 📝 **Built-in Code Editor**: Edit strategies with syntax highlighting and line numbers
- 📊 **Real-time Logging**: Monitor strategy execution with live logs
- 💾 **Export/Import**: Download and backup strategies
- 🔒 **Security**: CSRF protection, encrypted environment variables, and process sandboxing
- 🖥️ **Cross-Platform**: Works on Windows, Linux, and macOS
- 🔄 **State Management**: Persistent state across app restarts
- 📈 **Master Contract Dependency**: Automatic strategy start after master contracts download
- 🛡️ **Safety Restrictions**: Prevents modifications while strategies are running

## Features

### 1. Strategy Management
- Upload Python trading strategies
- Start/Stop strategies with one click
- Edit strategies with built-in code editor
- Delete strategies (when stopped)
- Export strategies for backup

### 2. Scheduling System
- Schedule strategies to run automatically
- Set start and stop times in IST
- Select specific days of the week
- Manual override always available

### 3. Process Isolation
- Each strategy runs in separate process
- Strategies cannot interfere with main application
- Clean process termination
- Resource isolation

### 4. Code Editor
- Syntax highlighting for Python
- Line numbers
- Tab/Shift+Tab for indentation
- Dark/Light theme toggle
- Export current content
- Auto-save detection

### 5. Logging System
- Real-time log capture
- IST timestamps
- Log file rotation
- Web-based log viewer

### 6. Environment Variables
- Regular variables for configuration
- Secure encrypted storage for sensitive data (API keys, passwords)
- Per-strategy configuration
- Automatic injection into strategy processes
- Read-only access while strategies are running

### 7. State Management
- Persistent state across application restarts
- Automatic strategy restoration after login
- Error state handling with recovery options
- Master contract dependency checking

### 8. Master Contract Integration
- Strategies wait for master contracts to be downloaded
- Automatic start once contracts are ready
- Visual status indicators (Ready/Waiting/Error)
- Manual check and start option

## Installation

### Prerequisites
```bash
# Required Python packages
pip install flask
pip install flask-wtf  # For CSRF protection
pip install apscheduler>=3.10.0
pip install psutil>=5.9.0
pip install pytz
pip install cryptography  # For secure environment variables
```

### Directory Structure
The system will automatically create these directories:
```
openalgo/
├── strategies/
│   ├── scripts/           # Strategy Python files
│   ├── strategy_configs.json  # Strategy configurations
│   ├── strategy_env.json     # Regular environment variables
│   ├── .secure_env           # Encrypted sensitive variables
│   └── .gitignore            # Prevents committing sensitive data
├── log/
│   └── strategies/        # Strategy log files
├── keys/
│   ├── .encryption_key    # Encryption key for secure variables
│   └── .gitignore         # Prevents committing keys
└── docs/
    └── python_strategies/  # Documentation
```

## Quick Start

### 1. Access the System
Navigate to: `http://127.0.0.1:5000/python`

Or access from Profile menu → Python Strategies

### 2. Upload Your First Strategy
```python
# example_strategy.py
from openalgo import api
import time

# Initialize API
client = api(api_key='YOUR_API_KEY', host='http://127.0.0.1:5000')

def main():
    while True:
        # Your trading logic here
        print(f"Strategy running at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        time.sleep(60)

if __name__ == "__main__":
    main()
```

### 3. Upload via Web Interface
1. Click "Upload New Strategy"
2. Select your Python file
3. Enter a strategy name
4. Click "Upload"

### 4. Start the Strategy
- Click "Start" button on strategy card
- Monitor status in real-time
- View logs by clicking "Logs"

### 5. Schedule the Strategy
1. Click "Schedule" button
2. Set start time (e.g., 09:15)
3. Set stop time (e.g., 15:30)
4. Select days (Mon-Fri for weekdays)
5. Save schedule

## Architecture

### System Components

```
┌─────────────────────────────────────────┐
│           Web Interface (Flask)          │
├─────────────────────────────────────────┤
│          Blueprint: /python              │
├─────────────────────────────────────────┤
│         Process Manager (subprocess)     │
├─────────────────────────────────────────┤
│         Scheduler (APScheduler)          │
├─────────────────────────────────────────┤
│      Strategy Processes (Isolated)       │
└─────────────────────────────────────────┘
```

### File Flow
1. **Upload**: Web → strategies/scripts/
2. **Execute**: subprocess.Popen(strategy.py)
3. **Log**: stdout/stderr → log/strategies/
4. **Monitor**: Web interface polls status

## Usage Guide

### Managing Strategies

#### Upload a Strategy
```http
POST /python/upload
Content-Type: multipart/form-data

file: strategy.py
name: "My Strategy"
```

#### Start a Strategy
```http
POST /python/start/<strategy_id>
```

#### Stop a Strategy
```http
POST /python/stop/<strategy_id>
```

#### Delete a Strategy
```http
POST /python/delete/<strategy_id>
```

#### Export a Strategy
```http
GET /python/export/<strategy_id>
```

### Environment Variables

The system supports both regular and secure environment variables for each strategy:

#### Regular Variables
- Configuration values like `DEBUG`, `LOG_LEVEL`, `SYMBOL`
- Stored in plain text in `strategies/strategy_env.json` (git-ignored)
- Suitable for non-sensitive configuration
- Persistent across logout/restart

#### Secure Variables
- Sensitive data like API keys, passwords, tokens
- Encrypted using Fernet encryption with unique installation key
- Stored in `strategies/.secure_env` (git-ignored)  
- Encryption key stored in `keys/.encryption_key` (isolated secure location)
- File permissions set to 600 (Unix systems)
- Only accessible to the running strategy process
- Persistent across logout/restart
- Read-only while strategies are running (safety feature)
- Values preserved when modal is closed/reopened (shows as bullets •••)

#### Setting Environment Variables
1. Click the "Environment Variables" button on any strategy card
2. Add regular variables for configuration
3. Add secure variables for sensitive data (API keys, etc.)
4. Save the variables

#### Using in Strategy Code
```python
import os

# Access environment variables
api_key = os.getenv('API_KEY')  # Secure variable
debug_mode = os.getenv('DEBUG', 'false')  # Regular variable
log_level = os.getenv('LOG_LEVEL', 'INFO')  # Regular variable

print(f"Debug mode: {debug_mode}")
print(f"Log level: {log_level}")
# API key is available but not logged for security
```

### Editing Strategies

1. **View Mode** (Running Strategy)
   - Read-only access
   - Syntax highlighting disabled
   - Export still available

2. **Edit Mode** (Stopped Strategy)
   - Full editing capabilities
   - Save changes with Ctrl+S
   - Reset to last saved version
   - Export current or saved version

### Scheduling

#### Schedule Format
- **Time**: 24-hour format in IST (e.g., 09:15, 15:30)
- **Days**: mon, tue, wed, thu, fri, sat, sun

#### Example Schedule
```json
{
  "schedule_start": "09:15",
  "schedule_stop": "15:30",
  "schedule_days": ["mon", "tue", "wed", "thu", "fri"]
}
```

## API Reference

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/python` | Dashboard |
| GET | `/python/new` | Upload form |
| POST | `/python/upload` | Upload strategy |
| POST | `/python/start/<id>` | Start strategy |
| POST | `/python/stop/<id>` | Stop strategy |
| POST | `/python/delete/<id>` | Delete strategy |
| GET | `/python/edit/<id>` | Edit/View strategy |
| POST | `/python/save/<id>` | Save changes |
| GET | `/python/export/<id>` | Export strategy |
| POST | `/python/schedule/<id>` | Set schedule |
| POST | `/python/unschedule/<id>` | Remove schedule |
| GET | `/python/logs/<id>` | View logs |
| GET | `/python/status` | System status |
| GET | `/python/env/<id>` | Get environment variables |
| POST | `/python/env/<id>` | Set environment variables |

### Response Format

```json
{
  "success": true,
  "message": "Operation successful",
  "data": {}
}
```

## Configuration

### Strategy Configuration File
Location: `strategies/strategy_configs.json`

```json
{
  "strategy_id": {
    "name": "Strategy Name",
    "file_path": "strategies/scripts/file.py",
    "is_running": false,
    "is_scheduled": false,
    "schedule_start": "09:15",
    "schedule_stop": "15:30",
    "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
    "last_started": "2024-01-01T09:15:00+05:30",
    "last_stopped": "2024-01-01T15:30:00+05:30",
    "pid": null
  }
}
```

### Environment Variables
Strategies inherit the environment from the main application:
- `PYTHONPATH`: Includes OpenAlgo directory
- `PATH`: System PATH
- Custom variables from `.env` file

## Security

### Process Isolation
- Each strategy runs in separate process
- No shared memory between strategies
- Process group isolation on Unix
- Job object isolation on Windows

### CSRF Protection
- All POST requests require CSRF token
- Token validated by Flask-WTF
- Automatic token refresh

### File Security
- `.gitignore` files prevent accidental commits of sensitive data
- Strategy files, configs, and environment variables are git-ignored
- Automatic backup before save
- UTF-8 encoding enforced

### Environment Variable Security
- **Regular variables**: Stored in `strategies/strategy_env.json` (git-ignored)
- **Secure variables**: Encrypted with Fernet in `strategies/.secure_env` (git-ignored)
- **Encryption key**: Unique per installation in `keys/.encryption_key` (isolated folder)
- **Keys folder**: Separate directory with `.gitignore` for all encryption keys
- **File permissions**: Restrictive permissions (600) on Unix systems
- **Persistence**: Survives logout/restart, cleared only when manually deleted
- **Safety restrictions**: Cannot modify while strategies are running
- **UI security**: Secure values shown as bullets (••••••••) in interface

### Best Practices
1. Never hardcode API keys in strategies
2. Use environment variables for sensitive data
3. Implement proper error handling
4. Add logging for debugging
5. Test strategies locally first

## Troubleshooting

### Common Issues

#### Strategy Won't Start
- **Check**: Master contracts are downloaded (check Master Contract status)
- **Check**: File exists in strategies/scripts/
- **Check**: Python syntax is valid
- **Check**: Required imports are available
- **Solution**: View logs for error details
- **Solution**: Click "Check & Start" button if waiting for master contracts

#### Editor Not Loading
- **Check**: Browser JavaScript enabled
- **Check**: Clear browser cache
- **Solution**: Refresh page (F5)

#### Save Returns 400 Error
- **Check**: Strategy is stopped
- **Check**: CSRF token present
- **Solution**: Refresh page and retry

#### Schedule Not Working
- **Check**: Valid time format (HH:MM)
- **Check**: At least one day selected
- **Check**: Strategy file exists
- **Solution**: Check scheduler logs

### Debug Mode
Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Log Locations
- Strategy logs: `log/strategies/`
- Application logs: Check Flask console
- Scheduler logs: In application logs

## Platform-Specific Notes

### Windows
- Uses `CREATE_NEW_PROCESS_GROUP`
- Process termination via `taskkill`
- Paths use backslashes

### Linux/macOS
- Uses `setsid` for process groups
- SIGTERM/SIGKILL for termination
- Standard Unix paths

### Docker
- Mount strategies volume: `-v ./strategies:/app/strategies`
- Mount logs volume: `-v ./log:/app/log`
- Ensure proper permissions

## Examples

### EMA Crossover Strategy with Environment Variables
```python
from openalgo import api
import pandas as pd
import time
import os
import logging

# Configure logging using environment variables
log_level = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

# Initialize API using secure environment variables
api_key = os.getenv('API_KEY')  # Secure variable
host = os.getenv('API_HOST', 'http://127.0.0.1:5000')  # Regular variable

if not api_key:
    logger.error("API_KEY environment variable not set")
    exit(1)

client = api(api_key=api_key, host=host)

def calculate_ema(data, period):
    return data.ewm(span=period, adjust=False).mean()

def main():
    # Get configuration from environment variables
    symbol = os.getenv('SYMBOL', 'RELIANCE')
    exchange = os.getenv('EXCHANGE', 'NSE')
    interval = os.getenv('INTERVAL', '5m')
    short_period = int(os.getenv('SHORT_EMA', '9'))
    long_period = int(os.getenv('LONG_EMA', '21'))
    sleep_duration = int(os.getenv('SLEEP_SECONDS', '300'))
    
    logger.info(f"Starting EMA Crossover strategy for {symbol} on {exchange}")
    logger.info(f"Short EMA: {short_period}, Long EMA: {long_period}")
    
    while True:
        try:
            # Fetch data
            df = client.history(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                days=1
            )
            
            # Calculate EMAs
            df['ema_short'] = calculate_ema(df['close'], short_period)
            df['ema_long'] = calculate_ema(df['close'], long_period)
            
            # Generate signals
            if df['ema_short'].iloc[-1] > df['ema_long'].iloc[-1]:
                logger.info(f"BUY Signal for {symbol} at {df['close'].iloc[-1]}")
                # Place buy order
            elif df['ema_short'].iloc[-1] < df['ema_long'].iloc[-1]:
                logger.info(f"SELL Signal for {symbol} at {df['close'].iloc[-1]}")
                # Place sell order
            
            time.sleep(sleep_duration)
            
        except Exception as e:
            logger.error(f"Error in strategy execution: {e}")
            time.sleep(60)  # Wait before retrying

if __name__ == "__main__":
    main()
```

**Environment Variables for this strategy:**
- **Secure:** `API_KEY` (your OpenAlgo API key)
- **Regular:** `SYMBOL` (default: RELIANCE), `EXCHANGE` (default: NSE), `INTERVAL` (default: 5m), `SHORT_EMA` (default: 9), `LONG_EMA` (default: 21), `LOG_LEVEL` (default: INFO), `SLEEP_SECONDS` (default: 300)

## Contributing

### Development Setup
```bash
# Clone repository
git clone https://github.com/openalgo/openalgo.git

# Install dependencies
pip install -r requirements.txt

# Run tests
python -m pytest tests/
```

### Code Style
- Follow PEP 8
- Add docstrings to functions
- Use type hints where appropriate
- Add unit tests for new features

## Support

### Documentation
- [Complete Implementation Guide](complete-implementation-guide.md)
- [Editor Guide](editor-guide.md)
- [API Documentation](api-reference.md)

### Getting Help
- Check logs in `log/strategies/`
- Review browser console for errors
- Open issue on GitHub
- Contact support team

## License

This project is part of OpenAlgo and follows the same license terms.

---

*Last Updated: September 2024*
*Version: 1.1.1*