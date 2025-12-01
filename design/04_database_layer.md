# Database Layer Architecture

OpenAlgo implements a sophisticated multi-database architecture with intelligent caching, supporting both SQLite (development) and PostgreSQL (production) through SQLAlchemy ORM.

## Multi-Database Architecture

OpenAlgo uses **5 separate databases** to isolate different concerns:

```
databases/
├── openalgo.db          # Main application database
├── openalgo_sandbox.db  # Paper trading sandbox
├── latency.db           # Order execution metrics
├── logs.db              # Application logging
└── telegram.db          # Telegram bot state
```

### Database Configuration

```python
# database/db_init.py
DATABASE_URLS = {
    'main': os.getenv('DATABASE_URL', 'sqlite:///databases/openalgo.db'),
    'sandbox': os.getenv('SANDBOX_DATABASE_URL', 'sqlite:///databases/openalgo_sandbox.db'),
    'latency': os.getenv('LATENCY_DATABASE_URL', 'sqlite:///databases/latency.db'),
    'logs': os.getenv('LOGS_DATABASE_URL', 'sqlite:///databases/logs.db'),
    'telegram': os.getenv('TELEGRAM_DATABASE_URL', 'sqlite:///databases/telegram.db')
}
```

### Connection Pooling

| Database Type | Pool Size | Max Overflow | Timeout |
|---------------|-----------|--------------|---------|
| PostgreSQL    | 50        | 100          | 30s     |
| SQLite        | NullPool  | N/A          | N/A     |

```python
def get_engine_options(url):
    if 'postgresql' in url:
        return {
            'pool_size': 50,
            'max_overflow': 100,
            'pool_timeout': 30,
            'pool_recycle': 1800,
            'pool_pre_ping': True
        }
    return {'poolclass': NullPool}  # SQLite
```

## Database Models

### Main Database Tables (25+)

#### User Management

**User Table** (`user_db.py`)
```python
class User(Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)  # Argon2 hash
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
```

**API Key Table** (`apikey_db.py`)
```python
class ApiKey(Base):
    __tablename__ = 'api_keys'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    api_key = Column(String(64), unique=True, nullable=False)
    name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime)
    is_active = Column(Boolean, default=True)
```

#### Broker Authentication

**Auth Token Table** (`auth_db.py`)
```python
class AuthToken(Base):
    __tablename__ = 'auth_tokens'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    broker = Column(String(50), nullable=False)
    access_token = Column(Text)           # Fernet encrypted
    refresh_token = Column(Text)          # Fernet encrypted
    feed_token = Column(Text)             # Fernet encrypted (Angel/Dhan)
    token_expiry = Column(DateTime)
    auth_data = Column(JSON)              # Additional broker-specific data
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
```

#### Trading Operations

**Order Book Table** (`orderbook_db.py`)
```python
class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    order_id = Column(String(50), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    broker = Column(String(50), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(20), nullable=False)
    action = Column(String(10))           # BUY/SELL
    quantity = Column(Integer)
    price = Column(Float)
    trigger_price = Column(Float)
    order_type = Column(String(20))       # MARKET/LIMIT/SL/SL-M
    product = Column(String(20))          # CNC/MIS/NRML
    status = Column(String(20))           # OPEN/COMPLETE/CANCELLED/REJECTED
    fill_price = Column(Float)
    fill_quantity = Column(Integer)
    placed_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
```

**Trade Book Table** (`tradebook_db.py`)
```python
class Trade(Base):
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True)
    trade_id = Column(String(50), unique=True)
    order_id = Column(String(50), ForeignKey('orders.order_id'))
    user_id = Column(Integer, ForeignKey('user.id'))
    symbol = Column(String(50))
    exchange = Column(String(20))
    action = Column(String(10))
    quantity = Column(Integer)
    price = Column(Float)
    traded_at = Column(DateTime)
```

**Position Book Table** (`positionbook_db.py`)
```python
class Position(Base):
    __tablename__ = 'positions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'))
    broker = Column(String(50))
    symbol = Column(String(50))
    exchange = Column(String(20))
    product = Column(String(20))
    quantity = Column(Integer)
    average_price = Column(Float)
    last_price = Column(Float)
    pnl = Column(Float)
    day_quantity = Column(Integer)
    overnight_quantity = Column(Integer)
```

**Holdings Table** (`holdings_db.py`)
```python
class Holding(Base):
    __tablename__ = 'holdings'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'))
    broker = Column(String(50))
    symbol = Column(String(50))
    exchange = Column(String(20))
    isin = Column(String(20))
    quantity = Column(Integer)
    average_price = Column(Float)
    last_price = Column(Float)
    pnl = Column(Float)
    pnl_percent = Column(Float)
```

#### Strategy Management

**Strategy Table** (`strategy_db.py`)
```python
class Strategy(Base):
    __tablename__ = 'strategies'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'))
    name = Column(String(100), nullable=False)
    description = Column(Text)
    strategy_type = Column(String(50))    # webhook/python/chartink
    config = Column(JSON)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
```

