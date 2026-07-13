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
- **Deliverables:** this design set; golden-master fixtures (current `/api/v1`
  responses + rendered symbols for equity/future/option across
  NSE·NFO·MCX·CDS·BSE); domain-type skeleton (`Market/Segment/AssetClass/
  Instrument` dataclasses/Protocols, no behavior yet).
- **Depends:** —
- **Done when:** golden tests run in CI and pass against current `main`
  unchanged.

## P1 · Broker Adapter Contract
- **Goal:** the versioned public plugin API + back-compat shim.
- **Deliverables:** `BrokerAdapter` Protocol; `plugin.json` v2 Capability
  Manifest schema; conformance shim wrapping all 33 brokers (+ auto-generated
  Indian manifests); `broker_conformance` test suite; out-of-tree entry-point
  loader with semver version-gating.
- **Depends:** P0
- **Done when:** all 33 brokers load through the shim with identical behavior; a
  trivial out-of-tree sample broker loads via entry-point; conformance suite
  green.

## P2 · Domain model & symbol renderer
- **Goal:** structure underneath the string, byte-identical on top.
- **Deliverables:** `Market/Segment/AssetClass/Instrument` model; per-asset-class
  renderers (Indian equity/future/option byte-identical; crypto base+quote; US
  reuses Indian option/equity); `SymToken` additive columns (`asset_class`,
  `market`, `quote_ccy`, …) with additive migration; round-trip tests.
- **Depends:** P0
- **Done when:** `render(structure(symbol)) == symbol` for 100% of existing
  `SymToken` rows; new migration is additive & reversible.

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
  resolvers as Market-selected strategies; migrate the ~55 hardcoded `₹/IST/tick`
  sites to resolve from metadata. Build IN + crypto strategies; US strategies are
  interface stubs. Margin: IN (SPAN/exposure) + crypto (leverage/isolated-cross).
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
- **Deliverables:** `GET /api/v1/config` (additive); migrate the 85 coupled React
  files to read markets/exchanges/products/currency/calendar from it;
  capability-gate the `/tools` options suite (visible only when the active market
  has OPTION + data).
- **Depends:** P1, P3, P4
- **Done when:** connecting a crypto broker auto-morphs the UI (crypto markets,
  USDT, perp/spot, post-only/reduce-only, 24/7) with no forked screens; Indian UI
  visually unchanged.

## P7 · Delta Exchange cleanup (proof exemplar)
- **Goal:** validate the whole contract against a real non-Indian broker.
- **Deliverables:** refactor `broker/deltaexchange/` to a native `BrokerAdapter`
  (remove the duplicate `delta_adapter.py`/`deltaexchange_adapter.py`); author a
  full crypto manifest; validate a second crypto venue on paper. Delta is the
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
