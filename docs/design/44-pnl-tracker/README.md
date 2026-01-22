# 44 - PnL Tracker

## Overview

The PnL (Profit & Loss) Tracker provides real-time monitoring of trading performance. It calculates realized and unrealized P&L, tracks daily performance, and displays data via interactive charts and tables.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          PnL Tracker Architecture                            │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         Data Sources                                         │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  Position Book  │  │   Trade Book    │  │  WebSocket      │             │
│  │  (Broker API)   │  │   (Broker API)  │  │  (Live Prices)  │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                │                                             │
│                                ▼                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       PnL Calculation Service                                │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Dual Calculation System                           │   │
│  │                                                                      │   │
│  │  ┌──────────────────────────┐  ┌──────────────────────────┐        │   │
│  │  │   Intraday (Legacy)      │  │   Sandbox (Modern)       │        │   │
│  │  │                          │  │                          │        │   │
│  │  │  • Position-based        │  │  • Trade-based           │        │   │
│  │  │  • MTM from positions    │  │  • FIFO matching         │        │   │
│  │  │  • Broker P&L values     │  │  • Precise tracking      │        │   │
│  │  └──────────────────────────┘  └──────────────────────────┘        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    P&L Components                                    │   │
│  │                                                                      │   │
│  │  Realized P&L        = Closed position profits/losses               │   │
│  │  Unrealized P&L      = Open position MTM (Mark-to-Market)           │   │
│  │  Total P&L           = Realized + Unrealized                        │   │
│  │  Day P&L             = Today's total performance                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Frontend Display                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Dashboard Cards                                                     │   │
│  │                                                                      │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐              │   │
│  │  │ Realized │ │Unrealized│ │  Total   │ │   ROI    │              │   │
│  │  │ +₹2,500  │ │ +₹1,250  │ │ +₹3,750  │ │  +0.75%  │              │   │
│  │  │  (green) │ │  (green) │ │  (green) │ │  (green) │              │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  P&L Chart (LightWeight Charts)                                     │   │
│  │                                                                      │   │
│  │       ₹                                                              │   │
│  │    4000│        ╭──────╮                                            │   │
│  │    3000│    ╭───╯      ╰──╮                                         │   │
│  │    2000│╭───╯              ╰──────                                  │   │
│  │    1000│                                                            │   │
│  │       0├────────────────────────────► Time                          │   │
│  │        9:15  10:00  11:00  12:00  1:00                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Calculation Methods

### Position-Based P&L (Intraday)

```
┌────────────────────────────────────────────────────────────────────────────┐
│                     Position-Based Calculation                              │
│                                                                             │
│  For each open position:                                                    │
│                                                                             │
│  Unrealized P&L = (LTP - Avg Price) × Quantity × Multiplier                │
│                                                                             │
│  Where:                                                                     │
│  • LTP = Last Traded Price (from WebSocket or API)                         │
│  • Avg Price = Average entry price                                         │
│  • Quantity = Net position quantity (positive=long, negative=short)        │
│  • Multiplier = Lot size (for F&O) or 1 (for equity)                       │
│                                                                             │
│  Example:                                                                   │
│  SBIN: LTP=630, Avg=625, Qty=100, Mult=1                                   │
│  Unrealized = (630 - 625) × 100 × 1 = ₹500                                │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### Trade-Based P&L (Sandbox)

```
┌────────────────────────────────────────────────────────────────────────────┐
│                     Trade-Based FIFO Calculation                            │
│                                                                             │
│  1. Match trades using FIFO (First In First Out)                           │
│                                                                             │
│  2. For matched pairs:                                                      │
│     Realized P&L = (Exit Price - Entry Price) × Quantity                   │
│                                                                             │
│  3. For unmatched trades:                                                   │
│     Unrealized P&L = (LTP - Entry Price) × Quantity                        │
│                                                                             │
│  Example:                                                                   │
│  Trade 1: BUY 100 @ ₹625 (Entry)                                           │
│  Trade 2: SELL 50 @ ₹630 (Partial Exit)                                    │
│                                                                             │
│  Realized = (630 - 625) × 50 = ₹250                                        │
│  Unrealized (remaining 50) = (LTP - 625) × 50                              │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

## Real-Time Updates

### WebSocket Data Freshness

