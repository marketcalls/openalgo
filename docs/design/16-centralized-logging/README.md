# 16 - Centralized Logging

## Overview

OpenAlgo implements centralized logging with configurable levels, file rotation, and structured output. All application logs are routed through a unified logging system stored in `logs.db` and optional file logs.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Centralized Logging Architecture                       │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          Application Components                              │
│                                                                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │  Flask     │  │  REST API  │  │  WebSocket │  │  Services  │            │
│  │  Routes    │  │  Endpoints │  │  Proxy     │  │            │            │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘            │
│        │               │               │               │                    │
│        └───────────────┴───────────────┴───────────────┘                    │
│                                    │                                         │
│                                    ▼                                         │
│                          ┌─────────────────┐                                │
│                          │  get_logger()   │                                │
│                          │  (utils/logging)│                                │
│                          └────────┬────────┘                                │
└───────────────────────────────────┼─────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
┌────────────────────────────┐    ┌────────────────────────────┐
│      Console Handler       │    │       File Handler         │
│                            │    │    (if LOG_TO_FILE=True)   │
│  - Colored output          │    │                            │
│  - Level-based formatting  │    │  - Rotating files          │
│  - Immediate display       │    │  - Configurable retention  │
└────────────────────────────┘    └────────────────────────────┘
                                              │
                                              ▼
                                  ┌────────────────────────────┐
                                  │       log/ directory       │
                                  │                            │
                                  │  - openalgo.log            │
                                  │  - openalgo.log.1          │
                                  │  - openalgo.log.2          │
                                  └────────────────────────────┘
```

## Configuration

### Environment Variables

```bash
# Enable/disable file logging
LOG_TO_FILE=True

# Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO

# Log directory
LOG_DIR=log

# Log format
LOG_FORMAT=[%(asctime)s] %(levelname)s in %(module)s: %(message)s

# Days to retain log files
LOG_RETENTION=14
```

## Usage

### Getting a Logger

```python
from utils.logging import get_logger

logger = get_logger(__name__)

# Log at different levels
logger.debug("Debug message")
logger.info("Info message")
logger.warning("Warning message")
logger.error("Error message")
logger.critical("Critical message")
```

### Log Levels

| Level | Value | Use Case |
|-------|-------|----------|
| DEBUG | 10 | Detailed debugging information |
| INFO | 20 | General operational messages |
| WARNING | 30 | Something unexpected happened |
| ERROR | 40 | Error occurred, operation failed |
| CRITICAL | 50 | System is unusable |

## Implementation

**Location:** `utils/logging.py`

```python
import logging
import os
from logging.handlers import RotatingFileHandler

def get_logger(name):
    """Get a configured logger instance"""
    logger = logging.getLogger(name)

    if not logger.handlers:
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(get_formatter())
        logger.addHandler(console_handler)

        # File handler (if enabled)
        if os.getenv('LOG_TO_FILE', 'False').lower() == 'true':
            file_handler = RotatingFileHandler(
                filename=os.path.join(os.getenv('LOG_DIR', 'log'), 'openalgo.log'),
                maxBytes=10*1024*1024,  # 10MB
                backupCount=int(os.getenv('LOG_RETENTION', '14'))
            )
            file_handler.setFormatter(get_formatter())
            logger.addHandler(file_handler)

        logger.setLevel(os.getenv('LOG_LEVEL', 'INFO'))

    return logger
```

## Log Categories

### Application Logs

| Category | Logger Name | Description |
|----------|-------------|-------------|
| Auth | `blueprints.auth` | Login/logout events |
| Orders | `restx_api.place_order` | Order placement |
| WebSocket | `websocket_proxy` | WS connections |
| Strategy | `blueprints.strategy` | Strategy execution |

### Example Log Output

```
[2024-01-15 09:30:15] INFO in auth: User admin logged in successfully
[2024-01-15 09:30:20] INFO in place_order: Order placed - SBIN BUY 100 MIS
[2024-01-15 09:30:21] DEBUG in broker_api: Broker response: {"orderid": "123456"}
[2024-01-15 09:31:00] WARNING in session: Session expiring in 5 minutes
[2024-01-15 15:30:00] INFO in squareoff: Auto square-off triggered for MIS positions
```

## Startup Banner

```python
from utils.logging import log_startup_banner

# Display startup banner with version and URLs
log_startup_banner(version, web_url, ws_url, ngrok_url)
```

Output:

```
╭─── OpenAlgo v1.3.0 ──────────────────────────────────────────╮
│                                                              │
│             Your Personal Algo Trading Platform              │
│                                                              │
│ Endpoints                                                    │
│ Web App    http://127.0.0.1:5000                            │
│ WebSocket  ws://127.0.0.1:8765                              │
│ Docs       https://docs.openalgo.in                         │
│                                                              │
│ Status     Ready                                             │
│                                                              │
╰──────────────────────────────────────────────────────────────╯
```

## File Rotation

```
log/
├── openalgo.log        # Current log file
├── openalgo.log.1      # Previous rotation
├── openalgo.log.2      # Older rotation
├── ...
└── openalgo.log.14     # Oldest (based on LOG_RETENTION)
```

### Rotation Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Max Size | 10 MB | Rotate when file exceeds |
| Backup Count | 14 | Number of rotated files to keep |
| Compression | None | Rotated files are not compressed |

## Viewing Logs

### File Logs

```bash
# View current log
cat log/openalgo.log

# Follow log in real-time
tail -f log/openalgo.log

# View last 100 lines
tail -100 log/openalgo.log

# Search for errors
grep ERROR log/openalgo.log
```

### UI Log Viewer

Access log viewer at `/logs`:
- Filter by level
- Search by keyword
- Date range selection
- Download logs

## Key Files Reference

| File | Purpose |
|------|---------|
| `utils/logging.py` | Logger configuration |
| `blueprints/logging.py` | Log viewer UI routes |
| `database/logs_db.py` | Log database models |
| `log/` | Log file directory |
