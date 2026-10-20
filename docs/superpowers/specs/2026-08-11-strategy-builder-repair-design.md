# Strategy Builder Repair Design

Date: 2026-08-11

Branch: `fix-strategy-builder`

Route: `/strategybuilder`

## Goal

Repair all independently verified Strategy Builder defects SB-01 through SB-26 while preserving the documented OpenAlgo order constants, symbol formats, and WebSocket subscription contract. The result must keep a strategy internally consistent across live market state, scenario valuation, saved-state restoration, order execution, responsive layout, and accessibility.

## Evidence and scope rule

Claude Code's issue inventory is supporting input, not an authority. Each repair is admitted only after independent source tracing against `origin/main` or an independently reproduced runtime observation. Runtime measurements stay labelled as runtime evidence. One Claude correction is rejected: `frontend/src/lib/utils.ts` already provides the shared broker-aware `makeFormatCurrency`; this repair adopts it instead of creating another formatter.

The repair remains a single project because all four P0 failures and most P1 failures share two boundaries: active strategy identity and per-leg market/contract metadata. Presentation-only changes are implemented after those boundaries stabilize.

## Authoritative contracts

- Orders keep the documented uppercase values such as `BUY`, `SELL`, `MARKET`, `LIMIT`, `NRML`, and `MIS`; basket quantities remain `lots × lotSize`.
- Option and futures symbols are accepted only when returned by the listed-contract APIs. Cross-expiry code must not synthesize a tradable symbol locally.
- WebSocket subscriptions use the documented exact `exchange` plus canonical `symbol` pair. Bare MCX/CRYPTO base names are not substituted for resolved futures or perpetual symbols.
- The backend option-chain response is the source of `expiry_ts`, `server_ts`, parity forward, canonical underlying reference symbol/exchange, and per-contract metadata.

## Chosen architecture

### 1. Explicit strategy and chain identity

The page remains single-underlying. Its identity is `(exchange, underlying)` and each loaded chain is identified by `(exchange, underlying, expiry)`. Underlying or exchange changes with existing legs require confirmation; acceptance clears legs and scenario state before the identity changes. Cancellation leaves both identity and legs unchanged.

Expiry-only changes do not clear legs because calendars are supported. They synchronously invalidate the currently displayed chain and disable Add until a response whose full chain identity matches the selected expiry arrives. Existing request generation guards remain; the fix does not replace working underlying/exchange sequencing.

Saved-strategy hydration applies exchange, underlying, expiry, legs, and scenarios as one guarded restoration. Default-selection effects remain suspended until that restoration reaches a consistent identity.

### 2. Listed-contract resolver and per-leg metadata

Every option/futures leg carries:

- canonical `symbol` and `exchange`;
- `expiry` plus authoritative `expiryTs`;
- `lotSize` and `tickSize`;
- entry price and current market price;
- current IV for options;
- reference underlying price and per-expiry forward used when that market snapshot was formed.

Manual Add, template application, Edit, saved-leg rehydration, and futures selection all use one async listed-contract resolver. It fetches/cache-selects the exact expiry chain, chooses the canonical row and side, and rejects missing or stale contracts. The already-correct template resolver is the behavioral pattern. Prices are keyed by `exchange:symbol`; strike-only fallback is removed.

### 3. One live market-state path

The existing option-chain REST/WebSocket hook becomes Strategy Builder's main market source. Polling requests `with_greeks: true`; the response supplies parity forward, IV, and Greeks. The page removes the redundant initial synthetic-future, ATM-Greeks, and multi-Greeks calls. Live ticks update option prices and recompute affected IV/Greeks with the latest resolved forward.

The option-chain API also returns the canonical underlying reference symbol/exchange chosen by the backend. The hook uses exactly this pair for REST price matching and WebSocket subscription, including no-spot MCX and CRYPTO cases. Visibility restoration performs an immediate poll/server-clock resync.

The LIVE badge is shown only while the live source is healthy and recent; loading, stale, and disconnected states use accurate copy.

### 4. Valuation model

Options use Black-76 consistently because their IV is solved against a parity/synthetic forward. At zero spot/IV/time shift, the model value must reconcile to the leg's current market price within tick/rounding tolerance.

> **Superseded 2026-08-14.** This section originally specified that "each leg's forward is shifted from its reference snapshot by the same `ΔS`", and that futures move by the same displacement from their stored reference. Both held the basis constant at every horizon, including expiry, which is wrong: a forward pulls to spot as its life runs out, and Indian index options settle against the index. A long 24000PE bought at 34.15 reported a breakeven of 23,886.58 against a true 23,965.85 — one basis low — and every expiry-derived figure was off by the same amount.
>
> The scenario forward is now `underlying × exp(carry × t)`, where `carry` is one continuous annual rate for the whole strategy and `t` is the leg's own remaining life. At the snapshot horizon this reproduces the reported forward, so the live mark still reconciles; at expiry the factor is 1 and the payoff is struck against spot. Futures converge on the same curve rather than carrying their basis to infinity.
>
> The rate is resolved once per strategy, as the median of the rates each leg implies, rather than per leg. A per-leg rate is unstable — the forward is a parity synthetic over two live quotes divided by a small remaining life — and, worse, legs disagree: a chain fetched without Greeks reports no forward, and a leg outside the loaded strike window keeps a stale snapshot. Two legs on one expiry with different carry factors stop cancelling, and a defined-risk iron condor reports an unlimited loss. **Invariant: legs sharing an expiry must share one carry curve.**