#### Symbol Management

**Symbol Master Table** (`symbol_db.py`)
```python
class Symbol(Base):
    __tablename__ = 'symbols'
    id = Column(Integer, primary_key=True)
    broker = Column(String(50), nullable=False)
    symbol = Column(String(50), nullable=False)
    broker_symbol = Column(String(100))
    token = Column(String(50))
    exchange = Column(String(20))
    instrument_type = Column(String(20))
    lot_size = Column(Integer)
    tick_size = Column(Float)
    expiry = Column(Date)
    strike = Column(Float)
    option_type = Column(String(5))       # CE/PE
    last_updated = Column(DateTime)

    __table_args__ = (
        UniqueConstraint('broker', 'symbol', 'exchange', name='uix_symbol'),
    )
```

### Sandbox Database

Mirrors main database structure for paper trading:

```python
# database/sandbox_db.py
class SandboxOrder(Base):
    __tablename__ = 'sandbox_orders'
    # Same structure as Order, isolated for paper trading

class SandboxPosition(Base):
    __tablename__ = 'sandbox_positions'
    # Same structure as Position

class SandboxTrade(Base):
    __tablename__ = 'sandbox_trades'
    # Same structure as Trade
```

### Latency Database

**Latency Metrics Table** (`latency_db.py`)
```python
class LatencyMetric(Base):
    __tablename__ = 'latency_metrics'
    id = Column(Integer, primary_key=True)
    order_id = Column(String(50))
    broker = Column(String(50))
    operation = Column(String(50))        # place_order/modify_order/cancel_order
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    latency_ms = Column(Float)
    success = Column(Boolean)
    error_message = Column(Text)
```

### Logs Database

**Application Log Table** (`logs_db.py`)
```python
class ApplicationLog(Base):
    __tablename__ = 'application_logs'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    level = Column(String(20))            # DEBUG/INFO/WARNING/ERROR/CRITICAL
    logger = Column(String(100))
    message = Column(Text)
    module = Column(String(100))
    function = Column(String(100))
    line_number = Column(Integer)
    exception = Column(Text)
    extra_data = Column(JSON)
```

### Telegram Database

**Chat State Table** (`telegram_db.py`)
```python
class TelegramChat(Base):
    __tablename__ = 'telegram_chats'
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'))
    username = Column(String(100))
    is_authorized = Column(Boolean, default=False)
    notification_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class TelegramMessage(Base):
    __tablename__ = 'telegram_messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, ForeignKey('telegram_chats.chat_id'))
    message_type = Column(String(50))     # order/alert/error
    content = Column(Text)
    sent_at = Column(DateTime, default=datetime.utcnow)
    delivered = Column(Boolean, default=False)
```

## Caching Architecture

### TTLCache Implementation

OpenAlgo uses `cachetools.TTLCache` for high-performance in-memory caching:

```python
from cachetools import TTLCache

# API Key Cache - 10 hour TTL for valid keys
api_key_cache = TTLCache(maxsize=1000, ttl=36000)

# Invalid Key Cache - 5 minute TTL to prevent brute force
invalid_key_cache = TTLCache(maxsize=10000, ttl=300)

# Symbol Cache - Session-based expiry
symbol_cache = TTLCache(maxsize=50000, ttl=get_ttl_to_session_end())

# Token Cache - 24 hour TTL
token_cache = TTLCache(maxsize=500, ttl=86400)
```

### Session-Based Cache Expiry

Caches expire at 3:00 AM IST daily (market session boundary):

```python
def get_ttl_to_session_end():
    """Calculate seconds until 3:00 AM IST"""
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)

    # Next 3:00 AM IST
    next_session_end = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now.hour >= 3:
        next_session_end += timedelta(days=1)

    return (next_session_end - now).total_seconds()
```

### Cache Flow Diagram

```
API Request
    |
    v
+------------------+
| Check API Key    |
| Cache (10hr)     |
+--------+---------+
         |
    Cache Hit? ---Yes---> Return Cached Result
         |
         No
         |
         v
+------------------+
| Check Invalid    |
| Cache (5min)     |
+--------+---------+
         |
    In Invalid? ---Yes---> Return 401 Immediately
         |
         No
         |
         v
+------------------+
| Database Query   |
+--------+---------+
         |
         v
+------------------+
| Update Cache     |
| (Valid/Invalid)  |
+------------------+
```

## Database Operations

### CRUD Functions

Each database module provides standard CRUD operations:

```python
# database/user_db.py
def create_user(username, email, password_hash):
    """Create new user record"""

def get_user_by_username(username):
    """Retrieve user by username"""

def get_user_by_api_key(api_key):
    """Retrieve user associated with API key"""

def update_user(user_id, **kwargs):
    """Update user attributes"""

def delete_user(user_id):
    """Soft delete user (set is_active=False)"""
```

### Transaction Management

