# Global-Market Architecture — Design

**Date:** 2026-07-13
**Status:** design, awaiting verification (no code yet)
**Companion docs:** [audit](../audit/2026-07-13-sitewide-coupling-audit.md) ·
[roadmap](../roadmap/2026-07-13-phased-roadmap.md)

## 1. Context & goals

OpenAlgo is production software for ~200,000 users, today centered on Indian
equity & F&O across 33 brokers. We are adding crypto (Delta Exchange live;
Binance/CoinDCX/Hyperliquid planned) and US brokers (IBKR/Alpaca planned), and
want *any* venue in *any* country to be pluggable.

The layering is already sound — **broker plugins → `services/` (internal API) →
`restx_api/` (`/api/v1`) → `websocket_proxy/`**. The problem is not the layers;
it is that **Indian-market assumptions leak through all of them**. This design
lifts those assumptions into a **normalized domain core** that the existing
Indian behavior falls out of as a special case.

**Success criteria**

- A third party can ship a broker for any market as an out-of-tree package
  against a documented, versioned contract, and self-certify it.
- Adding a market is *data + strategies*, not edits scattered across 55 files.
- Existing Indian users observe **no change** — proven in CI, not asserted.

## 2. The four locked decisions

1. **Additive, zero breaks** — the global model is a *superset*; today's Indian
   format/constants/`/api/v1` are byte-identical special cases.
2. **Out-of-tree plugins** — a versioned public `BrokerAdapter` contract;
   discovery via entry-points; a shipped conformance suite; plugins are *trusted
   code* (no sandboxing in v1 — consistent with the self-hosted, single-user
   security model).
3. **Model four, build two** — model & paper-validate Indian F&O, crypto
   derivatives, crypto spot, US equity/options; build live only **IN + crypto
   derivatives**.
4. **Normalized domain core** — structured instrument underneath; flat symbol is
   a byte-identical rendering on top; cross-cutting concerns resolve from
   metadata.

## 3. Layered target architecture

Indian coupling is pulled out of the individual layers and consolidated into a
**normalized core** between `services/` and the broker plugins:

```
External API   restx_api/        /api/v1 unchanged  + optional fields / new codes / new endpoints
Symbol Renderer (new)            structure → string; Indian = byte-identical; crypto/US renderers
Internal API   services/         same orchestration; calls BrokerAdapter; cross-cutting via resolvers
Domain Core    (new)             Market → Segment → AssetClass → Instrument
Capability Manifest  plugin.json v2   asset classes · order types · leverage · sessions · rate limits
Resolvers      (new)             Currency · Calendar/TZ · Tick/Lot · Rate-limit · Margin
Broker Adapters                  formal versioned Protocol; 33 existing wrapped via shim; out-of-tree loader
Symbol DB      SymToken (+cols)  same table + additive columns
Feed           websocket_proxy/  ZMQ fan-in unchanged; streaming part of adapter contract
```

Nothing in the existing layers is removed; new layers are inserted and existing
ones gain additive behavior.

## 4. Domain model

A small structured identity underneath the flat symbol:

- **Market** (`IN`, `CRYPTO-DELTA`, `US`) — carries base currency, timezone,
  trading calendar, rate-limit profile, margin regime.
- **Segment** (`NSE-EQ`, `NSE-FO`, `MCX`, `perp`, `spot`, `US-OPT`) — session
  hours, settlement, lot/tick conventions.
- **AssetClass** (`EQUITY`, `FUTURE`, `OPTION`, `PERPETUAL`, `SPOT`) — defines
  which fields are meaningful and which **renderer** to use.
- **Instrument** — a concrete tradable = one `SymToken` row (base ·
  quote/underlying · expiry? · strike? · right? · lot · tick · multiplier ·
  broker token).

### Symbol rendering

`Instrument → OpenAlgo symbol` is deterministic per asset class:

