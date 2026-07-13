# Phased Roadmap — P0 → P7

**Date:** 2026-07-13
**Companion:** [design](../specs/2026-07-13-global-market-architecture-design.md) ·
[audit](../audit/2026-07-13-sitewide-coupling-audit.md)

Each phase is its own **spec → plan → implementation** cycle. `IN + crypto` are
built live throughout; `US + crypto-spot` are contract + paper-validated only
(model-only). Every phase must keep the golden-master snapshots green.

## Dependency graph

```
P0 ─┬─► P1 ──► P3 ──┐
    └─► P2 ──┐      ├─► P6 (frontend)
             ├─► P4 ─┼─► P5 (sandbox)
             │       └─► P7 (Delta cleanup)
```

## P0 · Foundations & guardrails
- **Goal:** make "additive" enforceable before touching anything.
- **Deliverables:** this design set; **audit-correction step** — pin
  `python docs/superpowers/audit/coupling_inventory.py` output at a known commit
  so counts are reproducible; golden-master fixtures for **both** the Indian set
  (equity/future/option across NSE·NFO·MCX·CDS·BSE) **and the live Delta/crypto
  set** (perpetual `BTCUSDFUT`, dated `…FUT`, option `…CE/PE`, spot `BTCINR`) —
  REST responses, mapping output, and WebSocket payloads; domain-type skeleton
  (Venue/Market/Segment/UnderlyingAssetClass/InstrumentKind/Instrument
  dataclasses/Protocols, no behavior yet).
- **Depends:** —
- **Done when:** golden tests (Indian **and** crypto) run in CI and pass against
  current `main` unchanged.

## P1 · Broker Adapter Contract
- **Goal:** the versioned public plugin API + back-compat shim.
- **Deliverables:** `BrokerAdapter` Protocol covering the **full surface** — not
  just data/order methods but the **auth model (API-key/OAuth AND
  wallet-signature for Hyperliquid), declared credential schema,
  login/OAuth-callback flow, master-contract scheduling, owned migrations, and
  broker config**; the structured order model (type × time-in-force × exec-flags ×
  conditional); `plugin.json` v2 manifest schema (extending the existing
  `get_broker_capabilities`); conformance shim wrapping all 33 brokers (+
  auto-generated Indian manifests); `broker_conformance` suite; out-of-tree
  entry-point loader with semver version-gating.
- **Depends:** P0
- **Done when:** all 33 brokers load through the shim with identical behavior;
  **Delta is validated through the contract too** (even if its cleanup stays P7); a
  trivial out-of-tree sample broker loads via entry-point; conformance suite green.

## P2 · Domain model & symbol renderer
- **Goal:** structure underneath the string, byte-identical on top.
- **PREREQUISITE — `SymToken` schema ownership.** There are **34** `class
  SymToken` definitions in `broker/`, **1** shared in `database/symbol.py`, plus
  the `token_db_enhanced` cache representation. Decide the ownership model (shared
  base/mixin vs per-broker), the centralized migration path, compatibility with
  all 34 master-contract downloaders, and cache serialization — **before** adding
  columns.
- **Deliverables:** the five-axis model
  (Venue/Market/Segment/UnderlyingAssetClass/InstrumentKind/Instrument);
  per-InstrumentKind renderers (Indian equity/future/option byte-identical; crypto
  dated-future/option **reuse** the Indian renderers; perpetual `[sym]FUT`, spot
  `[base][quote]`; US reuses option/equity); `SymToken` additive columns with
  **Decimal/step/min-notional** precision (not `Float`) and additive migration;
  round-trip tests (Indian **and** crypto).
- **Depends:** P0
- **Done when:** `render(structure(symbol)) == symbol` for 100% of existing
  `SymToken` rows (Indian + Delta); migration additive & reversible.

## P3 · Order semantics
- **Goal:** one manifest-driven order vocabulary.
- **Deliverables:** manifest-driven validation replacing the static global enums;
  collapse the two sources of truth (`restx_api/schemas.py` inline literals +
  `utils/constants.py`) into the manifest; append-only extension mechanism for
  new order/product types & flags (`post_only`, `reduce_only`, `IOC`, `FOK`,
  bracket).