```python
from contextlib import contextmanager

@contextmanager
def get_db_session(database='main'):
    """Provide transactional scope around operations"""
    session = Session(get_engine(database))
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

# Usage
with get_db_session('main') as session:
    order = Order(symbol='RELIANCE', quantity=100)
    session.add(order)
    # Auto-commit on context exit
```

### Bulk Operations

```python
def bulk_insert_symbols(symbols_data, broker):
    """Efficiently insert many symbols"""
    with get_db_session() as session:
        session.bulk_insert_mappings(Symbol, symbols_data)

def bulk_update_positions(positions_data):
    """Update multiple positions atomically"""
    with get_db_session() as session:
        session.bulk_update_mappings(Position, positions_data)
```

## Database Initialization

### Startup Sequence

```python
# database/db_init.py
def init_databases():
    """Initialize all databases on application startup"""

    # 1. Create database directories
    os.makedirs('databases', exist_ok=True)

    # 2. Initialize engines for each database
    for db_name, url in DATABASE_URLS.items():
        engine = create_engine(url, **get_engine_options(url))
        engines[db_name] = engine

    # 3. Create all tables
    for db_name, engine in engines.items():
        Base.metadata.create_all(engine)

    # 4. Run migrations if needed
    run_pending_migrations()

    # 5. Initialize caches
    warm_symbol_cache()
    warm_api_key_cache()
```

### Migration Support

```python
def run_pending_migrations():
    """Apply any pending database migrations"""
    # Check current schema version
    current_version = get_schema_version()

    # Apply migrations sequentially
    for migration in get_pending_migrations(current_version):
        apply_migration(migration)
        update_schema_version(migration.version)
```

## Query Patterns

### Optimized Queries

```python
# Efficient symbol lookup with caching
def get_symbol_token(symbol, exchange, broker):
    cache_key = f"{broker}:{exchange}:{symbol}"

    if cache_key in symbol_cache:
        return symbol_cache[cache_key]

    with get_db_session() as session:
        result = session.query(Symbol.token).filter(
            Symbol.symbol == symbol,
            Symbol.exchange == exchange,
            Symbol.broker == broker
        ).scalar()

        symbol_cache[cache_key] = result
        return result

# Paginated order history
def get_order_history(user_id, page=1, per_page=50):
    with get_db_session() as session:
        return session.query(Order)\
            .filter(Order.user_id == user_id)\
            .order_by(Order.placed_at.desc())\
            .offset((page - 1) * per_page)\
            .limit(per_page)\
            .all()
```

### Aggregation Queries

```python
# Daily P&L calculation
def get_daily_pnl(user_id, date):
    with get_db_session() as session:
        return session.query(
            func.sum(Trade.quantity * Trade.price).label('turnover'),
            func.sum(case(
                (Trade.action == 'SELL', Trade.quantity * Trade.price),
                else_=-Trade.quantity * Trade.price
            )).label('realized_pnl')
        ).filter(
            Trade.user_id == user_id,
            func.date(Trade.traded_at) == date
        ).first()
```

## Performance Considerations

### Index Strategy

```python
# Composite indexes for common queries
__table_args__ = (
    Index('ix_orders_user_status', 'user_id', 'status'),
    Index('ix_orders_symbol_date', 'symbol', 'placed_at'),
    Index('ix_trades_user_date', 'user_id', 'traded_at'),
)
```

### Connection Health

```python
# PostgreSQL connection health check
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,      # Verify connections before use
    pool_recycle=1800,       # Recycle connections every 30 min
)
```

### Read Replicas (Production)

```python
# Optional read replica configuration
WRITE_DATABASE_URL = os.getenv('DATABASE_URL')
READ_DATABASE_URL = os.getenv('READ_DATABASE_URL', WRITE_DATABASE_URL)

def get_read_session():
    """Get session for read-only operations"""
    return Session(read_engine)

def get_write_session():
    """Get session for write operations"""
    return Session(write_engine)
```

## Environment Configuration

```bash
# SQLite (Development)
DATABASE_URL=sqlite:///databases/openalgo.db

# PostgreSQL (Production)
DATABASE_URL=postgresql://user:pass@localhost:5432/openalgo
SANDBOX_DATABASE_URL=postgresql://user:pass@localhost:5432/openalgo_sandbox
LATENCY_DATABASE_URL=postgresql://user:pass@localhost:5432/openalgo_latency
LOGS_DATABASE_URL=postgresql://user:pass@localhost:5432/openalgo_logs
TELEGRAM_DATABASE_URL=postgresql://user:pass@localhost:5432/openalgo_telegram

# Connection Pool Settings
DB_POOL_SIZE=50
DB_MAX_OVERFLOW=100
DB_POOL_TIMEOUT=30
```

## Related Documentation

- [Authentication Platform](./06_authentication_platform.md) - Token encryption and API key management
- [Broker Integration](./03_broker_integration.md) - Symbol mapping and token storage
- [Logging System](./10_logging_system.md) - Database logging configuration
- [Sandbox Architecture](./14_sandbox_architecture.md) - Paper trading database isolation
