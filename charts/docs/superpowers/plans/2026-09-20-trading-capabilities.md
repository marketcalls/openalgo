# Trading Capabilities Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for this scoped implementation. Root owns exports, integrated review and release verification; widget_contracts owns widget changes.

**Goal:** Declare and enforce supported trading operations at the existing engine and OpenAlgo feed boundaries while preserving broker authority and legacy defaults.

**Architecture:** Add a pure base-tier capability contract, re-exported through the trade tier. Check feed and optional host restrictions before delivery, including after asynchronous confirmation or mode checks. Expose the same check to UI consumers; leave order and position reconciliation with existing broker code.

**Tech Stack:** TypeScript, Vitest, existing OrderEngine and OpenAlgoTradeFeed.

**Spec:** `docs/superpowers/specs/2026-09-19-production-workspace-design.md`, P5.

## Global Constraints

- Existing library options retain their defaults. New APIs are additive.
- Broker state remains authoritative for orders and positions.
- Replay and replay selection lock every order-entry route across the workspace.
- No live orders, credentials, consumer changes, staging, commits, builds or full verification in this task.
- Keep P2 completed files intact and use `artifacts/candidate/p5-*` for focused evidence.
- Root owns base/trade entry points and metadata files; widget_contracts owns all widget files.

## Review Focus

- A capability withdrawal while confirmation is pending must prevent the eventual send and release only an unsent token.
- An unsupported queued modify must be removed without changing the existing order's state or acknowledged broker status.
- Ambiguous delivered requests must remain ambiguous and keep their idempotency claims after capabilities change.
- Capability provider failures and explicit unknown support must disable delivery, while omitted declarations preserve legacy behavior.
- Missing support for new order types must not prevent cancelling an existing order when cancel remains supported.

## Task 1: Shared contract and engine enforcement

**Files:** Create `src/feed/trading-capabilities.ts`, `tests/trading-capabilities.test.ts`; modify `src/trade/order-engine.ts`.

**Interfaces:** `TradingCapabilities` declares optional place/modify/cancel support, order types and modes. `TradingCapabilitySource` accepts a declaration or a request-aware synchronous provider. `checkTradingCapability` returns a supported result or a readable refusal, and `assertTradingCapability` raises a preflight `TradingCapabilityError` for direct feed boundaries.

- [x] Write failing regressions for omitted, false, unknown and unavailable capabilities, unsupported types/modes, async confirmation races, queued modifies and authority retention.
- [x] Implement the pure helper, optional `OrderFeed.capabilities` and `OrderEngineOptions.capabilities`, with restrictions combined at each write.
- [x] Check capabilities before modifying client state; retain current intent/status on a refused modify/cancel.
- [x] Run the focused capability suite and existing engine regressions, preserving failure and final logs.

## Task 2: Direct OpenAlgo enforcement and guidance

**Files:** Modify `src/feed/openalgo-trade.ts`; create `docs/trading-capabilities.md`; append the new contract to `.github/skills/openalgo-charts/references/trade-tier.md` after root's metadata section.

**Interfaces:** `OpenAlgoTradeConfig.capabilities` uses the same source and `OpenAlgoTradeFeed.capabilities` exposes it to hosts/engines. Place checks occur before and after server-mode verification. Modify/cancel refusals occur before request delivery or context mutation.

- [x] Reproduce unsupported direct-feed writes with injected fetch and verify zero write delivery after enforcement.
- [x] Preserve unknown book rows, ambiguous token state and existing mode/idempotency defaults.
- [x] Coordinate widget hidden/disabled controls and callback-time replay/capability checks with widget_contracts; root integrates public exports.
- [x] Document capability defaults, unknown support, host lock providers, preflight handling and broker authority.
- [x] Run focused tests, lint and type checking. Record exact commands and remaining integration gaps below.

## Evidence and rulings

Root approved scoped edits to `src/feed/openalgo-trade.ts` and requested the pure
contract in `src/feed/trading-capabilities.ts`, avoiding a base-to-trade runtime
dependency. No new order authority or broker state machine is introduced.

Semantic baseline regression: 16 failed and 2 passed in
`artifacts/candidate/p5-capabilities-red-final.log`. Failures included unsupported
delivery, support changing during awaits, queued edits after withdrawal, and
loss of partial client state after a direct-feed preflight refusal. Initial
implementation passed all 18 cases. Additional public-query and authority cases
brought the focused capability suite to 27 passing tests.

