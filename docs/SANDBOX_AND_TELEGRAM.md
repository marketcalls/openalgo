# Sandbox Mode and Telegram Bot - Feature Overview

## Introduction

This document provides an overview of two major features in OpenAlgo:
1. **Sandbox Mode (API Analyzer)** - Simulated trading environment
2. **Telegram Bot Integration** - Mobile trading interface

## Sandbox Mode (API Analyzer)

### What is Sandbox Mode?

Sandbox Mode, also known as API Analyzer, is a complete simulated trading environment that allows traders to test strategies, validate algorithms, and practice trading with realistic market data without risking real capital.

### Key Features

#### 1. Simulated Capital
- Start with ₹1 Crore (10 million) in sandbox funds
- Automatic reset every Sunday at 00:00 IST
- Manual reset available from settings

#### 2. Realistic Execution
- Orders execute at real-time LTP (Last Traded Price)
- LIMIT orders execute when LTP crosses limit price
- SL/SL-M orders trigger and execute at LTP
- No artificial slippage or delays

#### 3. Complete Order Support
- **MARKET**: Immediate execution at LTP
- **LIMIT**: Execute when price condition met
- **SL**: Stop Loss with limit price
- **SL-M**: Stop Loss Market

#### 4. Accurate Margin System
- Leverage-based margin blocking
- Order-type specific price selection for margin
- Instrument type detection via symbol suffix
- Margin release on cancellation/closure

**Leverage Rules**:
- Equity MIS: 5x leverage (20% margin)
- Equity CNC: 1x leverage (100% margin)
- Futures: 10x leverage (10% margin)
- Options BUY: Full premium required
- Options SELL: Futures equivalent margin

#### 5. Auto Square-Off System
Exchange-specific automatic position closure:
- NSE/BSE/NFO/BFO: 3:15 PM IST
- CDS/BCD: 4:45 PM IST
- MCX: 11:30 PM IST
- NCDEX: 5:00 PM IST

Implemented using APScheduler with:
- Separate background thread
- Cron jobs in IST timezone
- Dynamic configuration reload
- Status monitoring endpoints

#### 6. Complete Isolation
- Separate database: `db/sandbox.db`
- Own configuration table
- Independent background threads
- No impact on live trading

### Architecture Highlights

**Components**:
1. **Analyzer Service** - Mode toggle and status
2. **Order Manager** - Order placement, validation, margin blocking
3. **Execution Engine** - Background thread checking pending orders
4. **Squareoff Scheduler** - APScheduler for auto square-off
5. **Position Manager** - Position updates, P&L calculations
6. **Fund Manager** - Margin calculations, leverage rules

**Thread Management**:
- **Main Thread**: Flask application
- **Execution Thread**: Checks pending orders every 5 seconds
- **Squareoff Thread**: APScheduler with exchange-specific cron jobs

**Database Tables**:
- `sandbox_orders` - Order records with margin_blocked field
- `sandbox_trades` - Executed trade history
- `sandbox_positions` - Current positions
- `sandbox_holdings` - T+1 settled holdings
- `sandbox_funds` - Capital and margin tracking
- `sandbox_config` - 18 configuration entries

### Margin Handling

#### Margin Blocking Logic

**When is Margin Blocked?**
- ALL BUY orders
- SELL orders for options (option writing)
- SELL orders for futures (short selling)
- SELL orders for equity in MIS/NRML (short selling)

**Price Selection for Margin**:
- MARKET orders: Use current LTP
- LIMIT orders: Use order's limit price
- SL/SL-M orders: Use trigger price

**Example - LIMIT Order**:
```python
Order: BUY 1000 YESBANK @ ₹22 (LIMIT, MIS)
Current LTP: ₹21.40

Margin Calculation:
- Price Used: ₹22.00 (limit price, NOT LTP)
- Trade Value: 1000 × ₹22 = ₹22,000
- Leverage: 5x
- Margin: ₹22,000 ÷ 5 = ₹4,400

✅ Ensures sufficient margin even if order executes at limit price
```

#### Margin Release

Margin is automatically released when:

1. **Order Cancellation**
   - Full margin returned to available balance
   - Updates: available_balance += margin_blocked
   - Updates: used_margin -= margin_blocked

2. **Position Closure**
   - Margin released from closed position
   - Realized P&L calculated and added to funds
   - Updates: available_balance += margin_released

3. **Auto Square-Off**
   - All MIS positions closed at square-off time
   - Margins released for all closed positions
   - Realized P&L updated

4. **Partial Position Reduction**
   - Proportional margin released
   - Partial realized P&L calculated
   - Remaining position retains adjusted margin

