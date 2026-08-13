# Strategy Builder Payoff Graph — Final Consolidated Audit

Audit target: `http://127.0.0.1:5000/strategybuilder`  
Audit date: 2026-07-28  
Scope: payoff graph, payoff math feeding the graph, and the adjacent payoff metrics/simulators.  
Out of scope: implementation changes.

## Audit limitation

The local server responded successfully, but no controllable browser instance was available in the audit environment. The findings below therefore come from:

- tracing the live route to its current React/TypeScript implementation;
- comparing the frontend pricing path with the backend Greeks model;
- running focused numerical reproductions against `strategyMath.ts`; and
- reviewing Plotly configuration, responsive behavior, and accessibility at source level;
- closely inspecting the supplied Iron Condor screenshot; and
- querying the local master-contract database read-only for the exact screenshot expiry and irregular-chain counterexamples.

Items that require final pixel-level confirmation are explicitly marked. All numerical and data-flow findings are reproducible from the current code.

This final report consolidates and validates the findings from:

- `audit/PAYOFF_GRAPH_DEEP_AUDIT.md` (the initial independent audit, renamed to this final report); and
- `audit/STRATEGY_BUILDER_PAYOFF_AUDIT.md` (the Claude audit supplied for validation).

## Priority summary

| ID    | Priority | Issue                                                                                         | Primary impact                                    |
| ----- | -------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| PG-18 | P1       | Leg edits retain the previous contract's IV and Greeks                                        | Incorrect T+n valuation after editing             |
| PG-01 | P1       | Fixed ±10% sample window corrupts breakevens and probability of profit                        | Incorrect risk metrics                            |
| PG-02 | P1       | Frontend payoff pricing model disagrees with backend IV/Greeks model                          | Incorrect T+n curve                               |
| PG-03 | P1       | What-if scenario state is only partially reflected in the graph and PoP                       | Misleading simulator                              |
| PG-04 | P1       | Multi-expiry valuation is labeled and optimized as if it were a true expiry payoff            | Incorrect labels and extrema                      |
| PG-05 | P2       | Expiry time is hard-coded to 15:30 IST                                                        | Wrong time value for non-standard/crypto expiries |
| PG-06 | P2       | Payoff data domain is fixed and can omit strikes/breakevens or stop before σ bands            | Truncated or curve-less graph regions             |
| PG-07 | P2       | Exact-grid breakevens are emitted twice                                                       | Duplicate metric chips                            |
| PG-08 | P2       | Profit/loss fills do not meet the curve at the interpolated zero crossing                     | Incorrect shading slivers                         |
| PG-09 | P2       | A real 0% PoP is displayed as unavailable                                                     | Ambiguous risk metric                             |
| PG-10 | P2       | Curve labels do not follow the selected time scenario                                         | Incorrect legend/hover text                       |
| PG-11 | P2       | Expected-move bands use inconsistent scenario inputs and distribution semantics               | Misleading σ overlay                              |
| PG-12 | P2       | Currency and numeric precision are hard-coded for INR                                         | Incorrect crypto presentation                     |
| PG-13 | P2       | Plot interaction state is not preserved across simulator updates                              | Zoom resets/jumpy analysis                        |
| PG-14 | P2       | The graph has no explicit accessible equivalent                                               | Screen-reader and non-color access gap            |
| PG-15 | P3       | Near-expiry σ annotations collapse on top of the spot label                                   | Label overlap                                     |
| PG-16 | P3       | Hover information is asymmetric and rounds away useful values                                 | Weak inspection UX                                |
| PG-17 | P2       | No payoff-specific automated regression suite exists                                          | High regression risk                              |
| PG-19 | P2       | DTE and payoff valuation time freeze during a long-open session                               | Stale intraday time value                         |
| PG-20 | P1       | Template expiry changes can combine a new expiry with the previous chain's symbol and premium | Wrong contracts and entry prices                  |
| PG-21 | P2       | Calendar templates silently collapse to one expiry                                            | Strategy is no longer a calendar                  |
| PG-22 | P2       | Template strike resolution does not enforce distinct, ordered legs                            | Condors/butterflies can collapse                  |
| PG-23 | P2       | Hand-authored template previews can contradict the actual legs                                | Misleading strategy selection                     |
| PG-24 | P2       | Several template descriptions are mathematically or structurally inaccurate                   | Incorrect strategy education                      |
| PG-25 | P2       | Uniform payoff samples omit exact strikes and visibly soften Iron Condor kinks                | Distorted payoff geometry                         |
| PG-26 | P1       | IV/Greeks are one-shot snapshots and leg IV is never refreshed after backfill                 | Stale live valuation                              |

---

## Findings

### PG-01 — Fixed ±10% sample window corrupts breakevens and probability of profit

**Priority:** P1  
**Evidence:** `frontend/src/pages/StrategyBuilder.tsx:842-877`, `frontend/src/lib/strategyMath.ts:329-353`, `frontend/src/lib/strategyMath.ts:446-459`

The chart and all sampled risk calculations use only `[spot × 0.9, spot × 1.1]`. Breakevens are detected only when adjacent samples inside that window change sign. PoP then integrates profitable sample intervals and assumes the sign at the last sample continues forever.

That assumption is false whenever a strike or breakeven lies outside the window. A profitable tail can begin after `+10%`, while the last sampled point is still negative.

**Reproduction against the current code**

- Spot: `100`
- Long call: strike `115`, premium `1`
- Expiry breakeven: `116`
- Current graph range: `90–110`
- IV: `20%`, DTE: `31`

Current result:

- `breakevens = []`
- reported `PoP = 0`
- analytical probability of finishing above `116` under the same lognormal inputs: approximately `0.50%`

This is not only a visual clipping problem; it changes the displayed strategy metrics.

**What to fix**

1. Decouple risk math from the visible chart sample window.
2. Compute expiry roots structurally for same-expiry piecewise-linear payoffs.
3. For multi-expiry/model-valued curves, use adaptive root finding over a domain expanded until tail behavior is established.
4. Integrate PoP over the resulting profitable intervals, not over midpoint-classified chart pixels.
5. Let the chart use a display-oriented domain after the complete roots and extrema are known.

**Acceptance checks**

- The reproduction above shows breakeven `116` and a non-zero PoP.
- Deep OTM calls/puts and ratio spreads retain correct PoP when every breakeven is outside ±10%.
- Changing chart zoom never changes PoP, max profit/loss, or breakevens.

---

### PG-02 — Frontend payoff pricing model disagrees with backend IV/Greeks model

**Priority:** P1  
**Evidence:** `frontend/src/lib/strategyMath.ts:1-5`, `frontend/src/lib/strategyMath.ts:105-123`, `frontend/src/lib/strategyMath.ts:166-173`, `services/option_greeks_service.py:1-8`, `services/option_greeks_service.py:225-262`

The frontend reprices the T+n curve with Black-Scholes on **spot**, using `r = 0` and `q = 0`. The backend derives the supplied IV and Greeks with **Black-76**, using the per-expiry synthetic future/forward when available.

The graph therefore feeds a Black-76 implied volatility into a different pricing model and underlying definition. This can make the dashed curve fail to reconcile with the option premium at the current market point, especially where spot and synthetic future diverge.

