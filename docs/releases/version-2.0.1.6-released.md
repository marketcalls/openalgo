# Version 2.0.1.6 Released

**Date: 24th July 2026**

**Broker & Reliability Release: a new HDFC Sky broker integration, a ground-up TypeScript rewrite of the /trading chart-trading page with a multi-chart grid, real-time order-update streaming brought to IIFL Capital and Upstox, sandbox order lifecycle now includes a first-class "trigger pending" status for SL/SL-M orders, a Definedge connector overhaul, and a broad sweep of Dhan/Flattrade/Fyers/Zerodha broker fixes**

This release spans 119 commits since v2.0.1.5. The headline addition is **HDFC Sky**, a new broker integration (orders, WebSocket market depth, funds, OI tracker, and SL-M order protection under HDFC Sky's live margin regime) — OpenAlgo now supports 35 brokers. The **`/trading` page was rewritten from scratch** as a TypeScript React route with a multi-chart grid, TradingView-style timeframe/chart-type menus, an inline Buy/Sell panel, and a symbol search modal with per-pane state. **Real-time order-update streaming** — started in the previous cycle for a handful of brokers — was extended end-to-end, with IIFL Capital and Upstox gaining live order/trade push feeds and a new dedicated **`/websocket/order`** page for watching the raw event stream. The **sandbox engine** gained a proper **"trigger pending"** status for SL/SL-M orders (matching how a live exchange's Stop-Loss book actually works, instead of showing "open" the whole time) plus F&O expiry settlement timing, event-driven MTM, and several T+1/holdings settlement correctness fixes. On the broker side: **Definedge's connector was overhauled** for the current API (orders, OI, rate limits, WebSocket), **Dhan and IIFL Capital both got SL-M emulation** (a bare stop-loss-market order is blocked under SEBI's market-protection regime on several brokers — it's now transparently converted to a protective stop-limit order), and Flattrade, Fyers, Zerodha, and Upstox each picked up targeted reliability fixes. A large parallel documentation effort ("superpowers") laid out the architecture, ADRs, and roadmap for future global-market (non-Indian-exchange) broker support.

---

**Highlights**

