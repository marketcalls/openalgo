# 04 - Cache Architecture

## Overview

OpenAlgo implements a multi-layer caching system to achieve high performance with 100,000+ trading symbols. The caching architecture minimizes database queries, reduces latency, and ensures fast API responses during high-frequency trading operations.

## Cache Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Cache Architecture                                   │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           Application Layer                                  │
│                                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  REST API   │  │  WebSocket  │  │  Services   │  │  Broker Callbacks   │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                │                     │            │
│         └────────────────┴────────────────┴─────────────────────┘            │
│                                   │                                          │
└───────────────────────────────────┼──────────────────────────────────────────┘
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         In-Memory Cache Layer                                 │
│                                                                               │
│  ┌──────────────────────┐  ┌──────────────────────┐  ┌────────────────────┐  │
│  │   Symbol Cache       │  │    Auth Caches       │  │   API Key Caches   │  │
│  │   (BrokerSymbolCache)│  │                      │  │                    │  │
│  │                      │  │  ┌────────────────┐  │  │  ┌──────────────┐  │  │
│  │  • 100K+ symbols     │  │  │  auth_cache    │  │  │  │  verified_   │  │  │
│  │  • Multi-index maps  │  │  │  TTL: session  │  │  │  │  api_key     │  │  │
│  │  • O(1) lookups      │  │  └────────────────┘  │  │  │  TTL: 10hr   │  │  │
│  │  • ~50MB memory      │  │                      │  │  └──────────────┘  │  │
│  │                      │  │  ┌────────────────┐  │  │                    │  │
│  │  Indexes:            │  │  │ feed_token_    │  │  │  ┌──────────────┐  │  │
│  │  • by_symbol_exchange│  │  │ cache          │  │  │  │  invalid_    │  │  │
│  │  • by_token_exchange │  │  │ TTL: session   │  │  │  │  api_key     │  │  │
│  │  • by_brsymbol       │  │  └────────────────┘  │  │  │  TTL: 5min   │  │  │
│  │  • by_token          │  │                      │  │  └──────────────┘  │  │
│  │                      │  │  ┌────────────────┐  │  │                    │  │
│  │                      │  │  │ broker_cache   │  │  │                    │  │
│  │                      │  │  │ TTL: 50min     │  │  │                    │  │
│  │                      │  │  └────────────────┘  │  │                    │  │
│  └──────────────────────┘  └──────────────────────┘  └────────────────────┘  │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Cache Miss
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Database Layer                                       │
│                                                                               │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                  │
│  │   symtoken     │  │     auth       │  │   api_keys     │                  │
│  │   (symbols)    │  │   (tokens)     │  │   (hashes)     │                  │
│  └────────────────┘  └────────────────┘  └────────────────┘                  │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Cache Types

### 1. Symbol Cache (BrokerSymbolCache)

High-performance in-memory cache for 100,000+ trading symbols.

**Location:** `database/token_db_enhanced.py`

**Features:**
- O(1) lookups via multiple indexes
- ~50MB memory for 100K symbols
- Session-based TTL (resets at 3:00 AM IST)
- Cache statistics tracking

```python
@dataclass
class SymbolData:
    """Lightweight symbol data structure for in-memory storage"""
    symbol: str          # OpenAlgo symbol (NSE:SBIN-EQ)
    brsymbol: str        # Broker symbol (SBIN)
    name: str            # Company name
    exchange: str        # Exchange (NSE, NFO, BSE)
    brexchange: str      # Broker exchange code
    token: str           # Instrument token
    expiry: str          # Expiry date (for F&O)
    strike: float        # Strike price (for options)
    lotsize: int         # Lot size
    instrumenttype: str  # EQ, FUT, CE, PE
    tick_size: float     # Price tick size

class BrokerSymbolCache:
    def __init__(self):
        # Primary storage
        self.symbols: Dict[str, SymbolData] = {}

        # Multi-index maps for O(1) lookups
        self.by_symbol_exchange: Dict[Tuple[str, str], SymbolData] = {}
        self.by_token_exchange: Dict[Tuple[str, str], SymbolData] = {}
        self.by_brsymbol_exchange: Dict[Tuple[str, str], SymbolData] = {}
        self.by_token: Dict[str, SymbolData] = {}

        # Statistics
        self.stats = CacheStats()
```

