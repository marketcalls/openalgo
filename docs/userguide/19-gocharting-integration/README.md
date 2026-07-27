# 19 - GoCharting Integration

## Introduction

GoCharting is a modern web-based charting platform designed specifically for Indian markets. It offers TradingView-style functionality with native support for Indian exchanges. OpenAlgo integrates seamlessly with GoCharting's webhook system for automated trading.

## How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    GoCharting → OpenAlgo Flow                               │
│                                                                              │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌──────────┐  │
│  │ GoCharting  │     │   Webhook   │     │  OpenAlgo   │     │  Broker  │  │
│  │   Alert     │────▶│   Request   │────▶│   Server    │────▶│   API    │  │
│  │  Triggers   │     │             │     │             │     │          │  │
│  └─────────────┘     └─────────────┘     └─────────────┘     └──────────┘  │
│                                                                              │
│  Indicator/price     JSON payload        Validates &         Executes       │
│  condition met       sent to URL         processes           trade          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. GoCharting account (Pro plan for webhooks)
2. OpenAlgo running and accessible via internet
3. API key generated in OpenAlgo
4. Broker connected and logged in

## GoCharting Features

### Why Use GoCharting?

| Feature | Benefit |
|---------|---------|
| Indian Market Focus | Native NSE, BSE, MCX symbols |
| Pine Script Compatible | Use existing TradingView scripts |
| Real-time Data | Live quotes from exchanges |
| Alert System | Webhook support for automation |
| Mobile App | Trade from anywhere |

## Making OpenAlgo Accessible for Webhooks

GoCharting webhooks need to reach your OpenAlgo server from the internet.

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

## Creating Alerts in GoCharting

### Step 1: Set Up Your Chart

1. Open GoCharting
2. Load your symbol (e.g., NSE:SBIN)
3. Add indicators as needed

### Step 2: Create Alert

1. Right-click on chart
2. Select **Create Alert**
3. Configure conditions:
   - **Trigger**: When price crosses indicator
   - **Frequency**: Once per bar / Every time

### Step 3: Configure Webhook

1. In alert dialog, select **Webhook**
2. Enter URL: `https://your-openalgo-url/api/v1/placeorder`
3. Configure the message body

## Webhook Message Templates

### Basic Market Order

```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "GoCharting",
  "symbol": "{{ticker}}",
  "exchange": "{{exchange}}",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### Dynamic Order

```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "GoChartingDynamic",
  "symbol": "{{ticker}}",
  "exchange": "{{exchange}}",
  "action": "{{action}}",
  "quantity": "{{quantity}}",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### Smart Order

```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "GoChartingSmart",
  "symbol": "{{ticker}}",
  "exchange": "{{exchange}}",
  "action": "{{action}}",
  "quantity": "{{quantity}}",
  "position_size": "{{position_size}}",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

## GoCharting Variables

### Available Placeholders

| Variable | Description | Example |
|----------|-------------|---------|
| `{{ticker}}` | Symbol name | SBIN |
| `{{exchange}}` | Exchange code | NSE |
| `{{action}}` | Trade action | BUY / SELL |
| `{{quantity}}` | Order quantity | 100 |
| `{{price}}` | Current price | 625.50 |
| `{{time}}` | Alert time | 10:30:15 |
| `{{position_size}}` | Strategy position | 100 / -100 |

## Strategy Examples

### 1. Moving Average Crossover

**Setup in GoCharting:**
1. Add SMA(9) and SMA(21) indicators
2. Create alert: SMA(9) crosses above SMA(21)

**Buy Alert Message:**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "MA_Crossover",
  "symbol": "{{ticker}}",
  "exchange": "{{exchange}}",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

**Sell Alert Message:**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "MA_Crossover",
  "symbol": "{{ticker}}",
  "exchange": "{{exchange}}",
  "action": "SELL",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### 2. RSI Strategy

**Buy Alert (RSI crosses above 30):**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "RSI_Strategy",
  "symbol": "{{ticker}}",
  "exchange": "{{exchange}}",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

**Sell Alert (RSI crosses below 70):**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "RSI_Strategy",
  "symbol": "{{ticker}}",
  "exchange": "{{exchange}}",
  "action": "SELL",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### 3. Breakout Strategy

**Alert when price breaks 20-period high:**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "Breakout",
  "symbol": "{{ticker}}",
  "exchange": "{{exchange}}",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

## Pine Script Integration

GoCharting supports Pine Script. You can use your existing scripts:

### Example Pine Script Strategy

```pine
//@version=5
strategy("My Strategy", overlay=true)

// Indicators
fastMA = ta.sma(close, 9)
slowMA = ta.sma(close, 21)

// Conditions
longCondition = ta.crossover(fastMA, slowMA)
shortCondition = ta.crossunder(fastMA, slowMA)

// Entries
if (longCondition)
    strategy.entry("Long", strategy.long)

if (shortCondition)
    strategy.close("Long")
