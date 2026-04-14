# 24 - PnL Tracker

## Introduction

The PnL (Profit and Loss) Tracker in OpenAlgo provides comprehensive analytics on your trading performance. Track realized and unrealized P&L, analyze trade statistics, and monitor your equity curve over time.

## Accessing PnL Tracker

Navigate to **PnL** in the sidebar to access the tracker.

## Dashboard Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PnL Tracker                                    [Today] [Week] [Month] [YTD]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  Today's P&L    │  │  Realized P&L   │  │  Unrealized P&L │             │
│  │  ₹8,750         │  │  ₹6,500         │  │  ₹2,250         │             │
│  │  +2.16%         │  │                 │  │                 │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        EQUITY CURVE                                  │   │
│  │  ₹4.2L │      ∧        ∧                                            │   │
│  │        │     / \      / \      ∧                                    │   │
│  │  ₹4.1L │    /   \    /   \    / \    ∧                              │   │
│  │        │   /     \  /     \  /   \  / \                             │   │
│  │  ₹4.0L │  /       \/       \/     \/   ────                         │   │
│  │        │─────────────────────────────────────                        │   │
│  │        Jan 15  Jan 17  Jan 19  Jan 21                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌────────────────────────────┐  ┌────────────────────────────┐            │
│  │  TRADE STATISTICS         │  │  STRATEGY PERFORMANCE      │            │
│  │  ────────────────          │  │  ─────────────────          │            │
│  │  Total Trades: 45          │  │  MA_Crossover: +₹5,200     │            │
│  │  Winners: 28 (62%)         │  │  RSI_Strategy: +₹2,100     │            │
│  │  Losers: 17 (38%)          │  │  Scalping: +₹1,450         │            │
│  │  Avg Win: ₹850             │  │                             │            │
│  │  Avg Loss: ₹420            │  │                             │            │
│  │  Win/Loss Ratio: 2.02      │  │                             │            │
│  └────────────────────────────┘  └────────────────────────────┘            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## P&L Components

### Realized P&L

Profit/loss from closed positions:

```
Realized P&L = Σ (Exit Price - Entry Price) × Quantity

For each closed trade:
- Long: (Sell Price - Buy Price) × Qty
- Short: (Entry Price - Cover Price) × Qty
```

### Unrealized P&L

Profit/loss from open positions:

```
Unrealized P&L = Σ (Current Price - Entry Price) × Quantity

For open positions:
- Long: (LTP - Avg Price) × Qty
- Short: (Avg Price - LTP) × Qty
```

### Total P&L

```
Total P&L = Realized P&L + Unrealized P&L
```

## Time Period Views

### Today

- Current day's trading activity
- Real-time updates
- Intraday trades and positions

### This Week

- Monday to current day
- Daily breakdown available
- Week-over-week comparison

### This Month

- Current month statistics
- Daily and weekly views
- Month-over-month comparison

### Year to Date (YTD)

- January 1st to current date
- Monthly breakdown
- Annual performance trends

### Custom Range

Select specific date range:
1. Click **Custom**
2. Select start date
3. Select end date
4. Click **Apply**

## Detailed Analytics

### Trade Log

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Trade Log                                              [Export CSV]        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Date       Symbol    Action  Qty   Entry    Exit     P&L      Strategy    │
│  ─────────  ────────  ──────  ────  ───────  ───────  ───────  ──────────  │
│  21-Jan-25  SBIN      BUY     100   625.00   630.00   +₹500    MA_Cross    │
│  21-Jan-25  HDFC      SELL    50    1650.00  1640.00  +₹500    RSI_Strat   │
│  21-Jan-25  INFY      BUY     75    1550.00  1545.00  -₹375    MA_Cross    │
│  20-Jan-25  SBIN      BUY     100   620.00   628.00   +₹800    MA_Cross    │
│  20-Jan-25  TCS       SELL    25    3450.00  3480.00  -₹750    Scalping    │
│                                                                              │
│  Page 1 of 10                              [< Prev]  [1] [2] [3]  [Next >] │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Trade Statistics

| Metric | Description | Example |
|--------|-------------|---------|
| Total Trades | Number of closed trades | 45 |
| Winning Trades | Profitable trades | 28 (62%) |
| Losing Trades | Unprofitable trades | 17 (38%) |
| Average Win | Avg profit per winning trade | ₹850 |
| Average Loss | Avg loss per losing trade | ₹420 |
| Largest Win | Biggest single profit | ₹3,500 |
| Largest Loss | Biggest single loss | ₹1,200 |
| Win/Loss Ratio | Avg Win ÷ Avg Loss | 2.02 |
| Profit Factor | Gross Profit ÷ Gross Loss | 2.5 |
| Expectancy | Expected return per trade | ₹250 |

