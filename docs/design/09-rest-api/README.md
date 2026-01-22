# 09 - REST API Documentation

## Overview

OpenAlgo provides a comprehensive REST API built with Flask-RESTX at `/api/v1/`. The API enables trading operations, market data retrieval, and account management across 24+ Indian brokers through a unified interface.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        REST API Architecture                                  │
└──────────────────────────────────────────────────────────────────────────────┘

                         Client Request
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      /api/v1/ (Flask-RESTX)                                  │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Features:                                                           │   │
│  │  - Automatic Swagger documentation (/api/docs)                       │   │
│  │  - Request/response validation                                       │   │
│  │  - Rate limiting per endpoint                                        │   │
│  │  - API key authentication                                            │   │
│  │  - CSRF exempt (uses API key auth)                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   Order APIs    │  │   Data APIs     │  │  Account APIs   │
│                 │  │                 │  │                 │
│ - placeorder    │  │ - quotes        │  │ - funds         │
│ - modifyorder   │  │ - depth         │  │ - holdings      │
│ - cancelorder   │  │ - history       │  │ - positions     │
│ - placesmartord │  │ - optionchain   │  │ - orderbook     │
│ - basketorder   │  │ - optiongreeks  │  │ - tradebook     │
│ - splitorder    │  │ - intervals     │  │ - margin        │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

## API Categories

### Order Management

| Endpoint | Method | Rate Limit | Description |
|----------|--------|------------|-------------|
| `/api/v1/placeorder` | POST | ORDER_RATE | Place single order |
| `/api/v1/placesmartorder` | POST | SMART_ORDER | Place smart order (position sizing) |
| `/api/v1/modifyorder` | POST | ORDER_RATE | Modify pending order |
| `/api/v1/cancelorder` | POST | ORDER_RATE | Cancel single order |
| `/api/v1/cancelallorder` | POST | API_RATE | Cancel all orders |
| `/api/v1/basketorder` | POST | ORDER_RATE | Place multiple orders |
| `/api/v1/splitorder` | POST | API_RATE | Split large order |
| `/api/v1/closeposition` | POST | ORDER_RATE | Close specific position |
| `/api/v1/orderstatus` | POST | API_RATE | Get order status |
| `/api/v1/openposition` | POST | API_RATE | Get open positions |

### Market Data

| Endpoint | Method | Rate Limit | Description |
|----------|--------|------------|-------------|
| `/api/v1/quotes` | POST | API_RATE | Single symbol quote |
| `/api/v1/multiquotes` | POST | API_RATE | Multiple symbols quote |
| `/api/v1/depth` | POST | API_RATE | Market depth (L5) |
| `/api/v1/history` | POST | API_RATE | Historical OHLCV |
| `/api/v1/intervals` | POST | API_RATE | Supported intervals |
| `/api/v1/optionchain` | POST | API_RATE | Options chain data |
| `/api/v1/optiongreeks` | POST | API_RATE | Single option greeks |
| `/api/v1/multioptiongreeks` | POST | API_RATE | Multiple option greeks |
| `/api/v1/optionsymbol` | POST | API_RATE | Get option symbol |
| `/api/v1/expiry` | POST | API_RATE | Expiry dates |
| `/api/v1/syntheticfuture` | POST | API_RATE | Synthetic future price |

### Account Information

| Endpoint | Method | Rate Limit | Description |
|----------|--------|------------|-------------|
| `/api/v1/funds` | POST | API_RATE | Account balance |
| `/api/v1/holdings` | POST | API_RATE | Portfolio holdings |
| `/api/v1/positions` | POST | API_RATE | Open positions |
| `/api/v1/orderbook` | POST | API_RATE | Order history |
| `/api/v1/tradebook` | POST | API_RATE | Trade history |
| `/api/v1/margin` | POST | API_RATE | Margin calculation |

### Symbol & Search

| Endpoint | Method | Rate Limit | Description |
|----------|--------|------------|-------------|
| `/api/v1/symbol` | POST | API_RATE | Symbol lookup |
| `/api/v1/search` | POST | API_RATE | Symbol search |
| `/api/v1/instruments` | GET | API_RATE | All instruments |

### Utilities

| Endpoint | Method | Rate Limit | Description |
|----------|--------|------------|-------------|
| `/api/v1/ping` | POST | API_RATE | Connection test |
| `/api/v1/markettimings` | POST | API_RATE | Market hours |
| `/api/v1/marketholidays` | POST | API_RATE | Holiday calendar |

## Authentication

All API endpoints require API key authentication:

```python
# Method 1: In request body (recommended)
{
    "apikey": "your_64_char_api_key",
    "symbol": "SBIN",
    "exchange": "NSE"
}

# Method 2: X-API-KEY header (supported on some endpoints)
headers = {
    "X-API-KEY": "your_64_char_api_key"
}
```

**Note:** Bearer token authentication is NOT supported. Always use either the `apikey` field in the request body or the `X-API-KEY` header.

## Request/Response Format

### Standard Request

```json
{
    "apikey": "your_api_key",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 1,
    "product": "MIS",
    "pricetype": "MARKET"
}
```

### Standard Response

