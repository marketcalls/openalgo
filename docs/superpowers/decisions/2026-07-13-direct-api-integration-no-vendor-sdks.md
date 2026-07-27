# ADR-0002 — Direct API/WebSocket integration; no vendor SDKs or aggregation libraries

**Status:** Accepted · 2026-07-13
**Generalizes:** [ADR-0001](2026-07-13-crypto-native-integration-not-ccxt.md) (the crypto/CCXT-specific instance)
**Companion:** [design](../specs/2026-07-13-global-market-architecture-design.md)

## Context

OpenAlgo integrates 33 brokers today. The audit confirms this is **already the
de-facto practice** — there is no cleanup implied by this decision, only
formalization:

- **Zero vendor broker SDKs** imported anywhere in `broker/` (no `kiteconnect`,
  `fyers`, `dhanhq`, `upstox`, `NorenApi`, `SmartApi`, `py5paisa`, …).
- **None in dependencies** (`pyproject.toml` / `requirements.txt`).
- Every broker talks **directly** to the venue's endpoints: `httpx` (92×, the
  shared pooled client) and `requests` (30×) for REST; `websocket` / `socketio`
  (sync) for streaming. Delta (crypto) is the same.

## Decision

Every broker/exchange adapter — Indian, crypto, US, or any future venue —
integrates **directly against the venue's own REST and WebSocket endpoints**,
using OpenAlgo's shared generic transport. OpenAlgo will **not** depend on:

- **broker/exchange-provided SDKs** (kiteconnect, fyers, dhanhq, upstox, Noren,
  etc.), nor
- **multi-broker/exchange aggregation libraries** (CCXT, etc.).

### Scope — read this carefully

This excludes *broker-specific* and *aggregation* libraries. It does **not**
exclude generic transport/protocol libraries. The sanctioned building blocks are:

| Purpose | Use |
|---------|-----|
| REST | the shared pooled **`httpx`** client (`utils/httpx_client.get_httpx_client()`) |
| Streaming | sync **`websocket-client`** + threads (the eventlet-safe pattern), or `python-socketio` where the venue uses it |

You integrate the raw endpoints yourself (auth signing, request building, response
parsing, WS framing); you do **not** hand order flow to a third party's wrapper.

## Rationale

- **Control, fidelity, latency** on the trading-critical path — no capability
  ceiling, no `params` escape hatches, no black-box order routing.
- **No vendor supply-chain surface.** Vendor SDKs pin their own transitive
  dependencies and lag exchange API changes; keeping them out of the order path
  removes that risk.
- **Eventlet-safe by construction.** The sync `websocket` + threads pattern avoids
  the `asyncio`-vs-eventlet incompatibility (per `CLAUDE.md`); many vendor SDKs
  and aggregation libs are `asyncio`-based.
- **One pattern for every market.** Contributors learn a single adapter shape,
  Indian through crypto through US.
- **Already true.** This ADR ratifies existing practice rather than changing it.

## Consequences

- Each adapter owns auth/signing, request building, response parsing, and WS
  framing against the venue's raw API — via the shared `httpx` client (per the
  `CLAUDE.md` HTTP-pooling convention) and the sync-websocket + threads pattern.
- The `BrokerAdapter` contract + conformance suite + scaffolding generator keep
  the per-broker cost bounded despite hand integration.
- **Auth generality (for the P1 spec).** Because adapters sign requests
  themselves, the contract's auth model must cover **API-key / OAuth** (Indian,
  most crypto) **and wallet/signature auth** (e.g., Hyperliquid) — not just
  API keys.
- **Opportunistic consistency (not a blocker).** New adapters standardize on the
  shared `httpx` client + sync-websocket pattern; the older `requests`-based
  brokers can migrate over time.
