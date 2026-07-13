# Sitewide Indian-Market Coupling Audit

**Date:** 2026-07-13
**Scope:** every top-level folder in the OpenAlgo repository (manual sweep). The
reproducible `coupling_inventory.py` currently scans **9 code directories**; P0A
expands it to an AST/schema suite over all folders + semantic coupling.
**Goal:** locate every place Indian-market assumptions are baked in, so the
global-architecture design can be verified as *complete* (nothing surprises us
mid-implementation).

## Method

Swept all top-level directories for the coupling signals
`₹ · INR · Asia/Kolkata · IST · CNC · NRML · MIS · SEBI · SPAN`, plus targeted
reads of the central definition files. Counts below are **files matching**, not
raw hits.

## The seven coupling patterns

1. **No *unified full-lifecycle* broker contract.** REST/auth/data are duck-typed:
   services call `importlib.import_module(f"broker.{broker}.api.{module}")` and
   trust convention (`services/place_order_service.py:38`); `quotes_service.py:125`
   even sniffs `__init__` arity. A streaming base class *does* exist
   (`websocket_proxy/base_adapter.py` `BaseBrokerWebSocketAdapter`), but there is
   no single contract spanning auth→orders→data→streaming→lifecycle — so "plug in
   your exchange" means reverse-engineering Zerodha.
2. **Symbol format is Indian-derivative-shaped** — expiry-in-symbol + `CE/PE` +
   strike (`docs/prompt/symbol-format.md`). Crypto perps, US OCC options, forex
   don't fit.
3. **Order constants are Indian broker vocabulary** — `CNC/NRML/MIS`, `SL/SL-M`
   (`utils/constants.py:69-82`).
4. **Exchange codes are a hardcoded Indian enum** (`VALID_EXCHANGES`,
   `utils/constants.py:52-67`) with no Venue/Market/Segment/UnderlyingAssetClass/
   InstrumentKind abstraction above them.
5. **Cross-cutting Indian defaults scattered** across ~55 files (`₹/IST/tick`).
6. **`plugin.json` too coarse** — `broker_type` is only `IN_stock` (33×) vs
   `crypto` (1×); cannot express capabilities.
7. **Local inconsistency where crypto was bolted on** —
   `broker/deltaexchange/streaming/` needs an **alias** module
   (`deltaexchange_adapter.py`, 15 lines re-exporting `delta_adapter.py`) because
   `broker_factory.py:53` hard-codes a `{name}_adapter` / `{Name}WebSocketAdapter`
   naming convention; `services/` has
   `telegram_bot_service.py`, `telegram_bot_service_fixed.py`,
   `telegram_bot_service_v2.py`.

## Folder impact map

### ① Normalized core lives here — build

| Folder | Size | Coupled | What changes |
|--------|------|---------|--------------|
| `utils/` | 28 py | 5 | `constants.py` → market/asset/order registry; `number_formatter.py` → locale-aware; NEW resolvers |
| `broker/` | 549 py | 163 | formal `BrokerAdapter` Protocol + conformance shim (34 adapters = 33 Indian + Delta) + `plugin.json` v2 |
| `services/` | 71 py | 22 | call adapter contract; resolve `₹/IST/tick` from metadata |
| `restx_api/` | 49 py | 4 | extend `OneOf` enums additively; new optional fields; new endpoints |
| `database/` | 35 py | 13 | `SymToken` additive columns; market-calendar → multi-market |
| `websocket_proxy/` | 9 py | — | streaming becomes part of the adapter contract |

### ② Newly surfaced — must also change

| Folder | Size | Coupled | What changes |
|--------|------|---------|--------------|
| `sandbox/` | 11 py | 9 | **BIG.** ₹1 Cr capital, IST square-off, Indian margin → market-aware capital currency, session/24-7 square-off, per-market margin |
| `frontend/` | 836 files | 58 | **BIG.** exchange dropdowns, ₹ display, `CNC/NRML/MIS` selectors, market-hours → market-driven config |
| `blueprints/` | 52 py | 14 | server pages + webhooks: currency/exchange display, sandbox controls |
| `events/` + `subscribers/` | 12 py | — | event payloads + Telegram/WhatsApp alert currency formatting |
| `download/` | 3 py | — | historical downloaders: IST cutoffs, symbol-master assumptions |

### ③ Market metadata — data, not logic

- `database/market_calendar_db.py` — Indian holidays/timings → per-market rows.
- `data/qtyfreeze.csv` — NSE quantity-freeze table → per-market instrument metadata.

### ④ Follow-through — moves with the code

`test/` (67 py, 24 coupled — add global cases + conformance suite), `upgrade/`
(23 py — additive migrations), `mcp/`, `docs/`, `okf/`, `collections/`,
`examples/`, `strategies/`, `scripts/`.

### ⑤ Not source — ignore

`db/ · log/ · tmp/ · keys/ · __pycache__/ · .venv/ · openalgoUI.egg-info/ ·
audit/ (md notes) · vectorbt-backtesting-skills/`.

## Key file-level findings

### `utils/constants.py` — the keystone (already half-globalized)

