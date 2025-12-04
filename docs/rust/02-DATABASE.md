# OpenAlgo Desktop - Database Design

**Version:** 1.0.0
**Date:** December 2024

---

## 1. Overview

### 1.1 Database Strategy

| Aspect | Decision |
|--------|----------|
| **Engine** | SQLite with SQLCipher encryption |
| **Location** | `%APPDATA%/OpenAlgo/` (Windows), `~/Library/Application Support/OpenAlgo/` (macOS) |
| **Encryption** | AES-256-GCM via SQLCipher |
| **Key Storage** | OS Keychain (Windows Credential Manager, macOS Keychain) |

### 1.2 Database Files

```
openalgo_data/
├── main.db           # Primary database (encrypted)
├── master_contracts/ # Broker master contract caches
│   ├── angel.json
│   ├── zerodha.json
│   └── ...
└── logs/
    └── app.log
```

---

## 2. Schema Design

### 2.1 Entity Relationship Diagram

```
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│    User     │       │   Session   │       │   Broker    │
│─────────────│       │─────────────│       │ Connection  │
│ id (PK)     │───────│ id (PK)     │───────│─────────────│
│ username    │       │ user_id(FK) │       │ id (PK)     │
│ email       │       │ broker_id   │       │ user_id(FK) │
│ password    │       │ access_token│       │ broker_name │
│ totp_secret │       │ feed_token  │       │ client_id   │
│ created_at  │       │ expires_at  │       │ auth_token  │
└─────────────┘       │ is_active   │       │ feed_token  │
                      └─────────────┘       │ is_active   │
                                            └─────────────┘
       │                                           │
       │                                           │
       ▼                                           ▼
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│   ApiKey    │       │   Order     │       │  Position   │
│─────────────│       │─────────────│       │─────────────│
│ id (PK)     │       │ id (PK)     │       │ id (PK)     │
│ user_id(FK) │       │ user_id(FK) │       │ user_id(FK) │
│ key_hash    │       │ broker_id   │       │ broker_id   │
│ key_encrypt │       │ order_id    │       │ symbol      │
│ order_mode  │       │ symbol      │       │ exchange    │
│ created_at  │       │ exchange    │       │ product     │
└─────────────┘       │ action      │       │ quantity    │
                      │ quantity    │       │ avg_price   │
                      │ product     │       │ ltp         │
                      │ price_type  │       │ pnl         │
                      │ price       │       │ updated_at  │
                      │ status      │       └─────────────┘
                      │ broker_oid  │
                      │ created_at  │
                      │ updated_at  │
                      └─────────────┘

┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│  Strategy   │       │  Settings   │       │  Telegram   │
│─────────────│       │─────────────│       │─────────────│
│ id (PK)     │       │ key (PK)    │       │ id (PK)     │
│ user_id(FK) │       │ value       │       │ user_id(FK) │
│ name        │       │ updated_at  │       │ chat_id     │
│ webhook_url │       └─────────────┘       │ bot_token   │
│ symbols     │                             │ is_active   │
│ is_active   │                             └─────────────┘
│ created_at  │
└─────────────┘
```

---

## 3. Table Definitions

### 3.1 Core Tables

#### `users` - User Account

```sql
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,           -- Argon2id hash
    totp_secret     TEXT,                    -- TOTP 2FA secret (encrypted)
    is_admin        INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
```

#### `api_keys` - API Key Storage

```sql
CREATE TABLE api_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash        TEXT NOT NULL,           -- Argon2id hash for verification
    key_encrypted   TEXT NOT NULL,           -- AES-GCM encrypted for retrieval
    order_mode      TEXT DEFAULT 'auto',     -- 'auto' or 'semi_auto'
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id)
);

CREATE INDEX idx_api_keys_user_id ON api_keys(user_id);
```

#### `broker_connections` - Broker Authentication

