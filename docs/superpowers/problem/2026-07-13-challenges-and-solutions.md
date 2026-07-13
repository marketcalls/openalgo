# The Problem — Current Challenges & How We Overcome Them

**Date:** 2026-07-13
**Companion docs:** [design](../specs/2026-07-13-global-market-architecture-design.md) ·
[audit](../audit/2026-07-13-sitewide-coupling-audit.md) ·
[roadmap](../roadmap/2026-07-13-phased-roadmap.md)

## The meta-challenge

OpenAlgo grew up **Indian-equity-first** and does that job extremely well for
~200,000 users. But global expansion — crypto (Delta live; Binance/CoinDCX/
Hyperliquid next), US brokers (IBKR/Alpaca), and eventually any venue in any
country — is blocked by the same strength turned rigid: **Indian-market
assumptions are hardwired through every layer.** Crypto was bolted on in places,
which added tech debt without a reusable pattern.

The bind: we must open the platform to every market **without breaking the
200k users** who depend on today's API, symbol format, and order constants. This
doc pairs each concrete challenge with how the design overcomes it, and where in
the roadmap it happens.

## Challenge → Solution map

| # | Challenge (today) | Why it hurts | How we overcome it | Phase |
|---|-------------------|--------------|--------------------|-------|
| 1 | **No *unified full-lifecycle* contract** — REST/auth/data duck-typed via `importlib` (a WS base class exists) | "Plug in your exchange" means reverse-engineering Zerodha; core hard-codes broker dispatch in several spots | An **in-repo `BrokerAdapter` contract** (required + optional protocols, typed errors, idempotency) + **conformance suite** + a **unified registry** replacing the hard-coded dispatch — in-tree, PR-contributed ([ADR-0003](../decisions/2026-07-13-in-tree-broker-model.md)) | P1 |
| 2 | **Symbol format is Indian-derivative-shaped** (`NIFTY28MAR2420800CE`) | Crypto perps (OpenAlgo `BTCUSDFUT`), spot (`BTCINR`), US OCC options, forex need renderers beyond the expiry+CE/PE mold | A structured **Instrument** underneath the flat symbol; the string becomes a deterministic **rendering** — Indian renders byte-identical, US **and crypto dated/options reuse** the same renderers, only perpetual/spot add new ones | P2 |
| 3 | **Order constants are Indian vocabulary** (`CNC/NRML/MIS`, `SL/SL-M`) | Can't express crypto `reduce_only`/`post_only`/leverage or US `bracket`/Reg-T | The **Capability Manifest** declares each broker's vocabulary; **append-only** extension; **manifest-driven validation** replaces static enums | P3 |
| 4 | **Exchange codes are a hardcoded Indian enum** with no abstraction above them | No place to hang "which venue / market / asset class / session / currency" | A **five-axis** model (Venue · Market/Region · Segment · UnderlyingAssetClass · InstrumentKind); the public `exchange` field stays identical and resolves internally to `(Venue, Market, Segment)` | P2 |
| 5 | **Cross-cutting Indian defaults scattered** — `₹/IST/tick` across dozens of files | Every new market means hunting and editing dozens of files; easy to miss one | Five **Resolvers, each keyed on its own dimension** (Currency · Calendar/TZ = venue+segment · Tick/Lot = instrument · Rate-limit = broker+endpoint · Margin = account+instrument+mode); *data over branches*, no `if broker == …` in core | P4 |
| 6 | **`plugin.json` too coarse** — `broker_type: IN_stock` (33×) vs `crypto` (1×) | Can't declare what a broker actually supports | **`plugin.json` v2** capability manifest: markets, asset classes, order types/flags, leverage, currency, calendar, rate limits, streaming | P1 |
| 7 | **Crypto was bolted on inconsistently** — Delta needs an **alias module** forced by the factory's rigid naming; UI is partially forked; `telegram_bot_service` has `_fixed`/`_v2` variants | Tech debt, no reusable pattern, divergence risk | One contract + conformance; a **single config-driven UI path** (kills the fork); **Delta as the reference adapter** (P1.5) | P1.5, P6 |
| 8 | **Sandbox is deeply Indian** — ₹1 Cr capital, IST auto-square-off, SPAN/exposure margin | Can't paper-trade crypto (24/7, leverage) or US (ET sessions, Reg-T) | Wire `sandbox/` to the **same resolvers** as live: multi-currency capital, session-vs-24/7 square-off, leverage margin | P5 |
| 9 | **Frontend holds market knowledge** — 58 signal (+69 exchange-code) files hardcode exchanges/₹/CNC-NRML-MIS/hours | Every market needs forked screens; brittle and duplicative | **Extend** the existing `/capabilities` + `brokerStore` + `useSupportedExchanges`; **fail-closed** on load failure; **capability-gated** `/tools` | P6 |
| 10 | **Backward-compat risk for 200k users** — any refactor could break SDKs | Python/Node SDKs and TradingView/Amibroker/Excel integrations must not break | **Additive-only by construction**, proven by **golden-master CI snapshots** + **renderer round-trip** + **append-only enums** + **conformance shim** (existing brokers unchanged) | P0 (guardrail first) |

## The through-line

Every solution above is the same move applied in a different place: **replace a
hardcoded Indian assumption with a piece of declared data or a dimension-keyed
resolver strategy**, and let today's Indian behavior fall out as the default case.

- **Contract, not convention** (challenges 1, 6) → brokers become pluggable.
- **Structure, rendered to a string** (2, 4) → one model, every market, byte-identical output.
- **Declared capability, not static enums** (3) → per-broker correctness with no core branching.
- **Resolvers, not scattered literals** (5, 8) → one place per concern, shared by live and sandbox.
- **UI renders capability, doesn't hold it** (7, 9) → no forked screens.
- **Additive, proven in CI** (10) → the 200k users are protected the whole way.

The result: adding a market becomes *registering data and strategies*, not
editing 55 files — and a new broker for any venue in any country is added
**in-tree via a PR** against a documented contract + registry (no out-of-tree
shipping — [ADR-0003](../decisions/2026-07-13-in-tree-broker-model.md)).
