# 13 - Chartink Architecture

## Overview

Chartink integration allows OpenAlgo to receive trading signals from Chartink screener alerts via webhooks. When a stock appears in a Chartink scanner, it triggers a webhook that OpenAlgo processes to place trades automatically.

> **Note**: The Chartink integration uses a "Strategy" concept (not "Scanner") where each strategy has symbol-level configuration with time-based trading controls.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Chartink Integration                                   │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          Chartink Platform                                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Scanner/Screener Alert                                              │   │
│  │                                                                      │   │
│  │  When condition met → Trigger Webhook                               │   │
│  │  Example: Price > 20 DMA, Volume spike, RSI crossover               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP POST
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     OpenAlgo Chartink Webhook                                │
│                     POST /chartink/webhook                                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Rate Limit: WEBHOOK_RATE_LIMIT (100 per minute)                    │   │
│  │                                                                      │   │
│  │  Payload:                                                           │   │
│  │  {                                                                   │   │
│  │    "webhook_id": "your_webhook_id",                                 │   │
│  │    "stocks": "SBIN,RELIANCE,INFY"                                   │   │
│  │  }                                                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Chartink Processing                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  1. Validate webhook_id against database                            │   │
│  │  2. Get strategy configuration                                       │   │
│  │  3. Check time-based trading controls                               │   │
│  │     - Is current time within start_time and end_time?               │   │
│  │     - Is strategy active?                                           │   │
│  │  4. Parse stock list                                                │   │
│  │  5. For each stock:                                                 │   │
│  │     - Lookup symbol mapping (chartink_symbol → exchange/qty/product)│   │
│  │     - Queue order for execution                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Order Execution                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  REST API: /api/v1/placeorder or /api/v1/placesmartorder            │   │
│  │                                                                      │   │
│  │  Order queued → Rate-limited execution → Broker API                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Database Schema

**Location:** `database/chartink_db.py`

```python
class ChartinkStrategy(Base):
    """Model for Chartink strategies - each strategy has time-based trading controls"""
    __tablename__ = 'chartink_strategies'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)           # Strategy name
    webhook_id = Column(String(36), unique=True)         # UUID for webhook
    user_id = Column(String(255), nullable=False)        # Owner
    is_active = Column(Boolean, default=True)            # Enable/disable
    is_intraday = Column(Boolean, default=True)          # Intraday mode flag
    start_time = Column(String(5))                       # Trading start (HH:MM format)
    end_time = Column(String(5))                         # Trading end (HH:MM format)
    squareoff_time = Column(String(5))                   # Auto square-off time (HH:MM)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    symbol_mappings = relationship("ChartinkSymbolMapping", back_populates="strategy",
                                   cascade="all, delete-orphan")


class ChartinkSymbolMapping(Base):
    """Symbol-level configuration - maps Chartink symbols to trading parameters"""
    __tablename__ = 'chartink_symbol_mappings'

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey('chartink_strategies.id'), nullable=False)
    chartink_symbol = Column(String(50), nullable=False)  # Symbol from Chartink
    exchange = Column(String(10), nullable=False)         # NSE/BSE/NFO
    quantity = Column(Integer, nullable=False)            # Order quantity
    product_type = Column(String(10), nullable=False)     # MIS/CNC/NRML
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    strategy = relationship("ChartinkStrategy", back_populates="symbol_mappings")
```

> **Key Differences from Scanner Model**: The strategy model does NOT have `action` (BUY/SELL), `default_quantity`, or scanner-level `exchange`/`product_type`. Instead, trading parameters are defined per-symbol in the mapping table.

## Webhook Configuration

### Chartink Setup

1. Go to Chartink Scanner
2. Edit scanner settings
3. Add webhook URL: `http://your-domain/chartink/webhook`
4. Set webhook body:

```json
{
    "webhook_id": "your_webhook_id_from_openalgo",
    "stocks": "{stocks}"
}
```

### OpenAlgo Setup

1. Navigate to `/chartink`
2. Create new strategy
3. Copy the generated `webhook_id`
4. Configure time-based trading controls:
   - **Start Time**: When to start accepting signals (HH:MM)
   - **End Time**: When to stop accepting signals (HH:MM)
   - **Square-off Time**: Auto close positions (HH:MM)
   - **Intraday Mode**: Enable for MIS trades

5. Add symbol mappings with per-symbol configuration:
   - **Chartink Symbol**: Symbol as sent by Chartink
   - **Exchange**: NSE/BSE/NFO
   - **Product Type**: MIS/CNC/NRML
   - **Quantity**: Order quantity for this symbol

## Symbol Mapping

Each symbol in a strategy has its own trading configuration:

| Chartink Symbol | Exchange | Product | Quantity |
|-----------------|----------|---------|----------|
| SBIN | NSE | MIS | 100 |
| RELIANCE | NSE | CNC | 10 |
| INFY | NSE | MIS | 50 |

