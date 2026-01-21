# 10 - Placing Your First Order

## Introduction

This is the exciting part - placing your first order through OpenAlgo! We'll start with the Analyzer (sandbox testing) mode to practice safely, then show you how to go live.

## Before You Begin

Ensure you have:
- [ ] OpenAlgo running
- [ ] Logged into your broker
- [ ] API key generated
- [ ] Understand order types (review [Module 02](../02-key-concepts/README.md) if needed)

## Method 1: Using the Playground (Easiest)

The Playground is the best way to start - it's a visual interface to test orders.

### Step 1: Enable Analyzer Mode (Recommended for First Order)

1. Go to **Analyzer** page
2. Click **Enable Analyzer Mode**
3. You now have ₹1 Crore sandbox capital to practice

```
┌─────────────────────────────────────────────────────────────────┐
│  ⚠️ ANALYZER MODE ACTIVE                                        │
│  Orders will NOT go to your real broker                         │
│  Sandbox Balance: ₹1,00,00,000                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Step 2: Open Playground

Navigate to **Playground** in the sidebar.

### Step 3: Fill Order Details

```
┌─────────────────────────────────────────────────────────────────┐
│  Place Order                                                     │
│                                                                  │
│  Symbol:      [SBIN                    ]                        │
│  Exchange:    [NSE           ▾]                                 │
│  Action:      [BUY           ▾]                                 │
│  Quantity:    [100                     ]                        │
│  Price Type:  [MARKET        ▾]                                 │
│  Product:     [MIS           ▾]                                 │
│  Strategy:    [MyFirstOrder            ]                        │
│                                                                  │
│  [Place Order]                                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

Fill in:
| Field | Value | Explanation |
|-------|-------|-------------|
| Symbol | SBIN | State Bank of India stock |
| Exchange | NSE | National Stock Exchange |
| Action | BUY | We're buying shares |
| Quantity | 100 | Number of shares |
| Price Type | MARKET | Buy at current price |
| Product | MIS | Intraday (will auto-close) |
| Strategy | MyFirstOrder | Label for tracking |

### Step 4: Execute Order

1. Click **Place Order**
2. Wait for response
3. You should see:

```json
{
  "status": "success",
  "orderid": "230125000012345"
}
```

### Step 5: Verify Order

1. Go to **Order Book**
2. Find your order
3. Status should be "Complete" (for market orders)

4. Go to **Positions**
5. See your new SBIN position

Congratulations! You've placed your first order! 🎉

## Method 2: Using API (For Automation)

### Using cURL

```bash
curl -X POST http://127.0.0.1:5000/api/v1/placeorder \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "YOUR_API_KEY",
    "strategy": "CurlTest",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": "100",
    "pricetype": "MARKET",
    "product": "MIS"
  }'
```

### Using Python

```python
from openalgo import api

# Connect to OpenAlgo
client = api(
    api_key="YOUR_API_KEY",
    host="http://127.0.0.1:5000"
)

# Place order
response = client.place_order(
    symbol="SBIN",
    exchange="NSE",
    action="BUY",
    quantity=100,
    price_type="MARKET",
    product="MIS",
    strategy="PythonTest"
)

print(response)
# {'status': 'success', 'orderid': '230125000012345'}
```

## Understanding the Order Response

### Success Response

```json
{
  "status": "success",
  "orderid": "230125000012345"
}
```

| Field | Meaning |
|-------|---------|
| status | "success" = order accepted |
| orderid | Unique identifier from broker |

### Error Response

```json
{
  "status": "error",
  "message": "Insufficient margin"
}
```

Common error messages:
| Error | Cause | Solution |
|-------|-------|----------|
| Insufficient margin | Not enough funds | Reduce quantity or add funds |
| Invalid symbol | Symbol not found | Check symbol format |
| Market closed | Trading hours over | Wait for market to open |
| Invalid quantity | Wrong lot size | Use correct lot size |

