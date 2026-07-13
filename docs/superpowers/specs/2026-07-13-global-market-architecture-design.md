# Global-Market Architecture — Design

**Date:** 2026-07-13 · **Revised** after the [Codex review](../reviews/2026-07-13-codex-review-response.md)
**Status:** design, awaiting verification (no code yet)
**Companion docs:** [problem](../problem/2026-07-13-challenges-and-solutions.md) ·
[audit](../audit/2026-07-13-sitewide-coupling-audit.md) ·
[roadmap](../roadmap/2026-07-13-phased-roadmap.md) ·
[decisions](../decisions/) · [review response](../reviews/2026-07-13-codex-review-response.md)

## 1. Context & goals

OpenAlgo is production software for ~200,000 users, today centered on Indian
equity & F&O across 33 brokers. We are adding crypto (Delta Exchange live;
Binance/CoinDCX/Hyperliquid planned) and US brokers (IBKR/Alpaca planned), and
want *any* venue in *any* country to be pluggable.

The layering is already sound — **broker plugins → `services/` → `restx_api/`
(`/api/v1`) → `websocket_proxy/`**. The problem is that **Indian-market
assumptions leak through all of them**. This design lifts those assumptions into
a **normalized domain core** that today's Indian behavior falls out of as a
special case.

**Success criteria**

- A third party can ship a broker for any market as an out-of-tree package
  against a documented, versioned contract, and self-certify it.
- Adding a market is *data + strategies*, not edits scattered across dozens of files.
- Existing Indian users observe **no change** — proven in CI, not asserted.

## 2. The four locked decisions

1. **Additive, zero breaks** — the global model is a *superset*; today's Indian
   format/constants/`/api/v1` are byte-identical special cases.
2. **Out-of-tree plugins** — a versioned public `BrokerAdapter` contract;
   discovery via entry-points; a shipped conformance suite; plugins are *trusted
   code* (no sandboxing in v1).
3. **Model four, build two** — model & paper-validate Indian F&O, crypto
   derivatives, crypto spot, US equity/options; build live only **IN + crypto
   derivatives**.
4. **Normalized domain core** — structured instrument underneath; flat symbol is
   a byte-identical rendering on top; cross-cutting concerns resolve from metadata.

## 3. Layered target architecture

```
External API   restx_api/        /api/v1 unchanged  + optional fields / new codes / new endpoints
Symbol Renderer (new)            structure → string; Indian = byte-identical; crypto reuses Indian renderers
Internal API   services/         same orchestration; calls BrokerAdapter; cross-cutting via resolvers
Domain Core    (new)             Venue → Market/Region → Segment → (UnderlyingAssetClass × InstrumentKind) → Instrument
Capability Manifest  plugin.json v2 (EXTENDS existing get_broker_capabilities / /capabilities)
Resolvers      (new)             Currency · Calendar/TZ · Tick/Lot · Rate-limit · Margin (each with its OWN key)
Broker Adapters                  formal versioned Protocol; 33 existing wrapped via shim; out-of-tree loader
Symbol DB      SymToken          shared-schema decision required (34 defs today); additive columns
Feed           websocket_proxy/  ZMQ fan-in unchanged; streaming part of adapter contract
```

## 4. Domain model

> **Corrected after review:** the earlier flat `AssetClass` conflated *instrument
> kind* with *underlying asset class*, and folded venue identity into "Market". It
> could not express an index option vs an equity option vs a currency option.

A structured identity underneath the flat symbol, with **five orthogonal axes**:

- **Venue** (`NSE`, `MCX`, `DELTA`, `BINANCE`, `NASDAQ`) — the actual exchange/DEX.
- **Market / Region** (`IN`, `CRYPTO`, `US`) — currency, timezone, calendar,
  rate-limit profile, margin regime hang here.
- **Segment** (`NSE-EQ`, `NSE-FO`, `MCX`, `perp`, `spot`, `US-OPT`) — session
  hours, settlement, lot/tick conventions (these already differ *within* a market
  — see resolvers §6).
- **UnderlyingAssetClass** (`EQUITY`, `INDEX`, `COMMODITY`, `CURRENCY`, `CRYPTO`,
  `RATE`) — what the instrument is *on*.
- **InstrumentKind** (`CASH`/`SPOT`, `FUTURE`, `OPTION`, `PERPETUAL`) — the
  contract shape; selects the **renderer**.
