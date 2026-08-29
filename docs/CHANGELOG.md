# Changelog

All notable changes to OpenAlgo will be documented in this file.

Each release adds a stanza here summarising what changed and who contributed.
The full notes for a release, with commit SHAs and the reasoning behind each
fix, live in [docs/releases](releases/).

## [2.0.2.2] - 2026-08-29

### Stability and Security Release

143 commits since 2.0.2.1. Full notes: [version-2.0.2.2-released.md](releases/version-2.0.2.2-released.md).

---

### Highlights

- **The eventlet boundary closed** - the "first order works, next one hangs the app" reports (#1402, #1473, #1569) were four defects: a real thread contending on a green lock, a green logging handler lock, `PRAGMA busy_timeout` waiting inside C while holding the hub, and `run_coroutine_threadsafe` never waking its caller
- **Broker credentials swept out of the logs** - 73 bare `logging.getLogger()` call sites bypassing redaction across 30 plugins, credentials interpolated into messages in 12 plugins, 35 sites leaking a secret inside a URL, payload, headers dict or exception message, and a defect in the `Bearer` pattern itself
- **Dhan symbol mapping routed orders to the wrong instrument** - 8,642 security ids resolved to two contracts each, and equity symbols ignored `SEM_SERIES` so an order could reach a warrant (#1929, #1930)
- **User chart indicators, loaded at runtime** - drop a `.js` file in `strategies/indicators/` and it appears in the `/trading` picker. No build step, no Node.js, no restart (#1923)
- **Motilal Oswal repaired and modernised** - every endpoint on its documented version, smart orders that can see a position, and four WebSocket leaks closed (#1912)
- **GTT extended to Angel One, Fyers and Upstox** (#1922)
- **Flow nodes stop acting on data they do not have** - conditions answered on failed broker reads, an errored condition settled a gate into a real order, and `httpRequest` had two injection paths
- **A fresh install clones 20 MB instead of 276 MB** - 165 MB of committed compression artifacts removed and all clone paths made partial (#1896, #1897, #1898)

---

### New Features

- User chart indicators in `strategies/indicators/*.js`, served by `blueprints/custom_indicators.py` and loaded after the built-in tier, with in-browser validation (#1923)
- Charting terminal: market replay, a settings dialog rendered from the engine schema, chart sync groups, a warm-load history cache, drawing undo and redo, and an indicator browser with categories, favourites and recents
- GTT order support for Angel One, Fyers and Upstox, each registering itself by shipping `api/gtt_api.py` plus `mapping/gtt_data.py` (#1922)
- Every Flow order field accepts a `{{reference}}`, not just `symbol`
- Flow schedule trigger exposes its market-hours window and calendar exchange; interval schedules anchor to the clock with `FLOW_INTERVAL_ALIGN_OFFSET`
- Flow supports MCX commodity options and leg-by-leg multi-leg baskets (#1904)
- Flow defaults to NRML on NFO, BFO, CDS, BCD, MCX, NCDEX and NCO rather than storing MIS on every node (#1909)
- TradeSmart tags placed orders as `openalgo` and gives quotes their own 100/sec budget (#1928)
- Motilal Oswal order-update WebSocket adapter, bringing `_BROKER_FACTORIES` to 17 (#1912)
- `chart-indicator`, `flow-builder` and `verify` skills

### Stability Fixes

- Four eventlet boundary crossings fixed via `utils/real_threading`, `Handler.createLock` patching, a green-thread callback drain and a Python-side SQLite lock retry (#1402, #1473, #1569)
- Subscribe acks resolve immediately instead of waiting out a 12-second timeout; proxy error replies now echo `request_id`
- Motilal Oswal: market-data socket pooled per session, cold-start registration race, duplicate poll threads and unbounded tick caches (#1912)
- Dhan `unsubscribe()` reaches the broker instead of only clearing local tracking; `dhan_sandbox` stops sending the invalid `RequestCode: 0` (#1924)
- A silent feed logs at debug rather than warning every two minutes outside market hours
- Test suite database isolation no longer depends on module import order

### Security Fixes

- Broker loggers routed through `get_logger` so `SensitiveDataFilter` applies: 73 call sites in 60 files across 30 plugins
- Credential values removed from log messages in 12 plugins, and from URLs, payloads, headers dicts and exception messages at 35 sites in 15 plugins (#1854, #1855)
- `SensitiveDataFilter` Bearer pattern extended to composite credentials, `cookie` added to the key alternation, and `utils/logging.py` given its first tests
- `CORS_ENABLED=FALSE` disables CORS instead of falling through to the flask-cors `origins="*"` default; the enabled-but-unconfigured case fails closed (#1848)
- Client error reports no longer persist a reset-password token or broker OAuth code into `log/errors.jsonl`, sanitized on both boundaries (#1851)
- The frontend fails a mutating request rather than sending it with no CSRF token
- Password login clears the session before writing any authenticated value

### Platform Fixes

- Option resolver validates the strike interval and option type, so a `strike_int` of 0 or an option type of "CALL" is refused rather than returning the put strike (#1829)
- Sandbox position book, MIS square-off and T+1 settlement boundaries resolved in the database clock rather than naive local time (#1789, #1801)
- Sandbox serializes concurrent same-symbol position updates (#1808)
- An out-of-range `SESSION_EXPIRY_TIME` falls back rather than silently disabling the MIS square-off
- `get_history()` rejects an unsupported source at the entry point (#1826); market calendar helpers return 400 for a non-string date (#1824)
- Multi-option Greeks batch state keyed by leg index (#1819)
- Frontend rate limiter expires calls at the window boundary (#1830)
- Navigation links declare `aria-current="page"` (#1833)
- Frontend compression artifacts generated at startup rather than committed, and all install paths use `--filter=blob:none` (#1896, #1897, #1898)
- Ten routine startup log lines moved from INFO to debug
- CI runs `backend-test` on Python 3.12, 3.13 and 3.14 and the frontend jobs on Node 20, 22 and 24 (#1894)

### Flow Fixes

- `priceCondition`, `positionCheck` and `fundCheck` check the broker response status, so a 401 no longer reads as LTP 0.0 with `status: success`
- An errored condition leaves its gate pending instead of settling it to `False` and driving a real order
- A condition reachable by two paths runs once; gates honour `inputCount`
- `timeWindow` crosses midnight; `waitUntil` over 30 minutes points at a schedule trigger
- Websocket subscriptions are tracked per workflow and released on deactivate or delete; a specific-mode `unsubscribe` no longer falls through to `unsubscribe_all`
- `httpRequest` resolves its URL once and after parsing, closing two injection paths
- Broker rejections surface their real reason instead of "node failed"
- Import format docs corrected on gate wiring, `marketHoursOnly`, `days`, strike offset ranges and `optionsMultiOrder.strategy`

### Broker Fixes

- Dhan: master contract gated on `SEM_SEGMENT`, NSE segment M mapped to NCO, symbols built from `SEM_SERIES` and `SEM_STRIKE_PRICE`, `securityId`-first position matching, and the inverted INTRADAY reverse mapping. **Breaking: 7,190 NSE equity symbols gain a series suffix** (#1929, #1930, #1932)
- Shoonya: `GetQuotes` refuses a quote echoing a different instrument, measured at 9% of replies on the live API (#1904)
- Angel and Zerodha: holdings return LTP and average price, and one null row no longer fails the whole call (#1917, #1919)
- Flattrade: pledged holdings reported as collateral from the `collateral` field rather than `brkcollamt` (#1936)
- Motilal Oswal: endpoints on their documented versions, correct API key and secret convention, client code persisted from the TOTP page, smart orders matching on `symboltoken` (#1912)

### Documentation

- Broker plugin counts synchronised to 36 across 17 files, the FAQ, the devsprint guide and the design docs (#1844, #1906, #1910)
- Documentation-only contribution workflow (#1846), completed CONTRIBUTING table of contents (#1883), contributor test commands aligned with CI (#1841), corrected frontend build and Node guidance (#1842), obsolete `/react` routes replaced (#1840)
- The eventlet boundary rules recorded in CLAUDE.md, both directions, with the threads that are genuinely real named
- Sandbox margin PRD states that short options are not SPAN margined (#1795)

### Dependencies

- `openalgo-charts`: **1.6.0** to **1.8.2**, pinned exactly rather than with a caret
- `zmq==0.0.0` removed from all three dependency lists: a placeholder package shipping no code, with `pyzmq` already pinned (#1895)
- No other Python dependencies changed; the pinned `openalgo` SDK stays at 2.0.3

### Contributors

- **@marketcalls (Rajandran)** - release management; eventlet boundary sweep and regression suites (#1402, #1473, #1569); broker credential redaction across 30 plugins; Dhan master contract, symbol construction, NCO and unsubscribe (#1929, #1930, #1932, #1934); runtime-loaded chart indicators (#1923); charting terminal 1.6.0 to 1.8.2 with replay, settings, sync, history cache and the indicator browser; Flow node-contract audit, payload-driven order fields and clock-anchored schedules; sandbox clock boundaries; Flattrade collateral (#1936); repository size work (#1896, #1897, #1898); Motilal Oswal WebSocket pooling; CI version matrix (#1894); test isolation; three new skills
- **@Kalaiviswa** - Motilal Oswal plugin repair (#1912); GTT for Angel One, Fyers and Upstox (#1922); Angel and Zerodha holdings (#1917, #1919); Dhan PRs (#1932, #1934); TradeSmart tagging and quote budget (#1928); Flow MCX options, multi-leg baskets and NRML defaults (#1904, #1909); Shoonya wrong-instrument quote guard
- **@santhiprakash (Santhi Prakash)** - sandbox position-book session boundary (#1789), MIS square-off boundary (#1801), concurrent position updates (#1808), Historify index cleanup (#1803)
- **@siddharthg2309 (Siddharth Gouthaman)** - history source allowlist (#1875), client error URL sanitization (#1886), `aria-current` navigation (#1880), option chain view mode coverage (#1876)
- **@solstxce** - API key redaction in core service logs (#1914), credential removal from broker logs (#1916)
- **@nightcityblade** - client errors for invalid calendar dates (#1861), CONTRIBUTING table of contents (#1883)
- **@WilliamK112 (Ching Wei Kang)** - documentation-only contribution workflow (#1907), rate limiter window boundary (#1868)
- **@ANONYMOUSZED-beep (Arun)** - `CORS_ENABLED=FALSE` honoured (#1860)
- **@Narasimha722 (NarasimhaReddy)** - option resolver strike interval and option type validation (#1829)
- **@Pragitics (Pragit R V)** - multi-option Greeks batch state by leg index (#1885)
- **@Meraj-08 (Md Meraj Alam)** - contradictory broker plugin counts eliminated (#1906)
- **@K-PRAGALATHAN (PRAGALATHAN K)** - history format script converted to pytest coverage (#1887)
- **@NavadeepDj (NavadeepDJ)** - type hints for the data schema validators (#1864)
- **@suhaslord (Suhas)** - contributor test commands aligned with CI (#1889)
- **@thaildhe172591 (Luu Thai)** - frontend build-artifact and Node guidance (#1863)
- **@yiheng-kkk** - obsolete frontend routes replaced (#1867)
- **@PadmaBalajiL (Padma Balaji Leelavinodhan)** - devsprint participants (#1814)
- **@cracker314** - devsprint participants (#1817)

---

## [2.0.2.1] - 2026-08-21

### Flow Release

25 commits since 2.0.2.0. Full notes: [version-2.0.2.1-released.md](releases/version-2.0.2.1-released.md).

---

### Highlights

- **Flow QA audit remediation** - one production QA audit and three re-audits validated finding by finding against source, then closed across triggers, the scheduler lifecycle, execution reporting, node contracts, the editor, the import format and the generated documentation
- **Logic gates repaired** - a `False` input never reached an AND/OR/NOT gate, so OR behaved like AND, NOT could never fire, and the result depended on traversal order
- **The editor stopped losing work** - a failed fetch rendered a blank canvas that the next save wrote over the real graph, clicking Activate discarded unsaved edits, and a save race let Run Now execute a revision the user was no longer looking at
- **Typed fields replace hand-written JSON** on the Indicator and Margin Calculator nodes, with Margin gaining a leg editor and lot-based quantity
- **Order nodes fail on unresolved variables** instead of placing a successful order for the wrong size at the wrong price type
- **Charting terminal: 20 to 91 built-in indicators** across `openalgo-charts` 1.1.0 and 1.2.0, with search in the indicator menu
- **The endless "Loading new version" reload loop** ended, along with the unsafe `Vary`-less asset representations behind it
- **Migrations got the app's 15-second SQLite lock timeout**, which they had never had

---

### New Features

- Flow Indicator node renders each indicator's real parameters as typed fields, generated from the `openalgo.ta` signatures
- Flow Margin Calculator gains a repeatable leg editor with lot-based quantity for NFO and BFO, backed by a batched `POST /flow/api/symbol-lotsizes`
- Flow execution history is bounded by `FLOW_EXECUTION_RETENTION_COUNT` (500) and `FLOW_EXECUTION_RETENTION_DAYS` (30)
- `reconcile_scheduler_jobs()` and `restore_price_alerts()` run at startup, so Flow triggers survive a restart and stale jobs are cleared
- Charting terminal indicator menu has a search box, filtering on display name and id
- `GET /python/api/exchanges` serves session windows from the market calendar DB
- Home page "One platform, many desks" section, with counts read from the code
- Devsprint contributor prep guide (#1804)

### Flow Fixes

- Price Alert node evaluates the editor's own condition vocabulary; a monitor-fired run carries the trigger price rather than re-fetching a quote
- Condition results are delivered into logic gates instead of being filtered by the branch taken
- Condition nodes return an error rather than a substituted `false`; `timeCondition` keeps its seconds
- Order-defining fields are checked for unresolved `{{references}}` before the broker call
- Modify Order reads the live order and changes only what was supplied; its editor default no longer ships exchange and action
- Close Positions honours its symbol/exchange/product filter; HTTP Request parses headers, supports PATCH, reads a millisecond timeout capped at 60s and refuses non-http(s), loopback, private, link-local and reserved destinations
- Fund Check and Position Check fail closed; Delay is capped at 300s
- One-shot triggers are spent only when the workflow actually ran, and clear `is_active` when consumed
- Duplicate-run guard is an atomic try-acquire; a node returning error stops its branch and marks the run failed
- Activation persists before registering and rolls back on failure; the API key is no longer pickled into the jobstore
- Output variable names on nine node types are persisted rather than shown as a fallback
- Basket Order and Margin node subtitles count the fields the editor actually writes
- `flow_workflows.api_key` migration ships for existing installations; `create_execution` stamps `started_at` and history orders by id
- Both Flow monitors release their pools, threads and bus subscription at exit
- Webhook lookups cache the workflow id rather than a detached ORM instance; secret rotation evicts the cache

### Platform Fixes

- Endless "Loading new version" reload loop, and `/assets/<file>` serving three representations of one URL with no `Vary` header (#1807)
- Forced upgrade header removed from `change-domain.sh` and the Ubuntu server design doc sample (#1807)
- Migrations use the same `PRAGMA busy_timeout=15000` as the app, via `upgrade/_pragmas.py` (#1726)
- `/api/v1/telegram` write endpoints repaired and `/notify` gated (#1577)
- MCP loopback health probe honours `MCP_LOOPBACK_URL` (#1441)
- Order latency recorded for routes outside the RESTX API (#1805)
- `/python` schedule prefill no longer cuts NFO and BFO strategies off ten minutes early

### Broker Fixes

- TradeSmart: WebSocket lifecycle aligned with its Noren siblings, interruptible heartbeat, close frames told from faults, rate limits corrected to 10/sec and 120/min, bulk quotes served from the WebSocket feed (#1805, #1802)
- Delta Exchange: the pooled feed stays alive after the last unsubscribe, so an option chain keeps delivering ticks across an expiry or strike change (#1799)

### Dependencies

- `openalgo-charts`: **1.0.29** to **1.2.0** (20 to 91 built-in indicators, VWAP and CPR session anchoring, frontend only)
- No Python dependencies changed

---

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
