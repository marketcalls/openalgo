# 22 - Action Center

## Introduction

The Action Center is OpenAlgo's order approval system for managed trading environments. It allows you to review, approve, modify, or reject orders before they're sent to your broker.

## When to Use Action Center

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Trading Modes in OpenAlgo                                │
│                                                                              │
│  AUTO MODE                              SEMI-AUTO MODE (Action Center)      │
│  ─────────                              ─────────────────────────────       │
│                                                                              │
│  Signal → Order Executed                Signal → Pending Approval           │
│  (Immediate)                                           │                    │
│                                                        ▼                    │
│                                              ┌─────────────────┐            │
│                                              │  Review Order   │            │
│                                              │  ┌───────────┐  │            │
│                                              │  │ Approve   │  │            │
│                                              │  │ Modify    │  │            │
│                                              │  │ Reject    │  │            │
│                                              │  └───────────┘  │            │
│                                              └─────────────────┘            │
│                                                        │                    │
│  Best for:                                             ▼                    │
│  • Personal trading                        Order Executed or Cancelled      │
│  • Trusted strategies                                                       │
│  • Fast execution                        Best for:                          │
│                                          • Managed accounts                 │
│                                          • New strategies                   │
│                                          • Risk management                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Enabling Action Center

### Step 1: Access Settings

1. Go to **Settings** in OpenAlgo
2. Find **Order Mode** section

### Step 2: Select Semi-Auto Mode

1. Change mode from "Auto" to "Semi-Auto"
2. Click **Save Settings**

### Step 3: Verify

- All incoming orders now route to Action Center
- No orders execute automatically

## Using the Action Center

### Accessing Action Center

Navigate to **Action Center** in the sidebar.

### Interface Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Action Center                                     [Approve All] [Clear]    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Filters: [All ▾]  [All Strategies ▾]  [All Symbols ▾]                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  📥 Pending Orders (3)                                               │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │                                                                      │   │
│  │  #1 | SBIN | BUY 100 @ MARKET                                       │   │
│  │  Strategy: MA_Crossover | Time: 10:30:15                            │   │
│  │  [✓ Approve] [✏ Modify] [✗ Reject]                                  │   │
│  │                                                                      │   │
│  │  #2 | HDFCBANK | SELL 50 @ LIMIT 1650                               │   │
│  │  Strategy: RSI_Strategy | Time: 10:31:22                            │   │
│  │  [✓ Approve] [✏ Modify] [✗ Reject]                                  │   │
│  │                                                                      │   │
│  │  #3 | NIFTY30JAN2521500CE | BUY 50 @ MARKET                         │   │
│  │  Strategy: Options_Strategy | Time: 10:32:45                         │   │
│  │  [✓ Approve] [✏ Modify] [✗ Reject]                                  │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Order Details

Click on an order to see full details:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Order Details                                                    [Close]   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Symbol:        SBIN                                                        │
│  Exchange:      NSE                                                         │
│  Action:        BUY                                                         │
│  Quantity:      100                                                         │
│  Price Type:    MARKET                                                      │
│  Product:       MIS                                                         │
│  Strategy:      MA_Crossover                                                │
│                                                                              │
│  Received:      2025-01-21 10:30:15                                        │
│  Source:        TradingView Webhook                                         │
│                                                                              │
│  Original Request:                                                          │
│  {                                                                          │
│    "symbol": "SBIN",                                                        │
│    "exchange": "NSE",                                                       │
│    "action": "BUY",                                                         │
│    "quantity": "100"                                                        │
│  }                                                                          │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │   Approve    │  │    Modify    │  │    Reject    │                      │
│  └──────────────┘  └──────────────┘  └──────────────┘                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Order Actions

### Approve Order

Sends the order to broker as-is.

1. Review order details
2. Click **Approve**
3. Order executes immediately
4. Confirmation shown

### Modify Order

Change order parameters before execution.

1. Click **Modify**
2. Edit fields:
   - Quantity
   - Price (for limit orders)
   - Product type
3. Click **Save & Approve**
4. Modified order executes

### Reject Order

Cancel the order without execution.

1. Click **Reject**
2. Optionally add rejection reason
3. Order is cancelled
4. No trade executes

## Batch Operations

### Approve All

Approve all pending orders at once.

1. Click **Approve All** button
2. Confirm action
3. All orders sent to broker

### Filter and Approve

Approve specific subset:

1. Apply filters (strategy, symbol)
2. Click **Approve Filtered**
3. Only filtered orders approved

### Clear Old Orders

Remove expired or outdated orders:

