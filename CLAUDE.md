# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

OpenAlgo is a production-ready algorithmic trading platform built with Flask (backend) and React 19 (frontend). It provides a unified API layer across 24+ Indian brokers, enabling seamless integration with TradingView, Amibroker, Excel, Python, and AI agents.

**Repository**: https://github.com/marketcalls/openalgo
**Documentation**: https://docs.openalgo.in

## Security and Deployment Model

- **Single user per deployment** — no multi-user, no privilege escalation. One user, one broker session per instance.
- **Self-hosted on user's own server** — server access = full control. No SaaS component.
- All official install scripts (`install.sh`, `install-docker.sh`, `install-multi.sh`, `docker-run.sh`, `docker-run.bat`, `start.sh`) auto-generate unique `APP_KEY` and `API_KEY_PEPPER` via `secrets.token_hex(32)`.
- **SEBI static IP mandate** (effective April 1, 2026): All transactional API orders require broker-side static IP whitelisting. Delta Exchange (crypto) also enforces this. Stolen broker credentials CANNOT be used from an attacker's machine — the broker rejects requests from non-registered IPs. However, attacks routed THROUGH the OpenAlgo server (which has the registered IP) are still viable.
- External platforms (TradingView, GoCharting, Chartink) send API keys in JSON body or URL query params — they cannot set custom HTTP headers. This is an accepted architectural trade-off.
- The MCP server (`mcp/mcpserver.py`) is local-only, communicates via stdio with Claude Desktop/Cursor/Windsurf. It is NOT remotely exposed.
- Indian broker tokens expire daily at ~3:00 AM IST. Session management is aligned to this schedule.

## Development Environment Setup

### Prerequisites
- Python 3.12+ (required per pyproject.toml)
- Node.js 20/22/24 for React frontend development
- **uv package manager (required)** - Never use global Python

### Initial Setup

```bash
# Install uv package manager (required)
pip install uv

# Configure environment
cp .sample.env .env

# Generate new APP_KEY and API_KEY_PEPPER:
uv run python -c "import secrets; print(secrets.token_hex(32))"

# Build React frontend (required - not tracked in git)
cd frontend && npm install && npm run build && cd ..

# Run application (uv automatically handles virtual env and dependencies)
uv run app.py
```

### Important: Always Use UV

**Never use global Python or manually manage virtual environments.** Always prefix Python commands with `uv run`:

```bash
# Running the app
uv run app.py

# Running any Python script
uv run python script.py

# Installing a new package (adds to pyproject.toml)
uv add package_name

# Syncing dependencies after pulling changes
uv sync
```

### React Frontend Development

```bash
cd frontend

# Install dependencies
npm install

# Development server (hot reload)
npm run dev

# Production build
npm run build

# Run tests
npm test

# Run end-to-end tests
npm run e2e

# Linting and formatting
npm run lint
npm run format
```

## Application Architecture

### Frontend

**React 19 Frontend** (`/frontend/`): Modern SPA with TypeScript, Vite, shadcn/ui, TanStack Query. Built and served from `/frontend/dist/` by Flask via `blueprints/react_app.py`.

### Backend Structure

- `app.py` - Main Flask application entry point
- `blueprints/` - Flask route handlers (UI and webhooks)
- `restx_api/` - REST API endpoints (`/api/v1/`)
- `broker/` - Broker integrations (24+ brokers), each with `api/`, `database/`, `mapping/`, `streaming/`, `plugin.json`
- `services/` - Business logic layer
- `database/` - SQLAlchemy models and database utilities
- `utils/` - Shared utilities and helpers
- `websocket_proxy/` - Unified WebSocket server (port 8765)

### Database Architecture

OpenAlgo uses **6 separate databases** for isolation:

- `db/openalgo.db` - Main database (users, orders, positions, settings)
- `db/logs.db` - Traffic and API logs
- `db/latency.db` - Latency monitoring data
- `db/health.db` - Health monitoring data
- `db/sandbox.db` - Analyzer/sandbox mode (isolated virtual trading)
- `db/historify.duckdb` - Historical market data (DuckDB)

Each database has its own initialization function in `/database/`.

#### SQLite Connection Pooling (NullPool)

All SQLite databases use `NullPool` — each operation gets a fresh connection, closed immediately after use. **Do NOT use `StaticPool`** (single shared connection) — it causes `"bad parameter or other API misuse"` and `"cannot commit - SQL statements in progress"` errors because concurrent requests corrupt the shared connection's cursor state. This applies to all platforms (Windows, Mac, Linux).

FD leak prevention is handled by 5 layers of session cleanup:
- `app.py` `teardown_appcontext` removes all scoped sessions after every request
- `traffic_logger.py` explicit `logs_session.remove()` in finally block
- `security_middleware.py` explicit cleanup for banned-IP WSGI path
- `blueprints/traffic.py` and `blueprints/security.py` teardown handlers

