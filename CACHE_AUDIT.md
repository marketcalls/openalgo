# OpenAlgo Cache Architecture Audit

**Date:** 2026-02-22
**Scope:** All in-memory caching, persistence, eviction, concurrency, fault tolerance, and security
**Codebase:** OpenAlgo (Flask + React 19 algorithmic trading platform)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Cache Inventory](#2-cache-inventory)
3. [Architecture Analysis](#3-architecture-analysis)
4. [Data Scope](#4-data-scope)
5. [Persistence](#5-persistence)
6. [Eviction & Expiry](#6-eviction--expiry)
7. [Consistency & Invalidation](#7-consistency--invalidation)
8. [Performance](#8-performance)
9. [Concurrency & Thread Safety](#9-concurrency--thread-safety)
10. [Observability](#10-observability)
11. [Security](#11-security)
12. [Environment-Specific Behavior](#12-environment-specific-behavior)
13. [Risk Assessment](#13-risk-assessment)
14. [Recommendations](#14-recommendations)

---

## 1. Executive Summary

OpenAlgo uses a **multi-layer, all-in-memory caching architecture** built primarily on `cachetools.TTLCache` with one custom singleton cache (`BrokerSymbolCache`). There are **20+ distinct cache instances** spread across 10 database modules. No external cache service (Redis, Memcached) is used.

### Strengths
- Well-structured TTL-based caching with appropriate expiry times
- ZeroMQ-based cross-process cache invalidation (solves GitHub issue #765)
- Cache restoration on restart (avoids re-login requirement)
- Symbol cache with O(1) multi-index lookups and performance statistics
- Proper cache invalidation on credential changes and logout

### Key Risks
- **No thread-safety on TTLCache instances** — `cachetools.TTLCache` is not thread-safe; concurrent Flask request threads can corrupt cache state
- **Broker cache key leaks plaintext API key** — `broker_cache` uses raw `provided_api_key` as cache key
- **Unbounded growth in WebSocket throttle maps** — `last_message_time` dict grows without bound under high symbol churn
- **Rate limiter state lost on restart** — `memory://` storage is ephemeral; banned IPs reset on restart
- **Dummy/dead cache in `token_db.py`** — A `TTLCache` is allocated for backward compatibility but never used
- **No encryption of decrypted tokens in memory** — After decryption, auth tokens live in plain text in TTLCache entries

---

## 2. Cache Inventory

### 2.1 TTLCache Instances (cachetools)

| # | Cache Variable | File | maxsize | TTL | Purpose |
|---|---------------|------|---------|-----|---------|
| 1 | `auth_cache` | `database/auth_db.py:115` | 1024 | Session expiry (dynamic) | Broker auth tokens (encrypted Auth objects) |
| 2 | `feed_token_cache` | `database/auth_db.py:117` | 1024 | Session expiry (dynamic) | Broker feed/streaming tokens |
| 3 | `broker_cache` | `database/auth_db.py:119` | 1024 | 3000s (~50 min) | API key → broker name mapping |
| 4 | `verified_api_key_cache` | `database/auth_db.py:123` | 1024 | 36000s (10 hr) | SHA256(api_key) → user_id |
| 5 | `invalid_api_key_cache` | `database/auth_db.py:125` | 512 | 300s (5 min) | SHA256(bad_key) → True |
| 6 | `_settings_cache` | `database/settings_db.py:19` | 10 | 3600s (1 hr) | analyze_mode, security settings |
| 7 | `_strategy_webhook_cache` | `database/strategy_db.py:15` | 5000 | 300s (5 min) | webhook_id → Strategy |
| 8 | `_user_strategies_cache` | `database/strategy_db.py:16` | 1000 | 600s (10 min) | user_id → [strategies] |
| 9 | `_workflow_webhook_cache` | `database/flow_db.py:27` | 5000 | 300s (5 min) | webhook_token → Workflow |
| 10 | `_workflow_cache` | `database/flow_db.py:28` | 1000 | 600s (10 min) | Workflow details |
| 11 | `_telegram_user_cache` | `database/telegram_db.py:38` | 10000 | 1800s (30 min) | Telegram chat_id → user |
| 12 | `_telegram_username_cache` | `database/telegram_db.py:39` | 10000 | 1800s (30 min) | Username → user |
| 13 | `_user_preferences_cache` | `database/telegram_db.py:40` | 10000 | 1800s (30 min) | User preferences |
| 14 | `_user_credentials_cache` | `database/telegram_db.py:41` | 10000 | 1800s (30 min) | User API credentials |
| 15 | `_timings_cache` | `database/market_calendar_db.py:32` | 500 | 3600s (1 hr) | Market open/close times |
| 16 | `_holidays_cache` | `database/market_calendar_db.py:33` | 50 | 3600s (1 hr) | Market holidays |
| 17 | `username_cache` | `database/user_db.py:58` | 1024 | 30s | Username existence checks |
| 18 | `token_cache` (DEAD) | `database/token_db.py:42` | 1024 | 3600s | **Unused** — dummy for backward compat |

### 2.2 Custom Caches

| # | Cache | File | Type | Eviction | Purpose |
|---|-------|------|------|----------|---------|
| 19 | `BrokerSymbolCache` | `database/token_db_enhanced.py:109` | Singleton dict-of-dicts | Session-based validity check | 100K+ symbols with multi-index O(1) lookups |
| 20 | `_freeze_qty_cache` | `database/qty_freeze_db.py:42` | Plain dict | None (permanent) | F&O quantity freeze limits |
| 21 | `last_message_time` | `websocket_proxy/server.py:76` | Plain dict | Periodic cleanup (5 min) | WebSocket message throttling (50ms) |
| 22 | Rate limiter store | `limiter.py:7` | `memory://` (flask-limiter) | Moving window | Request rate limiting |

### 2.3 Flask Session Cache

| # | Cache | Mechanism | TTL |
|---|-------|-----------|-----|
| 23 | Flask sessions | Server-side signed cookies | SESSION_EXPIRY_TIME (default 03:00 IST) |

---

## 3. Architecture Analysis

### A. In-Memory vs Disk-Based vs Distributed

**All caches are in-memory only.** No disk-based or distributed cache exists.

```
┌─────────────────────────────────────────────────────┐
│                   Flask Process                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │  TTLCache ×17│  │BrokerSymbol  │  │ Rate Limiter│ │
│  │  (cachetools)│  │Cache (custom)│  │  (memory://)│ │
│  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘ │
│         │                 │                 │        │
│         ▼                 ▼                 ▼        │
│  ┌──────────────────────────────────────────────────┐│
│  │         SQLite / PostgreSQL (fallback)            ││
│  └──────────────────────────────────────────────────┘│
│                         │                            │
│                    ZeroMQ PUB/SUB                     │
│                         │                            │
└─────────────────────────┼────────────────────────────┘
                          │
            ┌─────────────▼─────────────┐
            │   WebSocket Proxy Process  │
            │  ┌─────────────────────┐   │
            │  │ Throttle dict       │   │
            │  │ Subscription index  │   │
            │  └─────────────────────┘   │
            └───────────────────────────┘
```

### B. Single-Layer or Multi-Layer

**Two-layer architecture:**

1. **Layer 1 (L1):** In-memory TTLCache/dict — fast O(1) lookups
2. **Layer 2 (L2):** SQLite/PostgreSQL database — authoritative source

Every cache-miss falls through to the database. This is implemented via the consistent pattern:

```python
if key in cache:
    return cache[key]
result = db_query(key)
cache[key] = result
return result
```

### C. Local Cache Only or Shared

**Local per-process only.** Each Flask worker and the WebSocket proxy maintain independent caches. Cross-process invalidation is handled via ZeroMQ pub/sub (`database/cache_invalidation.py`), but cache contents are never shared — only invalidation signals are broadcast.

---

## 4. Data Scope

### What Objects Are Cached

| Category | Objects | Entry Size (est.) | Sensitivity |
|----------|---------|-------------------|-------------|
| Auth tokens | Encrypted Auth ORM objects | ~2 KB each | **HIGH** — broker session tokens |
| API keys | SHA256 hash → user_id mapping | ~200 bytes | MEDIUM — only stores user_id |
| Invalid API keys | SHA256 hash → True | ~100 bytes | LOW |
| Broker names | API key → broker string | ~200 bytes | **HIGH** — plaintext API key as cache key |
| Symbol data | SymbolData dataclasses | ~500 bytes each × 100K+ | LOW — public instrument data |
| Settings | Boolean/dict values | ~100 bytes | LOW |
| Strategies | Strategy ORM objects | ~1 KB each | MEDIUM — trading configs |
| Telegram users | User/credential objects | ~500 bytes each | **HIGH** — contains API credentials |
| Market calendar | Timing dicts, holiday lists | ~200 bytes each | LOW |
| Qty freeze | Symbol → integer | ~50 bytes each | LOW |
| Rate limits | IP → counter | ~100 bytes each | LOW |

### Sensitive Data in Cache

| Cache | Sensitive Data | Risk |
|-------|---------------|------|
| `auth_cache` | Encrypted Auth objects (decrypted on access) | Decrypted tokens live briefly in memory |
| `broker_cache` | Uses **raw plaintext API key** as cache key | **HIGH** — key material in dict keys |
| `_user_credentials_cache` | Telegram user API credentials | HIGH — encrypted, but cached |
| `feed_token_cache` | Encrypted feed tokens | MEDIUM — encrypted at rest in cache |
| `verified_api_key_cache` | SHA256(api_key) → user_id | LOW — SHA256 is one-way |

### Memory Footprint

| Cache | Worst-Case Memory |
|-------|-------------------|
| BrokerSymbolCache (100K symbols) | ~50 MB |
| All TTLCaches combined (at maxsize) | ~20 MB |
| Qty freeze cache | ~1 MB |
| WebSocket throttle maps | Unbounded (risk) |
| Rate limiter | ~5 MB |
| **Total estimated** | **~76 MB typical, potentially higher** |

---

## 5. Persistence

### A. Survives Restart?

| Cache | Survives Restart? | Mechanism |
|-------|-------------------|-----------|
| Auth cache | **Yes** | `cache_restoration.py` reloads from DB on startup |
| Symbol cache | **Yes** | `cache_restoration.py` reloads from DB on startup |
| Broker cache | **No** | Populated on first API call |
| API key caches | **No** | Populated on first verification |
| Settings cache | **No** | Populated on first access |
| Strategy/Flow caches | **No** | Populated on first webhook |
| Telegram caches | **No** | Populated on first bot message |
| Rate limiter | **No** | **Risk**: Banned IPs/brute force counters reset |
| Qty freeze | **Yes** | Loaded from DB on startup |
| WebSocket throttle | **No** | Reset on WebSocket proxy restart |

### B. Backed by File/DB?

All caches except rate limiter and WebSocket throttle are backed by SQLite databases:

- `db/openalgo.db` — Auth, settings, strategies, symbols, users
- `db/logs.db` — Traffic logs (IP bans)
- `db/sandbox.db` — Analyzer mode data
- `db/latency.db` — Latency metrics

### C. Snapshot or Write-Through?

**Read-through, not write-through.** Writes go directly to the database, then caches are invalidated/cleared. This is the correct pattern — the database is always the source of truth.

```
Write path:  App → Database → Clear/Invalidate Cache
Read path:   App → Cache (hit) → return
             App → Cache (miss) → Database → Populate Cache → return
```

---

## 6. Eviction & Expiry

### A. TTL Support

All `cachetools.TTLCache` instances have TTL. The `BrokerSymbolCache` uses session-based validity checking rather than TTL eviction.

### B. LRU / LFU / FIFO

`cachetools.TTLCache` uses **LRU eviction** when `maxsize` is reached. Items are evicted least-recently-used first, combined with TTL expiration.

The `BrokerSymbolCache` and `_freeze_qty_cache` have **no eviction policy** — they hold all data until explicitly cleared.

### C. Manual Invalidation

| Trigger | Caches Cleared | Mechanism |
|---------|---------------|-----------|
| Login/token update | `auth_cache`, `feed_token_cache`, `broker_cache` (all entries) | `upsert_auth()` at `auth_db.py:238` |
| API key regeneration | All auth caches + `verified_api_key_cache` + `invalid_api_key_cache` | `invalidate_user_cache()` at `auth_db.py:404` |
| Logout | Auth, feed, symbol, settings, strategy, telegram caches | `revoke_user_tokens()` at `session.py:76` |
| Session expiry | Same as logout | `check_session_validity()` decorator |
| Settings change | `_settings_cache` (specific key) | `set_analyze_mode()`, `set_security_settings()` |
| Cross-process | Auth/feed caches in other processes | ZeroMQ pub/sub via `cache_invalidation.py` |

---

## 7. Consistency & Invalidation

### A. Cache Invalidated on Update?

**Yes, for most cases.** The codebase follows a consistent pattern of clearing cache after database writes:

- `upsert_auth()` clears all auth caches and publishes ZeroMQ invalidation
- `upsert_api_key()` calls `invalidate_user_cache()` clearing all auth caches
- `set_analyze_mode()` deletes the specific cache key
- `set_security_settings()` deletes the specific cache key
- Strategy/flow CRUD operations should invalidate their respective caches

### B. Versioned Keys?

**No.** Cache keys are static strings (e.g., `"auth-{username}"`, `"analyze_mode"`). There is no versioning or generation counter.

### C. Atomic Writes?

**No.** Cache reads and writes are not atomic. The read-check-populate sequence in functions like `get_auth_token()` is a classic TOCTOU (Time-of-Check-Time-of-Use) pattern:

```python
# auth_db.py:291 — not atomic
if cache_key in auth_cache:        # Check
    auth_obj = auth_cache[cache_key]  # Use (may have been evicted between check and use)
```

However, `cachetools.TTLCache` handles `KeyError` internally for expired items, so the practical risk is low for single-threaded access. The risk increases under concurrent access (see Section 9).

---

## 8. Performance

### A. Cache Hit Ratio Logged?

**Yes, for `BrokerSymbolCache` only.** The `CacheStats` class (`token_db_enhanced.py:59`) tracks:
- `hits`, `misses`, `db_queries`, `bulk_queries`, `cache_loads`
- Hit rate calculated as `hits / (hits + misses) × 100`
- Available via `get_cache_stats()` and the `/health` endpoint

**No hit ratio tracking for TTLCache instances.** The 17 TTLCache instances have no visibility into hit/miss rates.

### B. Memory Growth Bounded?

| Cache | Bounded? | Mechanism |
|-------|----------|-----------|
| TTLCache instances | **Yes** | `maxsize` parameter + TTL eviction |
| BrokerSymbolCache | **Partially** | No maxsize; bounded by total symbols in DB (~100K) |
| `_freeze_qty_cache` | **Partially** | No maxsize; bounded by F&O symbols (~5K) |
| `last_message_time` (WS) | **No** ⚠️ | Grows with unique (symbol, exchange, mode) tuples; periodic cleanup exists but relies on symbol unsubscription |
| Rate limiter (`memory://`) | **No** ⚠️ | Flask-Limiter's in-memory storage grows with unique IPs |

---

## 9. Concurrency & Thread Safety

### Critical Finding: TTLCache Is Not Thread-Safe

`cachetools.TTLCache` is explicitly **not thread-safe** per the [cachetools documentation](https://cachetools.readthedocs.io/en/latest/#cachetools.TTLCache). Flask serves requests in multiple threads (via Werkzeug or Gunicorn with `--threads`), meaning concurrent access to these caches can cause:

- `RuntimeError: dictionary changed size during iteration` (during TTL cleanup)
- Corrupted internal state
- Lost updates

**Affected caches:** All 17 TTLCache instances in `auth_db.py`, `settings_db.py`, `strategy_db.py`, `flow_db.py`, `telegram_db.py`, `market_calendar_db.py`, `user_db.py`.

**Mitigating factors:**
1. The default deployment uses Gunicorn with `-w 1` (single worker), reducing multi-process issues
2. Flask's development server uses threads, where this is a real risk
3. The `cachetools` docs recommend wrapping with `threading.Lock` for thread-safe access

### BrokerSymbolCache Thread Safety

The `BrokerSymbolCache` (`token_db_enhanced.py`) has **no locking mechanism**. The `load_all_symbols()` method clears and rebuilds all indexes, which is not atomic. If a request thread reads from the cache while another triggers a reload, inconsistent data may be returned.

However, the design mitigates this:
- `load_all_symbols()` is called only during master contract download (user-initiated, infrequent)
- The singleton pattern ensures only one instance exists

### WebSocket Proxy Thread Safety

The WebSocket proxy (`websocket_proxy/server.py`) uses `asyncio` (single-threaded event loop) for its core operations. The `subscription_index` and `last_message_time` dicts are safe within the async context. The ZeroMQ connection manager (`connection_manager.py`) properly uses `threading.Lock` and `threading.RLock`.

### Cache Invalidation Publisher

`CacheInvalidationPublisher` (`cache_invalidation.py:33`) uses `threading.Lock` for initialization — this is correct.

---

## 10. Observability

### A. Metrics Exposed?

| Cache | Metrics | Endpoint |
|-------|---------|----------|
| BrokerSymbolCache | Hits, misses, hit rate, DB queries, memory MB, load count | `/health` via `get_cache_health()` |
| Auth cache | Count only (via `len()`) | `get_cache_restoration_status()` |
| All TTLCaches | No metrics | None |
| Rate limiter | No metrics exposed | None |

### B. Debug Logging?

**Yes, extensively.** All cache operations are logged at `DEBUG` level:
- Cache loads, clears, and invalidations
- TTL calculations
- Cache restoration on startup
- ZeroMQ invalidation messages

Logging uses the centralized `utils/logging.py` module with configurable log levels.

---

## 11. Security

### A. Encryption at Rest?

| Cache | Encryption |
|-------|-----------|
| Auth tokens in DB | **Yes** — Fernet encryption (AES-128-CBC) with PBKDF2-derived key |
| Auth tokens in cache | **Partial** — Auth objects store encrypted tokens; decrypted only on access |
| API key hashes | **Yes** — Argon2 with pepper |
| Telegram credentials | **Yes** — Fernet encryption |
| SMTP passwords | **Yes** — Fernet encryption |
| All other caches | **No** — plain text (public data) |

### B. Secrets Cached?

| Issue | Severity | Location |
|-------|----------|----------|
| `broker_cache` uses **raw API key** as dict key | **HIGH** | `auth_db.py:567-578` |
| Decrypted auth tokens returned from `get_auth_token()` | MEDIUM | Transient — not stored in cache, but caller may hold reference |
| `get_auth_token_broker()` caches decrypted token tuples | **HIGH** | `auth_db.py:641` — `auth_cache[cache_key] = (decrypted_token, broker)` |
| `_user_credentials_cache` stores encrypted API creds | MEDIUM | `telegram_db.py:41` |

### C. File Permissions?

- SQLite databases stored in `db/` directory
- Docker: `chmod 700 /app/keys` for API keys directory
- Docker: App runs as non-root `appuser`
- `.env` mounted read-only in Docker (`ro` flag)

### D. Security Recommendations

1. **Replace raw API key in `broker_cache` key** with `hashlib.sha256(api_key).hexdigest()` (consistent with `verified_api_key_cache`)
2. **Avoid caching decrypted tokens** — `get_auth_token_broker()` stores plaintext tokens in `auth_cache`
3. **Add memory scrubbing** — Consider zeroing sensitive strings after use (limited effectiveness in Python due to string immutability)

---

## 12. Environment-Specific Behavior

### A. Local Desktop (Development)

| Aspect | Behavior |
|--------|----------|
| Workers | Single process (`uv run app.py` via Werkzeug) |
| Threads | Multiple (Werkzeug default) — **TTLCache thread-safety risk** |
| Cache persistence | Lost on Ctrl+C; restored on restart from DB |
| WebSocket proxy | Integrated in Flask process |
| Rate limiter | In-memory; resets on restart |
| Risk level | **MEDIUM** — thread-safety issues possible |

### B. Production Server (Gunicorn + eventlet)

| Aspect | Behavior |
|--------|----------|
| Workers | **Must use `-w 1`** for WebSocket compatibility |
| Threads | eventlet green threads (cooperative) — reduces TTLCache thread-safety risk |
| Cache persistence | Lost on restart; restored from DB |
| WebSocket proxy | Separate process or integrated |
| Rate limiter | In-memory; resets on restart; **all rate limits lost on deploy** |
| Risk level | **LOW-MEDIUM** — eventlet's cooperative threading reduces race conditions |

### C. Docker

| Aspect | Behavior |
|--------|----------|
| Workers | Single process via `start.sh` |
| Volumes | `openalgo_db` persists SQLite databases across container restarts |
| Cache persistence | In-memory caches lost; DB survives; caches restored from DB on startup |
| WebSocket proxy | Started separately by `start.sh` (Docker/standalone mode) |
| Rate limiter | In-memory; resets on container restart |
| shm_size | Configurable (`512m` default) — affects scipy/numba, not caches |
| Risk level | **LOW** — single-process, isolated environment |

### D. Multi-Worker Deployment (Not Recommended)

If someone uses `-w N` (N > 1) despite documentation warnings:

| Aspect | Behavior |
|--------|----------|
| Cache coherence | **Each worker has independent caches** — stale data guaranteed |
| ZeroMQ invalidation | Only helps for auth cache invalidation; symbol cache not synchronized |
| WebSocket | **Broken** — Socket.IO requires single worker |
| Risk level | **HIGH** — do not use |

---

## 13. Risk Assessment

### CRITICAL

| # | Risk | Location | Impact | Likelihood |
|---|------|----------|--------|------------|
| C1 | **Plaintext API key as broker_cache key** | `auth_db.py:567-578` | API key exposure in memory dumps, debug logs, or error traces | MEDIUM |
| C2 | **Decrypted tokens cached in auth_cache** | `auth_db.py:641` | Plaintext broker session tokens persist in memory for session duration | MEDIUM |

### HIGH

| # | Risk | Location | Impact | Likelihood |
|---|------|----------|--------|------------|
| H1 | **TTLCache not thread-safe** | All 17 instances | Cache corruption under concurrent access | MEDIUM (mitigated by single-worker deployment) |
| H2 | **Rate limiter state lost on restart** | `limiter.py:7` | Brute-force protection resets; banned IPs unblocked | HIGH (every restart) |
| H3 | **`get_auth_token_broker()` queries DB on every cache hit** | `auth_db.py:604-618` | Performance bottleneck — cache hit path still queries DB for revocation check | HIGH (every API request) |

### MEDIUM

| # | Risk | Location | Impact | Likelihood |
|---|------|----------|--------|------------|
| M1 | **WebSocket throttle dict unbounded growth** | `server.py:76` | Memory leak under high symbol churn (many subscribes/unsubscribes) | LOW |
| M2 | **BrokerSymbolCache not thread-safe during reload** | `token_db_enhanced.py:144-234` | Inconsistent symbol lookups during master contract download | LOW (user-initiated, infrequent) |
| M3 | **Dummy token_cache allocated but never used** | `token_db.py:42` | Wastes memory (minor), confuses maintainers | HIGH (always present) |
| M4 | **Auth cache TTL computed once at module load** | `auth_db.py:115` | If module loaded far from expiry time, TTL becomes very long; if loaded near expiry, TTL is near-minimum (5 min) | MEDIUM |
| M5 | **`broker_cache` TTL mislabeled** | `auth_db.py:119` | Comment says "5-minute TTL" but value is `3000` (50 minutes) | LOW (cosmetic) |
| M6 | **No cache for `get_user_id()` and `get_order_mode()`** | `auth_db.py:385,654` | These query the DB on every call with no caching | MEDIUM |

### LOW

| # | Risk | Location | Impact | Likelihood |
|---|------|----------|--------|------------|
| L1 | **`_freeze_qty_cache` never expires** | `qty_freeze_db.py:42` | Stale freeze quantities if updated without restart | LOW (rarely changes) |
| L2 | **Settings cache 1-hour TTL** | `settings_db.py:19` | Settings changes take up to 1 hour to propagate | LOW (settings rarely change) |
| L3 | **Strategy/webhook cache 5-min TTL** | `strategy_db.py:15` | New strategies may not receive webhooks for up to 5 minutes | LOW |
| L4 | **Static Fernet encryption salt** | `auth_db.py:60` | `b"openalgo_static_salt"` — functional but reduces KDF diversity | LOW |

---

## 14. Recommendations

### 14.1 Critical Fixes

#### Fix C1: Hash the broker_cache key

**File:** `database/auth_db.py:567`

```python
# BEFORE (insecure):
if provided_api_key in broker_cache:
    return broker_cache[provided_api_key]
broker_cache[provided_api_key] = auth_obj.broker

# AFTER (secure):
import hashlib
cache_key = hashlib.sha256(provided_api_key.encode()).hexdigest()
if cache_key in broker_cache:
    return broker_cache[cache_key]
broker_cache[cache_key] = auth_obj.broker
```

#### Fix C2: Don't cache decrypted tokens

**File:** `database/auth_db.py:589-651`

Instead of caching `(decrypted_token, broker)`, cache `(auth_obj_id, broker)` and decrypt on demand. Alternatively, accept the current design with documentation noting that in-memory tokens exist for the session duration.

### 14.2 High-Priority Fixes

#### Fix H1: Add thread-safe wrappers to TTLCache

The `cachetools` library provides `@cached` decorator with lock support:

```python
import threading
from cachetools import TTLCache, cached

_lock = threading.Lock()
_cache = TTLCache(maxsize=1024, ttl=300)

@cached(cache=_cache, lock=_lock)
def get_cached_value(key):
    return db_query(key)
```

Alternatively, wrap cache access with a lock:

```python
_cache_lock = threading.Lock()

def get_from_cache(key):
    with _cache_lock:
        if key in cache:
            return cache[key]
    # DB fallback outside lock
    result = db_query(key)
    with _cache_lock:
        cache[key] = result
    return result
```

#### Fix H2: Use persistent rate limiter storage

Replace `memory://` with a file-based or Redis backend:

```python
# Option A: Redis (if available)
limiter = Limiter(key_func=get_remote_address, storage_uri="redis://localhost:6379")

# Option B: File-based (simpler)
limiter = Limiter(key_func=get_remote_address, storage_uri="memcached://localhost:11211")
```

If external services are not desired, document that rate limiter state is ephemeral and consider persisting ban lists to the traffic database.

#### Fix H3: Remove redundant DB query from cache hit path

**File:** `database/auth_db.py:604-618`

The `get_auth_token_broker()` function queries the DB for revocation check even on cache hits. Since `upsert_auth()` clears all caches on revocation, the cached data is already guaranteed to be non-revoked. Remove the redundant DB query:

```python
# Cache hit path should trust the cache (it's cleared on revocation)
if cache_key in auth_cache:
    return auth_cache[cache_key]
```

### 14.3 Medium-Priority Improvements

#### Fix M3: Remove dummy `token_cache`

**File:** `database/token_db.py:42`

Remove the unused `token_cache = TTLCache(maxsize=1024, ttl=3600)` and its re-export in `__all__`. Grep the codebase for any remaining references.

#### Fix M4: Recompute auth cache TTL periodically

The TTL is computed once at module import time. If the module is imported at 2:59 AM, TTL will be ~1 minute. If imported at 3:01 AM, TTL will be ~24 hours. Consider using `cachetools.TTLCache` with a dynamic TTL function or recreating the cache at session boundaries.

#### Fix M5: Correct the broker_cache TTL comment

**File:** `database/auth_db.py:119`

```python
# BEFORE:
broker_cache = TTLCache(maxsize=1024, ttl=3000)  # Wrong: says "5-minute TTL"

# AFTER:
broker_cache = TTLCache(maxsize=1024, ttl=3000)  # 50-minute TTL
```

#### Fix M1: Bound WebSocket throttle map

Add a maximum size check or periodic full cleanup:

```python
# In websocket_proxy/server.py, enhance cleanup
if len(self.last_message_time) > 10000:
    self.last_message_time.clear()
```

### 14.4 Documentation Updates

1. **Add cache architecture section to CLAUDE.md** — Document the cache hierarchy, TTL values, and invalidation flow
2. **Document single-worker requirement** — Already documented but worth emphasizing: multi-worker breaks both WebSocket and cache coherence
3. **Document rate limiter limitations** — Note that `memory://` storage resets on restart; this affects security monitoring
4. **Add cache monitoring guide** — Document how to use the `/health` endpoint and `get_cache_restoration_status()` for cache diagnostics

### 14.5 Future Enhancements

1. **Add hit/miss metrics to all TTLCache instances** — Wrap each cache with a thin metrics layer
2. **Consider Redis for shared state** — If multi-worker deployment is ever needed, Redis would solve cache coherence, rate limiting persistence, and session storage
3. **Add cache warm-up for webhook caches** — Pre-populate strategy/flow webhook caches on startup to avoid cold-start latency
4. **Add memory budget configuration** — Allow operators to configure max memory for the symbol cache via environment variable

---

## Appendix: Cache Lifecycle Diagram

```
Startup:
  app.py → setup_environment() → init all databases
  app.py → restore_all_caches() → restore_auth_cache() + restore_symbol_cache()

Login:
  brlogin → broker OAuth → upsert_auth() → clear auth caches → ZMQ invalidation
  brlogin → master contract download → hook_into_master_contract_download()
           → load_symbols_to_cache() → BrokerSymbolCache.load_all_symbols()

Runtime:
  API request → verify_api_key() → check invalid_api_key_cache
                                  → check verified_api_key_cache
                                  → Argon2 verify → cache result
              → get_auth_token_broker() → check auth_cache → DB fallback

Logout/Expiry:
  revoke_user_tokens() → clear auth_cache, feed_token_cache
                       → clear_cache_on_logout() → BrokerSymbolCache.clear_cache()
                       → clear_settings_cache()
                       → clear_strategy_cache()
                       → clear_telegram_cache()
                       → ZMQ publish_all_cache_invalidation()
                       → upsert_auth(revoke=True) → DB update

Restart:
  app.py → restore_all_caches() → reload from DB → continue without re-login
```
