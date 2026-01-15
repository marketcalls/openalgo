# Telegram Alert API

## Endpoint URL

This API Function Sends Custom Alert Messages to Telegram Users

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/telegram/notify
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/telegram/notify
Custom Domain:  POST https://<your-custom-domain>/api/v1/telegram/notify
```

## Prerequisites

1. **Telegram Bot Must Be Running**
   - Start the bot from OpenAlgo Telegram settings
   - Bot must be active to send alerts

2. **User Must Be Linked**
   - User must have linked their account using `/link` command in Telegram
   - Username in API request must match your OpenAlgo login username (the username you use to login to OpenAlgo app)
   - This is NOT your Telegram username

3. **Valid API Key**
   - API key must be active and valid
   - Get API key from OpenAlgo settings

## Sample API Request (Basic Notification)

```json
{
    "apikey": "eb51c74ed08ffc821fd5da90b55b7560a3a9e48fd58df01063225ecd7b98c993",
    "username": "john_trader",
    "message": "NIFTY crossed 24000! Consider taking profit on long positions."
}
```

**Note**: `username` should be your OpenAlgo login username (e.g., "john_trader"), not your Telegram username (e.g., @johntrader).

###

## Sample API Response (Success)

```json
{
    "status": "success",
    "message": "Notification sent successfully"
}
```

###

## Sample API Request (With Priority)

```json
{
    "apikey": "eb51c74ed08ffc821fd5da90b55b7560a3a9e48fd58df01063225ecd7b98c993",
    "username": "john_trader",
    "message": "🚨 URGENT: Stop loss hit on BANKNIFTY position!",
    "priority": 10
}
```

###

## Sample API Request (Multi-line Alert)

```json
{
    "apikey": "your_api_key",
    "username": "john_trader",
    "message": "📊 Daily Trading Summary\n─────────────────────\n✅ Winning Trades: 8\n❌ Losing Trades: 2\n💰 Net P&L: +₹15,450\n📈 Win Rate: 80%\n\n🎯 Great day! Keep it up!",
    "priority": 5
}
```

###

## Parameter Description

| Parameters  | Description                                    | Mandatory/Optional | Default Value |
| ----------- | ---------------------------------------------- | ------------------ | ------------- |
| apikey      | App API key                                    | Mandatory          | -             |
| username    | OpenAlgo login username (the username used to login to OpenAlgo app, NOT Telegram username)| Mandatory | -             |
| message     | Alert message to send                          | Mandatory          | -             |
| priority    | Message priority (1-10, higher = more urgent) | Optional           | 5             |

###

## Response Parameters

| Parameter | Description                       | Type   |
| --------- | --------------------------------- | ------ |
| status    | API response status (success/error) | string |
| message   | Response message                  | string |

###

## Use Cases

### 1. Price Alert Notifications

```json
{
    "apikey": "your_api_key",
    "username": "trader_123",
    "message": "🔔 Price Alert: RELIANCE reached target price ₹2,850",
    "priority": 8
}
```

### 2. Strategy Signal Alerts

```json
{
    "apikey": "your_api_key",
    "username": "algo_trader",
    "message": "📈 BUY Signal: RSI oversold on NIFTY 24000 CE\nEntry: ₹145.50\nTarget: ₹165.00\nSL: ₹138.00",
    "priority": 9
}
```

### 3. Risk Management Alerts

```json
{
    "apikey": "your_api_key",
    "username": "trader_123",
    "message": "⚠️ Risk Alert: Daily loss limit reached (-₹25,000)\nNo new positions recommended.",
    "priority": 10
}
```

### 4. Market Update Notifications

```json
{
    "apikey": "your_api_key",
    "username": "trader_123",
    "message": "📰 Market Update: FII bought ₹2,500 crores today\nMarket sentiment: Bullish\nNIFTY support: 23,800",
    "priority": 5
}
```

### 5. Trade Execution Confirmation

```json
{
    "apikey": "your_api_key",
    "username": "trader_123",
    "message": "✅ Order Executed\nSymbol: BANKNIFTY 48000 CE\nAction: BUY\nQty: 30\nPrice: ₹245.75\nTotal: ₹7,372.50",
    "priority": 7
}
```

### 6. Technical Indicator Alerts

```json
{
    "apikey": "your_api_key",
    "username": "technical_trader",
    "message": "📊 Technical Alert: NIFTY\n• RSI: 72 (Overbought)\n• MACD: Bearish Crossover\n• Support: 23,850\n• Resistance: 24,150\n\nConsider booking profits.",
    "priority": 8
}
```

###

## Priority Levels

| Priority | Description              | Use Case                          |
| -------- | ------------------------ | --------------------------------- |
| 1-3      | Low Priority             | General updates, market news      |
| 4-6      | Normal Priority          | Trade signals, daily summaries    |
| 7-8      | High Priority            | Price alerts, position updates    |
| 9-10     | Urgent                   | Stop loss hits, risk alerts       |

**Note**: Priority affects message delivery order but all messages are delivered.

###

## Error Responses

### Invalid API Key

```json
{
    "status": "error",
    "message": "Invalid or missing API key"
}
```

### User Not Found

```json
{
    "status": "error",
    "message": "User not found or not linked to Telegram"
}
```

**Common Cause**: Using Telegram username instead of OpenAlgo login username. Use the username you login to OpenAlgo with, not your @telegram_handle.

### Missing Parameters

```json
{
    "status": "error",
    "message": "Username and message are required"
}
```

### Bot Not Running

```json
{
    "status": "error",
    "message": "Failed to send notification"
}
```

###

## Common Error Messages

| Error Message                          | Cause                                | Solution                           |
| -------------------------------------- | ------------------------------------ | ---------------------------------- |
| Invalid or missing API key             | API key is incorrect or expired      | Check API key in settings          |
| User not found or not linked to Telegram | User hasn't linked account OR using wrong username | Use OpenAlgo login username (not Telegram username). Link account via `/link` command |
| Username and message are required      | Missing required fields              | Provide username and message       |
| Failed to send notification            | Bot is not running                   | Start bot from Telegram settings   |

###

## Message Formatting

### Supported Markdown

- **Bold**: `*text*` or `**text**`
- **Italic**: `_text_` or `__text__`
- **Code**: `` `text` ``
- **Pre-formatted**: ` ```text``` `
- **Links**: `[text](url)`

### Emojis

Use standard Unicode emojis in messages:
- 📈 📉 Charts
- 💰 💵 Money
- ✅ ❌ Status
- 🚨 ⚠️ Alerts
- 📊 📉 Analytics
- 🎯 🔔 Notifications

### Line Breaks

Use `\n` for line breaks in JSON strings.

###

## Rate Limiting

- **Limit**: 30 requests per minute per user
- **Scope**: Per API endpoint
- **Response**: 429 status code if limit exceeded

###

## Best Practices

1. **Use Correct Username**: Always use your OpenAlgo login username (the one you use to login to OpenAlgo app), NOT your Telegram username (@handle)
2. **Keep Messages Concise**: Short, actionable messages work best
3. **Use Emojis Wisely**: Emojis improve readability but don't overuse
4. **Set Appropriate Priority**: Reserve high priority (9-10) for urgent alerts only
5. **Format for Readability**: Use line breaks and sections for multi-line messages
6. **Test First**: Send test messages before automating
7. **Handle Errors**: Implement error handling for failed notifications
8. **Username Match**: Ensure username matches exactly (case-sensitive)
9. **Bot Status**: Check bot is running before bulk notifications

###

## Integration Examples

### Python Example

```python
import requests
import json

