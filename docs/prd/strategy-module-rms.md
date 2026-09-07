# PRD: Strategy Module - Multi-Leg Baskets And Risk Management

> **Status:** Stable - two strategy kinds, shared risk core, end-to-end risk management

## Overview

The `/strategy` surface runs option and equity strategies with the risk management
that is normally left to the trader. Two kinds share one engine and one set of
rules:

- **Batch** - a multi-leg basket entered and exited as a unit. Start places every
  leg, stop squares every leg.
- **Signal** - one leg per alert. `long_entry`, `long_exit`, `short_entry` and
  `short_exit` each move a single leg, and a leg can be flipped from one side to
  the other.

Both are driven from the browser and from a public webhook that TradingView and
similar senders can post to. The API-key surface at `/api/v1/strategy/` carries
**lifecycle and reads only**: start, stop, close_all, close_leg, status, list,
runs, orders and events. The four signal actions are accepted **only** on the
tokenized public webhook, so a signal strategy is controlled by its alert
sender rather than by an API key.

## Problem Statement

A trader running a multi-leg option strategy has to hold several things at once
that nothing on the platform held for them:

- **Per-leg risk.** A stop, a target and a trailing stop, per leg, evaluated on
  every tick rather than watched by hand.
- **Basket risk.** A combined stop, a combined target and a lock-profit floor on
  the whole book, which no per-leg rule can express.
- **Session risk.** A daily loss limit that survives the strategy being started
  and stopped several times a day.
- **Contract resolution.** ATM offsets, expiry ranks and lot sizes differ per
  exchange and change without notice; NIFTY's lot size moved from 75 to 65.
- **Surviving the day.** Indian broker tokens expire around 03:00 IST and the
  process restarts. A positional strategy has to come back holding what it held.

Doing this in a Python strategy script means every trader writes their own
evaluator. The module this one is modelled on did exactly that, and four
defects lived in its evaluator undetected.

## Solution

One engine, one risk core, one order path.

- Risk is decided by `services/risk/`, the same module the scalping terminal and
  Flow use. It performs no I/O and is never reimplemented per consumer.
- Every order the module places passes through one dispatch point, so the rules
  about products, price types, duplicate exits and which pipe an order belongs
  on are stated once.
- State is durable. Runs checkpoint continuously and are recovered from order
  rows plus checkpoints after a restart.

## Target Users

| User | Use Case |
|------|----------|
| Option seller | Run a short straddle or iron condor with per-leg and combined stops |
| Signal follower | Route TradingView alerts to individual legs, long and short |
| Positional trader | Hold a basket across the 03:00 session boundary and have it recovered |
| Systematic trader | Drive lifecycle from `/api/v1/strategy/` and read runs, orders and events back |

## Architecture

```
Browser / TradingView / API key
        |
        v
blueprints/strategy_module.py        session API, public webhook, SocketIO rooms
restx_api/strategy.py                API-key surface (lifecycle plus reads)
        |
        v
services/strategy_module/
  webhook.py        admitted-request validation pipeline, every outcome audited
  signals.py        signal-mode vocabulary, one leg per alert
  engine.py         run lifecycle, tick evaluation, fills
  state.py          in-process run state, the lock every writer holds
  order_dispatch.py the single order decision point
  order_events.py   fills, from the order.update bus
  risk_adapter.py   translation to and from the shared core
  symbol_resolver.py contracts, expiries, strikes, lot sizes
  scheduler.py      timed start and square-off
  checkpoint.py     durability
  recovery.py       what comes back after a restart
  tick_feed.py      websocket prices, REST fallback
  broadcast.py      live frames to the page
  views.py          broker-backed orderbook, tradebook, positions
        |
        v
services/risk/      the shared, I/O-free decision core
```

Six tables, all `sm_` prefixed, in the main database: `sm_strategy`,
`sm_strategy_run`, `sm_strategy_order`, `sm_strategy_checkpoint`,
`sm_webhook_event`, `sm_strategy_event`.

## Functional Requirements

### FR1: Strategy Configuration
| ID | Requirement | Priority |
|----|-------------|----------|
| FR1.1 | Create, edit and delete a strategy with up to the configured leg cap | P0 |
| FR1.2 | Two kinds, batch and signal, each refusing the other's vocabulary | P0 |
| FR1.3 | Per-leg segment: cash, futures or options | P0 |
| FR1.4 | Strike by ATM offset, by outright strike, and expiry by rank | P0 |
| FR1.5 | Quantity in lots or in units, with the lot count stored rather than the product | P0 |
| FR1.6 | A PATCH re-validates the whole merged configuration, not only the changed fields | P0 |

