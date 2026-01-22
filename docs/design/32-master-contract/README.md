# 32 - Master Contract Download

## Overview

Master contracts contain symbol mappings between OpenAlgo's standardized format and broker-specific formats. They are downloaded daily and cached for fast symbol resolution.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    Master Contract Download Architecture                     │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         Download Trigger                                     │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  On Broker      │  │   Manual        │  │   Daily         │             │
│  │  Login          │  │   Trigger       │  │   Scheduled     │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                │                                             │
│                                ▼                                             │
│           ┌─────────────────────────────────────────────────────────┐       │
│           │              Async Download Task                         │       │
│           │              (Background Thread)                         │       │
│           └─────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Broker-Specific Download                                │
│                                                                              │
│  broker/{name}/database/master_contract_db.py                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  1. Fetch from broker API or static URL                              │   │
│  │  2. Parse CSV/JSON format                                            │   │
│  │  3. Transform to OpenAlgo format                                     │   │
│  │  4. Store in symtoken table                                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Symbol Database                                       │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     symtoken table                                   │   │
│  │                                                                      │   │
│  │  symbol     │ exchange │ token    │ lotsize │ tick_size │ ...       │   │
│  │  ──────────────────────────────────────────────────────────────────  │   │
│  │  SBIN       │ NSE      │ 779      │ 1       │ 0.05      │           │   │
│  │  NIFTY      │ NFO      │ 256265   │ 65      │ 0.05      │           │   │
│  │  BANKNIFTY  │ NFO      │ 260105   │ 30      │ 0.05      │           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Download Process

### 1. Trigger on Broker Login

```python
from utils.auth_utils import async_master_contract_download

def handle_auth_success(auth_token, broker):
    # Start background download
    async_master_contract_download(broker)
```

### 2. Background Download

```python
def async_master_contract_download(broker):
    """Download master contract in background thread"""
    from concurrent.futures import ThreadPoolExecutor

    executor = ThreadPoolExecutor(max_workers=2)
    executor.submit(_download_master_contract, broker)
```

### 3. Broker-Specific Download

```python
# broker/zerodha/database/master_contract_db.py

def download_master_contract():
    """Download Zerodha master contract"""
    url = "https://api.kite.trade/instruments"
    response = requests.get(url)

    # Parse CSV
    df = pd.read_csv(StringIO(response.text))

    # Transform and store
    for _, row in df.iterrows():
        store_symbol(
            symbol=row['tradingsymbol'],
            exchange=row['exchange'],
            token=row['instrument_token'],
            lotsize=row['lot_size']
        )
```

## Symbol Database Schema

### symtoken Table

```
┌────────────────────────────────────────────────────────────────┐
│                      symtoken table                             │
├──────────────┬──────────────┬──────────────────────────────────┤
│ Column       │ Type         │ Description                      │
├──────────────┼──────────────┼──────────────────────────────────┤
│ id           │ INTEGER PK   │ Auto-increment                   │
│ symbol       │ VARCHAR      │ OpenAlgo symbol format           │
│ brsymbol     │ VARCHAR      │ Broker-specific symbol           │
│ exchange     │ VARCHAR      │ Exchange code                    │
│ token        │ VARCHAR      │ Broker instrument token          │
│ lotsize      │ INTEGER      │ Lot size                         │
│ tick_size    │ DECIMAL      │ Minimum price tick               │
│ segment      │ VARCHAR      │ Trading segment                  │
│ expiry       │ DATE         │ Expiry date (F&O)                │
│ strike       │ DECIMAL      │ Strike price (options)           │
│ option_type  │ VARCHAR      │ CE/PE                            │
└──────────────┴──────────────┴──────────────────────────────────┘
```

## Symbol Mapping

### OpenAlgo to Broker

```python
from database.token_db import get_br_symbol

# Get broker-specific symbol
broker_symbol = get_br_symbol("SBIN", "NSE")
# Returns: "SBIN-EQ" (for Zerodha)

broker_symbol = get_br_symbol("NIFTY21JAN2521500CE", "NFO")
# Returns: "NIFTY 21JAN25 21500 CE" (for Zerodha)
```

### Get Token

```python
from database.token_db import get_token

# Get broker token for symbol
token = get_token("SBIN", "NSE")
# Returns: "779"
```

### Get Symbol Info

```python
from database.token_db import get_symbol_info

info = get_symbol_info("NIFTY", "NFO")
# Returns: {
#     "symbol": "NIFTY",
#     "lotsize": 65,
#     "tick_size": 0.05,
#     "expiry": "2025-01-30"
# }
```

## Broker Implementations

### Zerodha

```python
# broker/zerodha/database/master_contract_db.py

URL = "https://api.kite.trade/instruments"
FORMAT = "CSV"

def download_master_contract():
    df = pd.read_csv(URL)
    # Columns: instrument_token, exchange_token, tradingsymbol,
    #          name, last_price, expiry, strike, tick_size,
    #          lot_size, instrument_type, segment, exchange
```

### Dhan

```python
# broker/dhan/database/master_contract_db.py

URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
FORMAT = "CSV"
```

### Angel One

```python
# broker/angel/database/master_contract_db.py

URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
FORMAT = "JSON"
```

## Caching Strategy

### In-Memory Cache

```python
from cachetools import TTLCache

# Cache symbol lookups for 5 minutes
symbol_cache = TTLCache(maxsize=10000, ttl=300)

def get_br_symbol(symbol, exchange):
    key = f"{symbol}:{exchange}"
    if key in symbol_cache:
        return symbol_cache[key]

    result = db_lookup(symbol, exchange)
    symbol_cache[key] = result
    return result
```

### Database Index

```sql
CREATE INDEX idx_symbol_exchange ON symtoken(symbol, exchange);
CREATE INDEX idx_token ON symtoken(token);
```

## Status Tracking

### master_contract_status Table

```
┌────────────────────────────────────────────────────────────────┐
│               master_contract_status table                      │
├──────────────────┬──────────────┬──────────────────────────────┤
│ Column           │ Type         │ Description                  │
├──────────────────┼──────────────┼──────────────────────────────┤
│ id               │ INTEGER PK   │ Auto-increment               │
│ broker           │ VARCHAR      │ Broker name (unique)         │
│ status           │ VARCHAR      │ pending/success/failed       │
│ last_sync_at     │ DATETIME     │ Last successful sync         │
│ record_count     │ INTEGER      │ Total symbols                │
│ error_message    │ TEXT         │ Error details if failed      │
└──────────────────┴──────────────┴──────────────────────────────┘
```

## Error Handling

### Download Failures

```python
def download_master_contract():
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        process_data(response.text)
        update_status("success")
    except requests.Timeout:
        logger.error("Download timeout")
        update_status("failed", "Timeout")
    except Exception as e:
        logger.error(f"Download failed: {e}")
        update_status("failed", str(e))
```

### Fallback to Cache

If download fails, use existing cached data:

```python
def get_symbol(symbol, exchange):
    result = db_lookup(symbol, exchange)
    if result:
        return result

    # Log warning but don't fail
    logger.warning(f"Symbol not found: {symbol}:{exchange}")
    return None
```

## Daily Refresh

### Scheduled Update

```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

@scheduler.scheduled_job('cron', hour=8, minute=0)
def daily_contract_refresh():
    """Refresh contracts at 8 AM daily"""
    for broker in get_active_brokers():
        async_master_contract_download(broker)
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `broker/*/database/master_contract_db.py` | Broker download |
| `database/token_db.py` | Symbol lookup |
| `database/master_contract_status_db.py` | Status tracking |
| `utils/auth_utils.py` | Async download trigger |