```sql
CREATE TABLE broker_connections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    broker_name     TEXT NOT NULL,           -- 'angel', 'zerodha', etc.
    client_id       TEXT,                    -- Broker client ID
    auth_token      TEXT,                    -- Encrypted access token
    refresh_token   TEXT,                    -- Encrypted refresh token
    feed_token      TEXT,                    -- Encrypted feed token (for WS)
    user_broker_id  TEXT,                    -- Broker-specific user ID
    is_revoked      INTEGER DEFAULT 0,
    expires_at      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, broker_name)
);

CREATE INDEX idx_broker_conn_user ON broker_connections(user_id);
CREATE INDEX idx_broker_conn_broker ON broker_connections(broker_name);
CREATE INDEX idx_broker_conn_revoked ON broker_connections(is_revoked);
```

---

### 3.2 Trading Tables

#### `orders` - Order History

```sql
CREATE TABLE orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    broker_name     TEXT NOT NULL,
    broker_order_id TEXT NOT NULL,           -- Order ID from broker
    exchange        TEXT NOT NULL,           -- NSE, NFO, BSE, etc.
    symbol          TEXT NOT NULL,
    token           TEXT,                    -- Broker symbol token
    action          TEXT NOT NULL,           -- BUY, SELL
    quantity        INTEGER NOT NULL,
    filled_quantity INTEGER DEFAULT 0,
    pending_quantity INTEGER,
    product         TEXT NOT NULL,           -- CNC, MIS, NRML
    price_type      TEXT NOT NULL,           -- MARKET, LIMIT, SL, SL-M
    price           REAL DEFAULT 0,
    trigger_price   REAL DEFAULT 0,
    average_price   REAL DEFAULT 0,
    status          TEXT NOT NULL,           -- PENDING, COMPLETE, CANCELLED, REJECTED
    status_message  TEXT,
    strategy        TEXT,                    -- Strategy name if from webhook
    order_source    TEXT DEFAULT 'manual',   -- manual, api, strategy
    placed_at       TEXT,
    updated_at      TEXT DEFAULT (datetime('now')),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_orders_user ON orders(user_id);
CREATE INDEX idx_orders_broker_oid ON orders(broker_order_id);
CREATE INDEX idx_orders_symbol ON orders(symbol, exchange);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_strategy ON orders(strategy);
CREATE INDEX idx_orders_created ON orders(created_at DESC);
```

#### `trades` - Executed Trades

```sql
CREATE TABLE trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    order_id        INTEGER REFERENCES orders(id),
    broker_name     TEXT NOT NULL,
    broker_trade_id TEXT,
    exchange        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    action          TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    price           REAL NOT NULL,
    product         TEXT NOT NULL,
    trade_time      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_trades_user ON trades(user_id);
CREATE INDEX idx_trades_order ON trades(order_id);
CREATE INDEX idx_trades_symbol ON trades(symbol, exchange);
CREATE INDEX idx_trades_time ON trades(trade_time DESC);
```

#### `positions` - Current Positions

```sql
CREATE TABLE positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    broker_name     TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    token           TEXT,
    product         TEXT NOT NULL,
    quantity        INTEGER NOT NULL,        -- Net quantity (+ve buy, -ve sell)
    average_price   REAL NOT NULL,
    ltp             REAL DEFAULT 0,
    pnl             REAL DEFAULT 0,
    pnl_percent     REAL DEFAULT 0,
    day_buy_qty     INTEGER DEFAULT 0,
    day_sell_qty    INTEGER DEFAULT 0,
    day_buy_avg     REAL DEFAULT 0,
    day_sell_avg    REAL DEFAULT 0,
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, broker_name, exchange, symbol, product)
);

CREATE INDEX idx_positions_user ON positions(user_id);
CREATE INDEX idx_positions_symbol ON positions(symbol, exchange);
```

#### `holdings` - Demat Holdings

```sql
CREATE TABLE holdings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    broker_name     TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    token           TEXT,
    isin            TEXT,
    quantity        INTEGER NOT NULL,
    t1_quantity     INTEGER DEFAULT 0,       -- T+1 unsettled
    average_price   REAL NOT NULL,
    ltp             REAL DEFAULT 0,
    current_value   REAL DEFAULT 0,
    pnl             REAL DEFAULT 0,
    pnl_percent     REAL DEFAULT 0,
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, broker_name, symbol)
);

CREATE INDEX idx_holdings_user ON holdings(user_id);
```