**Cache Population:**
```python
def load_all_symbols(self, broker: str) -> bool:
    """Load all symbols for the active broker into memory"""
    symbols = SymToken.query.all()  # One-time DB query

    for sym in symbols:
        symbol_data = SymbolData(...)

        # Build indexes for O(1) lookups
        self.symbols[sym.token] = symbol_data
        self.by_symbol_exchange[(sym.symbol, sym.exchange)] = symbol_data
        self.by_token_exchange[(sym.token, sym.exchange)] = symbol_data
        self.by_brsymbol_exchange[(sym.brsymbol, sym.exchange)] = symbol_data
        self.by_token[sym.token] = symbol_data

    self.stats.total_symbols = len(symbols)
    self.stats.memory_usage_mb = len(self.symbols) * 500 / (1024 * 1024)
```

**Lookup Example:**
```python
def get_token(self, symbol: str, exchange: str) -> Optional[str]:
    """Get token for symbol and exchange - O(1) lookup"""
    self.stats.hits += 1
    key = (symbol, exchange)
    if key in self.by_symbol_exchange:
        return self.by_symbol_exchange[key].token
    self.stats.misses += 1
    return None
```

### 2. Authentication Caches

**Location:** `database/auth_db.py`

```python
from cachetools import TTLCache

# Auth token cache - TTL based on session expiry
auth_cache = TTLCache(maxsize=1024, ttl=get_session_based_cache_ttl())

# Feed token cache - same TTL as auth
feed_token_cache = TTLCache(maxsize=1024, ttl=get_session_based_cache_ttl())

# Broker name cache - 50 minute TTL
broker_cache = TTLCache(maxsize=1024, ttl=3000)
```

**Session-Based TTL Calculation:**
```python
def get_session_based_cache_ttl():
    """Calculate cache TTL based on daily session expiry time"""
    expiry_time = os.getenv('SESSION_EXPIRY_TIME', '03:00')
    hour, minute = map(int, expiry_time.split(':'))

    now_ist = datetime.now(pytz.timezone('Asia/Kolkata'))
    target_time = now_ist.replace(hour=hour, minute=minute)

    if now_ist >= target_time:
        target_time += timedelta(days=1)

    time_until_expiry = (target_time - now_ist).total_seconds()
    return max(300, min(time_until_expiry, 24 * 3600))  # 5min - 24hr bounds
```

### 3. API Key Caches

**Three-Level API Key Verification:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    API Key Verification Flow                     │
└─────────────────────────────────────────────────────────────────┘

API Request with Key
        │
        ▼
┌─────────────────┐     Found      ┌─────────────────┐
│ invalid_api_key │───────────────►│ REJECT (Fast)   │
│ cache (5min)    │                │ Return 401      │
└────────┬────────┘                └─────────────────┘
         │ Not Found
         ▼
┌─────────────────┐     Found      ┌─────────────────┐
│ verified_api_   │───────────────►│ ACCEPT (Fast)   │
│ key cache (10hr)│                │ Return user_id  │
└────────┬────────┘                └─────────────────┘
         │ Not Found
         ▼
┌─────────────────┐                ┌─────────────────┐
│ Database Query  │───────────────►│ Argon2 Verify   │
│ (Expensive)     │                │ (Slow)          │
└─────────────────┘                └────────┬────────┘
                                            │
              ┌─────────────────────────────┴─────────────────────────────┐
              │                                                           │
              ▼ Valid                                              Invalid ▼
    ┌─────────────────┐                                      ┌─────────────────┐
    │ Add to verified │                                      │ Add to invalid  │
    │ cache (10hr)    │                                      │ cache (5min)    │
    └─────────────────┘                                      └─────────────────┘
