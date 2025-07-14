# OpenAlgo MCP Server

This is a Model Context Protocol (MCP) server that provides trading and market data functionality through the OpenAlgo platform. It enables AI assistants to execute trades, manage positions, and retrieve market data directly from supported brokers.

## Prerequisites

### 1. OpenAlgo Server Setup

Ensure your OpenAlgo server is running and properly configured:

1. **Start OpenAlgo Server**: Your OpenAlgo server should be running on `http://127.0.0.1:5000`
2. **Verify Connection**: Test the server is accessible by visiting the web interface
3. **Broker Authentication**: Ensure your broker credentials are properly configured in OpenAlgo

### 2. API Key Configuration

**IMPORTANT**: Update the API key in `mcpserver.py`:

```python
# Line 7 in mcpserver.py - Replace with your actual API key
api_key = 'YOUR_OPENALGO_API_KEY_HERE'
```

To get your OpenAlgo API key:
1. Open your OpenAlgo web interface (usually `http://127.0.0.1:5000`)
2. Navigate to Settings → API Keys
3. Generate or copy your existing API key
4. Replace the placeholder in line 7 of `mcpserver.py`

## MCP Client Configuration

Add this configuration to your MCP client based on your operating system:

### macOS

#### Claude Desktop
Configuration file location: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "openalgo": {
      "command": "/Users/openalgo/openalgo-test/openalgo/.venv/bin/python3",
      "args": [
        "/Users/openalgo/openalgo-test/openalgo/mcp/mcpserver.py"
      ]
    }
  }
}
```

#### Windsurf
Configuration file location: `~/.config/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "openalgo": {
      "command": "/Users/openalgo/openalgo-test/openalgo/.venv/bin/python3",
      "args": [
        "/Users/openalgo/openalgo-test/openalgo/mcp/mcpserver.py"
      ]
    }
  }
}
```

#### Cursor
Configuration file location: `~/Library/Application Support/Cursor/User/settings.json`

```json
{
  "mcpServers": {
    "openalgo": {
      "command": "/Users/openalgo/openalgo-test/openalgo/.venv/bin/python3",
      "args": [
        "/Users/openalgo/openalgo-test/openalgo/mcp/mcpserver.py"
      ]
    }
  }
}
```

### Windows

#### Claude Desktop
Configuration file location: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "openalgo": {
      "command": "C:\\path\\to\\your\\openalgo\\venv\\Scripts\\python.exe",
      "args": [
        "C:\\path\\to\\your\\openalgo\\mcp\\mcpserver.py"
      ]
    }
  }
}
```

#### Windsurf
Configuration file location: `%APPDATA%\Windsurf\mcp_config.json`

```json
{
  "mcpServers": {
    "openalgo": {
      "command": "C:\\path\\to\\your\\openalgo\\venv\\Scripts\\python.exe",
      "args": [
        "C:\\path\\to\\your\\openalgo\\mcp\\mcpserver.py"
      ]
    }
  }
}
```

#### Cursor
Configuration file location: `%APPDATA%\Cursor\User\settings.json`

```json
{
  "mcpServers": {
    "openalgo": {
      "command": "C:\\path\\to\\your\\openalgo\\venv\\Scripts\\python.exe",
      "args": [
        "C:\\path\\to\\your\\openalgo\\mcp\\mcpserver.py"
      ]
    }
  }
}
```

### Linux

#### Claude Desktop
Configuration file location: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "openalgo": {
      "command": "/home/username/openalgo-test/openalgo/.venv/bin/python3",
      "args": [
        "/home/username/openalgo-test/openalgo/mcp/mcpserver.py"
      ]
    }
  }
}
```

#### Windsurf
Configuration file location: `~/.config/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "openalgo": {
      "command": "/home/username/openalgo-test/openalgo/.venv/bin/python3",
      "args": [
        "/home/username/openalgo-test/openalgo/mcp/mcpserver.py"
      ]
    }
  }
}
```

#### Cursor
Configuration file location: `~/.config/Cursor/User/settings.json`

```json
{
  "mcpServers": {
    "openalgo": {
      "command": "/home/username/openalgo-test/openalgo/.venv/bin/python3",
      "args": [
        "/home/username/openalgo-test/openalgo/mcp/mcpserver.py"
      ]
    }
  }
}
```

### Path Configuration Notes

**Important**: Replace the paths in the examples above with your actual installation paths:

- **Windows**: Replace `C:\\path\\to\\your\\openalgo` with your actual OpenAlgo installation path
- **Linux**: Replace `/home/username` with your actual home directory path
- **macOS**: The example shows `/Users/openalgo` - adjust to your actual path

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
- `get_market_depth` - Get order book depth
- `get_historical_data` - Retrieve historical price data

### Instrument Search
- `search_instruments` - Search for trading instruments
- `get_symbol_info` - Get detailed symbol information
- `get_expiry_dates` - Get derivative expiry dates
- `get_available_intervals` - List available time intervals

### Utilities
- `get_openalgo_version` - Check OpenAlgo version
- `validate_order_constants` - Display valid order parameters

## Usage Examples

Once configured, you can ask your AI assistant to:

- "Place a buy order for 100 shares of RELIANCE at market price"
- "Show me my current positions"
- "Get the latest quote for NIFTY"
- "Cancel all my pending orders"
- "What are my account funds?"

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

⚠️ **Important**: This server uses a hardcoded API key. For production use, consider:
- Using environment variables for the API key
- Implementing proper authentication mechanisms
- Restricting network access to the MCP server

## Troubleshooting

1. **Connection Issues**: Verify OpenAlgo server is running on `http://127.0.0.1:5000`
2. **Authentication Errors**: Check your API key is correct and valid
3. **Permission Errors**: Ensure the Python virtual environment has proper permissions
4. **Order Failures**: Verify broker credentials in OpenAlgo are valid and active

## Support

For issues related to:
- **OpenAlgo Platform**: Visit the OpenAlgo documentation
- **MCP Protocol**: Check the Model Context Protocol specifications
- **Trading Errors**: Verify your broker connection and trading permissions