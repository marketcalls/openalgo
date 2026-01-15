# PnL Tracker Documentation

## Overview

The PnL Tracker is a real-time profit and loss monitoring feature in OpenAlgo that provides visual insights into intraday trading performance. It displays MTM (Mark-to-Market) PnL curves and drawdown analysis using interactive charts powered by TradingView Lightweight Charts.

## Features

### Key Metrics
- **Current MTM**: Real-time mark-to-market profit/loss
- **Max MTM**: Peak profit achieved during the trading day with timestamp
- **Min MTM**: Maximum loss during the trading day with timestamp  
- **Max Drawdown**: Largest peak-to-trough decline in portfolio value

### Visualization
- Interactive intraday PnL curve from 9:00 AM IST to current time
- Drawdown visualization showing portfolio decline from peaks
- IST timezone support with accurate time display
- Theme-aware charts (Light/Dark/Garden themes)

## Technical Architecture

### Components

#### 1. Blueprint Route (`/blueprints/pnltracker.py`)
- **Endpoint**: `/pnltracker` - Main page
- **API Endpoint**: `/pnltracker/api/pnl` - Data API (POST)
- **Session Management**: Uses `check_session_validity` decorator
- **Authentication**: API key based authentication via `get_api_key_for_tradingview()`

#### 2. Frontend (`/templates/pnltracker.html`)
- TradingView Lightweight Charts v5.0.8 for visualization
- DaisyUI components for UI
- Manual refresh control (no auto-refresh)
- Responsive design with mobile support

### Data Flow

```
1. User clicks PnL Tracker in navbar
   ↓
2. Frontend loads and requests PnL data
   ↓
3. Backend fetches:
   - Tradebook (executed trades) 
   - Current positions
   - Historical 1-minute data
   ↓
4. Calculate MTM PnL:
   - For trades: (current_price - executed_price) × quantity
   - For positions: (current_price - average_price) × quantity
   ↓
5. Generate time series data from 9 AM IST
   ↓
6. Return formatted data to frontend
   ↓
7. Display interactive charts
```

## PnL Calculation Logic

### For Executed Trades
```python
# For each trade in tradebook:
if action == 'BUY':
    pnl = (current_price - executed_price) × quantity
else:  # SELL
    pnl = (executed_price - current_price) × quantity
```

### For Open Positions (No Trades)
```python
# When tradebook is empty but positions exist:
if quantity > 0:  # Long position
    pnl = (current_price - average_price) × quantity
else:  # Short position
    pnl = (average_price - current_price) × abs(quantity)
```

### Portfolio MTM
- Individual symbol PnLs are combined into portfolio PnL
- Time-synchronized data using pandas DataFrame joins
- Forward-fill missing data points for continuity

## Timestamp Handling

The system robustly handles different timestamp formats from various brokers:

1. **Unix timestamp (seconds)**: Most common format
2. **Unix timestamp (milliseconds)**: Alternative format
3. **String datetime**: ISO format strings
4. **Timezone handling**: Automatic conversion to IST

### Conversion Function
```python
def convert_timestamp_to_ist(df, symbol=""):
    """
    Attempts multiple timestamp format conversions:
    1. Unix seconds → IST
    2. Unix milliseconds → IST  
    3. String datetime → IST
    4. Returns None if all conversions fail
    """
```

## Error Handling

### Graceful Degradation
- **Missing historical data**: Shows flat PnL line at current value
- **Invalid timestamps**: Falls back to default time range
- **String numeric values**: Automatically converts to float
- **Empty tradebook**: Uses position data if available
- **No data**: Returns zero PnL metrics

### Logging
- Comprehensive logging at INFO, WARNING, and ERROR levels
- Detailed error messages for debugging
- Performance metrics logging

## Data Services Integration

### Tradebook Service
```python
get_tradebook(api_key=api_key)
# Returns: {'status': 'success', 'data': [...trades...]}
```

### History Service
```python
get_history(
    symbol=symbol,
    exchange=exchange,
    interval='1m',
    start_date=today_str,
    end_date=today_str,
    api_key=api_key
)
# Returns: {'status': 'success', 'data': [...candles...]}
```

### Positions API
Dynamic broker-specific imports:
```python
api_funcs = dynamic_import(broker, 'api.order_api', ['get_positions'])
mapping_funcs = dynamic_import(broker, 'mapping.order_data', [
    'map_position_data', 'transform_positions_data'
])
```

## Time Filtering

