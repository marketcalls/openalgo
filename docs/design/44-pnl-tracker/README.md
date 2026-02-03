# 44 - PnL Tracker

## Overview

The PnL (Profit & Loss) Tracker provides real-time intraday P&L monitoring by combining tradebook data with historical price data. It calculates mark-to-market (MTM) P&L for all positions throughout the trading day and displays it via interactive charts.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          PnL Tracker Architecture                            │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         Data Sources                                         │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  Tradebook      │  │  Position Book  │  │  History API    │             │
│  │  (Broker API)   │  │  (Broker API)   │  │  (1-minute bars)│             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                │                                             │
│                                ▼                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       PnL Calculation (blueprints/pnltracker.py)            │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Position Window Tracking                          │   │
│  │                                                                      │   │
│  │  1. Parse trades from tradebook                                     │   │
│  │  2. Group by symbol/exchange                                        │   │
│  │  3. Create position windows (start_time, end_time, qty, price)      │   │
│  │  4. Apply rate limiting (2 calls/sec for history API)               │   │
│  │  5. Calculate MTM using historical close prices                     │   │
│  │  6. Aggregate all symbols into portfolio P&L                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    P&L Calculation Formula                           │   │
│  │                                                                      │   │
│  │  For LONG positions:                                                 │   │
│  │    MTM P&L = (Current Price - Entry Price) × Quantity               │   │
│  │                                                                      │   │
│  │  For SHORT positions:                                                │   │
│  │    MTM P&L = (Entry Price - Current Price) × Quantity               │   │
│  │                                                                      │   │
│  │  Realized P&L = (Exit Price - Entry Price) × Quantity  [Long]       │   │
│  │                = (Entry Price - Exit Price) × Quantity  [Short]     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Frontend Display                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Metrics Cards                                                       │   │
│  │                                                                      │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐              │   │
│  │  │ Current  │ │   Max    │ │   Min    │ │   Max    │              │   │
│  │  │   MTM    │ │   MTM    │ │   MTM    │ │ Drawdown │              │   │
│  │  │ +₹3,750  │ │ +₹4,200  │ │ +₹1,000  │ │  -₹800   │              │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  P&L Chart (LightWeight Charts)                                     │   │
│  │                                                                      │   │
│  │       ₹                                                              │   │
│  │    4000│        ╭──────╮                                            │   │
│  │    3000│    ╭───╯      ╰──╮                                         │   │
│  │    2000│╭───╯              ╰──────                                  │   │
│  │    1000│                                                            │   │
│  │       0├────────────────────────────► Time                          │   │
│  │        9:15  10:00  11:00  12:00  1:00                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Implementation Details

### Position Window Tracking

The PnL tracker creates "position windows" to track when positions were opened and closed:

```python
# Data structure for each position window
position_window = {
    "start_time": datetime,    # When position was opened
    "end_time": datetime,      # When position was closed (None if still open)
    "qty": float,              # Position quantity
    "price": float,            # Entry price
    "action": str,             # "BUY" or "SELL"
    "exit_price": float        # Exit price (None if still open)
}
```

### Trade Timestamp Parsing

The system handles multiple timestamp formats from different brokers:

```python
# Supported formats in parse_trade_timestamp():
formats = [
    "%d-%b-%Y %H:%M:%S",    # AngelOne: "17-Dec-2025 10:54:03"
    "%H:%M:%S %d-%m-%Y",    # Flattrade: "09:41:01 17-12-2025"
    "%d-%m-%Y %H:%M:%S",    # "17-12-2025 09:41:01"
    "%Y-%m-%d %H:%M:%S",    # ISO-like: "2025-12-17 10:30:00"
    "%Y-%m-%dT%H:%M:%S",    # ISO: "2025-12-17T10:30:00"
]
```

### Rate Limiting

Historical data API calls are rate-limited to avoid broker rate limits:

```python
class RateLimiter:
    """Thread-safe rate limiter for API calls"""

    def __init__(self, calls_per_second=2):
        self.calls_per_second = calls_per_second
        self.min_interval = 1.0 / calls_per_second
        self.last_call_time = 0
        self.lock = threading.Lock()

    def wait(self):
        """Wait if necessary to respect rate limit"""
        with self.lock:
            current_time = time_module.time()
            elapsed = current_time - self.last_call_time
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                time_module.sleep(sleep_time)
            self.last_call_time = time_module.time()

# Global instance - 2 calls per second (conservative)
history_rate_limiter = RateLimiter(calls_per_second=2)
```

## API Endpoint

### Get P&L Data