```

**Implementation:**
```python
# Valid API keys - long TTL (10 hours)
# Only stores user_id, not the key itself
verified_api_key_cache = TTLCache(maxsize=1024, ttl=36000)

# Invalid API keys - short TTL (5 minutes)
# Prevents repeated expensive Argon2 verification
invalid_api_key_cache = TTLCache(maxsize=512, ttl=300)

def verify_api_key(api_key: str) -> Optional[str]:
    """Verify API key with 3-level caching"""
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # Level 1: Check invalid cache (fast rejection)
    if key_hash in invalid_api_key_cache:
        return None

    # Level 2: Check valid cache (fast acceptance)
    if key_hash in verified_api_key_cache:
        return verified_api_key_cache[key_hash]  # Returns user_id

    # Level 3: Database verification (expensive)
    user_id = db_verify_api_key(api_key)  # Argon2 verification

    if user_id:
        verified_api_key_cache[key_hash] = user_id
    else:
        invalid_api_key_cache[key_hash] = True

    return user_id
```

## Cache Lifecycle

### 1. Startup Restoration

On application startup, caches are restored from database:

```python
# database/cache_restoration.py
def restore_all_caches() -> dict:
    """Restore all caches from database on application startup"""
    result = {
        'symbol_cache': restore_symbol_cache(),
        'auth_cache': restore_auth_cache()
    }
    return result

def restore_auth_cache():
    """Load non-revoked auth tokens into memory"""
    auth_records = Auth.query.filter_by(is_revoked=False).all()

    for auth_record in auth_records:
        cache_key = f"auth-{auth_record.name}"
        auth_cache[cache_key] = auth_record

        if auth_record.feed_token:
            feed_token_cache[f"feed-{auth_record.name}"] = auth_record

def restore_symbol_cache():
    """Load symbols if active broker session exists"""
    auth_record = Auth.query.filter_by(is_revoked=False).first()
    if auth_record:
        cache = get_cache()
        cache.load_all_symbols(auth_record.broker)
```

### 2. Login Population

After successful broker authentication:

```python
# utils/auth_utils.py
def async_master_contract_download(broker):
    """Download master contract and populate symbol cache"""
    # Download from broker
    master_contract_module.master_contract_download()

    # Load symbols into memory cache
    from database.master_contract_cache_hook import hook_into_master_contract_download
    hook_into_master_contract_download(broker)
```

**Cache Hook:**
```python
# database/master_contract_cache_hook.py
def load_symbols_to_cache(broker: str) -> bool:
    """Load all symbols into memory cache after master contract download"""
    from database.token_db_enhanced import load_cache_for_broker, get_cache_stats

    success = load_cache_for_broker(broker)

    if success:
        stats = get_cache_stats()
        socketio.emit('cache_loaded', {
            'status': 'success',
            'broker': broker,
            'total_symbols': stats['total_symbols'],
            'memory_usage_mb': stats['stats']['memory_usage_mb']
        })
    return success
```

### 3. Logout Cleanup

On logout, caches are cleared:

```python
# blueprints/auth.py
def logout():
    username = session['user']

    # Clear auth caches
    del auth_cache[f"auth-{username}"]
    del feed_token_cache[f"feed-{username}"]

    # Clear symbol cache
    from database.master_contract_cache_hook import clear_cache_on_logout
    clear_cache_on_logout()
```

## Cache Statistics & Health

### Statistics Tracking

```python
@dataclass
class CacheStats:
    hits: int = 0           # Cache hits
    misses: int = 0         # Cache misses
    db_queries: int = 0     # Direct DB queries
    bulk_queries: int = 0   # Bulk DB queries
    cache_loads: int = 0    # Full cache loads
    last_loaded: datetime   # Last load timestamp
    total_symbols: int = 0  # Total cached symbols
    memory_usage_mb: float  # Memory consumption

    def get_hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0