---

### 3.3 Strategy Tables

#### `strategies` - Webhook Strategies

```sql
CREATE TABLE strategies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    name            TEXT NOT NULL,
    description     TEXT,
    webhook_id      TEXT NOT NULL UNIQUE,    -- Unique webhook identifier
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, name)
);

CREATE INDEX idx_strategies_user ON strategies(user_id);
CREATE INDEX idx_strategies_webhook ON strategies(webhook_id);
```

#### `strategy_symbols` - Strategy Symbol Mappings

```sql
CREATE TABLE strategy_symbols (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id     INTEGER NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    symbol          TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    product         TEXT DEFAULT 'MIS',
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(strategy_id, symbol, exchange)
);

CREATE INDEX idx_strategy_symbols_strategy ON strategy_symbols(strategy_id);
```

---

### 3.4 Settings & Configuration

#### `settings` - Application Settings

```sql
CREATE TABLE settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    description     TEXT,
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Default settings
INSERT INTO settings (key, value, description) VALUES
    ('theme', 'dark', 'UI theme: light, dark, system'),
    ('session_expiry_time', '03:00', 'Daily session expiry time IST'),
    ('smart_order_delay', '0.5', 'Delay between multi-leg orders'),
    ('default_product', 'MIS', 'Default product type'),
    ('default_exchange', 'NSE', 'Default exchange'),
    ('show_notifications', 'true', 'Show desktop notifications'),
    ('sound_alerts', 'true', 'Play sound on order execution');
```

#### `telegram_config` - Telegram Bot Configuration

```sql
CREATE TABLE telegram_config (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    chat_id         TEXT,
    bot_token       TEXT,                    -- Encrypted
    is_active       INTEGER DEFAULT 0,
    send_order_updates INTEGER DEFAULT 1,
    send_position_updates INTEGER DEFAULT 1,
    send_daily_summary INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id)
);
```

---

### 3.5 Action Center Tables

#### `pending_orders` - Orders Awaiting Approval (Semi-Auto Mode)

```sql
CREATE TABLE pending_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    strategy        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    action          TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    product         TEXT NOT NULL,
    price_type      TEXT NOT NULL,
    price           REAL DEFAULT 0,
    trigger_price   REAL DEFAULT 0,
    position_size   INTEGER,                 -- For smart orders
    status          TEXT DEFAULT 'PENDING',  -- PENDING, APPROVED, REJECTED, EXPIRED
    approved_at     TEXT,
    rejected_at     TEXT,
    expires_at      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_pending_user ON pending_orders(user_id);
CREATE INDEX idx_pending_status ON pending_orders(status);
CREATE INDEX idx_pending_created ON pending_orders(created_at DESC);
```

---

### 3.6 Monitoring & Logging Tables

#### `order_logs` - API Request Logs

```sql
CREATE TABLE order_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id),
    endpoint        TEXT NOT NULL,
    method          TEXT NOT NULL,
    request_data    TEXT,                    -- JSON
    response_data   TEXT,                    -- JSON
    status_code     INTEGER,
    latency_ms      INTEGER,
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_order_logs_user ON order_logs(user_id);
CREATE INDEX idx_order_logs_endpoint ON order_logs(endpoint);
CREATE INDEX idx_order_logs_created ON order_logs(created_at DESC);

-- Auto-cleanup: keep only last 30 days
CREATE TRIGGER cleanup_order_logs
AFTER INSERT ON order_logs
BEGIN
    DELETE FROM order_logs
    WHERE created_at < datetime('now', '-30 days');
END;
```

#### `latency_metrics` - Order Execution Latency

```sql
CREATE TABLE latency_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id),
    broker_name     TEXT NOT NULL,
    order_id        TEXT,
    operation       TEXT NOT NULL,           -- place, modify, cancel
    latency_ms      INTEGER NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_latency_broker ON latency_metrics(broker_name);
CREATE INDEX idx_latency_created ON latency_metrics(created_at DESC);
```

---

## 4. Rust Models

### 4.1 Model Definitions

