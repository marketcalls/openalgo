# OpenAlgo Desktop - Rust/Tauri Product Design

**Version:** 1.0.0
**Date:** December 2024
**Status:** Draft

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Product Vision](#2-product-vision)
3. [Current State Analysis](#3-current-state-analysis)
4. [Target Architecture](#4-target-architecture)
5. [Technology Stack](#5-technology-stack)
6. [Feature Mapping](#6-feature-mapping)
7. [Security Model](#7-security-model)
8. [Performance Goals](#8-performance-goals)
9. [Migration Strategy](#9-migration-strategy)
10. [Risk Assessment](#10-risk-assessment)

---

## 1. Executive Summary

### 1.1 Project Overview

OpenAlgo Desktop is a ground-up rewrite of the OpenAlgo trading platform from Python/Flask to Rust/Tauri. The goal is to create a high-performance, secure, native desktop application that provides algorithmic trading capabilities across 24+ Indian stock brokers.

### 1.2 Key Objectives

| Objective | Description |
|-----------|-------------|
| **Performance** | Sub-millisecond order routing, 10x faster startup |
| **Security** | Memory-safe code, encrypted local storage, secure IPC |
| **User Experience** | Native desktop feel, modern UI, offline capability |
| **Reliability** | Zero crashes, graceful error handling, auto-recovery |
| **Portability** | Windows, macOS, Linux from single codebase |

### 1.3 Success Metrics

- **Startup Time**: < 2 seconds (cold start)
- **Memory Usage**: < 150MB idle, < 500MB active trading
- **Order Latency**: < 50ms from UI click to broker API call
- **Binary Size**: < 50MB installer
- **Crash Rate**: < 0.1% sessions

---

## 2. Product Vision

### 2.1 Core Value Proposition

> "Professional-grade algorithmic trading platform that runs natively on your desktop with the performance of institutional software."

### 2.2 Target Users

1. **Retail Algorithmic Traders**: Individual traders running automated strategies
2. **Options Traders**: Heavy users of options chain, Greeks, multi-leg strategies
3. **Day Traders**: Need fast execution, real-time data, quick position management
4. **Strategy Developers**: Python/Pine Script strategy creators needing backtesting

### 2.3 Key Differentiators

| Feature | Current (Python) | Target (Rust) |
|---------|-----------------|---------------|
| Deployment | Web server (localhost) | Native app |
| Startup | 5-10 seconds | < 2 seconds |
| Memory | 300-500MB | < 150MB idle |
| Updates | Manual git pull | Auto-update |
| Security | Process isolation | Memory safety + encryption |

---

## 3. Current State Analysis

### 3.1 Existing Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Flask Web Server                         │
├─────────────────────────────────────────────────────────────┤
│  Blueprints (27)  │  RestX APIs (40+)  │  SocketIO Events   │
├─────────────────────────────────────────────────────────────┤
│                    Services Layer (40+)                      │
├─────────────────────────────────────────────────────────────┤
│  SQLAlchemy ORM   │  Broker Plugins (24+)  │  WebSocket Proxy│
├─────────────────────────────────────────────────────────────┤
│         SQLite/PostgreSQL         │         ZeroMQ          │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Component Inventory

| Category | Count | Complexity |
|----------|-------|------------|
| Database Models | 29 | Medium |
| REST Endpoints | 40+ | High |
| Broker Integrations | 24 | Very High |
| Services | 40+ | High |
| HTML Templates | 74 | Medium |
| JavaScript Files | 15 | Low |

### 3.3 Critical Dependencies

```
Flask + Extensions     → Tauri + Axum (optional internal)
SQLAlchemy            → SQLx / Diesel / rusqlite
SocketIO              → Tauri Events
WebSockets            → tokio-tungstenite
Argon2                → argon2 (Rust crate)
Cryptography          → ring / RustCrypto
Requests/HTTPX        → reqwest
ZeroMQ                → Tauri channels (native)
APScheduler           → tokio-cron-scheduler
```

---

## 4. Target Architecture

### 4.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Tauri Application                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │   WebView UI    │◄──►│      Tauri IPC Bridge           │ │
│  │  (HTML/CSS/JS)  │    │   (Commands & Events)           │ │
│  └─────────────────┘    └─────────────────────────────────┘ │
│           │                           │                      │
│           ▼                           ▼                      │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                   Rust Core Engine                       ││
│  ├─────────────────────────────────────────────────────────┤│
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌─────────┐ ││
│  │  │  Order    │ │  Market   │ │  Strategy │ │ Broker  │ ││
│  │  │  Manager  │ │   Data    │ │  Engine   │ │ Router  │ ││
│  │  └───────────┘ └───────────┘ └───────────┘ └─────────┘ ││
│  ├─────────────────────────────────────────────────────────┤│
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌─────────┐ ││
│  │  │  Auth     │ │  Config   │ │  Crypto   │ │ Logger  │ ││
│  │  │  Manager  │ │  Manager  │ │  Module   │ │         │ ││
│  │  └───────────┘ └───────────┘ └───────────┘ └─────────┘ ││
│  └─────────────────────────────────────────────────────────┘│
│           │                           │                      │
│           ▼                           ▼                      │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │   SQLite DB     │    │     Broker WebSocket Pool       │ │
│  │  (Encrypted)    │    │   (24+ Broker Connections)      │ │
│  └─────────────────┘    └─────────────────────────────────┘ │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Module Structure

```
openalgo-desktop/
├── src-tauri/
│   ├── src/
│   │   ├── main.rs                 # Application entry
│   │   ├── lib.rs                  # Library exports
│   │   ├── commands/               # Tauri IPC commands
│   │   │   ├── mod.rs
│   │   │   ├── auth.rs             # Authentication commands
│   │   │   ├── orders.rs           # Order management
│   │   │   ├── market_data.rs      # Quotes, depth, history
│   │   │   ├── portfolio.rs        # Positions, holdings, funds
│   │   │   ├── strategy.rs         # Strategy management
│   │   │   └── settings.rs         # App configuration
│   │   ├── brokers/                # Broker integrations
│   │   │   ├── mod.rs              # Broker trait definition
│   │   │   ├── factory.rs          # Broker factory
│   │   │   ├── angel/
│   │   │   ├── zerodha/
│   │   │   ├── dhan/
│   │   │   └── ... (24+ brokers)
│   │   ├── database/               # Database layer
│   │   │   ├── mod.rs
│   │   │   ├── models.rs           # Data models
│   │   │   ├── migrations.rs       # Schema migrations
│   │   │   └── queries.rs          # Query helpers
│   │   ├── services/               # Business logic
│   │   │   ├── mod.rs
│   │   │   ├── order_service.rs
│   │   │   ├── market_service.rs
│   │   │   ├── portfolio_service.rs
│   │   │   └── strategy_service.rs
│   │   ├── streaming/              # WebSocket handling
│   │   │   ├── mod.rs
│   │   │   ├── manager.rs          # Connection manager
│   │   │   └── handlers.rs         # Message handlers
│   │   ├── crypto/                 # Cryptography
│   │   │   ├── mod.rs
│   │   │   ├── encryption.rs       # AES-256-GCM
│   │   │   ├── hashing.rs          # Argon2
│   │   │   └── keyring.rs          # OS keychain
│   │   ├── config/                 # Configuration
│   │   │   ├── mod.rs
│   │   │   └── settings.rs
│   │   └── utils/                  # Utilities
│   │       ├── mod.rs
│   │       ├── logging.rs
│   │       └── errors.rs
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   └── build.rs
├── src/                            # Frontend (Svelte/React/Vue)
│   ├── lib/
│   ├── routes/
│   ├── components/
│   └── stores/
├── package.json
└── vite.config.js
```

### 4.3 Data Flow

```
User Action (UI)
      │
      ▼
┌─────────────────┐
│  Frontend       │  JavaScript/TypeScript
│  (WebView)      │  invoke('command', args)
└────────┬────────┘
         │ Tauri IPC (JSON serialization)
         ▼
┌─────────────────┐
│  Tauri Command  │  #[tauri::command]
│  Handler        │  async fn place_order(...)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Service Layer  │  Business logic, validation
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Broker Router  │  Select broker, transform request
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Broker Adapter │  HTTP/WebSocket to broker API
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Broker API     │  External API call
└────────┬────────┘
         │
         ▼
Response flows back through same layers
```

---

## 5. Technology Stack

### 5.1 Core Technologies

| Layer | Technology | Justification |
|-------|------------|---------------|
| **Runtime** | Tauri 2.0 | Native performance, small binary, secure IPC |
| **Backend** | Rust | Memory safety, performance, async |
| **Frontend** | Svelte + TypeScript | Reactive, small bundle, fast |
| **Database** | SQLite + SQLCipher | Encrypted, embedded, portable |
| **Styling** | Tailwind CSS | Utility-first, consistent with current UI |

### 5.2 Rust Crates

```toml
[dependencies]
# Framework
tauri = { version = "2.0", features = ["shell-open", "dialog", "notification"] }
tauri-plugin-store = "2.0"          # Encrypted storage
tauri-plugin-autostart = "2.0"      # Launch on startup
tauri-plugin-updater = "2.0"        # Auto-updates

# Async Runtime
tokio = { version = "1", features = ["full"] }

# HTTP Client
reqwest = { version = "0.12", features = ["json", "rustls-tls"] }

# WebSocket
tokio-tungstenite = "0.24"

# Database
rusqlite = { version = "0.32", features = ["bundled", "sqlcipher"] }

# Serialization
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"

# Cryptography
argon2 = "0.5"                       # Password hashing
ring = "0.17"                        # AES-GCM, HMAC
chacha20poly1305 = "0.10"            # Additional encryption

# Time & Scheduling
chrono = { version = "0.4", features = ["serde"] }
tokio-cron-scheduler = "0.13"

# Logging
tracing = "0.1"
tracing-subscriber = "0.3"

# Error Handling
thiserror = "2.0"
anyhow = "1.0"

# Utilities
once_cell = "1.20"
parking_lot = "0.12"
dashmap = "6.0"                      # Concurrent hashmap
```

### 5.3 Frontend Stack

```json
{
  "devDependencies": {
    "@sveltejs/vite-plugin-svelte": "^4.0.0",
    "@tauri-apps/api": "^2.0.0",
    "@tauri-apps/plugin-store": "^2.0.0",
    "svelte": "^5.0.0",
    "typescript": "^5.6.0",
    "vite": "^6.0.0",
    "tailwindcss": "^3.4.0",
    "daisyui": "^4.0.0"
  }
}
```

---

## 6. Feature Mapping

### 6.1 Core Features Matrix

| Python Feature | Rust Equivalent | Priority | Complexity |
|----------------|-----------------|----------|------------|
| User Authentication | Tauri + SQLite + Keyring | P0 | Medium |
| Broker OAuth | System Browser + Deep Link | P0 | High |
| Order Placement | Tauri Commands + reqwest | P0 | Medium |
| Order Book/Trade Book | SQLite + Tauri Events | P0 | Low |
| Positions/Holdings | Cached state + Events | P0 | Low |
| Real-time Quotes | WebSocket + Events | P0 | High |
| Market Depth | WebSocket + Events | P1 | Medium |
| Historical Data | HTTP + Local Cache | P1 | Medium |
| Options Chain | Computed + Cached | P1 | High |
| Option Greeks | Pure Rust calculation | P1 | Medium |
| Strategy Management | File-based + Scheduler | P2 | High |
| Telegram Bot | tokio-telegram-bot | P2 | Medium |
| Sandbox Mode | Separate SQLite DB | P2 | Medium |
| Action Center | State Machine | P2 | Low |

### 6.2 API Command Mapping

```
Python REST API              →    Tauri Command
─────────────────────────────────────────────────
POST /placeorder             →    place_order
POST /placesmartorder        →    place_smart_order
POST /modifyorder            →    modify_order
POST /cancelorder            →    cancel_order
POST /cancelallorder         →    cancel_all_orders
POST /closeposition          →    close_position
GET  /orderbook              →    get_orderbook
GET  /tradebook              →    get_tradebook
GET  /positionbook           →    get_positions
GET  /holdings               →    get_holdings
GET  /funds                  →    get_funds
GET  /quotes                 →    get_quotes
GET  /depth                  →    get_depth
GET  /history                →    get_history
GET  /optionchain            →    get_option_chain
GET  /optiongreeks           →    get_option_greeks
```

### 6.3 Event Mapping

```
Python SocketIO Event        →    Tauri Event
─────────────────────────────────────────────────
order_update                 →    order:update
trade_update                 →    trade:update
position_update              →    position:update
quote_update                 →    quote:{symbol}
depth_update                 →    depth:{symbol}
connection_status            →    broker:status
strategy_update              →    strategy:update
error                        →    error:global
```

---

## 7. Security Model

### 7.1 Threat Model

| Threat | Mitigation |
|--------|------------|
| Memory corruption | Rust memory safety |
| Credential theft | OS Keychain + encrypted SQLite |
| Man-in-the-middle | TLS 1.3, certificate pinning |
| Local file tampering | Encrypted database, checksums |
| Malicious updates | Code signing, update verification |
| IPC injection | Strict command validation |

### 7.2 Security Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Security Layers                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Layer 1: Transport Security                                 │
│  ├── TLS 1.3 for all HTTP/WebSocket                         │
│  ├── Certificate pinning for broker APIs                     │
│  └── Secure WebSocket (wss://)                              │
│                                                              │
│  Layer 2: Data at Rest                                       │
│  ├── SQLCipher (AES-256) for database                       │
│  ├── OS Keychain for master password                         │
│  └── Encrypted config files                                  │
│                                                              │
│  Layer 3: Authentication                                     │
│  ├── Argon2id for password hashing                          │
│  ├── TOTP 2FA support                                        │
│  └── Session tokens with expiry                              │
│                                                              │
│  Layer 4: Authorization                                      │
│  ├── Command-level permission checks                         │
│  ├── Rate limiting                                           │
│  └── Action audit logging                                    │
│                                                              │
│  Layer 5: Application Security                               │
│  ├── CSP for WebView                                         │
│  ├── Input validation on all commands                        │
│  └── Sandboxed WebView (no Node.js)                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 Credential Storage

```rust
// Credentials are stored in OS Keychain
// Database encryption key derived from keychain secret

┌─────────────────┐
│   OS Keychain   │  Master encryption key
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Key Derivation │  PBKDF2-SHA256 (100K iterations)
│     (PBKDF2)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  SQLCipher Key  │  Database encryption
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Encrypted Data  │  API keys, tokens, credentials
│    (SQLite)     │
└─────────────────┘
```

---

## 8. Performance Goals

### 8.1 Benchmarks

| Metric | Current (Python) | Target (Rust) | Improvement |
|--------|-----------------|---------------|-------------|
| Cold start | 5-10s | < 2s | 5x |
| Order placement | 100-200ms | < 50ms | 4x |
| Quote update | 50ms | < 10ms | 5x |
| Memory (idle) | 300-500MB | < 150MB | 3x |
| Memory (active) | 500-800MB | < 300MB | 2x |
| Binary size | N/A (Python) | < 50MB | - |
| WebSocket reconnect | 2-5s | < 500ms | 5x |

### 8.2 Optimization Strategies

1. **Connection Pooling**: Reuse HTTP connections to brokers
2. **Message Batching**: Aggregate quote updates (50ms window)
3. **Lazy Loading**: Load broker modules on-demand
4. **Cache Strategy**: LRU cache for quotes, aggressive cache for master contracts
5. **Zero-Copy Parsing**: Use `serde` with borrowed data where possible
6. **Async Everything**: Non-blocking I/O throughout
7. **Memory Mapping**: mmap for large master contract files

---

## 9. Migration Strategy

### 9.1 Phase Overview

```
Phase 1: Foundation (4-6 weeks)
├── Tauri project setup
├── Database schema & migrations
├── Authentication system
├── Basic UI shell
└── 1 broker integration (Angel)

Phase 2: Core Trading (6-8 weeks)
├── Order management (place, modify, cancel)
├── Portfolio views (positions, holdings, funds)
├── Order/trade book
├── 3 more brokers (Zerodha, Dhan, Fyers)
└── Basic error handling

Phase 3: Market Data (4-6 weeks)
├── Real-time quotes (WebSocket)
├── Market depth
├── Historical data
├── Symbol search
└── 5 more brokers

Phase 4: Advanced Features (6-8 weeks)
├── Options chain
├── Option Greeks
├── Multi-leg strategies
├── Strategy scheduler
└── Remaining brokers

Phase 5: Polish (4 weeks)
├── Auto-update system
├── Crash reporting
├── Performance optimization
├── Documentation
└── Beta testing
```

### 9.2 Parallel Development

```
Week     1  2  3  4  5  6  7  8  9  10 11 12
─────────────────────────────────────────────
Backend  [████████████████████████████████]
Frontend    [██████████████████████████████]
Brokers        [███████████████████████████]
Testing           [████████████████████████]
Docs                        [██████████████]
```

---

## 10. Risk Assessment

### 10.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Broker API changes | High | Medium | Version detection, fallback logic |
| WebSocket complexity | Medium | High | Battle-tested libraries, extensive testing |
| Cross-platform issues | Medium | Medium | CI testing on all platforms |
| Performance regression | Low | High | Continuous benchmarking |
| Security vulnerabilities | Low | Critical | Security audit, fuzzing |

### 10.2 Project Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Scope creep | High | Medium | Strict phase gates |
| Broker parity delays | Medium | High | Prioritize top 5 brokers |
| Learning curve (Rust) | Medium | Medium | Start with simpler modules |
| UI/UX regression | Low | Medium | A/B testing with users |

### 10.3 Contingency Plans

1. **Broker Integration Delays**: Ship with subset of brokers, add others post-launch
2. **Performance Issues**: Fall back to Python for specific features via sidecar
3. **Security Concerns**: Engage external security audit before launch
4. **Platform Issues**: Prioritize Windows first (largest user base)

---

## Document References

| Document | Description |
|----------|-------------|
| [01-ARCHITECTURE.md](./01-ARCHITECTURE.md) | Detailed architecture design |
| [02-DATABASE.md](./02-DATABASE.md) | Database schema and migrations |
| [03-TAURI-COMMANDS.md](./03-TAURI-COMMANDS.md) | Tauri IPC command reference |
| [04-FRONTEND.md](./04-FRONTEND.md) | Frontend component design |
| [05-BROKER-INTEGRATION.md](./05-BROKER-INTEGRATION.md) | Broker adapter patterns |
| [06-ROADMAP.md](./06-ROADMAP.md) | Implementation timeline |

---

**Next Steps:**

1. Review and approve this product design
2. Set up Tauri project scaffold
3. Define database schema in detail
4. Begin Phase 1 implementation

---

*Document maintained by: OpenAlgo Team*
*Last updated: December 2024*
