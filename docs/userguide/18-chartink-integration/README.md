# 18 - ChartInk Integration

## Introduction

ChartInk is a powerful stock screening platform popular among Indian traders. It can scan thousands of stocks in real-time and send webhook alerts when conditions are met. OpenAlgo integrates with ChartInk to execute trades automatically based on your screener alerts.

## How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ChartInk → OpenAlgo Flow                                 │
│                                                                              │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌──────────┐  │
│  │  ChartInk   │     │   Webhook   │     │  OpenAlgo   │     │  Broker  │  │
│  │  Screener   │────▶│   Alert     │────▶│   Server    │────▶│   API    │  │
│  │             │     │             │     │             │     │          │  │
│  └─────────────┘     └─────────────┘     └─────────────┘     └──────────┘  │
│                                                                              │
│  Stock matches       Sends stock        Validates &         Executes       │
│  your criteria       symbol + action    processes           trade          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. ChartInk account (premium for webhooks)
2. OpenAlgo running and accessible via internet
3. API key generated in OpenAlgo
4. Broker connected and logged in

## Making OpenAlgo Accessible for Webhooks

ChartInk webhooks need to reach your OpenAlgo server from the internet.

### Recommended: Production Server with Domain

Deploy OpenAlgo on an Ubuntu server using `install.sh` (see [Installation Guide](../04-installation/README.md)):

```
Webhook URL: https://yourdomain.com/api/v1/placeorder
```

This is the **recommended approach** for live trading.

### Alternative: Webhook Tunneling Services

If you don't have a domain or are testing locally, use a tunnel service **for webhooks only**:

| Service | Command | URL Format |
|---------|---------|------------|
| **ngrok** | `ngrok http 5000` | `https://abc123.ngrok.io` |
| **devtunnel** (Microsoft) | `devtunnel host -p 5000` | `https://xxxxx.devtunnels.ms` |
| **Cloudflare Tunnel** | `cloudflared tunnel --url http://localhost:5000` | `https://xxxxx.trycloudflare.com` |

**ngrok:**
```bash
ngrok http 5000
# Copy the https URL provided
```

**devtunnel (Microsoft):**
```bash
devtunnel user login
devtunnel host -p 5000
# Copy the https URL provided
```

**Cloudflare Tunnel:**
```bash
cloudflared tunnel --url http://localhost:5000
# Copy the https URL provided
```

**Important**: Tunnel services are **only for webhooks**, not for running the full application. Always run OpenAlgo on your own server for production use

## Creating a ChartInk Screener

### Step 1: Build Your Screener