### Strategy Breakdown

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Strategy Performance                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Strategy        Trades  Win%   P&L        Avg Trade  Max DD               │
│  ───────────────  ──────  ─────  ─────────  ─────────  ──────               │
│  MA_Crossover    20      65%    +₹5,200    +₹260      -₹1,200              │
│  RSI_Strategy    15      60%    +₹2,100    +₹140      -₹800                │
│  Scalping        10      70%    +₹1,450    +₹145      -₹500                │
│                                                                              │
│  Total           45      62%    +₹8,750    +₹194      -₹1,200              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Symbol Performance

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Symbol Performance                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Symbol      Trades  Win%   Total P&L  Avg P&L                             │
│  ──────────  ──────  ─────  ─────────  ─────────                            │
│  SBIN        12      67%    +₹3,200    +₹267                                │
│  NIFTY30JAN25FUT  8  62%    +₹2,800    +₹350                                │
│  HDFC        10      60%    +₹1,500    +₹150                                │
│  INFY        8       50%    +₹750      +₹94                                 │
│  TCS         7       57%    +₹500      +₹71                                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Charts and Visualization

### Equity Curve

Shows account value over time:
- X-axis: Date/Time
- Y-axis: Account Value
- Trend line and moving average

### Daily P&L Bar Chart

```
+₹2000 │         ██
+₹1000 │  ██     ██  ██
    ₹0 │──██──██─██──██──██────
-₹1000 │     ██
       └──────────────────────
         Mon Tue Wed Thu Fri
```

### Win/Loss Distribution

```
Wins:   ████████████████████████████ 62%
Losses: ████████████████ 38%
```

### P&L Histogram

Distribution of trade outcomes:
- X-axis: P&L ranges
- Y-axis: Number of trades

## Filtering Options

### Filter by Strategy

1. Click **Strategy** dropdown
2. Select specific strategy
3. View filtered results

### Filter by Symbol

1. Click **Symbol** dropdown
2. Select specific symbol
3. View filtered results

### Filter by Exchange

1. Click **Exchange** dropdown
2. Select: NSE, NFO, MCX, etc.
3. View filtered results

### Filter by Product

1. Click **Product** dropdown
2. Select: MIS, NRML, CNC
3. View filtered results

## Export Options

### Export to CSV

1. Click **Export CSV**
2. Select date range
3. Choose fields to include
4. Download file

### Export to Excel

1. Click **Export Excel**
2. Formatted spreadsheet generated
3. Includes charts and summaries

### Print Report

1. Click **Print**
2. Formatted PDF generated
3. Professional report layout

## Alerts and Notifications

### P&L Alerts

Configure alerts for:

| Alert Type | Description |
|------------|-------------|
| Daily Target | Alert when daily profit target hit |
| Daily Loss Limit | Alert when daily loss limit reached |
| Trade P&L | Alert on large individual trade P&L |
| Drawdown | Alert on maximum drawdown |

### Setting Up Alerts

1. Go to **PnL** → **Alerts**
2. Configure thresholds:
   - Daily profit target: ₹5,000
   - Daily loss limit: ₹2,000
   - Max drawdown: 5%
3. Enable notification channels

## Best Practices

### 1. Review Daily

- Check P&L at end of each trading day
- Identify what worked and what didn't
- Note patterns in winning/losing trades

### 2. Track by Strategy

- Monitor each strategy separately
- Identify best-performing strategies
- Allocate capital accordingly

### 3. Analyze Drawdowns

- Understand maximum drawdown
- Set appropriate loss limits
- Adjust position sizing

### 4. Compare Periods

- Week-over-week comparison
- Month-over-month trends
- Identify seasonal patterns

### 5. Export and Document

- Keep records for tax purposes
- Track long-term performance
- Share with advisors/accountants

## Understanding Key Metrics

### Profit Factor

```
Profit Factor = Gross Profit / Gross Loss

Example:
Gross Profit: ₹25,000
Gross Loss: ₹10,000
Profit Factor: 2.5

Interpretation:
> 1.0: Profitable
> 1.5: Good
> 2.0: Excellent
```

### Expectancy

```
Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)

Example:
Win%: 60%, Avg Win: ₹1,000
Loss%: 40%, Avg Loss: ₹600
Expectancy: (0.60 × 1000) - (0.40 × 600) = ₹360

Interpretation:
Expected profit per trade: ₹360
```

### Maximum Drawdown

```
Max Drawdown = (Peak - Trough) / Peak × 100

Example:
Peak Value: ₹5,00,000
Trough Value: ₹4,50,000
Max Drawdown: (500000 - 450000) / 500000 × 100 = 10%

Interpretation:
Largest decline from peak: 10%
```

---

**Previous**: [23 - Telegram Bot](../23-telegram-bot/README.md)

**Next**: [25 - Latency Monitor](../25-latency-monitor/README.md)