- **Instrument** — a concrete tradable = one `SymToken` row (base ·
  quote/underlying · expiry? · strike? · right? · lot · tick · multiplier · token).

"Index option" is now simply `(UnderlyingAssetClass=INDEX, InstrumentKind=OPTION)`;
"commodity future" is `(COMMODITY, FUTURE)`; "quote-only global index" is
`(INDEX, CASH)` flagged quote-only.

### Symbol rendering (code-verified)

`Instrument → OpenAlgo symbol`, deterministic per **InstrumentKind**. Crypto
values below are verified against the live Delta code — see
[`docs/prompt/crypto-symbol-format.md`](../../prompt/crypto-symbol-format.md).

| Shape | Kind | → symbol | exchange | Renderer |
|-------|------|----------|----------|----------|
| Indian index option | OPTION | `NIFTY28MAR2420800CE` | NFO | **byte-identical** |
| Indian future | FUTURE | `BANKNIFTY24APR24FUT` | NFO | **byte-identical** |
| Indian equity | CASH | `INFY` | NSE | **byte-identical** |
| Crypto perpetual | PERPETUAL | `BTCUSDFUT` | CRYPTO | crypto-specific (`[sym]FUT`) |
| Crypto dated future | FUTURE | `BTC28FEB25FUT` | CRYPTO | **reuses Indian FUTURE renderer** |
| Crypto option | OPTION | `BTC28FEB2580000CE` | CRYPTO | **reuses Indian OPTION renderer** |
| Crypto spot | SPOT | `BTCINR` | CRYPTO | crypto-specific (`[base][quote]`) |
| US option | OPTION | `AAPL17JAN25190CE` | US-OPT | **reuses OPTION renderer** |
| US equity | CASH | `AAPL` | US | **reuses CASH renderer** |

> The earlier draft's `BTCUSDT`/`ETHUSDT` rows were **wrong** — the live format is
> `BTCUSDFUT` (perp) and `BTCINR` (spot). Delta already uses Indian-F&O symbology
> for dated futures and options, which **strengthens** the renderer-reuse thesis.

**Numeric precision (corrected):** `strike`/`tick_size`/`contract_value` are
`Float` today — inadequate for crypto/FX. The model specifies **Decimal + explicit
step-size + min-notional** for price/quantity; the `SymToken` type change is a P2
deliverable.

**Two safety principles:** (1) rendering is one-way — the reverse is the existing
`SymToken` lookup, never a runtime parse; (2) the public `exchange` field never
changes — it resolves internally to `(Venue, Market, Segment)`.

## 5. Broker Adapter Contract

### 5.1 The `BrokerAdapter` Protocol — full surface (corrected)

The contract is **not just the data/order methods**. An out-of-tree broker must
also declare its integration surface:

| Group | Surface |
|-------|---------|
| auth | `authenticate` · `refresh_session` · `validate_session` — supporting **API-key/OAuth AND wallet-signature** (Hyperliquid) |
| **credentials** | **declared credential schema** (which fields/secrets the broker needs) + **login/OAuth-callback flow** |
| orders | `place` · `modify` · `cancel` · `cancel_all` |
| portfolio | `positions` · `holdings` · `orderbook` · `tradebook` · `funds` · `margin` |
| data | `quote` · `depth` · `history` · `intervals` |
| instruments | `download_master_contract` → `Instrument` rows + **its scheduling hook** |
| streaming | `connect` · `subscribe` · `unsubscribe` (eventlet-safe sync pattern) |
| **lifecycle** | **migrations** it owns + **broker-specific config** it declares |
| manifest | `capabilities()` → Capability Manifest |

**Required vs optional (corrected).** A single interface requiring every method
forces fake implementations (only `dhan`/`zerodha` have GTT, and **GTT is
experimental** — so it must never be a required capability). The contract is a
**minimal required protocol** + **optional protocols** (`HistoricalData`,
`Depth`, `GTT` *(experimental)*, `OptionsChain`, `Holdings`) with a standard
`UnsupportedCapability`
response; conformance tests are generated from declared capabilities. This also
eliminates the current **arity-sniffing** (`quotes_service.py:125` inspects
`__init__` argument count to decide feed-token handling).

**Errors & idempotency (new).** Typed errors — auth-expired · permission-denied ·
unsupported-capability · rate-limited+retry-after · transient-transport ·
permanent-reject — and **client-order-id idempotency** so a transport retry never
double-places a live order. Rate limiting is *behavior* (weights · concurrency
budgets · response-header handling · backoff · safe-vs-unsafe retry), not just
manifest data.

