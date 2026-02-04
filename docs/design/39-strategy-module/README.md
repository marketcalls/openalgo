# 39 - Strategy Module

## Overview

The Strategy Module provides a webhook-based system for receiving trading signals from external platforms (TradingView, Amibroker, ChartInk) and executing orders through OpenAlgo. It features time-based controls, symbol mappings, automatic square-off, and rate-limited order queuing.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Strategy Module Architecture                          │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   TradingView   │  │   Amibroker     │  │    ChartInk     │
│   Webhook       │  │   Webhook       │  │    Webhook      │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                      Strategy Webhook Endpoint                               │
│                      POST /strategy/webhook/<webhook_id>                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  1. Rate Limiting (100/min for webhooks)                             │   │
│  │  2. Validate webhook_id → Get strategy                               │   │
│  │  3. Check strategy enabled & time window                             │   │
│  │  4. Parse signal (action, symbol, quantity)                          │   │
│  │  5. Apply symbol mapping overrides                                   │   │
│  │  6. Queue order for execution                                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Order Queueing System                                │
│                                                                              │
│  ┌──────────────────────┐        ┌──────────────────────┐                   │
│  │   Regular Queue      │        │   Smart Order Queue  │                   │
│  │   (placeorder)       │        │   (placesmartorder)  │                   │
│  │                      │        │                      │                   │
│  │   Rate: 10/sec       │        │   Rate: 1/sec        │                   │
│  │   (ORDER_RATE_LIMIT) │        │   (SMART_ORDER_RATE) │                   │
│  └──────────┬───────────┘        └──────────┬───────────┘                   │
│             │                               │                               │
│             └───────────────┬───────────────┘                               │
│                             │                                               │
│                             ▼                                               │
│                    ┌────────────────┐                                       │
│                    │ Order Processor │                                       │
│                    │ (Background)    │                                       │
│                    └────────┬───────┘                                       │
│                             │                                               │
└─────────────────────────────┼───────────────────────────────────────────────┘
                              │
                              ▼
                    ┌────────────────┐
                    │ REST API       │
                    │ /api/v1/...    │
                    └────────────────┘
```

## Strategy Configuration

### Database Schema

**Location:** `database/strategy_db.py`

```python
class Strategy(Base):
    __tablename__ = 'strategies'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)        # Platform_StrategyName
    webhook_id = Column(String(36), unique=True)      # UUID for webhook URL
    user_id = Column(String(50), nullable=False)      # Owner
    is_intraday = Column(Boolean, default=True)       # Intraday or positional
    trading_mode = Column(String(10), default='LONG') # LONG, SHORT, BOTH
    start_time = Column(String(5))                    # HH:MM (09:15)
    end_time = Column(String(5))                      # HH:MM (15:15)
    squareoff_time = Column(String(5))                # HH:MM (15:25)
    is_active = Column(Boolean, default=True)         # Active/inactive
    created_at = Column(DateTime, default=func.now())

class StrategySymbolMapping(Base):
    __tablename__ = 'strategy_symbol_mappings'

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey('strategies.id'))
    signal_symbol = Column(String(50))    # Symbol from webhook signal
    symbol = Column(String(50))           # OpenAlgo symbol to trade
    exchange = Column(String(10))         # NSE, NFO, etc.
    product_type = Column(String(10))     # MIS, CNC, NRML
    quantity = Column(Integer)            # Override quantity
```

### Time Validation

```python
def validate_strategy_times(start_time, end_time, squareoff_time):
    """Validate strategy time settings"""

    # Market hours (9:15 AM to 3:30 PM)
    market_open = time(9, 15)
    market_close = time(15, 30)

    # Validations:
    # 1. Start time >= market_open
    # 2. End time <= market_close
    # 3. Square off time <= market_close
    # 4. Start < End < Square off
```

## Webhook Signal Format

### TradingView Format

```json
{
    "action": "{{strategy.order.action}}",
    "symbol": "{{ticker}}",
    "quantity": "{{strategy.order.contracts}}",
    "price": "{{close}}"
}
```

### Amibroker Format

```json
{
    "action": "BUY",
    "symbol": "SBIN",
    "quantity": 10,
    "exchange": "NSE",
    "product": "MIS"
}
```

### Supported Actions

| Action | Description |
|--------|-------------|
| `BUY` | Long entry / Short exit |
| `SELL` | Long exit / Short entry |

## Symbol Mapping

Allows mapping external symbols to OpenAlgo format:

```
External Signal: "SBIN"
       │
       ▼
