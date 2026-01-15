# Telegram Alert API Tests

This folder contains test scripts for the Telegram Alert API.

## ⚠️ Important Note

**Username Clarification**: The `username` parameter in the API refers to your **OpenAlgo login username** (the username you use to login to the OpenAlgo application), NOT your Telegram username (@handle).

- ✅ **Correct**: Use `"rajandran"` (your OpenAlgo login username)
- ❌ **Wrong**: Use `"@rajandranr"` (your Telegram username)

## Test Files

1. **test_telegram_alert_api.py** - Tests the `/api/v1/telegram/notify` endpoint

## Prerequisites

1. **OpenAlgo must be running**
   - Start OpenAlgo application
   - Ensure it's accessible at `http://127.0.0.1:5000`

2. **Telegram Bot Must Be Running**
   - Go to OpenAlgo Telegram settings (`/telegram`)
   - Configure your bot token (get from @BotFather on Telegram)
   - Click "Start Bot"
   - Verify bot status shows "Running"

3. **User Must Be Linked**
   - Open your Telegram bot chat
   - Send `/link your_api_key http://127.0.0.1:5000`
   - Verify linking successful with `/status` command
   - Username must match your OpenAlgo account username

4. **API Key and Username**
   - Get your API key from OpenAlgo settings
   - Replace `"your_api_key_here"` in the test files with your actual API key
   - Replace `"your_username_here"` with your **OpenAlgo login username** (the username you use to login to OpenAlgo app)
   - **IMPORTANT**: Use OpenAlgo username, NOT your Telegram username (@handle)

## How to Run Tests

### Option 1: From Test Directory

```bash
# Navigate to test directory
cd D:/openalgo-sandbox-test/openalgo/test

# Run Telegram Alert API tests
python test_telegram_alert_api.py
```

### Option 2: From Project Root

```bash
# Navigate to project root
cd D:/openalgo-sandbox-test/openalgo

# Run Telegram Alert API tests
python test/test_telegram_alert_api.py
```

### Option 3: Using uv

```bash
# From project root
cd D:/openalgo-sandbox-test/openalgo

# Run tests with uv
uv run python test/test_telegram_alert_api.py
```

## Test Configuration

Edit the test file to configure:

```python
# Configuration section at the top of the file
BASE_URL = "http://127.0.0.1:5000"  # Change if using different host/port
API_KEY = "your_api_key_here"        # Replace with your actual API key
USERNAME = "your_username_here"      # Replace with your OpenAlgo login username (NOT @telegram_handle)
```

**IMPORTANT**: `USERNAME` should be your OpenAlgo login username (e.g., "rajandran"), NOT your Telegram username (e.g., "@rajandranr").

## Test Coverage

### test_telegram_alert_api.py

- Test 1: Basic Alert Message
- Test 2: Alert with Priority (High)
- Test 3: Multi-line Formatted Alert
- Test 4: Price Alert Notification
- Test 5: Trade Signal Alert
- Test 6: Risk Management Alert
- Test 7: Validation Error (Missing Message)
- Test 8: Invalid Username

## Expected Output

### Successful Response

```json
{
  "status": "success",
  "message": "Notification sent successfully"
}
```

### Error Response (User Not Found)

```json
{
  "status": "error",
  "message": "User not found or not linked to Telegram"
}
```

### Error Response (Missing Parameters)

```json
{
  "status": "error",
  "message": "Username and message are required"
}
```

### Error Response (Invalid API Key)

```json
{
  "status": "error",
  "message": "Invalid or missing API key"
}
```

## Troubleshooting

### Bot Not Running Error

```
ConnectionError: Failed to send notification
```

**Solution**:
1. Go to OpenAlgo Telegram settings (`/telegram`)
2. Click "Start Bot"
3. Wait for status to show "Running"
4. Retry the test

### User Not Linked Error

```json
{
  "status": "error",
  "message": "User not found or not linked to Telegram"
}
```

**Solution**:
1. Open your Telegram bot chat
2. Send `/link your_api_key http://127.0.0.1:5000`
3. Verify with `/status` command
4. **Ensure you're using OpenAlgo login username, NOT Telegram username**
   - ✅ Correct: `"rajandran"` (OpenAlgo login)
   - ❌ Wrong: `"@rajandranr"` (Telegram handle)