### FR2: Order Execution
| ID | Requirement | Priority |
|----|-------------|----------|
| FR2.1 | Batch start resolves every leg to a contract before the strategy or any leg is claimed or placed | P0 |
| FR2.2 | Entries go BUY before SELL, so a spread is not refused for margin it would have had | P0 |
| FR2.3 | The product is translated to what the leg's venue accepts | P0 |
| FR2.4 | Exits are MARKET on every path | P0 |
| FR2.5 | An exit uses the symbol the run holds, never a re-resolved one | P0 |
| FR2.6 | Orders bypass the Action Center approval queue: a stop that waits for a human is not a stop | P0 |
| FR2.7 | A run's mode decides its pipe, and the platform analyzer toggle cannot divert it | P0 |
| FR2.8 | The product actually sent is recorded on the order row | P1 |
| FR2.9 | Batch and signal paths write a durable pending intent before calling the broker | P0 |
| FR2.10 | If intent persistence fails an entry is refused; an exit is still attempted and the lost audit row is reported at critical severity | P0 |
| FR2.11 | A broker acknowledgement write is checked and retried once; persistent failure records structured exact row/run/leg, broker id and accepted/rejected facts in `order_ack_unrecorded`, immediately attempts idempotent exact-row repair, and is retried by a bounded shared open-run sweep with broker-status folding; conflicts keep possible exposure open and reserved | P0 |
| FR2.12 | Every position incarnation has a durable `position_ref`; entry, exit and fill settle only the exact owner they name | P0 |
| FR2.13 | An accepted but unfilled entry is never squared off at requested size; the stop stays open until a confirmed quantity exists | P0 |
| FR2.14 | A stop request is durable before exits and finalises only after exact owner quantities confirm the run is flat | P0 |
| FR2.15 | An accepted exit placement is audited before a replayed synchronous fill may produce the confirmed-flat `run_stopped` transition | P0 |

### FR3: Per-Leg Risk
| ID | Requirement | Priority |
|----|-------------|----------|
| FR3.1 | Stop loss and target in points from entry | P0 |
| FR3.2 | Trailing stop, continuous and stepped | P0 |
| FR3.3 | Every decision taken by `services/risk/`, never a second evaluator | P0 |
| FR3.4 | A leg with no recorded side is refused rather than defaulted | P0 |
| FR3.5 | An unusable tick leaves the price, the favourable extreme and the stop untouched | P0 |

### FR4: Strategy And Session Risk
| ID | Requirement | Priority |
|----|-------------|----------|
| FR4.1 | Combined stop and combined target across the basket | P0 |
| FR4.2 | Lock-profit floor that ratchets and never loosens | P0 |
| FR4.3 | Trail every other leg to entry once one leg's stop fires | P1 |
| FR4.4 | Daily loss limit measured across the session, not one run | P0 |
| FR4.5 | The session boundary is the platform session reset, not midnight | P0 |
| FR4.6 | Combined thresholds evaluate rolling latest-known marks after each one-symbol tick and trigger MARKET exits; final fill-derived P&L may differ, while the terminal reason preserves the rule that fired | P0 |

### FR5: Signals And The Public Webhook
| ID | Requirement | Priority |
|----|-------------|----------|
| FR5.1 | Token in the URL, stored only as a digest, shown once, rotatable | P0 |
| FR5.2 | All admitted pipeline outcomes are audited; route-level rate limits and declared-size 413 preflight refusals happen before durable webhook-event audit | P0 |
| FR5.3 | A signal that changes nothing answers success with a note, never a failure | P0 |
| FR5.4 | Live is opt-in per strategy; a strategy is born sandbox-only | P0 |
| FR5.5 | Kill switch that refuses inbound alerts while engaged | P0 |
| FR5.6 | Optional CIDR allowlist, closed when non-empty | P1 |
| FR5.7 | Duplicate suppression and a cooling-off window on batch starts | P1 |
| FR5.8 | A leg may be named by id or by symbol and exchange | P1 |
| FR5.9 | Signal entry claims the leg atomically before contract resolution, durable intent and dispatch; duplicate decision and stopping gate share that claim so one alert never opens two positions or enters after a stop request | P0 |
| FR5.10 | A normal signal risk exit leaves the platform-session run open so later alerts share one session P&L and audit trail | P0 |

