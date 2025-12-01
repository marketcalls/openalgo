# OpenAlgo Sandbox Mode Documentation

## Overview

OpenAlgo is an **open-source application** that provides a Sandbox Mode (also known as **API Analyzer Mode**) - a sophisticated simulated trading environment that makes it **easier for traders and developers** to test strategies, validate algorithms, and practice trading with realistic market data without risking real capital.

> **⚖️ Regulatory Note**: OpenAlgo Sandbox is **NOT** a virtual/paper trading platform as prohibited by SEBI. It is an **open-source, self-hosted personal test environment** that runs with your own broker APIs for strategy validation. See [Regulatory Compliance](12_regulatory_compliance.md) for detailed clarification.

## Key Features

- **Simulated Capital**: Start with ₹1 Crore (10 million) in sandbox funds
- **Realistic Execution**: Orders execute using real-time market data with bid/ask pricing
- **Complete Order Types**: Support for MARKET, LIMIT, SL, and SL-M orders
- **Accurate Margin System**: Leverage-based margin blocking and release
- **Auto Square-Off**: Automatic MIS position closure at exchange-specific times
- **T+1 Settlement**: CNC positions automatically convert to holdings at midnight with proper fund flow
  - BUY: Margin transferred to holdings (used_margin ↓, holdings_value ↑)
  - SELL: Sale proceeds credited to available balance
- **Catch-up Settlement**: Automatic settlement of missed CNC positions on app restart
- **Real-time P&L**: Mark-to-market calculations with live price updates
- **Separate Database**: Isolated sandbox.db for clean data separation
- **Intraday P&L Accumulation**: Tracks accumulated P&L across multiple trades on same symbol
- **MIS Order Blocking**: Prevents new MIS orders after square-off time until 09:00 AM

## Documentation Structure

### 1. [Overview](01_overview.md)
Introduction to sandbox mode, features, and how it works.

### 2. [Getting Started](02_getting_started.md)
Quick start guide to enable sandbox mode and place your first trade.

### 3. [Order Management](03_order_management.md)
Complete guide to order types, execution, and lifecycle.

### 4. [Margin System](04_margin_system.md)
Detailed explanation of margin calculations and leverage rules.

### 5. [Position Management](05_position_management.md)
Understanding positions, P&L calculations, and position closure.

### 5a. [T+1 Settlement & Holdings](05a_holdings_t1_settlement.md)
Complete guide to CNC lifecycle, T+1 settlement, and holdings fund flow.

### 6. [Auto Square-Off System](06_auto_squareoff.md)
How MIS positions are automatically squared off at configured times.

### 7. [Database Schema](07_database_schema.md)
Complete database structure, tables, and relationships.

### 8. [Architecture](08_architecture.md)
System design, components, and thread management.

### 9. [Configuration](09_configuration.md)
All configurable settings and how to modify them.

### 10. [API Reference](10_api_reference.md)
Complete API endpoints and usage examples.

### 11. [Troubleshooting](11_troubleshooting.md)
Common issues and solutions.

### 12. [Regulatory Compliance](12_regulatory_compliance.md)
Why OpenAlgo Sandbox is NOT virtual/paper trading - SEBI compliance clarification.

## Quick Start

### Enable Sandbox Mode

Via Web UI:
1. Log in to OpenAlgo
2. Navigate to Settings
3. Toggle "API Analyzer Mode" to ON

Via API:
```python
from services.analyzer_service import toggle_analyzer_mode

analyzer_data = {"mode": True}
success, response, status_code = toggle_analyzer_mode(
    analyzer_data=analyzer_data,
    api_key='your_api_key'
)
```

### Place Your First Order

```python
import requests

payload = {
    "apikey": "your_api_key",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "pricetype": "MARKET",
    "product": "MIS"
}

response = requests.post("http://127.0.0.1:5000/api/v1/placeorder", json=payload)
print(response.json())
```

### Check Your Position

```python
payload = {"apikey": "your_api_key"}
response = requests.post("http://127.0.0.1:5000/api/v1/positionbook", json=payload)
print(response.json())
```

## Key Concepts

### Simulated Capital
- Starting balance: ₹10,000,000 (1 Crore)
- Automatic reset: Every Sunday at 00:00 IST (configurable)
- Manual reset available from sandbox settings

### Realistic Execution
- Market orders execute at bid/ask prices for realism
- LIMIT orders execute at LTP when price crosses limit
- SL/SL-M orders trigger at trigger price and execute at LTP
- No artificial slippage or delays

### Separate Environment
- Completely isolated from live trading
- Separate database: `db/sandbox.db`
- Own configuration stored in `sandbox_config` table
- Zero impact on live trading activities

## Recent Updates (Version 1.1.0 - October 2025)

### New Features

1. **Market Order Bid/Ask Execution**
   - BUY orders execute at ask price (realistic market impact)
   - SELL orders execute at bid price (realistic market impact)
   - Falls back to LTP if bid/ask is zero

