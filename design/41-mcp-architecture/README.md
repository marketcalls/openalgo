# 41 - MCP Architecture

## Overview

OpenAlgo includes an MCP (Model Context Protocol) server that enables AI assistants like Claude, Cursor, and Windsurf to control trading operations through natural language commands.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          MCP Architecture                                     │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           AI Clients                                         │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  Claude         │  │   Cursor        │  │   Windsurf      │             │
│  │  Desktop        │  │   IDE           │  │   IDE           │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                │                                             │
│                    MCP Protocol (stdio transport)                           │
│                                │                                             │
└────────────────────────────────┼────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     MCP Server (mcpserver.py)                                │
│                          FastMCP Framework                                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      50+ Trading Tools                               │   │
│  │                                                                      │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                │   │
│  │  │ Order Tools  │ │ Data Tools   │ │ Account Tools│                │   │
│  │  │              │ │              │ │              │                │   │
│  │  │ place_order  │ │ get_quote    │ │ get_funds    │                │   │
│  │  │ smart_order  │ │ get_depth    │ │ get_holdings │                │   │
│  │  │ cancel_order │ │ get_history  │ │ get_positions│                │   │
│  │  │ basket_order │ │ option_chain │ │ margin_calc  │                │   │
│  │  └──────────────┘ └──────────────┘ └──────────────┘                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 │ OpenAlgo Python Library
                                 │ (openalgo==1.0.45)
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       OpenAlgo REST API                                      │
│                       /api/v1/*                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Broker Integration                                      │
│                      (24+ Brokers)                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## MCP Tools

### Order Management (9 tools)

```python
@mcp.tool()
def place_order(symbol, quantity, action, exchange, price_type, product,
                strategy, price, trigger_price, disclosed_quantity):
    """Place a trading order"""

@mcp.tool()
def place_smart_order(symbol, quantity, action, position_size, exchange,
                      price_type, product, strategy, price):
    """Smart order considering current position"""

@mcp.tool()
def place_basket_order(orders, strategy):
    """Place multiple orders at once"""

@mcp.tool()
def place_split_order(symbol, quantity, split_size, action, exchange,
                      price_type, product, strategy, price, trigger_price):
    """Split large order into smaller chunks"""

@mcp.tool()
def place_options_order(underlying, exchange, offset, option_type, action,
                        quantity, expiry_date, strategy, price_type, product):
    """Place options order with ATM/ITM/OTM offset"""

@mcp.tool()
def place_options_multi_order(strategy, underlying, exchange, legs, expiry):
    """Place multi-leg options (spreads, straddles)"""

@mcp.tool()
def modify_order(order_id, strategy, symbol, action, exchange, price_type,
                 product, quantity, price):
    """Modify existing order"""

@mcp.tool()
def cancel_order(order_id, strategy):
    """Cancel pending order"""

@mcp.tool()
def cancel_all_orders(strategy):
    """Cancel all pending orders"""
```

### Market Data (6 tools)

```python
@mcp.tool()
def get_quote(symbol, exchange):
    """Get real-time quote for symbol"""

@mcp.tool()
def get_multi_quotes(symbols):
    """Get quotes for multiple symbols"""

@mcp.tool()
def get_option_chain(underlying, exchange, expiry_date, strike_count):
    """Get option chain with strikes"""

@mcp.tool()
def get_market_depth(symbol, exchange):
    """Get market depth (order book)"""

@mcp.tool()
def get_historical_data(symbol, exchange, interval, start_date, end_date):
    """Get historical OHLC data"""

@mcp.tool()
def get_option_greeks(symbol, exchange, underlying_symbol,
                      underlying_exchange, interest_rate):
    """Calculate option Greeks"""
```

### Account & Position (7 tools)

```python
@mcp.tool()
def get_order_book():
    """Get all orders"""

@mcp.tool()
def get_trade_book():
    """Get executed trades"""

@mcp.tool()
def get_position_book():
    """Get open positions"""

@mcp.tool()
def get_holdings():
    """Get stock holdings"""

@mcp.tool()
def get_funds():
    """Get account funds and margin"""

@mcp.tool()
def get_open_position(strategy, symbol, exchange, product):
    """Get specific open position"""

@mcp.tool()
def close_all_positions(strategy):
    """Close all open positions"""
```

### Instrument Search (8 tools)

```python
@mcp.tool()
def search_instruments(query, exchange, instrument_type):
    """Search for instruments"""

@mcp.tool()
def get_symbol_info(symbol, exchange, instrument_type):
    """Get symbol details (lot size, tick size)"""

@mcp.tool()
def get_expiry_dates(symbol, exchange, instrument_type):
    """Get available expiry dates"""

@mcp.tool()
def get_option_symbol(underlying, exchange, expiry, offset, option_type):
    """Get option symbol for given parameters"""

@mcp.tool()
def get_synthetic_future(underlying, exchange, expiry):
    """Calculate synthetic future price"""
```

### Utility (9 tools)

```python
@mcp.tool()
def get_openalgo_version():
    """Get OpenAlgo version"""

@mcp.tool()
def analyzer_status():
    """Check analyzer mode status"""

@mcp.tool()
def analyzer_toggle(mode):
    """Toggle between live and analyze mode"""

@mcp.tool()
def get_holidays(year):
    """Get market holidays"""

@mcp.tool()
def get_timings(date):
    """Get market timings for date"""
```

## Configuration

### Claude Desktop (macOS)

```json
// ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "openalgo": {
      "command": "/path/to/openalgo/.venv/bin/python3",
      "args": [
        "/path/to/openalgo/mcp/mcpserver.py",
        "YOUR_API_KEY",
        "http://127.0.0.1:5000"
      ]
    }
  }
}
```

### Cursor IDE

```json
// ~/.config/Cursor/User/settings.json (or %APPDATA%\Cursor\User\settings.json)
{
  "mcpServers": {
    "openalgo": {
      "command": "python",
      "args": [
        "path/to/openalgo/mcp/mcpserver.py",
        "YOUR_API_KEY",
        "http://127.0.0.1:5000"
      ]
    }
  }
}
```

### Windsurf IDE

```json
// ~/.config/windsurf/mcp_config.json
{
  "mcpServers": {
    "openalgo": {
      "command": "python",
      "args": [
        "path/to/openalgo/mcp/mcpserver.py",
        "YOUR_API_KEY",
        "http://127.0.0.1:5000"
      ]
    }
  }
}
```

## Natural Language Examples

### Order Placement

```
User: "Buy 100 shares of SBIN at market price"

AI: I'll place a market order for SBIN.
    [Calls place_order tool]
    Order placed successfully. Order ID: 123456789
```

### Position Management

```
User: "Show me my current positions"

AI: Let me fetch your open positions.
    [Calls get_position_book tool]

    Current Positions:
    - SBIN: 100 qty @ ₹625.50 (P&L: +₹150)
    - INFY: -50 qty @ ₹1655.00 (P&L: +₹250)
```

### Options Trading

```
User: "Place an iron condor on NIFTY expiring 30JAN25"

AI: I'll create an iron condor strategy for NIFTY.
    [Calls place_options_multi_order tool]

    Legs:
    1. SELL NIFTY 21500 CE @ ₹85
    2. BUY NIFTY 21600 CE @ ₹45
    3. SELL NIFTY 21000 PE @ ₹75
    4. BUY NIFTY 20900 PE @ ₹35

    Net credit: ₹80 per lot
```

### Market Analysis

```
User: "What's the current quote for RELIANCE?"

AI: [Calls get_quote tool]

    RELIANCE (NSE):
    - LTP: ₹2,450.00
    - Change: +₹25.50 (+1.05%)
    - Open: ₹2,430.00
    - High: ₹2,465.00
    - Low: ₹2,425.00
    - Volume: 5.2M
```

## Security

### API Key Handling

- API key passed as command-line argument
- Never hardcoded in scripts
- Stored securely in MCP config file

### Transport Security

- Uses stdio transport (local only)
- No network exposure of MCP server
- API calls use HTTPS when remote

### User Context

- All operations tied to strategy name
- Audit trail in OpenAlgo logs
- Rate limiting applied

## Dependencies

```
mcp==1.23.0           # MCP framework
openalgo==1.0.45      # OpenAlgo Python client
httpx[http2]==0.28.1  # HTTP client
```

## Implementation

### Server Initialization

```python
# mcp/mcpserver.py

from mcp.server.fastmcp import FastMCP
from openalgo import api

# Initialize OpenAlgo client
client = api(api_key=sys.argv[1], host=sys.argv[2])

# Initialize MCP server
mcp = FastMCP("openalgo")

# Register tools
@mcp.tool()
def place_order(...):
    return client.place_order(...)

# Run server
mcp.run(transport='stdio')
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `mcp/mcpserver.py` | MCP server with 50+ tools |
| `mcp/README.md` | Setup documentation |
| External: `openalgo` package | Python client library |
