# Version 2.0.1.5 Released

**Date: 10th July 2026**

**Reliability Release: a ZeroMQ bus fan-in fix that restores live ticks under gunicorn+eventlet, a three-part multi-session login audit that stops one device's login from tearing down another device's broker feed, a real-time futures calendar-spread scanner (Arbitrage), an IndMoney broker hardening pass (FD leaks, batching, IndStocks API alignment), Nubra market/stop-market order emulation with MCX support, and fixes across Angel, Groww, AliceBlue, Fyers, Arrow, sandbox startup and Action Center**

This release spans 49 commits since v2.0.1.4. The headline fix is the **ZeroMQ bus fan-in** correction (`c9591ae6`) — under Gunicorn+eventlet the WebSocket proxy and the cache-invalidation publisher both tried to *bind* the same ZMQ port from separate processes, silently losing the race and delivering **zero market-data ticks** even though subscribe calls succeeded. The bus is now strictly fan-in: the proxy's SUB is the sole binder and every publisher connects to it. Close behind is a **three-commit multi-session login audit** (#1591) that fixes a family of bugs where a second device/browser logging in — or a stale idle cookie at the daily 3 AM token rollover — could tear down or revoke the *first* device's already-working broker WebSocket feed or auth token. On the feature side, a new **Arbitrage** tool (`/arbitrage`) scans all NFO and MCX futures for executable calendar-spread edges in real time, and **IndMoney** gets a five-commit hardening pass (WebSocket FD-leak fixes, batched subscriptions, IndStocks API realignment, option-chain quote resilience). **Nubra** gains market/stop-market order emulation and MCX support, and broker fixes land for Angel (rate-limit pacing, gapless history), Groww (master-contract download resilience), AliceBlue (missing NFO/CDS futures), Fyers (shared rate-limit pacing, option-chain fast path) and Arrow (heartbeat fix for dead data streams). Sandbox gets a self-healing DB-init fix for a fresh-install race, and Action Center now executes all pending order types (multi-leg options, GTT), not just the original subset.

***

**Highlights**

