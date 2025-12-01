# GoCharting Webhook Setup Guide

## Overview

GoCharting is a professional HTML5 charting platform optimized for Indian markets. With a **Premium Plan**, you can set up webhook alerts to automate your trading strategies with OpenAlgo.

---

## Prerequisites

### 1. GoCharting Premium Plan
- Webhook alerts are only available on the **GoCharting Premium Plan**
- Subscribe at [GoCharting](https://gocharting.com) to access webhook features

### 2. OpenAlgo Setup
- OpenAlgo instance running and accessible
- API key configured in OpenAlgo
- Broker connected and authenticated

### 3. Public URL Configuration

#### Option A: Production/Custom Domain
If you have a custom domain or server:
1. Open your `.env` file
2. Update the `HOST_SERVER` variable:
   ```env
   HOST_SERVER=https://yourdomain.com
   ```

#### Option B: Local Development with Tunneling

If you're running OpenAlgo locally (on your computer) and want to test webhooks, you'll need to expose your local server to the internet using a tunneling service.

**Popular Tunneling Services:**
- **DevTunnel** (Microsoft) - Good for Visual Studio users
- **ngrok** - Popular cross-platform option
- **localtunnel** - Free and simple alternative
- **Cloudflare Tunnel** - Enterprise-grade option

**How Tunneling Works:**
1. Your local OpenAlgo runs on `http://localhost:5000`
2. Tunneling service creates a public URL pointing to your local server
3. GoCharting can send webhooks to this public URL
4. The tunnel forwards requests to your local OpenAlgo

**Typical URL Formats:**
- DevTunnel: `https://abc123.devtunnels.ms`
- ngrok: `https://abc123.ngrok.io`
- localtunnel: `https://abc123.loca.lt`

**Setup Steps:**
1. Install and configure your chosen tunneling service
2. Start the tunnel pointing to port 5000 (OpenAlgo's default port)
3. Copy the public URL provided by the tunneling service
4. Update your `.env` file:
   ```env
   HOST_SERVER=https://your-tunnel-url.com
   ```
5. Restart OpenAlgo application

⚠️ **Important Notes:**
- Tunnel URLs may change each time you restart (unless using paid plans)
- Free tier tunnels may have bandwidth/time limitations
- Update the webhook URL in GoCharting if your tunnel URL changes
- For production use, consider a custom domain instead of tunneling

---

## Step-by-Step Setup

### Step 1: Generate Webhook Configuration

1. **Login to OpenAlgo**
   - Navigate to your OpenAlgo dashboard
   - Go to **Platforms** from the main navigation menu

2. **Open GoCharting Configuration**
   - Click on the **"Configure GoCharting"** card
   - You'll be redirected to `/gocharting/`

3. **Configure Your Trade Parameters**

   Fill in the following fields:

   - **Symbol**: Enter the stock/instrument symbol (e.g., SAIL, RELIANCE, NIFTY)
     - Start typing and select from the autocomplete suggestions

   - **Exchange**: Select the exchange
     - NSE (National Stock Exchange)
     - NFO (NSE Futures & Options)
     - BSE (Bombay Stock Exchange)
     - BFO (BSE Futures & Options)
     - CDS (Currency Derivatives)
     - MCX (Multi Commodity Exchange)

   - **Product Type**: Choose the product type
     - MIS (Margin Intraday Square-off)
     - NRML (Normal/Overnight positions)
     - CNC (Cash & Carry/Delivery)

   - **Action**: Select the trade action
     - BUY
     - SELL

   - **Quantity**: Enter the number of shares/lots
     - Minimum: 1
     - Example: 10, 100, 500

4. **Generate JSON**
   - Click the **"Generate JSON"** button
   - The webhook configuration will be displayed on the right side

5. **Copy Configuration**
   - **Webhook URL**: Click "Copy" button next to the webhook URL
     ```
     https://yourdomain.com/api/v1/placeorder
     ```

   - **JSON Payload**: Click "Copy" button to copy the generated JSON
     ```json
     {
       "apikey": "your_api_key_here",
       "strategy": "GoCharting",
       "symbol": "SAIL",
       "action": "BUY",
       "exchange": "NSE",
       "pricetype": "MARKET",
       "product": "MIS",
       "quantity": "10"
     }
     ```

---

### Step 2: Create Alert in GoCharting

1. **Open GoCharting Chart**
   - Login to your GoCharting Premium account
   - Open the chart for your desired instrument

2. **Set Alert Conditions**
   - Right-click on the chart or use the alert button
   - Click **"Create Alert"**

   Configure the alert parameters:
   - **Parameter**: Select Price, Volume, or Indicator
   - **Operator**: Choose condition (CROSSING, GREATER THAN, LESS THAN, etc.)
   - **Value**: Enter the trigger value

3. **Configure Delivery Frequency**
   - **Frequency**: Select how often the alert should trigger
     - Once: Trigger only once
     - Once Per Bar: Trigger once per candle
     - Every Time: Trigger on every condition match

   - **Expiry**: Set when the alert should expire (optional)

4. **Setup Messaging**
   - **Name**: Give your alert a descriptive name (e.g., "SAIL BUY ALERT")

   - **Message**: Paste your copied JSON payload here
     ```json
     {
       "apikey": "your_api_key_here",
       "strategy": "GoCharting",
       "symbol": "SAIL",
       "action": "BUY",
       "exchange": "NSE",
       "pricetype": "MARKET",
       "product": "MIS",
       "quantity": "10"
     }
     ```

5. **Configure Delivery Methods**

   Enable/disable notification methods as needed:
   - ☑️ **Popup**: Visual popup in GoCharting
   - ☑️ **Sound**: Audio notification (select sound)
   - ☑️ **In-app Push**: Mobile app notification
   - ☑️ **Webhook**: Enable this for OpenAlgo integration

   **Webhook URL**: Paste your OpenAlgo webhook URL
   ```
   https://yourdomain.com/api/v1/placeorder
   ```

6. **Create the Alert**
   - Review all settings
   - Click **"CREATE ALERT"** button
   - Your alert is now active!

---

## ⚠️ IMPORTANT: Testing Workflow

### Before Testing - Enable Sandbox Mode

**ALWAYS test your webhooks in Sandbox mode before using them in live trading environments!**

1. **Enable Sandbox Mode in OpenAlgo**
   - Look for the **Sandbox toggle** in the navbar (top navigation bar)
   - Click the toggle to enable Sandbox mode
   - Configure your sandbox settings if needed
   - Sandbox mode is now active

2. **Why Use Sandbox Mode?**
   - ✅ Test without risking real money
   - ✅ Verify webhook configuration is correct
   - ✅ Debug payload structure
   - ✅ Check symbol mapping
   - ✅ Validate alert triggers
   - ✅ Ensure broker API connectivity

3. **Testing Progression**
   ```
   Step 1: Analyze Mode → Verify payload structure
   Step 2: Sandbox Mode → Test without real orders
   Step 3: Live Mode    → Execute real trades (with small quantities)
   ```

⚠️ **WARNING**: Never test directly in live mode. Always follow the testing progression above to avoid:
- Accidental real trades
- Financial losses during testing
- Multiple unwanted orders
- API rate limit exhaustion

---

## Testing Your Webhook

### Method 1: Test in Analyze Mode (Recommended First Step)

1. Enable **Analyze Mode** in OpenAlgo (toggle in navbar)
2. Create a test alert in GoCharting with a condition that will trigger immediately
3. Check the **API Analyzer** in OpenAlgo to see the incoming request
4. Verify the payload structure and response
5. **No actual orders will be placed in Analyze Mode**

### Method 2: Test in Sandbox Mode (Recommended Second Step)

1. Enable **Sandbox Mode** from the navbar toggle
2. Configure sandbox settings for your broker
3. Create a test alert in GoCharting
4. Trigger the alert and verify:
   - Webhook receives the request
   - Order logic executes correctly
   - No real trades are placed
5. Review logs and order responses

### Method 3: Manual Test with cURL (For Debugging)

```bash
curl -X POST https://yourdomain.com/api/v1/placeorder \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your_api_key_here",
    "strategy": "GoCharting",
    "symbol": "SAIL",
    "action": "BUY",
    "exchange": "NSE",
    "pricetype": "MARKET",
    "product": "MIS",
    "quantity": "1"
  }'
```

### Method 4: Test via Postman (For Debugging)

1. Create a new POST request
2. URL: `https://yourdomain.com/api/v1/placeorder`
3. Headers: `Content-Type: application/json`
4. Body: Paste your JSON payload
5. Click "Send"

### Method 5: Live Testing with Small Quantities

⚠️ **Only after successful testing in Analyze and Sandbox modes:**

1. Disable Analyze Mode and Sandbox Mode
2. Start with **minimal quantities** (e.g., 1 share)
3. Create a test alert that will trigger soon
4. Monitor the execution in real-time
5. Verify the order in your broker terminal
6. Gradually increase quantities once confident

---

## Understanding the Webhook Payload

```json
{
  "apikey": "your_api_key_here",      // Your OpenAlgo API key
  "strategy": "GoCharting",            // Strategy identifier
  "symbol": "SAIL",                    // Trading symbol
  "action": "BUY",                     // BUY or SELL
  "exchange": "NSE",                   // Exchange code
  "pricetype": "MARKET",               // MARKET, LIMIT, SL, SL-M
  "product": "MIS",                    // MIS, NRML, CNC
  "quantity": "10"                     // Number of shares/lots
}
```

### Field Descriptions

| Field | Required | Description | Valid Values |
|-------|----------|-------------|--------------|
| apikey | Yes | Your OpenAlgo API key | String |
| strategy | Yes | Strategy name for logging | Any string |
| symbol | Yes | Trading instrument | Valid symbol |
| action | Yes | Buy or Sell | BUY, SELL |
| exchange | Yes | Trading exchange | NSE, NFO, BSE, BFO, CDS, MCX |
| pricetype | Yes | Order type | MARKET, LIMIT, SL, SL-M |
| product | Yes | Product type | MIS, NRML, CNC |
| quantity | Yes | Number of shares | Positive integer |

---

## Common Use Cases

### 1. Simple Price Alert
**Scenario**: Buy SAIL when price crosses above 150

```json
{
  "apikey": "your_api_key",
  "strategy": "SAIL Price Breakout",
  "symbol": "SAIL",
  "action": "BUY",
  "exchange": "NSE",
  "pricetype": "MARKET",
  "product": "MIS",
  "quantity": "100"
}
```

### 2. Take Profit Alert
**Scenario**: Sell when target reached

```json
{
  "apikey": "your_api_key",
  "strategy": "Take Profit SAIL",
  "symbol": "SAIL",
  "action": "SELL",
  "exchange": "NSE",
  "pricetype": "MARKET",
  "product": "MIS",
  "quantity": "100"
}
```

### 3. Stop Loss Alert
**Scenario**: Sell when stop loss hit

```json
{
  "apikey": "your_api_key",
  "strategy": "Stop Loss SAIL",
  "symbol": "SAIL",
  "action": "SELL",
  "exchange": "NSE",
  "pricetype": "MARKET",
  "product": "MIS",
  "quantity": "100"
}
```

---

## Troubleshooting

### Issue: Webhook not triggering

**Solutions:**
1. Verify your GoCharting Premium subscription is active
2. Check webhook URL is correct and accessible
3. Test the URL with cURL or Postman
4. Ensure OpenAlgo is running and accessible from internet

### Issue: Orders not placing

**Solutions:**
1. Verify API key is correct in the JSON payload
2. Check broker connection in OpenAlgo dashboard
3. Verify sufficient funds in trading account
4. Check symbol format matches your broker's convention
5. Review logs in OpenAlgo (Logs menu)

### Issue: "API key not found" error

**Solutions:**
1. Go to OpenAlgo → API Key section
2. Generate or verify your API key
3. Copy the correct API key to your webhook JSON
4. Regenerate the configuration in GoCharting page

### Issue: Tunnel URL not working

**Solutions:**
1. **Check if tunnel is running**
   - Verify the tunneling service is active
   - Look for the forwarding/public URL in the terminal output
   - Ensure the tunnel is pointing to port 5000

2. **Verify tunnel URL is correct**
   - Copy the exact URL from the tunneling service output
   - Ensure URL starts with `https://` (not `http://`)
   - Check that URL is updated in `.env` file

3. **Restart tunnel if needed**
   - Stop the current tunnel
   - Start a new tunnel session
   - Update `.env` with the new URL
   - Restart OpenAlgo

4. **Test tunnel accessibility**
   - Open the tunnel URL in your browser
   - You should see OpenAlgo login page
   - If not accessible, check firewall/network settings

### Issue: Invalid symbol error

**Solutions:**
1. Use the symbol search in GoCharting configuration page
2. Select symbol from autocomplete dropdown
3. Verify symbol exists on the selected exchange
4. Check for correct spelling and format

---

## Security Best Practices

### 1. Protect Your API Key
- Never share your API key publicly
- Rotate API keys periodically
- Use separate API keys for testing and production

### 2. Use HTTPS
- Always use HTTPS URLs for webhooks
- Tunneling services (devtunnel, ngrok) provide HTTPS by default
- For production, ensure SSL certificate is valid

### 3. Monitor Activity
- Regularly check order logs in OpenAlgo
- Use Analyze Mode to debug webhook payloads
- Review Traffic Monitor for unusual activity

### 4. Test in Sandbox/Paper Trading

⚠️ **CRITICAL**: Always test in sandbox mode before live trading!

**Recommended Testing Workflow:**
1. **Analyze Mode**: Test payload structure without placing orders
2. **Sandbox Mode**: Simulate trades without real money
3. **Live Mode (Small Qty)**: Test with 1 share/lot first
4. **Full Trading**: Deploy with actual quantities

**Never Skip Steps:**
- ❌ Don't test directly in live mode
- ❌ Don't use large quantities for initial testing
- ❌ Don't deploy without monitoring first few trades
- ✅ Always follow the testing progression
- ✅ Monitor logs during initial deployment
- ✅ Keep alerts paused until fully tested

---

## Advanced Configuration

### Using Different Price Types

**Market Order** (Default):
```json
{
  "pricetype": "MARKET"
}
```

**Limit Order**:
```json
{
  "pricetype": "LIMIT",
  "price": 150.50
}
```

**Stop Loss Market**:
```json
{
  "pricetype": "SL-M",
  "trigger_price": 148.00
}
```

**Stop Loss Limit**:
```json
{
  "pricetype": "SL",
  "price": 149.00,
  "trigger_price": 148.50
}
```

### Multiple Alerts Strategy

Create separate alerts for entry, target, and stop loss:

1. **Entry Alert**: BUY when condition met
2. **Target Alert**: SELL at profit level
3. **Stop Loss Alert**: SELL at loss level

---

## Rate Limits

OpenAlgo has rate limiting to prevent abuse:
- Default: 10 requests per second for placeorder API
- Configurable via `ORDER_RATE_LIMIT` in .env file

If you hit rate limits:
1. Space out your alerts
2. Adjust rate limits in .env if needed
3. Consider using basket orders for multiple symbols

---

## Support & Resources

### Documentation
- OpenAlgo Docs: https://docs.openalgo.in
- GoCharting Help: https://gocharting.com/help

### Community
- OpenAlgo GitHub: https://github.com/marketcalls/openalgo
- Report Issues: https://github.com/marketcalls/openalgo/issues

### Video Tutorials
- Check OpenAlgo YouTube channel for video guides
- GoCharting tutorials for alert setup

---

## Changelog

### Version 1.0
- Initial GoCharting webhook integration
- Support for BUY/SELL actions
- Configurable quantity
- Market order support
- Multi-exchange support

---

## FAQs

**Q: Do I need GoCharting Premium for webhooks?**
A: Yes, webhook alerts are only available on GoCharting Premium plans.

**Q: Can I use multiple webhooks for the same chart?**
A: Yes, you can create multiple alerts with different conditions and webhooks.

**Q: What happens if my tunnel disconnects?**
A: Your alerts won't trigger. Restart the tunnel and update the webhook URL in GoCharting.

**Q: Can I change the action (BUY/SELL) dynamically?**
A: No, you need to create separate alerts for BUY and SELL with different configurations.

**Q: How do I know if my webhook was triggered?**
A: Check the Logs section in OpenAlgo or use the API Analyzer in Analyze Mode.

**Q: Can I use limit orders instead of market orders?**
A: Currently, the GoCharting configuration generates MARKET orders. For other order types, modify the JSON payload manually.

---

**Happy Trading with GoCharting and OpenAlgo! 🚀**