**What to fix**

- Use one pricing contract end to end. Prefer the backend's Black-76 convention for supported F&O instruments.
- Supply the graph with the per-leg/per-expiry forward, IV, rate, expiry timestamp, and settlement currency used to derive that IV.
- If client-side repricing remains necessary, implement the exact backend convention in a shared tested package.
- Represent missing model inputs as unavailable; do not silently substitute ATM IV across the whole smile and present the result as precise.

**Acceptance checks**

- A newly added leg repriced at the current forward, current IV, and `+0d` reconciles with its entry/live premium within a documented tolerance.
- T+n P&L and Greeks use the same forward, clock, IV units, and rate.
- Calendar legs use their own expiry-specific forward and time.

---

### PG-03 — What-if scenario state is only partially reflected in the graph and PoP

**Priority:** P1  
**Evidence:** `frontend/src/pages/StrategyBuilder.tsx:141-143`, `frontend/src/pages/StrategyBuilder.tsx:480-489`, `frontend/src/pages/StrategyBuilder.tsx:842-882`, `frontend/src/pages/StrategyBuilder.tsx:1238-1244`

The Spot Price slider updates `simulatedSpot`, but that value is used only for the adjacent Total P&L metric. The graph still receives the unshifted `spotPrice`, and the graph's spot line, percentage-from-spot hover text, and σ bands remain centered on the live spot.

PoP also continues to use the unshifted spot and unshifted ATM IV. The IV slider changes the payoff curve but not the probability distribution used to calculate PoP. The result is a hybrid scenario assembled from incompatible states.

**What to fix**

- Define an explicit scenario object: `{ scenarioSpot, scenarioIv, valuationTime, horizon }`.
- Use it consistently for the scenario marker, hover percentages, σ bands, T+n curve, Total P&L, and scenario PoP.
- Keep live spot visually distinct from simulated spot if both are useful.
- Decide whether PoP is a live-entry metric or a scenario metric. Label it and freeze/update it consistently rather than mixing both.

**Acceptance checks**

- Moving Spot Price moves a clearly labeled scenario marker on the graph.
- `+10%` does not leave the only scenario marker at the original spot.
- Moving IV changes every IV-dependent scenario output or leaves all live-entry outputs explicitly unchanged.
- Reset returns the graph and every metric to one consistent baseline.

---

### PG-04 — Multi-expiry valuation is labeled and optimized as if it were a true expiry payoff

**Priority:** P1  
**Evidence:** `frontend/src/pages/StrategyBuilder.tsx:472-486`, `frontend/src/pages/StrategyBuilder.tsx:859-870`, `frontend/src/components/strategy-builder/PayoffChart.tsx:109-121`, `frontend/src/lib/strategyMath.ts:355-405`

For calendars and diagonals, the orange curve is valued at the **nearest leg's expiry** while later legs retain Black-Scholes time value. It is still labeled simply “At Expiry,” and the chart title shows only the header-selected expiry.

The max-profit/max-loss algorithm then assumes this orange curve is piecewise linear and evaluates only zero, strikes, and one point at twice the highest strike. That assumption is valid for a common-expiry intrinsic payoff, but not for a curve containing model-valued far-expiry legs.

The `2 × highest strike` point is also not a mathematical asymptote. Long-dated/high-IV bounded spreads can still have material time value at that point, understating a plateau.

**What to fix**

- Label the curve with the actual valuation event, for example `Near expiry · 28 AUG 2026`, and list the remaining expiries.
- Use the piecewise-linear extrema algorithm only when every responsive leg has reached expiry.
- Use numerical optimization plus explicit asymptotic limits for mixed-expiry curves.
- Define whether max profit/loss means final-expiry terminal payoff or value at the selected intermediate horizon; expose both if needed.

**Acceptance checks**

- Same-expiry strategies still produce exact structural extrema.
- Calendar/diagonal labels state the valuation date and do not claim all legs are expired.
- A bounded far-expiry vertical converges to its true width-adjusted plateau rather than its value at an arbitrary `2 × strike` point.

---

### PG-05 — Expiry time is hard-coded to 15:30 IST

**Priority:** P2  
**Evidence:** `frontend/src/lib/strategyMath.ts:464-495`, `frontend/src/hooks/useSupportedExchanges.ts:62-73`, `services/option_greeks_service.py:141-175`

The client parser assigns every expiry to `15:30 IST`. The strategy builder supports crypto brokers, whose contracts are not governed by the NFO/BFO close. The backend already supports exchange/custom expiry times, so frontend and backend clocks can disagree.

This error propagates into remaining time, T+n valuation, σ bands, and PoP. It is most visible on expiry day.

**What to fix**

- Stop reconstructing expiry timestamps from `DDMMMYY` alone.
- Return an authoritative ISO-8601 expiry timestamp and timezone with instrument metadata.
- Store that timestamp per leg and use the same timestamp in pricing and display.

**Acceptance checks**

- A crypto expiry uses the venue contract timestamp.
- Frontend and backend report the same fractional DTE for the same symbol.
- Expiry-day time value does not disappear early or persist after settlement.

---

### PG-06 — Payoff data domain is fixed and can omit strikes/breakevens or stop before σ bands

**Priority:** P2  
**Evidence:** `frontend/src/pages/StrategyBuilder.tsx:853-858`, `frontend/src/components/strategy-builder/PayoffChart.tsx:80-84`, `frontend/src/components/strategy-builder/PayoffChart.tsx:304-309`

The graph always receives a ±10% payoff dataset. It does not expand that curve data to include active strikes, computed breakevens, or the ±2σ expected-move boundaries. The source comment acknowledges that long-dated/high-IV bands can be outside the sampled curve.

Plotly 3.3.1 includes axis-referenced shapes and annotations in initial autorange, so an out-of-domain σ overlay can stretch the visible x-axis beyond the last payoff sample, leaving a region with bands but no P&L line. After manual zoom, annotations outside the viewport simply disappear; the supplied screenshot shows this separate interaction state.

At the simulator's `±10%` Spot Price limits, the scenario spot would also sit directly on the graph edge once PG-03 is corrected.

**What to fix**

Build an adaptive display domain that includes:

- live and simulated spot with padding;
- every active strike;
- every breakeven;
- at least ±2σ when enabled; and
- a strategy-specific tail allowance.

Provide `Fit strategy` and `Reset zoom` actions separately from Plotly's generic autoscale.

**Acceptance checks**

- No active strike, breakeven, or σ label is off-canvas on initial render.
- Long-dated/high-IV cases expand gracefully without flattening the payoff around spot.
- Users can zoom without changing the underlying calculation domain.

---

### PG-07 — Exact-grid breakevens are emitted twice

**Priority:** P2  
**Evidence:** `frontend/src/lib/strategyMath.ts:329-353`, `frontend/src/components/strategy-builder/PositionsPanel.tsx:430-443`

Crossing detection compares `Math.sign` values. If a sample lands exactly on zero, the transition into zero and the transition out of zero are both recorded. Linear interpolation then emits the same breakeven twice, and the positions panel renders duplicate chips.

**Reproduction against the current code**

