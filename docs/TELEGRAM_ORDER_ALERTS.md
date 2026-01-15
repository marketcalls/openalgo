# Telegram Order Alerts

## Overview
The OpenAlgo platform now supports automatic Telegram notifications for all order-related API calls. When users place, modify, cancel orders or manage positions through the API, they will receive real-time alerts on Telegram.

## Features

### Supported Order Types
- **Place Order** - Regular order placement
- **Place Smart Order** - Smart orders with position sizing
- **Basket Order** - Multiple orders in one request
- **Split Order** - Large orders split into smaller chunks
- **Modify Order** - Order modifications
- **Cancel Order** - Single order cancellation
- **Cancel All Orders** - Bulk order cancellation
- **Close Position** - Position closing

### Alert Modes
The system differentiates between:
- **LIVE MODE** (💰) - Real orders executed with the broker
- **ANALYZE MODE** (🔬) - Simulated orders for testing/analysis

## How It Works

### Architecture
1. **Asynchronous Processing**: Alerts are sent asynchronously using thread pools, ensuring order execution speed is not affected
2. **Non-blocking**: Telegram notifications never block or slow down order processing
3. **Queue System**: If the Telegram bot is offline, notifications are queued for later delivery
4. **Modular Design**: The alert service is completely separate from order processing logic

### Message Format
Each alert contains:
- Mode indicator (LIVE or ANALYZE)
- Order details (symbol, action, quantity, price, etc.)
- Order status (success/failure)
- Order ID for tracking
- Timestamp
- Strategy name (if provided)

## Setup

### Prerequisites
1. Telegram bot must be configured and running
2. Users must link their OpenAlgo account with Telegram

### User Setup
1. Start the Telegram bot from the web interface: `/telegram/bot/start`
2. In Telegram, message the bot and use `/start`
3. Link your account: `/link <api_key> <host_url>`
4. Notifications are now enabled

### Configuration
- Alerts are enabled by default for linked users
- Users can enable/disable notifications in their preferences
- Rate limiting is applied to prevent spam

## Technical Implementation

### Service Module
`services/telegram_alert_service.py`
- Handles all alert formatting and sending
- Manages async operations
- Provides fallback mechanisms

### Integration Points
All order services have been updated:
- `place_order_service.py`
- `place_smart_order_service.py`
- `basket_order_service.py`
- `split_order_service.py`
- `modify_order_service.py`
- `cancel_order_service.py`
- `cancel_all_order_service.py`
- `close_position_service.py`

### Database
- Notifications are logged in the database
- Failed notifications are queued for retry
- User preferences are stored and respected

## Testing

Run the test script to verify the implementation:
```bash
python test/test_telegram_alerts.py
```

## Performance

### Impact on Order Execution
- **Zero latency added** to order processing
- Alerts are sent in parallel threads
- Order confirmation is returned immediately
- Telegram sending happens in background

### Scalability
- Thread pool handles concurrent alerts
- Queue system prevents message loss
- Automatic retry for failed deliveries

## Security
- API keys are never sent in Telegram messages
- User authentication required for alerts
- Messages are sent only to linked accounts
- Encrypted storage of user credentials

## Troubleshooting

### Alerts Not Received
1. Check if Telegram bot is running: `/telegram/bot/status`
2. Verify account is linked: Check in `/telegram/users`
3. Ensure notifications are enabled in preferences
4. Check bot logs for errors

### Bot Connection Issues
1. Verify bot token is correct
2. Check network connectivity
3. Ensure Telegram API is accessible
4. Review error logs in `/telegram/analytics`

## API Examples

When you place an order via the API:
```python
response = client.placeorder(
    strategy="MyStrategy",
    symbol="RELIANCE",
    action="BUY",
    exchange="NSE",
    price_type="MARKET",
    product="MIS",
    quantity=10
)
```

You'll receive a Telegram alert:
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

For analyze mode:
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

## Benefits

1. **Real-time Updates**: Instant notifications on order status
2. **Mobile Access**: Get alerts anywhere via Telegram
3. **Audit Trail**: All orders are logged with timestamps
4. **Error Alerts**: Immediate notification of failed orders
5. **Mode Awareness**: Clear distinction between live and test orders
6. **Multi-user Support**: Each user gets their own alerts

## Future Enhancements

Potential improvements:
- Customizable alert templates
- Alert filtering by strategy/symbol
- Daily summary reports
- P&L notifications
- Risk alerts
- Market data alerts