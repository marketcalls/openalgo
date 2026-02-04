# 00 - Directory Structure

## Overview

OpenAlgo follows a modular architecture with clear separation of concerns. This document provides a comprehensive map of the project structure to help developers navigate the codebase effectively.

## Root Directory

```
openalgo/
├── app.py                    # Flask application entry point
├── extensions.py             # Flask extensions (SocketIO, CORS)
├── cors.py                   # CORS configuration
├── csp.py                    # Content Security Policy
├── limiter.py                # Rate limiting setup
├── utils.py                  # Legacy utilities
│
├── .env                      # Environment configuration (not in git)
├── .sample.env               # Environment template
├── pyproject.toml            # Python dependencies (uv)
├── requirements.txt          # Pip fallback dependencies
├── uv.lock                   # Locked dependency versions
│
├── package.json              # Node.js for Tailwind CSS (Jinja2 templates)
├── tailwind.config.mjs       # Tailwind configuration
├── postcss.config.mjs        # PostCSS configuration
│
├── CLAUDE.md                 # AI assistant instructions
├── README.md                 # Project overview
├── CONTRIBUTING.md           # Contribution guidelines
├── SECURITY.md               # Security policy
├── License.md                # AGPL-3.0 license
│
├── Dockerfile                # Container build
├── docker-compose.yaml       # Multi-container setup
├── start.sh                  # Production startup script
│
├── blueprints/               # Flask route handlers
├── restx_api/                # REST API endpoints
├── services/                 # Business logic layer
├── database/                 # Database models & utilities
├── broker/                   # Broker integrations (29 brokers)
├── utils/                    # Shared utilities
├── websocket_proxy/          # Real-time data server
├── sandbox/                  # Sandbox trading engine
├── frontend/                 # React 19 SPA
├── templates/                # Jinja2 HTML templates
├── static/                   # Static assets (CSS, JS, images)
├── docs/                     # Documentation
├── test/                     # Test suites
└── db/                       # SQLite database files
```

## Core Backend Modules

### `/blueprints/` - Flask Route Handlers

UI routes and webhook handlers organized by feature.

```
blueprints/
├── __init__.py
├── core.py                   # Base routes, health checks
├── auth.py                   # Login, logout, session management
├── brlogin.py                # Broker OAuth callbacks
├── dashboard.py              # Main dashboard UI
├── orders.py                 # Order management UI
├── admin.py                  # Admin panel
├── settings.py               # User settings
├── apikey.py                 # API key management
├── playground.py             # API testing playground
├── flow.py                   # Visual workflow builder
├── historify.py              # Historical data UI
├── analyzer.py               # Sandbox mode UI
├── sandbox.py                # Sandbox API routes
├── pnltracker.py             # P&L tracking
├── chartink.py               # Chartink webhook
├── tv_json.py                # TradingView webhook
├── gc_json.py                # GoCharting webhook
├── telegram.py               # Telegram bot integration
├── search.py                 # Symbol search UI
├── strategy.py               # Strategy management
├── python_strategy.py        # Python strategy execution
├── log.py                    # Log viewer
├── traffic.py                # Traffic logs
├── latency.py                # Latency monitor
├── security.py               # Security settings
├── broker_credentials.py     # Broker API credentials
├── master_contract_status.py # Contract download status
├── system_permissions.py     # Permissions management
├── logging.py                # Logging configuration
├── websocket_example.py      # WebSocket demo page
├── platforms.py              # Platform integrations
└── react_app.py              # React SPA serving
```

### `/restx_api/` - REST API Endpoints

Flask-RESTX namespaces for `/api/v1/` routes with Swagger documentation.