- Spot: `100`
- Long call: strike `100`, premium `5`
- Range: `90–110`, step: `1`
- Expected breakeven: `[105]`
- Current result: `[105, 105]`

**What to fix**

- Treat exact zero as a root once.
- Collapse contiguous zero runs to the appropriate boundary/root representation.
- Sort and deduplicate roots using a price/tick-aware tolerance.

**Acceptance checks**

- Exact-grid roots produce one chip.
- Flat zero segments have a defined representation.
- Two genuinely distinct nearby breakevens are not accidentally merged.

---

### PG-08 — Profit/loss fills do not meet the curve at the interpolated zero crossing

**Priority:** P2  
**Evidence:** `frontend/src/components/strategy-builder/PayoffChart.tsx:76-108`

The fill arrays replace wrong-sign samples with zero but do not insert the interpolated crossing point. Plotly therefore draws each fill to zero at a neighboring sample x-coordinate, while the orange line crosses zero between samples. This creates small incorrect red/green wedges and a visible mismatch around breakevens.

**What to fix**

- Build segmented polygons/traces that include every interpolated zero crossing.
- Reuse the exact same roots for shading, breakeven metrics, and PoP intervals.

**Acceptance checks**

- At every breakeven, the orange curve and both fill boundaries meet at the same pixel.
- Increasing/decreasing sample density does not visibly move the color boundary.

#### Template-wide wedge susceptibility

This artifact is not specific to Iron Condors. It is produced by the shared fill construction, so any template whose breakeven falls between two samples can show it.

A diagnostic run across all 38 templates used one consistent reference market:

- NIFTY-style spot `24,000` and strike step `50`;
- `15%` IV;
- `7` days to the near expiry and `14` days to the far expiry;
- frontend Black-Scholes prices as entry premiums; and
- the production ±10% / 240-step grid (`20` points per sample).

Result: **36 of 38 templates had at least one between-sample crossing**, producing **62 potential fill wedges** in that one scenario.

| Between-sample crossings | Templates                                                                                                                                                                                          |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 4                        | Batman Strategy, Double Fly, Double Condor                                                                                                                                                         |
| 2                        | Bullish/Bearish Butterfly, Bullish/Bearish Condor, Long/Short Straddle, Long/Short Strangle, Long/Short Iron Fly, Long/Short Iron Condor, Call/Put/Diagonal Calendar, Call/Put Butterfly           |
| 1                        | Long Call, Short Put, Bull/Bear Call Spread, Bull/Bear Put Spread, Call/Put Ratio Back Spread, Range Forward, Short Call, Long Put, Risk Reversal, Jade/Reverse Jade Lizard, Call/Put Ratio Spread |
| 0 in this reference run  | Long Synthetic, Short Synthetic                                                                                                                                                                    |

The two synthetics landed exactly on the ATM sample and therefore exercised PG-07's duplicate-root path instead. Live call/put premium differences can move their root off-grid and make them susceptible to PG-08 as well.

This table is a susceptibility demonstration, not a promise of a fixed crossing count. Live premiums, IV, DTE, strike overrides, and roots outside ±10% can change the number of **visible** wedges.

---

### PG-09 — A real 0% PoP is displayed as unavailable

**Priority:** P2  
**Evidence:** `frontend/src/components/strategy-builder/PositionsPanel.tsx:397-400`

The UI displays PoP only when `probOfProfit > 0`; a legitimate `0` becomes `—`, the same output used for missing inputs or an unavailable calculation.

**What to fix**

- Return a nullable/result type such as `{ status, value, reason }`.
- Render `0.00%` for a valid zero and `—` only for unavailable.
- Surface a short reason when PoP cannot be calculated.

---

### PG-10 — Curve labels do not follow the selected time scenario

**Priority:** P2  
**Evidence:** `frontend/src/components/strategy-builder/PayoffChart.tsx:125-134`, `frontend/src/pages/StrategyBuilder.tsx:480-486`, `frontend/src/pages/StrategyBuilder.tsx:859-870`

The dashed curve is always named and hovered as `T+0`, although its values are computed at `clampedDaysElapsed`. At `+7d`, the graph still tells the user it is T+0.

The orange curve has a similar ambiguity for multi-expiry strategies, as covered in PG-04.

**What to fix**

- Pass valuation labels/dates as data, not hard-coded strings.
- Use `Today / T+0` only at zero days.
- Use `T+7 · 04 Aug 2026` or equivalent after advancing time.

---

### PG-11 — Expected-move bands use inconsistent scenario inputs and distribution semantics

**Priority:** P2  
**Evidence:** `frontend/src/components/strategy-builder/PayoffChart.tsx:80-84`, `frontend/src/pages/StrategyBuilder.tsx:485-489`, `frontend/src/pages/StrategyBuilder.tsx:1238-1244`

The σ bands:

- use live spot instead of simulated spot;
- use unshifted ATM IV instead of scenario IV;
- shrink with the simulated time advance; and
- are symmetric arithmetic moves (`spot ± n × spot × σ√T`) while PoP uses a lognormal distribution.

The overlay and PoP therefore do not describe the same scenario or the same distribution.

**What to fix**

- Choose and document one interpretation: live expected move or scenario expected move.
- Use the same spot, IV, time horizon, drift, and distribution as PoP.
- For a lognormal model, draw quantile boundaries rather than symmetric arithmetic bands.
- Include an overlay legend/help affordance explaining what `±1σ/±2σ` means.

---

### PG-12 — Currency and numeric precision are hard-coded for INR

**Priority:** P2  
**Evidence:** `frontend/src/components/strategy-builder/PayoffChart.tsx:118-133`, `frontend/src/components/strategy-builder/PayoffChart.tsx:310-317`, `frontend/src/components/strategy-builder/PositionsPanel.tsx:46-55`, `frontend/src/hooks/useSupportedExchanges.ts:62-73`

The strategy builder explicitly supports crypto, but the graph and metrics always use `₹`, `en-IN`, two-decimal spot labels, and whole-rupee P&L hover values. This is incorrect for non-INR settlement and hides small but meaningful P&L values.

**What to fix**

- Obtain settlement currency and tick/decimal metadata from the instrument or broker capability response.
- Centralize price and P&L formatting.
- Use tick-aware underlying precision and magnitude-aware P&L precision.

**Acceptance checks**

- INR instruments retain Indian formatting.
- Crypto instruments display the correct settlement currency and sufficient decimals.
- Small non-zero P&L never hovers as an indistinguishable `0`.

---

### PG-13 — Plot interaction state is not preserved across simulator updates

**Priority:** P2  
**Evidence:** `frontend/src/components/strategy-builder/PayoffChart.tsx:52-332`, `frontend/src/components/strategy-builder/PayoffChart.tsx:278-320`

Every simulator update creates new data/layout objects, but the layout has no stable Plotly `uirevision`. Plotly can therefore reset zoom/pan/autorange state while the user drags IV or time controls, making detailed inspection jump back to the default view.

**What to fix**

- Add a deliberate `uirevision` keyed to strategy identity, not every scenario value.
- Reset it only when the underlying/legs change materially or when the user chooses `Fit strategy`.
- Verify drag performance and debounce or schedule expensive graph updates if profiling shows dropped frames.