### FR6: Scheduling
| ID | Requirement | Priority |
|----|-------------|----------|
| FR6.1 | Timed start and timed square-off on chosen weekdays | P0 |
| FR6.2 | An intraday strategy always gets a square-off, including with the scheduler off | P0 |
| FR6.3 | Jobs rebuilt from the database on every write, so the database stays authoritative | P0 |

### FR7: Durability And Recovery
| ID | Requirement | Priority |
|----|-------------|----------|
| FR7.1 | Continuous checkpoints of volatile risk state, pruned to a bound | P0 |
| FR7.2 | Open runs recovered after a restart from order rows plus checkpoints | P0 |
| FR7.3 | A rejected order is never upgraded by a checkpoint | P0 |
| FR7.4 | Malformed state with no proven exposure is finalised as `recovery_failed`; proven but unrepresentable exposure remains database-open and reserves the strategy for manual reconciliation | P0 |
| FR7.5 | Realized P&L is derived from exact priced reference groups and an exact durable zero overrides a stale checkpoint | P0 |
| FR7.6 | A durable pending stop recovers its persisted reason, entry gate and retry behavior, and finalises only when recovery proves flatness | P0 |
| FR7.7 | Recovery groups orders by `position_ref` and can represent one live plus one outgoing superseded owner per leg | P0 |
| FR7.8 | More than two held references, overlapping instruments or ambiguous proven ownership remain open, unhydrated and critical for manual reconciliation | P0 |
| FR7.9 | An unpriced fill may use checkpoint P&L only when the checkpoint witnessed the exact recovered owner shape and quantities; otherwise the known portion is retained and marked for manual reconciliation | P0 |
| FR7.10 | Positive `filled_qty` proves exposure in every status, while missing price means valuation unavailable rather than zero | P0 |

### FR8: Observability
| ID | Requirement | Priority |
|----|-------------|----------|
| FR8.1 | An event per lifecycle and risk transition, with severity | P0 |
| FR8.2 | Live frames pushed to the page over SocketIO, with a periodic read as fallback | P1 |
| FR8.3 | Broker-backed orderbook, tradebook and positions filtered to the strategy | P1 |
| FR8.4 | A refused stop recorded at critical severity with the run left open | P0 |
| FR8.5 | Detail uses broker books as primary truth for the current/latest run and explicitly labelled local strategy rows as audit fallback; no run means not requested, not broker-empty | P1 |
| FR8.6 | Missing, malformed or non-finite broker numerics render unavailable while a legitimate zero remains zero | P0 |
| FR8.7 | Broker orders/trades reconcile unique ids, aggregate multiple fills, expose local-only/ambiguous/mismatch states and keep local rejection reasons visible | P1 |
| FR8.8 | Shared account-level positions are not attributed to one strategy; strategy P&L comes from its own fills | P0 |
| FR8.9 | Local position fallback preserves lifetime residual exposure, but live leg marks value it only when the frame and selected/current run ids match | P0 |
| FR8.10 | Once stopped, Detail uses the newest finalized run for realized P&L, peak, trough, stop metadata and broker-book scope; stale live/checkpoint state cannot restore unrealized P&L | P0 |

## Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR1 | Fills arrive on the `order.update` bus and prices normally arrive over the websocket; bounded REST polling may provide a safety fallback for prices and risk. No blocking or broker I/O is allowed while a run lock is held |
| NFR2 | The risk core performs no I/O, so it is testable without a running platform and identical across consumers |
| NFR3 | Order dispatch happens outside the run lock; a critical section holds in-memory bookkeeping only |
| NFR4 | Nothing creates a database engine, thread, executor, socket or subprocess per call |
| NFR5 | Caches are bounded and invalidated; registries have a matching removal |
| NFR6 | Every schema change ships as an idempotent migration tested against a populated database |
| NFR7 | Within OpenAlgo's boundary, URL webhook credentials are redacted from standard/JSON application logs and traffic rows, suppressed in every shipped nginx access log, absent from audit payloads and API responses; operators must protect external proxies/senders and rotate credentials that may have been logged previously |