#### HTTP Client Pooling

Broker API calls use `httpx` with HTTP/2 connection pooling (`utils/httpx_client.py`). A single shared client instance per broker session maintains persistent connections to the broker's API servers, avoiding TCP/TLS handshake overhead on every order or data request.

### Broker Integration Pattern

All 24+ brokers follow a standardized structure in `broker/{broker_name}/`:

1. `api/auth_api.py` - OAuth2 or API key based authentication
2. `api/order_api.py` - Place, modify, cancel orders
3. `api/data.py` - Quotes, depth, historical data
4. `api/funds.py` - Account balance and margins
5. `mapping/` - Transform OpenAlgo format ↔ broker format
6. `streaming/` - WebSocket adapter for real-time data
7. `database/master_contract_db.py` - Symbol mapping
8. `plugin.json` - Broker metadata

Reference implementations: `/broker/zerodha/`, `/broker/dhan/`, `/broker/angel/`

### WebSocket Architecture

Real-time market data flows through a three-layer pipeline:

1. **Broker WebSocket Adapters** (`broker/*/streaming/`): Each broker has a WebSocket adapter that connects to the broker's proprietary feed and normalizes data into OpenAlgo's internal format. Connection pooling is per-broker: `MAX_SYMBOLS_PER_WEBSOCKET` (default: 1000) x `MAX_WEBSOCKET_CONNECTIONS` (default: 3) = 3000 symbols max.

2. **ZeroMQ Message Bus** (port 5555): Broker adapters publish normalized tick data to a ZeroMQ PUB socket. This decouples the broker feed from client delivery — the broker adapter runs independently and never blocks on slow clients.

3. **Unified WebSocket Proxy Server** (`websocket_proxy/server.py`, port 8765): Subscribes to ZeroMQ, manages client WebSocket connections, handles symbol subscriptions/unsubscriptions, and delivers filtered ticks to each connected client. Includes per-symbol throttling to prevent flooding slow clients.

### Request Processing Pipeline

WSGI middleware wraps in reverse order — last registered is outermost. The request flows:

```
Incoming Request
  → TrafficLoggerMiddleware (logs method, path, duration, status code)
    → SecurityMiddleware (checks IP ban list, blocks banned IPs with 403)
      → CSP Middleware (sets Content-Security-Policy headers)
        → Flask app (routing, blueprints, CSRF, session)
          → API key auth (for /api/v1/ endpoints)
            → Service layer → Broker API
```

Registered in `app.py:319-323`: security middleware first, then traffic logging (so traffic wraps outside security). Session cleanup happens in `teardown_appcontext` after the response is sent.

## Runtime Constraints

### Eventlet + Gunicorn (Production)

Production deployments (Ubuntu direct and Docker) run under **Gunicorn with eventlet worker** (`--worker-class eventlet -w 1`). This has critical implications:

- **No `asyncio`**: eventlet monkey-patches the stdlib and is incompatible with `asyncio.run()`, `async/await`, and `asyncio.get_event_loop()`. Any code that needs async behavior must use eventlet green threads or run async work on a separate real OS thread (see `telegram_bot_service.py:_render_plotly_png` for the pattern).
- **Single worker (`-w 1`)**: Required for WebSocket and SocketIO compatibility. Flask-SocketIO state is in-process and cannot be shared across workers.
- **`threading.local()` maps to green threads**: eventlet monkey-patches `threading.local()` so each green thread gets its own session. This is why `scoped_session` works correctly under eventlet.

### Windows / Mac Development

The Flask development server (`uv run app.py`) uses standard threading, not eventlet. Code must work in both environments. Key differences:
- No monkey-patching — standard `threading` and `socket` modules
- `asyncio` works normally on dev server but will break under eventlet in production
- SQLite concurrency behavior differs (Windows is more restrictive with file locking)

## Common Development Tasks

### Running the Application

```bash
# Development mode (auto-reloads on code changes)
uv run app.py

# Production mode with Gunicorn (Linux only)
uv run gunicorn --worker-class eventlet -w 1 app:app

# IMPORTANT: Use -w 1 (one worker) for WebSocket compatibility
```

Access points:
- Main app: http://127.0.0.1:5000
- API docs: http://127.0.0.1:5000/api/docs
- React frontend: http://127.0.0.1:5000/react

### Testing

```bash
# Run all tests
uv run pytest test/ -v

# Run specific test file
uv run pytest test/test_broker.py -v

# Run single test function
uv run pytest test/test_broker.py::test_function_name -v

# Run tests with coverage
uv run pytest test/ --cov

# React frontend tests
cd frontend
npm test                    # Run all tests
npm run test:coverage      # With coverage
npm run e2e                # End-to-end tests
```