The first isolated typecheck exposed two annotation errors: the existing cached
order context named a validated order type as a general string, and a test
provider mock omitted its request parameter type. Both were corrected without
casts or changes to broker values. Final scoped typecheck is clean.

| Command | Result | Artifact |
| --- | --- | --- |
| `npx vitest run tests/trading-capabilities.test.ts` | 27 passed | `artifacts/candidate/p5-capabilities-expanded.log` |
| `npx vitest run tests/trading-capabilities.test.ts tests/order-engine.test.ts tests/hardening-order-engine.test.ts tests/hardening-trade-feed.test.ts tests/feed-guards.test.ts tests/openalgo-adapters.test.ts` | 118 passed across 6 files | `artifacts/candidate/p5-trade-focused-final.log` |
| `npx eslint src/feed/trading-capabilities.ts src/feed/openalgo-trade.ts src/trade/order-engine.ts tests/trading-capabilities.test.ts` | Exit 0 | `artifacts/candidate/p5-capabilities-lint.log` |
| `npx tsc --noEmit --strict --target ES2020 --module ESNext --moduleResolution Bundler --lib ES2020,DOM,DOM.Iterable --skipLibCheck --noUnusedLocals --noUnusedParameters tests/trading-capabilities.test.ts` | Exit 0 | `artifacts/candidate/p5-capabilities-types.log` |

Root added base/trade exports and the public active-replay query. The widget
owner implemented callback-time capability/replay/host-lock guards and reported
its focused widget verification separately. Root coordinates integrated
package/browser verification; this plan does not claim those results. No live
broker or consumer validation occurred. Runtime source is frozen for root's
integrated run; all changes remain unstaged.

## Quantity-grid review follow-up

Root authorized correcting the inherited shared quantity validator after the
instrument review reproduced `1000.0005` passing a `0.001` quantity step. The
old relative tolerance eventually exceeded half a whole step. Root retained
ownership of the Instrument and its alternate-scale fix.

Changed only `src/trade/validation.ts`, `tests/hardening-validation.test.ts`
and `tests/feed-guards.test.ts`. Six failing regressions demonstrated large
fractional step admission, quantities rounding to zero, unsafe/overflowing
step counts and actual direct-feed delivery. The correction requires a
positive safe-integer nearest step count, accepts exact reconstruction of the
input quantity, and otherwise permits eight machine epsilons of relative
rounding error capped at `1e-7` of one grid step.

This deliberately rejects a grid count above the safe-integer range or an
overflowing ratio. Exact reconstruction keeps large represented decimal
multiples usable even when division has more rounding error than the cap.
A mathematically intended multiple that cannot be established from the supplied
JavaScript numbers may reject; callers needing greater precision must preserve
it at their adapter boundary. No check can recover fractional information
already lost before the number reaches the validator. Existing ungridded
fractional-quantity opt-in and broker authority are unchanged.

| Command | Result | Artifact |
| --- | --- | --- |
| `npx vitest run tests/hardening-validation.test.ts tests/feed-guards.test.ts` before the fix | 6 failed, 31 passed | `artifacts/candidate/p5-quantity-grid-red.log` |
| `npx vitest run tests/hardening-validation.test.ts tests/feed-guards.test.ts tests/order-engine.test.ts tests/hardening-order-engine.test.ts tests/trading-capabilities.test.ts` | 101 passed across 5 files | `artifacts/candidate/p5-quantity-grid-green.log` |
| `npx eslint src/trade/validation.ts tests/hardening-validation.test.ts tests/feed-guards.test.ts` | Exit 0 | `artifacts/candidate/p5-quantity-grid-lint.log` |
| `npx tsc --noEmit --strict --target ES2020 --module ESNext --moduleResolution Bundler --lib ES2020,DOM,DOM.Iterable --skipLibCheck --noUnusedLocals --noUnusedParameters tests/hardening-validation.test.ts tests/feed-guards.test.ts` | Exit 0 | `artifacts/candidate/p5-quantity-grid-types.log` |

The quantity runtime change was announced frozen before root's next integrated
verification. No build, staging or commit was performed by this task.

## Request mutation and superseded completion review follow-up

