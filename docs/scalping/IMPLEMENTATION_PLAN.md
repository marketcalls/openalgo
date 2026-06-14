# Scalping Terminal (`/scalping`) — Implementation Plan

A keyboard-driven, low-latency options scalping terminal for OpenAlgo: a one-click
scaling tool for fast intraday execution. Built as a new surface inside OpenAlgo, reusing
the existing broker session, WebSocket market-data feed, and service layer.

- **Branch:** `scalping`
- **Tracker:** `docs/scalping/TRACKER.csv` (update status as phases complete)
- **Workflow:** implement a phase → validate → on success `git commit` (do **not** push).

---

## 1. Product summary

A browser terminal where the trader:

1. Selects an index underlying, expiry, and a CE strike + PE strike.
2. Arms "One-Click" mode.
3. Uses **arrow keys** to fire instant **MARKET** orders (1 lot per press): buy/sell call,
   buy/sell put. Lots configurable up to a cap (20).
4. Watches live LTP on both legs + the underlying, running MTM, Net Qty.
5. Sets a **stop-loss** per position with optional **auto-trailing**.
6. **F6** = Close All Positions, **F7** = Cancel All Orders.

The value proposition is *speed*: a keypress must fire an order with zero lookups on the
hot path.

---

## 2. OpenAlgo order constants (authoritative — use these everywhere)

Source: `docs/prompt/order-constants.md`, `docs/prompt/symbol-format.md`.

| Field | Allowed values | Used by scalping |
| --- | --- | --- |
| **Exchange (underlying)** | `NSE_INDEX`, `BSE_INDEX` | NIFTY/BANKNIFTY → `NSE_INDEX`; SENSEX/BANKEX → `BSE_INDEX` |
| **Exchange (legs)** | `NFO`, `BFO` | NSE index options → `NFO`; BSE index options → `BFO` |
| **Product** | `CNC`, `NRML`, `MIS` | `NRML` (carry) or `MIS` (intraday). **Default `NRML`** for F&O (avoids MIS post-15:15 square-off rejections), `MIS` for equity. Shown as the raw OpenAlgo code (`NRML`/`MIS`/`CNC`). `CNC` is equity-only. |
| **Price type** | `MARKET`, `LIMIT`, `SL`, `SL-M` | Entry/exit = `MARKET`. (SL handled in-app via trailing logic, not broker `SL` orders in v1.) |
| **Action** | `BUY`, `SELL` | both |

**Symbol formats:**
- Underlying (index): base symbol only — `NIFTY`, `BANKNIFTY`, `SENSEX`.
- Option leg: `[Base][Expiry DDMMMYY][Strike][CE|PE]` — e.g. `NIFTY28OCT2525950CE`.
- Expiry string passed to services: `DDMMMYY` uppercase (e.g. `28OCT25`).

**Hard rule:** never hardcode broker-specific symbols or product/price strings. Always use
the constants above and resolve symbols via the option services.

---

## 3. Architecture

### Reused (no changes needed)
- **Market data:** `frontend/src/hooks/useMarketData.ts` + `lib/MarketDataManager.ts`
  (shared WS singleton to `:8765`). Mode 1 = LTP, Mode 2 = Quote.
- **Services:** `place_order`, `close_position`, `cancel_all_orders`,
  `get_positionbook`, `get_orderbook`, `get_tradebook`, `get_option_chain`,
  `get_option_symbol`, `get_expiry_dates`.
- **SocketIO:** `extensions.socketio` + `order_event` for live order/position updates.
- **Auth:** session-based. Inside the blueprint resolve
  `auth_token = get_auth_token(session["user"])` + `broker = session.get("broker")` for
  trading services, and `api_key = get_api_key_for_tradingview(session["user"])` for the
  option-chain/symbol/expiry services (which take `api_key`).

### Trailing stop-loss decision
- **v1 = browser-driven (superseded).** The page computed the trail per LTP tick and fired
  a MARKET exit on breach. Trade-off: closing the tab stopped the trail.
- **v2 (shipped) = server-side engine.** `services/scalping_risk_monitor_service.py`
  consumes the live WebSocket feed and fires freeze-safe exits independent of the browser
  (event-driven, eventlet single-worker safe). The browser hook is now config + display
  only. See `PRD.md` §4.

### Trade mode
- Build & validate in **Sandbox / Analyzer mode first** (no real-money market orders while
  developing a no-confirmation tool). Switch to live only in Phase 3.

---

## 4. Files

**New (backend):**
- `blueprints/scalping.py` — page route + JSON API (`url_prefix="/scalping"`).
- `database/scalping_db.py` — session/SL config persistence (NullPool, mirrors `flow_db.py`).
- `services/scalping_trail_service.py` — v2 backend trail engine (Phase 4 only).

**New (frontend):**
- `frontend/src/pages/Scalping.tsx` — main page.
- `frontend/src/api/scalping.ts` — API client functions.
- `frontend/src/types/scalping.ts` — shared types.
- `frontend/src/stores/scalpingStore.ts` — optional Zustand state.

**Edited:**
- `app.py` — register `scalping_bp`, init scalping DB.
- `frontend/src/App.tsx` — lazy route `/scalping`.
- nav/menu source — add a "Scalping" entry.

---

## 5. Phases