### 5.2 Capability Manifest — structured order model (corrected)

Extends the **existing** `plugin.json` + `get_broker_capabilities()` (do not
invent a parallel system). Order semantics are **three orthogonal axes**, not a
flat `order_flags` list (`IOC`/`FOK` are time-in-force, not flags):

```yaml
contract_version: "1.0"
venue: NSE            # market/region below
market: IN
asset_classes:   [EQUITY, INDEX]         # underlying kinds
instrument_kinds: [CASH, FUTURE, OPTION]
product_types:   [CNC, NRML, MIS]
order_types:     [MARKET, LIMIT, SL, SL-M]
time_in_force:   [DAY]                    # crypto: [GTC, IOC, FOK]
exec_flags:      []                       # crypto: [post_only, reduce_only]
conditional:     []                       # bracket/OCO schemas where supported
leverage: false
base_currency: INR
sessions: { calendar: IN, tz: Asia/Kolkata }   # per venue+segment, see §6
rate_limits: { orders_per_sec: 10 }
data_caps: { quote: true, history: true, depth: true, option_chain: true, oi: true, greeks: true }
streaming: { modes: [ltp, quote, depth], max_symbols: 3000 }
```

`data_caps` is what drives **capability-gated tools** (§7), not a blanket "has
OPTION". Validation runs against the active broker's manifest.

### 5.3 Loading & conformance

In-tree (`broker/{name}/`) **or** out-of-tree; version-gated by
`contract_version`; a shipped `broker_conformance` suite; and the **conformance
shim** wrapping the **34** existing adapters (33 Indian + Delta; auto-generating an
Indian manifest so their accepted set is exactly today's). No broker rewrites to
ship.

> **Feasibility (corrected).** Out-of-tree is **not** just an entry-point loader.
> Today `pyproject.toml` ships `packages = []` (non-distributable) and broker
> dispatch is hard-coded in `brlogin.py:73`, `auth_utils.py:283` (`f"broker.{broker}…"`),
> `websocket_proxy/__init__.py:30` (eager in-tree imports), and
> `broker_factory.py:53` (fixed `{name}_adapter` naming — the reason Delta needs an
> alias). P1 must publish a **distributable contract package** (e.g.
> `openalgo-broker-api`) and a **unified broker registry** (auth · credentials ·
> master-contract · data · streaming · migrations · config) to remove that coupling.

## 6. Resolvers (cross-cutting) — each keyed on its OWN dimension (corrected)

> **Corrected after review:** "selected by Market" was too coarse — Indian
> calendars already differ by **exchange** (`market_calendar_db`: NSE 09:15–15:30,
> CDS 09:00–17:00, MCX 09:00–23:55). A uniform Market key would recreate
> hardcoded branching one level down.

| Resolver | **Selection key** | IN (build) | CRYPTO (build) | US (interface) |
|----------|-------------------|------------|----------------|----------------|
| Currency | monetary value + account + instrument | INR · ₹ · Lakh/Crore | USDT/USD | USD · $ |
| Calendar+TZ | **venue + segment** | per-exchange sessions | 24/7 · no square-off | NYSE ET |
| Tick/Lot/precision | **instrument** | tick+lot from `SymToken` | Decimal step · min-notional | fractional shares |
| Rate limit | **broker + endpoint + weight** | orders/sec per broker | weight-based | broker-specific |
| Margin | **account + instrument + margin-mode** | SPAN+exposure | leverage · isolated/cross | Reg-T / PDT |

Live trading and the sandbox consume the **same** resolvers. **But sandbox
globalization is a replatform, not just wiring** — its schema is integer quantity
/ `DECIMAL(10,2)` / no-partial-fills / single-INR-account (`sandbox_db.py`), so P5
needs schema + execution changes (fractional qty, precision, multipliers,
quote/settlement currency, partial fills, fees, funding, liquidation, 24/7
accounting) and depends on **P2+P3+P4**. Margin builds for IN + crypto.

## 7. Frontend decoupling — extend the existing substrate (corrected)

> **Corrected after review:** a capability layer already exists —
> `blueprints/broker_credentials.py:356` (`GET /capabilities`),
> `frontend/src/stores/brokerStore.ts`, and
> `frontend/src/hooks/useSupportedExchanges.ts`. **P6 extends these**, it does not
> add a parallel `/api/v1/config` unless a genuine *external-API* consumer needs
> one (open question for the P6 spec).

The UI renders capability rather than holding it, sourced from the extended
capabilities response. Tool gating uses the manifest's **`data_caps`** (quote /
history / option-chain / oi / greeks / depth) **plus per-tool plumbing** — the
current hook already excludes MCX/CDS from `/tools` for missing plumbing
(`useSupportedExchanges.ts:67`), which the capability model must express, not just
"market has OPTION".

