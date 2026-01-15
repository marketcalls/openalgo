# WebSocket UI Documentation

## Overview

The WebSocket UI provides a comprehensive testing interface for real-time market data streaming in OpenAlgo. It connects directly to the WebSocket proxy server at `ws://localhost:8765` and displays live market data for RELIANCE and TCS symbols.

## Architecture

### Direct WebSocket Connection
```
Frontend (Browser) ↔ WebSocket Server (ws://localhost:8765) ↔ ZeroMQ ↔ Broker Adapters ↔ Angel/Zerodha/etc.
```

**Key Benefits:**
- **Maximum Performance**: Direct TCP WebSocket connection with minimal latency
- **Real-time Updates**: Sub-second market data streaming
- **No Middleware**: Eliminates Socket.IO overhead for trading-critical applications
- **Production Ready**: Suitable for high-frequency trading applications

## File Structure

```
├── blueprints/websocket_example.py     # Flask blueprint with REST endpoints
├── templates/websocket/
│   └── test_market_data.html          # Main WebSocket UI template
└── services/
    ├── websocket_client.py            # Internal WebSocket client wrapper
    └── websocket_service.py           # Service layer functions
```

## Features

### 1. Connection Management
- **WebSocket Status**: Real-time connection indicator
- **Auto-connect**: Attempts connection on page load
- **API Key Authentication**: Automatically retrieves and uses API key
- **Connection Resilience**: Handles disconnections gracefully

### 2. Market Data Display

#### LTP (Last Traded Price)
- **Real-time Price**: Live price updates with color coding
- **Price Changes**: Green (↗️) for up, Red (↘️) for down
- **IST Timestamps**: Proper Indian Standard Time formatting
- **Flash Animation**: Visual feedback for price updates

#### Quote Data
Displays comprehensive market information:
- **OHLC**: Open, High, Low, Close prices
- **Volume**: Total traded volume with Indian number formatting
- **Average Price**: Volume-weighted average price
- **Buy/Sell Quantities**: Total pending buy and sell quantities
- **Circuit Limits**: Upper and lower circuit limits with color coding

#### Market Depth (Order Book)
- **5-Level Depth**: Best 5 buy and sell orders
- **Price/Quantity/Orders**: Complete order book information
- **Real-time Updates**: Live order book changes

### 3. Subscription Management

#### Individual Subscriptions
```javascript
// Subscribe to specific data types
subscribe('RELIANCE', 'NSE', 'LTP');    // Last Traded Price only
subscribe('RELIANCE', 'NSE', 'Quote');  // Complete quote data
subscribe('RELIANCE', 'NSE', 'Depth');  // Market depth/order book
```

#### Bulk Operations
- **Subscribe All**: Subscribe to LTP, Quote, and Depth for both symbols
- **Subscribe All LTP**: Subscribe to LTP for both RELIANCE and TCS
- **Subscribe All Quote**: Subscribe to Quote for both symbols
- **Subscribe All Depth**: Subscribe to Depth for both symbols
- **Unsubscribe All**: Remove all active subscriptions

#### Advanced Testing
- **Sequential Test**: Automated test sequence with subscription changes
- **Performance Test**: Rapid subscription/unsubscription with metrics
- **Subscription Counter**: Real-time count of active subscriptions

## Technical Implementation

### WebSocket Message Format

#### Authentication
```json
{
  "action": "authenticate",
  "api_key": "your_api_key_here"
}
```

#### Subscribe to Market Data
```json
{
  "action": "subscribe",
  "symbols": [
    {"symbol": "RELIANCE", "exchange": "NSE"}
  ],
  "mode": "LTP"
}
```

#### Unsubscribe from Market Data
```json
{
  "action": "unsubscribe",
  "symbols": [
    {
      "symbol": "RELIANCE", 
      "exchange": "NSE",
      "mode": 1
    }
  ],
  "mode": "LTP"
}
```

### Data Processing

#### Price Formatting
```javascript
function formatPrice(price) {
    return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(price);
}
```

#### IST Timestamp Formatting
```javascript
function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-IN', {
        timeZone: 'Asia/Kolkata',
        hour12: true,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}
```

