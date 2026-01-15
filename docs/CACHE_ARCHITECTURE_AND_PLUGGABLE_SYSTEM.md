# OpenAlgo Cache Architecture and Pluggable System Design

**Document Version:** 1.0
**Date:** December 3, 2025
**Status:** Design Proposal

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current Architecture](#current-architecture)
3. [Problems with Current Implementation](#problems-with-current-implementation)
4. [Proposed Solution: Pluggable Cache System](#proposed-solution-pluggable-cache-system)
5. [Architecture Design](#architecture-design)
6. [Implementation Specifications](#implementation-specifications)
7. [Multi-Instance Deployment Support](#multi-instance-deployment-support)
8. [Security Considerations](#security-considerations)
9. [Configuration Management](#configuration-management)
10. [Migration Path](#migration-path)
11. [Performance Impact](#performance-impact)
12. [Testing Strategy](#testing-strategy)
13. [Appendix](#appendix)

---

## Executive Summary

### Current State

OpenAlgo uses **100% in-memory caching** with the `cachetools` library (TTLCache). All caches are cleared on application restart or user logout, requiring re-login and re-download of master contracts (142,338 symbols, 67.87 MB).

### Problems

1. **No persistence** - Multi-day strategies cannot survive app restarts
2. **Not scalable** - Cannot support multi-instance deployments
3. **Memory-intensive** - 67.87 MB symbol cache always in RAM
4. **Tightly coupled** - Cannot swap cache backends without code changes

### Proposed Solution

Implement a **pluggable cache architecture** with multiple backend support:

- **SQLite** (default): Zero-config, persistent, Windows-friendly
- **Redis**: Distributed, multi-instance, high-performance
- **Valkey**: Redis fork alternative
- **Memory**: Current behavior (testing/development)

### Key Benefits

✅ **Persistence** - Survive restarts, support multi-day strategies
✅ **Scalability** - Multi-instance deployment with shared cache
✅ **Zero-config** - Auto-enable SQLite on Windows
✅ **Flexibility** - Configuration-driven backend selection
✅ **Security** - Encrypted cache, audit logging, access control
✅ **Performance** - Choose speed vs persistence tradeoff

---

## Current Architecture

### 1. Cache Inventory

| Cache Name | Type | Size | TTL | Storage | Location |
|------------|------|------|-----|---------|----------|
| **auth_cache** | TTLCache | 1024 | Until 3 AM IST | RAM | `database/auth_db.py` |
| **feed_token_cache** | TTLCache | 1024 | Until 3 AM IST | RAM | `database/auth_db.py` |
| **broker_cache** | TTLCache | 1024 | 5 minutes | RAM | `database/auth_db.py` |
| **verified_api_key_cache** | TTLCache | 1024 | 10 hours | RAM | `database/auth_db.py` |
| **invalid_api_key_cache** | TTLCache | 512 | 5 minutes | RAM | `database/auth_db.py` |
| **settings_cache** | TTLCache | 10 | 1 hour | RAM | `database/settings_db.py` |
| **strategy_webhook_cache** | TTLCache | 5000 | 5 minutes | RAM | `database/strategy_db.py` |
| **user_strategies_cache** | TTLCache | 1000 | 10 minutes | RAM | `database/strategy_db.py` |
| **symbol_cache** | BrokerSymbolCache | 142,338 | No expiry | RAM (67.87 MB) | `database/token_db_enhanced.py` |
| **RUNNING_STRATEGIES** | dict | Variable | No expiry | RAM | `blueprints/python_strategy.py` |
| **STRATEGY_CONFIGS** | dict | Variable | No expiry | RAM | `blueprints/python_strategy.py` |

**Total:** 11 caches, ~68 MB RAM, 0 bytes disk

### 2. Current Implementation Pattern

```python
# Tightly coupled to cachetools
from cachetools import TTLCache

# Global module-level cache
auth_cache = TTLCache(maxsize=1024, ttl=86400)

# Direct dictionary access
def get_auth_token(user_id):
    if user_id in auth_cache:
        return auth_cache[user_id]

    # Fetch from database
    token = db.query(...)
    auth_cache[user_id] = token
    return token
```

**Problems:**
- Cannot swap backend without rewriting code
- No abstraction layer
- Hardcoded TTLCache dependency

### 3. State Management

**Persistent State (SQLite Database):**
- User credentials (Argon2 hashed)
- Broker auth tokens (AES-256 encrypted)
- Strategy configurations
- API keys (hashed + encrypted)
- Master contract symbols
- Sandbox orders/positions/trades

**Transient State (In-Memory Cache):**
- Authentication tokens (runtime only)
- Symbol/token mappings (runtime only)
- Settings (reloaded from DB on miss)
- Strategy execution state (runtime only)

**State on Restart:**
```
BEFORE RESTART:
✓ auth_cache: 3 tokens
✓ symbol_cache: 142,338 symbols (67.87 MB)
✓ settings_cache: 1 entry (analyze_mode)

    ↓ [RESTART] ↓

AFTER RESTART:
✗ auth_cache: 0 tokens (LOST)
✗ symbol_cache: 0 symbols (LOST)
✓ settings_cache: 1 entry (reloaded from DB)
```

### 4. Current Persistence Layer

**Database Files:**
```
db/
├── openalgo.db        116 MB  ← Main database (users, auth, strategies, symbols)
├── sandbox.db         200 KB  ← Sandbox state (fully persistent)
├── latency.db         217 KB  ← Performance monitoring
└── logs.db              4 MB  ← Traffic logs
```

**What's Persistent:**
- ✅ User accounts
- ✅ Encrypted broker tokens
- ✅ Strategy configurations
- ✅ Master contract symbols (142,338 records)
- ✅ Sandbox trading state

**What's NOT Persistent:**
- ❌ Runtime auth cache
- ❌ Symbol cache (in-memory index)
- ❌ Strategy execution state
- ❌ Python strategy processes

---

## Problems with Current Implementation

### Problem 1: No Persistence for Multi-Day Strategies

**Scenario:**
```
Day 1, 10:00 AM:
  Strategy buys RELIANCE @ ₹2500
  Position stored in memory cache

Day 1, 2:00 AM:
  App restarts (maintenance/crash)

  ✗ auth_cache cleared → Cannot authenticate
  ✗ symbol_cache cleared → Cannot resolve symbols
  ✗ Position state lost → Strategy doesn't know it has open position

Day 2, 9:15 AM:
  Strategy resumes
  ✗ Cannot fetch positions (no auth)
  ✗ Cannot place exit order
  ✗ Strategy BROKEN
```

**Impact:** Multi-day strategies are impossible with current architecture.

### Problem 2: Symbol Cache Reload Overhead

**Current Flow:**
```
1. App starts
2. User logs in
3. Master contract downloaded from broker (10-30 seconds)
4. 142,338 symbols inserted into database
5. Symbols loaded into memory cache (67.87 MB)
6. Ready to trade

Total startup time: 30-60 seconds
```

**Problem:** This happens on EVERY restart, even though symbols rarely change.

### Problem 3: No Multi-Instance Support

**Current Architecture:**
```
┌─────────────────────┐
│  OpenAlgo Instance  │
│  ┌───────────────┐  │
│  │  In-Memory    │  │ ← Isolated, cannot share
│  │  Cache        │  │
│  │  67.87 MB     │  │
│  └───────────────┘  │
└─────────────────────┘
```

**Cannot Deploy:**
```
        Load Balancer
             ↓
    ┌────────┴────────┐
    ↓                 ↓
Instance 1       Instance 2
(Cache A)        (Cache B)

Problem: Cache A ≠ Cache B
- Different symbols loaded
- Different auth tokens
- Session not shared
- Cannot load balance
```

### Problem 4: Memory Usage

**Current Memory Profile:**
```
RSS Memory: 440.27 MB

Breakdown:
- Python runtime:     ~150 MB
- Flask/Dependencies: ~150 MB
- Symbol cache:        67.87 MB (15.4% of total)
- Other caches:         ~1 MB
- Working memory:      ~71 MB
```

**Problem:** Symbol cache always in RAM, even if not actively trading.

### Problem 5: Security Concerns

**Current Issues:**
1. **No cache encryption** - Tokens in memory are plaintext
2. **No access control** - Any code can access cache
3. **No audit logging** - Cache access not tracked
4. **Memory dumps** - Sensitive data vulnerable if process dumped

---

## Proposed Solution: Pluggable Cache System

### Design Goals

1. **Persistence** - Survive restarts, support multi-day strategies
2. **Scalability** - Support multi-instance deployments
3. **Zero-config** - Auto-enable SQLite on Windows
4. **Flexibility** - Swap backends via configuration
5. **Security** - Encrypted cache, access control, audit logs
6. **Performance** - Minimal overhead vs current implementation
7. **Backward compatibility** - Existing code continues to work

### Architecture Layers

```
┌─────────────────────────────────────────────────┐
│           Application Layer                     │
│  (auth_db.py, strategy_db.py, etc.)            │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│         Cache Manager (Abstraction)             │
│  - get_cache(name, backend, config)            │
│  - Security wrapper                             │
│  - Audit logging                                │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│          Cache Backend Interface                │
│  get(), set(), delete(), clear(), exists()      │
└─────────────────────────────────────────────────┘
                    ↓
        ┌───────────┴───────────┬─────────────┐
        ↓                       ↓             ↓
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│   Memory      │   │    SQLite     │   │  Redis/Valkey │
│   Backend     │   │    Backend    │   │    Backend    │
│               │   │               │   │               │
│ - TTLCache    │   │ - Persistent  │   │ - Distributed │
│ - Fast        │   │ - Zero-config │   │ - Shared      │
│ - Ephemeral   │   │ - File-based  │   │ - High-perf   │
└───────────────┘   └───────────────┘   └───────────────┘
```

### Supported Backends

| Backend | Use Case | Persistence | Multi-Instance | Setup | Windows Support |
|---------|----------|-------------|----------------|-------|-----------------|
| **SQLite** | Single-server, Windows, zero-config | ✅ Yes | ❌ No | ✅ Zero | ✅ Perfect |
| **Redis** | Multi-server, production, distributed | ✅ Yes | ✅ Yes | ⚠️ External service | ⚠️ Complex |
| **Valkey** | Redis alternative (open-source fork) | ✅ Yes | ✅ Yes | ⚠️ External service | ⚠️ Complex |
| **Memory** | Testing, development, ephemeral | ❌ No | ❌ No | ✅ Zero | ✅ Perfect |

---

## Architecture Design

### 1. Cache Backend Interface

**File:** `database/cache_backend.py`

```python
from abc import ABC, abstractmethod
from typing import Any, Optional, List, Dict

class CacheBackend(ABC):
    """Abstract base class for cache backends"""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with optional TTL (seconds)"""
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete key from cache"""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all cache entries"""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if key exists"""
        pass

    @abstractmethod
    def size(self) -> int:
        """Return number of entries"""
        pass

    @abstractmethod
    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """Batch get (optional optimization)"""
        pass

    @abstractmethod
    def set_many(self, items: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Batch set (optional optimization)"""
        pass
```

### 2. Backend Implementations

#### SQLite Backend (Default for Windows)

**Features:**
- File-based persistent storage
- ACID transactions
- Automatic expiry cleanup
- Per-key TTL support
- Zero external dependencies

**Storage Format:**
```sql
CREATE TABLE cache (
    key TEXT PRIMARY KEY,
    value BLOB,              -- Pickled Python object
    expires_at REAL,         -- Unix timestamp
    created_at TIMESTAMP,
    accessed_at TIMESTAMP,   -- For LRU tracking
    access_count INTEGER     -- For statistics
);

CREATE INDEX idx_expires ON cache(expires_at);
CREATE INDEX idx_accessed ON cache(accessed_at);
```

**Implementation:** `database/backends/sqlite_backend.py`

#### Redis Backend (Production Multi-Instance)

**Features:**
- In-memory + optional persistence (RDB/AOF)
- Distributed caching
- Built-in TTL support
- Pub/Sub for cache invalidation
- Cluster support

**Key Format:**
```
openalgo:{cache_name}:{key}

Examples:
openalgo:auth:user_123
openalgo:symbols:RELIANCE_NSE
openalgo:settings:analyze_mode
```

**Implementation:** `database/backends/redis_backend.py`

#### Memory Backend (Testing/Development)

**Features:**
- Current TTLCache wrapper
- Fastest performance
- No persistence
- Backward compatible

**Implementation:** `database/backends/memory_backend.py`

### 3. Cache Factory

**File:** `database/cache_factory.py`

```python
import os
import platform
from typing import Dict, Type, Optional
from database.cache_backend import CacheBackend
from utils.logging import get_logger

logger = get_logger(__name__)

# Registry of available backends
CACHE_BACKENDS: Dict[str, Type[CacheBackend]] = {
    'memory': 'database.backends.memory_backend.MemoryBackend',
    'sqlite': 'database.backends.sqlite_backend.SQLiteBackend',
    'redis': 'database.backends.redis_backend.RedisBackend',
    'valkey': 'database.backends.valkey_backend.ValkeyBackend',
}

def auto_detect_backend() -> str:
    """
    Auto-detect best cache backend for current environment

    Priority:
    1. CACHE_BACKEND env variable
    2. Redis if available and configured
    3. SQLite for Windows
    4. SQLite as default (zero-config persistence)
    """
    # Explicit configuration
    if os.getenv('CACHE_BACKEND'):
        return os.getenv('CACHE_BACKEND').lower()

    # Check Redis availability
    if is_redis_available():
        logger.info("Redis detected, using Redis cache backend")
        return 'redis'

    # Windows? Use SQLite (zero-config)
    if platform.system() == 'Windows':
        logger.info("Windows detected, using SQLite cache backend (persistent, zero-config)")
        return 'sqlite'

    # Default: SQLite (persistent, works everywhere)
    logger.info("Using SQLite cache backend (default, persistent)")
    return 'sqlite'

def get_cache_backend(
    backend_type: Optional[str] = None,
    **kwargs
) -> CacheBackend:
    """
    Factory function to create cache backend

    Args:
        backend_type: 'memory', 'sqlite', 'redis', 'valkey' (auto-detected if None)
        **kwargs: Backend-specific configuration

    Returns:
        CacheBackend instance
    """
    if backend_type is None:
        backend_type = auto_detect_backend()

    backend_type = backend_type.lower()

    if backend_type not in CACHE_BACKENDS:
        raise ValueError(f"Unknown cache backend: {backend_type}")

    # Dynamic import
    module_path, class_name = CACHE_BACKENDS[backend_type].rsplit('.', 1)
    module = __import__(module_path, fromlist=[class_name])
    backend_class = getattr(module, class_name)

    return backend_class(**kwargs)

def is_redis_available() -> bool:
    """Check if Redis is available and configured"""
    try:
        import redis
        host = os.getenv('REDIS_HOST', 'localhost')
        port = int(os.getenv('REDIS_PORT', 6379))

        client = redis.Redis(host=host, port=port, socket_connect_timeout=1)
        client.ping()
        return True
    except:
        return False
```

### 4. Cache Manager (Security Layer)

**File:** `database/cache_manager.py`

```python
from typing import Dict, Optional, Any
from database.cache_factory import get_cache_backend
from database.cache_backend import CacheBackend
from cryptography.fernet import Fernet
from utils.logging import get_logger
import os
import time

logger = get_logger(__name__)

class SecureCacheManager:
    """
    Manages multiple named caches with security features

    Features:
    - Encryption for sensitive caches
    - Access control
    - Audit logging
    - Cache statistics
    """

    def __init__(self):
        self._caches: Dict[str, CacheBackend] = {}
        self.backend_type = os.getenv('CACHE_BACKEND')

        # Load encryption key for sensitive caches
        self._encryption_key = self._load_encryption_key()
        self._cipher = Fernet(self._encryption_key) if self._encryption_key else None

        # Sensitive caches that require encryption
        self._encrypted_caches = {'auth', 'api_keys', 'tokens'}

        # Audit log
        self._audit_enabled = os.getenv('CACHE_AUDIT_ENABLED', 'false').lower() == 'true'

    def get_cache(
        self,
        name: str,
        maxsize: int = 1024,
        ttl: int = 3600,
        encrypted: bool = None,
        **kwargs
    ) -> CacheBackend:
        """
        Get or create a named cache

        Args:
            name: Cache name (e.g., 'auth', 'symbols', 'settings')
            maxsize: Max entries (for memory backend)
            ttl: Time-to-live in seconds
            encrypted: Force encryption (auto-detected for sensitive caches)
            **kwargs: Backend-specific options

        Returns:
            CacheBackend instance (wrapped with security layer)
        """
        if name not in self._caches:
            # Auto-enable encryption for sensitive caches
            if encrypted is None:
                encrypted = name in self._encrypted_caches

            # Create backend
            config = self._build_backend_config(name, maxsize, ttl, **kwargs)
            backend = get_cache_backend(self.backend_type, **config)

            # Wrap with security layer if encrypted
            if encrypted and self._cipher:
                backend = EncryptedCacheWrapper(backend, self._cipher, name)

            # Wrap with audit logging if enabled
            if self._audit_enabled:
                backend = AuditCacheWrapper(backend, name)

            self._caches[name] = backend
            logger.info(f"Created cache '{name}' (backend={self.backend_type}, encrypted={encrypted})")

        return self._caches[name]

    def _build_backend_config(self, name: str, maxsize: int, ttl: int, **kwargs) -> dict:
        """Build backend-specific configuration"""
        config = {
            'default_ttl': ttl,
            **kwargs
        }

        if self.backend_type == 'memory':
            config['maxsize'] = maxsize

        elif self.backend_type in ('redis', 'valkey'):
            config['prefix'] = f'openalgo:{name}:'
            config['host'] = os.getenv('REDIS_HOST', 'localhost')
            config['port'] = int(os.getenv('REDIS_PORT', 6379))
            config['db'] = int(os.getenv('REDIS_DB', 0))
            config['password'] = os.getenv('REDIS_PASSWORD')

        elif self.backend_type == 'sqlite':
            config['db_path'] = f"db/cache_{name}.db"

        return config

    def _load_encryption_key(self) -> Optional[bytes]:
        """Load or generate encryption key for cache"""
        key_file = 'db/.cache_key'

        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                return f.read()
        else:
            # Generate new key
            key = Fernet.generate_key()
            with open(key_file, 'wb') as f:
                f.write(key)
            os.chmod(key_file, 0o600)  # Owner read/write only
            return key

    def clear_all(self):
        """Clear all caches"""
        for name, cache in self._caches.items():
            cache.clear()
            logger.info(f"Cleared cache: {name}")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        stats = {}
        for name, cache in self._caches.items():
            stats[name] = {
                'size': cache.size(),
                'backend': self.backend_type,
            }
        return stats

# Singleton instance
_cache_manager = SecureCacheManager()

def get_cache(name: str, **kwargs) -> CacheBackend:
    """Convenience function to get a named cache"""
    return _cache_manager.get_cache(name, **kwargs)

def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics"""
    return _cache_manager.get_stats()
```

### 5. Security Wrappers

**Encrypted Cache Wrapper:**

```python
class EncryptedCacheWrapper(CacheBackend):
    """Wraps cache backend with encryption"""

    def __init__(self, backend: CacheBackend, cipher: Fernet, cache_name: str):
        self._backend = backend
        self._cipher = cipher
        self._cache_name = cache_name

    def get(self, key: str) -> Optional[Any]:
        encrypted_value = self._backend.get(key)
        if encrypted_value is None:
            return None

        # Decrypt
        try:
            decrypted = self._cipher.decrypt(encrypted_value)
            return pickle.loads(decrypted)
        except Exception as e:
            logger.error(f"Decryption failed for {self._cache_name}:{key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        # Encrypt
        serialized = pickle.dumps(value)
        encrypted = self._cipher.encrypt(serialized)
        self._backend.set(key, encrypted, ttl)

    # Delegate other methods...
```

**Audit Cache Wrapper:**

```python
class AuditCacheWrapper(CacheBackend):
    """Wraps cache backend with audit logging"""

    def __init__(self, backend: CacheBackend, cache_name: str):
        self._backend = backend
        self._cache_name = cache_name

    def get(self, key: str) -> Optional[Any]:
        result = self._backend.get(key)
        self._log_access('GET', key, hit=result is not None)
        return result

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self._backend.set(key, value, ttl)
        self._log_access('SET', key)

    def delete(self, key: str) -> None:
        self._backend.delete(key)
        self._log_access('DELETE', key)

    def _log_access(self, operation: str, key: str, hit: bool = None):
        """Log cache access to audit log"""
        logger.debug(f"CACHE_AUDIT: {operation} {self._cache_name}:{key} hit={hit}")
```

---

## Multi-Instance Deployment Support

### Architecture for Multi-Instance

```
                    ┌─────────────────┐
                    │  Load Balancer  │
                    │  (Nginx/HAProxy)│
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ↓              ↓              ↓
      ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
      │ OpenAlgo     │ │ OpenAlgo     │ │ OpenAlgo     │
      │ Instance 1   │ │ Instance 2   │ │ Instance 3   │
      └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
             │                │                │
             └────────────────┼────────────────┘
                              ↓
                    ┌─────────────────┐
                    │  Redis Cluster  │
                    │  (Shared Cache) │
                    └─────────────────┘
                              ↓
                    ┌─────────────────┐
                    │  Database       │
                    │  (PostgreSQL)   │
                    └─────────────────┘
```

### Configuration for Multi-Instance

**Instance 1:** `.env`
```bash
# Instance identification
INSTANCE_ID=instance-1
INSTANCE_NAME=openalgo-web-1

# Cache backend (MUST be Redis for multi-instance)
CACHE_BACKEND=redis
REDIS_HOST=redis-cluster.internal
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=your-secure-password

# Session backend (MUST be Redis for multi-instance)
SESSION_TYPE=redis
SESSION_REDIS=redis://redis-cluster.internal:6379/1

# Database (shared across instances)
DATABASE_URL=postgresql://user:pass@db-cluster.internal:5432/openalgo
```

**Instance 2:** Same configuration with different `INSTANCE_ID`

### Session Management for Multi-Instance

**Current:** Flask server-side sessions (in-memory, not shared)

**Required:** Redis-backed sessions

```python
# app.py - Multi-instance session configuration

from flask import Flask
from flask_session import Session
import redis

app = Flask(__name__)

# Redis-backed sessions for multi-instance
if os.getenv('CACHE_BACKEND') == 'redis':
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = redis.from_url(
        f"redis://{os.getenv('REDIS_HOST')}:{os.getenv('REDIS_PORT')}/1"
    )
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_KEY_PREFIX'] = 'openalgo:session:'
else:
    # Single-instance: in-memory sessions
    app.config['SESSION_TYPE'] = 'filesystem'

Session(app)
```

### Cache Invalidation Strategy

**Problem:** Instance 1 updates data, Instance 2's cache is stale

**Solution 1: TTL-based (Simple)**
```python
# Short TTL for frequently changing data
auth_cache.set('user_123', token, ttl=300)  # 5 minutes

# Automatic expiry ensures eventual consistency
```

**Solution 2: Pub/Sub Invalidation (Advanced)**
```python
# Instance 1: Update cache and publish invalidation
auth_cache.set('user_123', new_token)
redis_client.publish('cache:invalidate', json.dumps({
    'cache': 'auth',
    'key': 'user_123'
}))

# Instance 2: Subscribe and invalidate local cache
def on_invalidation_message(message):
    data = json.loads(message['data'])
    cache = get_cache(data['cache'])
    cache.delete(data['key'])

pubsub.subscribe('cache:invalidate')
pubsub.listen(on_invalidation_message)
```

### Load Balancing Strategy

**Sticky Sessions (Recommended):**
```nginx
# nginx.conf
upstream openalgo {
    ip_hash;  # Route same IP to same instance
    server instance1:5000;
    server instance2:5000;
    server instance3:5000;
}

server {
    location / {
        proxy_pass http://openalgo;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Benefits:**
- User stays on same instance during session
- Reduces cache misses
- Simpler session management

### Health Checks

**Endpoint:** `/health`

```python
@app.route('/health')
def health_check():
    """Health check for load balancer"""

    # Check database connection
    try:
        db.session.execute('SELECT 1')
    except:
        return jsonify({'status': 'unhealthy', 'reason': 'database'}), 503

    # Check cache connection
    try:
        cache = get_cache('health')
        cache.set('health_check', time.time(), ttl=10)
        cache.get('health_check')
    except:
        return jsonify({'status': 'unhealthy', 'reason': 'cache'}), 503

    return jsonify({
        'status': 'healthy',
        'instance': os.getenv('INSTANCE_ID'),
        'cache_backend': os.getenv('CACHE_BACKEND'),
        'uptime': time.time() - app.start_time
    }), 200
```

---

## Security Considerations

### 1. Cache Encryption

**Sensitive Data in Cache:**
- Authentication tokens
- Broker credentials
- API keys
- User PII (if cached)

**Encryption Strategy:**

| Cache | Encrypted? | Reason |
|-------|-----------|--------|
| auth_cache | ✅ YES | Contains broker access tokens |
| api_keys_cache | ✅ YES | Contains API keys |
| symbol_cache | ❌ NO | Public market data |
| settings_cache | ❌ NO | Non-sensitive configuration |
| broker_cache | ❌ NO | Just broker names |

**Implementation:**
```python
# Auto-encrypt sensitive caches
auth_cache = get_cache('auth', encrypted=True)  # Fernet encryption
symbol_cache = get_cache('symbols', encrypted=False)  # No overhead
```

### 2. Access Control

**Cache Access Policy:**

```python
class CacheAccessControl:
    """Enforce access control on cache operations"""

    # Define which modules can access which caches
    ACCESS_RULES = {
        'auth_cache': ['database.auth_db', 'blueprints.auth'],
        'symbol_cache': ['database.token_db_enhanced', 'services.*'],
        'api_keys_cache': ['database.auth_db', 'restx_api.*'],
    }

    @staticmethod
    def check_access(cache_name: str, caller_module: str) -> bool:
        """Check if caller module can access cache"""
        allowed = CacheAccessControl.ACCESS_RULES.get(cache_name, ['*'])

        if '*' in allowed:
            return True

        for pattern in allowed:
            if fnmatch.fnmatch(caller_module, pattern):
                return True

        return False
```

### 3. Audit Logging

**Log All Sensitive Cache Operations:**

```python
# Enable audit logging
CACHE_AUDIT_ENABLED=true

# Audit log format
{
    "timestamp": "2025-12-03T10:30:45Z",
    "cache": "auth_cache",
    "operation": "GET",
    "key": "user_123",
    "caller": "database.auth_db.get_auth_token",
    "hit": true,
    "instance_id": "instance-1"
}
```

**Storage:** `db/cache_audit.log` (rotated daily)

### 4. Cache Poisoning Prevention

**Risks:**
- Attacker injects malicious data into cache
- All instances serve poisoned data

**Mitigations:**

1. **Input Validation:**
```python
def set(self, key: str, value: Any, ttl: Optional[int] = None):
    # Validate key format
    if not re.match(r'^[a-zA-Z0-9_\-:]+$', key):
        raise ValueError("Invalid cache key")

    # Validate value type (whitelist)
    if not isinstance(value, (str, int, float, dict, list, tuple)):
        raise ValueError("Invalid cache value type")

    self._backend.set(key, value, ttl)
```

2. **Signature Verification:**
```python
def set(self, key: str, value: Any, ttl: Optional[int] = None):
    # Sign data before caching
    signature = hmac.new(SECRET_KEY, pickle.dumps(value), hashlib.sha256).digest()
    cached_value = {'data': value, 'signature': signature}
    self._backend.set(key, cached_value, ttl)

def get(self, key: str) -> Optional[Any]:
    cached = self._backend.get(key)
    if not cached:
        return None

    # Verify signature
    expected_sig = hmac.new(SECRET_KEY, pickle.dumps(cached['data']), hashlib.sha256).digest()
    if not hmac.compare_digest(cached['signature'], expected_sig):
        logger.error(f"Cache signature mismatch for {key}")
        self.delete(key)
        return None

    return cached['data']
```

### 5. Redis Security Checklist

**For Redis/Valkey backends:**

- [ ] **Authentication:** `requirepass` in redis.conf
- [ ] **Network:** Bind to localhost or private network only
- [ ] **Encryption:** Use TLS for Redis connections
- [ ] **ACLs:** Use Redis ACLs to limit command access
- [ ] **Persistence:** Enable AOF for durability
- [ ] **Firewall:** Block Redis port (6379) from public internet
- [ ] **Monitoring:** Monitor for unusual access patterns

**Configuration:**
```bash
# redis.conf
requirepass your-strong-password
bind 127.0.0.1 10.0.0.1  # Private network only
protected-mode yes
rename-command FLUSHDB ""  # Disable dangerous commands
rename-command FLUSHALL ""
rename-command CONFIG ""
```

### 6. SQLite Security

**For SQLite backend:**

- [ ] **File Permissions:** `chmod 600 db/cache_*.db`
- [ ] **Encryption:** Use SQLCipher for encrypted database
- [ ] **Location:** Store in non-web-accessible directory
- [ ] **Backup:** Regular backups with encryption

**Implementation:**
```python
# Secure SQLite cache creation
import os
import stat

db_path = 'db/cache_auth.db'

# Create database
conn = sqlite3.connect(db_path)
# ... initialize schema

# Set secure permissions (owner read/write only)
os.chmod(db_path, stat.S_IRUSR | stat.S_IWUSR)
```

---

## Configuration Management

### Environment Variables

**File:** `.env`

```bash
#============================================================================
# CACHE CONFIGURATION
#============================================================================

# Cache Backend Selection
# Options: memory, sqlite, redis, valkey
# Default: auto-detected (sqlite for Windows, redis if available)
CACHE_BACKEND=sqlite

# Zero-Config Mode
# Set to 'true' to auto-configure cache based on environment
# Windows → SQLite, Linux with Redis → Redis, else SQLite
CACHE_AUTO_CONFIGURE=true

#----------------------------------------------------------------------------
# SQLite Cache Configuration (Default for Single-Server)
#----------------------------------------------------------------------------

# SQLite cache database path
SQLITE_CACHE_PATH=db/cache

# Default TTL for SQLite cache (seconds)
SQLITE_DEFAULT_TTL=3600

# Enable SQLite WAL mode (better concurrency)
SQLITE_WAL_MODE=true

# Vacuum interval (cleanup expired entries)
SQLITE_VACUUM_INTERVAL=86400  # 24 hours

#----------------------------------------------------------------------------
# Redis/Valkey Configuration (For Multi-Instance Deployments)
#----------------------------------------------------------------------------

# Redis host
REDIS_HOST=localhost

# Redis port
REDIS_PORT=6379

# Redis database number (0-15)
REDIS_DB=0

# Redis password (if authentication enabled)
REDIS_PASSWORD=

# Redis connection pool size
REDIS_POOL_SIZE=10

# Redis connection timeout (seconds)
REDIS_TIMEOUT=5

# Enable Redis TLS/SSL
REDIS_TLS=false

# Redis key prefix (to avoid conflicts)
REDIS_KEY_PREFIX=openalgo

#----------------------------------------------------------------------------
# Cache Security Configuration
#----------------------------------------------------------------------------

# Enable cache encryption for sensitive data
CACHE_ENCRYPTION_ENABLED=true

# Encrypt specific caches (comma-separated)
CACHE_ENCRYPTED_NAMES=auth,api_keys,tokens

# Enable cache audit logging
CACHE_AUDIT_ENABLED=false

# Audit log path
CACHE_AUDIT_LOG_PATH=db/cache_audit.log

#----------------------------------------------------------------------------
# Cache Performance Configuration
#----------------------------------------------------------------------------

# Enable cache statistics
CACHE_STATS_ENABLED=true

# Cache hit/miss logging
CACHE_METRICS_ENABLED=false

# Preload symbol cache on startup
SYMBOL_CACHE_PRELOAD=true

# Symbol cache auto-refresh interval (seconds, 0 to disable)
SYMBOL_CACHE_REFRESH_INTERVAL=0

#----------------------------------------------------------------------------
# Multi-Instance Configuration
#----------------------------------------------------------------------------

# Instance identifier (required for multi-instance)
INSTANCE_ID=

# Instance name (for monitoring/logging)
INSTANCE_NAME=openalgo-default

# Enable multi-instance mode (forces Redis backend)
MULTI_INSTANCE_MODE=false

# Session backend (redis required for multi-instance)
SESSION_TYPE=filesystem

# Session Redis URL (for multi-instance)
SESSION_REDIS_URL=

#----------------------------------------------------------------------------
# Cache-Specific TTL Configuration
#----------------------------------------------------------------------------

# Auth cache TTL (seconds)
AUTH_CACHE_TTL=43200  # 12 hours

# Symbol cache TTL (seconds, 0 = no expiry)
SYMBOL_CACHE_TTL=0

# Settings cache TTL (seconds)
SETTINGS_CACHE_TTL=3600  # 1 hour

# Broker cache TTL (seconds)
BROKER_CACHE_TTL=300  # 5 minutes

# Strategy cache TTL (seconds)
STRATEGY_CACHE_TTL=600  # 10 minutes

# API key cache TTL (seconds)
API_KEY_CACHE_TTL=36000  # 10 hours
```

### Auto-Configuration Logic

**File:** `database/cache_config.py`

```python
import os
import platform
from utils.logging import get_logger

logger = get_logger(__name__)

def configure_cache_environment():
    """
    Auto-configure cache backend based on environment

    Called on app startup before cache initialization
    """

    # Skip if explicitly configured
    if os.getenv('CACHE_BACKEND'):
        logger.info(f"Cache backend explicitly set: {os.getenv('CACHE_BACKEND')}")
        return

    # Skip if auto-configure disabled
    if os.getenv('CACHE_AUTO_CONFIGURE', 'true').lower() != 'true':
        logger.info("Cache auto-configuration disabled")
        return

    # Multi-instance mode forces Redis
    if os.getenv('MULTI_INSTANCE_MODE', 'false').lower() == 'true':
        if not is_redis_available():
            logger.error("MULTI_INSTANCE_MODE enabled but Redis not available!")
            raise RuntimeError("Multi-instance mode requires Redis")
        os.environ['CACHE_BACKEND'] = 'redis'
        os.environ['SESSION_TYPE'] = 'redis'
        logger.info("Multi-instance mode: Redis backend selected")
        return

    # Check Redis availability
    if is_redis_available():
        os.environ['CACHE_BACKEND'] = 'redis'
        logger.info("Redis detected: Redis backend selected")
        return

    # Windows: Use SQLite (zero-config persistence)
    if platform.system() == 'Windows':
        os.environ['CACHE_BACKEND'] = 'sqlite'
        logger.info("Windows detected: SQLite backend selected (persistent, zero-config)")
        return

    # Default: SQLite (works everywhere)
    os.environ['CACHE_BACKEND'] = 'sqlite'
    logger.info("Default: SQLite backend selected (persistent, zero-config)")

def is_redis_available() -> bool:
    """Check if Redis is available and responding"""
    try:
        import redis
        host = os.getenv('REDIS_HOST', 'localhost')
        port = int(os.getenv('REDIS_PORT', 6379))
        password = os.getenv('REDIS_PASSWORD')

        client = redis.Redis(
            host=host,
            port=port,
            password=password,
            socket_connect_timeout=2,
            decode_responses=False
        )
        client.ping()
        logger.info(f"Redis connection successful: {host}:{port}")
        return True
    except Exception as e:
        logger.debug(f"Redis not available: {e}")
        return False
```

### Configuration Validation

**File:** `database/cache_validator.py`

```python
def validate_cache_configuration():
    """
    Validate cache configuration on startup

    Raises ValueError if configuration is invalid
    """
    backend = os.getenv('CACHE_BACKEND', 'sqlite')

    # Validate backend type
    valid_backends = ['memory', 'sqlite', 'redis', 'valkey']
    if backend not in valid_backends:
        raise ValueError(f"Invalid CACHE_BACKEND: {backend}. Must be one of {valid_backends}")

    # Multi-instance validation
    if os.getenv('MULTI_INSTANCE_MODE', 'false').lower() == 'true':
        if backend not in ('redis', 'valkey'):
            raise ValueError("MULTI_INSTANCE_MODE requires Redis or Valkey backend")

        if not os.getenv('INSTANCE_ID'):
            raise ValueError("INSTANCE_ID required for multi-instance mode")

        if not os.getenv('SESSION_REDIS_URL') and not os.getenv('REDIS_HOST'):
            raise ValueError("Redis configuration required for multi-instance mode")

    # Redis-specific validation
    if backend in ('redis', 'valkey'):
        if not is_redis_available():
            logger.warning(f"{backend} backend selected but not available, falling back to SQLite")
            os.environ['CACHE_BACKEND'] = 'sqlite'

    # Encryption validation
    if os.getenv('CACHE_ENCRYPTION_ENABLED', 'true').lower() == 'true':
        key_file = 'db/.cache_key'
        if not os.path.exists(key_file):
            logger.info("Generating cache encryption key...")
            # Key will be auto-generated by SecureCacheManager

    logger.info(f"Cache configuration validated: backend={os.getenv('CACHE_BACKEND')}")
```

---

## Migration Path

### Phase 1: Add Abstraction Layer (Week 1)

**Goal:** Create pluggable architecture without changing behavior

**Tasks:**
1. Create `database/cache_backend.py` (interface)
2. Create `database/backends/memory_backend.py` (wraps TTLCache)
3. Create `database/cache_factory.py`
4. Create `database/cache_manager.py`
5. Add unit tests for backends
6. Document API

**Validation:** Existing code continues to work unchanged

### Phase 2: Implement Alternative Backends (Week 2)

**Goal:** Add SQLite and Redis backends

**Tasks:**
1. Implement `database/backends/sqlite_backend.py`
2. Implement `database/backends/redis_backend.py`
3. Implement `database/backends/valkey_backend.py`
4. Add encryption wrappers
5. Add audit logging wrappers
6. Integration tests for all backends
7. Performance benchmarking

**Validation:** All backends pass integration tests

### Phase 3: Migrate Existing Caches (Week 3)

**Goal:** Update existing code to use new cache system

**Tasks:**
1. Update `database/auth_db.py`:
   ```python
   # OLD
   from cachetools import TTLCache
   auth_cache = TTLCache(maxsize=1024, ttl=86400)

   # NEW
   from database.cache_manager import get_cache
   auth_cache = get_cache('auth', maxsize=1024, ttl=86400, encrypted=True)
   ```

2. Update `database/settings_db.py`
3. Update `database/strategy_db.py`
4. Update `database/token_db_enhanced.py` (symbol cache)
5. Update all cache usage patterns

**Files to Update:**
- `database/auth_db.py`
- `database/settings_db.py`
- `database/strategy_db.py`
- `database/token_db_enhanced.py`
- `database/user_db.py`
- `database/telegram_db.py`

**Validation:** All tests pass, existing behavior preserved

### Phase 4: Add Configuration & Auto-Detection (Week 4)

**Goal:** Enable zero-config operation

**Tasks:**
1. Add `.env` configuration variables
2. Implement auto-detection logic
3. Add configuration validation
4. Update `app.py` to configure cache on startup
5. Add cache diagnostics endpoint (extend existing)
6. Documentation updates

**Validation:** Auto-configuration works on Windows/Linux

### Phase 5: Multi-Instance Support (Week 5)

**Goal:** Enable distributed deployments

**Tasks:**
1. Implement Redis-backed sessions
2. Add cache invalidation (Pub/Sub)
3. Add health check endpoint
4. Load balancer configuration templates
5. Docker Compose for multi-instance testing
6. Documentation for deployment

**Validation:** 3-instance deployment tested successfully

### Phase 6: Security Hardening (Week 6)

**Goal:** Production-ready security

**Tasks:**
1. Enable cache encryption by default
2. Implement access control
3. Add audit logging
4. Security testing (penetration testing)
5. Security documentation
6. Redis security hardening guide

**Validation:** Security audit passed

### Phase 7: Documentation & Release (Week 7)

**Goal:** Production release

**Tasks:**
1. User documentation (configuration guide)
2. Migration guide for existing deployments
3. Performance tuning guide
4. Troubleshooting guide
5. Release notes
6. Video tutorial

**Validation:** Beta testing with users

---

## Performance Impact

### Latency Comparison

**Symbol Lookup (142,338 symbols):**

| Backend | First Access | Cached Access | After Restart |
|---------|--------------|---------------|---------------|
| **Memory (current)** | 10-50 ms (DB) | 0.001 ms | 10-50 ms (DB) |
| **SQLite** | 0.5-2 ms | 0.5-2 ms | 0.5-2 ms |
| **Redis (local)** | 1-5 ms | 1-5 ms | 1-5 ms |
| **Redis (network)** | 5-10 ms | 5-10 ms | 5-10 ms |

**Analysis:**
- SQLite: ~500x slower than memory, but 10-20x faster than database
- Acceptable tradeoff for persistence
- Negligible impact on order placement latency

### Memory Usage Comparison

| Backend | RAM Usage | Disk Usage | Notes |
|---------|-----------|------------|-------|
| **Memory** | 67.87 MB | 0 MB | Current |
| **SQLite** | ~5 MB (indexes) | ~30 MB | Compressed on disk |
| **Redis** | External process | External | Separate server |

**Benefits:**
- SQLite frees 62 MB RAM (91% reduction)
- Redis offloads all cache memory

### Throughput Benchmarks

**Operations per second (single-threaded):**

| Backend | GET | SET | DELETE |
|---------|-----|-----|--------|
| **Memory** | 1,000,000 | 1,000,000 | 1,000,000 |
| **SQLite** | 50,000 | 10,000 | 10,000 |
| **Redis (local)** | 100,000 | 100,000 | 100,000 |

**Real-world impact:**
- Symbol lookups: ~100 per order (still <10ms with SQLite)
- Order frequency: ~10-100 orders/second
- Bottleneck: Broker API (200-500ms), not cache

**Conclusion:** Cache backend is NOT the bottleneck for trading operations.

---

## Testing Strategy

### Unit Tests

**Test Coverage:**
- [ ] Cache backend interface compliance
- [ ] Memory backend (TTLCache wrapper)
- [ ] SQLite backend (CRUD operations)
- [ ] Redis backend (CRUD operations)
- [ ] Encryption wrapper
- [ ] Audit wrapper
- [ ] Cache factory (auto-detection)
- [ ] Configuration validation

**File:** `tests/test_cache_backends.py`

### Integration Tests

**Scenarios:**
- [ ] Application startup with each backend
- [ ] Cache migration (memory → SQLite)
- [ ] Multi-instance with Redis
- [ ] Session sharing across instances
- [ ] Cache invalidation (Pub/Sub)
- [ ] Restart persistence
- [ ] Encryption round-trip

**File:** `tests/test_cache_integration.py`

### Performance Tests

**Benchmarks:**
- [ ] Latency: GET/SET operations
- [ ] Throughput: Operations per second
- [ ] Memory usage: Before/after
- [ ] Startup time: With/without preload
- [ ] Concurrent access: Multi-threaded

**File:** `tests/test_cache_performance.py`

### Security Tests

**Scenarios:**
- [ ] Cache poisoning attempt
- [ ] Unauthorized access
- [ ] Encryption verification
- [ ] Signature validation
- [ ] Audit log integrity
- [ ] Redis authentication

**File:** `tests/test_cache_security.py`

---

## Appendix

### A. Implementation Checklist

**Core Components:**
- [ ] `database/cache_backend.py` - Abstract interface
- [ ] `database/backends/memory_backend.py` - Memory implementation
- [ ] `database/backends/sqlite_backend.py` - SQLite implementation
- [ ] `database/backends/redis_backend.py` - Redis implementation
- [ ] `database/backends/valkey_backend.py` - Valkey implementation
- [ ] `database/cache_factory.py` - Factory pattern
- [ ] `database/cache_manager.py` - Manager with security
- [ ] `database/cache_config.py` - Auto-configuration
- [ ] `database/cache_validator.py` - Configuration validation

**Security:**
- [ ] Encryption wrapper
- [ ] Audit wrapper
- [ ] Access control
- [ ] Signature verification

**Migration:**
- [ ] Update `database/auth_db.py`
- [ ] Update `database/settings_db.py`
- [ ] Update `database/strategy_db.py`
- [ ] Update `database/token_db_enhanced.py`
- [ ] Update `database/user_db.py`

**Configuration:**
- [ ] `.env` template
- [ ] Auto-detection logic
- [ ] Validation logic
- [ ] Documentation

**Multi-Instance:**
- [ ] Redis session backend
- [ ] Health check endpoint
- [ ] Cache invalidation (Pub/Sub)
- [ ] Load balancer config

**Testing:**
- [ ] Unit tests (all backends)
- [ ] Integration tests
- [ ] Performance tests
- [ ] Security tests

**Documentation:**
- [ ] This design document
- [ ] User configuration guide
- [ ] Migration guide
- [ ] API documentation
- [ ] Deployment guide

### B. Dependencies

**New Requirements:**

```txt
# Cache backends
redis>=5.0.0              # Redis backend
hiredis>=2.2.0            # C parser for Redis (performance)

# Optional: SQLCipher for encrypted SQLite
sqlcipher3>=0.5.0         # Encrypted SQLite (optional)

# Existing (already installed)
cachetools>=5.3.3         # Memory backend
cryptography>=44.0.0      # Cache encryption
```

### C. File Structure

```
openalgo/
├── database/
│   ├── cache_backend.py          # Abstract interface
│   ├── cache_factory.py          # Factory
│   ├── cache_manager.py          # Manager (security layer)
│   ├── cache_config.py           # Auto-configuration
│   ├── cache_validator.py        # Validation
│   └── backends/
│       ├── __init__.py
│       ├── memory_backend.py     # Memory (TTLCache)
│       ├── sqlite_backend.py     # SQLite
│       ├── redis_backend.py      # Redis
│       └── valkey_backend.py     # Valkey
├── db/
│   ├── .cache_key                # Encryption key (600 perms)
│   ├── cache_auth.db             # SQLite cache (if enabled)
│   ├── cache_symbols.db
│   ├── cache_settings.db
│   └── cache_audit.log           # Audit log
├── docs/
│   └── CACHE_ARCHITECTURE_AND_PLUGGABLE_SYSTEM.md  # This document
├── tests/
│   ├── test_cache_backends.py
│   ├── test_cache_integration.py
│   ├── test_cache_performance.py
│   └── test_cache_security.py
└── .env                          # Configuration
```

### D. Monitoring & Observability

**Cache Metrics Endpoint:** `/diagnostics/cache-state` (existing, extend)

**Additional Metrics:**
```json
{
  "backend": "sqlite",
  "caches": {
    "auth": {
      "size": 125,
      "hit_rate": "98.5%",
      "avg_latency_ms": 1.2,
      "encrypted": true
    },
    "symbols": {
      "size": 142338,
      "hit_rate": "100%",
      "avg_latency_ms": 0.8,
      "memory_mb": 30.5
    }
  },
  "instance_id": "instance-1",
  "uptime": 86400
}
```

**Prometheus Metrics (Future):**
```python
# Cache hit rate
cache_hit_rate{cache="auth",backend="sqlite"} 0.985

# Cache latency
cache_latency_ms{cache="symbols",operation="get"} 0.8

# Cache size
cache_size_entries{cache="auth"} 125
```

### E. Troubleshooting Guide

**Problem:** Cache not persisting after restart

**Solution:**
```bash
# Check backend
echo $CACHE_BACKEND  # Should be 'sqlite' or 'redis'

# If memory:
CACHE_BACKEND=sqlite  # Change to SQLite

# Verify database files
ls -lh db/cache_*.db
```

**Problem:** Redis connection failed

**Solution:**
```bash
# Test Redis connection
redis-cli -h $REDIS_HOST -p $REDIS_PORT ping

# Check credentials
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD ping

# Fallback to SQLite
CACHE_BACKEND=sqlite
```

**Problem:** Slow cache performance

**Solution:**
```bash
# Check cache stats
curl http://localhost:5000/diagnostics/cache-state

# Enable SQLite WAL mode
SQLITE_WAL_MODE=true

# Or use Redis for better performance
CACHE_BACKEND=redis
```

---

## Conclusion

This design document outlines a comprehensive **pluggable cache architecture** for OpenAlgo that:

✅ **Solves current problems:**
- Persistence for multi-day strategies
- Multi-instance deployment support
- Memory optimization
- Flexibility

✅ **Provides zero-config experience:**
- Auto-detects best backend
- Works out-of-box on Windows (SQLite)
- No external dependencies required

✅ **Ensures security:**
- Encryption for sensitive caches
- Access control
- Audit logging
- Redis security hardening

✅ **Maintains performance:**
- Minimal latency overhead (<2ms)
- Not the bottleneck for trading
- Better memory efficiency

✅ **Supports scalability:**
- Multi-instance with Redis
- Shared cache
- Load balancing ready

**Next Steps:** Proceed with implementation following the migration path (7-week timeline).

---

**Document Status:** Design Proposal
**Review Required:** Yes
**Implementation:** Pending approval
**Target Release:** Q1 2026
