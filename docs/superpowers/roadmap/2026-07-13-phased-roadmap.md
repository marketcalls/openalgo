# Phased Roadmap — P0A → P7

**Date:** 2026-07-13 · **Resequenced** after the
[Codex deep audit](../reviews/2026-07-13-codex-review-2-response.md)
**Companion:** [design](../specs/2026-07-13-global-market-architecture-design.md) ·
[audit](../audit/2026-07-13-sitewide-coupling-audit.md)

Each phase is its own **spec → plan → implementation** cycle. Convention:
**34 broker adapters = 33 legacy Indian integrations + Delta.** `IN + crypto`
built live; `US + crypto-spot` model-only. Every phase keeps the golden fixtures
green.

## Dependency graph

```
P0A ─► P0B ─► P1 ─► P1.5(Delta) ─► P2 ─► P3 ─► P4 ─► P5 ─► P6 ─► P7
                └────────────────────────┴─► (P4 also feeds P5, P6)
```

## P0A · Architecture consistency & inventories
- **Goal:** one coherent design + a true coupling map before any code.
- **Deliverables:** reconcile **every** doc to the 5-axis model / per-resolver
  keys / extend-existing-capabilities / TIF-not-flags / alias-not-duplicate;
  evolve `coupling_inventory.py` into an **AST/schema inventory suite** (checked-in
  JSON, classified by owner + target phase) covering **all** top-level folders and
  **semantic** coupling (broker-name switches, int coercions, Float/Decimal, fixed
  column lengths, tz arithmetic, symbol parsing, plugin-lifecycle, migration
  coverage, WS static registration); enumerate all **34 adapters** and **every
  order-entry surface** (REST, smart/basket/split/options/GTT (experimental), UI, Flow,
  strategies, webhooks, MCP, scalping, action center, sandbox).
- **Depends:** —
- **Done when:** no doc contradicts the spec; inventory JSON reproducible via
  `uv run python …`.

## P0B · Compatibility & migration foundation
- **Goal:** make "zero breaks" enforceable.
- **Deliverables:** define compatibility **per surface** — `/api/v1` = semantic
  JSON compat (existing keys/values/types unchanged; responses may gain keys);
  byte-identity only for **rendered symbols**; WS topics/schemas preserved; new
  DTOs stay internal. Add **golden semantic fixtures** (Indian **and** Delta:
  perp `BTCUSDFUT`, dated, option, spot — REST + mapping + WS payloads);
  **old-DB migration tests**; a **versioned migration ledger** with dependency
  ordering, **atomic/fail-stop** behavior (fix `start.sh:291` swallowing failures
  and `migrate_all.py` central list), backup/recovery policy, and **plugin
  migration discovery**.
- **Depends:** P0A
- **Done when:** CI runs the golden + old-DB tests and fails on any regression;
  a failed migration **halts** startup.

## P1 · Public plugin boundary
- **Goal:** a stable, importable contract + a unified registry.
- **Deliverables:** publish/import a **distributable contract package**
  (e.g. `openalgo-broker-api`) — today `pyproject.toml` ships `packages = []`;
  a **unified broker registry** covering auth, credentials, master-contract,
  REST/data, streaming, migrations, config — replacing the hard-coded dispatch in
  `brlogin.py`, `auth_utils.py`, `websocket_proxy/__init__.py`, `broker_factory.py`
  (and removing the arity-sniffing in `quotes_service.py:125`). **Required minimal
  protocol + optional protocols** (`HistoricalData`, `Depth`,
  `GTT` *(experimental — 2 brokers, never required)*, `OptionsChain`, `Holdings`)
  with a standard `UnsupportedCapability`; **typed
  errors** (auth-expired / permission / unsupported / rate-limited+retry-after /
  transient / permanent-reject) and **client-order-id idempotency**; structured
  order model (type × TIF × exec-flags × conditional); manifest as **versioned
  JSON Schema** constrained by venue/segment/kind; conformance shim for the 34
  adapters; entry-point loader with semver gating. WS lifecycle contract preserves
  cleanup/reconnect/idempotent-sub/batching/backpressure/health/snapshot-vs-delta
  + shared-feed & FD-hygiene (fix the depth-mode doc discrepancy).
- **Depends:** P0B
- **Done when:** the 34 adapters conform (via shim); a clean-env sample plugin
  imports the contract package and loads.

## P1.5 · Delta reference adapter  *(moved up)*
- **Goal:** prove the contract against a real non-Indian broker **before**
  building more layers on it.