**Example - Position Closure**:
```python
Position: Long 100 RELIANCE @ ₹1,200 (MIS)
Margin Blocked: ₹24,000

SELL 100 RELIANCE @ ₹1,250:
- Position closes (qty becomes 0)
- Margin Released: ₹24,000
- Realized P&L: (₹1,250 - ₹1,200) × 100 = ₹5,000
- Available Balance: +₹24,000 + ₹5,000 = +₹29,000

✅ Full margin returned plus profit
```

### Recent Updates (v1.0.4)

**October 2025**:
1. ✅ Fixed margin blocking for LIMIT, SL, and SL-M orders
2. ✅ Implemented margin release on order cancellation
3. ✅ Enhanced execution to use LTP for realistic fills
4. ✅ Added instrument type detection via symbol suffix
5. ✅ Implemented auto square-off with APScheduler
6. ✅ Moved sandbox.db to /db directory
7. ✅ Created comprehensive migration system
8. ✅ Added 18 default configuration entries

### Getting Started

#### Enable Sandbox Mode

**Via API**:
```python
from services.analyzer_service import toggle_analyzer_mode

analyzer_data = {"mode": True}
success, response, status_code = toggle_analyzer_mode(
    analyzer_data=analyzer_data,
    api_key='your_api_key'
)
```

**Via Web UI**:
- Navigate to settings
- Toggle "Analyzer Mode" switch
- Background threads start automatically

#### Place First Order

```python
order_data = {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 100,
    "price_type": "MARKET",
    "product": "MIS"
}

# Place order
from services.sandbox_service import sandbox_place_order

success, response, code = sandbox_place_order(
    order_data=order_data,
    api_key='your_api_key'
)

# Response includes orderid and margin_blocked
print(f"Order ID: {response['orderid']}")
print(f"Margin Blocked: ₹{response['margin_blocked']}")
```

### Documentation

**Complete Documentation**: See `docs/sandbox/` folder

1. **[README.md](sandbox/README.md)** - Overview and quick start
2. **[04_margin_system.md](sandbox/04_margin_system.md)** - Complete margin handling guide
3. **[07_architecture.md](sandbox/07_architecture.md)** - System architecture and components

**Design Documentation**: See `design/14_sandbox_architecture.md`

---

## Telegram Bot Integration

### What is Telegram Bot?

The Telegram Bot provides a secure, mobile-friendly interface for traders to monitor and interact with their OpenAlgo accounts through Telegram messaging app.

### Key Features

#### 1. Account Management
- `/start` - Initialize bot
- `/link` - Link OpenAlgo account
- `/unlink` - Remove account
- `/status` - Check connection

#### 2. Trading Data Access
- `/orderbook` - View all orders
- `/tradebook` - View executed trades
- `/positions` - View open positions with P&L
- `/holdings` - View portfolio holdings
- `/funds` - View available funds
- `/pnl` - Comprehensive P&L summary

#### 3. Market Data
- `/quote <symbol>` - Real-time quotes
- `/chart <symbol>` - Generate and share charts

#### 4. Interactive Interface
- `/menu` - Button-based navigation
- `/help` - Comprehensive help

### Architecture Highlights

**Components**:
1. **TelegramBotService** - Central service (~1400 lines)
2. **Database Layer** - User data, config, logs
3. **Command System** - Handler functions for each command
4. **Chart Generator** - Plotly-based chart generation
5. **Web Management** - Dashboard at `/telegram`

**Security**:
- Fernet encryption for API keys
- Encrypted bot token storage
- User isolation and access control
- Complete audit trail via command logs

**Database Tables**:
- `telegram_users` - User accounts with encrypted credentials
- `bot_config` - Bot configuration and token
- `command_logs` - Complete command history for analytics

### Recent Updates (September 2025)

1. ✅ Enhanced shutdown process with synchronous stop method
2. ✅ Optimized logging levels (sensitive data moved to debug)
3. ✅ Improved message formatting for orders/trades/positions
4. ✅ Better symbol subscription logging

### Chart Generation

**Types**:
- **Intraday**: 5-minute candles, last 5 days
- **Daily**: Daily candles, last 252 trading days
- **Both**: Combined view

**Features**:
- Candlestick patterns
- Volume bars
- Moving averages (MA20, MA50, MA200)
- VWAP indicator
- Support/Resistance levels

**Example**:
```
/chart RELIANCE NSE intraday 5 5
```

### Web Management Dashboard

