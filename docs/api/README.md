# OpenAlgo API Documentation

Welcome to the OpenAlgo REST API Documentation. This comprehensive guide covers all API endpoints available for algorithmic trading operations.

## Base URL

```http
Local Host   :  http://127.0.0.1:5000/api/v1
Ngrok Domain :  https://<your-ngrok-domain>.ngrok-free.app/api/v1
Custom Domain:  https://<your-custom-domain>/api/v1
```

## Authentication

All API endpoints require authentication using an API key. Include your API key in the request body:

```json
{
  "apikey": "<your_app_apikey>"
}
```

## API Categories

### Order Management
Execute and manage trading orders across all supported exchanges.

| Endpoint | Description |
|----------|-------------|
| [PlaceOrder](./order-management/placeorder.md) | Place a new order |
| [PlaceSmartOrder](./order-management/placesmartorder.md) | Place position-aware smart order |
| [OptionsOrder](./order-management/optionsorder.md) | Place options order with offset |
| [OptionsMultiOrder](./order-management/optionsmultiorder.md) | Place multi-leg options order |
| [BasketOrder](./order-management/basketorder.md) | Place multiple orders simultaneously |
| [SplitOrder](./order-management/splitorder.md) | Split large order into smaller chunks |
| [ModifyOrder](./order-management/modifyorder.md) | Modify an existing order |
| [CancelOrder](./order-management/cancelorder.md) | Cancel a specific order |
| [CancelAllOrder](./order-management/cancelallorder.md) | Cancel all open orders |
| [ClosePosition](./order-management/closeposition.md) | Close all open positions |

### Order Information
Query order status and position information.

| Endpoint | Description |
|----------|-------------|
| [OrderStatus](./order-information/orderstatus.md) | Get current status of an order |
| [OpenPosition](./order-information/openposition.md) | Get open position for a symbol |

### Market Data
Access real-time and historical market data.

| Endpoint | Description |
|----------|-------------|
| [Quotes](./market-data/quotes.md) | Get market quotes for a symbol |
| [MultiQuotes](./market-data/multiquotes.md) | Get quotes for multiple symbols |
| [Depth](./market-data/depth.md) | Get market depth (Level 2) data |
| [History](./market-data/history.md) | Get historical OHLCV data |
| [Intervals](./market-data/intervals.md) | Get available time intervals |

### Symbol Services
Symbol lookup, search, and instrument data.

| Endpoint | Description |
|----------|-------------|
| [Symbol](./symbol-services/symbol.md) | Get detailed symbol information |
| [Search](./symbol-services/search.md) | Search for symbols |
| [Expiry](./symbol-services/expiry.md) | Get expiry dates for F&O |
| [Instruments](./symbol-services/instruments.md) | Get all instruments list |

### Options Services
Options-specific operations and analytics.

| Endpoint | Description |
|----------|-------------|
| [OptionSymbol](./options-services/optionsymbol.md) | Get option symbol by offset |
| [OptionChain](./options-services/optionchain.md) | Get full option chain data |
| [SyntheticFuture](./options-services/syntheticfuture.md) | Calculate synthetic futures price |
| [OptionGreeks](./options-services/optiongreeks.md) | Calculate option Greeks and IV |

### Account Services
Account information, funds, and portfolio data.

| Endpoint | Description |
|----------|-------------|
| [Funds](./account-services/funds.md) | Get account funds information |
| [Margin](./account-services/margin.md) | Calculate margin requirement |
| [OrderBook](./account-services/orderbook.md) | Get all orders for the day |
| [TradeBook](./account-services/tradebook.md) | Get all trades for the day |
| [PositionBook](./account-services/positionbook.md) | Get all current positions |
| [Holdings](./account-services/holdings.md) | Get portfolio holdings |

### Market Calendar
Market timing and holiday information.

| Endpoint | Description |
|----------|-------------|
| [Holidays](./market-calendar/holidays.md) | Get market holidays for a year |
| [Timings](./market-calendar/timings.md) | Get market timings for a date |
| [CheckHoliday](./market-calendar/checkholiday.md) | Check if a date is a holiday |

### Analyzer Services
Sandbox/analyzer mode for testing.

| Endpoint | Description |
|----------|-------------|
| [AnalyzerStatus](./analyzer-services/analyzerstatus.md) | Get analyzer mode status |
| [AnalyzerToggle](./analyzer-services/analyzertoggle.md) | Toggle analyzer mode on/off |

### WebSocket Streaming
Real-time market data streaming.

| Endpoint | Description |
|----------|-------------|
| [LTP](./websocket-streaming/ltp.md) | Subscribe to last traded price |
| [Quote](./websocket-streaming/quote.md) | Subscribe to quote updates |
| [Depth](./websocket-streaming/depth.md) | Subscribe to market depth |

## Order Constants

### Exchange Codes
| Code | Description |
|------|-------------|
| NSE | National Stock Exchange (Equity) |
| BSE | Bombay Stock Exchange (Equity) |
| NFO | NSE Futures & Options |
| BFO | BSE Futures & Options |
| CDS | Currency Derivatives (NSE) |
| BCD | Currency Derivatives (BSE) |
| MCX | Multi Commodity Exchange |
| NSE_INDEX | NSE Index (for options trading) |
| BSE_INDEX | BSE Index (for options trading) |

### Product Types
| Code | Description |
|------|-------------|
| MIS | Margin Intraday Square-off |
| CNC | Cash and Carry (Equity Delivery) |
| NRML | Normal (F&O Overnight) |

### Price Types
| Code | Description |
|------|-------------|
| MARKET | Market order |
| LIMIT | Limit order |
| SL | Stop-loss limit order |
| SL-M | Stop-loss market order |

### Action Types
| Code | Description |
|------|-------------|
| BUY | Buy order |
| SELL | Sell order |

## Symbol Format Reference

### Equity
```
SYMBOL
Example: RELIANCE, SBIN, TCS
```

### Futures
```
[SYMBOL][DD][MMM][YY]FUT
Example: NIFTY30JAN25FUT, BANKNIFTY27FEB25FUT
```

### Options
```
[SYMBOL][DD][MMM][YY][STRIKE][CE/PE]
Example: NIFTY30JAN2525000CE, BANKNIFTY27FEB2552000PE
```

## Response Format

All API responses follow a consistent JSON format:

### Success Response
```json
{
  "status": "success",
  "data": { ... }
}
```

### Error Response
```json
{
  "status": "error",
  "message": "Error description"
}
```

## HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 400 | Bad Request (validation error) |
| 403 | Forbidden (invalid API key) |
| 404 | Not Found |
| 429 | Rate Limit Exceeded |
| 500 | Internal Server Error |

## Rate Limits

OpenAlgo implements differentiated rate limiting for various API operations:

| API Type | Rate Limit |
|----------|------------|
| Order Management | 10 per second |
| Smart Orders | 2 per second |
| General APIs | 50 per second |
| Webhooks | 100 per minute |

For detailed rate limiting information including configuration options, see [Rate Limiting](./rate-limiting.md).

## SDK Support

OpenAlgo provides official SDKs for popular programming languages:

- **Python**: `pip install openalgo`
- **Node.js**: Coming soon
- **Java**: Coming soon

## Support

- Documentation: https://docs.openalgo.in
- GitHub: https://github.com/marketcalls/openalgo
- Discord: https://www.openalgo.in/discord