Independent review reproduced a caller changing an admitted LIMIT request to
MARKET during the engine confirmation gate or the direct feed mode lookup.
It also reproduced a newer authoritative broker fill losing its settled intent
when an older modify/cancel transport promise completed. Root authorized scoped
corrections in `src/trade/order-engine.ts`, `src/feed/openalgo-trade.ts` and new
`tests/trading-request-races.test.ts`.

- [x] Reproduce caller/gate mutation and late successful/failed completions in
  deterministic regressions before changing runtime source.
- [x] Snapshot placement values on entry, detach confirmation arguments and
  modify patches, and capture modify options before capability callbacks.
- [x] Track per-order write revisions so new writes, broker updates and
  reconciliation supersede older modify/cancel completions.
- [x] Cover ordinary transport failure, preflight refusal and transport success
  after newer broker fills, plus newer writes and reconciliation.
- [x] Run focused trade regressions, lint and strict isolated type checking.

| Command | Result | Artifact |
| --- | --- | --- |
| `npx vitest run tests/trading-request-races.test.ts` before the fix | 12 failed, 2 passed | `artifacts/candidate/p5-request-races-red.log` |
| `npx vitest run tests/trading-request-races.test.ts tests/trading-capabilities.test.ts tests/order-engine.test.ts tests/hardening-order-engine.test.ts tests/hardening-trade-feed.test.ts tests/feed-guards.test.ts tests/hardening-validation.test.ts tests/openalgo-adapters.test.ts` | 158 passed across 8 files | `artifacts/candidate/p5-request-races-green.log` |
| `npx eslint src/trade/order-engine.ts src/feed/openalgo-trade.ts tests/trading-request-races.test.ts` | Exit 0 | `artifacts/candidate/p5-request-races-lint.log` |
| `npx tsc --noEmit --strict --target ES2020 --module ESNext --moduleResolution Bundler --lib ES2020,DOM,DOM.Iterable --skipLibCheck --noUnusedLocals --noUnusedParameters tests/trading-request-races.test.ts` | Exit 0 | `artifacts/candidate/p5-request-races-types.log` |

Superseding a pending write protects local intent and broker authority; it does
not abort the request or prove its remote outcome. Request snapshots are shallow
because the public place/modify contracts contain only primitive values. All
test delivery remains synthetic. Runtime was announced frozen to root after
these checks, before root's next integrated verification.

## Public entry identity review follow-up

The final dry-run package review found that relative imports in the trade entry
and order engine caused Rollup to inline a second `TradingCapabilityError`.
An error thrown through the base entry matched its own constructor but failed
`instanceof` against the same named export from the trade entry.

Root authorized the minimal shared-entry correction. The trade entry now
re-exports capability helpers/types from `openalgo-charts`, and the engine
imports that runtime through the same public entry. Base feed code retains its
local implementation. No capability behavior or runtime defaults changed.

Before changing those imports, `scripts/check-dts.mjs` was extended to reject
duplicate capability-error declarations in lazy tiers, compare the built base
and trade constructors, and verify that refusals thrown through either entry
match both constructors with `preflight: true`. The existing built candidate
failed all four checks, recording the packaging defect directly.

| Command | Result | Artifact |
| --- | --- | --- |
| `node scripts/check-dts.mjs` against the existing build, before the import correction | Exit 1: duplicate declaration, constructor mismatch, two cross-entry refusal mismatches | `artifacts/candidate/p5-capability-identity-red.log` |
| `npx vitest run tests/trading-capabilities.test.ts tests/trading-request-races.test.ts tests/order-engine.test.ts tests/hardening-order-engine.test.ts` | 78 passed across 4 files | `artifacts/candidate/p5-capability-identity-source-tests.log` |
| `npx eslint src/trade/index.ts src/trade/order-engine.ts scripts/check-dts.mjs` | Exit 0 | `artifacts/candidate/p5-capability-identity-lint.log` |
| `npx tsc --noEmit --strict --target ES2020 --module ESNext --moduleResolution Bundler --lib ES2020,DOM,DOM.Iterable --skipLibCheck --noUnusedLocals --noUnusedParameters src/trade/index.ts src/trade/order-engine.ts` | Exit 0 | `artifacts/candidate/p5-capability-identity-types.log` |

Runtime and the package guard were frozen after these checks. Root coordinates
the rebuild and the resulting built-package guard; this scoped task did not
rebuild, stage or commit. The unchanged pre-correction dist is expected to keep
failing the new identity check until that rebuild occurs.