```
restx_api/
├── __init__.py               # API namespace registry
├── schemas.py                # Common response schemas
├── data_schemas.py           # Data model schemas
├── account_schema.py         # Account schemas
│
├── place_order.py            # POST /placeorder
├── place_smart_order.py      # POST /placesmartorder
├── options_order.py          # POST /optionsorder
├── options_multiorder.py     # POST /optionsmultiorder
├── modify_order.py           # POST /modifyorder
├── cancel_order.py           # POST /cancelorder
├── cancel_all_order.py       # POST /cancelallorder
├── close_position.py         # POST /closeposition
├── basket_order.py           # POST /basketorder
├── split_order.py            # POST /splitorder
│
├── orderbook.py              # GET /orderbook
├── orderstatus.py            # GET /orderstatus
├── tradebook.py              # GET /tradebook
├── positionbook.py           # GET /positionbook
├── holdings.py               # GET /holdings
├── openposition.py           # GET /openposition
├── funds.py                  # GET /funds
├── margin.py                 # GET /margin
│
├── quotes.py                 # GET /quotes
├── multiquotes.py            # GET /multiquotes
├── depth.py                  # GET /depth
├── history.py                # GET /history
├── ticker.py                 # WebSocket ticker info
│
├── symbol.py                 # Symbol lookup
├── search.py                 # Symbol search
├── instruments.py            # Instrument list
├── intervals.py              # Timeframe intervals
├── expiry.py                 # Option expiry dates
│
├── option_chain.py           # Option chain data
├── option_greeks.py          # Option Greeks
├── multi_option_greeks.py    # Batch Greeks
├── option_symbol.py          # Option symbol builder
├── synthetic_future.py       # Synthetic future price
│
├── market_holidays.py        # Market holiday calendar
├── market_timings.py         # Exchange timings
├── pnl_symbols.py            # P&L by symbol
├── chart_api.py              # Chart data
│
├── analyzer.py               # Sandbox mode API
├── telegram_bot.py           # Telegram integration
└── ping.py                   # Health check endpoint
```

### `/services/` - Business Logic Layer

Core business logic separated from routes.

```
services/
├── place_order_service.py        # Order placement logic
├── place_smart_order_service.py  # Smart order with position awareness
├── place_options_order_service.py # Options order handling
├── options_multiorder_service.py # Multi-leg options
├── modify_order_service.py       # Order modification
├── cancel_order_service.py       # Order cancellation
├── cancel_all_order_service.py   # Bulk cancellation
├── close_position_service.py     # Position closing
├── basket_order_service.py       # Basket orders
├── split_order_service.py        # Order splitting for large qty
├── order_router_service.py       # Order routing logic
├── pending_order_execution_service.py # Pending order execution
├── action_center_service.py      # Manual approval workflow
│
├── orderbook_service.py          # Order book retrieval
├── orderstatus_service.py        # Order status lookup
├── tradebook_service.py          # Trade history
├── positionbook_service.py       # Position data
├── holdings_service.py           # Holdings data
├── openposition_service.py       # Open positions
├── funds_service.py              # Account funds
├── margin_service.py             # Margin calculation
│
├── quotes_service.py             # Real-time quotes
├── depth_service.py              # Market depth
├── history_service.py            # Historical OHLCV
├── market_data_service.py        # Market data aggregation
├── chart_service.py              # Charting data
│
├── symbol_service.py             # Symbol resolution
├── search_service.py             # Symbol search
├── instruments_service.py        # Instrument data
├── intervals_service.py          # Timeframe info
├── expiry_service.py             # Expiry dates
│
├── option_chain_service.py       # Option chain
├── option_greeks_service.py      # Greeks calculation
├── option_symbol_service.py      # Option symbol builder
├── synthetic_future_service.py   # Synthetic futures
│
├── market_calendar_service.py    # Trading calendar
├── historify_service.py          # Historical data storage
├── analyzer_service.py           # Sandbox mode
├── sandbox_service.py            # Sandbox operations
│
├── telegram_alert_service.py     # Telegram alerts
├── telegram_bot_service.py       # Telegram bot commands
│
├── flow_executor_service.py      # Flow execution engine
├── flow_scheduler_service.py     # Scheduled flows
├── flow_price_monitor_service.py # Price-triggered flows
├── flow_openalgo_client.py       # Flow API client
│
├── websocket_service.py          # WebSocket management
└── websocket_client.py           # WebSocket client
```

### `/database/` - Database Models & Utilities

SQLAlchemy models and database operations.

```
database/
├── __init__.py
├── db_init_helper.py             # Database initialization
│
├── auth_db.py                    # User, ApiKey, Token models
├── user_db.py                    # User CRUD operations
├── token_db.py                   # Token management
├── settings_db.py                # User settings
│
├── sandbox_db.py                 # Sandbox mode models
├── analyzer_db.py                # Analyzer database
├── action_center_db.py           # Order approval workflow
│
├── strategy_db.py                # Strategy storage
├── flow_db.py                    # Flow workflows
├── chartink_db.py                # Chartink configurations
├── telegram_db.py                # Telegram settings
│
├── symbol.py                     # Symbol helpers
├── tv_search.py                  # TradingView search
├── qty_freeze_db.py              # Quantity freeze limits
├── market_calendar_db.py         # Market calendar data
├── master_contract_status_db.py  # Contract download status
├── master_contract_cache_hook.py # Contract caching
├── chart_prefs_db.py             # Chart preferences
│
├── historify_db.py               # Historical data (DuckDB)
├── apilog_db.py                  # API logs
├── latency_db.py                 # Latency metrics
├── traffic_db.py                 # Traffic logs
├── cache_restoration.py          # Cache recovery
└── token_db_enhanced.py          # Enhanced token features
```