Time-to-expiry uses the backend `expiry_ts` and a corrected server clock. Sub-day expiries expose fractional-day/hour progression; the control never displays a selectable value that calculation code immediately clamps away.

Closed legs retain realized P&L but are excluded from live repricing, Greeks, margin requests, and execution.

### 5. Coherent scenario output

The scenario marker, payoff range, lognormal expected-move bands, PoP distribution, P&L summary, curve labels, and hover content all consume the same shifted spot, shifted IV, and valuation time. The streaming P&L tab is labelled as live-market P&L and remains independent of what-if controls.

The terminal payoff curve is labelled with its actual first-expiry semantics for multi-expiry strategies. The current-value curve label reflects the selected horizon rather than hard-coded `T+0`. Plotly receives a stable `uirevision`; hover fields are symmetric and retain meaningful decimal precision. Near-expiry label collision is a browser verification target and only receives suppression if reproduced.

Unavailable PoP is `null`; finite zero renders as `0.00%`.

### 6. Greeks and currency units

Position Greeks always include direction, lots, and per-leg lot size. Per-unit mode means one underlying unit while position mode means total contract quantity; labels state the selected basis. Futures contribute their signed position delta. Currency-denominated values use the existing `makeFormatCurrency(user?.broker)` helper and appropriate chart precision; ratio/dimensionless Greeks are not labelled as rupees.

### 7. Execution and numeric safety

The execution dialog begins with only active, open, fully validated legs selected. If none remain, execution is disabled. Each row uses the leg's stored tick and lot size; there is no page-global fallback for a resolved contract.

Lots remain clamped to a positive integer. Price inputs must be finite and non-negative and must not silently fall back to a stale value. Manual and edit dialogs display programmatic inline errors (`aria-invalid` and an associated description) for invalid prices or unlisted contracts.

The margin effect depends on the normalized open-leg request only. Capability state is not part of the request identity, preventing the success transition from issuing a duplicate request.

### 8. Auxiliary charts and exchange coverage

Strategy Chart and Multi Strike OI attach a generation or abort guard to the actual debounced data request, not only their intervals request. They send the backend-resolved canonical underlying reference to latest-price consumers.

Strategy Builder's eligible derivative exchanges include documented BCD and NCDEX. The visible list is still intersected with broker-reported capabilities, so unsupported venues are not invented.

### 9. Presentation and templates

The analysis tab list scrolls horizontally inside its own viewport on narrow screens without increasing document width. Selector buttons, lot/range/order inputs, dialogs, and scenario controls have programmatic names; invalid and live/stale states meet contrast requirements; heading levels are sequential. The payoff chart has a concise screen-reader summary plus a data table for key values.

Same-expiry template previews are derived from their leg topology instead of static hand-drawn SVG paths. Calendar previews are explicitly illustrative because their first-expiry value depends on remaining time value. Template descriptions use bounded-at-zero downside language and conditional credit/debit language.

## Error handling

- A chain response whose identity no longer matches selection is discarded.
- A missing listed contract leaves Add/Save disabled and surfaces a specific inline error.
- A stale live source preserves the last displayed values but marks them stale and blocks execution until contract validation is current.
- An unsupported margin endpoint hides margin output after one failed capability probe; ordinary transient errors remain retryable on a later request identity.
- Saved legs that cannot be rehydrated remain visible as invalid/non-executable rows so the user can edit or remove them.

## Test strategy

Every production change follows red-green-refactor. Pure tests cover Black-76 reconciliation, futures references, expiry/server-time calculations, PoP zero, contract keys/resolution, numeric validation, exchange selection, template topology/copy, and request generations. Component tests cover identity confirmation, expiry invalidation, closed-leg execution filtering, per-leg metadata, hydration, scenario propagation, currency/Greek labels, accessible controls/table, and mobile tab containment. Backend tests cover canonical underlying-reference metadata and chart no-spot/CRYPTO resolution.

Final verification runs targeted tests, all frontend tests, relevant backend tests, frontend lint/typecheck/build, desktop/mobile browser flows, Axe, request-count inspection, and a fresh SB-01 through SB-26 evidence audit.

## Non-goals

- Mixed-underlying strategies are not introduced.
- Scenario valuation is not moved to a new server endpoint.
- Existing unrelated Vega-analysis and generated `frontend/dist` changes in the original checkout are not touched.
- A pull request is not opened unless requested; the completed branch is committed and pushed as `fix-strategy-builder`.