**Routes** (at `/telegram`):
- `/telegram/` - Main dashboard
- `/telegram/config` - Bot configuration
- `/telegram/users` - User management
- `/telegram/analytics` - Command analytics
- `/telegram/start` - Start bot
- `/telegram/stop` - Stop bot
- `/telegram/restart` - Restart bot

### Getting Started

#### 1. Create Bot
- Message @BotFather on Telegram
- Use `/newbot` command
- Save bot token

#### 2. Configure OpenAlgo
- Navigate to `/telegram` in web UI
- Enter bot token
- Click "Save Configuration"
- Click "Start Bot"

#### 3. Link Account
In Telegram, message your bot:
```
/link YOUR_API_KEY http://your-openalgo-host:5000
```

#### 4. Start Using
```
/menu        - Interactive menu
/positions   - Check positions
/quote RELIANCE NSE  - Get quotes
/chart NIFTY NSE     - Generate chart
```

### Documentation

**Complete Documentation**: See `design/13_telegram_bot_integration.md`

**Telegram Setup Guide**: See `docs/TELEGRAM_SETUP.md`

---

## Integration Between Features

### Sandbox + Telegram

Telegram bot works seamlessly with Sandbox Mode:

1. **Enable Sandbox Mode** via web UI or API
2. **Link Telegram** account with OpenAlgo API key
3. **View Sandbox Data** through Telegram:
   - `/positions` shows sandbox positions
   - `/funds` shows sandbox funds (₹1 Crore)
   - `/orderbook` shows sandbox orders

**Benefits**:
- Test strategies in sandbox
- Monitor via Telegram
- Mobile-friendly interface
- Real-time updates on phone

### Example Workflow

```python
# Step 1: Enable Sandbox Mode
toggle_analyzer_mode({'mode': True}, api_key)

# Step 2: Link Telegram (in Telegram app)
/link YOUR_API_KEY http://localhost:5000

# Step 3: Place test order (via API or web)
place_order({
    'symbol': 'RELIANCE',
    'action': 'BUY',
    'quantity': 100,
    'price_type': 'MARKET',
    'product': 'MIS'
})

# Step 4: Monitor on Telegram
/positions
# Shows: RELIANCE MIS +100 @ ₹1,187.50
# P&L updated in real-time

# Step 5: Get chart
/chart RELIANCE NSE
# Receives intraday chart with position marked

# Step 6: Close position
# (Via API or web)

# Step 7: Check P&L on Telegram
/pnl
# Shows: Total Realized P&L from sandbox
```

---

## Performance Metrics

### Sandbox Mode

| Operation | Target | Actual |
|-----------|--------|--------|
| Place Order | < 100ms | ~50ms |
| Get Positions | < 200ms | ~120ms |
| Execution Check | < 5s | ~3s |
| Square-off | < 30s | ~15s |

**Scalability**:
- Supports 100+ concurrent users
- Handles 1000+ orders per user
- Background thread processes 10 orders/second
- Database connection pooling (10-20 connections)

### Telegram Bot

| Command Type | Target | Actual |
|-------------|--------|--------|
| Simple (/help, /status) | < 100ms | 45ms |
| Data Queries (/positions) | < 500ms | 320ms |
| Chart Generation | < 3000ms | 2100ms |
| Complex Analytics | < 5000ms | 3800ms |

**Scalability**:
- Supports 100+ concurrent users
- Handles 50+ messages per second
- Memory: ~150MB base + 5MB per active user
- CPU: < 5% idle, < 20% under load

---

## Configuration

### Sandbox Configuration

**Location**: `/sandbox` settings page or `sandbox_config` table

**Key Settings**:
```python
{
    'starting_capital': '10000000.00',          # ₹1 Crore
    'reset_day': 'Sunday',                      # Weekly reset
    'reset_time': '00:00',                      # Midnight IST
    'order_check_interval': '5',               # Seconds
    'nse_bse_square_off_time': '15:15',        # 3:15 PM IST
    'equity_mis_leverage': '5',                # 5x leverage
    'futures_leverage': '10',                  # 10x leverage
    'order_rate_limit': '10',                  # Orders per second
    'api_rate_limit': '50',                    # API calls per second
}
```

### Telegram Configuration

**Location**: `/telegram` settings page or `bot_config` table

**Environment Variables**:
```bash
TELEGRAM_BOT_TOKEN=encrypted_token
TELEGRAM_WEBHOOK_URL=https://yourdomain.com/telegram/webhook
TELEGRAM_POLLING_MODE=true
TELEGRAM_AUTO_START=true
TELEGRAM_ENCRYPTION_KEY=generated_fernet_key
TELEGRAM_RATE_LIMIT=60  # requests per minute
```