---

### PG-14 — The graph has no explicit accessible equivalent

**Priority:** P2  
**Evidence:** `frontend/src/components/strategy-builder/PayoffChart.tsx:334-341`

The component supplies Plotly data but no graph-specific accessible name, description, keyboard-independent summary, or data table. Profit/loss areas also rely primarily on red/green fill.

**What to fix**

- Give the chart region an accessible name and concise dynamic description.
- Provide an expandable summary/table containing scenario date, spot, extrema, and breakevens.
- Do not use color alone: add labels, line styles, or patterns for profit/loss regions.
- Test keyboard access to modebar controls and screen-reader output.

---

### PG-15 — Near-expiry σ annotations collapse on top of the spot label

**Priority:** P3  
**Evidence:** `frontend/src/components/strategy-builder/PayoffChart.tsx:80-84`, `frontend/src/components/strategy-builder/PayoffChart.tsx:224-255`

The display calculation floors time at `1e-6` years. At zero remaining time it still creates four σ labels plus the spot label at almost identical x-coordinates. Even before zero, labels can become closer than their rendered width.

**What to fix**

- Do not floor time for display overlays.
- Hide σ bands at zero horizon.
- Suppress or stagger labels when projected pixel spacing is below a minimum.

**Pixel-level confirmation required:** verify the exact overlap threshold at desktop and mobile widths.

---

### PG-16 — Hover information is asymmetric and rounds away useful values

**Priority:** P3  
**Evidence:** `frontend/src/components/strategy-builder/PayoffChart.tsx:66-74`, `frontend/src/components/strategy-builder/PayoffChart.tsx:118-133`

The expiry hover shows percent change from live spot, while the dashed curve does not. Neither curve clearly labels the underlying price inside its own hover template, and P&L is rounded to zero decimals.

**What to fix**

Use one shared hover schema for every curve:

- underlying price with tick-aware precision;
- change from the relevant live/scenario spot;
- valuation date/T+n;
- P&L with currency-aware precision; and
- curve/model name.

---

### PG-17 — No payoff-specific automated regression suite exists

**Priority:** P2  
**Evidence:** no tests reference `computePayoff`, `probabilityOfProfit`, or `PayoffChart` under `frontend/src`.

The calculation path includes tail classification, root interpolation, asymptotic extrema, mixed expiries, closed legs, futures, IV fallback, and Plotly segmentation, but none has targeted regression coverage.

**What to fix**

Add:

1. table-driven unit tests for canonical strategies and exact analytical payoffs;
2. property tests for symmetry, monotonic tails, root uniqueness, and lot scaling;
3. mixed-expiry numerical-oracle tests;
4. component tests for trace labels, scenario props, and formatter metadata; and
5. visual regression snapshots at light/dark/analyzer themes and narrow/wide widths.

Minimum regression fixtures should include:

- long/short call and put;
- verticals, straddles, butterflies, condors, ratio spreads, futures, and synthetics;
- exact-grid and outside-window breakevens;
- zero and unavailable PoP;
- closed/inactive legs;
- calendar/diagonal strategies;
- high-IV/long-DTE domains;
- expiry-day behavior; and
- INR and crypto settlement/precision.

---

### PG-18 — Leg edits retain the previous contract's IV and Greeks

**Priority:** P1  
**Evidence:** `frontend/src/components/strategy-builder/EditLegDialog.tsx:163-176`, `frontend/src/pages/StrategyBuilder.tsx:491-583`, `frontend/src/pages/StrategyBuilder.tsx:899-931`

`EditLegDialog` creates the edited leg by spreading the old leg and changing strike, type, expiry, price, and quantity. It does not invalidate `iv`. `saveEditedLeg` rebuilds the symbol but also preserves that old positive IV.

The Greeks/IV fetch effect is keyed on `legs.length`, not on the active symbols/contracts. A strike, type, or expiry edit keeps the same leg count, so no refetch occurs. Even if another dependency later triggers the effect, the backfill logic explicitly preserves every `l.iv > 0`.

The result is a new contract priced with the previous contract's smile point, while the Greeks tab can retain the previous contract's cached Greeks under the same leg ID.

**Impact nuance**

- The dashed T+n curve is directly wrong after the edit.
- A mixed-expiry orange curve can also be wrong because later-expiry legs retain model value.
- Same-expiry terminal payoff and terminal PoP are intrinsic-payoff calculations, so they are not affected by stale per-leg IV in that specific case. The original Claude audit overstated this part.

**What to fix**

1. Compare the old and edited contract identity: segment, symbol, strike, option type, and expiry.
2. When identity changes, atomically clear the leg IV and cached Greeks before publishing the edited leg.
3. Key refresh work on a stable contract fingerprint, not `legs.length`.
4. Replace the “backfill only if zero” rule with provenance-aware state, so fetched IV can refresh while a deliberately user-specified IV remains protected if manual IV is later supported.
5. Ignore/cancel stale async results when a contract changes during a request.

**Acceptance checks**

- Editing `24000 CE` to `24500 CE` immediately marks IV/Greeks as loading or unavailable.
- The next successful response populates the new symbol's IV and Greeks.
- A late response for the old symbol cannot overwrite the edited leg.
- Changing only lots or side does not cause an unnecessary IV lookup.

---

### PG-19 — DTE and payoff valuation time freeze during a long-open session

**Priority:** P2  
**Evidence:** `frontend/src/pages/StrategyBuilder.tsx:465-486`, `frontend/src/pages/StrategyBuilder.tsx:842-877`, `frontend/src/lib/strategyMath.ts:491-511`

`nearestLegDays()` uses `new Date()` by default, but it is called inside a memo that reruns only when `legs` or `rawDays` changes. `rawDays` is itself memoized by selected expiry. The payoff memo then depends on that frozen DTE.

A strategy builder left open through the trading session can therefore retain the time basis from its last contract-state change. The error is most material on expiry day, when a few hours are a large fraction of the remaining option life.

**What to fix**

- Introduce a coarse valuation clock (for example, one update per minute while the page is visible).
- Pass one explicit `valuationNow` through DTE, curve, σ-band, and PoP calculations so all outputs use the same instant.
- Recompute on tab visibility resume and after manual refresh.
- Do not rely on unrelated spot or component renders to refresh time.

**Acceptance checks**

- DTE and T+n values advance without editing a leg.
- Suspending and resuming the tab catches up immediately.
- One render uses one consistent timestamp across every leg and metric.

---

### PG-20 — Template expiry changes can combine a new expiry with the previous chain's symbol and premium

**Priority:** P1  
**Evidence:** `frontend/src/pages/StrategyBuilder.tsx:328-360`, `frontend/src/components/strategy-builder/TemplateDialog.tsx:84-114`, `frontend/src/components/strategy-builder/TemplateDialog.tsx:204-218`, `frontend/src/pages/StrategyBuilder.tsx:753-788`

The template dialog lets the user change expiry. That starts an asynchronous chain reload, but `loadOptionChain` does not clear the previous `chainData` before fetching. `TemplateDialog` has no `chainExpiry` prop, so after the selected expiry changes it treats the still-present old chain as belonging to the new expiry.

