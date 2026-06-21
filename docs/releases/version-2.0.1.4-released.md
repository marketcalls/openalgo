# Version 2.0.1.4 Released

**Date: 21st June 2026**

**Feature Release: Scalping Terminal (keyboard-driven order entry with a server-side SL/TP/TSL engine across all F&O exchanges, live candlestick/volume charts), the TradeSmart (Noren v2) broker integration, two new options tools (Gamma Density and OI Range), a /chart/test live multi-chart streaming page, technical-indicator research tools for the MCP server, F&O freeze-quantity correctness across every exchange, and a startup/runtime performance sweep (WAL SQLite, warm broker modules, deferred traffic-log purge)**

This release spans 90+ commits since v2.0.1.3. The headline feature is the **Scalping Terminal** (`/scalping`) — a keyboard-first order-entry surface with a server-side stop-loss / target / trailing-stop engine, full F&O exchange + segment coverage (NSE/BSE equity & futures, NFO/BFO/CDS/MCX options), live WebSocket-driven tickers and candlestick/volume charts, and freeze-quantity-safe exits. Alongside it ships the **TradeSmart (Noren v2)** broker integration, two new analytics tools — **Gamma Density** (Γ×OI density and convexity zones with forward-based Black-76 IV) and **OI Range** (open interest by strike for a custom range) — and a **/chart/test** page for live multi-chart streaming. The MCP server gains **technical-indicator research tools**, F&O **freeze-quantity handling** is corrected for CDS/MCX and BSE indices, and a **performance sweep** enables WAL on every SQLite connection, warms broker modules at startup, and purges traffic logs past their retention window off the hot path.

***

**Highlights**

* **Scalping Terminal (`/scalping`)** — A new keyboard-driven scalping surface, built up across phases:
  * **Order entry**: keyboard shortcuts for buy/sell/exit, NIFTY + current-week expiry + ATM defaults on load, `NRML` default product to avoid post-square-off MIS rejections.
  * **Server-side risk engine**: stop-loss, target and browser-driven auto-trailing move to a server-side SL/TP/TSL engine with analyze/live segregation, predefined auto SL & target, and book scoping so `F6` closes only the scalping strategy's positions.
  * **All F&O exchanges & segments**: option chain + expiry for every F&O exchange (NFO/BFO/CDS/MCX), futures by underlying + expiry, and a unified exchange/segment frontend including NSE/BSE equity & futures single-instrument views.
  * **Live data & charts**: WebSocket-live LTP with a MultiQuotes after-hours fallback, OHLC range visualization on the tickers, and live candlestick + volume charts on a shared timeframe.
  * **Freeze-safe**: exits never exceed exchange freeze limits, with whole-lot splitting on close and an unknown-freeze fallback.
