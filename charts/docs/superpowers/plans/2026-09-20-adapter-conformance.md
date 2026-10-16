# Adapter Conformance Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to execute this scoped task. The parent coordinates review, integration and broader validation.

**Goal:** Apply one deterministic adapter contract to the production broker and crypto reference paths, with explicit synthetic evidence and negative controls.

**Architecture:** Inject deferred HTTP responses and socket frames into the existing OpenAlgo live feed and the website crypto polling feed. A reusable suite observes public host snapshots and transport cancellation. Keep protocol-specific fixtures and lifecycle drivers separate from shared assertions.

**Tech Stack:** TypeScript, Vitest fake timers, production DataLoadingController, OpenAlgoLiveDataFeed and createBtcUsdFeed.

**Spec:** `docs/superpowers/specs/2026-09-19-production-workspace-design.md`, P2.

## Global Constraints

- Work in the existing `feat/production-chart-workspace` worktree, starting at `dfa42d5`.
- UTC seconds for engine data. Default Asia/Kolkata behaviour is preserved.
- No credentials, live orders, consumer changes, comparison brands, icons or long dashes.
- Do not edit production feed code without first reproducing a defect and coordinating ownership with the parent.
- Do not stage, commit, build, run browser tests or modify shared release facts and ledgers.
- Record focused command output under `artifacts/candidate/p2-*`.

## Review Focus

- A duplicate timestamp must choose the provider's documented winner and cannot become a second candle.
- An obsolete response must not overwrite the newly selected interval, even when transport ignores abort.
- An authoritative correction to a closed candle must replace its values rather than preserve stale extremes.
- Failed refreshes must keep visible history and mark it stale until recovery succeeds.
- Destroy and unsubscribe must abort work, release timers and prevent late callbacks or reconnect work.

## Task 1: Shared history and lifecycle contract

**Files:**
- Create `tests/conformance/adapter-contract.ts`: generic scenario definitions and public harness interfaces.
- Create `tests/conformance/controlled-transport.ts`: deferred in-memory fetch requests, without network access.
- Create `tests/conformance/reference-adapters.ts`: production broker and crypto driver bindings and deterministic fixtures.
- Create `tests/conformance/website-crypto.d.ts`: test-only declaration for the existing JavaScript module.
- Create `tests/adapter-conformance.test.ts`: register each reference against the same cases and negative controls.

**Interfaces:** The runner consumes `AdapterHarness` from a factory and invokes `load`, `refresh`, `snapshot` and `destroy`. `ControlledTransport.request(index)` exposes the real request's signal and deterministic reply controls. Factories supply provider payloads and expected UTC-second bars; the runner owns all contract assertions.

- [x] Add shared cases for duplicate history, closed-bar repairs, network/provider/HTTP failures, cancellation, stale context and destroy.
- [x] Bind the broker driver to `DataLoadingController` and `OpenAlgoLiveDataFeed`, and the crypto driver to the existing website polling feed.
- [x] Add deliberately nonconforming output wrappers and confirm the same duplicate/repair assertions reject them.
- [x] Run `npx vitest run tests/adapter-conformance.test.ts` with output in `artifacts/candidate/p2-conformance-unit-expanded.log`; inspect every failure and require a green final result.

## Task 2: Stream-specific recovery and reference guidance

**Files:** Extend the new contract/test files and create `docs/adapter-conformance.md`.

**Interfaces:** Optional broker stream controls expose synthetic Quote frames, disconnect/reconnect and sent protocol frames. Crypto recovery remains polling; it does not claim a socket subscription.

- [x] Exercise repeated cumulative-volume frames, the existing late-tick policy, reconnect authentication and authoritative resync, buffering during repair, unsubscribe and intentional close.
- [x] Exercise crypto weekend UTC-midnight history and fractional volume through the shared fixtures, plus automatic polling recovery.
- [x] Document how to run and extend the suite, duplicate ordering, tail/repair policy, capability boundaries and the evidence required for a connected-feed claim.
- [x] Run the conformance suite plus adjacent broker/controller/node crypto suites, and focused lint. Record exact commands and results below.

## Evidence and rulings

The existing broker/controller unit suites and `scripts/check-btc-usd-feed.test.mjs` already cover detailed protocol and parsing behavior. The new suite adds a shared matrix across both production paths, with negative controls. It does not introduce a new crypto adapter or imply the website polling feed implements `DataFeed`.

All new transport inputs are authored deterministic fixtures. No recorded feed captures or connected broker evidence are supplied by this task.

The first registration run failed before the reference factory existed, as
recorded in `artifacts/candidate/p2-conformance-red.log`. Once the real reference
drivers were added, the initial shared matrix passed 26 tests. The expanded
suite passed 33 tests, including four negative controls. The negative controls
are behavioral rejection evidence; the initial missing-import run alone is
not a reproduced production defect.

Focused validation completed on 2026-09-20:

| Command | Result | Artifact |
| --- | --- | --- |
| `npx vitest run tests/adapter-conformance.test.ts` | 33 passed | `artifacts/candidate/p2-conformance-unit-expanded.log` |
| `npx vitest run tests/adapter-conformance.test.ts tests/openalgo-rest-request.test.ts tests/hardening-live-feed.test.ts tests/data-controller.test.ts tests/data-controller-review.test.ts tests/data-controller-repair.test.ts tests/data-controller-lagging-refresh.test.ts --reporter=verbose --reporter=json --outputFile=artifacts/candidate/p2-conformance-focused.json` | 100 passed across 7 files | `artifacts/candidate/p2-conformance-focused.log`, JSON report |
| `node --test scripts/check-btc-usd-feed.test.mjs` | 11 passed | `artifacts/candidate/p2-crypto-reference.log` |
| `npx eslint tests/adapter-conformance.test.ts tests/conformance` | Exit 0 | `artifacts/candidate/p2-conformance-lint.log` |
| `npx tsc --noEmit --strict --target ES2020 --module ESNext --moduleResolution Bundler --lib ES2020,DOM,DOM.Iterable --skipLibCheck --noUnusedLocals --noUnusedParameters tests/adapter-conformance.test.ts tests/conformance/website-crypto.d.ts` | Exit 0 | `artifacts/candidate/p2-conformance-types.log` |

No production defect or production source change was needed for this matrix.
Full package verification, rendering, endurance and connected-feed evidence
remain outside this scoped task and are coordinated by the parent. Source
changes are left unstaged for its review and integration.