During that window, `resolved` reads an old-expiry symbol and LTP. If the user clicks **Add Strategy**, `handleTemplateConfirm` stores:

- the newly selected expiry in `leg.expiry`;
- the old chain's non-null symbol in `leg.symbol`; and
- the old contract's premium in `leg.price`.

Because the price is already positive, the later zero-price backfill does not correct it. The symbol/expiry mismatch can then feed the wrong contract into IV/Greeks and order execution.

**What to fix**

- Track the authoritative expiry represented by `chainData`.
- Clear or mark the chain stale as soon as expiry changes.
- Resolve chain symbols/prices only when `resolvedExpiry === chainExpiry`.
- Disable **Add Strategy** while required chain data is loading or stale.
- On confirmation, validate that every symbol's parsed/returned expiry matches `resolvedExpiry`.

**Acceptance checks**

- Change the template expiry and immediately click Add: confirmation remains disabled until the matching chain arrives.
- Every confirmed leg has matching UI expiry, symbol expiry, premium source, and chain generation/request ID.
- A late response for the previous expiry cannot repopulate the dialog.

---

### PG-21 — Calendar templates silently collapse to one expiry

**Priority:** P2  
**Evidence:** `frontend/src/components/strategy-builder/TemplateDialog.tsx:84-99`, `frontend/src/pages/StrategyBuilder.tsx:297-307`, `frontend/src/lib/strategyTemplates.ts:466-507`

Calendar and diagonal legs use `expiryOffset: 1`, but the resolver clamps an out-of-range far expiry to the last available expiry. If the selected expiry is already last—or only one expiry is returned—the “far” leg resolves to the same expiry as the near leg.

Consequences:

- Call/put calendars can become equal-and-opposite same-strike positions with a flat payoff.
- The diagonal calendar becomes a same-expiry vertical, despite retaining the calendar name and description.
- The Add button remains enabled and no warning explains the degeneration.

The expiry array also preserves broker response order rather than sorting chronologically. `expiryOffset: 1` therefore means “next array item,” not necessarily “next later expiry.”

**What to fix**

- Parse and sort expiries chronologically before offset resolution.
- Require `farExpiry > nearExpiry`.
- Disable the calendar/diagonal template when a later expiry is unavailable.
- Show both resolved expiries prominently before confirmation.

---

### PG-22 — Template strike resolution does not enforce distinct, ordered legs

**Priority:** P2  
**Evidence:** `frontend/src/pages/StrategyBuilder.tsx:341`, `frontend/src/pages/StrategyBuilder.tsx:453-463`, `frontend/src/components/strategy-builder/TemplateDialog.tsx:46-57`, `frontend/src/components/strategy-builder/TemplateDialog.tsx:82-114`, `frontend/src/components/strategy-builder/TemplateDialog.tsx:127-165`, `frontend/src/lib/strategyTemplates.ts:421-445`, `services/option_symbol_service.py:414-489`

The default Iron Condor definition itself is canonical and symmetric:

- long put at `ATM - 4` steps;
- short put at `ATM - 2`;
- short call at `ATM + 2`; and
- long call at `ATM + 4`.

However, each target is independently snapped to its nearest available strike. On sparse, truncated, or irregular strike grids, two requested offsets can resolve to the same strike. Manual overrides also allow duplicate or crossed strikes without validation.

An Iron Condor can therefore silently become a narrower spread, duplicate/canceling legs, an inverted wing, or a non-condor while still carrying the Iron Condor name and preview.

The resolver's use of the **global minimum** positive gap is also the wrong abstraction for an offset documented as a number of listed “strike steps.” The repository already has the safer implementation pattern in `services/option_symbol_service.py:414-489`: find ATM in the sorted available-strike list and move by index. Its module documentation explicitly recommends this path because it handles unequal strike intervals.

**Read-only master-contract validation**

- The exact screenshot expiry, NIFTY `04-AUG-26`, contains 93 call strikes from `21,600` to `26,200`; all 92 adjacent gaps are exactly `50`. Therefore global-minimum spacing and local spacing are identical for that render, and this resolver defect did **not** cause its visible shoulder.
- The latent defect is nevertheless reproducible with current contract data. NIFTY `29-DEC-26` has non-uniform listed strikes around `24,000`: `... 22,500, 23,000, 24,000, 25,000, 25,500 ...`, while the global minimum is `500`. A requested `+1` step targets `24,500`; the tie-breaking `nearestStrike()` selects the earlier `24,000`, collapsing that leg onto ATM. Templates using adjacent offsets, including condors, can consequently duplicate or cancel legs.
- Current BANKNIFTY and quarterly NIFTY master-contract lists also contain multiple gap sizes, so this is not purely hypothetical. It is most dangerous on sparse/long-dated chains and near a truncated chain edge, not on the supplied uniform weekly NIFTY chain.

This is a P2 template-integrity defect, not two separate P1/high findings. Large offsets increase the chance of edge clamping, but they do not guarantee inward snapping, and the resulting risk can increase or decrease depending on leg sides, quantities, and the live debit/credit.

**What to fix**

- Resolve offsets by sorted strike **index** around the ATM index where possible.
- Validate template invariants before enabling Add.
- For the Iron Condor require:
  `longPut < shortPut < shortCall < longCall`.
- Require positive wing widths and show the actual left/right widths.
- Reject duplicates and crossed wings rather than silently snapping.

---

### PG-23 — Hand-authored template previews can contradict the actual legs

**Priority:** P2  
**Evidence:** `frontend/src/lib/strategyTemplates.ts:29-37`, `frontend/src/lib/strategyTemplates.ts:304-328`, `frontend/src/components/strategy-builder/TemplateGrid.tsx:39-66`

Every preview is a manually authored SVG path independent of the template legs and payoff engine. A topology comparison across all 38 definitions found no duplicate IDs or duplicate contract definitions, and most same-expiry previews match their leg slope sequence. Two previews do not:

- **Jade Lizard:** the icon draws a flat far-left tail, but the naked short put keeps losing as spot falls toward zero.
- **Reverse Jade Lizard:** the icon draws a flat far-right tail, but the naked short call has unlimited upside loss.

Calendar/diagonal previews are also necessarily illustrative because their shape depends on DTE, IV, premiums, and the valuation horizon; the static icon cannot promise a fixed topology/peak location.

**What to fix**

- Generate same-expiry mini-payoffs from the template legs using normalized strikes/premiums.
- For calendars, label previews as illustrative or generate them from explicit reference DTE/IV assumptions.
- Add topology tests comparing preview slope/tail direction with resolved legs.

---

### PG-24 — Several template descriptions are mathematically or structurally inaccurate

**Priority:** P2  
**Evidence:** `frontend/src/lib/strategyTemplates.ts:163-168`, `frontend/src/lib/strategyTemplates.ts:193-202`, `frontend/src/lib/strategyTemplates.ts:205-214`, `frontend/src/lib/strategyTemplates.ts:330-367`, `frontend/src/lib/strategyTemplates.ts:434-445`

Confirmed copy/semantics problems:

