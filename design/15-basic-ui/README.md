# 15 - Basic UI Elements

## Overview

OpenAlgo provides core trading UI components including Dashboard, OrderBook, TradeBook, Positions, and Holdings. These components display real-time data with auto-refresh and support both React and Jinja2 frontends.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Basic UI Components                                    │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          Dashboard                                           │
│                          /dashboard                                          │
│                                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   Funds     │  │  Positions  │  │   P&L       │  │   Orders    │        │
│  │   Summary   │  │   Count     │  │   Summary   │  │   Pending   │        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Quick Actions: Place Order | View Positions | API Key              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          OrderBook                                           │
│                          /orderbook                                          │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ Order ID | Symbol | Exchange | Action | Qty | Price | Status | Time   │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ 123456   | SBIN   | NSE      | BUY    | 100 | MKT   | Complete| 09:30 │ │
│  │ 123457   | INFY   | NSE      | SELL   | 50  | 1650  | Pending | 10:15 │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Actions: Cancel Order | Modify Order | Refresh                            │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          TradeBook                                           │
│                          /tradebook                                          │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ Trade ID | Symbol | Exchange | Action | Qty | Price | Time            │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ T001     | SBIN   | NSE      | BUY    | 100 | 625.50| 09:30:15       │ │
│  │ T002     | SBIN   | NSE      | SELL   | 100 | 627.25| 14:45:30       │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Summary: Total Trades | Buy Value | Sell Value | Net P&L                  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          Positions                                           │
│                          /positions                                          │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ Symbol | Exchange | Product | Qty | Avg Price | LTP | P&L | P&L%     │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ SBIN   | NSE      | MIS     | 100 | 625.50    | 627 | +150 | +0.24%  │ │
│  │ INFY   | NSE      | MIS     | -50 | 1655.00   | 1650| +250 | +0.30%  │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Actions: Close Position | Close All | Refresh                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          Holdings                                            │
│                          /holdings                                           │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ Symbol | Exchange | Qty | Avg Price | LTP | Current Value | P&L      │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ SBIN   | NSE      | 500 | 580.00    | 625 | 312,500 | +22,500       │ │
│  │ INFY   | NSE      | 100 | 1500.00   | 1650| 165,000 | +15,000       │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Summary: Total Investment | Current Value | Overall P&L                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Sources

### API Endpoints

| Component | API Endpoint | Method |
|-----------|--------------|--------|
| Dashboard | Multiple | GET |
| OrderBook | `/api/v1/orderbook` | POST |
| TradeBook | `/api/v1/tradebook` | POST |
| Positions | `/api/v1/positions` | POST |
| Holdings | `/api/v1/holdings` | POST |
| Funds | `/api/v1/funds` | POST |

### Real-Time Updates

Socket.IO events for live updates:

| Event | Description |
|-------|-------------|
| `order_update` | Order status change |
| `trade_update` | New trade executed |
| `position_update` | Position change |
| `pnl_update` | P&L refresh |

## Component Details

### Dashboard

**Route:** `/dashboard`

Features:
- Account summary (funds, margin)
- Open positions count
- Today's P&L
- Pending orders count
- Quick action buttons

### OrderBook

**Route:** `/orderbook`

Columns:
- Order ID
- Symbol
- Exchange
- Action (BUY/SELL)
- Quantity
- Price / Price Type
- Status (pending/complete/cancelled/rejected)
- Timestamp

Actions:
- Cancel pending order
- Modify order (qty, price)
- Filter by status

### TradeBook

**Route:** `/tradebook`

Columns:
- Trade ID
- Order ID (linked)
- Symbol
- Exchange
- Action
- Quantity
- Execution Price
- Timestamp

Summary:
- Total trades count
- Buy/Sell breakdown
- Turnover

### Positions

**Route:** `/positions`

Columns:
- Symbol
- Exchange
- Product (MIS/CNC/NRML)
- Quantity (+ve long, -ve short)
- Average Price
- LTP (Last Traded Price)
- P&L (absolute)
- P&L % (percentage)

Actions:
- Close individual position
- Close all positions
- Add to position

### Holdings

**Route:** `/holdings`

Columns:
- Symbol
- Exchange
- Quantity
- Average Cost
- Current Price
- Current Value
- Day's P&L
- Overall P&L

Features:
- T1 holdings (unsettled)
- Pledged quantities
- Portfolio value

## React Components

### File Structure

```
frontend/src/
├── pages/
│   ├── Dashboard.tsx
│   ├── OrderBook.tsx
│   ├── TradeBook.tsx
│   ├── Positions.tsx
│   └── Holdings.tsx
├── components/
│   ├── DataTable.tsx       # Reusable table
│   ├── PnLBadge.tsx        # P&L display
│   ├── StatusBadge.tsx     # Order status
│   └── ActionButton.tsx    # Quick actions
└── hooks/
    ├── useOrders.ts
    ├── useTrades.ts
    ├── usePositions.ts
    └── useHoldings.ts
```

### TanStack Query Usage

```typescript
// hooks/usePositions.ts
export function usePositions() {
  return useQuery({
    queryKey: ['positions'],
    queryFn: () => api.getPositions(),
    refetchInterval: 5000,  // Auto-refresh every 5 seconds
  });
}
```

## Jinja2 Templates

### File Structure

```
templates/
├── dashboard.html
├── orderbook.html
├── tradebook.html
├── positions.html
└── holdings.html
```

### Auto-Refresh

```javascript
// Auto-refresh every 10 seconds
setInterval(() => {
    fetch('/api/positions')
        .then(response => response.json())
        .then(data => updateTable(data));
}, 10000);
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/dashboard.py` | Dashboard routes |
| `blueprints/orders.py` | OrderBook/TradeBook routes |
| `restx_api/positionbook.py` | Positions API |
| `restx_api/holdings.py` | Holdings API |
| `frontend/src/pages/` | React UI components |
| `templates/` | Jinja2 templates |