def send_telegram_alert(username, message, priority=5):
    url = "http://127.0.0.1:5000/api/v1/telegram/notify"

    payload = {
        "apikey": "your_api_key_here",
        "username": username,
        "message": message,
        "priority": priority
    }

    response = requests.post(url, json=payload)
    return response.json()

# Usage
result = send_telegram_alert(
    username="trader_123",
    message="🎯 Target reached on NIFTY 24000 CE",
    priority=8
)

print(result)
```

### JavaScript Example

```javascript
async function sendTelegramAlert(username, message, priority = 5) {
    const url = 'http://127.0.0.1:5000/api/v1/telegram/notify';

    const payload = {
        apikey: 'your_api_key_here',
        username: username,
        message: message,
        priority: priority
    };

    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    });

    return await response.json();
}

// Usage
sendTelegramAlert(
    'trader_123',
    '📈 Buy signal detected on BANKNIFTY',
    8
).then(result => console.log(result));
```

### cURL Example

```bash
curl -X POST http://127.0.0.1:5000/api/v1/telegram/notify \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your_api_key_here",
    "username": "trader_123",
    "message": "Test alert from API",
    "priority": 5
  }'
```

###

## Workflow Integration

### With Trading Strategies

```python
# After order execution
if order_status == "success":
    send_telegram_alert(
        username="trader_123",
        message=f"✅ Order executed: {symbol} {action} {quantity}",
        priority=7
    )