* **TradeSmart (Noren v2) broker integration (#1548)** — New broker plugin on the Noren v2 stack, with a common broker-integration testing guide and an automated runner added alongside it.
* **Gamma Density tool (`/gammadensity`, #1553)** — Γ×OI density and convexity zones (Intraday and To-Expiry panels, ±1σ/±2σ expected-move bands, ATM IV) for all exchanges and underlyings. Index **weekly** options price off the per-expiry **synthetic future** as the Black-76 forward (monthly index / stocks use spot), fixing IV/Greeks alignment for weekly index options.
* **OI Range tool (`/oirange`)** — Open interest by strike for a custom strike range with ATM-relative quick selectors and optional 1-minute auto-refresh.
* **Chart Test page (`/chart/test`)** — Live multi-chart streaming page for validating real-time candlestick/volume rendering across instruments.
* **MCP technical-indicator research tools** — The MCP server gains indicator-calculation/research tools for use from Claude Desktop / Cursor / Windsurf.
* **F&O freeze-quantity correctness** — Freeze quantities now honored for **all** F&O exchanges including **CDS and MCX**, and **BFO** freeze quantities supported for SENSEX / BANKEX / SENSEX50.
* **Performance & startup sweep** — WAL + `synchronous=NORMAL` on every SQLite connection, broker modules warmed at startup with keep-warm pings, order hot-path logs demoted to debug across all 33 brokers, latency percentiles bounded to a 30-day window and cached, and traffic logs purged past their retention window at startup.
* **Platform version bump** — `2.0.1.3` → `2.0.1.4`. SDK pin (`openalgo`) `2.0.1` → `2.0.2`.

***

**Scalping Terminal — deep dive**

A keyboard-first scalping workflow delivered in phases (`c1c2923d` plan → `cba25cb7` hardening):

* **Plumbing & entry** — `a38d37df` (Phase 0: symbol/expiry/strike plumbing + live tickers), `358b0eef` (Phase 1: keyboard order entry, sandbox-ready), `97d9426f` (NIFTY + current-week expiry + ATM defaults), `11853ca4` (default product `NRML` to avoid MIS post-square-off 400s).
* **Risk engine** — `f3e390c0` (Phase 2: stop-loss + browser-driven auto-trailing), `4a7e56ba` (server-side SL/TP/TSL engine, analyze/live segregation, all-underlyings), `2594d16e` (predefined auto SL & target, WebSocket-driven, book scoping), `626e1d2f` (rate-limited trailing-SL writes + cached mode lookup), `cba25cb7` (drop stale mode cache; guard SL exit against mode toggle).
* **Exchanges & segments** — `f066564c` (Phase A: option chain + expiry for all F&O exchanges), `2b95004a` (Phase B: unified exchange/segment frontend), `b9e9aa4d` (futures by underlying + expiry), `20ab79d9` (MCX/CDS exchanges + 1cliq control-row), `3baabc2f` (NSE/BSE equity & futures single-instrument view).
* **Live data & charts** — `7be6bf00` (WebSocket-live LTP with MultiQuotes after-hours fallback), `1bcd3fb2` (OHLC range on tickers), `0e56b9de` (live candlestick + volume charts on a shared timeframe), `db516b84` (structure-only option chain + event-driven order updates for lower latency).
* **Freeze-safety & correctness** — `787ba14e` (whole-lot freeze split on close), `d31efa1f` (exits never exceed freeze limit, unknown-freeze fallback), `71a61ca9` (`F6` closes only the scalping strategy's positions), `af6751d2` (trust positionbook for net qty so closed legs aren't phantom-open), `c4c5523c` (coerce string position/trade numerics so live mode doesn't crash), `a8363edc` (CDS 4-decimal precision and live charts when the broker has no history).
* **Hardening** — `45ebd799` and `30ec6617` (security + correctness review fixes: SL exit safety, server lot cap), `6f5a9e2d` (stop Socket.IO reconnect churn + live-mode order apikey), `6b8fbf4e`/`6b2c4c00` (de-duplicate order notifications + trader-friendly errors), `7186446a` (share one Socket.IO connection per tab — fixes multi-tab hang).

A new `database/scalping_db.py` table persists scalping strategy/SL state; it is created automatically.

***

**TradeSmart (Noren v2) — deep dive**

`feat: add TradeSmart (Noren v2) broker integration` — `71359747`, merged via PR #1548.

* New broker plugin following the standard `api/`, `mapping/`, `database/`, `streaming/`, `plugin.json` layout on the Noren v2 stack.
* Data-API throttling: `7c65b839` caps the data API at 120 requests/min with retry on rate-limit responses.
* `test: add common broker-integration testing guide + automated runner` — `3c67f7dc` adds a reusable broker test harness used to validate the integration.

***

**Options tools**

* **Gamma Density** (`44a7fe50`, PR #1553) — `services/gamma_density_service.py` reuses the option chain for OI + LTP and computes per-strike gamma via `opengreeks` Black-76 for two horizons (intraday 1-day and full to-expiry), returning Γ×OI density plus daily/to-expiry ±1σ/±2σ expected-move bands. Index weekly options use the per-expiry synthetic future as the Black-76 forward; the expected-move band and Spot marker stay on cash spot.
* **OI Range** (`dc05c7ac`) — open interest by strike for a custom range, with ATM-relative quick selectors (5/10/15/20 strikes each side) and optional 1-minute auto-refresh.
* **Chart Test** (`e745e319`) — `/chart/test` live multi-chart streaming page; `59d41f35` adds the explicit `/scalping` route to `react_app.py`.

***

**Broker fixes**

* `71359747` — **TradeSmart**: new Noren v2 broker integration (#1548).
* `64d58909` — **Arrow**: multiquotes made resilient and diagnosable.
* `26fb5e3f` — **5paisa**: market orders via MPP, smart-order auth fix, historical candles for index symbols, WebSocket FD/thread leak fixes in the reconnect path, hardened reconnect (ping timeout, interruptible backoff, race), batched WS subscriptions (#1524); `b707dc99` — real intraday history timestamps + review fixes.
* `1c93aeaf` — **Dhan**: stop dropping 90-day intraday chunks on weekend boundaries (#1517).
* `119f8012` — **Definedge**: anchor intraday history end-time to IST so data doesn't lag on non-IST hosts.
* `4c816c83` — **Firstock**: map `BSE_INDEX` to `BSE` in quote/depth/history paths.

***

**Freeze quantities**

* `e087866c` — honor freeze quantities for all F&O exchanges, including **CDS** and **MCX** (#1541 family).
* `55184509` — support **BFO** freeze quantities for SENSEX / BANKEX / SENSEX50.

***

**Performance & reliability**

* `7b7505af` — enable WAL + `synchronous=NORMAL` for all SQLite connections.
* `3ec2084e` — warm broker modules at startup with fast-start keep-warm pings.
* `9f94a857` — demote order hot-path logs to debug across all 33 brokers.
* `4e0154cc` — bound latency stats percentiles to a 30-day window and cache the result.
* `d221c9cd` — purge traffic logs past the retention window at startup (`TRAFFIC_LOG_RETENTION_DAYS`).
* `db516b84` — structure-only option chain + event-driven order updates (scalping).

***

**WhatsApp / messaging**

* `2259ade6` — marshal `wars` callbacks off the eventlet hub to prevent freezes (#1515).
* `eedbed45` — bump `wars` to 0.1.4 (PN→LID delivery) and fix the `on_disconnect` crash (#1512).

***

**Other fixes**

* `61985786` — **Playground**: redirect legacy `/playground/` instead of returning 500 (#1526).

***

**Security**

* `c8517646` — patch Dependabot security advisories (`fix/dependabot-security-bumps`, #1535).

***

**Documentation**

* `c1b0a168` … `5324469d` — Flask→FastAPI migration plan, risk assessment, and a 63-item migration tracker CSV (assessment only; no runtime change).
* `c1c2923d`, `664cb548`, `4d4e5311` — scalping terminal implementation plan + sandbox order-lifecycle validation.
* `2677dd8c` — group indicator prompt docs into `docs/prompt/indicators/` (#1529).
* `ae6f0224` — add the current OpenAlgo PRD.

***

**Dependencies**

* `openalgo` SDK pin: `2.0.1` → **`2.0.2`** (PyPI: <https://pypi.org/project/openalgo/>).
* `opengreeks` `>=0.2.0` (unchanged).

***

**Configuration changes**

`utils/version.py`: `VERSION = "2.0.1.4"`

`pyproject.toml`: `version = "2.0.1.4"`; `openalgo==2.0.2` (`uv.lock` regenerated).

`.sample.env`:

* `VALID_BROKERS` gains `tradesmart`.
* New **optional** variable `TRAFFIC_LOG_RETENTION_DAYS='30'` — days to retain request traffic logs in `logs.db` (purged at startup; default applies if absent, no action required).

**Database**: a new `scalping_db` table backs the Scalping Terminal's strategy/SL state. It is created automatically on startup — no manual migration required.

***

**Upgrade procedure**

**For existing installs (Native Ubuntu):**

```bash
cd /var/python/openalgo-flask/<deploy-name>/openalgo
sudo ./install/update.sh
```

**For existing installs (Docker):**

```bash
cd /opt/openalgo/<domain>
sudo docker compose pull
sudo docker compose up -d
```

**For local developers (uv):**

```bash
git pull origin main
uv sync
# Frontend: a plain pull already ships the CI-built dist. Only rebuild if
# you are editing React code:
cd frontend && npm install && npm run build
uv run app.py
```

***

**Contributors**

* **@marketcalls (Rajandran)** — release management; Scalping Terminal (keyboard order entry, server-side SL/TP/TSL engine, all-exchange option chain/futures, live charts, freeze-safe exits, hardening); Gamma Density and OI Range tools; Chart Test live-streaming page; MCP technical-indicator research tools; F&O freeze-quantity fixes (CDS/MCX/BSE indices); WAL/startup/latency performance sweep; WhatsApp eventlet-hub and `wars` fixes; SDK pin bump.
* **@Kalaiviswa** — TradeSmart (Noren v2) broker integration (#1548); Arrow multiquotes resilience; 5paisa market orders/smart-order/WS-reconnect overhaul (#1524) and intraday timestamp fixes; Firstock `BSE_INDEX`→`BSE` mapping; Definedge intraday IST anchoring.

***

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Python SDK on PyPI**: <https://pypi.org/project/openalgo/>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>
