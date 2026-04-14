# 07 - Dashboard Overview

## Introduction

The Dashboard is your command center in OpenAlgo. It provides a quick snapshot of your trading activity, account status, and key metrics at a glance.

## Accessing the Dashboard

After logging in, the Dashboard is your default landing page:
```
http://127.0.0.1:5000/dashboard
```

Or click **Dashboard** in the navigation menu.

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  OpenAlgo                              🔔  👤 Admin  [Logout]               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Account Summary                                   │   │
│  │                                                                      │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐              │   │
│  │  │Available │ │  Used    │ │  Total   │ │  Day's   │              │   │
│  │  │ Margin   │ │  Margin  │ │  Balance │ │   P&L    │              │   │
│  │  │₹4,50,000 │ │₹50,000   │ │₹5,00,000 │ │ +₹2,500  │              │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────┐ ┌──────────────────────────────────┐    │
│  │    Broker Status             │ │    Quick Actions                  │    │
│  │                              │ │                                   │    │
│  │  Broker: Zerodha            │ │  [Login to Broker]               │    │
│  │  Status: 🟢 Connected       │ │  [Place Order]                   │    │
│  │  User: AB1234               │ │  [View Positions]                │    │
│  │  Last Login: 9:05 AM        │ │  [API Playground]                │    │
│  └──────────────────────────────┘ └──────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Today's Activity                                  │   │
│  │                                                                      │   │
│  │  Orders: 12    │    Trades: 8    │    Pending: 2    │    Failed: 0  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Dashboard Components

### 1. Account Summary Cards

Four key metrics displayed as cards:

| Card | What It Shows |
|------|---------------|
| **Available Margin** | Money available for new trades |
| **Used Margin** | Money currently blocked in positions |
| **Total Balance** | Complete account value |
| **Day's P&L** | Today's profit or loss |

**Color Coding**:
- 🟢 Green = Positive/Profit
- 🔴 Red = Negative/Loss
- ⚪ Gray = Neutral/Zero

### 2. Broker Status

Shows your broker connection:

| Field | Description |
|-------|-------------|
| Broker | Which broker you're using |
| Status | Connected/Disconnected |
| User ID | Your broker trading ID |
| Last Login | When you logged in |

**Status Indicators**:
- 🟢 **Connected**: Ready to trade
- 🔴 **Disconnected**: Need to login
- 🟡 **Reconnecting**: Attempting to reconnect

### 3. Quick Actions

One-click buttons for common tasks:

| Button | Action |
|--------|--------|
| Login to Broker | Open broker login |
| Place Order | Go to order form |
| View Positions | See current positions |
| API Playground | Test API calls |

### 4. Today's Activity

Summary of trading activity:

| Metric | Meaning |
|--------|---------|
| **Orders** | Total orders placed today |
| **Trades** | Orders that executed |
| **Pending** | Orders waiting to execute |
| **Failed** | Orders that failed |

## Navigation Menu

The sidebar provides access to all features:

```
┌──────────────────────┐
│  📊 Dashboard        │  ← You are here
│  📈 Positions        │
│  📋 Order Book       │
│  📜 Trade Book       │
│  💼 Holdings         │
│  💰 Funds            │
│  ──────────────────  │
│  🔑 API Key          │
│  🎮 Playground       │
│  ──────────────────  │
│  📺 TradingView      │
│  📉 ChartInk         │
│  🔄 Flow Builder     │
│  🐍 Python Strategy  │
│  ──────────────────  │
│  📊 PnL Tracker      │
│  ⏱️ Latency Monitor  │
│  📝 Traffic Logs     │
│  ──────────────────  │
│  ⚙️ Settings         │
│  🔒 Security         │
└──────────────────────┘
```

## Understanding Your Balances

### Available Margin

This is money you can use for new trades:

```
Available = Total Balance - Used Margin - Blocked Amounts
```

### Used Margin

Money currently locked in open positions:

- **MIS positions**: Requires margin (leverage)
- **NRML F&O**: Requires span margin
- **CNC delivery**: Full amount blocked

### Day's P&L Calculation

```
Day's P&L = Realized P&L + Unrealized P&L

Realized P&L   = Profit/loss from closed trades
Unrealized P&L = Profit/loss from open positions (mark-to-market)
```

## Dashboard Refresh

### Automatic Refresh

The dashboard automatically updates:
- Account balances: Every 30 seconds
- Positions P&L: Real-time (WebSocket)
- Order status: Real-time (WebSocket)

### Manual Refresh

Click the refresh icon (🔄) to force update all data.

## Analyzer Mode Indicator

When Analyzer (sandbox testing) mode is ON:

```
┌─────────────────────────────────────────────────────────────────┐
│  ⚠️ ANALYZER MODE ACTIVE - Sandbox testing mode                 │
│  Sandbox Balance: ₹1,00,00,000                                  │
└─────────────────────────────────────────────────────────────────┘
```

This reminds you that:
- Orders go to sandbox account
- No real money at risk
- Good for testing strategies

## Mobile View

On mobile devices, the dashboard adapts:

```
┌─────────────────────┐
│  Account Summary    │
│  ┌───┐ ┌───┐       │
│  │Avl│ │Used│       │
│  │4.5L│ │50K│       │
│  └───┘ └───┘       │
│  ┌───┐ ┌───┐       │
│  │Tot│ │P&L│       │
│  │5L │ │+2K│       │
│  └───┘ └───┘       │
│                     │
│  Broker: 🟢 Online  │
│                     │
│  [≡ Menu]           │
└─────────────────────┘
```

## Customizing Dashboard

### Theme Selection

1. Go to **Profile** → **Appearance**
2. Choose:
   - Light mode
   - Dark mode
   - System preference

### Accent Colors

8 accent colors available:
- Blue (default)
- Green
- Purple
- Orange
- Red
- Yellow
- Pink
- Cyan

## Common Dashboard Questions

### Q: Why is my balance showing ₹0?

**Causes**:
- Not logged into broker
- Broker session expired
- API connection issue

**Solution**: Click "Login to Broker"

### Q: P&L not updating?

**Causes**:
- WebSocket disconnected
- Market closed
- No open positions

**Solution**: Refresh page or check broker connection

### Q: Dashboard loading slowly?

**Causes**:
- Slow internet
- Broker API slow
- Too many positions

**Solution**: Wait or refresh. Check network.

## Dashboard Best Practices

### Morning Routine

1. ☐ Open OpenAlgo
2. ☐ Login to broker
3. ☐ Verify "Connected" status
4. ☐ Check available margin
5. ☐ Review any pending orders

### During Trading

1. ☐ Monitor P&L periodically
2. ☐ Check for failed orders
3. ☐ Watch position count

### End of Day

1. ☐ Review Day's P&L
2. ☐ Check all orders executed
3. ☐ Verify positions closed (if intraday)

---

**Previous**: [06 - Broker Connection](../06-broker-connection/README.md)

**Next**: [08 - Understanding the Interface](../08-understanding-interface/README.md)