- **Depends:** P1
- **Done when:** Indian brokers accept exactly today's set; a crypto broker
  accepts `reduce_only`; a US-manifest broker rejects `NRML` with a clear error;
  golden tests green.

## P4 · Resolvers
- **Goal:** market-aware cross-cutting concerns, no hardcoding.
- **Deliverables:** `Currency`, `Calendar/TZ`, `Tick/Lot`, `Rate-limit`, `Margin`
  resolvers — **each keyed on its own dimension**, not a uniform "Market":
  calendar = venue+segment (Indian sessions already differ per exchange),
  tick/lot = instrument, currency = value/account/instrument, rate-limit =
  broker+endpoint+weight, margin = account+instrument+margin-mode. Migrate the
  hardcoded `₹/IST/tick` sites to resolve from metadata. Build IN + crypto; US
  stubs. Margin: IN (SPAN/exposure) + crypto (leverage/isolated-cross).
- **Depends:** P1, P2
- **Done when:** live dashboards/alerts render correct currency & sessions for IN
  and Delta; no `₹`/`Asia/Kolkata` literal remains in `services/`/`utils` core
  paths (moved to the IN strategy).

## P5 · Sandbox globalization  *(added from audit)*
- **Goal:** the sandbox engine works for any market.
- **Deliverables:** wire `sandbox/` to the resolvers — multi-currency capital
  (Currency), session-vs-24/7 square-off (Calendar; crypto = none, define
  funding-time handling), leverage margin (Margin). Replace ₹1 Cr / IST /
  Indian-margin hardcoding.
- **Depends:** P4
- **Done when:** a crypto sandbox account holds USDT capital, never force-squares
  off on IST close, and applies leverage margin; Indian sandbox behavior
  unchanged.

## P6 · Frontend decoupling  *(added from audit)*
- **Goal:** UI renders capability; kill the partial fork.
- **Deliverables:** **extend the existing capability substrate** — the
  authenticated `GET /capabilities` (`blueprints/broker_credentials.py:356`),
  `brokerStore.ts`, and `useSupportedExchanges.ts` — rather than adding a parallel
  source. Only add an external `/api/v1/config` if a real external-API consumer
  needs one (decide in this spec). Migrate the coupled React files (58 signal + 69
  exchange-code, per `coupling_inventory.py`) to read from the extended
  capabilities response; **capability-gate `/tools` on the manifest's `data_caps`**
  (quote/history/option-chain/oi/greeks/depth) **plus per-tool plumbing** — the
  current hook already excludes MCX/CDS for missing plumbing
  (`useSupportedExchanges.ts:67`), which the model must express (not just "has
  OPTION").
- **Depends:** P1, P3, P4
- **Done when:** connecting a crypto broker auto-morphs the UI (crypto markets,
  USDT, perp/spot, post-only/reduce-only, 24/7) with no forked screens; Indian UI
  visually unchanged.

## P7 · Delta Exchange cleanup (proof exemplar)
- **Goal:** validate the whole contract against a real non-Indian broker.
- **Deliverables:** refactor `broker/deltaexchange/` to a native `BrokerAdapter`;
  **make the adapter module/class entry points explicit, then remove the
  compatibility alias** (`delta_adapter.py` vs `deltaexchange_adapter.py`) **only
  if no longer referenced** — don't blind-delete; fix the perpetual
  **comment/code/alias inconsistency** (`BTCUSDFUT` vs stale `.P`); author a full
  crypto manifest; validate a second crypto venue on paper. Delta is the
  **reference native crypto adapter** ([ADR-0001](../decisions/2026-07-13-crypto-native-integration-not-ccxt.md))
  that Binance/CoinDCX/Hyperliquid follow — no CCXT.
- **Depends:** P1–P4
- **Sequencing note:** placed last as the culminating proof. **Alternative:** pull
  forward to run right after P1 to de-risk the contract against a live
  non-Indian broker earlier — a reasonable trade the team may prefer. *(Open
  question flagged for review.)*

## Cross-phase invariants (must hold every phase)

- Golden-master snapshots stay byte-identical.
- ZMQ bus invariant (SUB binds, PUBs connect), single-worker eventlet model, and
  FD-hygiene conventions are untouched.
- No broker rewrites required to ship a phase (shim covers back-compat).