┌──────────────────────────────────────┐
│  Symbol Mapping Lookup               │
│  signal_symbol → trading symbol      │
│                                      │
│  "SBIN" → {                          │
│    symbol: "SBIN",                   │
│    exchange: "NSE",                  │
│    product_type: "MIS",              │
│    quantity: 50                      │
│  }                                   │
└──────────────────────────────────────┘
       │
       ▼
Place Order: NSE:SBIN, Qty: 50, Product: MIS
```

## Order Queuing System

### Dual Queue Architecture

```python
# Separate queues for different order types
regular_order_queue = queue.Queue()  # For placeorder (up to 10/sec)
smart_order_queue = queue.Queue()    # For placesmartorder (1/sec)

def process_orders():
    """Background task to process orders with rate limiting"""
    while True:
        # 1. Process smart orders first (1 per second)
        try:
            smart_order = smart_order_queue.get_nowait()
            response = requests.post(f'{BASE_URL}/api/v1/placesmartorder', json=smart_order)
            time.sleep(1)  # 1 second delay
            continue
        except queue.Empty:
            pass

        # 2. Process regular orders (up to 10 per second)
        if len(last_regular_orders) < 10:
            try:
                regular_order = regular_order_queue.get_nowait()
                response = requests.post(f'{BASE_URL}/api/v1/placeorder', json=regular_order)
                last_regular_orders.append(time.time())
            except queue.Empty:
                pass

        time.sleep(0.1)  # Prevent CPU spinning
```

### Rate Limiting

| Order Type | Rate Limit | Queue |
|------------|------------|-------|
| Regular Order | 10/second | `regular_order_queue` |
| Smart Order | 1/second | `smart_order_queue` |

## Automatic Square-Off

### APScheduler Integration

```python
scheduler = BackgroundScheduler(
    timezone=pytz.timezone('Asia/Kolkata'),
    job_defaults={
        'coalesce': True,
        'misfire_grace_time': 300,
        'max_instances': 1
    }
)

def schedule_squareoff(strategy_id):
    """Schedule squareoff for intraday strategy"""
    strategy = get_strategy(strategy_id)
    hours, minutes = map(int, strategy.squareoff_time.split(':'))

    scheduler.add_job(
        squareoff_positions,
        'cron',
        hour=hours,
        minute=minutes,
        args=[strategy_id],
        id=f'squareoff_{strategy_id}',
        timezone=pytz.timezone('Asia/Kolkata')
    )
```

### Square-Off Logic

```python
def squareoff_positions(strategy_id):
    """Square off all positions for intraday strategy"""
    strategy = get_strategy(strategy_id)
    mappings = get_symbol_mappings(strategy_id)

    for mapping in mappings:
        payload = {
            'apikey': api_key,
            'symbol': mapping.symbol,
            'exchange': mapping.exchange,
            'product': mapping.product_type,
            'strategy': strategy.name,
            'action': 'SELL',
            'pricetype': 'MARKET',
            'quantity': '0',
            'position_size': '0',  # Closes position
        }
        queue_order('placesmartorder', payload)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/strategy/` | GET | List all strategies |
| `/strategy/new` | GET/POST | Create new strategy |
| `/strategy/<id>` | GET | View strategy details |
| `/strategy/<id>/edit` | GET/POST | Edit strategy |
| `/strategy/<id>/delete` | POST | Delete strategy |
| `/strategy/<id>/toggle` | POST | Enable/disable strategy |
| `/strategy/<id>/symbols` | GET/POST | Manage symbol mappings |
| `/strategy/webhook/<webhook_id>` | POST | Receive trading signal |

## Trading Modes

| Mode | Allowed Actions | Use Case |
|------|-----------------|----------|
| `LONG` | BUY only | Long-only strategies |
| `SHORT` | SELL only | Short-only strategies |
| `BOTH` | BUY and SELL | Bidirectional trading |

## Strategy Time Window

```
Market Hours: 09:15 ─────────────────────────────────────── 15:30
                    │                                      │
Strategy Window:    │  start_time ─────── end_time        │
                    │      │                  │            │
                    │      └──────────────────┘            │
                    │             ▲                        │
                    │     Signals accepted                 │
                    │                                      │
Square-off:         │                              squareoff_time
                    │                                      │
                    │                                    ──┼──
                    │                              Close all MIS
```

## Configuration

### Environment Variables

```bash
WEBHOOK_RATE_LIMIT=100 per minute
STRATEGY_RATE_LIMIT=200 per minute
HOST_SERVER=http://127.0.0.1:5000  # Base URL for internal API calls
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/strategy.py` | Strategy blueprint and webhook handler |
| `database/strategy_db.py` | Strategy database models |
| `templates/strategy/` | Strategy UI templates |
| `frontend/src/pages/Strategy.tsx` | React strategy management |