```rust
// models/user.rs
use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub id: i64,
    pub username: String,
    pub email: String,
    #[serde(skip_serializing)]
    pub password_hash: String,
    pub totp_secret: Option<String>,
    pub is_admin: bool,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CreateUser {
    pub username: String,
    pub email: String,
    pub password: String,
}

// models/order.rs
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    pub id: i64,
    pub user_id: i64,
    pub broker_name: String,
    pub broker_order_id: String,
    pub exchange: String,
    pub symbol: String,
    pub token: Option<String>,
    pub action: OrderAction,
    pub quantity: i32,
    pub filled_quantity: i32,
    pub pending_quantity: i32,
    pub product: ProductType,
    pub price_type: PriceType,
    pub price: f64,
    pub trigger_price: f64,
    pub average_price: f64,
    pub status: OrderStatus,
    pub status_message: Option<String>,
    pub strategy: Option<String>,
    pub order_source: OrderSource,
    pub placed_at: Option<DateTime<Utc>>,
    pub updated_at: DateTime<Utc>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "UPPERCASE")]
pub enum OrderAction {
    Buy,
    Sell,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "UPPERCASE")]
pub enum ProductType {
    Mis,    // Intraday
    Cnc,    // Delivery
    Nrml,   // Normal (F&O)
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "UPPERCASE")]
pub enum PriceType {
    Market,
    Limit,
    Sl,      // Stop Loss Limit
    #[serde(rename = "SL-M")]
    SlM,     // Stop Loss Market
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "UPPERCASE")]
pub enum OrderStatus {
    Pending,
    Open,
    Complete,
    Cancelled,
    Rejected,
    #[serde(rename = "TRIGGER PENDING")]
    TriggerPending,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum OrderSource {
    Manual,
    Api,
    Strategy,
    Telegram,
}

// models/position.rs
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Position {
    pub id: i64,
    pub user_id: i64,
    pub broker_name: String,
    pub exchange: String,
    pub symbol: String,
    pub token: Option<String>,
    pub product: ProductType,
    pub quantity: i32,
    pub average_price: f64,
    pub ltp: f64,
    pub pnl: f64,
    pub pnl_percent: f64,
    pub day_buy_qty: i32,
    pub day_sell_qty: i32,
    pub day_buy_avg: f64,
    pub day_sell_avg: f64,
    pub updated_at: DateTime<Utc>,
}

// models/quote.rs
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Quote {
    pub symbol: String,
    pub exchange: String,
    pub token: String,
    pub ltp: f64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: i64,
    pub bid: f64,
    pub ask: f64,
    pub bid_qty: i32,
    pub ask_qty: i32,
    pub oi: Option<i64>,
    pub timestamp: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Depth {
    pub symbol: String,
    pub exchange: String,
    pub bids: Vec<DepthLevel>,
    pub asks: Vec<DepthLevel>,
    pub timestamp: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DepthLevel {
    pub price: f64,
    pub quantity: i32,
    pub orders: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Candle {
    pub timestamp: DateTime<Utc>,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: i64,
    pub oi: Option<i64>,
}
```

### 4.2 Database Operations

