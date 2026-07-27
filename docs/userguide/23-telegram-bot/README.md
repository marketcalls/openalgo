# 23 - Telegram Bot

## Introduction

OpenAlgo's Telegram Bot integration provides real-time notifications and remote control capabilities directly from your Telegram app. Get trade alerts, monitor positions, and execute commands without accessing the dashboard.

## Features

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Telegram Bot Features                                │
│                                                                              │
│  NOTIFICATIONS                         COMMANDS                             │
│  ─────────────                         ────────                             │
│  • Order placed/executed               • /positions - View positions        │
│  • Position updates                    • /orders - View order book          │
│  • P&L alerts                          • /pnl - Check P&L                   │
│  • Error notifications                 • /status - System status            │
│  • Strategy signals                    • /help - Command help               │
│                                                                              │
│  BENEFITS                                                                   │
│  ────────                                                                   │
│  • Instant mobile alerts                                                    │
│  • Monitor anywhere                                                         │
│  • Quick status checks                                                      │
│  • No app installation needed                                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Setting Up Telegram Bot

### Step 1: Create Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send command: `/newbot`
3. Follow prompts:
   - Enter bot name (e.g., "My OpenAlgo Bot")
   - Enter username (e.g., "myopenalgo_bot")
4. **Save the API token** provided

```
BotFather Response:
Done! Congratulations on your new bot.

Token: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

Keep your token secure and store it safely!
```

### Step 2: Get Your Chat ID

1. Search for **@userinfobot** on Telegram
2. Start a conversation
3. It will reply with your ID:
   ```
   Your user id: 123456789
   ```
4. Save this Chat ID

### Step 3: Configure in OpenAlgo

1. Go to **Settings** → **Telegram**
2. Enter:
   - **Bot Token**: Your token from BotFather
   - **Chat ID**: Your user ID
3. Click **Save**
4. Click **Test Connection**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Telegram Configuration                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Bot Token:                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Chat ID:                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 123456789                                                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐                                        │
│  │     Save     │  │  Test Send   │                                        │
│  └──────────────┘  └──────────────┘                                        │
│                                                                              │
│  Status: ✅ Connected                                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Step 4: Start Your Bot

1. Open Telegram
2. Search for your bot by username
3. Click **Start** or send `/start`
4. Bot is now ready!

## Notification Types

### Order Notifications

When an order is placed:

```
📊 ORDER PLACED

Symbol: SBIN
Exchange: NSE
Action: BUY
Quantity: 100
Price Type: MARKET
Product: MIS
Strategy: MA_Crossover

Order ID: 230125000012345
Time: 10:30:15
```

### Execution Notifications

When an order is executed:

```
✅ ORDER EXECUTED

Symbol: SBIN
Exchange: NSE
Action: BUY
Quantity: 100
Price: ₹625.50
Value: ₹62,550

Order ID: 230125000012345
Time: 10:30:17
```

### P&L Notifications

Daily P&L summary:

```
📈 DAILY P&L SUMMARY

Date: 2025-01-21

Realized P&L: ₹5,250
Unrealized P&L: ₹1,200
Total P&L: ₹6,450

Trades: 12
Winners: 8
Losers: 4
Win Rate: 66.7%
```

### Error Notifications

When something goes wrong:

```
⚠️ ERROR ALERT

Order Failed: SBIN BUY 100
Reason: Insufficient margin

Strategy: MA_Crossover
Time: 10:30:15

Please check your account balance.
```

## Configuring Notifications

### Enable/Disable Notification Types

Go to **Settings** → **Telegram** → **Notification Settings**

| Notification | Default | Description |
|--------------|---------|-------------|
| Order Placed | ✅ On | When order is sent |
| Order Executed | ✅ On | When order fills |
| Order Failed | ✅ On | When order fails |
| Position Updates | ❌ Off | Position changes |
| P&L Alerts | ✅ On | Daily P&L summary |
| Error Alerts | ✅ On | System errors |

### Alert Thresholds

Configure when to receive P&L alerts:

| Setting | Description |
|---------|-------------|
| P&L Threshold | Alert when P&L exceeds amount |
| Loss Alert | Alert on losses above threshold |
| Periodic Update | Hourly/30min P&L updates |

## Bot Commands

### Available Commands

| Command | Description |
|---------|-------------|
| `/start` | Initialize bot |
| `/help` | Show all commands |
| `/positions` | View open positions |
| `/orders` | View today's orders |
| `/pnl` | Check current P&L |
| `/status` | System status |
| `/holdings` | View holdings |

### /positions Command