1. **Short Iron Condor** says “long wings,” but its code buys the inner options and sells the outer wings.
2. **Long Put** says downside profit is unlimited. Spot is floored at zero, so maximum profit is finite.
3. **Put Ratio Back Spread** similarly calls downside profit unlimited.
4. **Put Ratio Spread** calls downside loss unlimited.
5. **Batman Strategy** says loss is unlimited on both wings; only the upside tail is mathematically unbounded, while downside loss is capped at spot zero.
6. **Call/Put Ratio Back Spread** promises a “small credit,” but the template neither checks nor enforces the live net premium; the structure can price for a debit.

These descriptions should distinguish “large/substantial” downside exposure from truly unbounded upside exposure.

**What to fix**

- Derive bounded/unbounded tail badges from the leg slopes already used by payoff math.
- Derive live debit/credit labels from resolved premiums.
- Keep prose conditional when the outcome depends on market prices.
- Add reviewed canonical definitions for every template name.

---

### PG-25 — Uniform payoff samples omit exact strikes and visibly soften Iron Condor kinks

**Priority:** P2  
**Evidence:** supplied Iron Condor screenshot, `frontend/src/pages/StrategyBuilder.tsx:842-870`, `frontend/src/lib/strategyMath.ts:322-341`

The orange expiry payoff is piecewise linear and must change slope exactly at each strike. The graph samples 241 uniformly spaced prices across ±10% but does not insert active strikes.

For the supplied NIFTY example:

- spot is `23,985.35`;
- the ±10% / 240-step grid is approximately `19.99` points apart; and
- expected Iron Condor kinks at `23,800`, `23,900`, `24,100`, and `24,200` fall between grid points.

The screenshot shows the resulting subtle shoulders: the loss plateau/ramp and ramp/profit-plateau transitions appear around neighboring samples rather than as crisp vertices at the actual strikes. This makes the top plateau look slightly narrower/asymmetric even though the template strikes are symmetric.

This is separate from max-profit/max-loss metrics, which use structural candidates for same-expiry strategies.

The exact master-contract check above isolates the cause more strongly than visual inference alone: every strike in the screenshot's NIFTY `04-AUG-26` chain is 50 points apart. Unequal strike spacing (PG-22 / Claude H4-H6) was inactive, while the 19.99-point payoff grid demonstrably missed the four expected condor strikes. Unequal wing widths would change the ramp width or tail levels, but would not create an extra kink inside an otherwise linear vertical-spread ramp.

**What to fix**

- Build the display x-grid as the sorted union of:
  uniform background samples, all active strikes, interpolated breakevens, live spot, and simulated spot.
- Ensure the Plotly line has an explicit vertex at every payoff kink.
- Add a visual regression for a symmetric Iron Condor and butterfly.

---

### PG-26 — IV/Greeks are one-shot snapshots and leg IV is never refreshed after backfill

**Priority:** P1  
**Evidence:** `frontend/src/pages/StrategyBuilder.tsx:491-583`

The `/multioptiongreeks` effect has no polling or market-data revision dependency. It runs when the leg count, selected market, underlying, or ATM strike changes. Once a fetched IV is copied into a leg, the `if (l.iv > 0) return l` guard prevents every later response from updating the IV used by `computePayoff()`.

Consequences:

- the Greeks panel is a snapshot with no timestamp or stale-state indicator;
- the T+n payoff curve can keep the first fetched IV for the rest of a long-open session;
- changing a contract at the same leg count preserves the old IV (PG-18); and
- merely adding a symbol fingerprint to the dependency list fixes identity invalidation, but does not make live IV update because the positive-IV guard still blocks replacement.

The code comment that the effect “reads the latest legs snapshot” is also inaccurate: React effects close over the render that created them. A change excluded from the dependency list does not rerun the body with a newer leg array.

**What to fix**

- Separate live market IV from user/scenario IV state.
- Refresh Greeks/IV on a documented interval or market-data revision, and expose the as-of time.
- Key requests by a stable contract fingerprint and discard responses whose fingerprint is no longer current.
- Invalidate contract-specific values immediately on strike/type/expiry edits.
- Do not use “already positive” as a freshness policy.

**Acceptance checks**

- A same-count contract edit refetches the new symbol and cannot apply the old response.
- A live IV change updates the unshifted T+n curve without adding/removing a leg.
- The panel exposes its last successful update time and stale/error state.

## Supplied Iron Condor screenshot — close visual validation

The screenshot does **not** show a wrong default Iron Condor leg definition. It does confirm these subtle rendering issues:

| Observation                                                                                 | Disposition                                                                                                                                                                         |
| ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Symmetric expiry max-loss tails and central max-profit plateau                              | Template leg sides/ratios look correct.                                                                                                                                             |
| Plateau shoulders do not turn exactly at round strikes                                      | Confirms PG-25: uniform samples omit strike vertices.                                                                                                                               |
| Small red/green boundary slivers near both breakevens                                       | Confirms PG-08: fill traces switch at samples, not interpolated roots.                                                                                                              |
| Only `+1σ` is visible in the supplied viewport; `-1σ` and both `±2σ` labels are absent      | Confirms a zoomed-viewport/context problem in PG-06/PG-11. It does **not** prove H3's initial-autorange scenario because the screenshot is zoomed well inside the ±10% data domain. |
| Much of the visible plot remains covered by σ wash even though most σ labels are off-screen | The overlay becomes difficult to interpret after zoom; hide/clamp/relabel based on the visible range.                                                                               |
| Dashed T+0 curve sits close to, but not exactly at, zero near current spot                  | Consistent with PG-02's model/input reconciliation issue; the screenshot alone is not sufficient to quantify the pricing error.                                                     |

## Validation of the revised Claude audit

The revised audit is useful but is **not valid verbatim**. The table below is the final disposition after source tracing, numerical reproductions, the supplied screenshot, Plotly 3.3.1 autorange source, and a read-only check of the local master-contract database.