```rust
// database/mod.rs
use rusqlite::{Connection, params};
use parking_lot::Mutex;
use std::sync::Arc;

pub struct Database {
    conn: Arc<Mutex<Connection>>,
}

impl Database {
    pub fn new(path: &str, encryption_key: &str) -> Result<Self> {
        let conn = Connection::open(path)?;

        // Enable SQLCipher encryption
        conn.execute_batch(&format!(
            "PRAGMA key = '{}';
             PRAGMA cipher_page_size = 4096;
             PRAGMA kdf_iter = 256000;
             PRAGMA cipher_hmac_algorithm = HMAC_SHA512;
             PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;",
            encryption_key
        ))?;

        // Enable WAL mode for better concurrency
        conn.execute_batch("PRAGMA journal_mode = WAL;")?;

        Ok(Self {
            conn: Arc::new(Mutex::new(conn)),
        })
    }

    pub fn run_migrations(&self) -> Result<()> {
        let conn = self.conn.lock();
        conn.execute_batch(include_str!("migrations/001_initial.sql"))?;
        Ok(())
    }
}

// database/orders.rs
impl Database {
    pub fn insert_order(&self, order: &Order) -> Result<i64> {
        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO orders (
                user_id, broker_name, broker_order_id, exchange, symbol,
                token, action, quantity, filled_quantity, pending_quantity,
                product, price_type, price, trigger_price, average_price,
                status, status_message, strategy, order_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params![
                order.user_id,
                order.broker_name,
                order.broker_order_id,
                order.exchange,
                order.symbol,
                order.token,
                order.action.to_string(),
                order.quantity,
                order.filled_quantity,
                order.pending_quantity,
                order.product.to_string(),
                order.price_type.to_string(),
                order.price,
                order.trigger_price,
                order.average_price,
                order.status.to_string(),
                order.status_message,
                order.strategy,
                order.order_source.to_string(),
            ],
        )?;
        Ok(conn.last_insert_rowid())
    }

    pub fn get_orders(&self, user_id: i64, limit: i32) -> Result<Vec<Order>> {
        let conn = self.conn.lock();
        let mut stmt = conn.prepare(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
        )?;

        let orders = stmt.query_map(params![user_id, limit], |row| {
            Ok(Order {
                id: row.get(0)?,
                user_id: row.get(1)?,
                broker_name: row.get(2)?,
                broker_order_id: row.get(3)?,
                // ... map all fields
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;

        Ok(orders)
    }

    pub fn update_order_status(
        &self,
        broker_order_id: &str,
        status: OrderStatus,
        filled_qty: i32,
        avg_price: f64,
    ) -> Result<()> {
        let conn = self.conn.lock();
        conn.execute(
            "UPDATE orders SET
                status = ?,
                filled_quantity = ?,
                average_price = ?,
                updated_at = datetime('now')
             WHERE broker_order_id = ?",
            params![status.to_string(), filled_qty, avg_price, broker_order_id],
        )?;
        Ok(())
    }
}

// database/positions.rs
impl Database {
    pub fn upsert_position(&self, position: &Position) -> Result<()> {
        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO positions (
                user_id, broker_name, exchange, symbol, token, product,
                quantity, average_price, ltp, pnl, pnl_percent,
                day_buy_qty, day_sell_qty, day_buy_avg, day_sell_avg
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, broker_name, exchange, symbol, product)
            DO UPDATE SET
                quantity = excluded.quantity,
                average_price = excluded.average_price,
                ltp = excluded.ltp,
                pnl = excluded.pnl,
                pnl_percent = excluded.pnl_percent,
                day_buy_qty = excluded.day_buy_qty,
                day_sell_qty = excluded.day_sell_qty,
                day_buy_avg = excluded.day_buy_avg,
                day_sell_avg = excluded.day_sell_avg,
                updated_at = datetime('now')",
            params![
                position.user_id,
                position.broker_name,
                position.exchange,
                position.symbol,
                position.token,
                position.product.to_string(),
                position.quantity,
                position.average_price,
                position.ltp,
                position.pnl,
                position.pnl_percent,
                position.day_buy_qty,
                position.day_sell_qty,
                position.day_buy_avg,
                position.day_sell_avg,
            ],
        )?;
        Ok(())
    }

    pub fn get_positions(&self, user_id: i64) -> Result<Vec<Position>> {
        let conn = self.conn.lock();
        let mut stmt = conn.prepare(
            "SELECT * FROM positions WHERE user_id = ? AND quantity != 0"
        )?;

        let positions = stmt.query_map(params![user_id], |row| {
            // Map row to Position
            Ok(Position { /* ... */ })
        })?
        .collect::<Result<Vec<_>, _>>()?;

        Ok(positions)
    }
}
```

---

## 5. Migration Strategy

### 5.1 Initial Migration (`001_initial.sql`)

```sql
-- Migration: 001_initial
-- Created: 2024-12-01

-- Enable foreign keys
PRAGMA foreign_keys = ON;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    totp_secret TEXT,
    is_admin INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ... (all table definitions from above)

-- Record migration
INSERT INTO schema_migrations (version, applied_at)
VALUES ('001_initial', datetime('now'));
```

