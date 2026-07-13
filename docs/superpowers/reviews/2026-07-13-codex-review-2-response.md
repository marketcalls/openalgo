# Review Response 2 — Codex deep audit (2026-07-13)

A second, deeper Codex audit against the codebase + `CLAUDE.md` invariants. I
independently verified every checkable claim. **Verdict: all confirmed.** The
architecture direction holds, but the design was **not implementation-ready**;
this round hardens it. Convention adopted throughout: **34 broker adapters =
33 legacy Indian integrations + Delta.**

## Critical blockers

| # | Finding | Verdict | Evidence | Resolution → phase |
|---|---------|---------|----------|--------------------|
| 1 | Docs internally inconsistent | **Confirmed** | `README` + `problem` still say `Market→Segment→AssetClass`; `problem` says "Market-selected resolvers"/85 files/new `/api/v1/config`; roadmap P3 lists `IOC/FOK` as "flags"; audit calls Delta a "duplicate" | Reconciled all four docs → the 5-axis model, per-resolver keys, extend-existing-capabilities, TIF-not-flags, **alias-not-duplicate** |
| 2 | Out-of-tree plugins not currently possible | **Confirmed** | `pyproject.toml:196` `packages = []` "not a distributable package"; broker-name switch `brlogin.py:73`; `f"broker.{broker}…"` in `auth_utils.py:283`; eager in-tree imports `websocket_proxy/__init__.py:30`; fixed naming `broker_factory.py:53` (the very reason the Delta **alias** exists) | P1 reframed: needs a **distributable contract package** + a **unified broker registry** (auth/credentials/master-contract/data/streaming/migrations/config), not just an entry-point loader |
| 3 | "Zero breaks" not enforceable | **Confirmed** | CI runs a "CI-safe subset" (`ci.yml`), no golden tests; migrations are a hardcoded central list (`migrate_all.py`); `start.sh:291` `… || echo "completed"` **continues after migration failure** | Split into **P0A** (consistency+inventory) and **P0B** (compat definition + migration ledger, fail-stop, old-DB tests); define compatibility **per surface** |
| 4 | Fractional/sandbox underestimated | **Confirmed** | `sandbox_db.py:66` `quantity Integer`, `price DECIMAL(10,2)`; `:75` "no partial fills"; `:188` single INR account; `order_manager.py:74` & `fund_manager.py` cast qty to `int`; `strategy_db`/`chartink_db` integer qty | P5 is a **replatform** (schema + execution), now depends on **P2+P3+P4** |

**Compatibility contradiction (blocker 3):** "byte-identical" + "add optional
fields" + "introduce Decimal" cannot all hold. **Redefined per surface:**
`/api/v1` = *semantic JSON compatibility* (existing keys/values/types unchanged;
responses may gain keys); *byte-identity* applies only to **rendered symbol
strings**; WebSocket topics/payload schemas preserved; new normalized DTOs stay
**internal** (behind adapters), never exposed on `/api/v1`.

## High-priority gaps (all confirmed)

| # | Finding | Evidence | Resolution → phase |
|---|---------|----------|--------------------|
| 5 | Contract needs required + capability-conditional protocols | Only `dhan`/`zerodha` have `gtt_api.py`; `quotes_service.py:125` inspects `__init__` **arity** for feed-token | P1: minimal required protocol + optional `HistoricalData/Depth/GTT(experimental)/OptionsChain/Holdings` + `UnsupportedCapability` + DTO schemas; kill arity-sniffing |
| 6 | No error/retry/idempotency contract | (design gap) | P1: typed errors (auth-expired, permission, unsupported, rate-limited+retry-after, transient, permanent-reject) + **client-order-id idempotency** (retry must not double-place); rate-limit = weights+concurrency+headers+backoff+safe/unsafe |
| 7 | Auth lifetime ≠ market calendar | `session.py:13` global 03:00 IST rollover; `auth_db.py:102` TTL vs IST; `:179` 4 generic aux fields | P4: explicit per-broker **auth/session policy** (lifetime/tz, refresh window, feed-token, revocation, callback state, flow type, master-contract schedule); richer credential schema |
| 8 | No canonical time-series contract | `zerodha/api/data.py:518` adds 5:30; `download/sqlite_downloader.py:78` labels −5:30 "UTC→IST" | P4: canonical UTC epoch, exchange-local tz, session date, candle open/close convention, inclusive/exclusive ranges, DST, 24/7 daily boundaries |
| 9 | Manifest too coarse + **fails open** | `data_caps:{history:true}` can't express intervals/ranges/depth-levels; `brokerStore.ts` catch → "fall back to showing all exchanges" | P1: capabilities constrained by venue/segment/kind, versioned JSON Schema; P6: **fail-closed** capability-health error |
| 10 | Instrument identity + backfill incomplete | round-trip test assumes flat rows always reconstruct; many lack info | P2: full identity (stable IDs, base/quote/settlement ccy, underlying ID, right/exercise, settlement, linear/inverse/quanto, multiplier/min-qty/min-notional, expiry instant+tz, listing/status); **backfill algorithm + ambiguity reporting + quarantine** — not a 100% assertion |
| 11 | WebSocket needs its own contract | `base_adapter.py:97` `BaseBrokerWebSocketAdapter(ABC)` already exists; depth-mode docs disagree (`mode_utils` canonical = 1/2/3) | Narrow "no formal contract" → **"no unified full-lifecycle contract"**; WS contract preserves cleanup/reconnect/idempotent-sub/batching/backpressure/health/snapshot-vs-delta/sequence + shared-feed & FD-hygiene; fix depth-mode doc |

## Methodology gap (confirmed)

`coupling_inventory.py` scans **9 dirs**, but the audit claims "every top-level
folder." It also misses **semantic** coupling (broker-name switches, int
coercions, Float/Decimal, fixed column lengths, tz arithmetic, symbol parsing,
plugin-lifecycle assumptions, migration coverage, WS static registration). →
Evolve into an **AST/schema inventory suite** with checked-in JSON (classified by
owner + target phase). Command corrected to `uv run python`.

## Resequenced roadmap

P0A (consistency + full inventory) → P0B (compat + migration foundation) → P1
(public plugin boundary: package + unified registry + conditional protocols +
errors/idempotency) → **P1.5 (Delta reference adapter — moved up to prove
auth/data/streaming/precision early)** → P2 (instrument identity + storage +
backfill) → P3 (order semantics across **every** entry surface: REST, smart/
basket/split/options/GTT (experimental), UI, Flow, strategies, webhooks, MCP, scalping, action
center, sandbox) → P4 (runtime policies: calendar/time-series, currency, auth/
session, rate limits, margin) → P5 (sandbox replatform) → P6 (frontend, versioned
schema, fail-closed) → P7 (second out-of-tree proof in a clean environment).

See the [roadmap](../roadmap/2026-07-13-phased-roadmap.md) for the detailed phases.
