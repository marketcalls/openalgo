# 15 - Basic UI Elements

## Overview

OpenAlgo provides core trading UI components including Dashboard, OrderBook, TradeBook, Positions, and Holdings, along with advanced analytics tools (GEX Dashboard, IV Smile, OI Profile, Volatility Surface, etc.). These components display real-time data with auto-refresh via the React frontend.

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

## Analytics Tools

OpenAlgo includes a suite of options analytics tools accessible from the **Tools** hub page (`/tools`). These tools use Plotly.js for interactive charting and visualization.

### Tools Hub (`/tools`)

Central navigation page listing all available analytical tools with descriptions.

### GEX Dashboard (`/gex`)

Gamma Exposure (GEX) analysis showing the net gamma exposure across strike prices. Helps identify key support/resistance levels driven by options market makers.

- **Blueprint:** `blueprints/gex.py`
- **Service:** `services/gex_service.py`
- **API:** `frontend/src/api/gex.ts`

### IV Smile (`/ivsmile`)

Implied Volatility Smile chart showing IV across different strike prices for a given expiry. Visualizes the volatility skew pattern.

- **Blueprint:** `blueprints/ivsmile.py`
- **Service:** `services/iv_smile_service.py`

### IV Chart (`/ivchart`)

IV time series chart tracking implied volatility changes over time for specific options contracts.

- **Blueprint:** `blueprints/ivchart.py`
- **Service:** `services/iv_chart_service.py`

### OI Profile (`/oiprofile`)

Open Interest profile analysis showing OI distribution across strike prices. Identifies where maximum OI is concentrated.

- **Blueprint:** `blueprints/oiprofile.py`
- **Service:** `services/oi_profile_service.py`

### OI Tracker (`/oitracker`)

Real-time OI change tracker monitoring changes in open interest across strikes. Useful for tracking smart money positioning.

- **Blueprint:** `blueprints/oitracker.py`
- **Service:** `services/oi_tracker_service.py`

### Max Pain (`/maxpain`)

Max Pain analysis calculating the strike price at which the maximum number of options contracts would expire worthless.

- **Blueprint:** (shared with option chain infrastructure)
- **Service:** Option chain data with max pain calculation

### ATM Straddle Chart (`/straddle`)

Dynamic ATM Straddle chart showing combined premium of at-the-money call and put options over time.

- **Blueprint:** `blueprints/straddle_chart.py`
- **Service:** `services/straddle_chart_service.py`

### 3D Volatility Surface (`/volsurface`)

Interactive 3D visualization of implied volatility across strike prices and expiry dates, rendered with Plotly.

- **Blueprint:** `blueprints/vol_surface.py`
- **Service:** `services/vol_surface_service.py`

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/dashboard.py` | Dashboard routes |
| `blueprints/orders.py` | OrderBook/TradeBook routes |
| `restx_api/positionbook.py` | Positions API |
| `restx_api/holdings.py` | Holdings API |
| `blueprints/gex.py` | GEX Dashboard routes |
| `blueprints/ivsmile.py` | IV Smile routes |
| `blueprints/oiprofile.py` | OI Profile routes |
| `blueprints/oitracker.py` | OI Tracker routes |
| `blueprints/straddle_chart.py` | Straddle Chart routes |
| `blueprints/vol_surface.py` | Volatility Surface routes |
| `frontend/src/pages/` | React UI components |