- **Deliverables:** implement Delta as a native adapter to the full contract —
  auth, data, streaming, **Decimal precision** — end to end; make the adapter
  entry points explicit and drop the `deltaexchange_adapter.py` **alias** once the
  registry no longer needs the naming convention; fix the `BTCUSDFUT` vs stale
  `.P` comment/alias inconsistency.
- **Depends:** P1
- **Done when:** Delta trades/streams through the contract with no core `if broker
  == …`.

## P2 · Instrument identity & storage
- **PREREQUISITE — `SymToken` schema ownership.** 34 `class SymToken` defs +
  shared `database/symbol.py` + `token_db_enhanced` cache. Decide shared base/mixin
  vs per-broker, centralized migration, downloader compatibility, cache
  serialization.
- **Deliverables:** the 5-axis model + renderers (Indian byte-identical; crypto
  dated/option reuse; perp/spot new); full identity — stable internal IDs,
  base/quote/settlement ccy, underlying ID, right/exercise style, settlement,
  linear/inverse/quanto, multiplier/min-qty/min-notional, expiry instant+tz,
  listing/status; **Decimal/step/min-notional** columns; a **backfill algorithm
  with ambiguity reporting + quarantine** (not a blind 100% round-trip assertion).
- **Depends:** P1.5
- **Done when:** every reconstructable row round-trips; ambiguous rows are
  quarantined and reported.

## P3 · Order semantics — every entry surface
- **Deliverables:** manifest-driven validation (collapse `schemas.py` +
  `constants.py`); append-only order-type/TIF/exec-flag extension; apply across
  **all** surfaces enumerated in P0A (REST, smart/basket/split/options/GTT (experimental), UI,
  Flow, strategies, webhooks, MCP, scalping, action center, sandbox).
- **Depends:** P2
- **Done when:** Indian brokers accept exactly today's set; crypto accepts
  `reduce_only`; a US manifest rejects `NRML` with a typed error; golden green.

## P4 · Runtime policies
- **Deliverables:** resolvers **each keyed on its own dimension** — calendar =
  venue+segment, tick/lot = instrument, currency = value/account/instrument,
  rate-limit = broker+endpoint+weight (concurrency + response headers + backoff +
  safe/unsafe retry), margin = account+instrument+margin-mode; **canonical
  time-series contract** (UTC epoch, exchange-local tz, session date, candle
  convention, ranges, DST, 24/7 boundaries); **auth/session policy** per broker
  (lifetime/tz, refresh window, feed-token, revocation, callback state, flow).
  Build IN + crypto; US stubs.
- **Depends:** P1 (+P2, P3)
- **Done when:** dashboards/alerts/history render correctly for IN + Delta; no
  `₹`/`Asia/Kolkata`/`+5:30` literal in core paths.

## P5 · Sandbox replatform
- **Goal:** the sandbox works for any market — **schema + execution changes, not
  just wiring.**
- **Deliverables:** fractional quantities (Integer→Decimal in `sandbox_db`,
  `strategy_db`, `chartink_db`), high-precision prices, contract multipliers,
  quote/settlement currency, **partial fills**, fees, funding, liquidation,
  isolated-vs-cross margin, explicit 24/7 daily accounting boundaries; wire to the
  resolvers.
- **Depends:** **P2, P3, P4**
- **Done when:** a crypto sandbox account holds USDT capital, fills fractionally,
  never IST-squares-off; Indian sandbox unchanged.

## P6 · Frontend capability rendering
- **Deliverables:** extend the existing `/capabilities` + `brokerStore` +
  `useSupportedExchanges`; versioned capability schema; **fail-closed** on
  capability-load failure (today `brokerStore.ts` silently shows all exchanges);
  tool requirements derived centrally from `data_caps` + per-tool plumbing.
- **Depends:** P1, P3, P4
- **Done when:** crypto broker auto-morphs the UI; capability-load failure shows a
  health error, not all-exchanges; Indian UI unchanged.

## P7 · Second out-of-tree proof
- **Deliverables:** clean-environment **package installation** of an out-of-tree
  broker; paper adapters for a second crypto venue + US edge cases (DST, OCC,
  Reg-T).
- **Depends:** P1–P6

## Cross-phase invariants
- Golden semantic fixtures stay green (Indian + crypto).
- ZMQ bus invariant, single-worker eventlet, FD-hygiene untouched.
- No broker rewrites to ship a phase (shim covers back-compat).
