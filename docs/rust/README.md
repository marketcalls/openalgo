# OpenAlgo Desktop - Rust/Tauri Product Design Documentation

## Overview

This documentation describes the complete product design for rebuilding OpenAlgo as a Rust/Tauri desktop application. The goal is to replace the Python Flask backend with a high-performance Rust implementation while maintaining 100% API compatibility with existing SDKs (Python, Go, Node.js, Excel, Amibroker).

## Documentation Index

### Core Architecture

| # | Document | Description |
|---|----------|-------------|
| 00 | [Product Design](./00-PRODUCT-DESIGN.md) | Executive summary and product vision |
| 01 | [Architecture](./01-ARCHITECTURE.md) | System architecture and technology stack |
| 02 | [Database](./02-DATABASE.md) | SQLite/SQLCipher schema and migrations |
| 03 | [Tauri Commands](./03-TAURI-COMMANDS.md) | Rust-JS IPC interface definitions |
| 04 | [Frontend](./04-FRONTEND.md) | Svelte 5 + TypeScript UI implementation |
| 05 | [Broker Integration](./05-BROKER-INTEGRATION.md) | 24-broker adapter pattern implementation |
| 06 | [Roadmap](./06-ROADMAP.md) | Implementation phases and milestones |

### REST API & Services

| # | Document | Description |
|---|----------|-------------|
| 07 | [REST API](./07-REST-API.md) | External REST API specification |
| 12 | [Services Layer](./12-SERVICES-LAYER.md) | Internal service architecture patterns |
| 20 | [API Reference](./20-API-REFERENCE.md) | Complete 35+ endpoint reference |

### Real-Time Data

| # | Document | Description |
|---|----------|-------------|
| 08 | [WebSocket Streaming](./08-WEBSOCKET-STREAMING.md) | Real-time market data streaming |

### Trading Features

| # | Document | Description |
|---|----------|-------------|
| 09 | [Sandbox Mode](./09-SANDBOX-MODE.md) | Paper trading engine (Rs 1 Crore virtual capital) |
| 10 | [Action Center](./10-ACTION-CENTER.md) | Semi-auto mode for SEBI RA compliance |

### Integrations

| # | Document | Description |
|---|----------|-------------|
| 11 | [Telegram Bot](./11-TELEGRAM-BOT.md) | Mobile trading via Telegram |
| 15 | [External Webhooks](./15-EXTERNAL-WEBHOOKS.md) | ngrok/cloudflared tunneling |
| 16 | [Webhook Platforms](./16-WEBHOOK-PLATFORMS.md) | TradingView, GoCharting, ChartInk, Strategies |
| 18 | [SDK Compatibility](./18-SDK-COMPATIBILITY.md) | Python, Go, Node, Excel, Amibroker SDKs |

### Configuration & Security

| # | Document | Description |
|---|----------|-------------|
| 13 | [Configuration](./13-CONFIGURATION.md) | App settings management |
| 14 | [Logging](./14-LOGGING.md) | Structured logging with tracing |
| 17 | [Zero-Config](./17-ZERO-CONFIG-ARCHITECTURE.md) | DB-stored configuration, first-run wizard |
| 19 | [Security](./19-SECURITY.md) | Comprehensive security architecture |

### Monitoring & Diagnostics

| # | Document | Description |
|---|----------|-------------|
| 21 | [Monitoring Dashboards](./21-MONITORING-DASHBOARDS.md) | Analyzer, Live Logs, Latency Dashboard |

---

## Technology Stack

### Backend (Rust)
- **Tauri 2.0**: Desktop application framework
- **Axum**: Embedded HTTP server for REST API
- **SQLx + SQLCipher**: Encrypted SQLite database
- **tokio-tungstenite**: WebSocket server
- **zeromq**: Inter-process communication
- **tracing**: Structured logging
- **teloxide**: Telegram bot framework

### Frontend (TypeScript)
- **Svelte 5**: Reactive UI framework with runes
- **SvelteKit**: Routing and SSR
- **TailwindCSS**: Utility-first styling
- **Tauri APIs**: Native desktop integration

---

## Key Features

### Zero-Config Installation
- No `.env` file required
- All settings stored in encrypted database
- First-run wizard for guided setup
- Import from existing Python OpenAlgo installations

### SDK Compatibility
- 100% backward compatible REST API
- Same WebSocket protocol
- Same endpoint paths (`/api/v1/*`)
- Same request/response schemas
- Existing SDKs work without modification

### Security
- Argon2id password hashing with pepper
- Fernet (AES-128-CBC) token encryption
- SQLCipher database encryption
- IP ban system with threat detection
- Rate limiting (moving window)
- CSRF/CORS protection

### Multi-Broker Support
- 24 Indian brokers supported
- BrokerAdapter trait pattern
- Per-user broker configuration
- Dynamic adapter loading

---

## Directory Structure

```
src-tauri/
├── Cargo.toml
├── tauri.conf.json
└── src/
    ├── main.rs
    ├── lib.rs
    ├── api/                    # REST API
    │   ├── router.rs
    │   ├── middleware.rs
    │   ├── orders/
    │   ├── market/
    │   ├── account/
    │   └── schemas/
    ├── broker/                 # Broker adapters
    │   ├── mod.rs
    │   ├── adapter.rs
    │   ├── angel/
    │   ├── zerodha/
    │   └── ...
    ├── commands/              # Tauri IPC
    │   ├── auth.rs
    │   ├── trading.rs
    │   └── ...
    ├── database/              # SQLite/SQLCipher
    │   ├── connection.rs
    │   ├── migrations/
    │   └── models/
    ├── services/              # Business logic
    │   ├── order_service.rs
    │   ├── quotes_service.rs
    │   └── ...
    ├── security/              # Auth & security
    │   ├── password.rs
    │   ├── api_key.rs
    │   ├── rate_limiter.rs
    │   └── ip_security.rs
    ├── streaming/             # WebSocket & ZMQ
    │   ├── websocket_server.rs
    │   ├── zmq_publisher.rs
    │   └── zmq_subscriber.rs
    └── config/                # Configuration
        ├── settings.rs
        └── network.rs

src/                           # Svelte frontend
├── app.html
├── routes/
│   ├── +layout.svelte
│   ├── +page.svelte           # Dashboard
│   ├── login/
│   ├── dashboard/
│   ├── orders/
│   ├── positions/
│   ├── settings/
│   ├── chartink/
│   ├── tradingview/
│   ├── gocharting/
│   ├── strategy/
│   ├── security/
│   └── setup/                 # First-run wizard
├── lib/
│   ├── components/
│   ├── stores/
│   ├── api/
│   └── utils/
└── static/
```

---

## Quick Links

- [Architecture Overview](./01-ARCHITECTURE.md)
- [Complete API Reference](./20-API-REFERENCE.md)
- [Security Architecture](./19-SECURITY.md)
- [Zero-Config Setup](./17-ZERO-CONFIG-ARCHITECTURE.md)
- [SDK Compatibility](./18-SDK-COMPATIBILITY.md)

---

## Version

- Documentation Version: 1.0.0
- Target OpenAlgo Version: 2.0.0 (Rust)
- Last Updated: December 2025