> **Note**: Unlike scanner-level defaults, each symbol must have its exchange, product, and quantity explicitly configured in the symbol mapping.

## Processing Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Chartink Webhook Processing                   │
└─────────────────────────────────────────────────────────────────┘

Webhook Received
      │
      ▼
┌─────────────────────┐
│ Validate webhook_id │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Check scanner active│
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Parse stocks list   │
│ "SBIN,RELIANCE"     │
│ → ["SBIN","RELIANCE"]│
└─────────┬───────────┘
          │
          ▼
┌───────────────────────────────────────────────────┐
│ For each stock:                                    │
│                                                    │
│  1. Check symbol mapping                           │
│     - If mapping exists: use mapped values        │
│     - If not: use scanner defaults                │
│                                                    │
│  2. Build order payload:                           │
│     {                                              │
│       "apikey": "user_api_key",                   │
│       "symbol": "SBIN",                           │
│       "exchange": "NSE",                          │
│       "action": "BUY",                            │
│       "quantity": 100,                            │
│       "product": "MIS",                           │
│       "pricetype": "MARKET"                       │
│     }                                              │
│                                                    │
│  3. Queue order for execution                      │
└───────────────────────────────────────────────────┘
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chartink/webhook` | POST | Receive Chartink alerts |
| `/chartink/` | GET | List strategies |
| `/chartink/new` | GET/POST | Create strategy |
| `/chartink/<id>` | GET | View strategy |
| `/chartink/<id>/edit` | GET/POST | Edit strategy |
| `/chartink/<id>/delete` | POST | Delete strategy |
| `/chartink/<id>/toggle` | POST | Enable/disable strategy |
| `/chartink/<id>/symbols` | GET/POST | Symbol mappings |

## Database Functions

**Strategy Management:**
- `create_strategy(name, webhook_id, user_id, is_intraday, start_time, end_time, squareoff_time)`
- `get_strategy(strategy_id)` - Get strategy by ID
- `get_strategy_by_webhook_id(webhook_id)` - Get strategy by webhook ID
- `get_user_strategies(user_id)` - Get all strategies for a user
- `get_all_strategies()` - Get all strategies
- `delete_strategy(strategy_id)` - Delete a strategy
- `toggle_strategy(strategy_id)` - Toggle active status
- `update_strategy_times(strategy_id, start_time, end_time, squareoff_time)` - Update trading times

**Symbol Mapping Management:**
- `add_symbol_mapping(strategy_id, chartink_symbol, exchange, quantity, product_type)`
- `bulk_add_symbol_mappings(strategy_id, mappings)` - Add multiple mappings at once
- `get_symbol_mappings(strategy_id)` - Get all mappings for a strategy
- `delete_symbol_mapping(mapping_id)` - Delete a mapping

## Webhook Payload Format

### From Chartink

```json
{
    "webhook_id": "abc123-def456-ghi789",
    "stocks": "SBIN,RELIANCE,INFY,TATAMOTORS"
}
```

### Processed Order

```json
{
    "apikey": "user_api_key",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 100,
    "product": "MIS",
    "pricetype": "MARKET"
}
```

## Configuration

### Environment Variables

```bash
WEBHOOK_RATE_LIMIT=100 per minute
STRATEGY_RATE_LIMIT=200 per minute
```

### Strategy Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `name` | Strategy name | Required |
| `webhook_id` | UUID for webhook | Auto-generated |
| `user_id` | Owner user ID | Current user |
| `is_active` | Enable/disable strategy | true |
| `is_intraday` | Intraday trading mode | true |
| `start_time` | Trading window start (HH:MM) | None |
| `end_time` | Trading window end (HH:MM) | None |
| `squareoff_time` | Auto square-off time (HH:MM) | None |

### Symbol Mapping Settings

| Setting | Description | Required |
|---------|-------------|----------|
| `chartink_symbol` | Symbol from Chartink | Yes |
| `exchange` | Trading exchange (NSE/BSE/NFO) | Yes |
| `quantity` | Order quantity | Yes |
| `product_type` | Product type (MIS/CNC/NRML) | Yes |

## Use Cases

### Momentum Scanner

```
Chartink: Stocks crossing 20 DMA with volume spike
OpenAlgo: Auto-buy with MIS product, qty=100
```

### Breakout Scanner

```
Chartink: Stocks breaking 52-week high
OpenAlgo: Auto-buy with CNC product for delivery
```

### Exit Scanner

```
Chartink: Stocks falling below support
OpenAlgo: Auto-sell to close positions
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/chartink.py` | Chartink blueprint |
| `database/chartink_db.py` | Database models |
| `templates/chartink/` | UI templates |
| `frontend/src/pages/Chartink.tsx` | React UI |