```python
# Data freshness check (≤5 seconds is considered fresh)
MAX_DATA_AGE_SECONDS = 5

def is_price_fresh(last_update_time):
    """Check if price data is recent enough"""
    age = (datetime.now() - last_update_time).total_seconds()
    return age <= MAX_DATA_AGE_SECONDS

def get_position_pnl(position, ws_data):
    """Calculate P&L with fresh WebSocket data"""
    symbol = position['symbol']

    if symbol in ws_data and is_price_fresh(ws_data[symbol]['time']):
        ltp = ws_data[symbol]['ltp']
    else:
        # Fallback to broker API
        ltp = get_quote_from_broker(symbol)

    return calculate_pnl(position, ltp)
```

### SocketIO Updates

```typescript
// Frontend real-time subscription
socket.on('position_update', (data) => {
    updatePositionPnL(data.symbol, data.pnl);
});

socket.on('pnl_summary', (data) => {
    setRealizedPnL(data.realized);
    setUnrealizedPnL(data.unrealized);
    setTotalPnL(data.total);
});
```

## Database Schema

### daily_pnl Table

```
┌────────────────────────────────────────────────────────────────┐
│                      daily_pnl table                            │
├──────────────────┬──────────────┬──────────────────────────────┤
│ Column           │ Type         │ Description                  │
├──────────────────┼──────────────┼──────────────────────────────┤
│ id               │ INTEGER PK   │ Auto-increment               │
│ user_id          │ VARCHAR(255) │ User identifier              │
│ date             │ DATE         │ Trading date                 │
│ realized_pnl     │ DECIMAL      │ Closed position P&L          │
│ unrealized_pnl   │ DECIMAL      │ Open position MTM            │
│ total_pnl        │ DECIMAL      │ Sum of realized + unrealized │
│ trade_count      │ INTEGER      │ Number of trades             │
│ win_count        │ INTEGER      │ Profitable trades            │
│ loss_count       │ INTEGER      │ Loss-making trades           │
│ created_at       │ DATETIME     │ Record creation time         │
│ updated_at       │ DATETIME     │ Last update time             │
└──────────────────┴──────────────┴──────────────────────────────┘
```

### pnl_snapshots Table

```
┌────────────────────────────────────────────────────────────────┐
│                    pnl_snapshots table                          │
├──────────────────┬──────────────┬──────────────────────────────┤
│ Column           │ Type         │ Description                  │
├──────────────────┼──────────────┼──────────────────────────────┤
│ id               │ INTEGER PK   │ Auto-increment               │
│ user_id          │ VARCHAR(255) │ User identifier              │
│ timestamp        │ DATETIME     │ Snapshot time                │
│ total_pnl        │ DECIMAL      │ P&L at snapshot time         │
│ positions_json   │ TEXT         │ Position details             │
└──────────────────┴──────────────┴──────────────────────────────┘
```

## Service Implementation

### P&L Calculation Service

```python
def calculate_total_pnl(user_id, positions, ws_data):
    """Calculate total P&L for all positions"""
    realized = 0
    unrealized = 0

    for position in positions:
        symbol = position['symbol']
        quantity = position['quantity']
        avg_price = position['average_price']

        # Get current price
        if symbol in ws_data:
            ltp = ws_data[symbol]['ltp']
        else:
            ltp = position.get('ltp', avg_price)

        # Calculate unrealized for open positions
        if quantity != 0:
            position_pnl = (ltp - avg_price) * quantity
            unrealized += position_pnl

        # Add realized from closed positions
        realized += position.get('realized_pnl', 0)

    return {
        'realized': round(realized, 2),
        'unrealized': round(unrealized, 2),
        'total': round(realized + unrealized, 2)
    }
```

### Daily Tracking

```python
def update_daily_pnl(user_id):
    """Update daily P&L record"""
    today = date.today()

    # Get current P&L
    positions = get_positions(user_id)
    trades = get_trades(user_id, today)
    pnl = calculate_total_pnl(user_id, positions, get_ws_data())

    # Calculate trade statistics
    winning_trades = [t for t in trades if t['pnl'] > 0]
    losing_trades = [t for t in trades if t['pnl'] < 0]

    # Update or create daily record
    daily = DailyPnL.query.filter_by(
        user_id=user_id,
        date=today
    ).first()

    if daily:
        daily.realized_pnl = pnl['realized']
        daily.unrealized_pnl = pnl['unrealized']
        daily.total_pnl = pnl['total']
        daily.trade_count = len(trades)
        daily.win_count = len(winning_trades)
        daily.loss_count = len(losing_trades)
        daily.updated_at = datetime.utcnow()
    else:
        daily = DailyPnL(
            user_id=user_id,
            date=today,
            realized_pnl=pnl['realized'],
            unrealized_pnl=pnl['unrealized'],
            total_pnl=pnl['total'],
            trade_count=len(trades),
            win_count=len(winning_trades),
            loss_count=len(losing_trades)
        )
        db.session.add(daily)

    db.session.commit()
```