### Phase 0 — Symbol & data plumbing (read-only)
- Backend: `blueprints/scalping.py` serving the page + `GET /scalping/api/expiry`,
  `GET /scalping/api/strikes` (wrap `get_expiry_dates`, `get_option_chain` /
  `get_option_symbol`). Register blueprint in `app.py`.
- Frontend: `Scalping.tsx`, route, `api/scalping.ts`, `types/scalping.ts`. Underlying /
  expiry / strike dropdowns. Subscribe underlying (Mode 2) + both legs (Mode 1) via
  `useMarketData`. Render 3 live tickers + WS connection-state badge.
- **Validation:** page loads at `/scalping`, dropdowns populate from live expiry/chain
  data, three tickers update live; `npm run build` + backend import clean.

### Phase 1 — Keyboard order entry (Sandbox)
- Backend: `POST /scalping/api/order` → `place_order`; `POST /scalping/api/close_all` →
  `close_position`; `POST /scalping/api/cancel_all` → `cancel_all_orders`. All using
  `auth_token`+`broker`. Pre-resolve token/lotsize/freeze_qty on strike select.
- Frontend: arm/disarm toggle; global `keydown` (arrows = buy/sell CE/PE; **F6**=close-all;
  **F7**=cancel-all; ignore when typing in inputs). Lot selector with cap (20).
  Product toggle MIS/NRML. Positions/Order book/Trade book tabs. Running MTM + Net Qty.
- **Validation (Analyzer on):** arrow keys place sandbox MARKET orders with correct
  symbol/qty/product/action constants; F6 closes all; F7 cancels all; grids + MTM update
  live via SocketIO.

### Phase 2 — Stop-loss + auto-trailing (browser-driven)
- Frontend: per-position SL state machine on each LTP tick; manual SL + auto-trail with the
  "don't trail until ≥1 rupee above entry" rule; "Set SL" dialog (initial SL + trailing
  step); MARKET exit on breach.
- Persistence: `database/scalping_db.py` storing session + SL config; init in `app.py`.
- **Validation:** SL triggers a sandbox exit at the right level; trailing raises the stop as
  price advances and never lowers it; state survives a page reload.

### Phase 3 — Hardening & go-live
- Latency measurement (keypress→ack), WS reconnect/resubscribe, double-fire debounce, fill
  reconciliation under rapid presses, safety rails (lot cap, arm required). Document switch
  from Sandbox to live.
- **Validation:** stable under rapid input; reconnect restores leg subscriptions; documented
  live checklist.

### Phase 4 — (Optional) Backend safety-net trail engine
- `services/scalping_trail_service.py` consuming ZeroMQ ticks; takes over SL when browser
  absent. Singleton thread, eventlet-safe, FD-audited.
- **Validation:** SL holds and fires with the browser tab closed (sandbox).

---

## 6. Validation checklist per phase (before commit)
- [ ] `cd frontend && npm run build` passes (if frontend touched).
- [ ] Backend imports cleanly: `uv run python -c "import app"` (or app starts).
- [ ] `uv run ruff check blueprints/scalping.py database/scalping_db.py services/` clean.
- [ ] Manual smoke test of the phase's validation criteria above (Analyzer mode).
- [ ] FD audit of any new DB/thread/socket/subprocess per CLAUDE.md.
- [ ] Update `docs/scalping/TRACKER.csv` statuses.
- [ ] `git commit` (no push).

---

## 6b. Sandbox → Live switch checklist (Phase 3)

The terminal fires **no-confirmation MARKET orders** from a keypress. Validate
everything in Sandbox/Analyzer first, then switch to live deliberately.

Before turning Analyzer mode OFF (going live):

1. **Confirm you are in Sandbox** while testing: `/analyzer` shows Analyzer ON;
   orders appear in the sandbox book, not the live broker.
2. **Broker session is live and IP-whitelisted** (SEBI static-IP mandate, eff.
   2026-04-01): the OpenAlgo server's IP is registered with the broker, daily
   token generated (tokens expire ~3:00 AM IST).
3. **Verify the keymap** on a single 1-lot order each: ↑ Buy Call, ↓ Sell Call,
   → Buy Put, ← Sell Put — confirm symbol/side/qty in the order book.
4. **Lot cap** is 20 (UI selector + server-side `MAX_LOTS`); confirm a >20 attempt
   is rejected. Start live with **lots = 1**.
5. **Stop-loss sanity**: set a manual SL on a live 1-lot position and confirm it
   exits at the level; for a SELL leg confirm the stop sits ABOVE entry.
6. **Feed health**: the status badge reads **Live** (not Polling/Disconnected).
   A red banner appears if the feed drops — do not trade through it.
7. **Latency**: the header shows `order NNms` after a fire; confirm it is
   acceptable on your network before scaling size.
8. **Flatten path works**: F6 (Close All) and F7 (Cancel All) both act on the
   live account. These are intentionally NOT gated by the One-Click arm toggle.
9. **One browser tab** drives trailing SL (Phase 2 is browser-driven) — keep it
   open and focused while in a position. For unattended safety, wait for the
   Phase 4 backend trail engine.
10. Flip Analyzer OFF, **arm One-Click**, trade 1 lot, verify the real fill, then
    scale.

## 7. Open items / decisions
- Confirm SENSEX/BANKEX (BSE, `BFO`) inclusion in v1 or NSE-only first.
- Confirm lot cap (default 20).
- v2 backend trail engine: in scope now or deferred.