**Fail closed (corrected).** Today the store **silently falls back to showing all
exchanges** when capability loading fails (`brokerStore.ts`,
`useSupportedExchanges.ts`). For a trading UI this must **fail closed** — surface a
capability-health error, never an unrestricted exchange list.

## 8. Backward-compatibility — defined per surface, enforced in CI (P0B)

**Compatibility is defined per surface** — the earlier flat "byte-identical"
became self-contradictory once optional fields + Decimal were added:

- **`/api/v1` requests & responses** — *semantic JSON compatibility*: existing
  keys, value semantics, and types unchanged; responses may **gain** keys. Not
  literal byte identity.
- **Rendered symbol strings** — *literal byte identity* (where "byte-identical"
  actually applies).
- **WebSocket** — existing topics and payload schemas preserved.
- **New normalized DTOs / Decimal values** — stay **internal** (behind adapters);
  never exposed on `/api/v1`.
- Dynamic values (timestamps, order IDs, broker messages) are normalized by the
  fixtures.

Enforced (built in **P0B** — CI runs only a small subset today, so this guardrail
does not yet exist):

- **Golden semantic fixtures** for the Indian set **and** the live Delta/crypto
  set (perp `BTCUSDFUT`/dated/option/spot) — REST + mapping + WS payloads.
- **Renderer round-trip** `render(structure(symbol)) == symbol` for reconstructable
  rows; ambiguous rows quarantined (P2), not force-asserted.
- **Append-only enums**; **fail-stop additive migrations** with old-DB tests;
  **optional new fields**; **conformance shim** keeps brokers on their code paths.

## 9. Principles & best practices

- **Data over branches** — no `if broker == …` in core.
- **One source of truth per concept** — extend existing capability infra, don't fork it.
- **The symbol string is an output, not a parser input.**
- **Small, single-purpose units** with explicit interfaces.
- **Additive by construction, proven by golden tests** (Indian + crypto).
- **Direct integration only** — raw REST/WebSocket, no vendor SDKs/aggregators
  ([ADR-0002](../decisions/2026-07-13-direct-api-integration-no-vendor-sdks.md)).

## 10. Non-goals (YAGNI)

- No US or crypto-spot **reference broker** in this effort (interfaces only).
- No plugin **sandboxing/signing** in v1 (plugins are trusted code).
- **No vendor SDKs / aggregation libraries** ([ADR-0002](../decisions/2026-07-13-direct-api-integration-no-vendor-sdks.md), [ADR-0001](../decisions/2026-07-13-crypto-native-integration-not-ccxt.md)).
- No new canonical symbol *table* — reuse `SymToken` (but resolve its **34-way
  schema ownership** first, §11).
- No rewrite of the 33 brokers — shim first, migrate opportunistically.
- No change to the ZMQ bus invariant, FD-hygiene, or single-worker eventlet model.

## 11. Risks & open questions (updated)

- **`SymToken` schema ownership** — there are **34** `class SymToken` definitions
  in `broker/` + 1 shared + the `token_db_enhanced` cache. "Add columns" is a
  multi-definition + migration + cache-serialization change. Ownership decision is
  a **P2 prerequisite**.
- **Delta baseline** — existing crypto users must be golden-tested too (P0), or
  "zero breaks" doesn't cover them. Includes the `BTCUSDFUT` vs stale-`.P`
  comment/alias inconsistency (fix in P7).
- **Margin correctness** across SPAN / leverage / Reg-T — IN+crypto now, US deferred.
- **Frontend blast radius** — 58 signal + 69 exchange-code files (`frontend/src`,
  reproducible via `audit/coupling_inventory.py`); migrate behind the extended
  capabilities endpoint.
- **External `/api/v1/config`?** — decide in P6 whether an external endpoint is
  needed at all vs extending the authenticated `/capabilities`.
- **Delta cleanup timing** — P7 vs pulled-forward to de-risk the contract.
