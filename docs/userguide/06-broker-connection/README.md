# 06 - Broker Connection

## Introduction

OpenAlgo supports 24+ Indian brokers through a unified interface. This guide covers connecting your broker account and understanding the authentication process.

## Supported Brokers

### Full List of Supported Brokers

| Broker | Auth Type | Auto Login |
|--------|-----------|------------|
| Zerodha (Kite) | OAuth2 | No |
| Angel One | API Key | Yes* |
| Dhan | API Key | Yes |
| Fyers | OAuth2 | No |
| Upstox | OAuth2 | No |
| 5paisa | OAuth2 | No |
| 5paisa XTS | API Key | Yes |
| Kotak Neo | OAuth2 | No |
| Flattrade | API Key | Yes |
| Shoonya (Finvasia) | API Key | Yes |
| AliceBlue | API Key | Yes |
| Firstock | API Key | Yes |
| IIFL | API Key | Yes |
| Motilal Oswal | OAuth2 | No |
| Samco | API Key | Yes |
| Groww | OAuth2 | No |
| Paytm Money | OAuth2 | No |
| Pocketful | API Key | Yes |
| Tradejini | API Key | Yes |
| Zebu | API Key | Yes |
| Mstock | API Key | Yes |
| Wisdom Capital | API Key | Yes |
| JainamXTS | API Key | Yes |
| Compositedge | API Key | Yes |
| Definedge | API Key | Yes |
| Indmoney | API Key | Yes |

*Auto Login requires TOTP key configuration

## Getting Broker API Credentials

### Zerodha (Kite Connect)

