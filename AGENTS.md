# AGENTS.md

This file provides guidance for AI agents and developers working with code in this repository.

## Project Overview

## Notes

### Diagnosing Very Slow Broker HTTP Calls (60–180s)

If broker requests (especially Zerodha/Kite `api.kite.trade`) occasionally take 60–180 seconds, it may be **TCP connect stalling** (often due to broken/blocked IPv6 paths, VPN tunnels like `utun*`, or ISP routing), not slow broker processing.

Quick diagnosis (no code changes required):

- Compare IPv4 vs IPv6 from the same machine:
  - `curl -v -4 https://api.kite.trade`
  - `curl -v -6 https://api.kite.trade --max-time 10`
  - If `-4` is fast and `-6` times out, IPv6 is likely the cause.

Interpreting low-level traces:

- When using `httpcore` tracing, a large gap between `connect_tcp.started` and `connect_tcp.complete` indicates a network/connectivity problem (connect phase), not broker latency.

Mitigation guidance:

- Prefer fixing the environment (disable IPv6 on the host/network or fix IPv6 routing).
- For latency-sensitive endpoints (quotes/ltp), consider enforcing **short connect timeouts** so requests fail fast instead of hanging for minutes.

### Avoid Startup Breakage When Modifying Logging

`setup_logging()` runs at import time. When adding logs inside it, always use a defined logger (e.g., `logging.getLogger(__name__)`) and avoid referencing undefined variables; otherwise the app can fail to start.

**OpenAlgo** is a production-ready algorithmic trading platform built with Flask (backend) and React
19 (frontend). It provides a unified API layer across 24+ Indian brokers, enabling seamless
integration with TradingView, Amibroker, Excel, Python, and AI agents.

- **Repository**: https://github.com/marketcalls/openalgo
- **Documentation**: https://docs.openalgo.in
- **License**: AGPL v3.0

> **Note**: This is a forked repository with custom modifications. See **[FORK.md](FORK.md)** for details on fork-specific changes and upstream sync instructions.

## Technology Stack

### Backend
- Python 3.12+ (required)
- Flask 3.0+ with Flask-RESTX, Flask-SocketIO, Flask-SQLAlchemy
- SQLite (development) / PostgreSQL (production recommended)
- DuckDB for historical market data
- ZeroMQ for high-performance message queue

### Frontend
- **Jinja2 Templates**: Traditional Flask templates with Tailwind CSS 4 + DaisyUI 5
- **React 19 Frontend**: Modern SPA with TypeScript, Vite, shadcn/ui, TanStack Query

### Key Dependencies
- `httpx` - HTTP client with HTTP/2 support
- `websockets` - WebSocket client and server
- `APScheduler` - Background task scheduling
- `pandas`, `numpy` - Data manipulation
- `argon2-cffi`, `cryptography` - Security

## Development Environment Setup

### Prerequisites
- Python 3.12+
- Node.js 20+ (for CSS compilation and React frontend)
- **uv package manager (required)** - Never use global Python

### Initial Setup

```bash
# Install uv package manager
pip install uv

# Configure environment
cp .sample.env .env

# Generate new APP_KEY and API_KEY_PEPPER:
uv run python -c "import secrets; print(secrets.token_hex(32))"

# Run application (uv automatically handles virtual env and dependencies)
uv run app.py
```

                                           Always Use UV

Never use global Python or manually manage virtual environments. Always prefix Python commands with
uv run:

```bash
uv run app.py                    # Run the application
uv run python script.py          # Run any Python script
uv add package_name              # Install a new package
uv sync                          # Sync dependencies after pulling changes
```

                                 CSS Development (Jinja2 Templates)

```bash
npm run dev      # Development mode (auto-compile on changes)
npm run build    # Production build (before committing)
# NEVER edit static/css/main.css directly - only edit src/css/styles.css
```

                                     React Frontend Development

```bash
cd frontend
npm install      # Install dependencies
npm run dev      # Development server (hot reload)
npm run build    # Production build
npm test         # Run tests
npm run e2e      # End-to-end tests
npm run lint     # Linting
```


                                        Directory Structure

                                          Core Application

 • app.py - Main Flask application entry point
 • extensions.py - Flask extensions (SocketIO)
 • blueprints/ - Flask route handlers (UI and webhooks)
 • restx_api/ - REST API endpoints (/api/v1/)
 • services/ - Business logic layer
 • database/ - SQLAlchemy models and database utilities
 • utils/ - Shared utilities and helpers

                                         Broker Integration

 • broker/ - 24+ broker integrations, each with:
    • api/ - Authentication, orders, data, funds
    • database/ - Master contract management
    • mapping/ - OpenAlgo ↔ broker format transformation
    • streaming/ - WebSocket adapter
    • plugin.json - Broker metadata

                                              Frontend

 • frontend/ - React 19 SPA (TypeScript, Vite)
 • frontend/dist/ - Built React assets (served by Flask)
 • templates/ - Jinja2 HTML templates
 • static/ - Static assets (CSS, JS, images)
 • src/css/ - Source CSS (Tailwind)

                                       WebSocket & Real-Time

 • websocket_proxy/ - Unified WebSocket server (port 8765)
 • sandbox/ - Paper trading/analyzer mode

                                               Other

 • strategies/ - Trading strategy examples
 • test/ - Test files
 • docs/ - Documentation
 • mcp/ - Model Context Protocol integration
 • upgrade/ - Database migration scripts


                                       Database Architecture

