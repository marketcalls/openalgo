# OpenAlgo Design Documentation

## Introduction

Welcome to the design documentation for OpenAlgo, a comprehensive broker-agnostic algorithmic trading platform with advanced strategy hosting capabilities.

**Current Version**: 1.0.0.39 (UI), Python SDK 1.0.39
**Last Updated**: December 2025

### Purpose

This documentation provides a comprehensive understanding of the OpenAlgo system architecture, core components, design patterns, data flows, and operational considerations. It serves as a guide for developers, architects, and maintainers involved in the development and extension of the platform.

### Platform Overview

OpenAlgo is a full-featured trading platform that provides:
* **RESTful API Interface**: Built with Flask-RESTX for programmatic trading (40+ endpoints)
* **Multi-Broker Support**: Unified interface for 27 Indian brokers
* **Strategy Hosting**: TradingView webhooks, ChartInk integration, and Python strategies
* **Real-time Market Data**: WebSocket infrastructure with ZeroMQ backend
* **Paper Trading**: Sandbox mode with Rs 1 Crore virtual capital
* **Telegram Bot**: Mobile trading and monitoring integration
* **Action Center**: Semi-automated order approval workflow for SEBI RA compliance
* **Advanced Analytics**: PnL tracking, latency monitoring, traffic analysis

### Key Features

#### Trading Capabilities
* Place, modify, and cancel orders across 27 brokers
* Smart orders with position sizing (percentage/value)
* Basket orders for multi-leg strategies
* Split orders for large quantity execution
* Options trading with multi-leg support
* Option Greeks calculator

#### Strategy Management
* TradingView webhook signal execution
* ChartInk scanner integration
* Python strategy hosting with process isolation
* Scheduled execution with IST timezone
* Action Center for semi-auto order approval

#### Market Data
* Real-time quotes and multi-quotes
* Market depth (Level 5)
* Historical data with multiple timeframes
* WebSocket streaming for live updates

#### Monitoring & Analytics
* Real-time PnL tracking (sub-minute support)
* Order latency monitoring with percentiles
* API traffic analytics and logging
* Master contract status tracking

### Goals

* **Broker Agnosticism:** Unified API abstracting 27 different broker APIs
* **Strategy Hosting:** Deploy and manage automated strategies easily
* **SEBI Compliance:** Action Center for Research Analyst regulatory compliance
* **Extensibility:** Easy integration of new brokers and strategies
* **Performance:** Efficient handling with < 100ms order placement
* **Reliability:** Stable connections with auto-reconnection
* **Security:** Multi-layer security with Argon2, Fernet encryption
* **Usability:** Clear APIs and intuitive web interface

### Target Users

* **Algorithmic Traders**: Deploy automated trading strategies
* **Developers**: Build custom trading applications via API
* **Research Analysts**: SEBI-compliant advisory with Action Center
* **Quantitative Analysts**: Backtest and deploy quant strategies
* **Trading Firms**: Manage multiple accounts and strategies
* **Individual Traders**: Execute across brokers from one platform

## Documentation Structure

### Core Architecture
- **[01_architecture.md](01_architecture.md)** - Overall system architecture and technology stack
- **[02_api_layer.md](02_api_layer.md)** - RESTful API design with 40+ endpoints
- **[03_broker_integration.md](03_broker_integration.md)** - 27 broker integrations and adapters

### Data and Storage
- **[04_database_layer.md](04_database_layer.md)** - Multi-database design (4 databases, 21+ models)
- **[05_strategies.md](05_strategies.md)** - Trading strategy implementation
- **[11_python_strategy_hosting.md](11_python_strategy_hosting.md)** - Python strategy hosting system

### Security and Configuration
- **[06_authentication_platform.md](06_authentication_platform.md)** - Authentication and authorization
- **[07_configuration.md](07_configuration.md)** - Configuration management
- **[12_deployment_architecture.md](12_deployment_architecture.md)** - Deployment options (VPS, Docker, AWS)

### Infrastructure and Utilities
- **[08_utilities.md](08_utilities.md)** - Common utilities and helpers
- **[09_websocket_architecture.md](09_websocket_architecture.md)** - Real-time WebSocket infrastructure
- **[10_logging_system.md](10_logging_system.md)** - Centralized logging system

### Advanced Features
- **[13_telegram_bot_integration.md](13_telegram_bot_integration.md)** - Telegram bot for mobile trading
- **[14_sandbox_architecture.md](14_sandbox_architecture.md)** - Sandbox/API Analyzer mode
- **[15_action_center.md](15_action_center.md)** - Action Center and Order Mode System

## System Architecture Overview

### High-Level Architecture