```json
{
    "status": "success",
    "data": {
        "orderid": "123456789"
    }
}
```

### Error Response

```json
{
    "status": "error",
    "message": "Invalid symbol"
}
```

## Place Order API

**Endpoint:** `POST /api/v1/placeorder`

### Request Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `apikey` | string | Yes | API key |
| `symbol` | string | Yes | Trading symbol |
| `exchange` | string | Yes | NSE, BSE, NFO, etc. |
| `action` | string | Yes | BUY or SELL |
| `quantity` | integer | Yes | Order quantity |
| `product` | string | Yes | MIS, CNC, NRML |
| `pricetype` | string | Yes | MARKET, LIMIT, SL, SL-M |
| `price` | float | No | Limit price |
| `trigger_price` | float | No | Trigger for SL orders |
| `disclosed_quantity` | integer | No | Disclosed quantity |

### Example

```python
import requests

response = requests.post(
    "http://localhost:5000/api/v1/placeorder",
    json={
        "apikey": "your_api_key",
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "product": "MIS",
        "pricetype": "MARKET"
    }
)

print(response.json())
# {"status": "success", "data": {"orderid": "123456"}}
```

## Smart Order API

**Endpoint:** `POST /api/v1/placesmartorder`

Intelligent order with position sizing and management.

### Additional Fields

| Field | Type | Description |
|-------|------|-------------|
| `position_size` | integer | Target position size |
| `strategy` | string | Strategy name for tracking |

### Position Sizing Logic

```
Current Position: +10
position_size: 0    → SELL 10 (close)
position_size: 5    → SELL 5 (reduce)
position_size: -5   → SELL 15 (reverse)
position_size: 15   → BUY 5 (add)
```

## Quotes API

**Endpoint:** `POST /api/v1/quotes`

### Response

```json
{
    "status": "success",
    "data": {
        "symbol": "SBIN",
        "exchange": "NSE",
        "ltp": 625.50,
        "open": 620.00,
        "high": 628.00,
        "low": 618.50,
        "close": 622.30,
        "volume": 12500000,
        "oi": 0
    }
}
```

## History API

**Endpoint:** `POST /api/v1/history`

### Request

```json
{
    "apikey": "your_api_key",
    "symbol": "SBIN",
    "exchange": "NSE",
    "interval": "1day",
    "start_date": "2024-01-01",
    "end_date": "2024-01-31"
}
```

### Supported Intervals

| Interval | Description |
|----------|-------------|
| `1minute` | 1-minute candles |
| `3minute` | 3-minute candles |
| `5minute` | 5-minute candles |
| `10minute` | 10-minute candles |
| `15minute` | 15-minute candles |
| `30minute` | 30-minute candles |
| `60minute` | 1-hour candles |
| `1day` | Daily candles |
| `1week` | Weekly candles |
| `1month` | Monthly candles |

## Option Chain API

**Endpoint:** `POST /api/v1/optionchain`

### Request

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY",
    "exchange": "NFO",
    "expiry": "2024-01-25"
}
```

### Response Structure

```json
{
    "status": "success",
    "data": {
        "calls": [...],
        "puts": [...],
        "spot_price": 21500.50,
        "expiry": "2024-01-25"
    }
}
```

## Swagger Documentation

Access interactive API documentation at:

```
http://localhost:5000/api/docs
```

Features:
- Try endpoints directly
- View request/response schemas
- Download OpenAPI spec

## File Structure

```
restx_api/
├── __init__.py              # API blueprint registration
├── schemas.py               # Order schemas
├── data_schemas.py          # Data schemas
├── account_schema.py        # Account schemas
├── place_order.py           # Place order endpoint
├── place_smart_order.py     # Smart order endpoint
├── modify_order.py          # Modify order
├── cancel_order.py          # Cancel order
├── cancel_all_order.py      # Cancel all orders
├── basket_order.py          # Basket orders
├── split_order.py           # Split orders
├── close_position.py        # Close position
├── orderstatus.py           # Order status
├── openposition.py          # Open positions
├── quotes.py                # Single quote
├── multiquotes.py           # Multiple quotes
├── depth.py                 # Market depth
├── history.py               # Historical data
├── option_chain.py          # Option chain
├── option_greeks.py         # Option greeks
├── multi_option_greeks.py   # Multi option greeks
├── option_symbol.py         # Option symbol lookup
├── expiry.py                # Expiry dates
├── synthetic_future.py      # Synthetic future
├── funds.py                 # Account funds
├── holdings.py              # Holdings
├── positionbook.py          # Positions
├── orderbook.py             # Order book
├── tradebook.py             # Trade book
├── margin.py                # Margin calculation
├── symbol.py                # Symbol lookup
├── search.py                # Symbol search
├── instruments.py           # All instruments
├── intervals.py             # Supported intervals
├── ping.py                  # Connection test
├── market_timings.py        # Market hours
├── market_holidays.py       # Holidays
└── chart_api.py             # Chart preferences
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `restx_api/__init__.py` | API blueprint and namespace setup |
| `restx_api/schemas.py` | Request/response models |
| `blueprints/api_v1.py` | API registration |
| `collections/` | Bruno/Postman collections |
