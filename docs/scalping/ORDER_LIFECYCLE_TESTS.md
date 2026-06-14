# Scalping Terminal — Order Lifecycle Test & Validation

Validation of the `/scalping` order lifecycle against a **live Sandbox (Analyzer
mode)** session, run on 2026-06-14. Orders were placed through the exact service
path the scalping endpoints use (`place_order`, `get_positionbook`,
`cancel_all_orders`, and the blueprint helpers `_reducing_exit` /
`_validate_quantity`), with `api_key` routing to the sandbox engine.

Instrument under test: **NIFTY** ATM CE/PE and the nearest **NIFTY FUT** on NFO
(lot size 65; NIFTY freeze 1800 → whole-lot cap 27 lots = 1755).

## Result: 20 / 20 scenarios PASS

### Core lifecycle (12/12)
| # | Scenario | Expectation | Result |
|---|----------|-------------|--------|
| 1 | Analyzer mode + ATM chain resolve | Sandbox on, ATM CE resolved | ✅ |
| 2 | Clean slate (flatten existing) | Start qty = 0 | ✅ |
| 3 | Entry — BUY 1 lot (MARKET, NRML) | order accepted, code 200, orderid | ✅ |
| 4 | Positionbook reflects entry | qty = +1 lot (65) | ✅ |
| 5 | Scale-in — BUY 1 lot | qty = +2 lots (130) | ✅ |
| 6 | Partial exit via `close_leg` — SELL 1 lot | qty = 65 | ✅ |
| 7 | Full exit via `close_leg` | qty = 0 (flat) | ✅ |
| 8 | Reject non-lot-multiple qty | 400 "whole number of lots" | ✅ |
| 9 | Reject > 20-lot cap | 400 "exceeds the 20-lot cap" | ✅ |
| 10 | Accept valid 1-lot qty | no error | ✅ |
| 11 | Equity (NSE) bypasses lot rules | `_is_derivative('NSE')` = False | ✅ |
| 12 | `cancel_all_orders` | code 200 | ✅ |

### Extended scenarios (8/8)
| # | Scenario | Expectation | Result |
|---|----------|-------------|--------|
| 13 | Short entry — SELL to open (PE) | qty = −1 lot (−65) | ✅ |
| 14 | Short exit — BUY to close | flat | ✅ |
| 15 | Build 28-lot position (1820 qty) | qty = 1820 | ✅ |
| 16 | **Freeze-split close** (qty > 27-lot freeze) | split into ≥2 whole-lot orders (27 + 1) | ✅ |
| 17 | Freeze-split close → flat | qty = 0 | ✅ |
| 18 | Futures entry — BUY 1 lot (NIFTY FUT) | qty = +1 lot | ✅ |
| 19 | Futures exit | flat | ✅ |
| 20 | Track + list scalping symbol | tracked list contains the leg | ✅ |

## What this validates
- **Entry / scale-in / partial / full exit** place real sandbox orders and the
  positionbook moves exactly as expected (long and short).
- **Risk-reducing exit (`close_leg`)** flattens any size and, when the quantity
  exceeds the exchange freeze, **splits into whole-lot, freeze-sized chunks**
  (28 lots → 27 + 1) — no single order breaches the freeze limit.
- **Server-side guards**: whole-lot multiple, 20-lot entry cap, equity vs
  derivative classification.
- **Futures** entry/exit lifecycle.
- **Strategy scoping**: instruments traded are tracked (the scalping list) so
  Close-All / books stay scoped to the scalping strategy.
- `cancel_all_orders` succeeds.

## Server-side SL / Target / Trailing-SL engine (event-driven, browser-independent)
The SL/TP/TSL engine now runs **server-side** in
`services/scalping_risk_monitor_service.py`, so stops keep working even after the
user leaves /scalping or closes the browser. It is **fully event-driven (zero
polling)**:
- prices arrive as live ticks from the WebSocket proxy
  (`services/websocket_client.py`, LTP mode) — each tick drives one evaluation;
- the watched-symbol set changes only when an SL is saved/deleted (the `/sl`
  endpoints call `notify_sl_changed()` → `sync()`), never on a timer;
- trailing updates / auto-clears are pushed to the browser via a SocketIO
  `scalping_sl_update` event; the React side listens for it (and order events)
  instead of polling.

On breach it fires the same freeze-safe `_reducing_exit` proven above, sized to
the CURRENT live position, and clears the SL only on a confirmed exit. The
browser `useTrailingSL` hook is now config + display only (no executor), so there
is exactly one engine and no double-exit.

### Tests (`test/test_scalping_risk_monitor.py`) — 20/20 PASS
- `evaluate_trail` decision core: SL, Target, and Trailing triggers for **both
  long (BUY) and short (SELL)** legs — breach boundaries, hold-cases, trailing
  raises/lowers only in your favour, trailing doesn't start until in profit, and
  a trailed stop then breaching.
- Event-driven `_on_tick`: a breaching tick dispatches an exit; a non-breaching
  tick does not; a trailing tick updates in-memory state + persists; ticks for
  unwatched symbols and zero/missing LTP are ignored.

### Live sandbox validation (2026-06-14)
End-to-end against the live sandbox: flatten → BUY 1 lot (→65) → target-breach
tick through the real `_on_tick` → exit worker → **flat (0)**, SL state cleared
from DB + memory. This surfaced and fixed a real bug: in analyze/sandbox mode the
monitor must pass the **api_key only** (not `auth_token`+`broker`) or
positionbook/place_order take the live-broker path and the sandbox position reads
as flat — silently clearing the SL without exiting.

## Not covered by this backend harness (validated separately)
- **UI interaction** (keyboard fire, dropdowns, OHLC bar) — requires a browser
  session; covered by `npm run build` + biome, pending a manual click-through.

## Exchange restructure validation (2026-06-14, follow-up)
After re-landing the unified exchange model (NSE/BSE/NFO/BFO/MCX/CDS):
- Option chain for **NFO** (NIFTY) and **MCX** (CRUDEOIL, ATM from current-month
  future LTP) return correct ATM + CE/PE symbols against sandbox.
- An order resolved through the **generalized strikes path** (NIFTY ATM CE)
  placed and flattened cleanly in sandbox (entry code 200 → +1 lot → flat).
- CDS option chain depends on the currency-future carrying a live quote in the
  feed (no logic issue; degrades gracefully when absent).

## How to re-run
With the app connected to a broker in **Analyzer (Sandbox)** mode, run a Python
script (under the repo root, after `import restx_api` to resolve the service
import graph) that calls `place_order` / `get_positionbook` /
`blueprints.scalping._reducing_exit` with the user's `api_key`, asserting
position deltas with polling. Orders settle asynchronously in the sandbox, so
assert on deltas (not absolutes) and poll the positionbook.
