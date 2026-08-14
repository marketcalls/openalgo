# Changelog

All notable changes to OpenAlgo will be documented in this file.

Point releases between minor versions are documented in
[docs/releases](releases/) rather than here.

## [2.0.2.0] - 2026-08-14

### Brokers and Options Release

58 commits since 2.0.1.9. Full notes: [version-2.0.2.0-released.md](releases/version-2.0.2.0-released.md).

---

### Highlights

- **HDFC Securities InvestRight** - new broker plugin covering auth, funds, master contract, orders, quotes, depth, WebSocket streaming and the option tools
- **AliceBlue rebuild** - order-update feed repaired, market-data reconnect storm ended, session-long socket reuse, documented rate limits enforced, index symbology and daily history boundaries corrected
- **Option Chain live Greeks** - client-side Black-76 recomputed on every tick, with a Price/Greeks view mode (shortcut G) and `with_greeks` on `POST /api/v1/optionchain`
- **Strategy Builder repair** - valuation aligned with Black-76, exact listed-contract resolution, live-market freshness, and a run of payoff and forward-curve corrections
- **MCP hardening** - tool annotations, a single structured error shape, a trust envelope, and toolset/read-only filtering on both transports
- **Samco Trade API v3.2**, **Tradejini CubePlus v2**, and **Delta Exchange** market data moved to the public WebSocket endpoint
- **Derivative underlying normalized once** on the shared master-contract path, fixing options orders, expiry lists and the underlying dropdown for every broker

---

### New Features

