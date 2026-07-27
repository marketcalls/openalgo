# 43 - Telegram Bot Configuration

## Overview

OpenAlgo integrates with Telegram to provide real-time trading notifications, account information, and bot commands. Users can configure their Telegram bot to receive order alerts, position updates, and execute queries.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                       Telegram Bot Architecture                              │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           Telegram Cloud                                     │
│                                                                              │
│  ┌─────────────────┐              ┌─────────────────┐                       │
│  │  User's         │              │   Bot Father    │                       │
│  │  Telegram App   │              │   @BotFather    │                       │
│  └────────┬────────┘              └────────┬────────┘                       │
│           │                                │                                 │
│           │  Messages/Commands             │  Create Bot Token              │
│           │                                │                                 │
│           └────────────────┬───────────────┘                                │
│                            │                                                 │
│                    Bot API Gateway                                          │
│                            │                                                 │
└────────────────────────────┼────────────────────────────────────────────────┘
                             │
                             │ Webhook / Long Polling
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        OpenAlgo Backend                                      │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Telegram Blueprint                                │   │
│  │                    /telegram/*                                       │   │
│  │                                                                      │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ /settings    │  │ /webhook     │  │ /test        │              │   │
│  │  │ Configure    │  │ Receive      │  │ Send test    │              │   │
│  │  │ bot token    │  │ updates      │  │ message      │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Telegram Service                                  │   │
│  │                                                                      │   │
│  │  ┌──────────────────────────────────────────────────────────────┐  │   │
│  │  │  Command Handler                                              │  │   │
│  │  │                                                               │  │   │
│  │  │  /start    - Initialize bot                                   │  │   │
│  │  │  /help     - Show commands                                    │  │   │
│  │  │  /funds    - Account balance                                  │  │   │
│  │  │  /positions- Open positions                                   │  │   │
│  │  │  /orders   - Order book                                       │  │   │
│  │  │  /holdings - Portfolio holdings                               │  │   │
│  │  │  /trades   - Trade book                                       │  │   │
│  │  │  /pnl      - P&L summary                                      │  │   │
│  │  │  /quote    - Get LTP                                          │  │   │
│  │  │  /status   - Connection status                                │  │   │
│  │  │  /alerts   - Toggle alerts                                    │  │   │
│  │  │  /settings - Preferences                                      │  │   │
│  │  │  /logout   - Disconnect                                       │  │   │
│  │  └──────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Database Layer                                    │   │
│  │                                                                      │   │
│  │  telegram_users │ bot_config │ command_log │ notification_queue     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Database Schema

### telegram_users Table

```
┌────────────────────────────────────────────────────────────────┐
│                    telegram_users table                         │
├──────────────────┬──────────────┬──────────────────────────────┤
│ Column           │ Type         │ Description                  │
├──────────────────┼──────────────┼──────────────────────────────┤
│ id               │ INTEGER PK   │ Auto-increment               │
│ user_id          │ VARCHAR(255) │ OpenAlgo user ID             │
│ telegram_id      │ BIGINT       │ Telegram chat ID             │
│ username         │ VARCHAR(255) │ Telegram username            │
│ first_name       │ VARCHAR(255) │ User's first name            │
│ is_active        │ BOOLEAN      │ Bot active status            │
│ linked_at        │ DATETIME     │ When linked                  │
│ last_activity    │ DATETIME     │ Last command time            │
└──────────────────┴──────────────┴──────────────────────────────┘
```

### bot_config Table

```
┌────────────────────────────────────────────────────────────────┐
│                      bot_config table                           │
├──────────────────┬──────────────┬──────────────────────────────┤
│ Column           │ Type         │ Description                  │
├──────────────────┼──────────────┼──────────────────────────────┤
│ id               │ INTEGER PK   │ Auto-increment               │
│ user_id          │ VARCHAR(255) │ OpenAlgo user ID (unique)    │
│ bot_token        │ TEXT         │ Encrypted bot token          │
│ webhook_url      │ VARCHAR(500) │ Webhook endpoint             │
│ is_enabled       │ BOOLEAN      │ Bot enabled status           │
│ created_at       │ DATETIME     │ Configuration created        │
│ updated_at       │ DATETIME     │ Last modified                │
└──────────────────┴──────────────┴──────────────────────────────┘
```

### notification_queue Table

```
┌────────────────────────────────────────────────────────────────┐
│                  notification_queue table                       │
├──────────────────┬──────────────┬──────────────────────────────┤
│ Column           │ Type         │ Description                  │
├──────────────────┼──────────────┼──────────────────────────────┤
│ id               │ INTEGER PK   │ Auto-increment               │
│ user_id          │ VARCHAR(255) │ Target user                  │
│ message_type     │ VARCHAR(50)  │ order/position/alert         │
│ message          │ TEXT         │ Message content              │
│ status           │ VARCHAR(20)  │ pending/sent/failed          │
│ created_at       │ DATETIME     │ Queue time                   │
│ sent_at          │ DATETIME     │ Delivery time                │
│ retry_count      │ INTEGER      │ Retry attempts               │
└──────────────────┴──────────────┴──────────────────────────────┘
```

### user_preferences Table

```
┌────────────────────────────────────────────────────────────────┐
│                   user_preferences table                        │
├──────────────────┬──────────────┬──────────────────────────────┤
│ Column           │ Type         │ Description                  │
├──────────────────┼──────────────┼──────────────────────────────┤
│ id               │ INTEGER PK   │ Auto-increment               │
│ user_id          │ VARCHAR(255) │ User ID (unique)             │
│ order_alerts     │ BOOLEAN      │ Order notifications          │
│ position_alerts  │ BOOLEAN      │ Position updates             │
│ pnl_alerts       │ BOOLEAN      │ P&L notifications            │
│ daily_summary    │ BOOLEAN      │ End of day summary           │
│ alert_threshold  │ DECIMAL      │ P&L alert threshold          │
└──────────────────┴──────────────┴──────────────────────────────┘
```

## Bot Commands

### Command Reference

| Command | Description | Example |
|---------|-------------|---------|
| /start | Initialize bot and link account | /start |
| /help | Display available commands | /help |
| /funds | Get account balance and margin | /funds |
| /positions | View open positions with P&L | /positions |
| /orders | Get today's order book | /orders |
| /holdings | View portfolio holdings | /holdings |
| /trades | Get executed trades | /trades |
| /pnl | Get P&L summary | /pnl |
| /quote SYMBOL | Get last traded price | /quote SBIN |
| /status | Check broker connection | /status |
| /alerts on/off | Toggle notifications | /alerts on |
| /settings | View/modify preferences | /settings |
| /logout | Disconnect bot | /logout |

## Configuration Flow

```
┌────────────────────────────────────────────────────────────────────────────┐
│                     Telegram Bot Setup Flow                                 │
│                                                                             │
│  1. Create Bot with BotFather ─────────────────────────────────────────►   │
│           │                                                                 │
│           ├──► Message @BotFather                                          │
│           ├──► /newbot command                                             │
│           ├──► Set bot name and username                                   │
│           └──► Receive bot token                                           │
│                       │                                                     │
│                       ▼                                                     │
│  2. Configure in OpenAlgo ─────────────────────────────────────────────►   │
│           │                                                                 │
│           ├──► Go to Settings > Telegram                                   │
│           ├──► Enter bot token                                             │
│           ├──► Set webhook URL (optional)                                  │
│           └──► Save configuration                                          │
│                       │                                                     │
│                       ▼                                                     │
│  3. Link Telegram Account ─────────────────────────────────────────────►   │
│           │                                                                 │
│           ├──► Open bot in Telegram                                        │
│           ├──► Send /start command                                         │
│           ├──► Enter verification code                                     │
│           └──► Account linked                                              │
│                       │                                                     │
│                       ▼                                                     │
│  4. Configure Notifications ───────────────────────────────────────────►   │
│           │                                                                 │
│           ├──► /settings in Telegram                                       │
│           ├──► Select notification types                                   │
│           └──► Set thresholds                                              │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

## Service Implementation

### Bot Token Security

```python
from cryptography.fernet import Fernet
from utils.env_utils import get_fernet_key

def encrypt_bot_token(token):
    """Encrypt bot token before storage"""
    key = get_fernet_key()
    fernet = Fernet(key)
    return fernet.encrypt(token.encode()).decode()

def decrypt_bot_token(encrypted_token):
    """Decrypt bot token for use"""
    key = get_fernet_key()
    fernet = Fernet(key)
    return fernet.decrypt(encrypted_token.encode()).decode()
```

### Command Handler

```python
def handle_telegram_command(update):
    """Process incoming Telegram command"""
    chat_id = update['message']['chat']['id']
    text = update['message'].get('text', '')

    # Parse command
    if text.startswith('/'):
        command = text.split()[0].lower()
        args = text.split()[1:] if len(text.split()) > 1 else []

        handlers = {
            '/start': handle_start,
            '/help': handle_help,
            '/funds': handle_funds,
            '/positions': handle_positions,
            '/orders': handle_orders,
            '/holdings': handle_holdings,
            '/trades': handle_trades,
            '/pnl': handle_pnl,
            '/quote': handle_quote,
            '/status': handle_status,
            '/alerts': handle_alerts,
            '/settings': handle_settings,
            '/logout': handle_logout
        }

        handler = handlers.get(command, handle_unknown)
        return handler(chat_id, args)
```

### Order Alert Integration (via Event Bus)

Order-related Telegram alerts are dispatched through the Event Bus. The `telegram_subscriber` receives all order events and calls `telegram_alert_service.send_order_alert()` for each one.

```python
# subscribers/telegram_subscriber.py
def on_order_placed(event):
    socketio.start_background_task(
        telegram_alert_service.send_order_alert,
        event.api_type, event.request_data, event.response_data, event.api_key,
    )
```

The alert service formats messages per order type and handles both live and analyze mode:

| Order Type | Template |
|------------|----------|
| `placeorder` | Order Placed (symbol, action, qty, price) |
| `placesmartorder` | Smart Order Placed (symbol, position_size) |
| `basketorder` | Basket Order (success/fail counts, symbols) |
| `splitorder` | Split Order (total qty, split size, success/fail) |
| `optionsorder` | Options Order (underlying, legs, results) |
| `optionsmultiorder` | Options Multi-Order (underlying, all legs with symbols) |
| `modifyorder` | Order Modified (orderid, new qty/price) |
| `cancelorder` | Order Cancelled (orderid) |
| `cancelallorder` | All Orders Cancelled (counts) |
| `closeposition` | Position Closed (symbol or count of positions) |

See [53-event-bus](../53-event-bus/README.md) for the full event bus architecture.

## API Endpoints

### Save Configuration

```
POST /telegram/settings
Content-Type: application/json

{
    "bot_token": "123456:ABC-DEF...",
    "webhook_url": "https://example.com/webhook",
    "is_enabled": true
}
```

### Test Connection

```
POST /telegram/test
```

**Response:**
```json
{
    "status": "success",
    "message": "Test message sent successfully"
}
```

### Webhook Endpoint

```
POST /telegram/webhook
Content-Type: application/json

{
    "update_id": 123456789,
    "message": {
        "chat": {"id": 987654321},
        "text": "/funds"
    }
}
```

## Notification Types

### Order Notifications

```
📊 Order Executed

Symbol: SBIN
Action: BUY
Quantity: 100
Price: ₹625.50
Status: COMPLETE

Order ID: 230125000123
Time: 10:30:15 IST
```

### Position Alerts

```
📈 Position Update

Symbol: SBIN
Quantity: 100
Entry: ₹625.50
LTP: ₹630.00
P&L: +₹450.00 (+0.72%)

Time: 10:45:00 IST
```

### P&L Summary

```
📊 Daily P&L Summary

Realized: +₹2,500.00
Unrealized: +₹1,250.00
Total: +₹3,750.00

Trades: 5
Win Rate: 80%

Date: 25-Jan-2025
```

## Error Handling

### Rate Limiting

```python
TELEGRAM_RATE_LIMIT = 30  # messages per second

def check_rate_limit(user_id):
    """Ensure rate limit compliance"""
    key = f"telegram_rate:{user_id}"
    count = cache.get(key, 0)

    if count >= TELEGRAM_RATE_LIMIT:
        return False

    cache.set(key, count + 1, ttl=1)
    return True
```

### Retry Logic

```python
MAX_RETRIES = 3
RETRY_DELAY = [1, 5, 15]  # seconds

def send_with_retry(bot_token, chat_id, message):
    """Send message with retry on failure"""
    for attempt in range(MAX_RETRIES):
        try:
            response = send_telegram_message(bot_token, chat_id, message)
            if response.ok:
                return True
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY[attempt])

    return False
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/telegram.py` | Telegram routes and webhook |
| `services/telegram_bot_service.py` | Bot command handlers |
| `services/telegram_alert_service.py` | Alert/notification service |
| `database/telegram_db.py` | Database models |
| `restx_api/telegram_bot.py` | REST API endpoints |
| `frontend/src/pages/TelegramSettings.tsx` | Configuration UI |
