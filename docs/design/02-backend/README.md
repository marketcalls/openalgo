# 02 - Backend Architecture

## Overview

OpenAlgo backend is a production-ready Flask application providing a unified API layer across **28+ Indian brokers**. It features a plugin-based broker system, multi-database architecture, real-time WebSocket streaming, and comprehensive security layers.

## Technology Stack

| Technology | Purpose |
|------------|---------|
| Flask | Web framework |
| Flask-RESTX | REST API with Swagger |
| Flask-SocketIO | Real-time events |
| SQLAlchemy | ORM for SQLite databases |
| DuckDB | Historical data storage |
| ZeroMQ | High-performance message bus |
| Argon2 | Password hashing |
| Fernet | Token encryption |

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Flask Application                                │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                         Middleware Stack                                │  │
│  │                                                                         │  │
│  │   CSRF Protection → Rate Limiting → Security → Traffic Logging → CSP   │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                      │                                        │
│          ┌───────────────────────────┼───────────────────────────┐           │
│          ▼                           ▼                           ▼           │
│  ┌───────────────┐         ┌─────────────────┐         ┌───────────────────┐ │
│  │  Blueprints   │         │   REST API v1   │         │    WebSocket      │ │
│  │  (34 routes)  │         │   /api/v1/*     │         │    Proxy :8765    │ │
│  └───────┬───────┘         └────────┬────────┘         └─────────┬─────────┘ │
│          │                          │                            │           │
│          └──────────────────────────┼────────────────────────────┘           │
│                                     ▼                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                         Service Layer (50+)                             │  │
│  │                                                                         │  │
│  │   place_order_service   │   quotes_service   │   funds_service         │  │
│  │   cancel_order_service  │   depth_service    │   holdings_service      │  │
│  │   modify_order_service  │   history_service  │   positionbook_service  │  │
│  └────────────────────────────────┬───────────────────────────────────────┘  │
│                                   │                                           │
│                                   ▼                                           │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                      Broker Plugin System (28+)                         │  │
│  │                                                                         │  │
│  │   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │  │
│  │   │ Zerodha │ │  Dhan   │ │  Angel  │ │  Fyers  │ │ Upstox  │  ...     │  │
│  │   └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘          │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Database Layer (5 DBs)                              │
│                                                                               │
│  ┌──────────────┐  ┌──────────┐  ┌────────────┐  ┌───────────┐  ┌─────────┐ │
│  │ openalgo.db  │  │ logs.db  │  │ latency.db │  │sandbox.db │  │historify│ │
│  │   (main)     │  │(traffic) │  │ (metrics)  │  │  (paper)  │  │ .duckdb │ │
│  └──────────────┘  └──────────┘  └────────────┘  └───────────┘  └─────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
openalgo/
├── app.py                      # Application entry point
├── extensions.py               # Flask extensions (SocketIO)
├── limiter.py                  # Rate limiting configuration
├── cors.py                     # CORS configuration
├── csp.py                      # Content Security Policy
│
├── blueprints/                 # Route handlers (33 files)
│   ├── auth.py                 # Login, logout, CSRF
│   ├── core.py                 # Home, setup, download
│   ├── dashboard.py            # Dashboard UI
│   ├── orders.py               # Order management UI
│   ├── brlogin.py              # Broker OAuth callbacks
│   ├── strategy.py             # Strategy webhooks
│   ├── flow.py                 # Flow workflows
│   ├── analyzer.py             # Analyzer mode
│   ├── react_app.py            # React SPA serving
│   └── ...
│
├── restx_api/                  # REST API endpoints
│   ├── __init__.py             # API namespace registry
│   ├── place_order.py          # POST /placeorder
│   ├── quotes.py               # POST /quotes
│   └── ...
│
├── services/                   # Business logic (50+ files)
│   ├── place_order_service.py
│   ├── quotes_service.py
│   ├── order_router_service.py
│   └── ...
│
├── broker/                     # Broker plugins (24+ brokers)
│   ├── zerodha/
│   ├── dhan/
│   ├── angel/
│   └── ...
│
├── database/                   # Database models & utilities
│   ├── auth_db.py              # Auth tables
│   ├── user_db.py              # User tables
│   ├── analyzer_db.py          # Analyzer tables
│   └── ...
│
├── websocket_proxy/            # WebSocket server
│   ├── server.py               # Main server (port 8765)
│   ├── base_adapter.py         # Broker adapter base class
│   └── app_integration.py      # Flask integration
│
├── sandbox/                    # Paper trading engine
│   ├── execution_engine.py
│   ├── fund_manager.py
│   └── ...
│
└── utils/                      # Shared utilities
    ├── plugin_loader.py        # Broker plugin discovery
    ├── security_middleware.py
    └── ...
```

## Application Startup Flow

```
┌────────────────────────────────────────────────────────────────┐
│                     Application Startup                         │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  1. Environment Check                                           │
│     - Validate APP_KEY (required)                               │
│     - Validate API_KEY_PEPPER (min 32 chars)                   │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  2. Flask App Creation                                          │
│     - Initialize SocketIO (threading mode)                      │
│     - Configure CSRF protection                                 │
│     - Setup rate limiting                                       │
│     - Configure CORS                                            │
│     - Apply CSP middleware                                      │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  3. Blueprint Registration (33 blueprints)                      │
│     - React frontend (if available)                             │
│     - REST API v1                                               │
│     - Auth, Dashboard, Orders, Search...                        │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  4. Environment Setup (Parallel - ThreadPoolExecutor)           │
│     - Initialize 5 databases                                    │
│     - Load broker plugins                                       │
│     - Start Flow scheduler                                      │
│     - Restore caches                                            │
│     - Start Analyzer engine (if enabled)                        │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  5. Start Servers                                               │
│     - Flask on port 5000                                        │
│     - WebSocket proxy on port 8765                              │
└────────────────────────────────────────────────────────────────┘
```

## Broker Plugin System

### Plugin Structure

Each broker follows a standardized directory structure:

```
broker/zerodha/
├── plugin.json                 # Broker metadata
│
├── api/
│   ├── __init__.py
│   ├── auth_api.py             # authenticate_broker()
│   ├── order_api.py            # place_order(), modify_order(), cancel_order()
│   ├── data.py                 # get_quotes(), get_depth(), get_history()
│   ├── funds.py                # get_funds()
│   └── margin_api.py           # get_margin()
│
├── mapping/
│   ├── transform_data.py       # Symbol format conversion
│   ├── order_data.py           # Order field mapping
│   └── margin_data.py          # Margin field mapping
│
├── streaming/
│   ├── zerodha_adapter.py      # WebSocket adapter
│   ├── zerodha_websocket.py    # Broker WebSocket client
│   └── zerodha_mapping.py      # Data normalization
│
└── database/
    └── master_contract_db.py   # Symbol master download
```

### Plugin Metadata (plugin.json)

```json
{
    "Plugin Name": "zerodha",
    "Plugin URI": "https://openalgo.in",
    "Description": "Zerodha OpenAlgo Plugin",
    "Version": "1.0",
    "Author": "Rajandran R"
}
```

### Dynamic Plugin Loading

```python
# utils/plugin_loader.py
def load_broker_auth_functions():
    broker_auth_functions = {}
    broker_dir = Path(__file__).parent.parent / 'broker'

    for broker_path in broker_dir.iterdir():
        if broker_path.is_dir():
            plugin_json = broker_path / 'plugin.json'
            if plugin_json.exists():
                module = importlib.import_module(
                    f'broker.{broker_path.name}.api.auth_api'
                )
                broker_auth_functions[broker_path.name] = module.authenticate_broker

    return broker_auth_functions
```

## Service Layer Pattern

Services encapsulate business logic, keeping routes thin:

```python
# services/place_order_service.py
def place_order_service(data, auth_token, api_key=None):
    """
    1. Validate order data
    2. Get broker from auth
    3. Import broker module dynamically
    4. Call broker API
    5. Log to analyzer (async)
    6. Emit SocketIO event
    7. Return response
    """
    broker = get_broker_from_auth()
    module_path = f'broker.{broker}.api.order_api'
    broker_module = importlib.import_module(module_path)

    response = broker_module.place_order(order_data, auth_token)

    # Async logging (non-blocking)
    executor.submit(async_log_analyzer, data, response, 'placeorder')

    # Real-time UI update
    socketio.start_background_task(
        socketio.emit, 'order_event', response
    )

    return response
```

## Blueprint Categories

| Category | Blueprints | Purpose |
|----------|------------|---------|
| Core | auth, core, dashboard | Authentication, home, setup |
| Trading | orders, search, apikey | Order management, symbol search |
| Strategies | strategy, chartink, python_strategy, flow | Webhook strategies |
| Data | tv_json, gc_json, historify | Chart data, historical data |
| Monitoring | log, traffic, latency, security | Logs and metrics |
| Admin | admin, settings, telegram | Configuration |
| Sandbox | analyzer, sandbox | Paper trading |
| Frontend | react_app, platforms | UI serving |

## Request Flow

```
HTTP Request
     │
     ▼
┌─────────────────┐
│  Middleware     │
│  - CSRF check   │
│  - Rate limit   │
│  - IP ban check │
│  - Traffic log  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│   Blueprint     │────▶│    Service      │
│   (Route)       │     │  (Business)     │
└─────────────────┘     └────────┬────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Broker Plugin   │     │    Database     │     │    SocketIO     │
│ (External API)  │     │   (SQLAlchemy)  │     │  (Real-time)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Running the Application

```bash
# Development (auto-reload)
uv run app.py

# Production with Gunicorn (Linux only)
uv run gunicorn --worker-class eventlet -w 1 app:app

# IMPORTANT: Use -w 1 for WebSocket compatibility
```

## Access Points

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:5000 | Main application |
| http://127.0.0.1:5000/api/docs | Swagger API documentation |
| ws://127.0.0.1:8765 | WebSocket market data |

## Key Files Reference

| File | Purpose |
|------|---------|
| `app.py` | Application entry point, startup orchestration |
| `extensions.py` | SocketIO configuration |
| `restx_api/__init__.py` | API namespace registry |
| `utils/plugin_loader.py` | Broker plugin discovery |
| `database/auth_db.py` | Authentication database operations |

## Environment Variables

```bash
# Required
APP_KEY=<32+ char secret>
API_KEY_PEPPER=<32+ char pepper>

# Broker
VALID_BROKERS=zerodha,dhan,angel

# Database
DATABASE_URL=sqlite:///db/openalgo.db

# WebSocket
WEBSOCKET_HOST=127.0.0.1
WEBSOCKET_PORT=8765

# Security
CSRF_ENABLED=TRUE
FLASK_DEBUG=FALSE
```
