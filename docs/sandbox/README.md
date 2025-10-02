# OpenAlgo Sandbox Mode Documentation

## Overview

OpenAlgo Sandbox Mode (also known as Analyzer Mode) is a sophisticated simulated trading environment that allows traders and developers to test strategies, validate algorithms, and practice trading with realistic market data without risking real capital.

## Key Features

- **Simulated Capital**: Start with ₹1 Crore (10 million) in sandbox funds
- **Realistic Execution**: Orders execute using real-time market data (LTP)
- **Complete Order Types**: Support for MARKET, LIMIT, SL, and SL-M orders
- **Accurate Margin System**: Leverage-based margin blocking and release
- **Auto Square-Off**: Automatic MIS position closure at exchange-specific times
- **Real-time P&L**: Mark-to-market calculations with live price updates
- **Separate Database**: Isolated sandbox.db for clean data separation

## Documentation Structure

This documentation is organized into the following sections:

### 1. [Getting Started](01_getting_started.md)
- Enabling Sandbox Mode
- Initial Setup and Configuration
- Understanding the Interface
- Your First Virtual Trade

### 2. [Order Management](02_order_management.md)
- Order Types and Execution
- Margin Blocking System
- Order Status Lifecycle
- Pending Order Processing
- Rate Limiting and Compliance

### 3. [Position Management](03_position_management.md)
- Position Creation and Updates
- P&L Calculations
- MTM (Mark to Market)
- Product Types (MIS, NRML, CNC)
- Position Closure

### 4. [Margin System](04_margin_system.md)
- Leverage Rules by Exchange
- Margin Calculation Methods
- Instrument Type Detection
- Margin Blocking and Release
- Price Types for Margin Calculation

### 5. [Auto Square-Off System](05_auto_squareoff.md)
- Exchange-wise Square-off Times
- APScheduler Implementation
- Squareoff Thread Architecture
- Configuration and Reload
- Status Monitoring

### 6. [Database Schema](06_database_schema.md)
- Table Structures
- Indexes and Performance
- Data Relationships
- Migration System

### 7. [Architecture](07_architecture.md)
- System Components
- Thread Management
- Service Layer
- Integration Points

### 8. [Configuration](08_configuration.md)
- Sandbox Settings
- Environment Variables
- Leverage Configuration
- Timing Configuration

### 9. [API Reference](09_api_reference.md)
- Endpoints
- Request/Response Formats
- Error Handling
- Authentication

### 10. [Troubleshooting](10_troubleshooting.md)
- Common Issues
- Debug Procedures
- Log Analysis
- Performance Tuning

## Quick Start

### Enable Sandbox Mode

```python
# Via API
from services.analyzer_service import toggle_analyzer_mode

analyzer_data = {"mode": True}
success, response, status_code = toggle_analyzer_mode(
    analyzer_data=analyzer_data,
    api_key='your_api_key'
)
```

### Place Your First Sandbox Order

```python
# Place a MARKET order
order_data = {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 100,
    "price_type": "MARKET",
    "product": "MIS"
}
```

### Check Your Position

```python
# Get positions
from services.sandbox_service import get_positions

success, response, status_code = get_positions(
    api_key='your_api_key'
)
```

## Key Concepts

### Simulated Capital
- Starting balance: ₹10,000,000 (1 Crore)
- Automatic reset: Every Sunday at 00:00 IST
- Manual reset available from sandbox settings

### Realistic Execution
- All orders execute at real-time LTP (Last Traded Price)
- LIMIT orders execute when LTP crosses limit price
- SL/SL-M orders trigger at trigger price and execute at LTP
- No artificial slippage or delays

### Separate Environment
- Completely isolated from live trading
- Separate database: `db/sandbox.db`
- Own configuration: Stored in `sandbox_config` table
- No impact on live trading activities

## Recent Updates (Version 1.0.4)

### October 2025 Updates

1. **Margin System Enhancements**
   - Fixed margin blocking for LIMIT, SL, and SL-M orders
   - Added margin release on order cancellation
   - Improved margin calculation using order-specific prices

2. **Execution Price Improvements**
   - LIMIT orders now execute at LTP for realistic fills
   - SL/SL-M orders execute at LTP after trigger
   - Better price discovery and realistic trading

3. **Instrument Type Detection**
   - Replaced hardcoded instrument types with exchange+suffix logic
   - Options: NFO/BFO/MCX/CDS/BCD/NCDEX symbols ending with CE/PE
   - Futures: NFO/BFO/MCX/CDS/BCD/NCDEX symbols ending with FUT

4. **Auto Square-Off System**
   - Implemented separate squareoff_thread using APScheduler
   - Exchange-specific timing in IST timezone
   - Dynamic configuration reload without restart
   - Status monitoring endpoints

5. **Database Organization**
   - Moved sandbox.db to /db directory
   - Configurable via SANDBOX_DATABASE_URL in .env
   - Better organization and backup management

6. **Migration System**
   - Created upgrade/003_sandbox_complete_setup.py
   - Idempotent migration supporting fresh installs and upgrades
   - Adds missing columns and indexes
   - Inserts 18 default configuration entries

## System Requirements

- Python 3.8+
- SQLAlchemy 1.4+
- APScheduler 3.10+
- Flask 2.0+
- Real-time market data access

## Getting Help

- **Documentation**: Read the detailed guides in this folder
- **Troubleshooting**: See [Troubleshooting Guide](10_troubleshooting.md)
- **GitHub Issues**: Report bugs and request features
- **Community Support**: Join discussions

## Version History

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

**Next Steps**: Start with [Getting Started](01_getting_started.md) to begin using Sandbox Mode.
