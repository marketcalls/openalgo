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
| 1 | **No formal broker contract** — services duck-type brokers via `importlib` and convention | "Plug in your exchange" means reverse-engineering Zerodha; no way to ship a broker out-of-tree | A versioned, public **`BrokerAdapter` Protocol** + shipped **conformance suite** + **entry-point loader** so anyone installs a broker without touching core | P1 |
| 2 | **Symbol format is Indian-derivative-shaped** (`NIFTY28MAR2420800CE`) | Crypto perps (OpenAlgo `BTCUSDFUT`), spot (`BTCINR`), US OCC options, forex need renderers beyond the expiry+CE/PE mold | A structured **Instrument** underneath the flat symbol; the string becomes a deterministic **rendering** — Indian renders byte-identical, US **and crypto dated/options reuse** the same renderers, only perpetual/spot add new ones | P2 |
| 3 | **Order constants are Indian vocabulary** (`CNC/NRML/MIS`, `SL/SL-M`) | Can't express crypto `reduce_only`/`post_only`/leverage or US `bracket`/Reg-T | The **Capability Manifest** declares each broker's vocabulary; **append-only** extension; **manifest-driven validation** replaces static enums | P3 |
| 4 | **Exchange codes are a hardcoded Indian enum** with no abstraction above them | No place to hang "which market / asset class / session / currency" | A **`Market → Segment → AssetClass`** model; the public `exchange` field stays identical and resolves internally to `(Market, Segment)` | P2 |
| 5 | **Cross-cutting Indian defaults scattered** — `₹/IST/tick` across ~55 files | Every new market means hunting and editing dozens of files; easy to miss one | Five **Market-selected Resolvers** (Currency · Calendar/TZ · Tick/Lot · Rate-limit · Margin); *data over branches*, no `if broker == …` in core | P4 |
| 6 | **`plugin.json` too coarse** — `broker_type: IN_stock` (33×) vs `crypto` (1×) | Can't declare what a broker actually supports | **`plugin.json` v2** capability manifest: markets, asset classes, order types/flags, leverage, currency, calendar, rate limits, streaming | P1 |
| 7 | **Crypto was bolted on inconsistently** — Delta has duplicate adapters; UI is partially forked; `telegram_bot_service` has `_fixed`/`_v2` variants | Tech debt, no reusable pattern, divergence risk | One contract + conformance; a **single config-driven UI path** (kills the fork); **Delta refactor** as the proof exemplar | P6, P7 |
| 8 | **Sandbox is deeply Indian** — ₹1 Cr capital, IST auto-square-off, SPAN/exposure margin | Can't paper-trade crypto (24/7, leverage) or US (ET sessions, Reg-T) | Wire `sandbox/` to the **same resolvers** as live: multi-currency capital, session-vs-24/7 square-off, leverage margin | P5 |
| 9 | **Frontend holds market knowledge** — 85 files hardcode exchanges/₹/CNC-NRML-MIS/hours | Every market needs forked screens; brittle and duplicative | A new additive **`GET /api/v1/config`** drives the UI; **capability-gated** `/tools` options suite | P6 |
| 10 | **Backward-compat risk for 200k users** — any refactor could break SDKs | Python/Node SDKs and TradingView/Amibroker/Excel integrations must not break | **Additive-only by construction**, proven by **golden-master CI snapshots** + **renderer round-trip** + **append-only enums** + **conformance shim** (33 brokers unchanged) | P0 (guardrail first) |

## The through-line

Every solution above is the same move applied in a different place: **replace a
hardcoded Indian assumption with a piece of declared data or a Market-selected
strategy**, and let today's Indian behavior fall out as the default case.

- **Contract, not convention** (challenges 1, 6) → brokers become pluggable.
- **Structure, rendered to a string** (2, 4) → one model, every market, byte-identical output.
- **Declared capability, not static enums** (3) → per-broker correctness with no core branching.
- **Resolvers, not scattered literals** (5, 8) → one place per concern, shared by live and sandbox.
- **UI renders capability, doesn't hold it** (7, 9) → no forked screens.
- **Additive, proven in CI** (10) → the 200k users are protected the whole way.

The result: adding a market becomes *registering data and strategies*, not
editing 55 files — and a third party can ship a broker for any venue in any
country against a documented, versioned contract.