#### Volume Formatting
```javascript
function formatVolume(volume) {
    return new Intl.NumberFormat('en-IN').format(volume);
}
```

### Market Data Structure

The WebSocket server publishes market data in the following format:

#### LTP Mode (mode: 1)
```json
{
  "type": "market_data",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 1,
  "data": {
    "ltp": 1402.7,
    "ltt": 1753340513000,
    "timestamp": 1753340514068
  }
}
```

#### Quote Mode (mode: 2)
```json
{
  "type": "market_data",
  "symbol": "RELIANCE",
  "exchange": "NSE", 
  "mode": 1,
  "data": {
    "ltp": 1402.7,
    "ltt": 1753340513000,
    "volume": 7082847,
    "open": 1419.2,
    "high": 1423.0,
    "low": 1396.0,
    "close": 1424.6,
    "last_quantity": 205,
    "average_price": 1410.36,
    "total_buy_quantity": 576510.0,
    "total_sell_quantity": 634558.0,
    "upper_circuit": 1567.0,
    "lower_circuit": 1282.2,
    "timestamp": 1753340515067
  }
}
```

#### Depth Mode (mode: 3)
```json
{
  "type": "market_data",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 1,
  "data": {
    "ltp": 1402.7,
    "ltt": 1753340513000,
    "volume": 7082847,
    "oi": 277831000,
    "upper_circuit": 1567.0,
    "lower_circuit": 1282.2,
    "depth": {
      "buy": [
        {"price": 1402.5, "quantity": 674, "orders": 6},
        {"price": 1402.4, "quantity": 157, "orders": 6},
        {"price": 1402.3, "quantity": 905, "orders": 13},
        {"price": 1402.2, "quantity": 1336, "orders": 6},
        {"price": 1402.1, "quantity": 758, "orders": 14}
      ],
      "sell": [
        {"price": 1402.7, "quantity": 696, "orders": 4},
        {"price": 1402.8, "quantity": 27, "orders": 1},
        {"price": 1402.9, "quantity": 722, "orders": 8},
        {"price": 1403.0, "quantity": 568, "orders": 12},
        {"price": 1403.1, "quantity": 1466, "orders": 18}
      ]
    },
    "timestamp": 1753340514584
  }
}
```

## User Interface Components

### Connection Status Panel
- **WebSocket Status**: Green (Connected) / Red (Disconnected)
- **Subscription Count**: Real-time count of active subscriptions
- **Visual Indicators**: Color-coded connection indicators

### Control Panel
- **Connect WebSocket**: Manual connection button
- **Bulk Subscription Buttons**: Quick subscribe/unsubscribe for common patterns
- **Individual Symbol Controls**: Granular subscription management
- **Testing Functions**: Sequential and performance tests

### Market Data Display
- **Symbol Cards**: Separate cards for RELIANCE and TCS
- **Data Sections**: LTP, Quote, and Depth sections per symbol
- **Real-time Updates**: Flash animations and color coding
- **Responsive Design**: Works on desktop and mobile

### Event Log
- **Real-time Logging**: All WebSocket events and data updates
- **Color-coded Messages**: Success (green), Error (red), Info (blue)
- **Timestamps**: IST timestamps for all events
- **Scrollable**: Auto-scroll to latest events
- **Clear Function**: Reset log display

## Usage Examples

### Basic Usage
1. **Navigate** to `/websocket/test`
2. **Click** "Connect WebSocket" (auto-connects on page load)
3. **Subscribe** to desired data using individual buttons
4. **Monitor** real-time data updates in the interface
5. **Check** event log for detailed message flow

### Testing Scenarios

#### Performance Testing
```javascript
// Test rapid subscriptions
function testPerformance() {
    const symbols = ['RELIANCE', 'TCS'];
    const modes = ['LTP', 'Quote', 'Depth'];
    
    symbols.forEach((symbol, i) => {
        modes.forEach((mode, j) => {
            setTimeout(() => {
                subscribe(symbol, 'NSE', mode);
            }, (i * 3 + j) * 200);
        });
    });
}
```