This is the single central definition of exchanges/products/price-types. Someone
**already began** the globalization: `CRYPTO_EXCHANGES`, `CRYPTO_BROKERS`,
`FNO_EXCHANGES` are sets with comments like *"onboarding a second crypto exchange
is a one-line change here"* (`utils/constants.py:22-50`). **The design should
formalize and extend this existing pattern, not fight it.** Still Indian-anchored:
product types are only `CNC/NRML/MIS`; price types only `SL/SL-M`;
`EXCHANGE_BADGE_COLORS` is Indian; `DEFAULT_PRODUCT_TYPE = MIS`.

### `restx_api/schemas.py` — two sources of truth (backward-compat gotcha)

`exchange` validates against `VALID_EXCHANGES` (imported from constants — good),
but `product` and `pricetype` are validated with **inline literals**:
`OneOf(["MIS","NRML","CNC"])` and `OneOf(["MARKET","LIMIT","SL","SL-M"])`
(`restx_api/schemas.py:32-34,67-69,94-96,142-144`). So the accepted order
vocabulary lives in **two** places. The design collapses these into one
manifest-driven check. Note the API is already partly crypto-aware:
`schemas.py:12` special-cases `CRYPTO_EXCHANGES` for quantity handling.

### `utils/number_formatter.py` — Indian-only formatting

`format_indian_number` (Cr/L) and `format_indian_currency` (₹ prefix) are
hardcoded. Becomes the `IN` strategy of a market-aware `CurrencyResolver`.

### `sandbox/` — deepest single coupling

9 of 11 files carry Indian assumptions: ₹1 Crore capital, IST auto-square-off,
Indian SPAN/exposure margin. Globalizing it is a **replatform** — the schema is
integer-quantity / `DECIMAL(10,2)` / no-partial-fills / single-INR-account — not
just resolver wiring (P5, depends on P2+P3+P4).

### `SymToken` is defined 34+1 times (schema-ownership blocker)

There are **34** `class SymToken` definitions across `broker/*/database/
master_contract_db.py`, plus the shared one in `database/symbol.py:33`, plus the
cache representation in `token_db_enhanced.py`. "Add nullable columns to
`SymToken`" is therefore not one change — it needs a schema-ownership decision
(shared base/mixin vs per-broker), a centralized migration, compatibility with
all 34 downloaders, and cache serialization changes. **P2 prerequisite.**

### A capability endpoint + frontend layer already exist (extend, don't duplicate)

`blueprints/broker_credentials.py:356` exposes `GET /capabilities` →
`get_broker_capabilities()` (from cached `plugin.json`); `frontend/src/stores/
brokerStore.ts` consumes it; `frontend/src/hooks/useSupportedExchanges.ts`
centralizes exchange filtering and **already excludes MCX/CDS from `/tools`**
(line 67) for missing plumbing. The design must **extend** this substrate, not add
a parallel `/api/v1/config`.

### Delta crypto symbol format (code-verified)

`broker/deltaexchange/database/master_contract_db.py` `_to_canonical_symbol`
produces: perpetual `BTCUSDFUT` (line 238 — the `.P` in the comment is stale),
dated future `BTC28FEB25FUT`, option `BTC28FEB2580000CE/PE`, spot `BTCINR`. Delta
**already uses Indian-F&O symbology** for dated futures & options. Documented in
[`docs/prompt/crypto-symbol-format.md`](../../prompt/crypto-symbol-format.md).

## Coupling inventory summary (reproducible)

Generated by [`coupling_inventory.py`](coupling_inventory.py) at commit
`41dfe0202` (`.py` for backend, `.ts/.tsx` for frontend). **Signal** =
`₹|INR|Asia/Kolkata|IST|CNC|NRML|MIS|SEBI|SPAN` (word-boundary). **Exchange
codes** (`NSE|NFO|BSE|BFO|MCX|CDS|BCD|NCO`) are counted separately because they
appear pervasively.

| Area | Signal files | Exchange-code files |
|------|-------------|--------------------|
| `broker/` | 163 | 214 |
| `frontend/src` | 58 | 69 |
| `test/` | 24 | 36 |
| `services/` | 22 | 30 |
| `blueprints/` | 14 | 11 |
| `database/` | 13 | 9 |
| `sandbox/` | 9 | 5 |
| `utils/` | 5 | 1 |
| `restx_api/` | 4 | 9 |

> Earlier drafts cited `frontend/src = 85` from an ad-hoc grep that mixed signal
> and exchange-code tokens. The script pins the methodology so counts are
> reproducible over time. Re-run: `uv run python docs/superpowers/audit/coupling_inventory.py`.
>
> **Scope caveat:** this first pass scans **9 code directories** for *token*
> coupling only. P0A expands it into an **AST/schema inventory suite** over all
> top-level folders plus **semantic** coupling (broker-name switches, int
> coercions, Float/Decimal, fixed column lengths, tz arithmetic, symbol parsing,
> plugin-lifecycle, migration coverage, WS static registration).

These counts scope each phase in the [roadmap](../roadmap/2026-07-13-phased-roadmap.md).
