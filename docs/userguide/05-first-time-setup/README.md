# 05 - First-Time Setup

## Introduction

You've installed OpenAlgo. Now let's configure it properly for secure operation and connect it to your broker.

## Setup Wizard Overview

When you first access OpenAlgo, you'll go through these steps:

```
┌─────────────────────────────────────────────────────────────────┐
│                     First-Time Setup Flow                        │
│                                                                  │
│  Step 1: Create Admin Account                                   │
│     ↓                                                            │
│  Step 2: Generate Security Keys                                 │
│     ↓                                                            │
│  Step 3: Configure Broker Credentials                           │
│     ↓                                                            │
│  Step 4: Connect to Broker                                      │
│     ↓                                                            │
│  Step 5: Generate API Key                                       │
│     ↓                                                            │
│  Ready to Trade!                                                │
└─────────────────────────────────────────────────────────────────┘
```

## Step 1: Access OpenAlgo

1. Start OpenAlgo:
   ```bash
   uv run app.py
   ```

2. Open your browser and go to:
   ```
   http://127.0.0.1:5000
   ```

3. You'll see the setup/login page

## Step 2: Create Admin Account

On first launch, you'll be asked to create an admin account.

**Fill in the form**:
- **Username**: Choose a username (e.g., `admin`)
- **Email**: Your email address
- **Password**: Strong password (8+ characters, mix of letters/numbers/symbols)
- **Confirm Password**: Re-enter password

**Password Requirements**:
- At least 8 characters
- Contains uppercase letter
- Contains lowercase letter
- Contains number
- Contains special character (!@#$%^&*)

**Example of a strong password**: `Trade@2024Secure!`

Click **Create Account**.

## Step 3: Configure Security Keys

Before using OpenAlgo, you MUST set unique security keys.

### Generate Security Keys

Open terminal/command prompt:

```bash
# Generate APP_KEY
uv run python -c "import secrets; print(secrets.token_hex(32))"
# Example output: a3f2b1c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7

# Generate API_KEY_PEPPER (run again)
uv run python -c "import secrets; print(secrets.token_hex(32))"
# Example output: z7y6x5w4v3u2t1s0r9q8p7o6n5m4l3k2j1i0h9g8f7e6d5c4b3a2
```

### Update .env File

Open `.env` file and update:

```ini
# Security Keys - CHANGE THESE!
APP_KEY=a3f2b1c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7
API_KEY_PEPPER=z7y6x5w4v3u2t1s0r9q8p7o6n5m4l3k2j1i0h9g8f7e6d5c4b3a2
```

**Important**:
- Use YOUR generated values, not the examples above
- Keep these keys SECRET
- Never share them

### Restart OpenAlgo

After changing `.env`, restart:
```bash
# Stop OpenAlgo (Ctrl+C)
# Start again
uv run app.py
```

## Step 4: Configure Broker Credentials

Now let's add your broker API credentials.

### Getting Broker Credentials

Each broker has different requirements. Here's a quick reference:

| Broker | What You Need | Where to Get |
|--------|--------------|--------------|
| Zerodha | API Key, Secret | [Kite Connect](https://kite.trade) |
| Angel One | API Key, Client Code | [Angel SmartAPI](https://smartapi.angelbroking.com) |
| Dhan | Client ID, Access Token | [Dhan API](https://api.dhan.co) |
| Fyers | App ID, Secret | [Fyers API](https://myapi.fyers.in) |
| Upstox | API Key, Secret | [Upstox Developer](https://api.upstox.com) |

### Update .env with Broker Details

Example for Zerodha:
```ini
# Broker Selection
BROKER=zerodha

# Zerodha Credentials
BROKER_API_KEY=your_kite_api_key
BROKER_API_SECRET=your_kite_api_secret
```

Example for Angel One:
```ini
# Broker Selection
BROKER=angel

# Angel One Credentials
BROKER_API_KEY=your_angel_api_key
BROKER_CLIENT_CODE=your_client_code
BROKER_PASSWORD=your_password
BROKER_TOTP_KEY=your_totp_secret
```

### Alternative: Configure via Web Interface

1. Login to OpenAlgo
2. Go to **Profile** → **Broker Configuration**
3. Select your broker
4. Enter credentials
5. Click **Save**

## Step 5: Connect to Broker

### Login to Your Broker

1. In OpenAlgo, click **Login to Broker**
2. You'll be redirected to your broker's login page
3. Enter your broker credentials
4. Authorize OpenAlgo
5. You'll be redirected back to OpenAlgo

**Successful connection shows**:
- Green "Connected" status
- Your broker user ID
- Account balance

### Daily Login

Most brokers require daily re-authentication:
- Login expires at end of trading day
- You'll need to login again next morning
- Some brokers support auto-login (check broker docs)

## Step 6: Generate API Key

To use webhooks (TradingView, ChartInk, etc.), you need an API key.

### Create API Key

1. Go to **API Key** section
2. Click **Generate New Key**
3. Your API key is displayed:
   ```
   API Key: abc123def456ghi789jkl012mno345
   ```
4. **Copy and save this key** - it won't be shown again!

### API Key Settings

| Setting | Description |
|---------|-------------|
| Order Mode | Auto (immediate) or Semi-Auto (needs approval) |
| Rate Limit | Orders per minute allowed |

## Step 7: Verify Setup

### Test 1: Check Broker Connection

Go to **Dashboard** and verify:
- [ ] Broker status shows "Connected"
- [ ] Account balance is displayed
- [ ] User ID is correct

### Test 2: View Positions/Holdings

Navigate to:
- **Positions** - Should show current positions (or empty if none)
- **Holdings** - Should show your holdings (or empty)
- **Order Book** - Today's orders

### Test 3: Test API (Optional)

Go to **Playground** and try a simple API call:
1. Select "Get Funds"
2. Click "Execute"
3. Should return your account balance

## Initial Settings to Review

### Security Settings (Recommended)

Go to **Profile** → **Security**:

1. **Enable Two-Factor Authentication**
   - Adds extra security to your login
   - Uses Google Authenticator or similar

2. **Review Session Timeout**
   - Default is 30 minutes of inactivity
   - Adjust based on your needs

### Notification Settings

Go to **Telegram Bot** settings if you want alerts:
- Order execution notifications
- P&L updates
- Strategy alerts

## Common Setup Issues

### Issue: "Invalid API credentials"

**Solution**:
- Double-check credentials in `.env`
- Ensure no extra spaces
- Verify broker API is activated

### Issue: "Broker login failed"

**Solution**:
- Check if broker servers are up
- Try logging into broker's website directly
- Ensure API permissions are granted

### Issue: "Session expired"

**Solution**:
- This is normal for daily expiry
- Re-login to broker each trading day

## Setup Checklist

Before proceeding, confirm:

- [ ] Admin account created
- [ ] Security keys generated and set
- [ ] Broker credentials configured
- [ ] Successfully logged into broker
- [ ] API key generated
- [ ] Dashboard shows correct account info
- [ ] Two-factor authentication enabled (recommended)

## What's Next?

Congratulations! OpenAlgo is now set up. Your next steps:

1. **Learn the Interface**: [Understanding the Interface](../08-understanding-interface/README.md)
2. **Practice First**: [Analyzer Mode](../15-analyzer-mode/README.md) - Walkforward test with sandbox capital
3. **Place Your First Order**: [Placing Your First Order](../10-placing-first-order/README.md)

---

**Previous**: [04 - Installation Guide](../04-installation/README.md)

**Next**: [06 - Broker Connection](../06-broker-connection/README.md)
