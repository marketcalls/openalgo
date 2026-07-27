# 46 - Search

## Overview

OpenAlgo provides fast symbol search across equity, futures, and options instruments. The search system uses an in-memory cache with database fallback for optimal performance.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Search Architecture                                  │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           Search Request                                     │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  React UI       │  │   REST API      │  │   MCP Tools     │             │
│  │  /search        │  │   /api/search   │  │   search_inst   │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                │                                             │
│                        Search Service                                        │
│                                │                                             │
└────────────────────────────────┼────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    BrokerSymbolCache (Singleton)                             │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    In-Memory Data Structures                         │   │
│  │                                                                      │   │
│  │  symbols_list[]     - All symbols for iteration                     │   │
│  │  symbol_index{}     - symbol → data (O(1) lookup)                   │   │
│  │  exchange_index{}   - exchange → [symbols] (filtered search)        │   │
│  │  type_index{}       - instrument_type → [symbols]                   │   │
│  │  expiry_index{}     - underlying → [expiry_dates]                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                    ┌───────────────┴───────────────┐                        │
│                    │                               │                         │
│               Cache Hit                       Cache Miss                     │
│                    │                               │                         │
│                    ▼                               ▼                         │
│           Return from memory              Query database                     │
│           (microseconds)                  (milliseconds)                     │
│                                                    │                         │
│                                                    ▼                         │
│                                           Update cache                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Cache Architecture

### Singleton Pattern

```python
class BrokerSymbolCache:
    """Singleton cache for broker symbols"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.symbols_list = []
        self.symbol_index = {}       # symbol:exchange → data
        self.exchange_index = {}     # exchange → [symbols]
        self.type_index = {}         # type → [symbols]
        self.expiry_index = {}       # underlying → [expiries]
        self._initialized = True
```

### Index Structures

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         Index Data Structures                               │
│                                                                             │
│  symbol_index (Hash Map)                                                    │
│  ─────────────────────────────────────────                                  │
│  "SBIN:NSE"      → {symbol, exchange, token, lotsize, ...}                 │
│  "NIFTY:NFO"     → {symbol, exchange, token, lotsize, expiry, ...}         │
│  "RELIANCE:NSE"  → {symbol, exchange, token, lotsize, ...}                 │
│                                                                             │
│  exchange_index (Inverted Index)                                            │
│  ─────────────────────────────────────────                                  │
│  "NSE"  → ["SBIN", "RELIANCE", "INFY", ...]                                │
│  "NFO"  → ["NIFTY25JAN21500CE", "BANKNIFTY25JAN48000PE", ...]              │
│  "MCX"  → ["CRUDEOIL", "GOLD", "SILVER", ...]                              │
│                                                                             │
│  type_index (Inverted Index)                                                │
│  ─────────────────────────────────────────                                  │
│  "EQ"      → ["SBIN", "RELIANCE", ...]                                     │
│  "FUTIDX"  → ["NIFTY25JANFUT", "BANKNIFTY25JANFUT", ...]                   │
│  "OPTIDX"  → ["NIFTY25JAN21500CE", "NIFTY25JAN21500PE", ...]               │
│                                                                             │
│  expiry_index (Grouped Index)                                               │
│  ─────────────────────────────────────────                                  │
│  "NIFTY"     → ["30JAN25", "06FEB25", "27FEB25", ...]                       │
│  "BANKNIFTY" → ["29JAN25", "05FEB25", "26FEB25", ...]                       │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

## Search Types

### Basic Symbol Search

```python
def search_symbols(query, exchange=None, limit=50):
    """Search symbols by partial match"""
    cache = BrokerSymbolCache()
    query = query.upper()
    results = []

    # Filter by exchange if specified
    if exchange:
        candidates = cache.exchange_index.get(exchange, [])
    else:
        candidates = cache.symbols_list

    # Partial match search
    for symbol in candidates:
        if query in symbol:
            data = cache.symbol_index.get(f"{symbol}:{exchange or 'NSE'}")
            if data:
                results.append(data)
                if len(results) >= limit:
                    break

    return results
```

### FNO Search with Filters