```
+-----------------------------------------------------------------+
|                        Client Layer                              |
+----------------+----------------+----------------+---------------+
|   Web UI       |  REST API      |  WebSocket     |   Telegram    |
|  Dashboard     |   Clients      |   Clients      |     Bot       |
+----------------+----------------+----------------+---------------+
                              |
+-----------------------------------------------------------------+
|                    OpenAlgo Platform                             |
+-----------------------------------------------------------------+
|  +-----------------------------------------------------------+  |
|  |              Application Layer (Flask)                     |  |
|  +---------------+-------------+-----------------------------+  |
|  |  26 Blueprints|  REST API   |  Strategy Manager           |  |
|  |  (Web Routes) | (Flask-RESTX)|  (TradingView/ChartInk/Py)  |  |
|  +---------------+-------------+-----------------------------+  |
|                                                                  |
|  +-----------------------------------------------------------+  |
|  |              Business Logic Layer                          |  |
|  +----------+----------+----------+------------+-------------+  |
|  |  Order   | Position | Strategy |  Market    |   Sandbox    |  |
|  |  Manager | Manager  |  Engine  |  Data Mgr  |   Engine     |  |
|  +----------+----------+----------+------------+-------------+  |
|                                                                  |
|  +-----------------------------------------------------------+  |
|  |            Broker Integration Layer (27 Brokers)           |  |
|  +-----------------------------------------------------------+  |
|  |  Broker Adapters | WebSocket Adapters | Symbol Mapping     |  |
|  +-----------------------------------------------------------+  |
|                                                                  |
|  +-----------------------------------------------------------+  |
|  |              Infrastructure Layer                          |  |
|  +----------+----------+----------+------------+-------------+  |
|  | Database | Logging  | WebSocket|  Security  |  Monitoring  |  |
|  |   ORM    |  System  |   Proxy  |  & Auth    |  & Analytics |  |
|  +----------+----------+----------+------------+-------------+  |
+-----------------------------------------------------------------+
                              |
+-----------------------------------------------------------------+
|                    External Systems                              |
+----------------+----------------+----------------+---------------+
|   4 Databases  | 27 Broker APIs| Market Data    |    Cloud      |
|   (SQLite/     |  (REST/WS)    |   Feeds        |   Services    |
|   PostgreSQL)  |               |                |    (AWS)      |
+----------------+----------------+----------------+---------------+
```

## Recent Enhancements (December 2025)

### Core Features
- **Action Center** - Semi-auto order approval workflow for SEBI RA compliance
- **Order Mode System** - Auto/Semi-Auto modes with operation restrictions
- **PNL Tracker Sub-Minute Support** - Fixed timestamp handling for intraday analysis
- **Motilal Oswal WebSocket** - LTP, Quotes, and Depth Level 1 support
- **Options Multi-Order Fix** - Corrected response schema for multi-leg orders
- **Multi-Quote API** - Batch quote retrieval for multiple symbols

### Infrastructure
- **4 Separate Databases** - Main, Sandbox, Latency, and Logs isolation
- **26 Flask Blueprints** - Comprehensive modular routing
- **40+ REST API Endpoints** - Complete trading functionality
- **21+ Database Models** - Full data persistence layer

### Monitoring & Analytics
- **Latency Monitoring** - Order RTT with percentile analysis
- **Traffic Analytics** - Per-user and per-endpoint tracking
- **Master Contract Status** - Contract download monitoring

## Supported Brokers (27 Total)

| Category | Brokers |
|----------|---------|
| **Major Brokers** | Zerodha, Angel One, Upstox, IIFL, Kotak Neo |
| **Discount Brokers** | Fyers, Dhan (Live + Sandbox), 5Paisa, 5Paisa XTS |
| **Traditional** | Motilal Oswal (with WebSocket), Groww, Mstock |
| **Specialized** | Definedge, Shoonya, Flattrade, Alice Blue |
| **Others** | Compositedge, Firstock, IBulls, Indmoney, Paytm Money, Pocketful, Tradejini, Wisdom Capital, Zebu |

Each broker integration includes:
- Order placement and management
- Position and holdings retrieval
- Market data access
- WebSocket streaming (where available)
- Master contract management

## Quick Start

### Installation
1. Use provided installation scripts for Ubuntu/VPS deployment
2. Configure broker API credentials in `.env` file
3. Run migration scripts for database setup
4. Start application with `uv run app.py`

### API Authentication
```bash
# All API calls require X-API-KEY header
curl -X GET "http://localhost:5000/api/v1/quotes?symbol=RELIANCE&exchange=NSE" \
  -H "X-API-KEY: your_api_key"
```

### WebSocket Connection
```python
# Connect to WebSocket proxy on port 8765
import websocket
ws = websocket.WebSocket()
ws.connect("ws://localhost:8765")
```

## Technology Stack

| Component | Technology |
|-----------|------------|
| **Backend** | Python 3.8+, Flask 3.0.3 |
| **API** | Flask-RESTX 1.3.0 |
| **Database** | SQLAlchemy 2.0.31, SQLite/PostgreSQL |
| **WebSocket** | websockets 15.0.1, ZeroMQ |
| **Security** | Argon2, Fernet, pyotp |
| **Scheduling** | APScheduler 3.11.0 |
| **Data Processing** | Pandas 2.2.3, NumPy 2.2.4 |

## Performance Targets

| Operation | Target | Typical |
|-----------|--------|---------|
| Order Placement | < 100ms | ~50ms |
| Quote Retrieval | < 200ms | ~100ms |
| WebSocket Tick | < 50ms | ~20ms |
| Database Query | < 10ms | ~5ms |

## Security Features

- **Password Hashing**: Argon2 with pepper
- **Token Encryption**: Fernet symmetric encryption
- **2FA Support**: TOTP via pyotp
- **Session Security**: IST-based expiry at 3:00 AM
- **API Rate Limiting**: Per-user and per-endpoint
- **CSRF Protection**: WTF-CSRF tokens
- **Sensitive Data Redaction**: In logs and responses
- **SEBI RA Compliance**: Action Center for advisory separation

## Contributing

For detailed setup instructions, refer to the INSTALL.md file in the root directory.

For API documentation, access the Swagger UI at `/api/v1/docs` after starting the application.

## License

OpenAlgo is open source software. See the LICENSE file for details.