### `/utils/` - Shared Utilities

Common utilities used across the application.

```
utils/
├── __init__.py
├── config.py                 # Configuration loading
├── constants.py              # Application constants
├── logging.py                # Logging setup
├── session.py                # Session management
│
├── auth_utils.py             # Authentication helpers
├── security_middleware.py    # Security middleware
├── ip_helper.py              # IP address utilities
│
├── plugin_loader.py          # Broker plugin discovery
├── api_analyzer.py           # API analysis tools
├── httpx_client.py           # HTTP client pooling
│
├── email_utils.py            # Email sending
├── email_debug.py            # Email debugging
│
├── latency_monitor.py        # Latency tracking
├── traffic_logger.py         # Traffic logging
├── number_formatter.py       # Number formatting
├── mpp_slab.py               # Margin slab calculations
│
├── ngrok_manager.py          # Ngrok tunnel management
├── env_check.py              # Environment validation
├── version.py                # Version information
└── socketio_error_handler.py # SocketIO error handling
```

## Broker Integration

### `/broker/` - Broker Plugins

Each broker follows a standardized structure.

```
broker/
├── __init__.py
├── zerodha/                  # Reference implementation
├── dhan/
├── angel/
├── fyers/
├── upstox/
├── kotak/
├── iifl/
├── flattrade/
├── shoonya/
├── aliceblue/
├── fivepaisa/
├── fivepaisaxts/
├── firstock/
├── groww/
├── samco/
├── motilal/
├── mstock/
├── tradejini/
├── wisdom/
├── zebu/
├── ibulls/
├── compositedge/
├── definedge/
├── indmoney/
├── jainamxts/
├── nubra/
├── paytm/
├── pocketful/
└── dhan_sandbox/             # Dhan sandbox mode
```

### Broker Module Structure

Each broker implements the same interface:

```
broker/zerodha/
├── plugin.json               # Broker metadata
├── api/
│   ├── auth_api.py           # OAuth/API authentication
│   ├── order_api.py          # Order operations
│   ├── data.py               # Market data
│   └── funds.py              # Account funds
├── mapping/
│   ├── order_data.py         # Order format mapping
│   ├── transform_data.py     # Data transformation
│   └── *.py                  # Additional mappings
├── database/
│   └── master_contract_db.py # Symbol master download
└── streaming/
    ├── adapter.py            # WebSocket adapter
    └── *.py                  # Streaming utilities
```

## Real-Time Infrastructure

### `/websocket_proxy/` - WebSocket Server

Unified market data streaming server.

```
websocket_proxy/
├── __init__.py
├── server.py                 # Main WebSocket server (port 8765)
├── connection_manager.py     # Client connection handling
├── broker_factory.py         # Broker adapter factory
├── base_adapter.py           # Base WebSocket adapter
├── mapping.py                # Symbol mapping utilities
├── port_check.py             # Port availability check
└── app_integration.py        # Flask integration
```

### `/sandbox/` - Sandbox Trading Engine

Virtual trading environment for testing.

```
sandbox/
├── __init__.py
├── execution_engine.py       # Order execution simulator
├── position_manager.py       # Position tracking
├── fund_manager.py           # Virtual fund management
├── margin_calculator.py      # Margin calculations
├── mtm_engine.py             # Mark-to-market updates
├── auto_squareoff.py         # Auto square-off logic
├── session_manager.py        # Session boundary handling
├── order_validator.py        # Order validation
├── price_feed.py             # Price feed integration
└── *.py                      # Additional modules
```

## Frontend

### `/frontend/` - React 19 SPA

Modern single-page application.