```python
def search_fno(
    underlying,
    exchange="NFO",
    instrument_type=None,
    expiry=None,
    strike_from=None,
    strike_to=None,
    option_type=None
):
    """Search F&O instruments with filters"""
    cache = BrokerSymbolCache()
    results = []

    # Get all symbols for underlying
    candidates = [
        s for s in cache.exchange_index.get(exchange, [])
        if s.startswith(underlying)
    ]

    for symbol in candidates:
        data = cache.symbol_index.get(f"{symbol}:{exchange}")
        if not data:
            continue

        # Apply filters
        if instrument_type and data.get('instrument_type') != instrument_type:
            continue
        if expiry and data.get('expiry') != expiry:
            continue
        if strike_from and data.get('strike', 0) < strike_from:
            continue
        if strike_to and data.get('strike', 0) > strike_to:
            continue
        if option_type and data.get('option_type') != option_type:
            continue

        results.append(data)

    return results
```

### Exact Lookup (O(1))

```python
def get_symbol(symbol, exchange):
    """Get exact symbol data - O(1) lookup"""
    cache = BrokerSymbolCache()
    key = f"{symbol}:{exchange}"
    return cache.symbol_index.get(key)
```

## Database Fallback

```python
def search_with_fallback(query, exchange=None):
    """Search with database fallback"""
    # Try cache first
    cache = BrokerSymbolCache()
    if cache.is_loaded:
        return search_symbols(query, exchange)

    # Fallback to database
    from database.token_db import SymToken

    filters = [SymToken.symbol.ilike(f"%{query}%")]
    if exchange:
        filters.append(SymToken.exchange == exchange)

    results = SymToken.query.filter(*filters).limit(50).all()

    return [
        {
            'symbol': r.symbol,
            'exchange': r.exchange,
            'token': r.token,
            'lotsize': r.lotsize
        }
        for r in results
    ]
```

## Cache Loading

### Initial Load

```python
def load_cache(broker):
    """Load all symbols into cache"""
    cache = BrokerSymbolCache()

    # Get all symbols from database
    from database.token_db import SymToken
    symbols = SymToken.query.all()

    for sym in symbols:
        data = {
            'symbol': sym.symbol,
            'brsymbol': sym.brsymbol,
            'exchange': sym.exchange,
            'token': sym.token,
            'lotsize': sym.lotsize,
            'tick_size': sym.tick_size,
            'instrument_type': sym.instrument_type,
            'expiry': sym.expiry,
            'strike': sym.strike,
            'option_type': sym.option_type
        }

        # Add to all indexes
        key = f"{sym.symbol}:{sym.exchange}"
        cache.symbol_index[key] = data
        cache.symbols_list.append(sym.symbol)

        # Exchange index
        if sym.exchange not in cache.exchange_index:
            cache.exchange_index[sym.exchange] = []
        cache.exchange_index[sym.exchange].append(sym.symbol)

        # Type index
        if sym.instrument_type:
            if sym.instrument_type not in cache.type_index:
                cache.type_index[sym.instrument_type] = []
            cache.type_index[sym.instrument_type].append(sym.symbol)

        # Expiry index (for F&O)
        if sym.expiry and hasattr(sym, 'underlying'):
            underlying = sym.underlying or sym.symbol[:5]
            if underlying not in cache.expiry_index:
                cache.expiry_index[underlying] = set()
            cache.expiry_index[underlying].add(sym.expiry)

    cache.is_loaded = True
    logger.info(f"Cache loaded: {len(cache.symbols_list)} symbols")
```

### Cache Refresh

```python
def refresh_cache():
    """Refresh cache after master contract download"""
    cache = BrokerSymbolCache()

    # Clear existing data
    cache.symbols_list.clear()
    cache.symbol_index.clear()
    cache.exchange_index.clear()
    cache.type_index.clear()
    cache.expiry_index.clear()
    cache.is_loaded = False

    # Reload
    load_cache(get_active_broker())
```

## API Endpoints

### Search Symbols

```
GET /api/v1/search?query=SBIN&exchange=NSE&limit=20
Authorization: Bearer YOUR_API_KEY
```

**Response:**
```json
{
    "status": "success",
    "data": [
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "token": "779",
            "lotsize": 1,
            "instrument_type": "EQ"
        },
        {
            "symbol": "SBIN-EQ",
            "exchange": "NSE",
            "token": "779",
            "lotsize": 1,
            "instrument_type": "EQ"
        }
    ]
}
```

