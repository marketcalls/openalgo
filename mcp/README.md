# OpenAlgo MCP Server

This is a Model Context Protocol (MCP) server that provides trading and market data functionality through the OpenAlgo platform. It enables AI assistants to execute trades, manage positions, and retrieve market data directly from supported brokers.

## Prerequisites

### 1. OpenAlgo Server Setup

Ensure your OpenAlgo server is running and properly configured:

1. **Start OpenAlgo Server**: Your OpenAlgo server should be running (e.g., on `http://127.0.0.1:5000`)
2. **Verify Connection**: Test that the server is accessible by visiting the web interface.
3. **Broker Authentication**: Ensure your broker credentials are properly configured in OpenAlgo.

### 2. API Key

To get your OpenAlgo API key:
1. Open your OpenAlgo web interface (e.g., `http://127.0.0.1:5000`)
2. Navigate to **Settings → API Keys**.
3. Generate or copy your existing API key.

## MCP Client Configuration

Add the following configuration to your MCP client, replacing the placeholder paths with your actual file paths. The server now takes the API key and host URL as command-line arguments for better security and flexibility.

### Windows

**Example Configuration:**
```json
{
  "mcpServers": {
    "openalgo": {
      "command": "D:\\openalgo-mcp\\openalgo\\.venv\\Scripts\\python.exe",
      "args": [
        "D:\\openalgo-mcp\\openalgo\\mcp\\mcpserver.py",
        "YOUR_API_KEY_HERE",
        "http://127.0.0.1:5000"
      ]
    }
  }
}
```

**Configuration File Locations:**
- **Claude Desktop**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Windsurf**: `%APPDATA%\Windsurf\mcp_config.json`
- **Cursor**: `%APPDATA%\Cursor\User\settings.json`

### macOS

**Example Configuration:**
```json
{
  "mcpServers": {
    "openalgo": {
      "command": "/Users/your_username/openalgo/.venv/bin/python3",
      "args": [
        "/Users/your_username/openalgo/mcp/mcpserver.py",
        "YOUR_API_KEY_HERE",
        "http://127.0.0.1:5000"
      ]
    }
  }
}
```

**Configuration File Locations:**
- **Claude Desktop**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windsurf**: `~/.config/windsurf/mcp_config.json`
- **Cursor**: `~/Library/Application Support/Cursor/User/settings.json`

### Linux

**Example Configuration:**
```json
{
  "mcpServers": {
    "openalgo": {
      "command": "/home/your_username/openalgo/.venv/bin/python3",
      "args": [
        "/home/your_username/openalgo/mcp/mcpserver.py",
        "YOUR_API_KEY_HERE",
        "http://127.0.0.1:5000"
      ]
    }
  }
}
```

**Configuration File Locations:**
- **Claude Desktop**: `~/.config/Claude/claude_desktop_config.json`
- **Windsurf**: `~/.config/windsurf/mcp_config.json`
- **Cursor**: `~/.config/Cursor/User/settings.json`

### Path Configuration Notes

**Important**: Replace the paths in the examples above with your actual installation paths:

- **Windows**: Replace `D:\\openalgo-zerodha\\openalgo` with your actual OpenAlgo installation path
- **macOS/Linux**: Replace `/Users/your_username` or `/home/your_username` with your actual home directory path

To find your Python virtual environment path:
- **Windows**: Usually in `venv\Scripts\python.exe`
- **macOS/Linux**: Usually in `.venv/bin/python3`

### ChatGPT Configuration (Platform Independent)

If your ChatGPT client supports MCP, use the appropriate path format for your operating system from the examples above.

## Available Tools

The MCP server provides the following categories of tools:

### Order Management
- `place_order` - Place market or limit orders
- `place_smart_order` - Place orders considering position size
- `place_basket_order` - Place multiple orders at once
- `place_split_order` - Split large orders into smaller chunks
- `place_options_order` - Place single leg options order with ATM/ITM/OTM offset
- `place_options_multi_order` - Place multi-leg options strategies (spreads, iron condor, etc.)
- `modify_order` - Modify existing orders
- `cancel_order` - Cancel specific orders
- `cancel_all_orders` - Cancel all orders for a strategy

