# OpenAlgo Sandbox Mode - Overview

## What is Sandbox Mode?

OpenAlgo is an **open-source application** that provides Sandbox Mode (also called **API Analyzer Mode**) - a sophisticated simulated trading environment that makes it **easier for traders** to test strategies, validate algorithms, and practice trading using real-time market data without risking actual capital.

## Important: Regulatory Compliance

> **⚖️ NOT Virtual/Paper Trading**: OpenAlgo Sandbox is fundamentally different from prohibited "virtual trading" platforms. It is an **open-source, self-hosted personal test environment** that:
> - **Open-source software** - transparent, community-driven development
> - Runs on **your own system** with **your own broker APIs**
> - Makes it **easier to test strategies** safely before live deployment
> - Has **no contests, prizes, or public competitions**
> - Serves as a **developer tool** for strategy validation, not a game
>
> For detailed regulatory clarification, see [Regulatory Compliance](12_regulatory_compliance.md).

## Key Features

### 1. Simulated Capital Management
- **Starting Balance**: ₹10,000,000 (1 Crore) in sandbox funds
- **Automatic Reset**: Every Sunday at 00:00 IST (configurable)
- **Manual Reset**: Available from sandbox settings page
- **Real-time Tracking**: Available balance, used margin, and P&L tracking

### 2. Realistic Order Execution
- **Real Market Data**: Uses live LTP from broker API
- **Bid/Ask Execution**: Market orders execute at realistic bid/ask prices
- **All Order Types**: MARKET, LIMIT, SL (Stop-Loss), SL-M (Stop-Loss Market)
- **No Slippage**: Pure execution based on market conditions
- **Rate Limiting**: 10 orders/second, 50 API calls/second compliance

### 3. Complete Product Support
- **MIS** (Intraday): Auto square-off at configured times
- **NRML** (Normal): Overnight positions allowed
- **CNC** (Cash & Carry): T+1 settlement to holdings

### 4. Margin System
- **Leverage-based**: Different leverage for equity, futures, and options
- **Dynamic Calculation**: Based on product type and instrument
- **Realistic Blocking**: Margin blocked at order placement
- **Auto Release**: Margin released on order cancellation or position closure

### 5. Auto Square-Off
- **Exchange-specific Timings**:
  - NSE/BSE: 15:15 IST
  - CDS/BCD: 16:45 IST
  - MCX: 23:30 IST
  - NCDEX: 17:00 IST
- **Automatic Order Cancellation**: Pending MIS orders cancelled at square-off time
- **Position Closure**: Open MIS positions automatically squared off
- **Post Square-off Blocking**: New MIS orders blocked until 09:00 AM next day

### 6. Accurate P&L Tracking
- **Real-time MTM**: Mark-to-market using live prices
- **Intraday Accumulation**: P&L accumulated across multiple trades on same symbol
- **Realized vs Unrealized**: Separate tracking of closed and open positions
- **Percentage Tracking**: P&L percentage for performance analysis

### 7. Complete Isolation
- **Separate Database**: Independent sandbox.db database
- **No Live Impact**: Zero interaction with live trading systems
- **Independent Configuration**: Own settings and parameters

## How It Works

### 1. Enable Sandbox Mode
Toggle the "Analyzer Mode" switch in OpenAlgo settings or use the API:

```python
from services.analyzer_service import toggle_analyzer_mode

analyzer_data = {"mode": True}
success, response, status_code = toggle_analyzer_mode(
    analyzer_data=analyzer_data,
    api_key='your_api_key'
)
```

### 2. Background Threads Start
When enabled, two daemon threads automatically start:

**Execution Engine Thread**:
- Monitors pending orders every 5 seconds (configurable)
- Fetches real-time quotes from broker API
- Executes orders when price conditions are met
- Updates positions and P&L

**Square-Off Scheduler Thread**:
- APScheduler-based cron jobs for each exchange
- Runs at configured square-off times in IST timezone
- Cancels pending MIS orders
- Closes open MIS positions
- Processes T+1 settlement at midnight (00:00 IST) - moves CNC positions to holdings

### 3. Place Orders
All standard OpenAlgo API endpoints work in sandbox mode:

```python
# Place a market order
order_data = {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 100,
    "price_type": "MARKET",
    "product": "MIS"
}
```

### 4. Order Lifecycle

```
PLACE ORDER
    ↓
VALIDATE (Symbol, Quantity, Margin)
    ↓
BLOCK MARGIN (Based on Leverage)
    ↓
CREATE ORDER (Status: open)
    ↓
┌───────────────────────────────────┐
│   EXECUTION ENGINE CHECKS          │
│   (Every 5 seconds)                │
│                                   │
│   MARKET: Execute immediately     │
│   LIMIT: Execute when LTP crosses │
│   SL/SL-M: Execute when triggered │
└───────────────────────────────────┘
    ↓
EXECUTE ORDER
    ↓
CREATE TRADE
    ↓
UPDATE POSITION (Netting logic)
    ↓
ADJUST MARGIN (Release if reducing position)
    ↓
UPDATE P&L (Real-time MTM)
```

### 5. Position Management

**Opening Position**:
- Margin blocked at order placement
- Position created when order executes
- Average price calculated
- MTM updates every 5 seconds

**Adding to Position**:
- Additional margin blocked
- Average price recalculated
- Position quantity updated

**Reducing Position**:
- Margin released proportionally
- Realized P&L calculated
- Accumulated P&L updated