| Shape | Asset class | → symbol | exchange | Renderer |
|-------|-------------|----------|----------|----------|
| Indian index option | OPTION | `NIFTY28MAR2420800CE` | NFO | **byte-identical** |
| Indian future | FUTURE | `BANKNIFTY24APR24FUT` | NFO | **byte-identical** |
| Indian equity | EQUITY | `INFY` | NSE | **byte-identical** |
| Crypto perpetual | PERPETUAL | `BTCUSDT` | CRYPTO | new (`base+quote`) |
| Crypto spot | SPOT | `ETHUSDT` | CRYPTO | new (`base+quote`) |
| US option | OPTION | `AAPL17JAN25190CE` | US-OPT | **reuses OPTION renderer** |
| US equity | EQUITY | `AAPL` | US | **reuses EQUITY renderer** |

**Two safety principles:**

1. **Rendering is one-way.** Instrument → string only. The reverse (string →
   instrument) is the existing `SymToken` DB lookup — we never parse an ambiguous
   string at runtime.
2. **The public `exchange` field never changes.** `NSE`/`NFO`/`CRYPTO` stay as
   callers send them; internally each resolves to a `(Market, Segment)` pair. The
   Indian OPTION & EQUITY renderers generalize to US unchanged; only crypto adds
   one renderer.

## 5. Broker Adapter Contract

### 5.1 The `BrokerAdapter` Protocol (versioned, public)

Methods take & return **normalized domain types** (OpenAlgo order dict,
`Instrument`, `Quote`); each broker's existing `mapping/` layer converts to
broker-native internally.

| Group | Methods |
|-------|---------|
| auth | `authenticate` · `refresh_session` · `validate_session` |
| orders | `place` · `modify` · `cancel` · `cancel_all` |
| portfolio | `positions` · `holdings` · `orderbook` · `tradebook` · `funds` · `margin` |
| data | `quote` · `depth` · `history` · `intervals` |
| instruments | `download_master_contract` → `Instrument` rows |
| streaming | `connect` · `subscribe` · `unsubscribe` |
| manifest | `capabilities()` → Capability Manifest |

### 5.2 Capability Manifest (`plugin.json` v2)

Each broker *declares* what it supports:

```yaml
contract_version: "1.0"
markets: [IN]                 # crypto: [CRYPTO-DELTA]
asset_classes: [EQUITY, FUTURE, OPTION]
product_types: [CNC, NRML, MIS]
order_types:   [MARKET, LIMIT, SL, SL-M]
order_flags:   []             # crypto: [post_only, reduce_only, IOC, FOK]
leverage: false
base_currency: INR
timezone: Asia/Kolkata
calendar: IN
rate_limits: { orders_per_sec: 10 }
streaming: { modes: [ltp, quote, depth], max_symbols: 3000 }
```

Core validates each request against the **active broker's manifest** — a US
broker rejects `NRML`, a crypto broker accepts `reduce_only` — **with no
per-broker `if` in core.** This is an approved behavior change: valid Indian
requests on Indian brokers are unaffected; invalid cross-market requests are
rejected **upfront with a clear error** instead of failing deep in the broker
call. It also collapses the two enum sources of truth
(`schemas.py` + `constants.py`) into one.

### 5.3 Loading & conformance

- **In-tree** — `broker/{name}/` as today (via `plugin.json`).
- **Out-of-tree** — a pip package registers under the `openalgo.brokers`
  entry-point group (or drops into a `plugins/` dir). No core edits to add a
  broker.
- **Version-gated** — each plugin declares `contract_version`; core checks semver
  compatibility at load and refuses a mismatch with a clear error.
- **Self-certify** — a shipped `broker_conformance` suite proves an adapter
  satisfies the contract before publishing.
- **Conformance shim (back-compat)** — the 33 existing brokers are **not
  rewritten**. A shim wraps their existing `place_order`/`get_margin_data`/…
  functions to present the new interface and auto-generates a v2 manifest
  (defaults: `markets:[IN]`, Indian product/order types). Ship day one; migrate
  individual brokers to native adapters later.

## 6. Resolvers (cross-cutting concerns)

Five strategy services, **selected by Market**, that answer questions hardcoded
today. They read Market/Segment metadata + `SymToken` + the manifest.

