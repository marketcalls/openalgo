# Review Response — Codex validation (2026-07-13)

An external review (Codex) challenged the design docs at commit `41dfe0202`. I
independently verified every claim against the code. **Verdict: all 10 findings
confirmed.** This doc records the evidence and the resulting changes.

## Verdicts

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | `BTCUSDT` rendering breaks existing Delta; P0 must baseline Delta | **Confirmed** | `broker/deltaexchange/database/master_contract_db.py:238` returns `delta_symbol + "FUT"` → **`BTCUSDFUT`** (the code even contradicts its own `.P` comment). Options/futures are `BTC28FEB2580000CE` / `BTC28FEB25FUT`; spot `BTCINR`. My `BTCUSDT` was simply wrong. |
| 2 | `SymToken` is not one model/migration | **Confirmed** | **34** `class SymToken` in `broker/` + **1** in `database/symbol.py` + the cache repr in `token_db_enhanced.py`. "Add nullable columns" understates P2. |
| 3 | A capability API + FE capability layer already exist | **Confirmed** | `blueprints/broker_credentials.py:356` `GET /capabilities` → `get_broker_capabilities()` from cached `plugin.json`; `frontend/src/stores/brokerStore.ts`; `frontend/src/hooks/useSupportedExchanges.ts`. Extend this substrate, don't duplicate. |
| 4 | Taxonomy conflates instrument-kind with asset-class | **Confirmed** | NFO carries both index options (NIFTY) and equity options (RELIANCE); MCX commodity futures; CDS currency derivatives; `GLOBAL_INDEX` quote-only. A flat `AssetClass` can't express (kind × underlying). |
| 5 | "Resolver selected by Market" is too coarse | **Confirmed** | `database/market_calendar_db.py` already keys timings by **exchange** (NSE 09:15–15:30, CDS 09:00–17:00, MCX 09:00–23:55), i.e. venue+segment — not "Market=IN". |
| 6 | Contract covers methods, not auth/credential/OAuth/scheduling/migration/config | **Confirmed** | The Protocol listed 7 method groups only. Real out-of-tree surfaces (credential schema, OAuth callback/login UI, master-contract scheduling, migrations, wallet-signature auth) were unspecified. |
| 7 | Numeric precision (Float) unaddressed | **Confirmed** | `database/symbol.py:43,46,47` — `strike`, `tick_size`, `contract_value` are `Float`. Crypto/FX need Decimal + step-size + min-notional. |
| 8 | IOC/FOK are time-in-force, not flags | **Confirmed** | The manifest's flat `order_flags:[post_only,reduce_only,IOC,FOK]` conflates three axes: order type × time-in-force × execution flag. Needs structured order schemas. |
| 9 | Tool gating by "has OPTION + data" is insufficient | **Confirmed** | `frontend/src/hooks/useSupportedExchanges.ts:67` already excludes MCX/CDS from `/tools` because "option chain + quotes plumbing doesn't fully support them." Gating must be per-capability (quote/history/option-chain/OI/greeks/depth) + per-tool plumbing. |
| 10 | Audit counts not reproducible | **Confirmed** | Neither party's numbers were pinned. New script `audit/coupling_inventory.py` fixes methodology → at `41dfe0202`: frontend/src **58** signal + 69 exchange-code files; test **24**; broker 163; services 22; etc. |

Note on #1: Codex's detail was exactly right — the perpetual becomes `BTCUSDFUT`,
and the `.P` comment is stale. There is also a latent **code/comment mismatch bug**
in Delta itself, now flagged for P7.

## Changes applied

- **Spec** — corrected the symbol table (`BTCUSDFUT`/`BTC28FEB25FUT`/
  `BTC28FEB2580000CE`/`BTCINR`); split the taxonomy into
  **Venue → Market/Region → Segment → (UnderlyingAssetClass × InstrumentKind) →
  Instrument**; per-resolver selection keys; structured order model (type ×
  time-in-force × exec-flags × conditional); Decimal/step/min-notional precision;
  expanded contract surfaces (auth/credential/OAuth/scheduling/migration/config);
  reuse of the existing `plugin.json` + `/capabilities` + `useSupportedExchanges`
  substrate; per-capability tool gating.
- **Roadmap** — P0 adds **Delta golden fixtures** + a pinned audit-inventory
  command; **P2** adds a `SymToken` schema-ownership decision (34+1 defs + cache);
  **P6** extends the existing capability endpoint/store instead of adding a second
  source; **P7** rewords Delta cleanup to "make adapter entry points explicit,
  then drop the compat alias if unused" and fixes the perpetual comment/code bug.
- **Audit** — counts replaced with `coupling_inventory.py` output + methodology;
  added the 34-`SymToken` and existing-capability-substrate findings.
- **New** — `audit/coupling_inventory.py` (reproducible, commit-pinned).

## Still open for the phase specs (not silently resolved here)

- Exact `SymToken` schema-ownership mechanism (shared mixin vs per-broker) → P2 spec.
- Whether an external `/api/v1/config` is needed at all, or the existing
  authenticated `/capabilities` suffices → P6 spec.
- Full conditional-order schema per asset class → P3 spec.