```

### Health Monitoring

```python
# database/master_contract_cache_hook.py
def get_cache_health() -> dict:
    """Get cache health information for monitoring"""
    stats = get_cache_stats()
    hit_rate = float(stats['stats']['hit_rate'].rstrip('%'))

    # Calculate health score
    health_score = 100
    if not stats['cache_loaded']:
        health_score = 0
    elif not stats['cache_valid']:
        health_score = 50
    elif hit_rate < 90:
        health_score = 75

    return {
        'health_score': health_score,
        'status': 'healthy' if health_score >= 75 else 'degraded',
        'cache_loaded': stats['cache_loaded'],
        'cache_valid': stats['cache_valid'],
        'hit_rate': stats['stats']['hit_rate'],
        'total_symbols': stats['total_symbols'],
        'memory_usage_mb': stats['stats']['memory_usage_mb'],
        'recommendations': _get_health_recommendations(health_score, stats)
    }
```

## Cache Configuration

### Environment Variables

```bash
# Session expiry time (cache reset time)
SESSION_EXPIRY_TIME=03:00

# Cache sizes (in code, not configurable via env)
# auth_cache: maxsize=1024
# feed_token_cache: maxsize=1024
# broker_cache: maxsize=1024
# verified_api_key_cache: maxsize=1024
# invalid_api_key_cache: maxsize=512
```

### TTL Summary

| Cache | TTL | Purpose |
|-------|-----|---------|
| `auth_cache` | Until session expiry | Auth token storage |
| `feed_token_cache` | Until session expiry | WebSocket feed tokens |
| `broker_cache` | 50 minutes | Broker name lookups |
| `verified_api_key_cache` | 10 hours | Valid API key user IDs |
| `invalid_api_key_cache` | 5 minutes | Failed API key attempts |
| `symbol_cache` | Until session expiry | Trading symbols |

## Performance Characteristics

### Memory Usage

| Component | Size | Memory |
|-----------|------|--------|
| Symbol Cache (100K symbols) | ~500 bytes/symbol | ~50 MB |
| Auth Cache (1024 entries) | ~1 KB/entry | ~1 MB |
| API Key Cache (1024 entries) | ~100 bytes/entry | ~100 KB |
| **Total** | | **~52 MB** |

### Lookup Performance

| Operation | Complexity | Latency |
|-----------|------------|---------|
| Symbol lookup (cached) | O(1) | <1 ms |
| Auth token lookup (cached) | O(1) | <1 ms |
| API key verification (cached) | O(1) | <1 ms |
| API key verification (DB) | O(1) + Argon2 | ~100 ms |
| Symbol lookup (DB fallback) | O(log n) | ~5 ms |

## Cache Invalidation

### Automatic Invalidation

1. **TTL Expiry** - Caches auto-expire based on TTL
2. **Session Expiry** - Symbol and auth caches reset at 3:00 AM IST
3. **Logout** - All user-specific caches cleared

### Manual Invalidation

```python
# Clear symbol cache
from database.token_db_enhanced import clear_cache
clear_cache()

# Clear auth cache for user
del auth_cache[f"auth-{username}"]
del feed_token_cache[f"feed-{username}"]

# Invalidate API key cache on regeneration
# (Handled automatically by clearing verified_api_key_cache)
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `database/token_db_enhanced.py` | Symbol cache implementation |
| `database/auth_db.py` | Auth and API key caches |
| `database/cache_restoration.py` | Startup cache restoration |
| `database/master_contract_cache_hook.py` | Cache lifecycle hooks |

## Best Practices

1. **Always check cache first** - Use cache methods before DB queries
2. **Invalidate on mutation** - Clear relevant cache entries on data changes
3. **Monitor hit rates** - Investigate if hit rate drops below 90%
4. **Respect TTLs** - Don't manually extend cache entries
5. **Handle cache misses gracefully** - Fall back to DB on miss