| Claude finding                                                       | Disposition                                                 | Final report mapping / correction                                                                                                                                                                                                                     |
| -------------------------------------------------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| H1 stale IV after editing a leg                                      | **Confirmed, scope corrected**                              | PG-18/P1 and PG-26/P1. It corrupts T+n and mixed-expiry valuation; same-expiry terminal intrinsic payoff/PoP does not use IV.                                                                                                                         |
| H2 fixed ±10% window hides breakevens                                | **Confirmed**                                               | PG-01/P1 and PG-06/P2. Numerically reproduced. “Max P/L remains exact” applies only to compatible same-expiry piecewise-linear cases, not calendars/diagonals.                                                                                        |
| H3 σ bands independent of sampled range                              | **Mechanism confirmed; evidence/severity corrected**        | PG-06/PG-11, P2. Plotly 3.3.1 includes axis-referenced shapes and annotations in autorange, so an out-of-domain band can expand the initial axis and leave curve-less space. The supplied zoomed screenshot does not prove this case.                 |
| H4 global-minimum strike step can distort symmetric templates        | **Latent defect confirmed; screenshot attribution refuted** | Merged into PG-22/P2. Actual NIFTY `04-AUG-26` gaps are uniformly 50, so H4 was inactive in the screenshot. Also, unequal wing spacing alone cannot create an extra internal kink in a linear vertical-spread ramp.                                   |
| H5 fills switch at sample positions, not exact roots                 | **Confirmed**                                               | PG-08/P2. The mismatch scales with payoff slope × sample spacing, and the screenshot shows it. This is a visual fidelity defect; it does not alter the orange curve's calculated root.                                                                |
| H6 large offsets amplify H4 and understate risk                      | **Partially confirmed; merge with H4**                      | PG-22/P2. Large offsets raise edge-clamping/collapse exposure. “Always pulled toward ATM” and “understates risk” are not valid general conclusions; nearest snapping can go either way and risk impact depends on the resolved structure and premium. |
| M1 piecewise-linear extrema assumption fails for calendars/diagonals | **Confirmed**                                               | PG-04/P1. The arbitrary far-right candidate can also understate a bounded plateau.                                                                                                                                                                    |
| M2 Greeks/IV effect keyed on leg count                               | **Confirmed and broadened**                                 | PG-18/P1 and PG-26/P1. Identity invalidation is broken, and there is no periodic live refresh. An active-only fingerprint is insufficient unless response races and the positive-IV guard are also fixed.                                             |
| M3 Payoff and Strategy Chart disagree on futures                     | **Rejected as a defect**                                    | Strategy Chart is an historical **option-premium** chart, intentionally filters futures, and already displays the explicit warning at `StrategyChartTab.tsx:600-603`. A clearer tab name is optional copy polish.                                     |
| M4 DTE can go stale during a session                                 | **Confirmed**                                               | PG-19/P2.                                                                                                                                                                                                                                             |
| M5 uniform samples omit strikes and bevel kinks                      | **Confirmed, absolute wording corrected**                   | PG-25/P2. A uniform grid can land on a strike by coincidence; it simply does not guarantee/inject it. For the supplied screenshot, the ~19.99-point grid misses all four expected 50-point strikes, so this cause is confirmed.                       |
| L1 `Math.sign()` exact-zero edge case                                | **Confirmed**                                               | PG-07/P2. Numerically reproduced as duplicate `[105, 105]`.                                                                                                                                                                                           |
| L2 PoP inherits the ±10% blind spot                                  | **Confirmed; severity raised**                              | Included in PG-01/P1 because it can report 0% when a real profitable tail exists.                                                                                                                                                                     |
| L3 frontend/backend near-expiry epsilon mismatch                     | **Confirmed, subsumed**                                     | Part of PG-02/P1. Frontend switches to intrinsic near `1e-6` years while the backend floors positive remaining time to `1e-4` years; the broader Black-Scholes/Black-76 contract mismatch is the root problem.                                        |

Additional corrections to the revised write-up:

- Its statement that a Codex pass “returned back the document essentially verbatim” is not an accurate description of this validation. This report independently disagrees on H3 evidence/severity, H4 screenshot causation, H6 risk direction/severity, M3's defect status, and several scope claims.
- The exposure survey should say H5/M5 are **shared code-path exposures**, not guaranteed visible failures for every render. H5 needs a zero crossing in the displayed domain; M5 disappears whenever a strike happens to coincide with a grid point.
- The exposure table still says Iron Condor is “High (confirmed live)” even though its later prose says to downgrade that label. The exact chain check now goes further: H4/H6 are ruled out for this screenshot.
- H6's ±20 citation belongs at `StrategyBuilder.tsx:341`, where the page passes literal `20`, not at the unused fallback in `frontend/src/api/option-chain.ts:23`.
- The revised audit omits PG-20 through PG-24 and PG-26, including the expiry/chain race, calendar collapse, actual-strike invariant failures, preview/copy errors, and permanently stale live IV used by payoff repricing.

## Recommended repair order

1. **Prevent stale/wrong contract identity and market state:** PG-18, PG-20, PG-26.
2. **Correct the calculation contract and clock:** PG-02, PG-05, PG-19.
3. **Separate complete risk math from chart sampling:** PG-01, PG-04, PG-07, PG-08, PG-25.
4. **Make scenario state coherent:** PG-03, PG-09, PG-10, PG-11.
5. **Harden template resolution and metadata:** PG-21, PG-22, PG-23, PG-24.
6. **Fix chart domain and interaction behavior:** PG-06, PG-13, PG-15, PG-16.
7. **Finish cross-market and accessibility support:** PG-12, PG-14.
8. **Lock behavior with regression coverage:** PG-17.

## Definition of done

The payoff graph should not be considered fixed until:

- displayed roots, PoP, and extrema are independent of the visible chart window;
- editing a contract invalidates and refetches contract-specific IV/Greeks without stale-response races;
- live IV/Greeks have a documented refresh policy, as-of timestamp, and stale-state behavior;
- T+n pricing and Greeks share one model/input contract;
- DTE and valuation time continue to advance while the builder remains open;
- every simulator control updates one coherent scenario;
- multi-expiry labels and metrics identify their valuation horizon;
- active strikes, roots, spot markers, and expected-move bands fit on initial render;
- currency, precision, and expiry timestamps are instrument-aware;
- zoom survives scenario adjustments;
- template confirmation cannot mix chain generations, expiries, symbols, or premiums;
- condor/butterfly/calendar templates satisfy their ordering and expiry invariants;
- template previews and descriptions agree with their actual bounded/unbounded tails;
- keyboard/screen-reader users have an equivalent summary; and
- canonical plus adversarial payoff cases are covered by automated and visual tests.

---

## Independent Validation (Claude, second pass)