| Resolver | Replaces today | IN (build) | CRYPTO (build) | US (interface only) |
|----------|----------------|------------|----------------|---------------------|
| Currency | `₹` hardcode, `number_formatter` Cr/L | INR · ₹ · Lakh/Crore | USDT/USD · thousands | USD · $ · thousands |
| Calendar+TZ | IST, 09:15/15:30, Asia/Kolkata | NSE sessions+holidays | 24/7 · no square-off | NYSE ET + US holidays |
| Tick/Lot | scattered rounding | tick+lot from `SymToken` | fractional base qty · price precision | fractional shares |
| Rate limit | global/Indian throttle | orders/sec per broker | weight-based (Binance) | broker-specific |
| Margin | Indian SPAN+exposure only | SPAN+exposure | leverage · isolated/cross | Reg-T / PDT |

**Principles:** each resolver is a strategy object chosen by Market (no
`if broker == …` in core); **live trading and the sandbox consume the same
resolvers**, so globalizing `sandbox/` is mostly wiring it to these. Margin is
built for **IN + crypto**; US Reg-T is interface-only.

## 7. Frontend decoupling

The UI renders capability rather than holding it. One new additive endpoint,
`GET /api/v1/config`, returns the active broker's
`markets/exchanges/asset_classes/product_types/order_types/order_flags/currency/
calendar`. React reads it instead of hardcoded arrays.

| UI concern | Today | After (driven by) |
|------------|-------|-------------------|
| Exchange/market dropdown | NSE/NFO arrays in JS | `config.markets + exchanges` |
| Product/price selectors | CNC/NRML/MIS, MARKET/LIMIT/SL | `config.product_types/order_types` (+ `order_flags`) |
| Currency display | `₹` + Cr/L in JS | `formatCurrency(v, config.currency)` |
| Market-hours widget | IST 09:15–15:30 | `config.calendar` (crypto → 24/7) |
| Option chain / strike | CE/PE assumed | asset-class gated; `right ∈ {CE,PE,C,P}` |
| Options tools `/tools` ×12 | always Indian F&O | **capability-gated**: shown when market has OPTION + data |

This replaces today's partial Indian/crypto fork with **one data-driven path** —
connecting a crypto broker auto-morphs the UI with no forked "crypto screens."

## 8. Backward-compatibility — guaranteed in CI

- **Golden-master snapshots** of current `/api/v1` responses + rendered symbols
  for a representative Indian set (equity/future/option across
  NSE·NFO·MCX·CDS·BSE); CI fails on any byte change.
- **Renderer round-trip:** `render(structure(symbol)) == symbol` for every
  existing `SymToken` symbol.
- **Append-only enums** — Indian values never removed/renamed.
- **Additive migrations** — new `SymToken` columns nullable with Indian defaults.
- **Optional new fields** — requests without them behave as today; responses gain
  keys only additively.
- **Conformance shim** keeps the 33 brokers on their same code paths.

## 9. Principles & best practices (for contributors)

- **Data over branches.** Market differences live in metadata + strategy objects,
  never in `if broker == …` sprinkled through core.
- **One source of truth per concept.** Order vocabulary lives in the manifest;
  currency/calendar in resolvers; instrument identity in `SymToken`.
- **The symbol string is an output, not a parser input.** Look up, don't parse.
- **Small, single-purpose units** with explicit interfaces (Protocol, resolver
  strategy) so each can be understood and tested in isolation.
- **Additive by construction, proven by golden tests.**

## 10. Non-goals (YAGNI)

- No US or crypto-spot **reference broker** in this effort (interfaces only).
- No plugin **sandboxing/signing** in v1 (plugins are trusted code).
- **No CCXT or third-party crypto aggregation** — each crypto exchange is a
  direct native adapter (see [ADR-0001](../decisions/2026-07-13-crypto-native-integration-not-ccxt.md)).
- No new canonical symbol *table* — reuse `SymToken` + additive columns.
- No rewrite of the 33 brokers — shim first, migrate opportunistically.
- No change to the ZMQ bus invariant, FD-hygiene, or single-worker eventlet model.

## 11. Risks & open questions

- **Margin correctness** across regimes (SPAN vs leverage vs Reg-T) is the
  hardest area; scoped to IN+crypto now, US deferred.
- **Frontend blast radius** (85 files) — mitigate by shipping `/api/v1/config`
  first and migrating screens incrementally behind it.
- **Sandbox 24/7 semantics** — define crypto "no square-off" and funding-time
  handling explicitly in the P5 spec.
- **Delta cleanup timing** — currently P7 (proof exemplar last); could move
  earlier to de-risk the contract. Flagged for the roadmap review.