1. Go to [kite.trade](https://kite.trade)
2. Login with your Zerodha credentials
3. Create a new app under "Apps"
4. Note down:
   - **API Key**
   - **API Secret**
5. Set redirect URL to: `http://127.0.0.1:5000/callback/zerodha`

**Cost**: ₹2,000/month for Kite Connect

### Angel One (Smart API)

1. Go to [smartapi.angelbroking.com](https://smartapi.angelbroking.com)
2. Login and generate API credentials
3. Note down:
   - **API Key**
   - **Client Code** (your trading ID)
4. You'll also need your:
   - **Password**
   - **TOTP Secret** (for auto-login)

**Cost**: Free

### Dhan

1. Go to [api.dhan.co](https://api.dhan.co)
2. Login with Dhan credentials
3. Generate access token
4. Note down:
   - **Client ID**
   - **Access Token**

**Cost**: Free

### Fyers

1. Go to [myapi.fyers.in](https://myapi.fyers.in)
2. Create developer account
3. Create an app
4. Note down:
   - **App ID**
   - **Secret ID**

**Cost**: Free

### Upstox

1. Go to [developer.upstox.com](https://developer.upstox.com)
2. Create developer account
3. Create an app
4. Note down:
   - **API Key**
   - **API Secret**

**Cost**: Free

## Configuring Broker in OpenAlgo

### Method 1: Via .env File

Edit your `.env` file:

```ini
# Select your broker
BROKER=zerodha

# Zerodha specific
BROKER_API_KEY=your_api_key_here
BROKER_API_SECRET=your_api_secret_here
```

For Angel One:
```ini
BROKER=angel
BROKER_API_KEY=your_api_key
BROKER_CLIENT_CODE=your_client_code
BROKER_PASSWORD=your_password
BROKER_TOTP_KEY=your_totp_secret
```

### Method 2: Via Web Interface

1. Login to OpenAlgo
2. Go to **Profile** → **Broker Configuration**
3. Select your broker from dropdown
4. Enter credentials in the form
5. Click **Save**

## Logging into Your Broker

### OAuth2 Brokers (Zerodha, Fyers, etc.)

1. In OpenAlgo, click **Login to Broker**
2. You're redirected to broker's login page
3. Enter your broker credentials
4. Approve the connection
5. Automatically redirected back to OpenAlgo

```
OpenAlgo → Broker Login Page → Enter Credentials → Approve → Back to OpenAlgo
```

### API Key Brokers (Dhan, Angel, etc.)

1. Credentials already in .env or profile
2. Click **Login to Broker**
3. OpenAlgo uses stored credentials
4. Connection established automatically

## Understanding Authentication

### Daily Login Requirement

Most brokers require you to login every trading day:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Typical Trading Day                          │
│                                                                  │
│  8:30 AM  - Login to OpenAlgo                                   │
│  8:35 AM  - Login to Broker                                     │
│  9:15 AM  - Market Opens (you're ready to trade)                │
│  3:30 PM  - Market Closes                                       │
│  ~6:00 PM - Broker session expires                              │
│                                                                  │
│  Next Day - Login again                                         │
└─────────────────────────────────────────────────────────────────┘
```

### Auto-Login (TOTP Based)

Some brokers support automatic login using TOTP:

**Requirements**:
- Broker TOTP secret key
- Configure in `.env` or profile

**Supported Brokers for Auto-Login**:
- Angel One
- Flattrade
- Shoonya
- AliceBlue

**How to get TOTP Secret**:
1. During broker 2FA setup
2. Choose "Enter code manually" instead of scanning QR
3. Copy the secret key shown
4. Store in `BROKER_TOTP_KEY`

### Token Storage

OpenAlgo stores broker tokens:
- Encrypted in database
- Never stored in plain text
- Auto-deleted on logout

## Connection Status

### Checking Connection

In OpenAlgo dashboard, you'll see:

| Status | Meaning |
|--------|---------|
| 🟢 Connected | Broker session active |
| 🔴 Disconnected | Need to login |
| 🟡 Connecting | Login in progress |

### What "Connected" Means

When connected, you can:
- Place orders
- View positions
- Check holdings
- Get market data

### What Happens When Disconnected

- Orders will fail
- Real-time data stops
- Need to re-login

## Handling Multiple Brokers

### Switching Brokers

1. Update `BROKER=` in `.env` to new broker
2. Update corresponding credentials
3. Restart OpenAlgo
4. Login to new broker

**Note**: Only one broker active at a time per instance

### Running Multiple Instances

To use multiple brokers simultaneously:

1. Install OpenAlgo in separate folders
2. Configure each with different broker
3. Run on different ports

```bash
# Instance 1 (Zerodha on port 5000)
FLASK_PORT=5000 uv run app.py

# Instance 2 (Angel on port 5001)
FLASK_PORT=5001 uv run app.py
```

## Connection Troubleshooting

### Issue: "Invalid API credentials"

**Causes**:
- Typo in API key/secret
- Extra spaces in credentials
- Expired credentials

**Solutions**:
- Double-check credentials
- Remove any spaces
- Regenerate from broker

### Issue: "Broker not responding"

**Causes**:
- Broker server down
- Network issues
- Market closed

**Solutions**:
- Check broker status page
- Try broker's website
- Wait and retry

### Issue: "TOTP verification failed"

**Causes**:
- Wrong TOTP secret
- Time sync issue
- Clock drift

**Solutions**:
- Verify TOTP secret
- Sync device time
- Regenerate TOTP

### Issue: "Session expired"

**Normal behavior** - sessions expire daily.

**Solution**: Login again when markets open.

## Best Practices

### Security

1. **Never share** broker credentials
2. **Use strong passwords** for broker accounts
3. **Enable 2FA** on broker account
4. **Restrict IP** if broker supports it

### Reliability

1. **Login early** - Before market opens (8:30-9:00 AM)
2. **Check status** - Verify connection before trading
3. **Have backup** - Know broker's web/mobile as fallback
4. **Monitor** - Watch for disconnections

### For VPS Users

1. Use static IP if possible
2. Some brokers restrict new IPs
3. Whitelist VPS IP with broker
4. Consider VPN if required

## Broker-Specific Notes

### Zerodha
- Kite Connect costs ₹2,000/month
- Order rate limit: 10/second
- Historical data available

### Angel One
- Free API access
- TOTP required for trading
- Good for beginners

### Dhan
- Free API access
- Simple token-based auth
- Has sandbox mode

### Fyers
- Free API access
- Good historical data
- Web-based OAuth

---

**Previous**: [05 - First-Time Setup](../05-first-time-setup/README.md)

**Next**: [07 - Dashboard Overview](../07-dashboard-overview/README.md)