## Order Flow Visualization

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Order Flow                                            │
│                                                                              │
│  1. You submit order                                                        │
│         │                                                                    │
│         ▼                                                                    │
│  2. OpenAlgo validates                                                      │
│         │                                                                    │
│         ├──→ Invalid? Return error                                          │
│         │                                                                    │
│         ▼                                                                    │
│  3. Check Analyzer Mode                                                     │
│         │                                                                    │
│         ├──→ ON?  Execute in sandbox (virtual)                              │
│         │                                                                    │
│         ▼                                                                    │
│  4. Check Order Mode                                                        │
│         │                                                                    │
│         ├──→ Semi-Auto? Queue in Action Center                              │
│         │                                                                    │
│         ▼                                                                    │
│  5. Send to Broker                                                          │
│         │                                                                    │
│         ▼                                                                    │
│  6. Broker executes                                                         │
│         │                                                                    │
│         ▼                                                                    │
│  7. Return order ID                                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Practice Exercises

### Exercise 1: Market Buy Order

Place a market buy order:
- Symbol: INFY
- Exchange: NSE
- Quantity: 50
- Product: MIS

### Exercise 2: Limit Buy Order

Place a limit order:
- Symbol: TCS
- Exchange: NSE
- Action: BUY
- Quantity: 25
- Price Type: LIMIT
- Price: ₹3500 (below current price)

Watch it appear as "Pending" in order book.

### Exercise 3: Sell Order

First, ensure you have a position from Exercise 1, then:
- Symbol: INFY
- Exchange: NSE
- Action: SELL
- Quantity: 50
- Product: MIS

### Exercise 4: Exit Position

Use the Positions page:
1. Find your SBIN position
2. Click **Exit**
3. Watch it close

## Going Live (Real Orders)

Once comfortable with sandbox testing:

### Step 1: Disable Analyzer Mode

1. Go to **Analyzer** page
2. Click **Disable Analyzer Mode**
3. Confirm you want to trade with real money

### Step 2: Verify Broker Connection

- Check broker status is 🟢 Connected
- Verify available margin

### Step 3: Start Small

For your first real order:
- Use small quantity
- Choose liquid stocks (SBIN, RELIANCE, INFY)
- Use MARKET orders (guaranteed execution)
- Use MIS (auto-closes if you forget)

### Step 4: Place Real Order

Same process as before, but now:
- Orders go to real broker
- Real money at stake
- Real positions created

## Order Checklist

Before every order:

- [ ] Correct symbol?
- [ ] Correct exchange (NSE/NFO/MCX)?
- [ ] BUY or SELL correct?
- [ ] Quantity correct?
- [ ] Price type appropriate?
- [ ] Sufficient margin available?
- [ ] Analyzer mode ON/OFF as intended?

## Common First-Order Mistakes

### Mistake 1: Wrong Exchange

**Problem**: Trying to buy NIFTY options on NSE
**Solution**: Use NFO for futures and options

### Mistake 2: Wrong Lot Size

**Problem**: Buying 100 NIFTY options (should be lot size of 50)
**Solution**: Check lot size in Search page

### Mistake 3: CNC for F&O

**Problem**: Using CNC product for options
**Solution**: Use NRML for overnight F&O, MIS for intraday

### Mistake 4: Forgetting Strategy Name

**Problem**: Empty strategy field
**Solution**: Always name your strategy for tracking

## What's Next?

Now that you can place orders:

1. **Learn Order Types**: [Module 11](../11-order-types/README.md) - Understand all order types
2. **Try Smart Orders**: [Module 12](../12-smart-orders/README.md) - Position-aware orders
3. **Automate with TradingView**: [Module 16](../16-tradingview-integration/README.md)

---

**Previous**: [09 - API Key Management](../09-api-key-management/README.md)

**Next**: [11 - Order Types Explained](../11-order-types/README.md)