## API Endpoints

### Get Current P&L

```
GET /api/v1/pnl
Authorization: Bearer YOUR_API_KEY
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "realized": 2500.00,
        "unrealized": 1250.00,
        "total": 3750.00,
        "positions": [
            {
                "symbol": "SBIN",
                "exchange": "NSE",
                "quantity": 100,
                "avg_price": 625.50,
                "ltp": 630.00,
                "pnl": 450.00,
                "pnl_percent": 0.72
            }
        ]
    }
}
```

### Get Daily History

```
GET /api/v1/pnl/history?days=30
Authorization: Bearer YOUR_API_KEY
```

**Response:**
```json
{
    "status": "success",
    "data": [
        {
            "date": "2025-01-25",
            "realized": 2500.00,
            "unrealized": 1250.00,
            "total": 3750.00,
            "trade_count": 5,
            "win_rate": 80
        }
    ]
}
```

### Get P&L Chart Data

```
GET /api/v1/pnl/chart?interval=1m
Authorization: Bearer YOUR_API_KEY
```

**Response:**
```json
{
    "status": "success",
    "data": [
        {"time": 1706165700, "value": 1000},
        {"time": 1706165760, "value": 1500},
        {"time": 1706165820, "value": 2200}
    ]
}
```

## Frontend Components

### P&L Dashboard

```typescript
interface PnLSummary {
  realized: number;
  unrealized: number;
  total: number;
  roi: number;
}

function PnLDashboard() {
  const { data: pnl } = useQuery({
    queryKey: ['pnl'],
    queryFn: () => api.getPnL(),
    refetchInterval: 5000  // Refresh every 5 seconds
  });

  return (
    <div className="grid grid-cols-4 gap-4">
      <PnLCard
        label="Realized"
        value={pnl?.realized}
        color={pnl?.realized >= 0 ? 'green' : 'red'}
      />
      <PnLCard
        label="Unrealized"
        value={pnl?.unrealized}
        color={pnl?.unrealized >= 0 ? 'green' : 'red'}
      />
      <PnLCard
        label="Total"
        value={pnl?.total}
        color={pnl?.total >= 0 ? 'green' : 'red'}
      />
      <PnLCard
        label="ROI"
        value={`${pnl?.roi}%`}
        color={pnl?.roi >= 0 ? 'green' : 'red'}
      />
    </div>
  );
}
```

### P&L Chart

```typescript
import { createChart } from 'lightweight-charts';

function PnLChart({ data }) {
  const chartRef = useRef(null);

  useEffect(() => {
    const chart = createChart(chartRef.current, {
      width: 800,
      height: 300,
      layout: {
        background: { type: 'solid', color: 'white' },
        textColor: 'black',
      }
    });

    const lineSeries = chart.addLineSeries({
      color: data[data.length - 1]?.value >= 0 ? '#22c55e' : '#ef4444',
      lineWidth: 2
    });

    lineSeries.setData(data);

    return () => chart.remove();
  }, [data]);

  return <div ref={chartRef} />;
}
```

## Performance Optimization

### Caching Strategy

```python
from cachetools import TTLCache

# Cache P&L calculations for 1 second
pnl_cache = TTLCache(maxsize=1000, ttl=1)

def get_cached_pnl(user_id):
    """Get P&L with caching"""
    if user_id in pnl_cache:
        return pnl_cache[user_id]

    pnl = calculate_total_pnl(user_id)
    pnl_cache[user_id] = pnl
    return pnl
```

### Batch Updates

```python
def batch_update_pnl():
    """Update P&L for all active users"""
    active_users = get_active_users()
    ws_data = get_all_ws_data()

    for user_id in active_users:
        positions = get_positions(user_id)
        pnl = calculate_total_pnl(user_id, positions, ws_data)

        # Emit to user's socket room
        socketio.emit('pnl_update', pnl, room=f"user_{user_id}")
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `services/pnl_service.py` | P&L calculation logic |
| `database/pnl_db.py` | Daily P&L database models |
| `blueprints/pnl.py` | P&L API endpoints |
| `frontend/src/components/PnLDashboard.tsx` | Dashboard UI |
| `frontend/src/components/PnLChart.tsx` | Chart component |