Most testing is currently manual via:
- Web UI: http://127.0.0.1:5000
- Swagger API: http://127.0.0.1:5000/api/docs
- API Analyzer: http://127.0.0.1:5000/analyzer

### Building for Production

```bash
# Build React frontend
cd frontend
npm run build

# The React build artifacts go to frontend/dist/
# These are served by Flask via blueprints/react_app.py
```

### Important: Frontend Build (CI/CD)

**`frontend/dist/` is NOT tracked in git.** The CI/CD pipeline builds it automatically on each push.

For local development after cloning:
```bash
cd frontend
npm install
npm run build
```

This is required before running the application locally. The build artifacts are gitignored to:
- Prevent merge conflicts on hash-named files
- Keep the repository size smaller
- Ensure fresh builds via CI/CD

## Key Architectural Concepts

### Plugin System for Brokers

Brokers are dynamically loaded from `broker/*/plugin.json`. The plugin loader (`utils/plugin_loader.py`) discovers and loads broker modules at runtime. To add a new broker:

1. Create directory: `broker/new_broker/`
2. Implement required modules: `api/`, `mapping/`, `database/`, `streaming/`
3. Add `plugin.json` with metadata
4. Add broker to `VALID_BROKERS` in `.env`

### REST API Layer (Flask-RESTX)

The `/api/v1/` endpoints are defined in `restx_api/`:
- Automatic Swagger documentation at `/api/docs`
- Uses Flask-RESTX for request/response validation
- All endpoints require API key authentication
- Rate limiting configured per endpoint type

### Action Center (Order Approval System)

Orders can flow through two modes:
- **Auto Mode**: Direct execution (personal trading)
- **Semi-Auto Mode**: Manual approval required (managed accounts)

Approval workflow in `database/action_center_db.py` and `services/action_center_service.py`

### Analyzer Mode (Paper Trading)

Separate database (`sandbox.db`) with ₹1 Crore virtual capital:
- Realistic margin system with leverage
- Auto square-off at exchange timings
- Complete isolation from live trading
- Toggle via `/analyzer` blueprint

### Real-Time Communication (Event-Driven Architecture)

OpenAlgo uses an event-driven architecture where state changes are broadcast to the UI in real-time:

1. **Flask-SocketIO events**: Order placement, modification, cancellation, position updates, and analyzer results all emit SocketIO events (e.g., `order_update`, `analyzer_update`, `cache_loaded`). The React frontend subscribes to these events for live dashboard updates without polling.

2. **WebSocket Proxy**: Unified market data streaming (port 8765) — see WebSocket Architecture above.

3. **ZeroMQ PUB/SUB**: Internal message bus between broker adapters and WebSocket proxy (port 5555). Also used for cache invalidation events across modules.

Key event flows:
- **Order placed** → `order_router_service.py` → broker API → `socketio.emit("order_update")` → UI updates
- **Market data tick** → broker WebSocket adapter → ZeroMQ PUB → WebSocket proxy → client browser
- **Master contract loaded** → `master_contract_cache_hook.py` → `socketio.emit("cache_loaded")` → UI notified
- **Analyzer trade** → `sandbox_service.py` → `socketio.emit("analyzer_update")` → sandbox UI updates

## Important Configuration

### Environment Variables (.env)

Critical variables to configure:
- `APP_KEY`: Flask secret key (generate with secrets.token_hex(32))
- `API_KEY_PEPPER`: Encryption pepper (generate with secrets.token_hex(32))
- `BROKER_API_KEY` / `BROKER_API_SECRET`: Broker credentials
- `VALID_BROKERS`: Comma-separated list of enabled brokers
- `DATABASE_URL`: Main database path
- `WEBSOCKET_HOST` / `WEBSOCKET_PORT`: WebSocket server config
- `MAX_SYMBOLS_PER_WEBSOCKET`: Symbol limit per connection
- `FLASK_DEBUG`: Enable debug mode (development only)

## Code Style and Conventions

### Python
- Follow PEP 8 style guide
- Use 4 spaces for indentation
- Use Google-style docstrings
- Imports: Standard library → Third-party → Local

### React/TypeScript
- Follow Biome.js linting rules (`frontend/biome.json`)
- Use functional components with hooks
- Component files use PascalCase: `MyComponent.tsx`

### Git Commit Messages (Conventional Commits)
- `feat:` New features
- `fix:` Bug fixes
- `docs:` Documentation changes
- `refactor:` Code refactoring

## Common Patterns and Utilities

### API Authentication

All `/api/v1/` endpoints require API key:
```python
# In request body (recommended):
{"apikey": "YOUR_API_KEY", "symbol": "SBIN", ...}

# Or in headers:
X-API-KEY: YOUR_API_KEY
```