OpenAlgo uses 5 separate databases for isolation:


  Database              Purpose
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  db/openalgo.db        Main database (users, orders, positions, settings)
  db/logs.db            Traffic and API logs
  db/latency.db         Latency monitoring data
  db/sandbox.db         Analyzer/sandbox mode (virtual trading)
  db/historify.duckdb   Historical market data (DuckDB)



                                     Key Architectural Patterns

                                        Broker Plugin System

 • Brokers are dynamically loaded from broker/*/plugin.json
 • Plugin loader: utils/plugin_loader.py
 • Reference implementations: broker/zerodha/, broker/dhan/, broker/angel/

                                       WebSocket Architecture

 • Unified Proxy Server: websocket_proxy/server.py (port 8765)
 • ZeroMQ Message Bus: High-performance data distribution (port 5555)
 • Connection Pooling: MAX_SYMBOLS_PER_WEBSOCKET × MAX_WEBSOCKET_CONNECTIONS

                                            Order Modes

 • Auto Mode: Direct execution (personal trading)
 • Semi-Auto Mode: Manual approval via Action Center

                                   Analyzer Mode (Paper Trading)

 • Separate database (sandbox.db) with ₹1 Crore virtual capital
 • Toggle via /analyzer blueprint


                                          API Conventions

                                           Authentication

All /api/v1/ endpoints require API key:

```python
# In request body (recommended):
{"apikey": "YOUR_API_KEY", "symbol": "SBIN", ...}

# Or in headers:
X-API-KEY: YOUR_API_KEY
```

                                           Symbol Format

Standardized format across all brokers:

```
NSE:SBIN-EQ           # Equity
NFO:NIFTY24JAN24000CE # Options
NSE:NIFTY-INDEX       # Index
```

                                          Response Format

```python
{
    'status': 'success' | 'error',
    'message': 'Human-readable message',
    'data': {...}  # Optional payload
}
```


                                     Code Style and Conventions

                                               Python

 • Follow PEP 8 style guide
 • Use 4 spaces for indentation
 • Use Google-style docstrings
 • Imports: Standard library → Third-party → Local
 • Always use SQLAlchemy ORM (never raw SQL)

                                          React/TypeScript

 • Follow Biome.js linting rules (frontend/biome.json)
 • Use functional components with hooks
 • Component files use PascalCase: MyComponent.tsx
 • Use TanStack Query for server state

                                 Git Commits (Conventional Commits)

 • feat: New features
 • fix: Bug fixes
 • docs: Documentation changes
 • refactor: Code refactoring


                                              Testing

```bash
# Python tests
uv run pytest test/ -v
uv run pytest test/test_broker.py -v           # Specific file
uv run pytest test/test_broker.py::test_name -v # Specific test

# React frontend tests
cd frontend
npm test
npm run test:coverage
npm run e2e
```

                                       Manual Testing Points

 • Web UI: http://127.0.0.1:5000
 • API Docs (Swagger): http://127.0.0.1:5000/api/docs
 • API Analyzer: http://127.0.0.1:5000/analyzer
 • React Frontend: http://127.0.0.1:5000/react


                                    Common Issues and Solutions

                                          CSS Not Updating

 1 Clear browser cache
 2 Run npm run build in root directory
 3 Never edit static/css/main.css directly

                                    WebSocket Connection Issues

 1 Ensure WebSocket server is running (starts with app.py)
 2 Check WEBSOCKET_HOST and WEBSOCKET_PORT in .env
 3 For Gunicorn: Use -w 1 (single worker only)

                                       Database Locked Errors

 1 Close all connections and restart app
 2 For production, consider PostgreSQL

                                   Broker Integration Not Loading

 1 Check broker name in VALID_BROKERS (.env)
 2 Verify plugin.json exists in broker directory
 3 Restart application to reload plugins


                                        Important Constants

Located in utils/constants.py:

                                             Exchanges

NSE, NFO, CDS, BSE, BFO, BCD, MCX, NCDEX, NSE_INDEX, BSE_INDEX

                                           Product Types

CNC (Cash & Carry), NRML (Normal), MIS (Intraday)

                                            Price Types

MARKET, LIMIT, SL, SL-M

                                              Actions

BUY, SELL


                                        Adding a New Broker

 1 Create directory: broker/new_broker/
 2 Implement required modules:
    • api/auth_api.py - Authentication
    • api/order_api.py - Order management
    • api/data.py - Market data
    • api/funds.py - Account balance
    • mapping/order_data.py - Data transformation
    • database/master_contract_db.py - Symbol mapping
    • streaming/broker_adapter.py - WebSocket adapter
    • plugin.json - Broker metadata
 3 Add broker to VALID_BROKERS in .env
 4 Reference: broker/zerodha/, broker/dhan/


                                      Security Best Practices

 • Never commit sensitive data or API keys
 • Use environment variables for all credentials
 • Validate all user inputs
 • Use parameterized queries (SQLAlchemy ORM)
 • CSRF protection is enabled by default
 • Rate limiting is configured per endpoint type


                                             Resources

 • Discord: https://discord.com/invite/UPh7QPsNhP
 • GitHub Issues: https://github.com/marketcalls/openalgo/issues
 • API Docs: https://docs.openalgo.in
 • PyPI Package: https://pypi.org/project/openalgo