- HDFC Securities InvestRight broker integration (#1784)
- Option Chain streams live Greeks with a Price/Greeks column-preset toggle
- `POST /api/v1/optionchain` accepts `with_greeks` and `interest_rate`, and returns `expiry_ts` and `server_ts`
- HalfTrend added to the charting terminal as the 20th built-in indicator
- MCP tool annotations, structured errors, trust envelope, and `OPENALGO_MCP_TOOLSETS` / `OPENALGO_MCP_READ_ONLY` filtering
- AliceBlue EC error codes expand into readable messages
- PnL Tracker splits PnL and drawdown into 3:1 panes

### Broker Fixes

- AliceBlue: order-update WebSocket token host, market-data reconnect storm, session-long socket reuse, 1800 req / 15 min rate limit, bounded symbol-lock registry, integer master-contract tokens, BSE historical data, daily history day boundary at midnight IST, index symbology and `::index` history routing
- Samco: migrated to Trade API v3.2; a stalled streaming worker is now always replaced on reconnect (#1783)
- Tradejini: realigned to the refreshed CubePlus v2 API docs (#1787)
- Delta Exchange: market data moved to the public WebSocket endpoint with batched subscriptions; expiry dropdown fixed - requires a master contract re-download (#1790)
- Definedge: no longer loses a full trading day at each history chunk boundary (#1790)
- All brokers: the derivative underlying root is normalized once on the shared master-contract path, fixing Fyers and any broker that ships a contract description in `name`

### Platform Fixes

- 23 unregistered React routes were feeding `Error404Tracker` and pushing logged-out users toward an automatic IP ban; Flask rules added
- Strategy Builder: Black-76 scenario valuation, aggregate horizons, exact listed-contract resolution, stale margin invalidation, WebSocket-bound freshness, closed-leg exclusion, and exact tick rounding (#1786)
- Strategy Builder payoff charts: one carry curve per strategy, forward converging to spot at expiry, no breakeven at an underlying of zero, x-axis no longer collapsing, and zoom preserved
- Flow: option lot size resolved without trusting `SymToken.name`; open strategy legs sort ahead of flat ones
- Greeks: parsed option expiry kept naive
- Charting terminal: screenshots include the readout and exclude the order buttons
- Option Chain: a hidden column now hides on both sides in one toggle

### Documentation

- WebSocket client connection limits clarified (#1764, #1788)
- Option Chain `with_greeks` documented, examples moved to 25AUG26

### Dependencies

- `openalgo-charts`: **1.0.28** to **1.0.29** (HalfTrend indicator, frontend only)
- No Python dependencies changed

---

## [2.0.0.0] - 2026-01-22

### Major Release: Complete Frontend Rewrite & Feature Expansion

This is a major release featuring a complete rewrite of the frontend from Flask/Jinja2 templates to a modern React 19 Single Page Application (SPA). This release includes **212 commits** representing months of development work, introducing new features like Flow Visual Builder, Historify, and enhanced real-time capabilities.

---

## Highlights

- **React 19 Frontend** - Complete migration of 77 templates to modern React with TypeScript
- **Flow Visual Builder** - Node-based visual workflow builder for trading automation
- **Historify** - Historical market data management with DuckDB storage
- **Real-Time WebSocket** - Native WebSocket integration for live market data
- **Sandbox Mode** - Enhanced sandbox testing environment with sandbox capital
- **API Playground** - Bruno-style API testing with WebSocket support
- **Python Strategies** - Enhanced scheduler with real-time status and resource limits
- **Telegram Bot** - Fixed callbacks and improved status display
- **Enhanced Security** - Multiple security improvements and vulnerability fixes

---

## New Features

### React 19 Frontend Migration (77 Templates)

**Phase 1 - Foundation**
- Initialized React frontend with Vite, TypeScript, TanStack Query
- Added Flask blueprint to serve React frontend
- Pre-built frontend dist included for community use

**Phase 2 - Core Authentication & Trading**
- Login, Dashboard, Profile pages
- Orders, Positions, Holdings pages
- Order placement and management

**Phase 3 - Search & Symbol Management**
- FNO Discovery with performance optimization
- Symbol search and watchlist
- Bulk watchlist operations

**Phase 4 - Charts, WebSocket & Sandbox**
- TradingView charts integration
- WebSocket Test Console
- Sandbox/Analyzer mode interface

**Phase 5 - Platform Integrations**
- TradingView webhook page
- GoCharting integration
- Amibroker integration
- ChartInk integration

**Phase 6 - Strategy & Automation**
- Python Strategies management
- Strategy scheduler with SSE
- Strategy logs viewer

**Phase 7 - Monitoring & Administration**
- Logs, Latency Monitor, Traffic Logs
- Profile & Security settings
- Action Center for order approval
- Admin & Telegram modules

**Frontend Tech Stack**
- React 19 with TypeScript
- Vite 6 build system with code splitting
- TanStack Query v5 for server state
- shadcn/ui + Tailwind CSS 4 + DaisyUI
- Biome.js (replaced ESLint)
- Vitest unit tests + Playwright E2E tests
- Responsive mobile bottom navigation
- Accessibility testing (jest-axe)

---

### Flow Visual Builder

- **Node-based visual workflow builder** for trading strategies
- **Order Nodes**: Market Order, Limit Order, Smart Order, Basket Order
- **Options Order Node**: ATM/ITM/OTM offset resolution for F&O
- **Modify Order Node**: Live order management within workflows
- **Cancel Order Node**: Cancel single or all orders
- **Close Position Node**: Square off positions
- **WebSocket Streaming Nodes**: Real-time data within workflows
- **Telegram Alert Node**: Send notifications from workflows
- **Webhook Integration**: Trigger flows from external systems
- **Multi-leg Options Strategy**: Execute complex option strategies
- **Keyboard Shortcuts**: Efficient workflow creation
- Service integration for order execution

---

### Historify - Historical Data Management

- **DuckDB-powered storage** for historical market data
- **Multi-timeframe support**: 1m, 5m, 15m, 30m, 1h, Daily
- **Computed timeframes**: Weekly (W), Monthly (MO), Quarterly (Q), Yearly (Y)
- **Aggregation from daily data** for higher timeframes
- **Bulk export** with inline symbol selection
- **Multi-timeframe export** in single operation
- **Parquet import support** for external data sources
- **TradingView-style charts** with IST timezone
- **Styled crosshair tooltips** with IST timestamps
- **Job management**: Pause, resume, cancel operations
- **Broker badge display** and theme toggle
- **Date selector improvements** with Calendar component
- **Exchange market open time alignment** for candle boundaries

---

### Real-Time WebSocket Integration

- **Native WebSocket** for Holdings and Positions pages
- **Unified WebSocket proxy server** on port 8765
- **ZeroMQ message bus** for high-performance data distribution (port 5555)
- **Connection pooling**: MAX_SYMBOLS_PER_WEBSOCKET (1000) x MAX_WEBSOCKET_CONNECTIONS (3)
- **MultiQuotes API fallback** when WebSocket unavailable
- **Market timing awareness** for automatic data source switching
- **Real-time P&L calculation** using live LTP data
- **WebSocket templates** in Playground with Bruno-style collections
- **Multi-client subscribe/unsubscribe** support
- **Callback-based data retrieval** for Flow nodes
- **Pong message display** for manual ping testing

---

### Sandbox Mode (Sandbox Testing)

- **Isolated sandbox trading** with Rs. 1 Crore sandbox capital
- **Realistic margin system** with leverage
- **Auto square-off** at exchange timings for F&O contracts
- **Complete isolation** from live trading
- **Separate database** (sandbox.db) for sandbox trades
- **Real-time P&L** using WebSocket data
- **Session-based position filtering** for expired contracts
- **Expired F&O contract cleanup** on app startup
- **Sandbox logs** with date filter and Calendar icons
- **Wide dialog display** (98vw) for better visibility

---

### API Playground

- **Bruno-style API collection browser**
- **WebSocket testing console** with comprehensive controls
- **CodeMirror JSON editor** with syntax highlighting
- **Theme support** matching application theme
- **Manual ping/pong testing** for WebSocket connections
- **Multiple tabs** for endpoints with same path but different names
- **Nested braces handling** in body:json parsing
- **Source parameter** for History API collections

---

### Python Strategies

- **Enhanced scheduler** with mandatory scheduling
- **Real-time status updates** via SSE (Server-Sent Events)
- **Resource limits** to prevent runaway strategies
- **Python Strategy Guide page** with comprehensive help
- **FAQ for installing libraries** (TA-Lib, pandas-ta, etc.)
- **Log management** with configurable retention
- **Reverse chronological logs** with auto-scroll
- **Schedule box theme** with opacity-based dark mode colors
- **Holiday enforcement** for market-aware scheduling
- **Environment Variables feature removed** (security)

---

### Telegram Bot

- **Fixed /menu callbacks** for command navigation
- **Fixed /status display** for current position status
- **Flow Telegram alert integration** using existing send_alert_sync
- **Admin & Telegram modules** migrated to React

---

### Email & SMTP

- **Fixed SMTP email delivery**
- **Updated email templates**
- **Email icon centering** using table-based layout

---

### Action Center

- **Order approval workflow** for managed accounts
- **Semi-Auto mode** for manual approval
- **Auto mode** for direct execution
- **Complete migration** to React interface
- **Documentation** added (Module 42)

---

## Improvements

### User Interface
- Profile menu with mode controls on all pages
- Theme consistency across broker and public pages
- Theme sensitivity for dark/light mode switching
- Broker badge display across pages
- Chart icons in watchlist for smart navigation
- Responsive dialogs with optimized widths
- Mobile bottom navigation
- Accessible icon buttons with aria-labels

### Performance
- FNO Discovery performance optimization
- Historify storage optimization
- Code splitting and lazy loading
- Bulk watchlist add optimization
- Connection pooling for WebSocket

### Order Management
- P&L % calculation for flat positions using implied investment
- Show dash for P&L % on closed positions
- Preserved realized P&L for closed positions
- Position filtering for session boundaries
- Show closed positions that were traded today
- Expired F&O contract cleanup on startup
- Order field names aligned with OpenAlgo schema

### Broker Integrations
- AliceBlue holdings symbol field fix
- OAuth broker redirect improvements (AJAX vs browser detection)
- Broker login migrated to React JSON responses
- Updated lot sizes and expiry dates in Bruno collections
- Broker credentials GUI for easy configuration

### Charts
- TradingView-style x-axis labels for daily+ timeframes
- IST timezone correction for W/MO/Q/Y timeframes
- Dates instead of time for daily+ timeframes
- CodeMirror JSON editor on TradingView and GoCharting pages

---

## Security

- Fixed critical frontend vulnerabilities
- Removed environment variables feature from Python strategies
- Added resource limits for strategy execution
- Enhanced CSRF protection
- Security audit documentation added
- Dependency updates for known vulnerabilities

---

## Documentation

### User Guide (30 Modules)
- What is OpenAlgo, Key Concepts, System Requirements
- Installation Guide, First-Time Setup
- Broker Connection, Dashboard Overview
- Understanding Interface, API Key Management
- Order Types, Smart Orders, Basket Orders
- Positions & Holdings, Analyzer Mode
- Symbol Format Guide
- TradingView, Amibroker, ChartInk, GoCharting Integration
- Python Strategies, Flow Visual Builder
- Action Center, Telegram Bot
- PnL Tracker, Latency Monitor, Traffic Logs
- Security Settings, Two-Factor Authentication
- Troubleshooting, FAQs

### Architecture Documentation
- Frontend and Backend Architecture
- Login and Broker Login Flow (Module 03)
- Cache Architecture (Module 04)
- Security Architecture (Module 05)
- WebSockets Architecture (Module 06)
- Sandbox Architecture (Module 07)
- REST API Documentation (Module 09)
- Flow Architecture (Module 10)
- MCP Architecture (Module 41)
- Action Center (Module 42)

### API Documentation
- All REST endpoints documented
- OpenAlgo symbol format reference
- Manual testing guide
- Bruno collections for all APIs

### PRD Documents
- Sandbox PRD
- Python Strategies PRD
- Historify PRD
- Broker Factory Design
- WebSocket Guide
- Latency Audit

### Other Documentation
- Why Build with OpenAlgo guide
- Ubuntu Server deployment
- Docker deployment guide
- Security Policy
- Contributor guidelines for /frontend/dist

---

## Infrastructure

### Database Architecture (5 Databases)
- `db/openalgo.db` - Main database (users, orders, settings)
- `db/logs.db` - Traffic and API logs
- `db/latency.db` - Latency monitoring data
- `db/sandbox.db` - Analyzer/sandbox mode (isolated)
- `db/historify.duckdb` - Historical market data (DuckDB)

### Server Configuration
- React frontend served via Flask blueprint
- Pre-built frontend dist for community use
- System permissions monitoring for db directories
- Ngrok ERR_NGROK_108 fix in debug mode
- Prevented duplicate startup messages
- Password reset fixed for React migration
- Startup log noise reduced (DEBUG level)

### Docker
- Updated .dockerignore for React frontend
- Added db directory to permission commands
- Frontend documentation included

---

## Dependencies

### Python
- DuckDB 1.4.3
- PyArrow 22.0.0
- FastParquet 2025.12.0
- simple-websocket 1.1.0
- Python 3.12+ required

### Frontend
- React 19
- TypeScript 5.6
- Vite 6
- TanStack Query v5
- shadcn/ui components
- Tailwind CSS 4 + DaisyUI
- Biome.js
- Vitest + Playwright
- CodeMirror 6
- Socket.IO Client

---

## Breaking Changes

- Frontend routes served from React SPA
- Old Jinja2 templates removed completely
- Static folder cleaned up (React has all assets)
- API responses updated for React JSON format
- Broker login returns JSON instead of HTML redirects
- Environment variables feature removed from Python strategies

---

## Migration Guide

For users upgrading from v1.0.0.41:

1. **Backup your data**
   - Export databases before upgrading
   - Backup .env configuration

2. **Update environment**
   - Python 3.12+ required
   - Node.js 20+ for frontend development

3. **Install dependencies**
   ```bash
   uv sync                    # Python dependencies
   cd frontend && npm install # Frontend (for development only)
   ```

4. **Database migration**
   - Existing databases are compatible
   - New sandbox.db created automatically
   - New historify.duckdb created automatically

5. **Clear browser cache**
   - React frontend requires fresh load
   - Clear all cookies and cache for the domain

6. **Review breaking changes**
   - Update any custom integrations using old template routes
   - Update broker login handling if using custom flows

---

## Contributors

Special thanks to all contributors who made this release possible:
- @Kalaiviswa - Flow Visual Builder, React migration
- @akhandhediya - WebSocket Playground
- Community contributors and testers

---

## Previous Releases

### [1.0.0.41] and earlier

See [GitHub Releases](https://github.com/marketcalls/openalgo/releases) for previous version history.

---

## Links

- **Repository**: https://github.com/marketcalls/openalgo
- **Documentation**: https://docs.openalgo.in
- **Discord**: https://www.openalgo.in/discord
- **YouTube**: https://www.youtube.com/@openalgo
