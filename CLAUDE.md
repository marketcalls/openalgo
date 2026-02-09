# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

OpenAlgo is a production-ready algorithmic trading platform built with Flask (backend) and React 19 (frontend). It provides a unified API layer across 24+ Indian brokers, enabling seamless integration with TradingView, Amibroker, Excel, Python, and AI agents.

**Repository**: https://github.com/marketcalls/openalgo
**Documentation**: https://docs.openalgo.in

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

OpenAlgo uses **5 separate databases** for isolation:

- `db/openalgo.db` - Main database (users, orders, positions, settings)
- `db/logs.db` - Traffic and API logs
- `db/latency.db` - Latency monitoring data
- `db/sandbox.db` - Analyzer/sandbox mode (isolated virtual trading)
- `db/historify.duckdb` - Historical market data (DuckDB)

Each database has its own initialization function in `/database/`.

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

- **Unified Proxy Server**: `websocket_proxy/server.py` (port 8765)
- **ZeroMQ Message Bus**: High-performance data distribution (port 5555)
- **Broker Adapters**: Normalize broker-specific WebSocket data
- **Connection Pooling**: `MAX_SYMBOLS_PER_WEBSOCKET` (default: 1000) × `MAX_WEBSOCKET_CONNECTIONS` (default: 3) = 3000 symbols

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

### Real-Time Communication

1. **Flask-SocketIO**: Real-time updates for orders, trades, positions, logs
2. **WebSocket Proxy**: Unified market data streaming (port 8765)
3. **ZeroMQ**: High-performance message bus for internal communication

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

OpenAlgo uses standardized symbol format across all brokers:
```
NSE:SBIN-EQ          # Equity
NFO:NIFTY24JAN24000CE  # Options
NSE:NIFTY-INDEX      # Index
```

Broker-specific symbols are mapped via `broker/*/mapping/` modules.

### Database Queries

Always use SQLAlchemy ORM (never raw SQL):
```python
from database.auth_db import User

# Good
user = User.query.filter_by(username='admin').first()
```

### Error Handling

Return consistent JSON responses:
```python
return {
    'status': 'success' | 'error',
    'message': 'Human-readable message',
    'data': {...}  # Optional payload
}
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