```

### With Price Monitoring

```python
# Price alert system
if current_price >= target_price:
    send_telegram_alert(
        username="trader_123",
        message=f"🎯 {symbol} reached target price: ₹{current_price}",
        priority=9
    )
```

### With Risk Management

```python
# Daily loss limit
if daily_loss >= max_loss_limit:
    send_telegram_alert(
        username="trader_123",
        message=f"🚨 Daily loss limit reached: -₹{daily_loss}\nTrading halted.",
        priority=10
    )
```

###

## Features

1. **Custom Messages**: Send any text-based alert
2. **Priority System**: Control message importance (1-10)
3. **Rich Formatting**: Support for emojis, markdown, line breaks
4. **User-Specific**: Target specific users by username
5. **High Reliability**: Messages queued if delivery fails
6. **Rate Limited**: Prevents spam and abuse
7. **Secure**: API key authentication required

###

## Troubleshooting

### Alert Not Received

1. **Check Bot Status**: Ensure bot is running in OpenAlgo settings
2. **Verify Username**: Confirm username matches linked account (case-sensitive)
3. **Check Linking**: User must have linked account via `/link` command
4. **Review Logs**: Check OpenAlgo logs for error messages
5. **Test Connection**: Use `/status` command in Telegram bot

### Delivery Delays

1. **Rate Limiting**: Check if rate limit exceeded (30/min)
2. **Bot Load**: High message volume may cause slight delays
3. **Network Issues**: Check internet connectivity
4. **Telegram API**: Telegram may have temporary issues

### Formatting Issues

1. **Escape Characters**: Use proper JSON escaping for special characters
2. **Line Breaks**: Use `\n` not actual line breaks in JSON
3. **Markdown**: Check markdown syntax is correct
4. **Message Length**: Keep messages under 4096 characters (Telegram limit)

###

## Security Considerations

1. **API Key Protection**: Never expose API keys in client-side code
2. **Username Privacy**: Usernames are case-sensitive and private
3. **Message Content**: Don't send sensitive data in plain text
4. **Rate Limiting**: Prevents abuse and spam
5. **Authentication**: Every request must include valid API key

###

## Limitations

- Maximum message length: 4096 characters (Telegram limit)
- Rate limit: 30 messages per minute per user
- Bot must be running to send messages
- User must be linked to receive messages
- Messages are queued but not guaranteed during bot downtime

###

## Support

For issues or questions:
- Check bot status in OpenAlgo Telegram settings
- Verify user is linked via `/status` command in Telegram
- Review API response for specific error messages
- Check OpenAlgo logs for detailed error information