* **ZeroMQ bus fan-in fix (`c9591ae6`)** — The proxy SUB socket is now the sole binder of `ZMQ_PORT`; every publisher (broker adapters, cache-invalidation) connects instead of binding. Removes the port-scan/5556 fallback and the runtime `ZMQ_PORT` mutation that let the two binders silently disagree on which port ticks actually flowed through. Broker-agnostic; fixes silent tick loss under Gunicorn+eventlet (bare-metal `install.sh` subprocess and Docker `start.sh`) that worked fine on the single-process dev server. Invariant documented in `CLAUDE.md`.
* **Multi-session login audit (#1591, 3 commits)** — Devices/browsers sharing one broker session no longer step on each other:
  * `3aadeb33` — a second device's login no longer tears down the first device's live broker WebSocket feed; `upsert_auth` now gates the ZMQ `CACHE_INVALIDATE_ALL` + pool cleanup on an *actual* token change, not just a re-persist of the same token.
  * `350f0733` — the daily ~3 AM rollover no longer revokes a token another device already refreshed that morning; the revoke path checks for a fresher active session before tearing down.
  * `fcf1f4ee` — `active_sessions.last_seen` now updates on a throttled heartbeat (was wired but never called), so the active-session list reflects real device liveness instead of freezing at login time.
* **Arbitrage tool (`/arbitrage`)** — Real-time futures calendar-spread scanner across all NFO and MCX underlyings: near-vs-next and near-vs-third month pairs ranked by executable bid/ask spread percentage, live Depth-mode pricing, and one-click two-leg basket order placement.
* **IndMoney broker hardening (5 commits)** — API realignment to the current IndStocks docs (positions, order status, trade book, WS URI), two rounds of WebSocket FD/thread-leak fixes in the adapter and client, Zerodha-style two-level subscription batching, and option-chain quote resilience (bisect + cache poison scrip codes instead of failing the whole batch).
* **Nubra: market/stop-market emulation + MCX (`ca8985dd`)** — Nubra is limit-only and rejected `MARKET`/`SL-M` orders outright; both are now emulated (Market-Protection-Price limit, stop-limit beyond trigger). Adds MCX instrument support and hardens TOTP auth + order-status mapping.
* **Broker fixes** — Angel (real rate-limit pacing, gapless multi-year history, faster streaming lookups), Groww (master-contract download no longer aborts on a blank-symbol row), AliceBlue (NFO/CDS futures were silently dropped from the master contract), Fyers (shared rate-limit clock across requests, native option-chain fast path), Arrow (app-level PONG heartbeat so the data stream doesn't go silently dead).
* **Sandbox self-heal (`fe65bc13`, #1580)** — A fresh-install DB-init race could leave `sandbox.db` permanently partial ("no such table: sandbox_funds"); `create_all` now self-heals from an orphaned-index state and retries once.
* **Action Center: execute all order types (`1db1294d`)** — Approved pending orders of type `optionsmultiorder` and `placegttorder` now execute (previously only single-leg/basket/split/options orders were wired); DB isolation added for Action Center tests.
* **Telegram alert gating fixes** — Menu P&L now matches `/pnl` (both source from funds, not positionbook) (#1576); Flow's "send Telegram alert" action is now gated on bot-active state like order alerts, so stopping the bot silences Flow alerts too (#1577, follow-up `2904b5ef`).
* **Latency logger crash fix (`3880ba72`)** — A dict-typed validation error (e.g. `/history` called without `apikey`) crashed `OrderLatency.log_latency` on the String-typed error column; now coerced to string at the storage boundary.
* **Dependency bumps** — pydantic 2.13.4, mcp 1.28.0, SQLAlchemy 2.0.51, uvicorn 0.49.0, kaleido/choreographer 1.3.0 (fixes broken Plotly→PNG rendering used by Telegram chart commands, #1578), plus a broad low-risk patch/minor sweep (certifi, click, plotly, pytest, python-telegram-bot, tzdata, etc.).

***

**ZeroMQ bus fan-in — deep dive**

`c9591ae6` — Under Gunicorn+eventlet the WebSocket proxy runs *out-of-process* (a subprocess on bare-metal `install.sh`, or a separate `python -m websocket_proxy.server` on Docker `start.sh`) while the cache-invalidation publisher runs inside the gunicorn process. Both previously created a `SharedZmqPublisher` that **bound** `ZMQ_PORT` (5555). As a per-process singleton, the two binders raced: the gunicorn process usually won port 5555, so the WebSocket process's market-data publisher silently fell back to 5556 via a bind port-scan — while the proxy's SUB socket stayed fixed on 5555. Result: auth and subscribe calls succeeded, but no `market_data` ticks were ever delivered. It worked on the single-process dev server (only one binder existed) and broke only under eventlet servers, which made it hard to spot in testing.

The fix flips the topology to strict fan-in: the proxy SUB is the sole binder, and every publisher — broker adapters and the cache-invalidation publisher alike — **connects** to it (many PUB-connects to one SUB-bind is valid ZMQ). The port-scan/5556 fallback and the runtime `os.environ["ZMQ_PORT"]` mutation are removed, so `ZMQ_PORT` is fixed by config and never drifts (5555 for a single instance, `5555 + i-1` per instance under `install-multi.sh`). Applies to all deployment modes — dev thread, `install.sh` subprocess, Docker `start.sh`, `install-multi.sh` — and is broker-agnostic since the bus itself is shared plumbing. The invariant is now documented in `CLAUDE.md` so it isn't reintroduced.

***

**Multi-session login audit — deep dive (#1591)**

OpenAlgo is single-user/single-broker per instance, but the same user can be logged in from up to `MAX_SESSIONS_PER_USER` (5) devices at once, all sharing **one** server-side broker WebSocket feed. Three bugs in that sharing surfaced together:

* `3aadeb33` — A second device's login resumes the existing broker session and re-persists the *same* token via `upsert_auth()`, which unconditionally published a ZMQ `CACHE_INVALIDATE_ALL` (disconnecting the shared adapter + pool) and ran `cleanup_pools_for_user()` — tearing down the feed the first device was actively streaming from. Symptoms: Shoonya ticks stopped until a page refresh; Flattrade's single-active-session Noren backend dropped the token entirely ("broker session expired"). The fix gates that teardown on an *actual* token/feed-token/broker/revoke-flag change (comparing decrypted plaintext, since Fernet ciphertext is non-deterministic) — an unchanged session now just clears cheap in-process caches and returns early.
* `350f0733` — The daily ~3 AM IST rollover path revoked the shared broker token based only on the *current* cookie's `login_time`. A device left idle overnight would, on its first request after rollover, blindly revoke a token another device had already re-established that morning — kicking the fresh device and collaterally killing API-key/webhook access. The guard now checks `active_sessions` for a session authenticated at/after today's rollover boundary before revoking; if one exists, only the stale device's own session row is dropped.
* `fcf1f4ee` — `update_session_last_seen` existed but was never called, so `active_sessions.last_seen` stayed frozen at login time — the active-session list couldn't distinguish a live device from one whose browser was closed. A throttled heartbeat (once per device per 30s) is now wired into the SPA's `/session-status` poll.

Together these mean multiple devices genuinely stream and stay authenticated concurrently, which is the deployment model OpenAlgo already assumed but didn't fully enforce.

***

**Options tools**

* **Arbitrage** (`2f5acd24`) — `services/arbitrage_service.py` builds the calendar-spread universe from the master-contract cache (near/next/third futures per underlying); `blueprints/arbitrage.py` exposes `GET /arbitrage/api/universe`. Frontend subscribes to the shared `MarketDataManager` in Depth mode for live bid/ask, with a ranked/filterable table and a two-leg trade dialog via the existing basket-order service (NRML default, BUY leg before SELL).

***

**Broker fixes**

* `ca8985dd` — **Nubra**: emulate MARKET (Market-Protection-Price limit) and SL-M (stop-limit beyond trigger) since Nubra is limit-only and has no native stop-market type; add MCX instrument support; map the real `OrderStatus` enum (add SENT/TRIGGERED, drop non-existent PARTIALLY_FILLED); harden TOTP for leading-zero codes.
* `24477b48`, `9f2e295e`, `e8f02ea3`, `85a91e0d`, `96a64da0` — **IndMoney**: realign positions/orders/order-status/trade-book/WS-URI to the current IndStocks API; bisect-and-cache poison scrip codes so one unquotable symbol no longer 400s the whole option-chain batch; two rounds of WebSocket FD/thread-leak fixes (single-owner reconnect loop, interruptible backoff, teardown-before-reinit); Zerodha-style two-level subscription batching (500ms flush, 1000-instrument chunking, dedup); reject unsupported exchanges before order placement instead of silently defaulting to NSE.
* `48807197` — **Angel**: shared per-category rate limiter sized to real caps (was ~7x too slow on quotes), retry on rate-limit 403/429 instead of misreporting as auth failure, retry (not skip) failed 30-day history chunks so multi-year downloads are gapless, O(1) tick-to-subscription lookup (was O(N) per tick).
* `84146cbd` — **Groww**: master-contract download no longer aborts entirely on a single blank-`trading_symbol` row (a stray BSE index entry); malformed rows are skipped and logged instead of rolling back the whole insert. Download also now validates against Groww's real CSV header by name instead of relabelling columns by position.
* `e55e1de0` — **AliceBlue**: NFO/CDS futures were silently dropped from the master contract because the V2 CSV identifies futures by Instrument Type with a NaN Option Type (not `'XX'`); futures Instrument Types are now mapped to `'XX'` before symbol construction, matching the existing BFO/MCX/BCD processors.
* `16a01dcd` — **Fyers**: rate-limit pacing moved from a per-request instance clock (never persisted, so concurrent requests collectively blew past the 10 req/sec cap) to a process-wide shared clock with 429 retry/backoff; native `/data/options-chain-v3` fast path replaces per-symbol bulk-quote + depth calls for option-chain OI/bid-ask.
* `44532dd4` — **Arrow**: send the app-level text PONG heartbeat every 3s (matching the official SDK) instead of relying on protocol-level WebSocket pings, which the server ignores — ticks were silently not delivered even though auth/subscribe succeeded (#1583).

***

**Reliability & fixes**

* `fe65bc13` — **Sandbox**: self-heal a partial `sandbox.db` from a fresh-install DB-init race (#1580); `db/` directory now created up front before any DB module imports; sandbox index names de-duplicated against `action_center_db`/`symtoken`.
* `1db1294d` — **Action Center**: execute `optionsmultiorder` and `placegttorder` pending order types (previously unwired); order-ID summarization for the DB column when a split/batch order returns multiple broker order IDs.
* `c32c41a3` — **Action Center**: isolate the test database so Action Center tests don't share state with other suites.
* `967d0d04` — **Telegram**: `/menu` P&L now sources from funds (matching `/pnl`) instead of positionbook day-P&L, which disagreed and looked stale (#1576); order alerts now gated on bot-active state so stopping the bot actually silences them (#1577).
* `2904b5ef` — **Telegram**: Flow's "send Telegram alert" action gated on bot-active state too, closing the same gap for background Flow strategies.
* `3880ba72` — **Latency**: a dict-typed validation error crashed `OrderLatency.log_latency` (String-typed column); coerced to string at the storage boundary, bounded to 500 chars.
* `f6136f74` — **Scalping**: charts toggle (default off) so per-instrument chart components — each opening their own market-data subscription and history poll — don't run unless explicitly enabled; toggle and timeframe persist in `localStorage`.

***

**Security**

* `0df92a57` — rotate hardcoded API keys in examples to `os.getenv`; refresh sample NIFTY expiry/lot size.

***

**Documentation**

* `2643db5f`, `4526a8fc` — add an Open Knowledge Format (OKF) bundle (63 concepts across REST API, Python SDK, indicator library), then refactor it to thin pointer concepts linking back to `docs/` so the source of truth stays in one place; add `docs/INDEX.md` as a flat documentation router.
* `e27546fd` — remove stale `PRD.md` pointer stub and a resolved `REVIEW_QUEUE.md`.
* `b67d674a`, `65126531`, `55b541e3`, `1acb0099` — full documentation reconciliation sweep against current codebase: broker count 33→34 (TradeSmart), 7 new routes added to the inventory (`/arbitrage`, `/gammadensity/api/gamma-data`, `/scalping/api/history`, `/chart/test`), stale API/design docs rewritten, internal services reference refreshed.

***

**Dependencies**

* `pydantic` 2.12.5 → 2.13.4 (+ `pydantic-core` 2.46.4, `pydantic-settings` 2.14.2)
* `mcp` 1.27.0 → 1.28.0, `sse-starlette` 2.4.1 → 3.4.5
* `python-socketio` 5.16.3, `python-engineio` 4.13.3
* `SQLAlchemy` 2.0.49 → 2.0.51, `uvicorn` 0.44.0 → 0.49.0, `requests` 2.33.1 → 2.34.2
* `kaleido` + `choreographer` → 1.3.0 (matched pair; fixes Plotly→PNG rendering broken since kaleido 1.2.0, used by Telegram chart commands, #1578)
* Broad low-risk patch/minor sweep: `certifi`, `click`, `plotly` 6.8.0, `pytest` 9.1.1, `python-telegram-bot` 22.8, `tzdata`, `duckdb`, `orjson`, and others
* `openalgo` SDK pin unchanged at `2.0.2` (PyPI: <https://pypi.org/project/openalgo/>)

***

**Configuration changes**

`utils/version.py`: `VERSION = "2.0.1.5"`

`pyproject.toml`: `version = "2.0.1.5"` (`uv.lock` regenerated).

`.sample.env`: no new variables; `ZMQ_HOST`/`ZMQ_PORT` comment updated to reflect the fan-in topology (proxy SUB binds, publishers connect — was previously documented as same-process only).

**Database**: no new tables. `sandbox_db` index names changed (`idx_user_status` → `idx_sandbox_user_status`, `idx_symbol_exchange` → `idx_sandbox_symbol_exchange`) as part of the sandbox self-heal fix; applied automatically via the existing self-healing `create_all` path, no manual migration required.

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

* **@marketcalls (Rajandran)** — release management; ZeroMQ bus fan-in fix; multi-session login audit (#1591, 3 commits); Arbitrage tool; Nubra market/stop-market emulation + MCX; Angel/Groww broker fixes; sandbox self-heal; Action Center order-type execution + test isolation; Telegram P&L/alert-gating fixes; latency logger fix; scalping charts toggle; documentation reconciliation sweep; dependency bumps.
* **@Kalaiviswa** — AliceBlue NFO/CDS futures fix; IndMoney broker hardening (API realignment, WebSocket FD-leak fixes, subscription batching, option-chain resilience, #1604/#1610/#1613).
* **@Raj27i** — Arrow app-level PONG heartbeat fix (#1583, #1614).

***

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Python SDK on PyPI**: <https://pypi.org/project/openalgo/>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>
