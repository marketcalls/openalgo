# Instrument contract implementation plan

> Execute under the user's continuous authorization. The user now explicitly
> requests parallel agents. Root owns this plan; independent agents own P2-P4.

**Goal:** Complete P1 with one immutable, validated instrument profile used by
chart formatting, supported-interval controls, session-aware aggregation and
existing trade quantity guards.

**Architecture:** A DOM-free base Instrument class validates InstrumentMetadata
at construction. It exposes its detached metadata, exact supported interval
checks, price formatting, session lookup and application to an existing chart.
The trade tier maps quantityStep and priceTick to existing OrderConstraints.
Neither constructor nor application creates a subscription or sends an order.

**Spec:** docs/superpowers/specs/2026-09-19-production-workspace-design.md, P1.

## Constraints and rulings

- Preserve existing chart/feed defaults. Hosts explicitly opt into metadata.
- Keep source identity, OI capability, UTC seconds and order quantity units honest.
- Sessions reuse HHMM-HHMM[:days], with Sunday 1 through Saturday 7. Opening-date
  exceptions replace the weekly windows; an empty array closes that opening date.
  Overnight sessions belong to their opening date, including across holidays.
- Resolve real IANA offsets for each boundary. Reject nonexistent DST boundaries;
  repeated boundary times follow the existing wall-clock conversion policy.
- Unsupported intervals fail before chart mutation. Applying a different source
  requires clearing old bars first; the host retains async request ownership.
- Price precision affects only the primary price scale, not oscillators or volume.
  It formats values, without rounding stored OHLC or changing the price tick.
- Quantity steps use the adapter's order units; never infer lots or multiply them.
- No comparison brands, new icons/emoji/em/en dashes. No live orders.

## Task 1: Instrument metadata and integration

Files: src/feed/instrument.ts, src/trade/instrument.ts, base/trade entry exports,
tests/instrument.test.ts, docs/instruments.md, data/time and trading skill docs.

- [x] Write failing contract tests: invalid identity/timezone/precision/step,
  detached metadata, cash/derivative/crypto OI capability, exact interval tokens,
  holidays/short sessions/lunch/overnight/24-hour sessions and DST boundaries.
- [x] Implement InstrumentMetadata, InstrumentCalendar, InstrumentSession and
  Instrument. Public methods: supportsInterval(code), formatPrice(value),
  sessionAt(utcSeconds), applyTo(chart, interval).
- [x] Add orderConstraintsForInstrument(instrument) in the trade tier. Integration
  tests use the actual Chart, CandleBuilder and validateQuantity/validatePrice.
  Verify precision does not alter ticks or oscillator axes, source changes reject
  before mutation, fractional quantity grid and session-aligned hourly candles.
- [x] Run focused cases, then coordinate package verification after the parallel
  agents finish runtime edits. Update docs/skills and measure additive cost.

## Task 2: Reference consumption

- [x] Add a reference fixture/example that obtains all price/calendar/interval/OI
  settings from the profile and displays the resulting real chart. Use explicit
  synthetic broker and crypto metadata; do not claim a live provider supplies it.
- [x] Verify browser output for both profiles in all three engines, source changes,
  a session exception and unsupported interval feedback. Preserve the existing
  reference market provider's unknown OI capability.
- [x] Record evidence and commit locally. P2-P6 and publication remain separate.

Pre-flight: root owns base/trade exports. Widget translation edits are isolated.
Adapter conformance uses existing production feed paths. Browser endurance serves
an immutable copy of dist. No build starts until runtime editors are quiescent.

## Reviewed candidate evidence

All 29 instrument cases pass, including actual primary scales on the left and
hidden axes. Independent review first reproduced both scale regressions. DST
coverage checks nonexistent boundaries, repeated-hour membership and closed
preceding sessions. The trade quantity-grid correction has separate failing and
passing evidence in the trading-capabilities plan.

The complete reviewed package verification passed 5734 engine tests in 242 files,
389 reference tests in 30 files, seven harness tests, lint, types, build,
declarations, sizes and tree-shaking. The final base is 91002 Brotli bytes.
API generation is warning-free and public-reference coverage is 930/930.

The cash, futures and crypto example passes six cases across Chromium, Firefox
and WebKit. Source transitions, quantity rules, closure dates, unsupported
intervals and actual candle/OI pixels are covered. Wide and narrow captures were
inspected. A WebKit resize loop was fixed by explicit flex sizing in the example.
A later blank screenshot came from accepting the old wide bitmap before resize
completed: the test now waits for matching container/canvas dimensions, actual
painted pixels and two frames, then captures viewport and chart separately.
No production rendering change was needed for the capture race. The original
blank screenshot and diagnostic measurements remain preserved.

Evidence: artifacts/candidate/production-245-reviewed-verify.log and
artifacts/diagnostics/instrument-webkit/verified. Commit and final publication
remain coordinated by the production-release plan.
