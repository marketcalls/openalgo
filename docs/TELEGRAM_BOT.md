# OpenAlgo Telegram Bot Documentation

## Overview

The OpenAlgo Telegram Bot provides a comprehensive interface to access your trading data and receive real-time order notifications through Telegram. It offers both read-only access to your trading account and automatic alerts for all order-related activities, allowing you to view positions, orders, holdings, P&L, generate charts, and stay updated on your trading activities directly from your Telegram app.

## Features

- **Account Linking**: Securely link your OpenAlgo account using API keys
- **Real-time Data Access**: View orderbook, tradebook, positions, holdings, and funds
- **Automatic Order Alerts**: Receive instant notifications for all order activities
- **P&L Tracking**: Monitor realized and unrealized profit/loss
- **Quote Information**: Get real-time quotes for any symbol
- **Chart Generation**: Generate intraday and daily charts with technical indicators
- **Interactive Menu**: Easy-to-use button interface for quick access
- **Mode Differentiation**: Clear distinction between LIVE and ANALYZE mode orders

## Setup

For detailed setup instructions, please refer to the official OpenAlgo documentation:
[**📚 Telegram Bot Setup Guide**](https://docs.openalgo.in/trading-platform/telegram)

### Quick Setup Steps

1. **Create Bot**: Get a bot token from [@BotFather](https://t.me/botfather) on Telegram
2. **Configure**: Enter the bot token in OpenAlgo's Telegram configuration
3. **Start Bot**: Click "Start Bot" in the dashboard
4. **Link Account**: Send `/link your_api_key host_url` to your bot on Telegram

## Available Commands

### Account Management

- `/start` - Initialize the bot and see welcome message
- `/link <api_key> <host_url>` - Link your OpenAlgo account
- `/unlink` - Unlink your account
- `/status` - Check connection status

### Trading Data

- `/orderbook` - View all orders
- `/tradebook` - View executed trades
- `/positions` - View open positions
- `/holdings` - View holdings
- `/funds` - View available funds
- `/pnl` - View profit & loss summary

### Market Data

- `/quote <symbol> [exchange]` - Get quote for a symbol
  - Example: `/quote RELIANCE`
  - Example: `/quote NIFTY NSE_INDEX`

### Charts

- `/chart <symbol> [exchange] [type] [interval] [days]` - Generate price charts
  - Type: `intraday` (default), `daily`, or `both`
  - Intervals: `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `D`
  - Examples:
    - `/chart RELIANCE` - 5-minute intraday chart
    - `/chart RELIANCE NSE intraday 15m 10` - 15-minute chart for 10 days
    - `/chart RELIANCE NSE daily D 100` - Daily chart for 100 days
    - `/chart RELIANCE NSE both` - Both intraday and daily charts

### Interactive Interface

- `/menu` - Display interactive button menu
- `/help` - Show help message with all commands

## Order Alerts (Automatic Notifications)

### Overview
The bot automatically sends real-time notifications for all order-related API activities. No additional commands are needed - alerts are sent automatically when orders are placed through the OpenAlgo API.

### Supported Order Types
- **Place Order** - Regular order placement notifications
- **Place Smart Order** - Smart orders with position sizing alerts
- **Basket Order** - Multiple orders in one request notifications
- **Split Order** - Large orders split into smaller chunks alerts
- **Modify Order** - Order modification notifications
- **Cancel Order** - Single order cancellation alerts
- **Cancel All Orders** - Bulk order cancellation notifications
- **Close Position** - Position closing alerts

### Alert Format
Each alert includes:
- **Mode Indicator**:
  - 💰 **LIVE MODE** - Real orders executed with the broker
  - 🔬 **ANALYZE MODE** - Simulated orders for testing/analysis
- **Order Details**: Symbol, action, quantity, price, exchange, product type
- **Status**: Success or failure with error messages if applicable
- **Order ID**: Unique identifier for tracking
- **Timestamp**: Time of order execution
- **Strategy Name**: If provided in the API call

### Example Notifications

#### Live Order Placed:
```
📈 Order Placed
💰 LIVE MODE - Real Order
─────────────────────
Strategy: MyStrategy
Symbol: RELIANCE
Action: BUY
Quantity: 10
Price Type: MARKET
Exchange: NSE
Product: MIS
Order ID: 250408000989443
⏰ Time: 14:23:45
```

#### Analyze Mode Order:
```
📈 Order Placed
🔬 ANALYZE MODE - No Real Order
─────────────────────
Strategy: TestStrategy
Symbol: RELIANCE
Action: BUY
Quantity: 10
Price Type: MARKET
Exchange: NSE
Product: MIS
Order ID: ANALYZE123456
⏰ Time: 14:23:45
```

### Configuration
- Alerts are **enabled by default** for all linked users
- Users can enable/disable notifications in their preferences
- Failed alerts are queued for retry when the bot comes online
- Zero impact on order execution speed (asynchronous processing)

### Requirements for Receiving Alerts
1. Telegram bot must be running (`/telegram/bot/start` in web interface)
2. Your account must be linked via `/link` command
3. Notifications must be enabled (default: enabled)
4. Orders must be placed through the OpenAlgo API

## Chart Features

### Intraday Charts
- Default interval: 5 minutes
- Default period: 5 days
- Includes candlestick pattern and volume bars
- No gaps for non-trading hours

### Daily Charts
- Default interval: Daily (D)
- Default period: 252 trading days
- Includes moving averages (MA20, MA50, MA200)
- Shows candlestick patterns with volume

### Chart Customization
- **Intervals**: 1m, 3m, 5m, 15m, 30m, 1h for intraday; D for daily
- **Days**: Customize the lookback period
- **Exchange**: Supports NSE, BSE, NFO, CDS, MCX, NSE_INDEX, BSE_INDEX

## Security

### API Key Encryption
- API keys are encrypted using Fernet encryption before storage
- Keys are never stored in plain text
- Each user's API key is isolated

### Authentication
- Bot requires valid API key for account linking
- API key is validated against OpenAlgo server
- Session-based authentication for all data requests

### Privacy
- Each Telegram user can only access their own linked account
- No cross-user data access
- Command usage is logged for security audit

## Database Schema

The bot uses SQLAlchemy ORM with the following tables:

### TelegramUser
- Stores user-bot linkage information
- Encrypted API key storage
- User preferences and settings
- Notification enable/disable flag

### BotConfig
- Bot configuration settings
- Webhook URL and polling mode
- Bot state management
- Broadcast enable/disable settings

### CommandLog
- Audit trail of all commands
- Usage analytics
- Error tracking

### NotificationQueue
- Stores pending notifications for delivery
- Priority-based queue system
- Retry mechanism for failed messages
- Delivery status tracking

### UserPreference
- Individual user notification preferences
- Order type specific settings
- Daily summary configuration
- Timezone and language settings

## Technical Architecture

### Components

1. **TelegramBotService** (`services/telegram_bot_service.py`)
   - Core bot logic and command handlers
   - OpenAlgo SDK integration
   - Chart generation using Plotly

2. **TelegramAlertService** (`services/telegram_alert_service.py`)
   - Automatic order notification system
   - Asynchronous alert processing
   - Message formatting and queuing
   - Mode differentiation (LIVE vs ANALYZE)

3. **Database Layer** (`database/telegram_db.py`)
   - SQLAlchemy models and queries
   - Encryption/decryption utilities
   - Configuration management
   - Notification queue for failed messages

4. **Blueprint** (`blueprints/telegram.py`)
   - Flask routes for bot management
   - Web interface for configuration
   - Bot lifecycle management

5. **Auto-start Feature**
   - Bot automatically starts on application launch if previously active
   - State persistence across restarts
   - Configured in `app.py`

6. **Order Service Integration**
   - All order services automatically trigger alerts
   - Non-blocking execution using thread pools
   - Zero latency impact on order processing

### Threading Model
- Bot runs in a separate thread with its own event loop
- Non-blocking operation with main Flask application
- Graceful shutdown handling

### Chart Generation
- Uses Plotly for chart creation
- Kaleido engine for image export
- Pandas for data manipulation
- Category-type x-axis to handle gaps

## Troubleshooting

### Bot Not Responding
1. Check if bot is running in OpenAlgo dashboard
2. Verify bot token is correct
3. Check network connectivity
4. Review logs for errors

### Order Alerts Not Received
1. **Check Username Match**: Ensure your Telegram linked username matches your OpenAlgo auth username
2. **Verify Bot Status**: Confirm bot is running in `/telegram/bot/status`
3. **Check Notifications**: Ensure notifications are enabled in user preferences
4. **Review Logs**: Look for "Telegram alert triggered" messages in logs
5. **Test Connection**: Send a test message from `/telegram` dashboard
6. **Mode Check**: Verify if orders are in LIVE or ANALYZE mode

### Chart Generation Issues
1. Ensure market data is available for the symbol
2. Check if the exchange is correct
3. Verify interval is supported
4. Check date range is valid

### Linking Issues
1. Verify API key is correct
2. Ensure host URL is accessible
3. Check if API key has necessary permissions
4. Verify OpenAlgo server is running
5. **Username Format**: Ensure consistent username format (without @ prefix)

## Environment Variables

The bot respects the following environment variables:

- `DATABASE_URL` - Database connection string
- `ENCRYPTION_KEY` - Fernet encryption key for API keys
- `APP_KEY` - Flask application secret key
- `HOST_SERVER` - OpenAlgo server URL

## API Endpoints

### Web Interface
- `GET /telegram/` - Bot management dashboard
- `POST /telegram/config` - Update bot configuration
- `POST /telegram/start` - Start the bot
- `POST /telegram/stop` - Stop the bot
- `POST /telegram/restart` - Restart the bot

## Error Handling

- All errors are logged with context
- User-friendly error messages in Telegram
- Automatic retry for transient failures
- Graceful degradation for missing data

## Performance Considerations

- Charts are generated asynchronously
- API calls use connection pooling
- Database queries are optimized with indexes
- Image generation uses efficient Kaleido backend
- **Order alerts use thread pools for zero-latency execution**
- **Notification queue prevents message loss during downtime**
- **Async processing ensures order execution is never blocked**

## Future Enhancements

- [x] ~~Real-time order alerts~~ ✅ **Implemented**
- [ ] Real-time price alerts
- [ ] Portfolio analytics
- [ ] Multi-account support
- [ ] Custom indicators on charts
- [ ] Webhook mode for better scalability
- [ ] Inline queries for quick quotes
- [ ] Customizable alert templates
- [ ] Alert filtering by strategy/symbol
- [ ] Daily P&L summary reports

## Support

For issues or questions:
1. Check the logs in OpenAlgo dashboard
2. Review this documentation
3. Contact OpenAlgo support