### 5.2 Migration Tracking

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

### 5.3 Migration Runner

```rust
// database/migrations.rs
pub struct Migrator {
    db: Arc<Database>,
    migrations_dir: PathBuf,
}

impl Migrator {
    pub fn run_pending(&self) -> Result<Vec<String>> {
        let applied = self.get_applied_migrations()?;
        let available = self.get_available_migrations()?;

        let pending: Vec<_> = available
            .into_iter()
            .filter(|m| !applied.contains(&m.version))
            .collect();

        for migration in &pending {
            self.apply_migration(migration)?;
        }

        Ok(pending.iter().map(|m| m.version.clone()).collect())
    }

    fn apply_migration(&self, migration: &Migration) -> Result<()> {
        let conn = self.db.conn.lock();

        // Run migration in transaction
        conn.execute_batch("BEGIN TRANSACTION;")?;

        match conn.execute_batch(&migration.sql) {
            Ok(_) => {
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
                    params![migration.version],
                )?;
                conn.execute_batch("COMMIT;")?;
                Ok(())
            }
            Err(e) => {
                conn.execute_batch("ROLLBACK;")?;
                Err(e.into())
            }
        }
    }
}
```

---

## 6. Data Encryption

### 6.1 Field-Level Encryption

```rust
// crypto/encryption.rs
use ring::aead::{Aad, LessSafeKey, Nonce, UnboundKey, AES_256_GCM};
use ring::rand::{SecureRandom, SystemRandom};

pub struct FieldEncryptor {
    key: LessSafeKey,
    rng: SystemRandom,
}

impl FieldEncryptor {
    pub fn new(key_bytes: &[u8; 32]) -> Result<Self> {
        let unbound_key = UnboundKey::new(&AES_256_GCM, key_bytes)?;
        Ok(Self {
            key: LessSafeKey::new(unbound_key),
            rng: SystemRandom::new(),
        })
    }

    pub fn encrypt(&self, plaintext: &str) -> Result<String> {
        let mut nonce_bytes = [0u8; 12];
        self.rng.fill(&mut nonce_bytes)?;

        let nonce = Nonce::assume_unique_for_key(nonce_bytes);
        let mut in_out = plaintext.as_bytes().to_vec();

        self.key.seal_in_place_append_tag(nonce, Aad::empty(), &mut in_out)?;

        // Prepend nonce to ciphertext
        let mut result = nonce_bytes.to_vec();
        result.extend(in_out);

        Ok(base64::encode(&result))
    }

    pub fn decrypt(&self, ciphertext: &str) -> Result<String> {
        let data = base64::decode(ciphertext)?;

        if data.len() < 12 {
            return Err(CryptoError::InvalidCiphertext);
        }

        let (nonce_bytes, encrypted) = data.split_at(12);
        let nonce = Nonce::assume_unique_for_key(nonce_bytes.try_into()?);

        let mut in_out = encrypted.to_vec();
        let plaintext = self.key.open_in_place(nonce, Aad::empty(), &mut in_out)?;

        Ok(String::from_utf8(plaintext.to_vec())?)
    }
}
```

### 6.2 Sensitive Field Handling

Fields requiring encryption:
- `broker_connections.auth_token`
- `broker_connections.refresh_token`
- `broker_connections.feed_token`
- `api_keys.key_encrypted`
- `telegram_config.bot_token`
- `users.totp_secret`

---

## Document References

- [00-PRODUCT-DESIGN.md](./00-PRODUCT-DESIGN.md) - Product overview
- [01-ARCHITECTURE.md](./01-ARCHITECTURE.md) - System architecture
- [03-TAURI-COMMANDS.md](./03-TAURI-COMMANDS.md) - Command reference
- [04-FRONTEND.md](./04-FRONTEND.md) - Frontend design
- [05-BROKER-INTEGRATION.md](./05-BROKER-INTEGRATION.md) - Broker patterns
- [06-ROADMAP.md](./06-ROADMAP.md) - Implementation plan

---

*Last updated: December 2024*