* **HDFC Sky broker integration (`cb4ec7d56` + 9 follow-up fixes)** — new broker: order placement/modification, WebSocket market depth (served from a live snapshot), funds, OI tracker (batched LTP fetch + OI sourced over WebSocket), and SL-M/MARKET algo orders converted to protected LIMIT/SL under HDFC Sky's live margin rules. OpenAlgo now supports **35 brokers**.
* **`/trading` page rewrite (`a55a95fe3` + 10 follow-ups)** — ported from the legacy page to a TypeScript React route: multi-chart grid layout, TradingView-style timeframe/chart-type menus and product segments, an inline Buy/Sell button panel with live top-of-book bid × ask, a TradingView-style symbol search modal with per-pane state, 2-decimal P&L with platform-stable tick precision (Windows vs macOS), and square-off routed through `placeorder` (never `placesmartorder`) to avoid a position-sizing mismatch.
* **Real-time order-update streaming extended (`2960edace` and related, this + prior cycle)** — IIFL Capital and Upstox gained live order/trade push feeds; every order-update source now normalizes to OpenAlgo's standard symbol format; a new dedicated **`/websocket/order`** page (`074768845`) lets you watch the raw live order-update stream with auto-reconnect; the ZMQ publisher now warms up at boot so the very first order event isn't dropped under gunicorn (`e9fc4d761`).
* **Sandbox: "trigger pending" order status (`3e7132a52`)** — SL/SL-M orders in sandbox now correctly rest in a "trigger pending" state (mirroring an exchange's Stop-Loss book) until the trigger price actually fires, instead of showing "open" the entire time. Ships with a schema migration (`upgrade/migrate_sandbox_trigger_pending.py`) wired into `migrate_all.py`.
* **IIFL Capital: rate limiting + live order updates + SL-M fix (`5e562a79c`, `18c003106`)** — previously-unthrottled option-chain/OI requests were silently dropping data past IIFL's rate caps; a new dedicated MQTT order/trade-update adapter now streams live order status; bare SL-M orders (blocked by IIFL) are now converted to a protective stop-limit order, mirroring the Dhan fix below.
* **Dhan: SL-M protective-limit hardening (`55b3e2027`, `828f8d23e`, `943e39912`)** — SL-M orders rest as a protective `STOP_LOSS` limit order instead of being rejected under Dhan's live market-protection-percent regime; live order-update payload parsing corrected for Dhan's camelCase field names.
* **Definedge: connector overhaul (`0332220a8`)** — orders, open interest, rate limits, and WebSocket streaming brought up to date against Definedge's current API; SL-M orders now show correct Cancel/Modify actions while in "trigger pending" (`72e398a3b`).
* **Sandbox reliability sweep** — F&O expiry settlement timing and option LTP settlement (`2342af5de`), event-driven MTM via position-feed subscriptions instead of polling (`5a245e9d2`), corrected weighted-average in T+1 holdings settlement (`265fd3419`), auto-cancel of open orders on expired F&O contracts (`fa1de5794`), non-trading days skipped in daily P&L snapshots (`ccb8e629b`, #876), deferred MARKET fills on stale quotes (`6665d6e7f`, #1638), and CNC sells against existing holdings settling correctly instead of opening a phantom short (`bb27f2ff2`, #1640).
* **WebSocket protocol fix: per-mode subscription tracking (`be65283ef`, #1664)** — a client holding both LTP and Depth subscriptions on the same symbol no longer has one silently overwrite the other; the trading terminal now subscribes Depth-only for tradeable instruments (Depth's payload already carries `ltp` as a first-class field).
* **Broker fixes** — Flattrade (bounded auth-failure retry instead of hammering a dead WebSocket session, burst-friendly dual-window rate limiter for #1663), Fyers (redundant inter-chunk sleep dropped from history fetch, paise conversion fixed for CDS/BCD in WebSocket mapping, empty funds returned on error instead of a fabricated zero), Zerodha (order-update symbol resolution now prefers the broker's instrument token over name matching), Upstox (portfolio-stream authorize endpoint corrected with a direct-WSS fallback, full RMS rejection reason surfaced in order updates).
* **Security & infra** — a pepper mismatch on the encryption key now surfaces clearly with DB recovery tooling instead of failing silently (`e8660191d`, #1660); `api_keys` table name corrected in the `init_db` diagnostic; icons and emojis removed repo-wide and forbidden going forward in all generated output (code, docs, commits, alerts) per updated CLAUDE.md guidance.
* **Order dialog / Holdings UI** — cash equity orders now show the real share count instead of a lot-size multiplier, with an NSE/BSE exchange switch; Holdings gained Add/Exit actions and a fix for a zero LTP defeating the REST fallback.
* **Global-market architecture planning ("superpowers" docs, 10 commits)** — design, audit, and roadmap documents plus three ADRs (crypto via direct native adapters not CCXT; direct API/WebSocket integration, no vendor SDKs; in-tree broker model) laying groundwork for future non-Indian-exchange broker support. Documentation only in this release — no code shipped yet.
* **Dependency bumps** — TypeScript migrated to 7.0 (`8b6e5f08d`), `openalgo` SDK pin bumped to 2.0.3 (adds `subscribe_orders`), `openalgo-charts` 1.0.7, `axios` 1.18.0, `pillow` 12.3.0, `mcp` 1.28.1, `svgo` 4.0.2, `setuptools` 83.0.0, `actions/setup-node` 6 → 7.

---

**HDFC Sky broker integration — deep dive**

`cb4ec7d56` (Add HDFC Sky broker integration) plus 9 follow-up fixes over the following day: WebSocket auth corrected and index normalization relocated (`8ffae60a3`), `exchange.py` folded into `transform_data.py` for consistency with the standard broker plugin shape (`5a3566954`), OI tracker fixed by capping the LTP-fetch batch size and sourcing OI over WebSocket instead of REST (`cfb05fb8b`), MARKET/SL-M algo orders converted to protected LIMIT/SL orders to satisfy HDFC Sky's live margin checks (`2f933dad9`), market depth now served from a live WebSocket snapshot rather than polled (`f1f63a769`), queued WebSocket subscriptions no longer dropped — now batched by type (`7a608ac02`), margin leg `underlying` sent as an integer per the API's actual expectation (`d30fd933b`), and a final docs pass resolving the margin-underlying TODO and genericizing the funds sample (`935817c49`).

---

**`/trading` page rewrite — deep dive**

The chart-trading page moved from its previous implementation to a TypeScript React route (`a55a95fe3`) with a multi-chart grid layout. Follow-up commits over the next several days: square-off now routes through `placeorder` instead of `placesmartorder` to avoid a position-sizing mismatch (`c0adca1f3`); a guard against a coarse tick feed snapping orders to whole rupees (`e85b7800e`); 2-decimal P&L display with robust tick precision and a stable default chart zoom (`40f2abc9a`); platform-stable price decimals reconciling Windows vs macOS floating-point display differences (`04021aa1f`); live top-of-book bid × ask shown directly on the Buy/Sell panel (`02bcd2788`); TradingView-style timeframe and chart-type menus plus product-segment selection (`934e2a7ed`); the "Fit" text button replaced with a fit-to-screen icon (`3b4a829ca`); cross-platform MIME type and state-persistence fixes plus a BHEL fallback symbol (`26723bfaf`); an inline Buy/Sell button panel added directly on the chart (`f19b2cd9b`); and finally a TradingView-style symbol search modal with independent per-pane state (`249a4a43f`) for the multi-chart grid.

---

**Order-update streaming — deep dive**

Building on the end-to-end real-time order-update pipeline shipped this cycle (`2960edace`), follow-up work: Upstox's portfolio-stream authorize endpoint corrected with a direct-WSS fallback (`516b9073b`), then its OpenAlgo symbol mapping and full RMS rejection reason wired into order updates (`705b80fee`); every order-update source normalized to emit OpenAlgo's standard symbol format with unit test coverage (`3dc0d797c`); the `openalgo` Python SDK pin bumped to 2.0.3 to pick up `subscribe_orders`, with order-update environment variables documented (`62b60a90f`); the shared ZMQ publisher now warms up at application boot so the very first order event of a session isn't silently dropped under gunicorn (`e9fc4d761`); "trigger pending" promoted to a first-class order-update status broker-wide (`c3870d3a6`) — the same status this release's sandbox work (`3e7132a52`) then implemented for the simulated engine; sandbox order placement now streams an "open" alert immediately, matching live-broker behavior (`15f375278`); and a new dedicated **`/websocket/order`** page for watching the raw live stream (`074768845`), with a follow-up fix for a stale-closure bug in its auto-reconnect logic (`ac0827779`).

---

**Sandbox: trigger pending — deep dive**

`3e7132a52` — SL and SL-M orders previously sat as "open" from placement until the trigger fired, indistinguishable from a normal resting order. Real exchanges hold SL/SL-M orders in a separate Stop-Loss order book until the trigger price is touched; sandbox now mirrors this with a genuine "trigger pending" state. SL-M fires straight to `complete` once triggered (no resting phase, matching live brokers); SL transitions to `open` once triggered unless the limit price is also immediately satisfiable, in which case it fills directly. Modify/cancel and the end-of-day/expired-contract auto-cancel sweeps all now accept the new state. Ships with `upgrade/migrate_sandbox_trigger_pending.py` (SQLite doesn't support altering a CHECK constraint in place, so this rebuilds `sandbox_orders` preserving every row) wired into the standard `migrate_all.py` upgrade path.

---

**Broker fixes**

* `55b3e2027`, `828f8d23e`, `943e39912` — **Dhan**: SL-M orders rest as a protective `STOP_LOSS` limit order under Dhan's live market-protection-percent regime instead of being rejected outright; live order-update payload parsing corrected for Dhan's camelCase field names; the protective-limit calculation itself hardened following code review.
* `0332220a8`, `c24d2282a`, `72e398a3b` — **Definedge**: full connector overhaul for the current API (orders, open interest, rate limits, WebSocket streaming); noisy logs quieted and a redundant multiquote batch delay dropped; SL-M orders now show correct Cancel/Modify actions while in "trigger pending".
* `41bcaa4f8`, `96ad15ab9` — **Flattrade**: burst-friendly dual-window rate limiter replacing an overly conservative fixed-gap pacer (#1663); WebSocket reconnect logic no longer retries indefinitely on a confirmed auth failure — backs off through a tightly bounded retry path instead of hammering a dead session.
* `527249885`, `1815de268`, `7a3fbc0f6` — **Fyers**: redundant inter-chunk sleep dropped from history fetch; paise-to-rupee conversion corrected for CDS/BCD in WebSocket mapping; funds endpoint returns empty on error instead of a fabricated zero balance.
* `78d048d12` — **Zerodha**: order-update symbol resolution now prefers the broker's instrument token over brsymbol name-matching, more reliable for F&O contracts.
* `5e562a79c`, `18c003106` — **IIFL Capital**: rate limiting added across the REST API (fixing silent option-chain/OI data loss from an unthrottled concurrent burst); a new dedicated MQTT adapter streams live order/trade updates; bare SL-M orders converted to a protective stop-limit order.

---

**Reliability & fixes**

* `e8660191d` — a mismatched encryption pepper now surfaces as a clear error with accompanying DB recovery tooling, instead of failing silently (#1660).
* `d4786ca11` — corrected the `api_keys` table name referenced in the `init_db` diagnostic.
* `be65283ef` — WebSocket per-mode subscription tracking (#1664): a client holding LTP and Depth on the same symbol no longer has one mode silently overwrite the other; the trading terminal now subscribes Depth-only for tradeable instruments since Depth's payload already carries `ltp`.
* `4f928011d` — Holdings page gained Add/Exit position actions; fixed a zero LTP value defeating the REST fallback path.
* `5be274364`, `932c03bdb` — order dialog: dropped the lots UI for cash equity (added an NSE/BSE exchange switch instead), and cash equity orders now show the real share count rather than a lot-size multiplier.
* `b3e142e9c`, `891f8b7ae` — icons and emojis removed repo-wide (source, comments, logs, docs) and forbidden going forward in all generated output per updated CLAUDE.md guidance.

---

**Global-market architecture planning ("superpowers" docs)**

Ten documentation-only commits (`7cfa323bc` through `786f5932b`) laying out design, audit, and roadmap material for eventual non-Indian-exchange broker support: three ADRs (crypto via direct native adapters rather than CCXT; direct API/WebSocket integration with no vendor SDKs; an in-tree broker model rather than out-of-tree plugins), a `problem/` directory documenting current challenges, GTT marked as an experimental/optional capability, and a `blockers/` living register for open questions. No code shipped in this release from this effort — planning only.

---

**Dependencies**

* TypeScript migrated to **7.0** (`8b6e5f08d`, with a package-lock sync fix `a7f2be646`)
* `openalgo` SDK pin: `2.0.2` → **2.0.3** (adds `subscribe_orders`)
* `openalgo-charts` → **1.0.7**, `axios` → **1.18.0**
* `pillow` → **12.3.0**, `mcp` → **1.28.1**
* `svgo` → **4.0.2**, `setuptools` → **83.0.0**
* `actions/setup-node` → **7** (CI only)

---

**Configuration changes**

`utils/version.py`: `VERSION = "2.0.1.6"`

`pyproject.toml`: `version = "2.0.1.6"` (`uv.lock` regenerated).

**Database**: `sandbox_orders.order_status` CHECK constraint widened to include `'trigger pending'`. Existing installs need `upgrade/migrate_sandbox_trigger_pending.py`, which is wired into `upgrade/migrate_all.py` and runs automatically via the standard upgrade path (rebuilds the table via SQLite's create/copy/drop/rename procedure, preserving every existing row). Fresh installs get the widened constraint from schema creation directly — no migration needed.

**Upgrading is recommended for all users, and mandatory for sandbox mode** — without the migration, placing an SL or SL-M order in sandbox will fail with a `CHECK constraint failed` error.

---

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
uv run upgrade/migrate_all.py
# Frontend: a plain pull already ships the CI-built dist. Only rebuild if
# you are editing React code:
cd frontend && npm install && npm run build
uv run app.py
```

Never run `cp .sample.env .env` on an existing installation — it destroys broker credentials and the `API_KEY_PEPPER`, permanently invalidating password hashes and encrypted tokens. Compare `.env.sample` against your `.env` for new variables instead.

---

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Python SDK on PyPI**: <https://pypi.org/project/openalgo/>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>