### Search F&O

```
GET /api/v1/search/fno?underlying=NIFTY&exchange=NFO&expiry=30JAN25&option_type=CE
Authorization: Bearer YOUR_API_KEY
```

**Response:**
```json
{
    "status": "success",
    "data": [
        {
            "symbol": "NIFTY25JAN21500CE",
            "exchange": "NFO",
            "token": "12345",
            "lotsize": 50,
            "strike": 21500,
            "option_type": "CE",
            "expiry": "30JAN25"
        }
    ]
}
```

### Get Expiries

```
GET /api/v1/search/expiries?underlying=NIFTY&exchange=NFO
Authorization: Bearer YOUR_API_KEY
```

**Response:**
```json
{
    "status": "success",
    "data": ["30JAN25", "06FEB25", "27FEB25", "27MAR25"]
}
```

## Frontend Integration

### Search Component

```typescript
function SymbolSearch() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const debouncedQuery = useDebounce(query, 300);

  useEffect(() => {
    if (debouncedQuery.length >= 2) {
      api.searchSymbols(debouncedQuery)
        .then(data => setResults(data))
        .catch(console.error);
    } else {
      setResults([]);
    }
  }, [debouncedQuery]);

  return (
    <div className="relative">
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search symbols..."
        className="input input-bordered w-full"
      />

      {results.length > 0 && (
        <ul className="absolute z-10 w-full bg-base-100 shadow-lg rounded-lg mt-1">
          {results.map((item) => (
            <li
              key={`${item.symbol}:${item.exchange}`}
              className="px-4 py-2 hover:bg-base-200 cursor-pointer"
              onClick={() => onSelect(item)}
            >
              <span className="font-medium">{item.symbol}</span>
              <span className="badge badge-sm ml-2">{item.exchange}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

### F&O Filter Component

```typescript
function FnOSearch() {
  const [filters, setFilters] = useState({
    underlying: 'NIFTY',
    exchange: 'NFO',
    expiry: '',
    optionType: '',
    strikeFrom: '',
    strikeTo: ''
  });

  const { data: expiries } = useQuery({
    queryKey: ['expiries', filters.underlying],
    queryFn: () => api.getExpiries(filters.underlying)
  });

  const { data: results } = useQuery({
    queryKey: ['fno-search', filters],
    queryFn: () => api.searchFnO(filters),
    enabled: !!filters.expiry
  });

  return (
    <div className="space-y-4">
      <select
        value={filters.underlying}
        onChange={(e) => setFilters({...filters, underlying: e.target.value})}
      >
        <option value="NIFTY">NIFTY</option>
        <option value="BANKNIFTY">BANKNIFTY</option>
        <option value="FINNIFTY">FINNIFTY</option>
      </select>

      <select
        value={filters.expiry}
        onChange={(e) => setFilters({...filters, expiry: e.target.value})}
      >
        {expiries?.map(exp => (
          <option key={exp} value={exp}>{exp}</option>
        ))}
      </select>

      <div className="flex gap-2">
        <button
          className={`btn ${filters.optionType === 'CE' ? 'btn-success' : 'btn-ghost'}`}
          onClick={() => setFilters({...filters, optionType: 'CE'})}
        >
          CALL
        </button>
        <button
          className={`btn ${filters.optionType === 'PE' ? 'btn-error' : 'btn-ghost'}`}
          onClick={() => setFilters({...filters, optionType: 'PE'})}
        >
          PUT
        </button>
      </div>

      <table className="table">
        {/* Results table */}
      </table>
    </div>
  );
}
```

## Performance Characteristics

| Operation | Time Complexity | Notes |
|-----------|----------------|-------|
| Exact lookup | O(1) | Hash map access |
| Prefix search | O(n) | Linear scan with filter |
| Exchange filter | O(k) | k = symbols in exchange |
| F&O filter | O(k × m) | k = candidates, m = filters |
| Cache load | O(n) | n = total symbols |

## Key Files Reference

| File | Purpose |
|------|---------|
| `services/search_service.py` | Search logic and cache |
| `database/token_db.py` | Symbol database queries |
| `restx_api/search.py` | Search API endpoints |
| `frontend/src/components/SymbolSearch.tsx` | Search UI component |
| `frontend/src/pages/FnOChain.tsx` | F&O search interface |