1. Click **Clear**
2. Select age threshold (e.g., older than 5 minutes)
3. Orders removed from queue

## Filters and Sorting

### Filter Options

| Filter | Options |
|--------|---------|
| Status | Pending, Approved, Rejected |
| Strategy | List of active strategies |
| Symbol | List of symbols |
| Exchange | NSE, NFO, MCX, etc. |
| Action | BUY, SELL |

### Sort Options

| Sort By | Description |
|---------|-------------|
| Time (Newest) | Most recent first |
| Time (Oldest) | Oldest first |
| Symbol | Alphabetical |
| Strategy | By strategy name |

## Action History

### Viewing History

1. Go to **Action Center**
2. Click **History** tab
3. View past decisions

### History Entry

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Action History                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Time         │ Symbol │ Action │ Decision │ Order ID                       │
│  ─────────────│────────│────────│──────────│───────────                     │
│  10:30:15     │ SBIN   │ BUY    │ Approved │ 230125000012345                │
│  10:31:22     │ HDFC   │ SELL   │ Modified │ 230125000012346                │
│  10:32:45     │ INFY   │ BUY    │ Rejected │ -                              │
│  10:35:10     │ TCS    │ BUY    │ Approved │ 230125000012347                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Notifications

### Real-time Alerts

When orders arrive in Action Center:

1. **Browser Notification**: Desktop alert
2. **Sound Alert**: Audio notification (configurable)
3. **Telegram**: Optional Telegram message
4. **Badge Count**: Shows pending count

### Configuring Notifications

1. Go to **Settings** → **Notifications**
2. Enable/disable notification types
3. Set sound preferences
4. Configure Telegram alerts

## Best Practices

### 1. Set Reasonable Review Time

Don't let orders wait too long:
- Market conditions change
- Prices move
- Signals become stale

### 2. Use Filters Effectively

For high-volume scenarios:
- Filter by strategy
- Group similar orders
- Batch approve when appropriate

### 3. Monitor Continuously

During market hours:
- Keep Action Center visible
- Enable notifications
- Check regularly

### 4. Document Rejections

When rejecting orders:
- Note the reason
- Review for patterns
- Adjust strategies if needed

### 5. Test New Strategies

Use Action Center to:
- Verify new strategy signals
- Check order parameters
- Build confidence before auto-mode

## Use Cases

### Use Case 1: Managed Accounts

For investment advisors managing client funds:

```
Client Strategy Signal
        │
        ▼
┌─────────────────┐
│  Action Center  │  ← Advisor reviews
│                 │
│  ✓ Check risk   │
│  ✓ Verify size  │
│  ✓ Confirm fit  │
│                 │
└─────────────────┘
        │
        ▼
   Execute Order
```

### Use Case 2: Strategy Validation

Testing new strategies:

```
Week 1: Semi-Auto Mode
  - Review all signals
  - Track accuracy
  - Note improvements

Week 2-4: Continued Review
  - Build confidence
  - Measure performance

Week 5+: Switch to Auto (if satisfied)
```

### Use Case 3: Risk Management

High-value trades:

```
Small trades (<₹50k): Auto Mode
Large trades (>₹50k): Action Center

Configure via:
- Strategy-specific settings
- Quantity thresholds
```

## API Integration

### Checking Pending Orders

```python
# Get pending orders
response = client.get_pending_actions()

for order in response['data']:
    print(f"Pending: {order['symbol']} {order['action']}")
```

### Approving via API

```python
# Approve specific order
client.approve_action(action_id="12345")

# Approve all for strategy
client.approve_all_actions(strategy="MA_Crossover")
```

### Rejecting via API

```python
# Reject order
client.reject_action(
    action_id="12345",
    reason="Price moved unfavorably"
)
```

## Troubleshooting

### Orders Not Appearing

| Issue | Solution |
|-------|----------|
| Mode not set | Enable Semi-Auto mode |
| Wrong strategy | Check strategy name |
| Filter active | Clear filters |
| Browser cache | Refresh page |

### Orders Expiring

| Issue | Solution |
|-------|----------|
| Too slow to review | Approve faster |
| Not monitoring | Enable notifications |
| High volume | Use batch operations |

### Notifications Not Working

| Issue | Solution |
|-------|----------|
| Browser permissions | Allow notifications |
| Telegram not configured | Set up Telegram bot |
| Sound muted | Check browser audio |

---

**Previous**: [21 - Flow Visual Strategy Builder](../21-flow-visual-builder/README.md)

**Next**: [23 - Telegram Bot](../23-telegram-bot/README.md)
