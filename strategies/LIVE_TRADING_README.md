# Live Trading Engine

A high-frequency, multi-symbol live trading system that exactly mirrors the backtesting logic with real-time execution.

## 🏗️ Architecture

### Core Components

1. **LiveTradingEngine** - Main orchestrator
2. **PositionManager** - Handles positions and constraints  
3. **LiveDataManager** - Real-time data and indicators
4. **OrderManager** - Order execution through API
5. **TradingDashboard** - Monitoring interface

### Data Flow

```
TimescaleDB (Historical + Real-time) 
    ↓
LiveDataManager (Indicators) 
    ↓
Symbol Scanner (Entry Signals)
    ↓
PositionManager (Risk Checks)
    ↓
OrderManager (Execution)
    ↓
Position Monitor (Exit Signals)
```

## 🚀 Quick Start

### 1. Setup Environment

```bash
# Set database environment variables
export TIMESCALE_DB_USER="your_user"
export TIMESCALE_DB_PASSWORD="your_password"
export TIMESCALE_DB_HOST="localhost"
export TIMESCALE_DB_PORT="5432"
export TIMESCALE_DB_NAME="your_db"
```

### 2. Configure Symbols

Edit `symbol_list_live.csv` with your trading symbols:
```csv
Symbol
RELIANCE
TCS
INFY
...
```

### 3. Start Live Trading

```bash
# Full live trading
python run_live_trading.py --symbols live

# Test mode with limited symbols
python run_live_trading.py --symbols test --max-symbols 10

# Dry run (no actual orders)
python run_live_trading.py --dry-run --debug
```

### 4. Monitor with Dashboard

```bash
# In separate terminal
python trading_dashboard.py
```

## ⚙️ Configuration

### Trading Hours
- **Market**: 09:15 - 15:30 IST
- **Trading**: 09:20 - 15:20 IST (buffer for startup/shutdown)

### Risk Constraints
- **Max Open Positions**: 3
- **Max Daily Trades**: 5  
- **Max Strategy Use**: 1 per day per strategy
- **Position Size**: 30% of capital per trade

### Scanning Frequency
- **Symbol Scan**: Every 1 second
- **Position Monitor**: Every 2 seconds
- **Status Update**: Every 60 seconds

## 📊 Trading Logic

### Entry Strategies

**15-Minute Timeframe:**
- **Strategy 8**: Short entry on bearish breakout
- **Strategy 12**: Long entry on bullish breakout

**5-Minute Timeframe:**  
- **Strategy 10**: Short entry on bearish momentum
- **Strategy 11**: Long entry on bullish momentum
- **Strategy 9**: Alternative short strategy

### Exit Conditions

1. **Trailing Stop**: ATR-based (1.5x ATR distance)
2. **End of Day**: Force close at 15:20
3. **Manual**: Via position manager

### Indicators Used

- **ATR (14)**: Volatility measurement
- **EMA (50, 100, 200)**: Trend direction  
- **Zero-Lag MACD**: Momentum signals
- **Range Analysis**: Breakout detection
- **Volume Analysis**: Confirmation

## 🔧 Advanced Configuration

### Custom Position Sizing

```python
# In live_config.py
TRADING_CONFIG = {
    'capital': 200000,  # 2 Lakh
    'leverage': 10,     # 10x leverage
    'capital_alloc_pct': 25,  # 25% per trade
}
```

### Risk Management

```python
# Modify constraints
TRADING_CONFIG = {
    'max_positions': 5,      # Allow 5 positions
    'max_daily_trades': 10,  # Allow 10 trades
    'trail_atr_multiple': 2.0,  # Wider trailing stops
}
```

## 📁 File Structure

```
strategies/
├── live_trading_engine.py    # Main engine
├── live_config.py           # Configuration
├── run_live_trading.py      # Startup script
├── trading_dashboard.py     # Monitoring
├── symbol_list_live.csv     # Trading symbols
├── symbol_list_test.csv     # Test symbols
└── LIVE_TRADING_README.md   # This file
```

## 📈 Monitoring

### Real-time Dashboard
- Open positions with P&L
- Today's trade history  
- Constraint status
- System statistics
- Market status

### Log Files
- `live_trading_YYYYMMDD.log` - Daily trading logs
- Real-time position updates
- Entry/exit confirmations
- Error tracking

### Key Metrics
- **Win Rate**: Percentage of profitable trades
- **Daily P&L**: Running profit/loss
- **Position Utilization**: Active vs max positions
- **Strategy Performance**: Per-strategy results

## 🚨 Safety Features

### Pre-trade Validation
- Position limit checks
- Daily trade limits
- Strategy usage limits
- Market hours validation

### Error Handling
- API connection failures
- Database disconnections
- Invalid market data
- Order execution errors

### Emergency Shutdown
- **Ctrl+C**: Graceful shutdown
- **SIGTERM**: Service shutdown
- **Market Close**: Auto position closure

## 🔍 Troubleshooting

### Common Issues

**"No data for symbol"**
```bash
# Check if historical data exists
python -c "
import psycopg2
conn = psycopg2.connect(...)
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM ohlc_15m WHERE symbol = %s', ('RELIANCE',))
print(cursor.fetchone())
"
```

**"API connection failed"**
- Check API key and host configuration
- Verify OpenAlgo server is running
- Check network connectivity

**"Database connection failed"**
- Verify environment variables
- Check TimescaleDB service status
- Validate connection parameters

### Debug Mode

```bash
python run_live_trading.py --debug --dry-run
```

This enables:
- Detailed logging
- No actual orders
- Step-by-step execution traces

## 📋 Production Checklist

### Before Going Live

- [ ] Test with paper trading
- [ ] Verify API connectivity  
- [ ] Check position sizing calculations
- [ ] Validate risk constraints
- [ ] Test emergency shutdown
- [ ] Monitor resource usage
- [ ] Set up alerting

### Daily Operations

- [ ] Check market calendar
- [ ] Verify system resources
- [ ] Review previous day's performance
- [ ] Monitor log files
- [ ] Check data quality
- [ ] Validate positions at EOD

## 🆘 Support

### Logs Location
- Main logs: `live_trading_YYYYMMDD.log`
- Error logs: Check console output
- Position logs: Within main log file

### Performance Metrics
- Memory usage: Monitor via dashboard
- CPU usage: Check system stats
- Scan latency: Review debug logs

### Emergency Contacts
- Trading desk: [Your contact]
- Technical support: [Your contact]
- Risk management: [Your contact]

---

**⚠️ Important**: This is a live trading system. Always test thoroughly before deploying with real money. Past performance does not guarantee future results.