```
frontend/
├── package.json              # Dependencies
├── vite.config.ts            # Vite build config
├── tsconfig.json             # TypeScript config
├── biome.json                # Linting/formatting
├── index.html                # Entry HTML
│
├── src/
│   ├── main.tsx              # Application entry
│   ├── App.tsx               # Router configuration
│   ├── index.css             # Global styles
│   │
│   ├── api/                  # API client modules
│   │   ├── client.ts         # Axios instance
│   │   ├── orders.ts         # Order API
│   │   ├── positions.ts      # Position API
│   │   └── *.ts              # Other API modules
│   │
│   ├── components/           # Reusable components
│   │   ├── ui/               # shadcn/ui components
│   │   ├── layout/           # Layout components
│   │   ├── flow/             # Flow editor components
│   │   └── *.tsx             # Feature components
│   │
│   ├── pages/                # Route pages
│   │   ├── Dashboard.tsx
│   │   ├── OrderBook.tsx
│   │   ├── Positions.tsx
│   │   └── *.tsx
│   │
│   ├── features/             # Feature modules
│   │   ├── auth/
│   │   ├── trading/
│   │   └── *.ts
│   │
│   ├── hooks/                # Custom React hooks
│   │   ├── useSocket.ts
│   │   ├── useApi.ts
│   │   └── *.ts
│   │
│   ├── stores/               # Zustand stores
│   │   ├── authStore.ts
│   │   └── *.ts
│   │
│   ├── lib/                  # Utility libraries
│   │   ├── utils.ts
│   │   └── flow/
│   │
│   ├── types/                # TypeScript types
│   │   ├── api.ts
│   │   ├── order.ts
│   │   └── *.ts
│   │
│   ├── config/               # Configuration
│   │   └── routes.ts
│   │
│   └── test/                 # Test utilities
│
├── dist/                     # Production build output
├── e2e/                      # Playwright E2E tests
└── node_modules/             # Dependencies
```

### `/templates/` - Jinja2 Templates

Server-rendered HTML templates (legacy/admin).

```
templates/
├── base.html                 # Base template
├── login.html                # Login page
├── dashboard.html            # Dashboard
├── admin/                    # Admin templates
└── *.html                    # Other pages
```

### `/static/` - Static Assets

```
static/
├── css/
│   └── main.css              # Compiled Tailwind CSS
├── js/
│   └── *.js                  # JavaScript files
└── icons/
    └── *.png                 # Favicons and icons
```

## Data & Storage

### `/db/` - Database Files

```
db/
├── openalgo.db               # Main database (users, orders, settings)
├── logs.db                   # API and traffic logs
├── latency.db                # Latency metrics
├── sandbox.db                # Sandbox trading data
└── historify.duckdb          # Historical market data (DuckDB)
```

## Documentation

### `/docs/` - Documentation

```
docs/
├── design/                   # Developer design docs (this folder)
│   ├── 00-directory-structure/
│   ├── 01-frontend/
│   ├── 02-backend/
│   └── ...
│
├── api/                      # API documentation
├── userguide/                # User guide
├── CHANGELOG.md              # Version history
└── *.md                      # Other docs
```

## Testing

### `/test/` - Test Suites

```
test/
├── conftest.py               # Pytest fixtures
├── test_*.py                 # Backend tests
└── *.py                      # Test utilities
```

## Additional Directories

| Directory | Purpose |
|-----------|---------|
| `/collections/` | Postman/Bruno API collections |
| `/examples/` | Example integrations and scripts |
| `/strategies/` | Strategy templates |
| `/playground/` | API playground resources |
| `/mcp/` | Model Context Protocol configs |
| `/upgrade/` | Database migration scripts |
| `/install/` | Installation helpers |
| `/scripts/` | Utility scripts |
| `/download/` | Downloaded resources |
| `/data/` | Data files |
| `/keys/` | SSL certificates (not in git) |
| `/logs/` | Application logs (not in git) |
| `/tmp/` | Temporary files (not in git) |

## Key File Reference

| File | Purpose |
|------|---------|
| `app.py` | Main Flask entry point, registers all blueprints |
| `extensions.py` | SocketIO, CORS initialization |
| `frontend/src/App.tsx` | React router configuration |
| `restx_api/__init__.py` | REST API namespace registry |
| `broker/*/plugin.json` | Broker plugin metadata |
| `websocket_proxy/server.py` | WebSocket server entry |
| `sandbox/execution_engine.py` | Sandbox order execution |
| `database/auth_db.py` | Core authentication models |
| `services/place_order_service.py` | Order placement logic |

## Navigation Tips

1. **Finding a feature**: Start in `/blueprints/` for UI routes or `/restx_api/` for API endpoints
2. **Business logic**: Look in `/services/` for the corresponding service
3. **Database operations**: Check `/database/` for models and queries
4. **Broker-specific code**: Navigate to `/broker/{broker_name}/`
5. **Frontend components**: Explore `/frontend/src/components/` and `/frontend/src/pages/`
6. **Real-time features**: See `/websocket_proxy/` for market data streaming
7. **Sandbox mode**: Check `/sandbox/` for virtual trading logic
