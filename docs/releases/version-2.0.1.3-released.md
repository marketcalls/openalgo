# Version 2.0.1.3 Released

**Date: 11th June 2026**

**Feature + Performance Release: Arrow Broker Integration (edge.arrow.trade, Full REST + Binary WebSocket Streaming), Order Hot-Path Latency Overhaul (Idle-Gap Orders ~150ms → ~15ms via Connection Keep-Warm, Zero Inline fsync on the Order Path), Broker-Token Daily-Rollover Resilience (WS Self-Heal + Session Kept Intact), an FD/Resource-Leak Audit, the Vite 8 Frontend Toolchain, and a Crypto/Security Hardening Sweep**

This release spans 80+ commits since v2.0.1.2. The headline feature is the **Arrow broker integration** (PR #1494) — a complete REST + WebSocket implementation for edge.arrow.trade covering orders, smart orders, single and basket margin, master contract, quotes/depth/historical data, and a binary market-data stream parser. The headline performance work is an **order hot-path latency overhaul**: a new connection keep-warm service eliminates the ~150ms TCP+TLS handshake that orders paid after idle gaps (verified live: ~150ms → ~15ms broker RTT), and every inline SQLite commit is moved off the order response path. Reliability work makes the **daily ~3:00 AM IST broker-token rollover** a non-event: WebSocket adapters refresh tokens and self-heal on reconnect, and an expired broker token now flags the session for re-authentication instead of destroying it. The codebase also gets a **file-descriptor/resource-leak audit** with fixes and an enforced NullPool engine factory, the frontend moves to **Vite 8** with precompressed assets, and crypto startup validation is hardened.

***

**Highlights**

* **Arrow broker integration (#1494)** — New broker plugin for **Arrow (edge.arrow.trade)** supporting NSE, BSE, NFO, BFO, CDS, BCD, MCX and index quotes. Full implementation: token authentication, place/modify/cancel/smart orders, Dhan-style single + basket margin routing, master contract rebuilt from the live instrument CSV, REST quotes/multiquotes with batch capping, and full binary quote/depth parsing on the market-data stream. Hardened post-merge with live-trading review fixes and a position cache for smart-order flows.
* **Order latency overhaul** — Three changes verified with live orders:
  * **Connection keep-warm** (`services/broker_keepalive_service.py`): the shared httpx pool recycles idle connections after 30s, so any order after a longer gap paid a fresh TCP+TLS handshake — measured ~150ms vs ~15ms warm. A daemon thread now HEAD-pings the active broker's API origin every 20s during market hours through the same pooled client, so every order finds a warm connection.
  * **Zero inline fsync on the order path**: the latency record and traffic log commits (previously synchronous SQLite fsyncs before the HTTP response) now run on background single-worker executors; the per-request IP-ban query and per-order order-mode query are cached with explicit invalidation, so enforcement semantics are unchanged.
  * **Honest measurement**: the API Playground previously included its CSRF-token round trip in the displayed response time, reading 10-40ms high; the timer now covers only the actual request.
* **Broker-token rollover resilience (#1419, #1226, #1421, #1453, #1468)** — WebSocket adapters read a fresh auth token on every (re)connect and self-heal on Zerodha auth failures; the broker token is revoked at the daily session rollover so the next morning's WS comes up clean; the data-stall watchdog is fed from ping/pong so it stops false-firing; Socket.IO heartbeats relax to engine.io defaults to stop reconnect loops; depth packets route to LTP consumers.
* **Session UX on token expiry** — An expired broker token no longer logs you out of OpenAlgo: the session stays intact, the UI flags the stale token and offers a re-authentication path, and login resume requires a valid broker session.
* **FD/resource-leak audit** — A full file-descriptor audit (documented in `docs/`), two leak fixes (FD-5, FD-6), and a shared `database/engine_factory.py` that enforces NullPool for every SQLite engine project-wide.
* **Vite 8 frontend toolchain** — Migration completed (the attempt reverted in v2.0.1.2 now lands cleanly), with precompressed assets + vendor chunk splitting for faster page loads, Plotly compatibility fixes for `/tools` pages, zero Biome lint warnings, and stabilized e2e waits.
* **Security hardening** — `APP_KEY` is validated at startup instead of silently allowing `None`; SMTP key derivation strengthened and weak pepper fallbacks removed; first-run secret rotation now persists through Docker bind-mounted `.env`; `starlette` bumped 0.52.1 → 1.0.1 and `react-router`/`vitest` CVEs patched.
* **Platform version bump** — `2.0.1.2` → `2.0.1.3`. SDK pin (`openalgo`) `1.0.51` → `2.0.1`, `opengreeks` `0.1.0` → `0.2.0`.

***

**Arrow broker — deep dive**

`feat(broker): add Arrow (edge.arrow.trade) broker integration` — `6f2be4a6`, merged via PR #1494 (`9af53e2f`), followed by six hardening commits.

* **Auth**: token authentication against `https://edge.arrow.trade` with corrected `authenticate-token` request field names (`1060bf71`).
* **Orders**: place, modify, cancel, cancel-all, close-position and smart orders following the Zerodha reference algorithm, with a 1-second position cache to prevent N+1 position fetches when multiple smart orders queue.
* **Margin**: single + basket margin routing modeled on the Dhan implementation (`212d37c9`).
* **Master contract**: rebuilt from Arrow's live instrument CSV with correct price/strike scaling (`e0d3dba9`).
* **Market data**: REST quotes/multiquotes with symbol resolution and batch capping (`7352ad50`); the WebSocket adapter parses Arrow's binary quote and depth frames natively (`6413905a`).
* **Post-merge hardening**: live-trading review findings addressed (`776f00ed`); lessons captured in the broker-integration docs (`b13c2fb5`).

***

**Order latency — deep dive**

Measured end-to-end with live NHPC MIS MARKET orders on Arrow:

| Stage | Before | After |
| --- | --- | --- |
| Order after >30s idle gap (handshake) | ~150ms broker RTT | ~15ms broker RTT |
| Inline SQLite commits before response | 2 (latency.db + logs.db) + 2 hot-path DB queries | 0 commits, both queries cached |
| Warm platform overhead | 3-4ms (plus hidden write time) | 2.9-4.1ms, nothing hidden |

* `perf(latency): move order hot-path DB writes off the request thread` — `55244799`. The latency record and traffic log now commit on shared single-worker executors after the response is sent; worker threads remove their scoped sessions so no SQLite read transaction is left open. The IP-ban verdict is cached per IP (60s TTL, invalidated on ban/unban so enforcement stays immediate) and the per-order `order_mode` lookup is cached (invalidated by `update_order_mode`).
* `feat(broker): keep the pooled broker HTTP connection warm in market hours` — `e6af52f6`. New env-configurable service; the deliberate `keepalive_expiry=30s` pool setting is untouched, so genuinely stale connections still recycle outside trading hours. Brokers expose their API origin via `broker/{name}/api/baseurl.py`; brokers without one are skipped.
* `fix(playground): exclude CSRF token fetch from displayed response time` — `66e220f1`.
* `perf(arrow): demote order hot-path payload/response logs to debug` — `c8bd25ba`. Console writes from the order path cost real milliseconds on Windows terminals; payloads remain visible under `LOG_LEVEL=DEBUG`.

***

**WebSocket + session reliability**

* `340010ca` / `c3564cc8` — broker WS adapters refresh the auth token on every (re)connect and self-heal Zerodha auth failures (#1419, #1226, #1421).
* `3f167e23` — broker token revoked at daily session rollover, fixing the dead-WS-next-morning symptom (#1419).
* `fd026bed` — data-stall watchdog fed from ping/pong frames so idle-but-healthy feeds stop false-firing (#1419).
* `8d913b74` — Socket.IO heartbeat relaxed to engine.io defaults, stopping reconnect loops (#1419).
* `b9154f66` — depth packets route to LTP-mode consumers (#1453, #1468).
* `f69cb587`, `fa0b90a3`, `5e3f5f0e` — broker-token expiry no longer destroys the app session: the session-status endpoint flags instead of downgrading, and the UI offers a re-authentication path.
* `efc589b8` — login resume requires a valid broker session.
* `09729eaf` — Health Monitor page shows WebSocket connection details again.

***

**FD / resource-leak audit**

* `c2e46bc6` + `190c6652` — full file-descriptor/resource-leak audit documented, with cross-review corrections.
* `8e297e62` — FD-5 and FD-6 leaks fixed.
* `7d59a62c` — `database/engine_factory.py` enforces NullPool for every SQLite engine, including all broker `master_contract_db.py` modules.
* `1feb07bf` — FD-hygiene workflow added to the contributor instructions.

***

**Frontend**

* `29d93244` — toolchain migrated to **Vite 8** (with lockfile syncs `af9749a3`, `f8ca2245` and e2e stabilization `95dd2fb1`).
* `734ddd85` — assets precompressed (gzip + brotli) at build time and the vendor chunk split for faster page loads.
* `e92fbeff` + `74861b38` — Plotly `/tools` pages fixed under Vite 8 (`global=globalThis`, react-plotly CJS factory unwrap).
* `d2abfb3e` + `0eb6d1d6` — reusable EmptyState component replaces plain-text empty states (#1484).
* `7d497ac3` — orderbook gets a sortable Price column and per-instrument price grouping.
* `82d4b8b9` — navbar fits portrait monitors and small laptops; `c7abd7b8` — Leverage menu gated by broker capabilities.
* `b29fa579` + `ce678e40` — Reset Password TOTP input shows a numeric keypad and keeps its 6-digit pattern (#1478).
* `46338586` — zero Biome lint warnings; `204f3ac8` — Dhan/Zerodha broker notice readable in light theme.

***

**Broker fixes**

* `cb1b08bc` — **Dhan**: null symbol/exchange in positions no longer crashes the UI (#1463, #1477).
* `bbac66d1` — **Dhan**: data-API rate limit split by endpoint class (#1476).
* `7583b8b3` — **Dhan**: baskets use the multi-margin calculator.
* `f5451bab` — **Definedge**: historical data date range corrected (#1475).
* `4dc48eb0` + `8963407d` — **Indmoney**: master-contract CSV NaN crash resolved (#1427) and `update_status` calls match the real signature.
* `ef6e8cbc` — Strategy Builder handles expired multi-option Greeks.
* `b4a80e25` — Python Strategy host hardens restored-process lifecycle.

***

**Security**

* `624dbe9b` — `APP_KEY` validated at startup instead of allowing `None`.
* `02087959` — SMTP key derivation strengthened; weak pepper fallbacks removed.
* `0cd5979c` — first-run secret rotation persists through Docker bind-mounted `.env` (#1337 family).
* `663c3d8c` — `starlette` 0.52.1 → 1.0.1 (Dependabot advisory).
* `8811fec7` — `react-router` and `vitest` CVE patches.
* `b1bd779a` — loopback HTTP health-check false alarm fixed on native Ubuntu installs.

***

**Dependencies**

* `openalgo` SDK pin: `1.0.51` → `2.0.0` → **`2.0.1`** (PyPI: <https://pypi.org/project/openalgo/>).
* `opengreeks` `0.1.0` → `0.2.0`.
* `starlette` `0.52.1` → `1.0.1`.
* Frontend toolchain: `vite` 7 → 8; `react-router` / `vitest` security bumps.

***

**Configuration changes**

`utils/version.py`: `VERSION = "2.0.1.3"`

`pyproject.toml`: `version = "2.0.1.3"`; SDK and dependency pins as above (`uv.lock` regenerated).

`.sample.env` — three new **optional** variables (defaults apply if absent; no action required):

* `BROKER_CONNECTION_KEEPALIVE='TRUE'` — enable/disable the broker connection keep-warm service
* `BROKER_KEEPALIVE_INTERVAL='20'` — seconds between keep-warm pings (keep below the 30s pool expiry)
* `BROKER_KEEPALIVE_WINDOW='09:00-23:30'` — IST window (Mon-Fri) covering NSE/BSE through the MCX close

`VALID_BROKERS` gains `arrow`.

There are **no database schema changes** in this release.

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

* **@marketcalls (Rajandran)** — release management; Arrow broker integration (#1494) with auth, orders, margin, master contract, binary streaming and post-merge hardening; order hot-path latency overhaul (keep-warm service, deferred DB writes, hot-path caches, playground timing fix); broker-token rollover and session-intact fixes; Vite 8 migration with asset precompression; crypto/startup security hardening; FD audit and NullPool engine factory; dependency sweep.
* **@Kalaiviswa** — Dhan positions null-crash fix (#1463, #1477), Definedge historical date range (#1475), depth-to-LTP routing (#1453, #1468).
* **@Minh_Nguyen** — reusable EmptyState component (#1484).
* **@Christo John** — Indmoney CSV NaN crash fix (#1427).
* **@Quang Pham** — numeric keypad for the Reset Password TOTP input (#1478).

***

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Python SDK on PyPI**: <https://pypi.org/project/openalgo/>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>