API keys are generated at `/apikey` and hashed with pepper before storage.

### Symbol Format

OpenAlgo uses a standardized symbol format across all 24+ brokers. Broker-specific symbols are mapped via `broker/*/mapping/` modules and stored in the `SymToken` table.

**Equity:** Just the base symbol — `INFY`, `SBIN`, `TATAMOTORS`

**Futures:** `[BaseSymbol][ExpiryDate]FUT` — `BANKNIFTY24APR24FUT`, `CRUDEOILM20MAY24FUT`

**Options:** `[BaseSymbol][ExpiryDate][Strike][CE/PE]` — `NIFTY28MAR2420800CE`, `VEDL25APR24292.5CE`

**Exchange codes:** `NSE` (equity), `BSE` (equity), `NFO` (NSE F&O), `BFO` (BSE F&O), `CDS` (NSE currency), `BCD` (BSE currency), `MCX` (commodity), `NCDEX` (commodity), `NSE_INDEX` (indices), `BSE_INDEX` (indices)

**Order constants:**
- **Product:** `CNC` (cash & carry / delivery), `NRML` (futures & options carry), `MIS` (intraday square-off)
- **Price type:** `MARKET`, `LIMIT`, `SL` (stop-loss limit), `SL-M` (stop-loss market)
- **Action:** `BUY`, `SELL`

**Database schema (`SymToken`):** `symbol` (OpenAlgo format), `brsymbol` (broker format), `exchange`, `brexchange`, `token` (broker instrument token), `expiry`, `strike`, `lotsize`, `instrumenttype`, `tick_size`

### Database Queries

Always use SQLAlchemy ORM (never raw SQL):
```python
from database.auth_db import User

# Good
user = User.query.filter_by(username='admin').first()
```

### Error Handling

Return consistent JSON responses and use `logger.exception()` for error logging:
```python
from utils.logging import get_logger
logger = get_logger(__name__)

try:
    result = broker_module.place_order(data, token)
    return {'status': 'success', 'data': result}
except Exception as e:
    logger.exception(f"Error placing order: {e}")  # auto-captures traceback
    return {'status': 'error', 'message': str(e)}
```

### React API Calls

Use TanStack Query for server state:
```typescript
import { useQuery } from '@tanstack/react-query';

const { data, isLoading, error } = useQuery({
  queryKey: ['positions'],
  queryFn: () => api.getPositions()
});
```

## Logging Architecture

### Centralized Logging (`utils/logging.py`)

All logging flows through Python's standard `logging` module, configured in `setup_logging()` at import time. Every module uses `logger = get_logger(__name__)`.

**Three output handlers (all share the same `SensitiveDataFilter` to redact API keys/tokens):**

1. **Console** (always active): Colored output via `ColoredFormatter`, level controlled by `LOG_LEVEL` env var.
2. **File** (if `LOG_TO_FILE=True`): Daily-rotated text logs in `log/openalgo_YYYY-MM-DD.log`, retained for `LOG_RETENTION` days.
3. **JSON error log** (always active): `log/errors.jsonl` — structured JSON Lines, ERROR+ only.

### Error Log for Debugging

When debugging issues, **read `log/errors.jsonl` first**. Each line is a JSON object with: timestamp, logger name, module, source file:line, error message, full exception traceback (if any), and Flask request context (method, path, IP) when available. Auto-truncated to the last 1000 entries on app startup.

### Error Handling Convention

All error logging uses `logger.exception()` (not `logger.error()` + manual traceback). This automatically captures the full traceback and routes it to the JSON error handler. Do NOT use `import traceback` / `traceback.print_exc()` / `traceback.format_exc()` — these bypass centralized logging.

## Troubleshooting Common Issues

### WebSocket Connection Issues
1. Ensure WebSocket server is running (starts with app.py)
2. Check `WEBSOCKET_HOST` and `WEBSOCKET_PORT` in `.env`
3. For Gunicorn: Use `-w 1` (single worker only)
4. Check firewall settings for port 8765

### Database Locked Errors
1. SQLite doesn't handle high concurrency well
2. Close all connections and restart app
3. For production, consider PostgreSQL

### Broker Integration Not Loading
1. Check broker name in `VALID_BROKERS` (.env)
2. Verify `plugin.json` exists in broker directory
3. Check broker module structure matches pattern
4. Restart application to reload plugins

### React Frontend Build Errors
1. Ensure Node.js version matches `frontend/package.json` engines
2. Delete `frontend/node_modules` and run `npm install`
3. Check for TypeScript errors: `npm run build`

## Claude Code Instructions

### Frontend Build Process
When building the React frontend locally:
- Run `cd frontend && npm run build` (build only, no tests)
- Tests are handled by CI/CD pipeline, not required for local builds
- The `frontend/dist/` directory is gitignored and built by GitHub Actions