```

### Corresponding Webhook

```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "{{strategy.order.id}}",
  "symbol": "{{ticker}}",
  "exchange": "{{exchange}}",
  "action": "{{strategy.order.action}}",
  "quantity": "{{strategy.order.contracts}}",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

## F&O Trading

### Futures Order

```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "FuturesStrategy",
  "symbol": "NIFTY25JANFUT",
  "exchange": "NFO",
  "action": "BUY",
  "quantity": "50",
  "pricetype": "MARKET",
  "product": "NRML"
}
```

### Options Order

```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "OptionsStrategy",
  "symbol": "NIFTY25JAN21500CE",
  "exchange": "NFO",
  "action": "BUY",
  "quantity": "50",
  "pricetype": "MARKET",
  "product": "NRML"
}
```

## Symbol Mapping

### Equity Symbols

| GoCharting | OpenAlgo |
|------------|----------|
| NSE:SBIN | SBIN (exchange: NSE) |
| BSE:SBIN | SBIN (exchange: BSE) |
| NSE:RELIANCE | RELIANCE (exchange: NSE) |

### Index Symbols

| GoCharting | OpenAlgo |
|------------|----------|
| NSE:NIFTY | NIFTY 50 |
| NSE:BANKNIFTY | NIFTY BANK |

### F&O Symbols

Format: `SYMBOL` + `EXPIRY` + `STRIKE` + `CE/PE`

| Type | Example |
|------|---------|
| Future | NIFTY25JANFUT |
| Call Option | NIFTY25JAN21500CE |
| Put Option | NIFTY25JAN21500PE |

## Testing Your Integration

### Step 1: Enable Analyzer Mode

1. Go to **Analyzer** in OpenAlgo
2. Click **Enable Analyzer Mode**
3. Orders route to sandbox

### Step 2: Create Test Alert

1. Create simple price alert in GoCharting
2. Set to trigger immediately
3. Configure webhook with your payload

### Step 3: Verify Execution

1. Check **Order Book** in OpenAlgo
2. Verify order details
3. Check **Positions**

### Step 4: Review Logs

1. Go to **Traffic Logs**
2. Find webhook request
3. Check request/response

## Alert Management

### Managing Multiple Alerts

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  GoCharting Alerts                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Alert 1: SBIN MA Crossover Buy    [Active]  [Edit]  [Delete]              │
│  Alert 2: SBIN MA Crossover Sell   [Active]  [Edit]  [Delete]              │
│  Alert 3: NIFTY Breakout           [Active]  [Edit]  [Delete]              │
│  Alert 4: BANKNIFTY RSI            [Paused]  [Edit]  [Delete]              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Alert Expiration

- GoCharting alerts have expiration dates
- Renew alerts periodically
- Premium plans offer longer expiration

## Best Practices

### 1. Test Thoroughly

- Use Analyzer Mode first
- Test with small quantities
- Monitor first few live trades

### 2. Use Descriptive Strategy Names

```json
"strategy": "SBIN_MA_Crossover"
```

Instead of:
```json
"strategy": "Strategy1"
```

### 3. Set Appropriate Alert Frequency

| Frequency | Use Case |
|-----------|----------|
| Once per bar | End-of-bar signals |
| Every time | Intrabar signals |
| Once | One-time alerts |

### 4. Handle Multiple Timeframes

Create separate alerts for different timeframes:
- 5-minute chart entry signals
- 15-minute chart confirmation
- Daily chart trend direction

### 5. Monitor Regularly

- Check OpenAlgo dashboard
- Review trade logs
- Verify position accuracy

## Troubleshooting

### Webhook Not Reaching OpenAlgo

| Issue | Solution |
|-------|----------|
| URL not accessible | Check ngrok/public IP |
| SSL certificate error | Use https with valid cert |
| Firewall blocking | Allow incoming connections |

### Order Not Executing

| Issue | Solution |
|-------|----------|
| Invalid API key | Verify API key |
| Symbol not found | Check symbol format |
| Broker not logged in | Re-authenticate |
| Market closed | Wait for market hours |

### Debugging Steps

1. Check GoCharting alert history
2. Review OpenAlgo Traffic Logs
3. Verify webhook payload format
4. Test API manually with Playground

### Common Error Messages

```
"Invalid API key" → Check API key in webhook message
"Symbol not found" → Verify symbol exists in master contract
"Insufficient margin" → Add funds or reduce quantity
"Market closed" → Alert triggered outside market hours
```

## GoCharting vs TradingView

| Feature | GoCharting | TradingView |
|---------|------------|-------------|
| Indian Market Focus | Native | Through exchange |
| Pricing | More affordable | Premium plans |
| Pine Script | Supported | Native |
| Webhook | Pro plan | Premium+ |
| Mobile App | Yes | Yes |
| Data Quality | Good | Excellent |

---

**Previous**: [18 - ChartInk Integration](../18-chartink-integration/README.md)

**Next**: [20 - Python Strategies](../20-python-strategies/README.md)
