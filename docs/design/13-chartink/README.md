# 13 - Chartink Architecture

## Overview

Chartink integration allows OpenAlgo to receive trading signals from Chartink screener alerts via webhooks. When a stock appears in a Chartink scanner, it triggers a webhook that OpenAlgo processes to place trades automatically.

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
│  │  2. Get scanner configuration                                        │   │
│  │  3. Parse stock list                                                 │   │
│  │  4. For each stock:                                                 │   │
│  │     - Lookup symbol mapping (if exists)                              │   │
│  │     - Apply default exchange/product/quantity                       │   │
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
class ChartinkScanner(Base):
    __tablename__ = 'chartink_scanners'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)      # Scanner name
    webhook_id = Column(String(36), unique=True)    # UUID for webhook
    user_id = Column(String(50), nullable=False)    # Owner
    action = Column(String(10), default='BUY')      # BUY or SELL
    exchange = Column(String(10), default='NSE')    # Default exchange
    product_type = Column(String(10), default='MIS')# Default product
    default_quantity = Column(Integer, default=1)   # Default qty
    is_active = Column(Boolean, default=True)       # Enable/disable
    created_at = Column(DateTime, default=func.now())

class ChartinkSymbolMapping(Base):
    __tablename__ = 'chartink_symbol_mappings'

    id = Column(Integer, primary_key=True)
    scanner_id = Column(Integer, ForeignKey('chartink_scanners.id'))
    chartink_symbol = Column(String(50))     # Symbol from Chartink
    symbol = Column(String(50))               # OpenAlgo symbol
    exchange = Column(String(10))             # Override exchange
    product_type = Column(String(10))         # Override product
    quantity = Column(Integer)                # Override quantity
```

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
2. Create new scanner
3. Copy the generated `webhook_id`
4. Configure default settings:
   - Action: BUY/SELL
   - Exchange: NSE/BSE/NFO
   - Product: MIS/CNC/NRML
   - Default Quantity

## Symbol Mapping

Map Chartink symbols to OpenAlgo format:

| Chartink Symbol | OpenAlgo Symbol | Exchange | Product | Quantity |
|-----------------|-----------------|----------|---------|----------|
| SBIN | SBIN | NSE | MIS | 100 |
| RELIANCE | RELIANCE | NSE | CNC | 10 |
| INFY | INFY | NSE | MIS | 50 |

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
| `/chartink/` | GET | List scanners |
| `/chartink/new` | GET/POST | Create scanner |
| `/chartink/<id>` | GET | View scanner |
| `/chartink/<id>/edit` | GET/POST | Edit scanner |
| `/chartink/<id>/delete` | POST | Delete scanner |
| `/chartink/<id>/toggle` | POST | Enable/disable |
| `/chartink/<id>/symbols` | GET/POST | Symbol mappings |

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

### Scanner Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `name` | Scanner name | Required |
| `action` | BUY or SELL | BUY |
| `exchange` | Default exchange | NSE |
| `product_type` | MIS/CNC/NRML | MIS |
| `default_quantity` | Default order qty | 1 |
| `is_active` | Enable/disable | true |

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