**Closing Position**:
- Full margin released
- Realized P&L finalized
- Position marked as closed (qty = 0)
- Accumulated P&L preserved for day's trading

### 6. Holdings (CNC Only)

**T+1 Settlement**:
- CNC positions automatically move to holdings at midnight (00:00 IST)
- Settlement runs as background scheduler task
- **Catch-up Settlement**: Automatically settles missed positions on app startup
  - If app was stopped for days, old CNC positions (>1 day) settle automatically when app restarts
  - Ensures holdings are always correct even after extended downtime
- Holdings track long-term investments
- Separate MTM tracking
- Holdings can be sold using CNC SELL orders

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   OpenAlgo Application                   │
│                                                           │
│  ┌────────────┐     ┌──────────────┐                    │
│  │ Analyzer   │────>│   Sandbox    │                    │
│  │ Toggle     │     │   Service    │                    │
│  └────────────┘     └──────────────┘                    │
│                              │                            │
└──────────────────────────────┼────────────────────────────┘
                               │
        ┌──────────────────────┴──────────────────────┐
        │                                             │
┌───────▼────────┐                       ┌────────────▼────────┐
│  Execution     │                       │   Square-Off        │
│  Engine        │                       │   Scheduler         │
│  Thread        │                       │   Thread            │
│                │                       │                     │
│  - Check orders│                       │  - APScheduler      │
│  - Get quotes  │                       │  - Cron jobs (IST)  │
│  - Execute     │                       │  - Cancel orders    │
│  - Update MTM  │                       │  - Close positions  │
└───────┬────────┘                       └────────────┬────────┘
        │                                             │
        └──────────────────┬──────────────────────────┘
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
┌───────▼────────┐                 ┌─────────▼────────┐
│ Order Manager  │                 │  Position Manager│
│                │                 │                  │
│ - Validate     │                 │ - Update qty     │
│ - Block margin │                 │ - Calculate P&L  │
│ - Create order │                 │ - Close position │
└───────┬────────┘                 └─────────┬────────┘
        │                                     │
        └──────────────────┬──────────────────┘
                           │
                ┌──────────▼──────────┐
                │   Fund Manager      │
                │                     │
                │ - Calculate margin  │
                │ - Block/Release     │
                │ - Track P&L         │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │  Sandbox Database   │
                │   (sandbox.db)      │
                │                     │
                │ - Orders            │
                │ - Trades            │
                │ - Positions         │
                │ - Holdings          │
                │ - Funds             │
                │ - Config            │
                └─────────────────────┘
```

## Database Schema Summary

### sandbox_orders
Stores all sandbox orders (open, completed, cancelled, rejected)

### sandbox_trades
Stores executed trades (created when orders execute)

### sandbox_positions
Tracks open and closed positions with real-time P&L

### sandbox_holdings
Stores T+1 settled CNC positions

### sandbox_funds
User-wise capital, margin, and P&L tracking

### sandbox_config
System configuration (leverage, timings, intervals)

## Configuration

All sandbox settings are stored in the database and can be modified from the sandbox settings page:

- **Capital Settings**:
  - Starting capital (₹10,000,000 default)
  - Auto-reset day (dropdown: Monday-Sunday, default: Sunday)
  - Auto-reset time (time picker: HH:MM format, default: 00:00)
  - **Auto-reset runs via APScheduler** - works even if app was stopped during reset time
- **Leverage Settings**: Equity, futures, options leverage
- **Square-Off Times**: Exchange-specific closure times (time picker)
- **Intervals**: Order check, MTM update intervals
- **Rate Limits**: Order, API, smart order limits

## Use Cases

### 1. Strategy Testing
Test your trading algorithms with real market data before going live.

### 2. Algorithm Validation
Validate order logic, position management, and P&L calculations.

### 3. Learning Trading
Practice trading mechanics without financial risk.

### 4. Debugging Strategies
Identify and fix strategy issues in a safe environment.

### 5. Performance Analysis
Track strategy performance over time with realistic execution.

## System Requirements

- **Python**: 3.8 or higher
- **SQLAlchemy**: 1.4 or higher
- **APScheduler**: 3.10 or higher
- **Flask**: 2.0 or higher
- **Broker API Access**: For real-time quotes

## Next Steps

1. **[Getting Started](02_getting_started.md)**: Learn how to enable and use sandbox mode
2. **[Order Management](03_order_management.md)**: Understand order types and execution
3. **[Margin System](04_margin_system.md)**: Understand margin calculations
4. **[Position Management](05_position_management.md)**: Learn about positions and P&L
5. **[Auto Square-Off](06_auto_squareoff.md)**: Learn about MIS position closure
6. **[Database Schema](07_database_schema.md)**: Explore the data model
7. **[Architecture](08_architecture.md)**: Deep dive into system design
8. **[Configuration](09_configuration.md)**: Configure sandbox settings
9. **[API Reference](10_api_reference.md)**: API endpoints and usage
10. **[Troubleshooting](11_troubleshooting.md)**: Debug common issues

## Version

**Current Version**: 1.1.0 (October 2025)

### Recent Enhancements
- Market order bid/ask execution for realism
- Intraday P&L accumulation for multiple trades
- Dynamic starting capital updates
- Configurable option selling leverage
- MIS order blocking after square-off time
- Import datetime scope fix

---

**Next**: [Getting Started](02_getting_started.md)