This section is an independent fact-check of this report, requested after the report was produced. Rather than take its claims on trust (including the places where it corrects Claude's own earlier `STRATEGY_BUILDER_PAYOFF_AUDIT.md`), every specific, checkable claim below was re-derived from the live source tree and the live `db/openalgo.db` master-contract data — not just re-read for internal consistency. Cross-referenced against `docs/prompt/symbol-format.md`, `docs/prompt/order-constants.md`, and `docs/prompt/services_documentation.md` for terminology/architecture grounding.

### Checks performed and results

| # | Claim checked | Method | Result |
|---|---|---|---|
| 1 | NIFTY `04-AUG-26` CE strikes: 93 strikes, `21,600`-`26,200`, all gaps exactly `50` | `sqlite3 db/openalgo.db` against `symtoken` (`name='NIFTY' AND exchange='NFO' AND instrumenttype='CE' AND expiry='04-AUG-26'`) | **Confirmed exactly.** `MIN=21600, MAX=26200, COUNT(DISTINCT strike)=93`; gap distribution query returns a single value, `50.0`, for all 92 adjacent gaps. |
| 2 | NIFTY `29-DEC-26` has non-uniform strikes near `24,000` (`22500, 23000, 24000, 25000, 25500`), global-min gap `500` | Same DB, `expiry='29-DEC-26'` | **Confirmed exactly**, including the literal strike list quoted in the report. Full gap histogram: `500→10, 1000→9, 1500→3`. |
| 3 | At that `29-DEC-26` chain, a `+1` step from ATM `24000` targets `24500`, which is equidistant (`500`) from both `24000` and `25000`, and `nearestStrike()`'s tie-break keeps the earlier `24000` | Re-read `TemplateDialog.tsx:46-58`; the loop only updates on strict `d < bestDist`, so the first-encountered candidate at a tied minimum distance wins, and `strikes` is built ascending | **Confirmed.** The tie-break mechanism matches the claim precisely — a materially different (and more precise) counterexample than anything in Claude's original audit, which only asserted this kind of collision was "plausible," not reproduced it. |
| 4 | Plotly pinned at `3.3.1` | `grep plotly frontend/package.json` | **Confirmed**: `"plotly.js-dist-min": "^3.3.1"`. |
| 5 | `StrategyChartTab.tsx:600-603` already shows an explicit "futures excluded" warning, rejecting Claude's M3 | Direct read | **Confirmed exactly**, word-for-word: *"Note: Futures legs are excluded from the combined premium — price levels are not premia."* Claude's original M3 finding is fairly overturned. |
| 6 | `services/option_symbol_service.py:413-493` (`calculate_offset_strike_from_actual`) already resolves offsets by **list index** around ATM, not by price distance | Direct read | **Confirmed.** `atm_index = available_strikes.index(atm_strike)`, then `target_index = atm_index ± num`. This is exactly the safer pattern the report says the Strategy Builder's own template resolver should have used instead of `nearestStrike()`. |
| 7 | `PositionsPanel.tsx` shows PoP as `—` whenever `probOfProfit === 0`, indistinguishable from unavailable | Direct read, line ~399 | **Confirmed exactly**: `probOfProfit > 0 ? formatPct(...) : '—'`. |
| 8 | Template description text errors (Short Iron Condor "long wings"; Long Put / Put Ratio Back Spread / Put Ratio Spread / Batman "unlimited downside") | `grep` against `strategyTemplates.ts` | **Confirmed for all five quotes**, verbatim. Cross-checked `short_iron_condor`'s actual legs (`SELL PE -4`, `BUY PE -2`, `BUY CE +2`, `SELL CE +4`) against its description's "long wings pay off on a big move" — the wings (offsets `±4`) are **sold**, the body (`±2`) is **bought**, the opposite of the prose. The description bug is real. |
| 9 | `loadOptionChain` (`StrategyBuilder.tsx:328-360`) never clears `chainData` before an expiry-change refetch, only guards against a *stale response* via `reqId`, not a *stale current value* while the new request is in flight | Direct read | **Confirmed.** There is a request-ID race guard, but no `setChainData(null)`/pending flag — `chainData` visibly holds the previous expiry's chain for the full duration of the new fetch. |
| 10 | `TemplateDialog` has no independent `chainExpiry` prop and compares `resolvedExpiry === expiry` (the same live "current expiry" state that already flipped), not against what the passed-in `chain` prop actually represents | Direct read of `TemplateDialog.tsx` props and `resolved` memo | **Confirmed.** The props are `template, expiry, expiries, onExpiryChange, chain, atmStrike, strikeStep, onConfirm` — no `chainExpiry`. Combined with #9, this is a real, reproducible race: `expiry` updates synchronously on selection, `chain` updates only after the async refetch resolves, and `canUseChain` can read `true` while `chain` is still the old expiry's data. |
| 11 | Calendar/diagonal `expiryOffset` clamps to the last available expiry (`Math.min(baseIdx + offset, expiries.length - 1)`), collapsing near/far legs to the same expiry when only one expiry is available or the base is already last | Direct read of `TemplateDialog.tsx` `resolved` memo | **Confirmed exactly** — the clamp is real and produces the claimed collapse in the stated edge case. |
| 12 | `expiries` array is not independently re-sorted chronologically on the frontend | `grep sort` in `StrategyBuilder.tsx`'s `normaliseList`; cross-checked `services/expiry_service.py` | **Partially confirmed, severity nuance found.** The frontend indeed does not re-sort — it trusts whatever order the backend returns. But `services/expiry_service.py:228` does call `sorted(live_expiry_dates, key=parse_expiry_date)` server-side, so in the common path the array **is** chronological by the time it reaches the frontend. The report's phrasing ("`expiryOffset: 1` therefore means 'next array item,' not necessarily 'next later expiry'") reads as a present-tense bug; it is more accurately a **missing defensive invariant on the frontend** that would only misfire if the backend's sort guarantee were ever violated (a different broker path, a parsing edge case), not something independently broken in today's normal flow. Worth a one-line softening, not a retraction. |

### Where this report is stronger than Claude's original audit

Every one of the above was either unverified-in-practice in Claude's original pass (H4/H6 were argued from plausibility, not measured against real chain data) or missed entirely (PG-09, PG-20, PG-21, PG-23, PG-24, PG-26 have no equivalent in the original 14 findings). The specific, reproducible NIFTY `29-DEC-26` tie-break counterexample (#2-#3 above) is materially better evidence than anything in the original audit for the same underlying mechanism, and the direct DB check that NIFTY `04-AUG-26` is uniformly 50-wide (#1) is a correct and now-verified refutation of the original audit's "confirmed live" attribution for H4 against that specific screenshot.

### Where a residual nuance remains (not a factual error, a framing note)

- **PG-21's severity framing** (#12 above) is slightly stronger than the current code path actually risks, given the backend already sorts expiries. This doesn't change the P2 priority or the recommended fix (require `farExpiry > nearExpiry` defensively on the frontend too) — it just means this is presently a latent/defense-in-depth gap rather than an active miss in the common case.
- **H6's "always pulled toward ATM" framing**, which this report already downgrades to "not a valid general conclusion" — that downgrade is itself correct: `nearestStrike()`'s tie-break can go to either neighbor depending on iteration order and exact distances, not deterministically "inward" in every case, even though the *global-minimum-instead-of-local-spacing* root cause is real and confirmed (as items #2-#3 show for one concrete, reproduced case).
- The report explicitly and correctly flags its own biggest limitation: no live browser session was available, so PG-06/PG-13/PG-14/PG-15/PG-16 (autorange/interaction/accessibility) are traced from source and Plotly's documented behavior, not pixel-confirmed in a running instance. That caveat is honestly stated in the report's own "Audit limitation" section and this validation pass did not have browser access either, so those specific items remain source-level-confirmed rather than pixel-confirmed.

### Verdict

**All of the specific, independently checkable claims in this report — the master-contract strike-spacing data, the code mechanisms for PG-09/18/20/21/22/24/26, the Plotly version, the `StrategyChartTab` warning text, and the `option_symbol_service.py` index-based reference pattern — check out exactly against the live database and source tree.** Nothing examined was fabricated or misquoted. The one soft spot is PG-21's severity phrasing, which slightly overstates present-day risk given the backend's existing chronological sort — a wording nuance, not a factual error, and it doesn't change the fix that's needed.

This report supersedes `audit/STRATEGY_BUILDER_PAYOFF_AUDIT.md` for the Iron Condor screenshot's root cause specifically (M5, not H4/H6, per the now-verified uniform 50-point NIFTY `04-AUG-26` chain) and materially extends it with real, previously-unreported P1/P2 defects (PG-09, PG-20, PG-21, PG-23, PG-24, PG-26). Treat this file, not the original, as the authoritative punch list for fixes going forward.