2. **Intraday P&L Accumulation**
   - Accumulated realized P&L tracked across multiple trades
   - Position reopening preserves previous day's accumulated P&L
   - Closed positions display total accumulated P&L

3. **Dynamic Starting Capital Updates**
   - Changing starting_capital in settings updates all user funds immediately
   - Formula: available_balance = new_capital - used_margin + total_pnl

4. **Configurable Option Leverage**
   - Separate configuration for option buying and selling leverage
   - option_buy_leverage: Default 1x (full premium required)
   - option_sell_leverage: Default 10x (configurable futures-like margin)

5. **MIS Order Post-Squareoff Blocking**
   - New MIS orders blocked after square-off time until 09:00 AM next day
   - Exception: Orders that reduce/close existing positions are allowed
   - User-friendly error message with timing information

### Bug Fixes

1. **Import Scope Fix**: Resolved datetime import conflict in order_manager.py
2. **Closed Position Filtering**: Square-off only processes positions with quantity != 0
3. **Option Leverage**: Removed hardcoded leverage values

## System Requirements

- Python 3.8+
- SQLAlchemy 1.4+
- APScheduler 3.10+
- Flask 2.0+
- Real-time market data access (broker API)

## Database Location

Sandbox database is stored at: `db/sandbox.db`

Configure via environment variable:
```bash
# .env
SANDBOX_DATABASE_URL=sqlite:///db/sandbox.db
```

## Configuration

Access sandbox settings at: `http://127.0.0.1:5000/sandbox`

### Capital Settings
- Starting Capital: ₹10,000,000
- Auto-Reset Day: Sunday (configurable via dropdown)
- Auto-Reset Time: 00:00 IST (configurable via time picker)
- **Automatic Reset**: APScheduler runs auto-reset job at configured day/time even if app was stopped

### Leverage Settings
- Equity MIS: 5x
- Equity CNC: 1x
- Futures: 10x
- Option Buy: 1x
- Option Sell: 10x

### Square-Off Times (IST)
- NSE/BSE: 15:15
- CDS/BCD: 16:45
- MCX: 23:30
- NCDEX: 17:00

### Update Intervals
- Order Check: 5 seconds
- MTM Update: 5 seconds

### Rate Limits
- Order Rate: 10 per second
- API Rate: 50 per second
- Smart Order Rate: 2 per second

## Architecture Overview

```
┌────────────────────────────────────────────────┐
│            OpenAlgo Application                 │
│                                                 │
│  ┌──────────┐        ┌──────────────┐         │
│  │ Analyzer │───────>│   Sandbox    │         │
│  │ Service  │        │   Service    │         │
│  └──────────┘        └──────────────┘         │
│                             │                   │
└─────────────────────────────┼───────────────────┘
                              │
        ┌─────────────────────┴────────────────┐
        │                                      │
┌───────▼────────┐          ┌──────────────────▼──────┐
│  Execution     │          │   APScheduler (Daemon)  │
│  Engine        │          │  - MIS Square-Off Jobs  │
│  Thread        │          │  - T+1 Settlement       │
└───────┬────────┘          │  - Auto-Reset Funds     │
        │                   └──────────┬──────────────┘
        │                              │
        └──────────────┬───────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
┌───────▼────────┐         ┌─────────▼────────┐
│ Order Manager  │         │ Position Manager │
└───────┬────────┘         └─────────┬────────┘
        │                             │
        └──────────────┬──────────────┘
                       │
               ┌───────▼────────┐
               │  Fund Manager  │
               └───────┬────────┘
                       │
               ┌───────▼────────┐
               │ Sandbox.db     │
               │                │
               │ - Orders       │
               │ - Trades       │
               │ - Positions    │
               │ - Holdings     │
               │ - Funds        │
               │ - Config       │
               └────────────────┘
```

## Getting Help

- **Documentation**: Read the detailed guides in this folder
- **Troubleshooting**: See [Troubleshooting Guide](11_troubleshooting.md)
- **GitHub Issues**: Report bugs and request features
- **Community Support**: Join discussions

## Version History

### Version 1.1.0 (October 2025)
- Market order bid/ask execution
- Intraday P&L accumulation
- Dynamic capital updates
- Configurable option leverage
- MIS post-squareoff blocking
- Import scope fixes

### Version 1.0.4 (October 2025)
- Complete margin system overhaul
- Auto square-off implementation
- Realistic execution pricing
- Database migration system

### Version 1.0.3 (September 2025)
- Initial sandbox implementation
- Basic order execution
- Position management

## License

OpenAlgo Sandbox Mode is part of OpenAlgo and follows the same license terms.

---

**Next Steps**: Start with [Overview](01_overview.md) to understand sandbox mode basics, then proceed to [Getting Started](02_getting_started.md) to begin trading.