#### Sequential Testing
```javascript
// Automated test sequence
function testSequential() {
    setTimeout(() => subscribeAllLTP(), 1000);
    setTimeout(() => subscribeAllQuote(), 3000);  
    setTimeout(() => unsubscribeAll(), 8000);
}
```

## Error Handling

### Connection Errors
- **Timeout Handling**: 10-second connection timeout
- **Retry Logic**: Automatic reconnection attempts
- **Error Messages**: Clear error descriptions in event log

### Authentication Errors
- **API Key Validation**: Checks for valid API key before connection
- **Session Validation**: Ensures user session is active
- **Clear Instructions**: Guides user to generate API key if missing

### Subscription Errors
- **Invalid Parameters**: Validates symbol and exchange parameters
- **Server Errors**: Displays broker adapter errors
- **Mode Validation**: Ensures valid subscription modes

## Performance Characteristics

### Latency
- **Sub-millisecond**: Direct WebSocket connection
- **Real-time**: No buffering or batching delays
- **Broker-dependent**: Limited by broker feed latency

### Throughput
- **High-frequency**: Handles rapid market data updates
- **Multiple symbols**: Concurrent subscriptions without performance impact
- **Efficient rendering**: Optimized DOM updates with flash animations

### Memory Usage
- **Lightweight**: Minimal JavaScript footprint
- **Efficient caching**: Last price tracking for color coding
- **Log management**: Automatic log entry limiting (100 entries)

## Browser Compatibility

### Supported Browsers
- **Chrome**: Full support
- **Firefox**: Full support  
- **Safari**: Full support
- **Edge**: Full support

### Required Features
- **WebSocket API**: Native WebSocket support
- **ES6 Features**: Arrow functions, const/let, template literals
- **Fetch API**: For REST API calls
- **Intl API**: For number and date formatting

## Security Considerations

### Authentication
- **API Key**: Required for WebSocket server access
- **Session Validation**: Server-side session checking
- **HTTPS/WSS**: Secure connections in production

### Data Protection
- **No Data Persistence**: No market data stored locally
- **Session-based**: Temporary connections only
- **CSRF Protection**: CSRF tokens for REST endpoints

## Troubleshooting

### Common Issues

#### "No API key found"
**Solution**: Generate API key at `/apikey` endpoint first

#### "WebSocket connection failed"
**Solution**: Ensure WebSocket server is running on port 8765

#### "Authentication failed"
**Solution**: Check API key validity and user session

#### "No data updates"
**Solution**: Verify broker connection and subscription status

### Debug Information

Enable debug logging by checking the event log for:
- **Connection messages**: WebSocket connection status
- **Authentication flow**: API key validation steps  
- **Subscription details**: Sent/received message payloads
- **Data flow**: Market data update frequency

## Integration with OpenAlgo

### Flask Integration
- **Blueprint Registration**: Auto-registered in main Flask app
- **Session Management**: Uses existing user session system
- **API Key Integration**: Leverages OpenAlgo API key system

### Database Integration
- **API Key Lookup**: Queries existing API key database
- **User Authentication**: Uses OpenAlgo user session management
- **No Additional Storage**: No new database tables required

### WebSocket Proxy Integration
- **Direct Connection**: Uses existing WebSocket proxy server
- **Broker Compatibility**: Works with all supported brokers
- **Real-time Feed**: Leverages existing market data infrastructure

## Future Enhancements

### Planned Features
- **More Symbols**: Support for custom symbol selection
- **Chart Integration**: Price charts with historical data
- **Alert System**: Price-based alerts and notifications
- **Data Export**: CSV/JSON export of market data
- **Advanced Filters**: Symbol search and filtering
- **Portfolio View**: Multiple symbol monitoring dashboard

### Technical Improvements
- **Reconnection Logic**: Enhanced auto-reconnection
- **Data Compression**: WebSocket compression for efficiency
- **Offline Support**: Service worker for offline functionality
- **Mobile App**: Native mobile application

---

**Note**: This UI is designed for testing and development purposes. For production trading applications, consider implementing additional error handling, monitoring, and failover mechanisms.