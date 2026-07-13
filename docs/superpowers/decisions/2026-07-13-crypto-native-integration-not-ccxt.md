# ADR-0001 — Crypto exchanges: direct native integration, not CCXT

**Status:** Accepted · 2026-07-13
**Companion:** [design](../specs/2026-07-13-global-market-architecture-design.md) ·
[roadmap](../roadmap/2026-07-13-phased-roadmap.md)

## Context

OpenAlgo is adding crypto (Delta Exchange live; Binance / CoinDCX / Hyperliquid
planned). The existing Delta integration is **hand-rolled**: a custom REST client
plus a synchronous `websocket` + `threading` streaming client, structured exactly
like an Indian broker (`api/`, `mapping/`, `database/`, `streaming/`,
`plugin.json`). Confirmed: `ccxt` is **not** a dependency and Delta imports no
aggregation library.

CCXT (one library, 100+ exchanges) was considered as an alternative implementation
path for the crypto slice.

## Decision

Each crypto exchange is integrated as a **direct native `BrokerAdapter`** against
that exchange's own REST + WebSocket API. OpenAlgo will **not** use CCXT — or any
third-party aggregation library — for crypto connectivity.

## Rationale

- **One integration pattern for all markets.** Crypto adapters follow the same
  structure as the 30+ Indian broker adapters. Maintainers and contributors learn
  one pattern, not two.
- **Full fidelity to each exchange.** Direct integration exposes every
  exchange-specific order type/flag, margin mode, and data field, without being
  capped at a lowest-common-denominator unified API or needing `params` escape
  hatches.
- **Eventlet-safe streaming.** Native adapters use the sync `websocket` + threads
  pattern (as Delta does today), which is compatible with the gunicorn+eventlet
  production model. CCXT Pro is `asyncio`-based and would require running an async
  loop on a separate real OS thread to coexist with eventlet — avoided entirely.
- **Latency & control** on the trading-critical path; no large third-party
  dependency or supply-chain surface in the order/stream flow.
- **Honest capability declaration.** Each exchange's `plugin.json` v2 manifest
  states exactly what it supports; core validation stays correct per exchange.

## Consequences

- **More work per exchange** than a single CCXT adapter. Mitigated by: the
  **conformance suite**, a **scaffolding generator** that stubs a new broker, and
  the shared `mapping/` + `streaming/` conventions.
- Each crypto exchange = its own `broker/<name>/` (api · mapping · database ·
  streaming · `plugin.json` v2) implementing the native `BrokerAdapter`.
- **Streaming adapters MUST use the eventlet-safe sync-websocket + threads
  pattern**; `asyncio` is disallowed on the request/stream path (per the runtime
  constraints in `CLAUDE.md`).

## Roadmap implications

- **P7** — clean up Delta to the native contract (remove the duplicate
  `delta_adapter.py` / `deltaexchange_adapter.py`). **Delta becomes the reference
  native crypto adapter** that Binance / CoinDCX / Hyperliquid follow.
- **P4** — rate-limit and margin (leverage / isolated-cross) resolvers are
  implemented natively per exchange.
- Contributor docs ship a **native crypto adapter guide** + scaffolding, so the
  per-exchange cost stays low.