```
POST /pnltracker/api/pnl
Content-Type: application/json
Cookie: session=...
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "current_mtm": 3750.00,
        "max_mtm": 4200.00,
        "max_mtm_time": "11:30",
        "min_mtm": 1000.00,
        "min_mtm_time": "09:45",
        "max_drawdown": -800.00,
        "pnl_series": [
            {"time": 1706165700000, "value": 1000.00},
            {"time": 1706165760000, "value": 1500.00},
            {"time": 1706165820000, "value": 2200.00}
        ],
        "drawdown_series": [
            {"time": 1706165700000, "value": 0.00},
            {"time": 1706165760000, "value": -200.00},
            {"time": 1706165820000, "value": 0.00}
        ]
    }
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `current_mtm` | number | Current mark-to-market P&L |
| `max_mtm` | number | Maximum P&L reached during the day |
| `max_mtm_time` | string | Time when max P&L was reached (HH:MM) |
| `min_mtm` | number | Minimum P&L during the day |
| `min_mtm_time` | string | Time when min P&L was reached (HH:MM) |
| `max_drawdown` | number | Largest drawdown from peak (negative) |
| `pnl_series` | array | Time series data for P&L chart |
| `drawdown_series` | array | Time series data for drawdown chart |

## Calculation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    P&L Calculation Flow                          │
└─────────────────────────────────────────────────────────────────┘

Request arrives at /pnltracker/api/pnl
              │
              ▼
┌─────────────────────────┐
│ Get broker from session │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐     ┌─────────────────────┐
│ Get tradebook via       │────▶│ services/tradebook  │
│ get_tradebook(api_key)  │     │ _service.py         │
└───────────┬─────────────┘     └─────────────────────┘
            │
            ▼
┌─────────────────────────┐     ┌─────────────────────┐
│ Get positions via       │────▶│ services/positionbook│
│ get_positionbook()      │     │ _service.py         │
└───────────┬─────────────┘     └─────────────────────┘
            │
            ▼
┌─────────────────────────┐
│ Group trades by symbol  │
│ Create position windows │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ For each symbol:        │
│ 1. Rate limit wait      │
│ 2. Get 1m history       │
│ 3. Calculate MTM        │
│ 4. Track realized P&L   │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Aggregate portfolio     │
│ Calculate drawdown      │
│ Return JSON response    │
└─────────────────────────┘
```

## Data Dependencies

The PnL tracker relies on these services (no dedicated database):

| Service | Purpose |
|---------|---------|
| `services/tradebook_service.py` | Get today's executed trades |
| `services/positionbook_service.py` | Get current positions |
| `services/history_service.py` | Get 1-minute historical bars |
| `database/auth_db.py` | Get user auth token and API key |

## Frontend Components

### React Page

**Location:** `frontend/src/pages/PnLTracker.tsx`

The React frontend:
- Polls `/pnltracker/api/pnl` periodically
- Renders metrics cards (current MTM, max, min, drawdown)
- Uses LightWeight Charts for interactive P&L visualization
- Shows separate drawdown chart below main chart

### Legacy Jinja Template

**Location:** `templates/pnltracker.html`

Available at `/pnltracker/legacy` for backwards compatibility.

## Edge Cases Handled

### Sub-Minute Trades

When a position is opened and closed within the same minute (no historical data points):

```python
# Calculate realized PnL even without historical data
if is_closed_position:
    if window["action"] == "BUY":
        realized = (window["exit_price"] - window["price"]) * window["qty"]
    else:  # SELL
        realized = (window["price"] - window["exit_price"]) * window["qty"]
```

### Pre-Trade Period

Zero P&L data is added from market open (9:15 AM IST) to first trade time for complete visualization.

### Timezone Handling

All timestamps are converted to IST (Asia/Kolkata) timezone:

```python
ist = pytz.timezone("Asia/Kolkata")
if df["datetime"].dt.tz is None:
    df["datetime"] = df["datetime"].dt.tz_localize("UTC").dt.tz_convert(ist)
```

## Drawdown Calculation

```python
# Drawdown = Current P&L - Peak P&L (running maximum)
portfolio_pnl["Peak"] = portfolio_pnl["Total_PnL"].cummax()
portfolio_pnl["Drawdown"] = portfolio_pnl["Total_PnL"] - portfolio_pnl["Peak"]

# Max drawdown is the minimum value (most negative)
max_drawdown = portfolio_pnl["Drawdown"].min()
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/pnltracker.py` | Blueprint with P&L calculation logic |
| `services/tradebook_service.py` | Fetches tradebook from broker |
| `services/positionbook_service.py` | Fetches current positions |
| `services/history_service.py` | Fetches historical price data |
| `frontend/src/pages/PnLTracker.tsx` | React UI component |
| `templates/pnltracker.html` | Legacy Jinja template |