5. Ensure username in test matches exactly (case-sensitive)

### Invalid API Key Error

```json
{
  "status": "error",
  "message": "Invalid or missing API key"
}
```

**Solution**:
1. Go to OpenAlgo settings
2. Copy your API key
3. Replace in test file: `API_KEY = "your_actual_api_key"`

### Message Not Received

**Possible Causes**:
1. Bot is not running - check bot status
2. User is not linked - verify with `/status` in Telegram
3. Username mismatch - ensure exact match (case-sensitive)
4. Telegram notifications disabled - check user preferences
5. Network issues - check internet connectivity

**Solution**:
1. Check bot status in OpenAlgo dashboard
2. Verify username with `/status` in Telegram bot
3. Check OpenAlgo logs for errors
4. Test with `/menu` command in Telegram to verify bot responds

### Module Import Errors

```
ModuleNotFoundError: No module named 'requests'
```

**Solution**: Install required packages:
```bash
pip install requests
# or
uv pip install requests
```

## Priority Levels Guide

| Priority | Description     | Use Case                    |
| -------- | --------------- | --------------------------- |
| 1-3      | Low             | General updates, news       |
| 4-6      | Normal          | Trade signals, summaries    |
| 7-8      | High            | Price alerts, updates       |
| 9-10     | Urgent          | Stop loss, risk alerts      |

## Message Formatting

### Emojis (Copy-Paste Ready)

```
📈 📉 📊 Charts/Trends
💰 💵 💸 Money
✅ ❌ ⚠️ Status
🚨 🔔 🎯 Alerts
🔴 🟢 🟡 Indicators
📱 💻 🖥️ Devices
⏰ 🕐 ⏱️ Time
🏆 🎉 ✨ Success
```

### Line Breaks

Use `\n` in JSON strings for line breaks:

```json
{
  "message": "Line 1\nLine 2\nLine 3"
}
```

### Markdown (if supported)

- Bold: `*text*` or `**text**`
- Italic: `_text_` or `__text__`
- Code: `` `text` ``

## Integration Examples

### Send Alert After Order

```python
import requests

def send_alert(message, priority=5):
    url = "http://127.0.0.1:5000/api/v1/telegram/notify"
    payload = {
        "apikey": "your_api_key",
        "username": "your_username",
        "message": message,
        "priority": priority
    }
    response = requests.post(url, json=payload)
    return response.json()

# After placing order
order_response = place_order(...)
if order_response['status'] == 'success':
    send_alert(
        f"✅ Order placed: {symbol} {action} {quantity}",
        priority=7
    )
```

### Price Alert Monitor

```python
import time

def monitor_price(symbol, target_price):
    while True:
        current_price = get_ltp(symbol)

        if current_price >= target_price:
            send_alert(
                f"🎯 Target reached!\n{symbol}: ₹{current_price}",
                priority=9
            )
            break

        time.sleep(60)  # Check every minute
```

### Daily Summary

```python
def send_daily_summary():
    stats = get_daily_stats()

    message = f"""📊 Daily Summary
─────────────────────
Trades: {stats['total_trades']}
Win Rate: {stats['win_rate']}%
P&L: ₹{stats['net_pnl']:,.2f}
"""

    send_alert(message, priority=5)
```

## Notes

- Maximum message length: 4096 characters (Telegram limit)
- Rate limit: 30 messages per minute per user
- Bot must be running continuously for alerts
- Messages are queued if delivery fails temporarily
- All alerts are user-specific (username-based)
- Priority affects delivery order but all messages are sent

## Rate Limiting

- **Limit**: 30 requests per minute per user
- **Endpoint**: `/api/v1/telegram/notify`
- **Response**: 429 status code if exceeded
- **Recommendation**: Implement delays between bulk alerts

## Support

For issues or questions:
- Check bot status in OpenAlgo Telegram dashboard
- Verify user linking with `/status` in Telegram
- Review OpenAlgo logs for detailed error messages
- Test bot responsiveness with `/menu` command
- Ensure API key is valid and active