```
📊 OPEN POSITIONS

Symbol    Qty    Avg     LTP      P&L
─────────────────────────────────────
SBIN      +100   625.00  630.00   +₹500
HDFC      -50    1650    1640     +₹500
NIFTY30JAN25FUT +50  21500  21550  +₹2500

Total Unrealized P&L: ₹3,500
```

### /orders Command

```
📋 TODAY'S ORDERS

Time     Symbol  Action  Qty   Status
──────────────────────────────────────
10:30:15 SBIN    BUY     100   Executed
10:31:22 HDFC    SELL    50    Executed
10:45:10 INFY    BUY     25    Pending

Total Orders: 3
Executed: 2 | Pending: 1
```

### /pnl Command

```
📈 P&L STATUS

Realized P&L: ₹5,250
Unrealized P&L: ₹3,500
─────────────────────
Total P&L: ₹8,750

Today's Trades: 12
Win Rate: 66.7%
```

### /status Command

```
🔧 SYSTEM STATUS

OpenAlgo: ✅ Running
Broker: ✅ Connected
WebSocket: ✅ Active
Last Order: 10:45:10

Uptime: 5h 30m
Active Strategies: 3
```

## Advanced Features

### Group Notifications

For team environments:

1. Create Telegram Group
2. Add your bot to the group
3. Get group Chat ID (starts with -)
4. Configure in OpenAlgo

```
Group Chat ID: -1001234567890
```

### Multiple Recipients

Send to multiple users:

1. Go to **Settings** → **Telegram**
2. Add multiple Chat IDs (comma-separated)
3. All users receive notifications

### Custom Messages

Send custom notifications from strategies:

**TradingView Alert:**
```json
{
  "apikey": "YOUR_KEY",
  "symbol": "SBIN",
  "action": "BUY",
  "quantity": "100",
  "telegram_message": "Custom: Buying SBIN on MA crossover"
}
```

**Python Strategy:**
```python
from openalgo import api

client = api(api_key="YOUR_KEY", host="http://127.0.0.1:5000")

# Send custom Telegram message
client.send_telegram("Custom alert: Strategy triggered!")
```

## Troubleshooting

### Bot Not Responding

| Issue | Solution |
|-------|----------|
| Bot token invalid | Re-copy from BotFather |
| Chat ID wrong | Get correct ID from @userinfobot |
| Bot not started | Send /start to your bot |
| Network issues | Check internet connection |

### Not Receiving Notifications

| Issue | Solution |
|-------|----------|
| Notifications disabled | Check notification settings |
| Telegram app settings | Enable notifications in app |
| Bot blocked | Unblock bot in Telegram |

### Testing Connection

1. Go to **Settings** → **Telegram**
2. Click **Test Connection**
3. Check Telegram for test message

Expected message:
```
🔔 OpenAlgo Test

This is a test message.
Your Telegram integration is working correctly!

Time: 2025-01-21 10:30:15
```

## Security Best Practices

### 1. Protect Your Bot Token

- Never share your bot token
- Don't commit to version control
- Regenerate if compromised (via BotFather)

### 2. Private Conversations

- Use private chat with bot
- Don't share in public groups
- Be careful with sensitive data

### 3. Limit Access

- Only your Chat ID receives messages
- Don't add bot to public groups

### 4. Regular Review

- Check bot activity
- Review connected sessions
- Rotate token periodically

## Notification Examples

### Trade Alert Flow

```
Signal Received
      │
      ▼
Order Placed → 📊 Notification
      │
      ▼
Order Executed → ✅ Notification
      │
      ▼
Position Updated → 📈 Optional Notification
```

### Daily Summary Example

```
📊 DAILY TRADING SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━

Date: 2025-01-21 (Tuesday)

📈 P&L
───────────────────────
Realized: ₹8,500
Unrealized: ₹2,300
Total: ₹10,800 (+2.16%)

📋 TRADES
───────────────────────
Total: 15
Winning: 10 (66.7%)
Losing: 5 (33.3%)
Avg Win: ₹1,200
Avg Loss: ₹550

📊 POSITIONS (EOD)
───────────────────────
SBIN: +100 @ 625 (P&L: +₹500)
HDFC: -50 @ 1650 (P&L: +₹800)

🎯 TOP PERFORMERS
───────────────────────
1. NIFTY30JAN25FUT: +₹3,500
2. SBIN: +₹2,000
3. HDFC: +₹1,500

Happy Trading! 🚀
```

---

**Previous**: [22 - Action Center](../22-action-center/README.md)

**Next**: [24 - PnL Tracker](../24-pnl-tracker/README.md)