## Database Schema

| Table | Holds |
|---|---|
| `sm_strategy` | Configuration, legs, risk limits, schedule, webhook digest, live opt-in, kill switch |
| `sm_strategy_run` | One execution: mode, broker, trigger source, durable pending-stop timestamp/reason, terminal stop reason, final P&L, resolved expiries |
| `sm_strategy_order` | Every durable intent, with exact `position_ref`, broker acknowledgement, product and price type sent, fills and reject reasons |
| `sm_strategy_checkpoint` | Volatile risk state, written continuously, pruned to a bound |
| `sm_webhook_event` | Every request admitted to the webhook pipeline and its outcome; ownerless rows capped; route preflight refusals are not stored |
| `sm_strategy_event` | Lifecycle and risk transitions with severity |

## API Endpoints

**Session API** (`/strategy/api/strategies/...`): CRUD, `start`, `stop`,
`close_all`, `legs/<id>/close`, `webhook/rotate`, `live`, `kill_switch`,
`unlock_webhook`, and the reads `runs`, `orders`, `events`, `webhook_events`,
`checkpoints`, `orderbook`, `tradebook`, `positions`.

**Public webhook**: `POST /strategy/webhook/<token>`.

**API-key surface** (`/api/v1/strategy/`): `list`, `status`, `start`, `stop`,
`close_all`, `close_leg`, `runs`, `orders`, `events`.

## Deliberately Not Built

| Item | Why |
|---|---|
| LIMIT, SL and SL-M entries | Neither the strategy nor a leg carries a price, so such an order would go out priced at zero. MARKET only until there is a price to send |
| Expiry ranks on a signal leg | A signal leg names its own contract. A base symbol is refused rather than resolved, so no order is placed for a symbol the master contract does not list |
| Account-level risk caps across strategies | The core supports it; nothing aggregates across strategies yet |
| Re-checking room ownership after a join | Ownership is checked on the join and not re-checked, so a socket connected before a logout keeps receiving until it disconnects. Low on a single-user deployment |
| Webhook audit on the strategy page | The session endpoint can read audit rows, but Detail does not fetch or render them yet |
| Webhook IP-allowlist editor | The backend field and enforcement exist, but the wizard currently creates `null` and exposes no editor |

## Related Documentation

- [`../prompt/strategy_rms_documentation.md`](../prompt/strategy_rms_documentation.md) - the service reference, module by module
- [`../api/strategy-services/`](../api/strategy-services/) - the public endpoint reference
- [`../bdd/strategy_module_rms.feature`](../bdd/strategy_module_rms.feature) - behaviour specifications
- [`../prompt/order-constants.md`](../prompt/order-constants.md) - exchange, product, price-type and action codes
- [`../prompt/symbol-format.md`](../prompt/symbol-format.md) - the symbol format every leg resolves to

## Key Files Reference

| Path | Role |
|---|---|
| `blueprints/strategy_module.py` | Session API, validator, public webhook, SocketIO rooms |
| `restx_api/strategy.py` | API-key surface |
| `services/strategy_module/` | Engine, signals, dispatch, risk adapter, resolver, scheduler, recovery, feed, views |
| `services/risk/` | The shared decision core |
| `database/strategy_module_db.py` | Six tables, store functions, vocabularies |
| `upgrade/migrate_strategy_module.py` | Schema migration, tables and later columns |
| `frontend/src/pages/strategy/` | List, wizard and detail pages |

## Success Metrics

| Metric | Target |
|---|---|
| A position is never held with nothing evaluating its stop | Zero occurrences |
| A single alert never becomes two positions | Zero occurrences |
| A stop never reports terminal flatness before every exact owner is confirmed flat | Zero occurrences |
| Every flip/recovery fill settles the exact durable `position_ref` it belongs to | Zero cross-owner applications |
| Proven exposure that cannot be represented is never released for reuse | Run remains database-open, strategy reserved, critical manual-reconciliation event |
| Missing valuation evidence is never displayed or persisted as an invented zero | Unavailable or known partial value with explicit critical reconciliation context |
| An order never goes out with a product its venue refuses | Zero occurrences |
| An open run survives a restart and the session boundary | Recovered with side, entry and stop intact |
| Risk rules agree between Python and the TypeScript copy | `test/risk/vectors.json` passes both |