1. Go to [chartink.com](https://chartink.com)
2. Click **Screener** → **Create New**
3. Build your conditions

Example screener conditions:

```
For Bullish Crossover:
- Close > SMA(Close, 50)
- RSI(14) crossed above 30
- Volume > SMA(Volume, 20)
```

### Step 2: Save the Screener

1. Click **Save**
2. Give it a meaningful name
3. Note the screener URL/ID

### Step 3: Set Up Webhook Alert

1. Click **Alert** button on your screener
2. Enable **Webhook**
3. Enter your OpenAlgo webhook URL

## Webhook Configuration

### ChartInk Webhook URL

Enter this URL in ChartInk:

```
https://your-openalgo-url/api/v1/placeorder
```

### ChartInk Webhook Payload

ChartInk sends data in a specific format. You need to configure the payload to match OpenAlgo's API:

```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "ChartInkScanner",
  "symbol": "{stock}",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

**Note**: `{stock}` is ChartInk's variable that gets replaced with the actual stock symbol.

## ChartInk Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `{stock}` | Stock symbol | SBIN |
| `{trigger_price}` | Price when triggered | 625.50 |
| `{trigger_time}` | Time of trigger | 10:30:15 |

## Complete Integration Setup

### Buy Alert Setup

1. Create bullish screener
2. Set webhook URL: `https://your-url/api/v1/placeorder`
3. Configure payload:

```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "ChartInkBuy",
  "symbol": "{stock}",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### Sell Alert Setup

1. Create bearish screener
2. Set webhook URL: `https://your-url/api/v1/placeorder`
3. Configure payload:

```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "ChartInkSell",
  "symbol": "{stock}",
  "exchange": "NSE",
  "action": "SELL",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

## Example Screener Strategies

### 1. Moving Average Crossover

**Buy Screener:**
```
SMA(Close, 20) crossed above SMA(Close, 50)
Volume > 100000
Close > 50
```

**Sell Screener:**
```
SMA(Close, 20) crossed below SMA(Close, 50)
Volume > 100000
```

### 2. RSI Reversal

**Buy Screener (Oversold):**
```
RSI(14) crossed above 30
Close > SMA(Close, 200)
```

**Sell Screener (Overbought):**
```
RSI(14) crossed below 70
```

### 3. Breakout Scanner

**Buy Screener:**
```
Close crossed above Max(High, 20)
Volume > 2 * SMA(Volume, 20)
```

### 4. MACD Signal

**Buy Screener:**
```
MACD line crossed above Signal line
MACD histogram > 0
Close > SMA(Close, 50)
```

## Position Management

### Using Smart Orders

For better position management, use the smart order endpoint:

```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "ChartInkSmart",
  "symbol": "{stock}",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "100",
  "position_size": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### Managing Multiple Stocks

ChartInk can trigger alerts for multiple stocks simultaneously. Consider:

1. **Capital Allocation**: Set quantity based on per-stock allocation
2. **Maximum Positions**: Limit total open positions
3. **Risk Per Trade**: Calculate quantity based on stop-loss distance

## Testing Your Setup

### Step 1: Enable Analyzer Mode

1. Enable Analyzer Mode in OpenAlgo
2. All orders go to sandbox

### Step 2: Run Screener Manually

1. Open your screener in ChartInk
2. Click **Run** to get current matches
3. Verify stocks match your criteria

### Step 3: Trigger Test Alert

1. Wait for market hours
2. Let screener trigger naturally
3. Or manually trigger for testing

### Step 4: Verify in OpenAlgo

Check:
- Order Book for new orders
- Positions for created positions
- Logs for any errors

## Timing Considerations

### ChartInk Scan Frequency

| Plan | Scan Frequency |
|------|----------------|
| Free | Manual only |
| Premium | Every 1 minute |
| Professional | Every 30 seconds |

### Order Execution Timing

```
ChartInk scans      → 10:30:00
Alert triggered     → 10:30:01
Webhook sent        → 10:30:02
OpenAlgo receives   → 10:30:02
Order placed        → 10:30:03
Order executed      → 10:30:04

Total latency: ~4 seconds
```

## Handling Multiple Alerts

### Scenario: Multiple Stocks Trigger

If 5 stocks trigger simultaneously:

```
Stock 1 → Webhook → Order placed
Stock 2 → Webhook → Order placed
Stock 3 → Webhook → Order placed
Stock 4 → Webhook → Order placed
Stock 5 → Webhook → Order placed
```

All orders are processed independently.

### Rate Limiting

Be aware of:
- Broker API rate limits
- OpenAlgo processing capacity
- ChartInk webhook frequency

## Filtering Stocks

### Pre-Filter in ChartInk

Add filters to your screener:

```
Market Cap > 1000 Cr
Average Volume > 100000
Close > 100
Sector = Banking
```

### Post-Filter in OpenAlgo

Use strategy-specific logic or manual review with Action Center.

## Best Practices

### 1. Start Small

- Test with small quantities first
- Use Analyzer Mode initially
- Monitor for a week before going live

### 2. Define Clear Criteria

- Specific entry conditions
- Clear exit strategy
- Risk management rules

### 3. Limit Positions

```
Maximum Positions: 10
Per-Stock Allocation: ₹50,000
Stop-Loss: 2%
```

### 4. Use Complementary Screeners

- Entry screener (buy signal)
- Exit screener (sell signal)
- Stop-loss screener (emergency exit)

### 5. Monitor Execution

- Check OpenAlgo dashboard regularly
- Set up Telegram notifications
- Review trades daily

## Troubleshooting

### Alert Not Reaching OpenAlgo

| Issue | Solution |
|-------|----------|
| URL not accessible | Check ngrok/public IP |
| Firewall blocking | Allow port 5000 |
| Invalid webhook URL | Verify URL format |

### Order Not Executing

| Issue | Solution |
|-------|----------|
| Invalid API key | Check API key in payload |
| Symbol not found | Verify symbol mapping |
| Broker not logged in | Re-authenticate |
| Insufficient margin | Add funds |

### Checking Logs

1. Go to **Traffic Logs** in OpenAlgo
2. Filter by source or time
3. Check request payload and response

### Common Errors

```json
{"status": "error", "message": "Invalid API key"}
→ Verify API key in ChartInk payload

{"status": "error", "message": "Symbol not found"}
→ Check symbol exists in master contract

{"status": "error", "message": "Market closed"}
→ Alert triggered outside market hours
```

## Advanced: Custom Middleware

For complex scenarios, you can create a middleware:

```python
# middleware.py
from flask import Flask, request
import requests

app = Flask(__name__)

@app.route('/chartink-handler', methods=['POST'])
def handle_chartink():
    data = request.json
    stock = data.get('stock')

    # Apply custom logic
    if should_trade(stock):
        # Forward to OpenAlgo
        openalgo_payload = {
            "apikey": "YOUR_KEY",
            "strategy": "ChartInk",
            "symbol": stock,
            "exchange": "NSE",
            "action": "BUY",
            "quantity": calculate_quantity(stock),
            "pricetype": "MARKET",
            "product": "MIS"
        }

        response = requests.post(
            "http://127.0.0.1:5000/api/v1/placeorder",
            json=openalgo_payload
        )

        return response.json()

    return {"status": "skipped"}

def should_trade(stock):
    # Custom logic
    return True

def calculate_quantity(stock):
    # Position sizing logic
    return 100
```

---

**Previous**: [17 - Amibroker Integration](../17-amibroker-integration/README.md)

**Next**: [19 - GoCharting Integration](../19-gocharting-integration/README.md)