### Position Management
- `close_all_positions` - Close all positions for a strategy
- `get_open_position` - Get current position for an instrument

### Order Status & Tracking
- `get_order_status` - Check status of specific orders
- `get_order_book` - View all orders
- `get_trade_book` - View executed trades
- `get_position_book` - View current positions
- `get_holdings` - View long-term holdings
- `get_funds` - Check account funds and margins

### Market Data
- `get_quote` - Get current price quotes
- `get_multi_quotes` - Get quotes for multiple symbols at once
- `get_market_depth` - Get order book depth
- `get_historical_data` - Retrieve historical price data
- `get_option_chain` - Get option chain with real-time quotes for all strikes

### Instrument Search
- `search_instruments` - Search for trading instruments
- `get_symbol_info` - Get detailed symbol information
- `get_expiry_dates` - Get derivative expiry dates
- `get_available_intervals` - List available time intervals
- `get_option_symbol` - Get option symbol for specific strike and expiry
- `get_synthetic_future` - Calculate synthetic future price using put-call parity
- `get_option_greeks` - Calculate option Greeks (delta, gamma, theta, vega, rho)
- `get_instruments` - Download all instruments for an exchange
- `get_index_symbols` - Get common index symbols for NSE or BSE

### Utilities
- `get_openalgo_version` - Check OpenAlgo version
- `validate_order_constants` - Display valid order parameters
- `send_telegram_alert` - Send Telegram notifications
- `get_holidays` - Get trading holidays for a year
- `get_timings` - Get exchange trading timings for a date
- `analyzer_status` - Get current analyzer mode status
- `analyzer_toggle` - Toggle between analyze (simulated) and live trading mode
- `calculate_margin` - Calculate margin requirements for positions

## Usage Examples

Once configured, you can ask your AI assistant to:

- "Place a buy order for 100 shares of RELIANCE at market price"
- "Show me my current positions"
- "Get the latest quote for NIFTY"
- "Get quotes for RELIANCE, INFY, and TCS"
- "Cancel all my pending orders"
- "What are my account funds?"
- "Place an iron condor on NIFTY with 25NOV25 expiry using OTM4 and OTM6 strikes"
- "Calculate the synthetic future price for NIFTY 25NOV25 expiry"
- "Get option Greeks for NIFTY 26000 CE expiring on 25NOV25"
- "Show me the option chain for NIFTY with 30DEC25 expiry"
- "What are the trading holidays in 2025?"
- "What are the market timings for today?"
- "Get all instruments for NSE"

## Supported Exchanges

- **NSE** - National Stock Exchange (Equity)
- **NFO** - NSE Futures & Options
- **CDS** - NSE Currency Derivatives
- **BSE** - Bombay Stock Exchange
- **BFO** - BSE Futures & Options
- **BCD** - BSE Currency Derivatives
- **MCX** - Multi Commodity Exchange
- **NCDEX** - National Commodity & Derivatives Exchange

## Security Note

⚠️ **Important**: This server is designed for local use. For production environments, consider implementing additional security measures such as environment variables for sensitive data and restricting network access.

## Troubleshooting

1. **Connection Issues**: Verify OpenAlgo server is running on `http://127.0.0.1:5000`
2. **Authentication Errors**: Check your API key is correct and valid
3. **Permission Errors**: Ensure the Python virtual environment has proper permissions
4. **Order Failures**: Verify your broker connection and trading permissions
4. **Order Failures**: Verify broker credentials in OpenAlgo are valid and active

## Support

For issues related to:
- **OpenAlgo Platform**: Visit the OpenAlgo documentation
- **MCP Protocol**: Check the Model Context Protocol specifications
- **Trading Errors**: Verify your broker connection and trading permissions