---

## Troubleshooting

### Sandbox Mode

**Issue**: Orders not executing
- ✓ Check if execution thread is running
- ✓ Verify LTP is crossing limit/trigger price
- ✓ Check sufficient funds available

**Issue**: Auto square-off not working
- ✓ Verify exchange-wise timings in config
- ✓ Check if squareoff scheduler is running
- ✓ Review logs for execution errors

**Issue**: Margin not released on cancellation
- ✓ Check order.margin_blocked value
- ✓ Verify funds.used_margin decreased
- ✓ Review order cancellation logs

### Telegram Bot

**Issue**: Bot not responding
- ✓ Check bot is started in `/telegram`
- ✓ Verify bot token is correct
- ✓ Check bot thread is running
- ✓ Review bot logs for errors

**Issue**: Commands returning errors
- ✓ Verify account is linked (`/status`)
- ✓ Check API key is valid
- ✓ Ensure host URL is accessible
- ✓ Review command logs

---

## Security Considerations

### Sandbox Mode

1. **Data Isolation**
   - Separate database (`db/sandbox.db`)
   - No shared tables with live trading
   - User-scoped queries

2. **Rate Limiting**
   - Order: 10 per second
   - Smart orders: 2 per second
   - API calls: 50 per second

3. **Validation**
   - Symbol validation
   - Quantity/price validation
   - Sufficient funds check

### Telegram Bot

1. **Encryption**
   - API keys encrypted at rest (Fernet)
   - Bot token encrypted
   - Secure key storage

2. **User Isolation**
   - User-specific data access
   - Command authentication
   - Audit trail logging

3. **Rate Limiting**
   - 60 requests per minute per user
   - Prevention of API abuse

---

## Monitoring and Maintenance

### Health Checks

**Sandbox**:
```python
def check_sandbox_health():
    return {
        'execution_thread': is_execution_running(),
        'squareoff_scheduler': is_squareoff_running(),
        'database_connection': test_db_connection(),
        'pending_orders_count': get_pending_orders_count()
    }
```

**Telegram**:
```python
def check_telegram_health():
    return {
        'bot_running': is_bot_running(),
        'active_users': get_active_users_count(),
        'commands_processed': get_commands_count_today(),
        'average_response_time': get_avg_response_time()
    }
```

### Log Monitoring

```bash
# Sandbox logs
tail -f logs/sandbox.log | grep ERROR

# Telegram logs
tail -f logs/telegram_bot.log | grep ERROR

# Monitor execution thread
grep "Execution thread" logs/sandbox.log

# Monitor squareoff
grep "Square-off" logs/sandbox.log
```

---

## Future Enhancements

### Sandbox Mode

**Short Term**:
- Enhanced MTM with auto-update
- Basket orders support
- Order modification

**Long Term**:
- Backtesting integration
- Strategy performance analytics
- Machine learning insights

### Telegram Bot

**Short Term**:
- Real-time price alerts
- Order placement via Telegram
- Portfolio analytics

**Long Term**:
- Multi-account support
- Trade journal integration
- AI-powered insights

---

## Conclusion

Sandbox Mode and Telegram Bot are powerful features that enhance the OpenAlgo platform:

**Sandbox Mode** provides:
- Safe strategy testing
- Realistic execution simulation
- Accurate margin mechanics
- Complete order lifecycle
- Automatic position management

**Telegram Bot** provides:
- Mobile trading interface
- Real-time monitoring
- Secure account access
- Chart generation
- Comprehensive analytics

Together, they enable traders to:
1. Test strategies safely in sandbox
2. Monitor progress via Telegram
3. Build confidence before live trading
4. Access trading data anywhere
5. Make informed decisions quickly

---

## Additional Resources

### Documentation
- **Sandbox**: `docs/sandbox/` folder
- **Telegram**: `design/13_telegram_bot_integration.md`
- **Design**: `design/14_sandbox_architecture.md`

### Setup Guides
- **Sandbox Migration**: `upgrade/migrate_sandbox.py`
- **Telegram Setup**: `docs/TELEGRAM_SETUP.md`

### API References
- **Sandbox Service**: `services/sandbox_service.py`
- **Analyzer Service**: `services/analyzer_service.py`
- **Telegram Service**: `services/telegram_bot_service.py`

### Support
- **GitHub Issues**: Report bugs and request features
- **Community**: Join discussions
- **Documentation**: Read detailed guides

---

**Version**: 1.0.4
**Last Updated**: October 2025
**Status**: Production Ready
