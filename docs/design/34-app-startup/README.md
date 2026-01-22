# 34 - App Startup

## Overview

OpenAlgo follows a carefully orchestrated startup sequence that ensures all components are properly initialized before accepting requests. The startup performs environment validation, database initialization, cache restoration, and service activation.

## Startup Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        OpenAlgo Startup Sequence                             │
└──────────────────────────────────────────────────────────────────────────────┘

                        uv run app.py
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 1: Environment Validation                                             │
│                                                                              │
│  utils/env_check.py::load_and_check_env_variables()                         │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 1. Check ENV_CONFIG_VERSION compatibility                           │    │
│  │    - Compare .env version with .sample.env                          │    │
│  │    - Warn if outdated, prompt to continue or exit                   │    │
│  │                                                                     │    │
│  │ 2. Validate required environment variables (30+ vars)               │    │
│  │    - APP_KEY, API_KEY_PEPPER (security)                            │    │
│  │    - BROKER_API_KEY, BROKER_API_SECRET (broker auth)               │    │
│  │    - DATABASE_URL, WEBSOCKET_PORT (infrastructure)                 │    │
│  │    - Rate limits, logging config                                   │    │
│  │                                                                     │    │
│  │ 3. Validate broker-specific API key formats                         │    │
│  │    - 5paisa: User_Key:::User_ID:::client_id                        │    │
│  │    - Flattrade: client_id:::api_key                                │    │
│  │    - Dhan: client_id:::api_key                                     │    │
│  │                                                                     │    │
│  │ 4. Validate REDIRECT_URL matches valid broker                       │    │
│  │                                                                     │    │
│  │ 5. Exit with error if any validation fails                          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (if all validations pass)
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 2: Flask App Creation (create_app())                                  │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 1. Initialize Flask application                                     │    │
│  │                                                                     │    │
│  │ 2. Initialize extensions:                                           │    │
│  │    - SocketIO (real-time updates)                                  │    │
│  │    - CSRF Protection                                               │    │
│  │    - Flask-Limiter (rate limiting)                                 │    │
│  │    - Flask-CORS (cross-origin)                                     │    │
│  │    - CSP Middleware (content security)                             │    │
│  │                                                                     │    │
│  │ 3. Configure session cookies:                                       │    │
│  │    - HTTPONLY, SAMESITE=Lax                                        │    │
│  │    - SECURE if HTTPS detected                                      │    │
│  │    - __Secure- prefix for HTTPS                                    │    │
│  │                                                                     │    │
│  │ 4. Register 30+ blueprints:                                         │    │
│  │    - React frontend (if /frontend/dist exists)                     │    │
│  │    - REST API (/api/v1/)                                           │    │
│  │    - UI blueprints (dashboard, orders, etc.)                       │    │
│  │    - Webhook endpoints (chartink, strategy, flow)                  │    │
│  │                                                                     │    │
│  │ 5. Configure CSRF exemptions:                                       │    │
│  │    - API endpoints (use API key auth)                              │    │
│  │    - Webhook endpoints (external callbacks)                        │    │
│  │    - OAuth broker callbacks                                        │    │
│  │                                                                     │    │
│  │ 6. Initialize middleware:                                           │    │
│  │    - Security middleware (IP banning, etc.)                        │    │
│  │    - Traffic logging                                               │    │
│  │    - Latency monitoring                                            │    │
│  │                                                                     │    │
│  │ 7. Setup error handlers (400, 404, 429, 500)                        │    │
│  │                                                                     │    │
│  │ 8. Auto-start Telegram bot (if previously active)                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 3: Setup Environment (setup_environment())                            │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 1. Load broker plugins                                              │    │
│  │    utils/plugin_loader.py::load_broker_auth_functions()            │    │
│  │    - Scan broker/*/plugin.json                                     │    │
│  │    - Load auth functions dynamically                               │    │
│  │                                                                     │    │
│  │ 2. Initialize 17 databases in PARALLEL (ThreadPoolExecutor)         │    │
│  │    - Auth DB, User DB, Master Contract DB                          │    │
│  │    - API Log DB, Analyzer DB, Settings DB                          │    │
│  │    - Chartink DB, Traffic Logs DB, Latency DB                      │    │
│  │    - Strategy DB, Sandbox DB, Action Center DB                     │    │
│  │    - Chart Prefs DB, Market Calendar DB                            │    │
│  │    - Qty Freeze DB, Historify DB, Flow DB                          │    │
│  │                                                                     │    │
│  │ 3. Initialize Flow scheduler                                        │    │
│  │    services/flow_scheduler_service.py                              │    │
│  │                                                                     │    │
│  │ 4. Setup ngrok cleanup handlers                                     │    │
│  │    (always registered, tunnel created later if enabled)            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 4: Cache Restoration                                                  │
│                                                                              │
│  database/cache_restoration.py::restore_all_caches()                        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Enables server restart without re-login:                            │    │
│  │                                                                     │    │
│  │ 1. Restore Symbol Cache                                             │    │
│  │    - Load broker symbols from master contract DB                   │    │
│  │    - Rebuild BrokerSymbolCache in memory                           │    │
│  │                                                                     │    │
│  │ 2. Restore Auth Token Cache                                         │    │
│  │    - Load encrypted tokens from auth DB                            │    │
│  │    - Decrypt and restore to TTLCache                               │    │
│  │                                                                     │    │
│  │ Result: Users remain logged in after server restart                 │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 5: Analyzer Mode Services (if enabled)                                │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Check: database/settings_db.py::get_analyze_mode()                  │    │
│  │                                                                     │    │
│  │ If Analyzer Mode is ON, start in PARALLEL:                          │    │
│  │                                                                     │    │
│  │ 1. Execution Engine (sandbox/execution_thread.py)                   │    │
│  │    - Monitors pending orders                                       │    │
│  │    - Executes based on live market prices                          │    │
│  │                                                                     │    │
│  │ 2. Square-off Scheduler (sandbox/squareoff_thread.py)               │    │
│  │    - Auto-closes MIS positions at EOD                              │    │
│  │                                                                     │    │
│  │ 3. Catch-up Settlement Processor                                    │    │
│  │    - Process any missed T+1 settlements                            │    │
│  │    - Handles weekend/holiday gaps                                  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 6: WebSocket Proxy Integration                                        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Check environment mode:                                             │    │
│  │                                                                     │    │
│  │ Docker/Standalone Mode:                                             │    │
│  │   - WebSocket server started separately by start.sh                │    │
│  │   - Skip proxy integration                                         │    │
│  │                                                                     │    │
│  │ Local/Integrated Mode:                                              │    │
│  │   - Start WebSocket proxy in Flask process                         │    │
│  │   - websocket_proxy/app_integration.py::start_websocket_proxy()    │    │
│  │   - Runs on port 8765 (default)                                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 7: Server Start (__main__ block)                                      │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 1. Read server configuration:                                       │    │
│  │    - FLASK_HOST_IP (default: 127.0.0.1)                            │    │
│  │    - FLASK_PORT (default: 5000)                                    │    │
│  │    - FLASK_DEBUG mode                                              │    │
│  │                                                                     │    │
│  │ 2. Start ngrok tunnel (if NGROK_ALLOW=TRUE)                         │    │
│  │    utils/ngrok_manager.py::start_ngrok_tunnel()                    │    │
│  │                                                                     │    │
│  │ 3. Display startup banner with:                                     │    │
│  │    - Version number                                                │    │
│  │    - Web App URL                                                   │    │
│  │    - WebSocket URL                                                 │    │
│  │    - Ngrok URL (if enabled)                                        │    │
│  │    - Docs URL                                                      │    │
│  │    - Ready status                                                  │    │
│  │                                                                     │    │
│  │ 4. Start SocketIO server:                                           │    │
│  │    socketio.run(app, host, port, debug)                            │    │
│  │    - Excludes strategies/* and log/* from reloader                 │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                       Server Ready!
```

## Startup Checks Summary

### Environment Validation Checks

| Check | Description | Exit on Failure |
|-------|-------------|-----------------|
| `.env` exists | Configuration file must exist | Yes |
| Version compatibility | ENV_CONFIG_VERSION matches sample | Prompt |
| Required variables | 30+ env vars must be set | Yes |
| Broker API format | Broker-specific format validation | Yes |
| REDIRECT_URL | Must match valid broker | Yes |
| Rate limit format | `N per timeunit` format | Yes |
| Port numbers | Valid range 0-65535 | Yes |
| Log configuration | Valid log level, retention | Yes |

### Database Initialization

All 17 databases initialized in parallel for fast startup:

```python
db_init_functions = [
    ('Auth DB', ensure_auth_tables_exists),
    ('User DB', ensure_user_tables_exists),
    ('Master Contract DB', ensure_master_contract_tables_exists),
    ('API Log DB', ensure_api_log_tables_exists),
    ('Analyzer DB', ensure_analyzer_tables_exists),
    ('Settings DB', ensure_settings_tables_exists),
    ('Chartink DB', ensure_chartink_tables_exists),
    ('Traffic Logs DB', ensure_traffic_logs_exists),
    ('Latency DB', ensure_latency_tables_exists),
    ('Strategy DB', ensure_strategy_tables_exists),
    ('Sandbox DB', ensure_sandbox_tables_exists),
    ('Action Center DB', ensure_action_center_tables_exists),
    ('Chart Prefs DB', ensure_chart_prefs_tables_exists),
    ('Market Calendar DB', ensure_market_calendar_tables_exists),
    ('Qty Freeze DB', ensure_qty_freeze_tables_exists),
    ('Historify DB', ensure_historify_tables_exists),
    ('Flow DB', ensure_flow_tables_exists),
]

# Parallel execution with ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=15) as executor:
    futures = {executor.submit(func): name for name, func in db_init_functions}
```

## Before Request Hook

Every request goes through session validation:

```python
@app.before_request
def check_session_expiry():
    """Check session validity before each request"""

    # Skip for static files, API endpoints, public routes
    if (request.path.startswith('/static/') or
        request.path.startswith('/api/') or
        request.path in ['/', '/auth/login', '/setup', ...]):
        return

    # Check if user is logged in and session is expired
    if session.get('logged_in') and not is_session_valid():
        logger.info(f"Session expired for user: {session.get('user')}")
        revoke_user_tokens()
        session.clear()
```

## Error Handlers

| Error | Handler | Behavior |
|-------|---------|----------|
| 400 | CSRF error | JSON for API, redirect for web |
| 404 | Not found | Track for security, serve React app |
| 429 | Rate limit | JSON for API, redirect for web |
| 500 | Server error | Log error, redirect to /error |

## Startup Banner Example

```
╭─── OpenAlgo v1.3.0 ──────────────────────────────────────────╮
│                                                              │
│             Your Personal Algo Trading Platform              │
│                                                              │
│ Endpoints                                                    │
│ Web App    http://127.0.0.1:5000                            │
│ WebSocket  ws://127.0.0.1:8765                              │
│ Docs       https://docs.openalgo.in                         │
│                                                              │
│ Status     Ready                                             │
│                                                              │
╰──────────────────────────────────────────────────────────────╯
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `app.py` | Main entry point, orchestrates startup |
| `utils/env_check.py` | Environment validation |
| `utils/plugin_loader.py` | Dynamic broker loading |
| `database/cache_restoration.py` | Cache warmup on restart |
| `sandbox/execution_thread.py` | Analyzer mode order execution |
| `websocket_proxy/app_integration.py` | WebSocket server integration |
| `extensions.py` | Flask extension instances |