- **Start Time**: 9:00 AM IST (market open)
- **End Time**: Current time
- **Frequency**: 1-minute intervals
- **Timezone**: Asia/Kolkata (IST)

### Implementation
```python
# Filter to trading hours
today_9am = df_hist.index[0].replace(hour=9, minute=0, second=0, microsecond=0)
current_time = datetime.now(ist)
df_hist = df_hist[df_hist.index >= today_9am]
df_hist = df_hist[df_hist.index <= current_time]
```

## Chart Configuration

### TradingView Lightweight Charts Setup
```javascript
// v5.0 API usage
pnlSeries = chart.addSeries(LightweightCharts.AreaSeries, {
    lineColor: '#570df8',
    topColor: 'rgba(87, 13, 248, 0.4)',
    bottomColor: 'rgba(87, 13, 248, 0.0)',
    lineWidth: 2
});

// Custom IST time formatter
tickMarkFormatter: (time, tickMarkType, locale) => {
    const date = new Date(time * 1000);
    const istOffset = 5.5 * 60 * 60 * 1000; 
    const istDate = new Date(date.getTime() + istOffset);
    return `${hours}:${minutes}`;
}
```

## Performance Optimization

### Manual Refresh Only
- No automatic refresh to reduce server load
- User-initiated refresh via button click
- Prevents unnecessary API calls

### Data Batching
- Single API call fetches all required data
- Parallel processing of multiple symbols
- Efficient pandas operations for calculations

### Caching Strategy
- Session-based authentication caching
- Reuses auth tokens within session
- Minimizes database queries

## Broker Compatibility

### Supported Features by Broker
- All brokers supporting tradebook API
- All brokers supporting 1-minute historical data
- Position tracking across all integrated brokers

### Special Cases
- **MCX/Commodities**: Special quantity calculation when trade_value equals average_price (1 lot)
- **Different timestamp formats**: Automatic detection and conversion
- **Missing data fields**: Graceful fallback to defaults

## Security

### Authentication Flow
1. Session validation via decorator
2. API key retrieval from database
3. Encrypted auth token usage
4. CSRF protection on POST endpoints

### Data Protection
- No sensitive data in frontend
- API keys never exposed to client
- Session-based access control
- Encrypted database storage

## Usage

### Accessing PnL Tracker
1. Login to OpenAlgo
2. Click profile menu in navbar
3. Select "PnL Tracker" (below "Logs")
4. View real-time PnL metrics and charts
5. Click "Refresh" button to update data

### Understanding the Display
- **Green values**: Profit positions
- **Red values**: Loss positions  
- **Purple line**: MTM PnL curve
- **Pink area**: Drawdown from peak

## Troubleshooting

### Common Issues

1. **"No data in TradeBook"**
   - Normal when no trades executed
   - Position PnL will still be displayed if positions exist

2. **Timestamps showing wrong time**
   - Automatic IST conversion handles this
   - Check broker's timestamp format if persistent

3. **Zero values displayed**
   - Verify API key is configured
   - Check if market is open (after 9 AM IST)
   - Ensure positions or trades exist

4. **Chart not loading**
   - Verify lightweight-charts.js is loaded
   - Check browser console for errors
   - Try different theme or refresh page

### Debug Mode
Enable detailed logging:
```python
logger.info(f"Number of trades: {len(trades)}")
logger.info(f"Position {key}: qty={qty}, avg={avg_price}, ltp={ltp}, pnl={pnl}")
logger.info(f"PnL series length: {len(pnl_series)}")
```

## Future Enhancements

### Planned Features
- Historical PnL comparison
- Multi-day PnL tracking
- Export to CSV/Excel
- PnL targets and alerts
- Strategy-wise PnL breakdown
- Risk metrics (Sharpe, Sortino)

### API Extensions
- WebSocket real-time updates
- Batch historical data fetching
- Performance analytics API
- Custom time range selection

## Dependencies

### Python Libraries
- `flask`: Web framework
- `pandas`: Data manipulation
- `numpy`: Numerical operations
- `pytz`: Timezone handling

### Frontend Libraries
- TradingView Lightweight Charts v5.0.8
- DaisyUI v4.12.21
- Tailwind CSS

## Credits

- **TradingView Lightweight Charts**: https://github.com/tradingview/lightweight-charts
- **DaisyUI**: https://github.com/saadeghi/daisyui

## Support

For issues or questions about the PnL Tracker:
1. Check this documentation
2. Review logs in `/logs` directory
3. Join OpenAlgo Discord server
4. Report issues on GitHub