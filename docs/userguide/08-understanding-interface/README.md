# 08 - Understanding the Interface

## Introduction

OpenAlgo's interface is designed to be intuitive while providing powerful functionality. This guide helps you navigate and understand each section.

## Main Navigation

### Top Bar

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ OpenAlgo          [Search...] Notifications Admin  ▾    │
└─────────────────────────────────────────────────────────────────────────────┘
     │                       │                    │                │
     Logo                  Search            Alerts          Profile Menu
```

| Element | Function |
|---------|----------|
| Logo | Click to go to Dashboard |
| Search | Quick symbol/page search |
| Notifications | Order alerts, system messages |
| Profile Menu | Settings, logout, theme |

### Sidebar Navigation

```
┌─────────────────────────┐
│  TRADING                │
│  ├── Dashboard          │
│  ├── Positions          │
│  ├── Order Book         │
│  ├── Trade Book         │
│  ├── Holdings           │
│  └── Funds              │
│                         │
│  API & INTEGRATION      │
│  ├── API Key            │
│  ├── Playground         │
│  └── Search             │
│                         │
│  PLATFORMS              │
│  ├── TradingView        │
│  ├── Amibroker          │
│  ├── ChartInk           │
│  └── GoCharting         │
│                         │
│  STRATEGIES             │
│  ├── Flow Builder       │
│  ├── Python Strategy    │
│  └── Strategy Manager   │
│                         │
│  MONITORING             │
│  ├── PnL Tracker        │
│  ├── Latency Monitor    │
│  └── Traffic Logs       │
│                         │
│  SETTINGS               │
│  ├── Profile            │
│  ├── Security           │
│  ├── Telegram           │
│  └── Admin              │
└─────────────────────────┘
```

## Trading Section

### Positions Page

Shows your current open positions:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Positions                                          [Refresh] [Square All] │
├─────────────────────────────────────────────────────────────────────────────┤
│  Symbol    │ Exchange │ Qty  │ Avg Price │  LTP   │  P&L    │ Actions     │
│────────────│──────────│──────│───────────│────────│─────────│─────────────│
│  SBIN      │ NSE      │ 100  │ ₹625.00   │ ₹630.50│ +₹550   │ [Exit]      │
│  RELIANCE  │ NSE      │ -50  │ ₹2450.00  │ ₹2440  │ +₹500   │ [Exit]      │
│  NIFTY..CE │ NFO      │ 50   │ ₹150.00   │ ₹165.00│ +₹750   │ [Exit]      │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Elements**:
- **Qty**: Positive = Long, Negative = Short
- **P&L**: Color-coded (green/red)
- **Exit**: One-click position exit

### Order Book Page

Shows all orders for today:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Order Book                    [All] [Pending] [Complete] [Rejected]       │
├─────────────────────────────────────────────────────────────────────────────┤
│  Time     │ Symbol  │ Type   │ Qty │ Price  │ Status   │ Actions          │
│───────────│─────────│────────│─────│────────│──────────│──────────────────│
│  10:30:15 │ SBIN    │ BUY    │ 100 │ MARKET │ Complete │ -                │
│  10:45:22 │ INFY    │ BUY LMT│ 50  │ ₹1500  │ Pending  │ [Modify][Cancel] │
│  11:00:05 │ TCS     │ SELL   │ 25  │ MARKET │ Rejected │ [Details]        │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Order Status**:
| Status | Meaning | Color |
|--------|---------|-------|
| Pending | Waiting to execute | Yellow |
| Complete | Fully executed | Green |
| Rejected | Broker rejected | Red |
| Cancelled | You cancelled | Gray |

### Trade Book Page

Shows executed trades:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Trade Book                                                   [Download]    │
├─────────────────────────────────────────────────────────────────────────────┤
│  Time     │ Symbol  │ Type │ Qty │ Price   │ Exchange │ Order ID          │
│───────────│─────────│──────│─────│─────────│──────────│───────────────────│
│  10:30:16 │ SBIN    │ BUY  │ 100 │ ₹625.50 │ NSE      │ 230125000012345   │
│  11:15:42 │ RELIANCE│ SELL │ 50  │ ₹2448.25│ NSE      │ 230125000012346   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Holdings Page

Your delivery holdings (CNC):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Holdings                                              Total: ₹5,25,000    │
├─────────────────────────────────────────────────────────────────────────────┤
│  Symbol  │ Qty  │ Avg Price │  LTP    │ Current │ P&L    │ P&L %          │
│──────────│──────│───────────│─────────│─────────│────────│────────────────│
│  HDFC    │ 100  │ ₹1500     │ ₹1650   │ ₹1,65,000│+₹15,000│ +10.0%        │
│  ICICI   │ 200  │ ₹950      │ ₹1020   │ ₹2,04,000│+₹14,000│ +7.4%         │
│  SBIN    │ 500  │ ₹400      │ ₹625    │ ₹3,12,500│+₹1,12,500│ +56.3%      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Funds Page

Account balance details:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Funds                                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────┐  ┌─────────────────────┐                          │
│  │  Available Margin   │  │  Used Margin        │                          │
│  │  ₹4,50,000          │  │  ₹50,000            │                          │
│  └─────────────────────┘  └─────────────────────┘                          │
│                                                                              │
│  ┌─────────────────────┐  ┌─────────────────────┐                          │
│  │  Total Balance      │  │  Collateral         │                          │
│  │  ₹5,00,000          │  │  ₹2,00,000          │                          │
│  └─────────────────────┘  └─────────────────────┘                          │
│                                                                              │
│  Segment-wise Breakdown:                                                    │
│  Equity     : ₹3,00,000 available                                          │
│  F&O        : ₹1,50,000 available                                          │
│  Commodity  : ₹0                                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## API & Integration Section

### API Key Page

Manage your API keys for external integrations:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  API Key Management                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Your API Key:                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  abc123def456ghi789jkl012mno345pqr678                  [Copy] [ ]  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  Order Mode:  ◉ Auto    ○ Semi-Auto                                        │
│                                                                              │
│  [Regenerate Key]   [Revoke Key]                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Playground Page

Test API calls interactively:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  API Playground                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Endpoint: [Place Order        ▾]                                          │
│                                                                              │
│  Parameters:                                                                │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  Symbol:    [SBIN          ]                                       │    │
│  │  Exchange:  [NSE           ]                                       │    │
│  │  Action:    [BUY           ]                                       │    │
│  │  Quantity:  [100           ]                                       │    │
│  │  Price:     [MARKET        ]                                       │    │
│  │  Product:   [MIS           ]                                       │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  [Execute]                                                                  │
│                                                                              │
│  Response:                                                                  │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  {                                                                  │    │
│  │    "status": "success",                                            │    │
│  │    "orderid": "230125000012345"                                    │    │
│  │  }                                                                  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Search Page

Find symbols across exchanges:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Symbol Search                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  [Search symbol...                          ] [NSE ▾] [Search]             │
│                                                                              │
│  Results:                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Symbol      │ Exchange │ Type    │ Lot Size │ [Select]             │   │
│  │──────────────│──────────│─────────│──────────│──────────────────────│   │
│  │  SBIN        │ NSE      │ Equity  │ 1        │ [Copy Symbol]        │   │
│  │  SBIN        │ BSE      │ Equity  │ 1        │ [Copy Symbol]        │   │
│  │  SBIN25JAN600CE│ NFO    │ Option  │ 1500     │ [Copy Symbol]        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Platform Integration Section

### TradingView Page

Configure TradingView webhook:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TradingView Integration                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Webhook URL:                                                               │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  http://your-server:5000/api/v1/placeorder            [Copy]        │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  JSON Template:                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  {                                                                  │    │
│  │    "apikey": "your-api-key",                                       │    │
│  │    "strategy": "TradingView",                                      │    │
│  │    "symbol": "{{ticker}}",                                         │    │
│  │    "action": "{{strategy.order.action}}",                          │    │
│  │    "quantity": "100"                                               │    │
│  │  }                                                                  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  [Copy Template]                                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Monitoring Section

### PnL Tracker

Visual profit/loss tracking:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PnL Tracker                                                   [Today ▾]   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐              │
│  │ Realized   │ │ Unrealized │ │   Total    │ │    ROI     │              │
│  │  +₹2,500   │ │  +₹1,250   │ │  +₹3,750   │ │   +0.75%   │              │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘              │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ P&L Chart                                                        │   │
│  │       ₹                                                              │   │
│  │    4000│        ╭──────╮                                            │   │
│  │    3000│    ╭───╯      ╰──╮                                         │   │
│  │    2000│╭───╯              ╰──────                                  │   │
│  │    1000│                                                            │   │
│  │       0├────────────────────────────► Time                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Common UI Elements

### Buttons

| Button Style | Usage |
|-------------|-------|
| Primary (Blue) | Main actions (Submit, Save) |
| Secondary (Gray) | Secondary actions (Cancel, Back) |
| Danger (Red) | Destructive actions (Delete, Exit) |
| Success (Green) | Positive actions (Approve, Enable) |

### Status Badges

| Badge | Meaning |
|-------|---------|
| | Active/Success/Connected |
| | Pending/Warning |
| | Error/Failed/Disconnected |
| | Inactive/Neutral |

### Tooltips

Hover over any (?) icon to see helpful explanations.

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `/` | Focus search |
| `Esc` | Close modals |
| `Ctrl+K` | Command palette |

---

**Previous**: [07 - Dashboard Overview](../07-dashboard-overview/README.md)

**Next**: [09 - API Key Management](../09-api-key-management/README.md)
