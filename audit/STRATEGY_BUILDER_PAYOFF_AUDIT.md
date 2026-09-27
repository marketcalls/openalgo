# Strategy Builder — Payoff Graph Correctness Audit

> **Generated**: 28th July 2026
> **Scope**: `/strategybuilder` payoff graph and everything that feeds numbers into it — payoff-curve math (`frontend/src/lib/strategyMath.ts`), the chart component (`frontend/src/components/strategy-builder/PayoffChart.tsx`), the page-level orchestration (`frontend/src/pages/StrategyBuilder.tsx`), the leg-edit dialog (`frontend/src/components/strategy-builder/EditLegDialog.tsx`), the metrics panel (`frontend/src/components/strategy-builder/PositionsPanel.tsx`), the adjacent Strategy Chart backend service (`services/strategy_chart_service.py`), and — added in a follow-up pass — the strategy templates (`frontend/src/lib/strategyTemplates.ts`) and their strike-resolution logic (`frontend/src/components/strategy-builder/TemplateDialog.tsx`).
> **Methodology**: Manual trace of the data path from leg state → payoff sampling → breakeven/max-profit/max-loss → chart rendering, cross-checked against the documented intent in each file's own comments (several findings are cases where the code's own comment claims a guarantee — "true mathematical maximum", "critical for calendar/diagonal spreads" — that the implementation doesn't fully deliver). The template-fidelity findings (PB-H4/H5/M5) were triggered by a close visual read of a live "Long Iron Condor" render (`NIFTY — 04AUG26`) that shows exactly the artifacts described below: a small shading/curve mismatch at the left breakeven and a shoulder on the call side that breaks into two segments where the payoff should have a single straight line. A follow-up pass then swept all 38 templates in `strategyTemplates.ts` for the same root causes (see **Template-by-Template Exposure Survey** and **PB-H6**) to establish which other templates share the exposure and which don't.
> **Status**: Findings only. No fixes applied in this pass.

---

## Why this audit

The Strategy Builder's Payoff tab is the primary decision surface for the tool — traders read Max Profit / Max Loss / Breakeven and the P&L curve shape directly off it before executing a multi-leg options basket. Silent inaccuracies here don't crash anything; they misinform a live trading decision, which is a worse failure mode than a visible error. This audit focuses on where the *displayed numbers* can diverge from the *true* payoff, not on styling or layout.

---

## Executive Summary

| Severity | Count | Nature |
| --- | --- | --- |
| High | 6 | Stale IV silently reused after editing a leg; breakeven/curve visibility silently capped by a fixed ±10% window; σ-bands drawn outside the plotted curve's range; **`strikeStep` detected from the chain's global-minimum gap, not local spacing — nominally symmetric templates (condors, flies, butterflies) can resolve to visibly asymmetric strikes**; **profit/loss shading is computed at the wrong (pre-sample) resolution and visibly disagrees with the curve's true zero-crossing**; **large `strikeOffset` templates (Batman, Double Fly) get systematically pulled toward ATM, understating real risk rather than just looking cosmetically uneven** |
| Medium | 5 | Max Profit/Loss "true mathematical maximum" claim breaks for calendar/diagonal spreads; Greeks/IV refresh keyed on leg *count* not leg *content*; Payoff tab vs. Strategy Chart tab disagree on whether futures legs count; payoff curve can go stale over wall-clock time; **240 uniformly-spaced samples never land exactly on a strike, so every kink renders as a subtly beveled double-segment instead of one sharp corner** |
| Low | 3 | Sign()-based zero-crossing edge case; Probability-of-Profit tail extrapolation inherits the ±10% window's blind spot; frontend/backend use different near-expiry epsilon floors |

**Root cause pattern**: three of the top findings (H-2, H-3, M-2) all trace back to the same fixed ±10% price band and one shared staleness pattern (H-1, M-4) — fixing the sampling-range and the IV-refresh-trigger would resolve most of the practical impact in one pass. The template-fidelity findings added below (H-4, H-5, H-6, M-5) are a second, independent cluster: all four are why a symmetric-by-recipe template like Iron Condor can visibly render as slightly lopsided even though `strategyTemplates.ts` itself defines it correctly — and per the **Template-by-Template Exposure Survey** below, H-4/H-6 aren't unique to Iron Condor: every butterfly, condor, and iron-fly template shares the exact same exposure, and Batman/Double Fly/Double Condor are worse (more legs, larger offsets).

---

## High Findings

### [PB-H1] Editing a leg's strike/expiry/type keeps the *old* implied volatility

- **Location**: `frontend/src/components/strategy-builder/EditLegDialog.tsx:163-177` (`handleSave`), `frontend/src/pages/StrategyBuilder.tsx:899-932` (`saveEditedLeg`), `frontend/src/pages/StrategyBuilder.tsx:567-574` (IV backfill effect)
- **Evidence**:
  ```ts
  // EditLegDialog.tsx:163-177
  const handleSave = () => {
    const updated: StrategyLeg = {
      ...leg,
      side, expiry, lots: Math.max(1, lots),
      price: Number(entryPrice) || leg.price,
      exitPrice: exitPrice.trim() === '' ? undefined : Number(exitPrice) || undefined,
    }
    if (leg.segment === 'OPTION') {
      updated.strike = strike ?? leg.strike
      updated.optionType = optionType
    }
    onSave(updated)   // `updated.iv` is never touched — carries the PRE-EDIT iv forward
  }
  ```
  ```ts
  // StrategyBuilder.tsx:567-574 — the only place that ever backfills leg.iv
  setLegs((prev) =>
    prev.map((l) => {
      if (l.iv > 0) return l          // <-- never overwrites an already-nonzero iv
      const iv = map[l.id]?.iv
      return iv ? { ...l, iv } : l
    })
  )
  ```
  The effect that populates this `map` is keyed on `[apiKey, legs.length, selectedExchange, selectedUnderlying, atmStrike]` (`StrategyBuilder.tsx:583`) — it does not re-run when an existing leg's strike/expiry changes without the leg *count* changing.
- **Failure scenario**: User adds a leg at strike 24000 (IV backfilled to, say, 14.2%). User then edits the same leg in the dialog to strike 24500 (a different point on the vol skew, commonly 1-2 points of IV different intraday). The leg keeps `iv = 14.2` — both because the refresh effect never re-fires (leg count unchanged) and because even if it did, the `l.iv > 0` guard would refuse to overwrite it. The T+0 curve, the Greeks tab, and Probability-of-Profit for the *new* strike are all computed with the *old* strike's volatility, with no error, warning, or visual indicator that anything is stale.
- **Fix direction**: On save, reset `iv` (and cached Greeks) to `0` whenever `strike`, `optionType`, or `expiry` changes, so the next fetch treats it as unbackfilled; and key the Greeks-refresh effect on a stable fingerprint of leg `(symbol, active)` pairs rather than `legs.length`.

### [PB-H2] Fixed ±10% price window silently caps which breakevens are ever found — while Max Profit/Loss are computed correctly beyond it

- **Location**: `frontend/src/pages/StrategyBuilder.tsx:858` (range), `frontend/src/lib/strategyMath.ts:322-353` (`computePayoff` samples + breakevens)
- **Evidence**:
  ```ts
  // StrategyBuilder.tsx:858
  const range: [number, number] = [spotPrice * 0.9, spotPrice * 1.1]
  ```
  ```ts
  // strategyMath.ts:343-353 — breakevens are ONLY found via zero-crossings
  // within the sampled `samples` array, i.e. only within that ±10% window.
  const breakevens: number[] = []
  for (const idx of zeroCrossings) { ... }
  ```
  Meanwhile Max Profit/Max Loss (`strategyMath.ts:374-405`) are computed *structurally* from strikes + asymptotic slope, independent of the sampled window, and correctly report values (or `Infinity`) even when the true extremum lies outside ±10%.
- **Failure scenario**: A short strangle or wide iron condor on a monthly NIFTY/BANKNIFTY expiry commonly has breakevens 12-18% away from spot (well outside ±10%, especially with weeks of IV baked in). The Max Profit/Max Loss tiles report correct finite numbers, but `breakevens` comes back empty (or, worse, reports the artefactual sign of whatever the curve happens to be doing at the ±10% edge as if it were a crossing — see PB-L1). The user sees Max Profit/Loss but no breakeven chips at all for a strategy that unquestionably has them, with nothing indicating the window was too narrow to find them.
- **Fix direction**: Size the sampled range off the same volatility measure already used for the σ-bands (e.g. spot ± max(10%, 3σ) using `atmIv` and days-to-expiry) instead of a flat 10%, or compute breakevens via the same strike-based structural method used for Max Profit/Loss rather than by scanning the finite sample array.

### [PB-H3] σ-bands are computed independently of the plotted curve's x-range and can fall entirely outside it

- **Location**: `frontend/src/components/strategy-builder/PayoffChart.tsx:80-84` (σ calc) vs. `StrategyBuilder.tsx:858` (curve's x-domain)
- **Evidence**:
  ```ts
  // PayoffChart.tsx:80-84 — sigma bands use REAL iv/time, unrelated to the
  // ±10% window the curve itself (`xs`, `ysExpiry`, `ysT0`) is sampled over.
  const sigmaT = (atmIv / 100) * Math.sqrt(Math.max(tYears, 1e-6))
  const sigmaMove = spot * sigmaT
  const band = (n: number) => ({ lo: spot - n * sigmaMove, hi: spot + n * sigmaMove })
  ```
- **Failure scenario**: For a monthly-expiry, higher-IV instrument (e.g. `atmIv` ~ 22%, `tYears` ~ 0.08 for ~30 DTE), `sigmaMove ≈ spot × 0.062`, so the ±2σ markers sit at roughly ±12.4% — already past the ±10% sampled curve. The `±2σ` (and sometimes `±1σ`) vertical tick + shaded rect + annotation label are drawn past the last point of the "At Expiry"/"T+0" lines, in a region with no P&L curve at all — either clipped by Plotly's axis range or, if Plotly's shape-driven autorange kicks in, stretching the visible plot so the actual curve is compressed into a small portion of the chart. Either way the σ overlay — meant to show "how far is 1/2 standard deviations from here" relative to the payoff — visually disagrees with the curve it's supposed to annotate.
- **Fix direction**: Once PB-H2's sampling range is tied to the same σ measure, this resolves itself; short of that, clamp the σ band/tick rendering to the curve's actual `[lo, hi]` domain rather than drawing unconditionally.
- **Confirmed live**: the `NIFTY — 04AUG26` Long Iron Condor screenshot referenced below shows exactly this — only a single `+1σ` label/tick is visible near the right edge of the chart; `-1σ`, `-2σ`, and `+2σ` are all off-frame, with nothing on screen indicating three of the four σ markers even exist for this render.

### [PB-H4] `strikeStep` is detected as the chain's global-minimum gap, not the local spacing around each leg's resolved strike — symmetric templates can resolve to asymmetric strikes

- **Location**: `frontend/src/pages/StrategyBuilder.tsx:454-463` (`strikeStep` detection), `frontend/src/components/strategy-builder/TemplateDialog.tsx:46-58` (`nearestStrike`), `TemplateDialog.tsx:84-114` (`resolved` — per-leg target + snap)
- **Evidence**:
  ```ts
  // StrategyBuilder.tsx:454-463
  const strikeStep = useMemo(() => {
    if (!chainData?.chain || chainData.chain.length < 2) return 50
    const sorted = [...chainData.chain].map((s) => s.strike).sort((a, b) => a - b)
    let minDiff = Infinity
    for (let i = 1; i < sorted.length; i++) {
      const d = sorted[i] - sorted[i - 1]
      if (d > 0 && d < minDiff) minDiff = d   // <-- global minimum over the WHOLE fetched chain
    }
    return Number.isFinite(minDiff) ? minDiff : 50
  }, [chainData])
  ```
  ```ts
  // TemplateDialog.tsx:88-91 — each leg's target strike is computed
  // independently from this single global step, then independently
  // snapped to the nearest strike actually present in the chain:
  const target = atmStrike + leg.strikeOffset * strikeStep
  const override = strikeOverrides[idx]
  const resolvedStrike = override ?? nearestStrike(target, strikes) ?? target
  ```
  `strategyTemplates.ts`'s `long_iron_condor` recipe is symmetric by construction — `strikeOffset: -4, -2, +2, +4` — but the offsets are only ever multiplied by one globally-detected `strikeStep` and then independently nearest-snapped per leg.
- **Failure scenario**: Indian index option chains routinely do **not** have a uniform strike interval across their full listed range — a NIFTY/BANKNIFTY chain frequently shows a tighter step near ATM (e.g. 50) that widens a few strikes out (100, then 100+ again near the tails of a 20-strikes-each-side fetch). `strikeStep` picks up whatever the *tightest* gap anywhere in that fetched window is (typically the ATM-adjacent gap), then every leg's target is computed as `atmStrike ± n × (that tightest step)`. For a leg whose target lands in a *coarser* part of the chain, `nearestStrike` snaps it to whatever's actually listed there — which is not guaranteed to be equidistant from ATM the way the recipe intends, and is not guaranteed to snap the same way on the call side as the put side. The put wing and call wing of the *same* Long Iron Condor can end up different widths even though the template's offsets (`-4/-2` vs `+2/+4`) are symmetric. This is consistent with the referenced screenshot: the put-side rise (long put → short put) renders as one clean straight segment, while the call-side fall (short call → long call) shows an extra intermediate kink — exactly what you'd see if the snapped call strikes ended up more closely spaced than the put strikes the template intended to mirror.
- **Fix direction**: Detect `strikeStep` locally — around each leg's own target strike (or at minimum around ATM ± the largest offset actually used by the template) — rather than as one global minimum over the whole fetched chain; alternatively, resolve all of a template's legs against a shared, verified-uniform sub-list of strikes (or surface a warning in `TemplateDialog` when two legs of a symmetric template snap to unequal distances from ATM).

### [PB-H5] Profit/loss shading is computed at the wrong resolution and visibly disagrees with the curve's own zero-crossing

- **Location**: `frontend/src/components/strategy-builder/PayoffChart.tsx:76-78`
- **Evidence**:
  ```ts
  // PayoffChart.tsx:76-78
  // Split expiry into profit/loss fills via trace thresholding.
  const profitFill = samples.map((s) => (s.expiry >= 0 ? s.expiry : 0))
  const lossFill = samples.map((s) => (s.expiry < 0 ? s.expiry : 0))
  ```
  This assigns each *sample* wholesale to either the profit or loss series based on that sample's own sign — a hard, per-index switch. The "At Expiry" line itself (`ysExpiry`, drawn as a continuous `mode: 'lines'` trace) passes through the *true*, sub-sample zero-crossing (the same crossing `computePayoff`'s `breakevens` correctly finds via linear interpolation, `strategyMath.ts:344-352`). The fill polygons' corner, by contrast, sits at whichever sample index happens to be closest to zero — generally a few underlying-price-units away from where the line itself actually crosses zero.
- **Failure scenario**: At every breakeven, the green (profit) and red (loss) fill regions meet at a slightly different x-position than where the orange "At Expiry" line crosses the zero axis. The visual result is a small triangular sliver of the "wrong" color sitting right at the crossing — e.g. a thin wedge of red bleeding just above the zero line into the green zone, or vice versa. This is exactly the artifact visible in the referenced `NIFTY — 04AUG26` screenshot immediately around the left breakeven (~23.8k–23.9k): a small pink triangular wedge sits inside/against the green profit zone right where the curve crosses zero, rather than the fill boundary meeting the curve cleanly at that single point.
- **Fix direction**: Compute the fill boundary from the same interpolated zero-crossing `computePayoff` already produces (insert the exact crossing x/0 point into each fill series at the crossing index) instead of thresholding per-sample; or increase sample density enough that the discrepancy becomes sub-pixel (band-aid — doesn't fix the underlying mismatch, just shrinks it).

---

## Medium Findings

### [PB-M1] Max Profit / Max Loss is exact only for single-expiry strategies; the code claims "true mathematical maximum" unconditionally

- **Location**: `frontend/src/lib/strategyMath.ts:355-405` (`computePayoff`'s extrema search), comment at `355-373`
- **Evidence**:
  ```ts
  // strategyMath.ts:355-373
  // ── True (mathematical) max profit / max loss ──
  // ...
  //   1. Enumerate candidate underlying prices where the piecewise-linear
  //      expiry payoff can have an extremum — every strike (kinks) plus 0
  //      ... plus a point well past the highest strike ...
  ```
  This assumes the "at expiry" payoff is **piecewise-linear** in spot. That's only true when every active leg is evaluated at zero remaining time. `computePayoff` is called with `daysAtExpiry = nearestDays` — the *nearest* active leg's DTE (`StrategyBuilder.tsx:475-478`, explicitly to support calendar/diagonal spreads per its own comment: *"far-dated legs (calendar / diagonal) keep their remaining time value"*). For any leg whose own expiry is later than the nearest leg's, `legPnlAt` (`strategyMath.ts:161-171`) still has `tLeg > 0` at that evaluation point and prices it via smooth Black-Scholes rather than intrinsic — so the combined curve is **not** piecewise-linear for calendar/diagonal strategies, and its true extremum need not sit at a strike.
- **Failure scenario**: A calendar call spread (sell near-month, buy far-month, same strike) evaluated at the near leg's expiry: the near leg is a clean kink at its strike, but the far leg is still a smooth BS curve there. The true maximum of the combined curve sits near — but not exactly at — the shared strike; `strikeSet` (`376-391`) only evaluates *at* the strike itself (plus 0 and 2× the max strike), so the reported Max Profit is a close approximation, not the exact value the code's own comment promises. For a *diagonal* (different strikes across expiries) the discrepancy is larger since there's no shared kink to anchor near.
- **Fix direction**: For any leg set spanning more than one distinct expiry, either (a) don't claim exactness — compute max/min from the dense sample array instead (accepting the ±10%-window caveat from PB-H2) and label it "approximate", or (b) do a local refinement (e.g. golden-section search) around each strike using the smooth BS component for the far leg(s).

### [PB-M2] Greeks/IV refresh effect keyed on leg count, not leg identity/state

- **Location**: `frontend/src/pages/StrategyBuilder.tsx:583` (effect dependency array)
- **Evidence**:
  ```ts
  }, [apiKey, legs.length, selectedExchange, selectedUnderlying, atmStrike])
  ```
- **Failure scenario**: Re-activating a leg that was toggled inactive earlier in the session (`toggleLeg`, `StrategyBuilder.tsx:888-890`) changes `active` but not `legs.length` — no refetch is triggered, so a leg that's been inactive (and therefore possibly stale) for a while resumes contributing to the payoff with whatever Greeks/IV it last had, however old. Same applies to any bulk edit that swaps one leg for a different one at the same count (e.g. `toggleAll`).
- **Fix direction**: Depend on a derived key such as `legs.filter(l => l.active).map(l => l.symbol).join(',')` so any change in the *set* of symbols actually contributing to the payoff triggers a refresh, not just a change in array length.

### [PB-M3] Payoff tab and Strategy Chart tab disagree on whether futures legs count

- **Location**: `services/strategy_chart_service.py:139-142` (`_normalize_leg`) vs. `frontend/src/lib/strategyMath.ts:156-158` (`legPnlAt`) / `275-298` (`asymptoticSlopes`)
- **Evidence**:
  ```python
  # strategy_chart_service.py:139-142
  segment = (leg.get("segment") or "OPTION").upper()
  # Futures contribute a price level rather than a premium — exclude.
  if segment != "OPTION":
      return None
  ```
  ```ts
  // strategyMath.ts:156-158 — Payoff tab DOES include futures legs
  if (leg.segment === 'FUTURE') {
    return sign * (underlying - leg.price) * qty
  }
  ```
- **Failure scenario**: A covered-call-style or synthetic-long combo (long future + short call) shows the futures leg's contribution in the Payoff tab's curve and Max Profit/Loss, but the adjacent Strategy Chart tab's combined-premium series silently drops the futures leg entirely — the same saved strategy renders two different economic pictures depending on which tab the user is looking at, with no label clarifying the Strategy Chart tab is options-premium-only.
- **Fix direction**: Either extend the Strategy Chart series to include a futures price-level component, or make the tab's subtitle/legend explicit that it is an options-premium-only view so it isn't read as a second payoff chart.

### [PB-M4] The payoff curve can go stale across wall-clock time with no re-render trigger

- **Location**: `frontend/src/lib/strategyMath.ts:503-511` (`nearestLegDays`), `frontend/src/pages/StrategyBuilder.tsx:475-478` (`nearestDays` memo)
- **Evidence**:
  ```ts
  // strategyMath.ts:503-511
  export function nearestLegDays(legs: StrategyLeg[], now: Date = new Date()): number { ... }
  ```
  ```ts
  // StrategyBuilder.tsx:475-478
  const nearestDays = useMemo(() => {
    if (legs.length === 0) return rawDays ?? 0
    return nearestLegDays(legs)     // `now` defaults fresh each CALL, but the
  }, [legs, rawDays])                // memo itself only re-runs on legs/rawDays change
  ```
- **Failure scenario**: A user builds a strategy and leaves the tab open (a realistic pattern — traders watch a payoff chart through a session). `nearestDays`, and therefore the whole "At Expiry"/"T+0" time-to-expiry basis, is frozen at whatever it was computed at on the last unrelated re-render (leg add/remove, spot change, etc.) — it does not tick down over the session the way a live DTE display should, however minor the drift within a single day.
- **Fix direction**: Not necessarily worth a timer re-render every second, but at minimum recompute on a coarse interval (e.g. once a minute) or whenever `spotPrice` updates (which already happens frequently via the live feed) so DTE-derived values don't visibly lag reality.

### [PB-M5] 240 uniformly-spaced samples never land exactly on a strike — every kink renders as a subtly beveled double-segment instead of one sharp corner

- **Location**: `frontend/src/lib/strategyMath.ts:322-323, 330-334` (`computePayoff` sampling loop)
- **Evidence**:
  ```ts
  // strategyMath.ts:322-323, 330-334
  const [lo, hi] = priceRange
  const step = (hi - lo) / steps          // steps defaults to 240
  ...
  for (let i = 0; i <= steps; i++) {
    const x = lo + i * step               // uniform grid — never explicitly
    ...                                    // includes a leg's own `strike`
  }
  ```
  For a ±10% window around a ~24,000 NIFTY spot, `step ≈ (24000 × 0.2) / 240 ≈ 20` points per sample. The true "at expiry" payoff has an exact, sharp corner at every strike (`legPnlAt`'s `intrinsic()` switch, `strategyMath.ts:126-128`), but the chart only ever draws straight lines *between* samples — a sharp corner is reproduced faithfully only when a sample happens to land exactly on the strike. Since strikes are not, in general, an exact multiple of `step` away from `lo`, most kinks fall *between* two samples and get rendered as a shallow partial-slope segment leading into the real, steeper segment — a visibly "beveled" corner instead of a crisp one.
- **Failure scenario**: This is subtle at the default zoomed-out view (the bevel is a few points wide against a ±10% span) but becomes obvious the moment a user zooms in near a strike — exactly what the referenced Iron Condor screenshot shows on the call side: the flat max-profit plateau doesn't run cleanly into one straight decline to the max-loss floor: there's a shallow partial drop first (the "bevel"), then the real, steeper decline. The put side of the same chart happens to look cleaner only because its nearby samples land closer to that particular strike — the artifact is present at every kink, just more or less visible depending on where the uniform grid happens to fall.
- **Fix direction**: Explicitly inject each active leg's strike (and the two adjacent grid points) as extra sample x-values (a leg's kink is always at its own strike, regardless of the uniform grid), so every genuine kink in the payoff has a sample sitting exactly on it.

---

## Low / Minor Findings

### [PB-L1] `Math.sign()`-based zero-crossing detection mishandles exact-zero samples

- **Location**: `frontend/src/lib/strategyMath.ts:336-339`
- **Evidence**:
  ```ts
  if (prevExpiry !== null && Math.sign(prevExpiry) !== Math.sign(atExpiry)) {
    zeroCrossings.push(i - 1)
  }
  ```
  `Math.sign(0) === 0`, which differs from both `1` and `-1` — a sample landing exactly on zero registers as a crossing against its non-zero neighbor on *both* sides, and the paired interpolation at `344-352` can produce a duplicate or near-duplicate breakeven right next to the genuine one for strategies whose payoff happens to touch exactly zero at a sampled grid point (e.g. certain box/synthetic combinations, or a leg set that nets to a flat-zero region).
- **Fix direction**: Treat `0` as same-sign-as-previous (or explicitly skip flat-zero runs) rather than comparing raw `Math.sign()` output.

### [PB-L2] Probability-of-Profit tail extrapolation inherits the ±10% window's blind spot

- **Location**: `frontend/src/lib/strategyMath.ts:446-460` (`probabilityOfProfit`)
- **Evidence**:
  ```ts
  // Tail beyond last sample: assume same sign as last point.
  const last = samples[samples.length - 1]
  if (last.expiry > 0) prob += 1 - cdf(last.underlying)
  ```
- **Failure scenario**: Same root cause as PB-H2 — if the true breakeven sits beyond the ±10% window (common for wide strangles/condors), the entire tail probability mass gets attributed based on the sign of the payoff at the arbitrary ±10% boundary rather than at the true crossing, systematically biasing the displayed Probability-of-Profit.
- **Fix direction**: Resolves automatically once the sampling range (PB-H2) is widened to actually contain the true breakevens for the IV/DTE in play.

### [PB-L3] Frontend and backend use different near-expiry epsilon floors

- **Location**: `frontend/src/lib/strategyMath.ts:169` (`tLeg <= 1e-6` → intrinsic), `frontend/src/lib/strategyMath.ts:110` (`bsPrice` floors `t` at `1e-8`), vs. `services/option_greeks_service.py` (`calculate_time_to_expiry` floors at `1e-4` years per the backend Black-76 path)
- **Evidence**: Cited directly in the code-map research for this audit; the frontend's own module docstring (`strategyMath.ts:1-8`) explicitly says its role is to "re-price the same legs" that the backend's Black-76 Greeks service already priced — implying the two are meant to be reconcilable, but they don't share a near-expiry cutoff convention.
- **Failure scenario**: In the last few minutes before expiry, the frontend's T+0 simulator and the backend's live Greeks can flip between intrinsic and time-value pricing at different thresholds, producing a visible (if short-lived) divergence between the displayed Greeks and the payoff curve's own repricing on expiry day.
- **Fix direction**: Share one epsilon constant (or pass the backend's floor value down) so both paths agree on when "time value" stops mattering.

---

## Template-by-Template Exposure Survey

The Iron Condor screenshot triggered PB-H4/H5/M5, but those root causes live in shared code — the question is which of the other 37 templates in `strategyTemplates.ts` are exposed, and how badly. Two different things are true at once:

- **PB-H2, PB-H3, PB-H5, PB-M5 are universal.** They live entirely in `computePayoff`/`PayoffChart` and don't look at which template built the legs. Every template — and every hand-built custom strategy — hits the same fixed ±10% window, the same possibly-out-of-range σ bands, the same fill/crossing mismatch, and the same beveled-kink sampling artifact. There is no template that avoids these; severity just scales with how far the strategy's true breakevens/kinks sit from spot and from the 240-sample grid.
- **PB-H4 (and a related amplification effect below) is template-shaped.** Its impact depends on how many legs a template puts on each side, whether those legs are supposed to mirror each other in width, and how large the `strikeOffset` values are. That part *does* vary a lot template-to-template, and is worth enumerating.

### [PB-H6] Large `strikeOffset` values amplify PB-H4 into a wrong risk profile, not just a cosmetic asymmetry

- **Location**: same root cause as PB-H4 (`StrategyBuilder.tsx:454-463`, `TemplateDialog.tsx:88-91`)
- **Why this is a distinct, worse failure mode**: `strikeStep` is a **global minimum** over the whole fetched chain (`minDiff` in the loop at `454-463`) — by construction it can never be *larger* than the true local spacing anywhere in the chain, only smaller or equal. Every leg's target is `atmStrike + strikeOffset × strikeStep`. So for any leg whose true intended spacing is wider than the chain's tightest gap, the computed target is **systematically pulled in toward ATM** — never pushed further out. The error is proportional to `strikeOffset`, so it is small for a 2-step vertical spread and large for a template using offsets of 10-15.
- **Failure scenario**: `batman_strategy` uses offsets `±10` and `±15`; `double_fly` goes out to `±12`; `double_condor` uses eight legs spanning `-5` to `+5`. If the chain's tightest gap (say 50, typical near ATM) is being applied to a leg whose real local spacing is double that (100, typical a few strikes further out — common on NIFTY/BANKNIFTY), a `strikeOffset: 15` leg resolves roughly **half as far from ATM as the template intends** — not a subtle rendering bevel, but a materially different (much narrower, much less far-OTM) strategy than the one the user picked from the template grid. For a "Batman" or "Double Fly" — templates explicitly built to place their loss-generating short legs far from ATM — this directly understates real risk: the wings the user thinks are far OTM safety margins are actually much closer than displayed.
- **Fix direction**: Same as PB-H4's — resolve `strikeStep` locally per offset magnitude (or walk outward from ATM by the requested number of *actual listed strikes* rather than a price distance derived from one global step) so large offsets are not disproportionately compressed toward ATM.

### Exposure table

| Template(s) | Max \|offset\| | H4/H6 exposure | Why |
| --- | --- | --- | --- |
| Long Call, Short Put, Short Call, Long Put | 0 | None | Single leg — no other strike to be asymmetric against. |
| Long Straddle, Short Straddle, Long/Short Synthetic | 0 | None | Both legs share one strike (ATM) — nothing to space. |
| Bull/Bear Call Spread, Bull/Bear Put Spread, Call/Put Ratio (Back) Spread | 2 | Low | Single-sided, single width — only the *absolute* width can be mis-estimated (leg resolves closer to ATM than the recipe intends); no left/right mirror to visibly desync. |
| Long/Short Strangle, Range Forward, Risk Reversal | 2 | Low-Medium | Two independent OTM legs (put + call) — cosmetic symmetry only; a strangle/strangle-like V-shape stays structurally valid even if the two sides end up unevenly spaced from ATM. |
| Jade Lizard, Reverse Jade Lizard | 4 | Medium | One single-strike side + one two-strike (spread) side — the spread side's width can be mis-estimated the same way as a vertical spread, but there's no cross-side mirror requirement. |
| **Bullish/Bearish Butterfly, Call/Put Butterfly** | 4 | **High** | Two wings around a body **must resolve to equal widths** for the classic single-peak triangle; PB-H4 does not guarantee this — the same failure class as the audited Iron Condor, arguably more visible since a butterfly's max profit is a single point, not a plateau. |
| **Bullish/Bearish Condor** | 4 | **High** | Same equal-wing-width requirement as a butterfly, applied to a flat-topped (not pointed) profit zone — same exposure as the audited Iron Condor. |
| **Long/Short Iron Fly** | 2 | **High** | This *is* the audited Iron Condor's failure mode with a straddle body instead of a strangle body — wings must be equal on both sides of the ATM straddle. |
| **Long/Short Iron Condor** | 4 | **High (confirmed live)** | The template audited via the referenced screenshot. |
| **Double Condor** | 5 | **Very High** | Two independent condors (8 legs) — four separate wing-width constraints that all need to hold simultaneously; the most constraint-dense template in the set even though its offsets aren't the largest. |
| **Batman Strategy** | 15 | **Very High** | Largest offsets in the template set — most exposed to the PB-H6 "pulled toward ATM" amplification; also the closest to the ±20-strike default chain-fetch boundary (`option-chain.ts:23`), so on an underlying/expiry where the broker returns fewer than 20 listed strikes on a side, the far (±15) legs are also at risk of clamping to whatever the edge of the fetched list happens to be. |
| **Double Fly** | 12 | **Very High** | Two independent iron-flies (8 legs) spanning `-12` to `+12` — combines the Double Condor's multi-constraint exposure with Batman's large-offset exposure. |
| Call Calendar, Put Calendar | 0 (same strike, 2 expiries) | None for H4/H6 | Both legs share one strike — no width to mis-estimate. **But see PB-M1**: this is exactly the calendar-spread case where the "at expiry" curve's claimed exactness already breaks down, independent of strikes. |
| Diagonal Calendar | 2 (2 expiries) | Low for H4/H6 | Single width, no mirror — same low exposure as a vertical spread. **Also hits PB-M1**, and worse than the same-strike calendars per that finding's own analysis (no shared kink to anchor the approximation near). |

### Reading this table against PB-H4/H6

The pattern is consistent: **any template with two or more strikes on the *same* option side that are supposed to define a symmetric shape (a wing, a body, a plateau) is exposed**, and the exposure scales with how many such constraints exist (Double Condor, Double Fly) and how large the offsets are (Batman, Double Fly). Single-width, single-sided, or same-strike templates are largely insulated from H4/H6 specifically — they still inherit the *universal* findings (H2/H3/H5/M5) like everything else, just not this additional template-shaped one.

---

## Suggested fix order

1. **PB-H1** (stale IV on leg edit) — highest real-money impact, smallest fix (reset `iv` on edit + fix the effect dependency).
2. **PB-H4 + PB-H6** (`strikeStep` global-minimum detection, and its amplification at large offsets) — directly explains the visible Iron Condor asymmetry; fix is localized to one `useMemo` plus how `TemplateDialog` resolves per-leg targets. Per the Template-by-Template Exposure Survey, this affects every butterfly/condor/iron-fly template, and hits Batman Strategy / Double Fly / Double Condor hardest (large offsets, many legs) — prioritize verifying the fix against those three, not just Iron Condor.
3. **PB-H5 + PB-M5** together — both are "the chart doesn't sample/fill exactly at the true kink/crossing" issues; injecting each leg's strike (and the interpolated breakeven) as explicit sample points fixes the beveled-corner artifact and lets the fill boundary be computed from the same exact crossing, in one pass.
4. **PB-H2 + PB-H3 + PB-L2** together — all three are downstream of the same fixed ±10% window; widening it to a volatility-scaled range fixes all three in one change.
5. **PB-M2** — small dependency-array fix, same shape as PB-H1's second cause.
6. **PB-M1** — either relabel as approximate or add local refinement; lower urgency since the strike-anchored estimate is usually close.
7. **PB-M3, PB-M4, PB-L1, PB-L3** — polish-tier, address opportunistically.

---

## Codex Cross-Check & Validation

A second review pass ("Codex") was run against this audit and returned back the document essentially verbatim — same 14 findings (H1-H6, M1-M5, L1-L3), same file/line citations, same severity counts, same fix order. Rather than rubber-stamp a match, this section re-derives each citation independently against the current source tree (all files are unmodified since the original pass — no drift to account for) and calls out the couple of places where the write-up is stronger or weaker than it reads.

### What re-checked clean

Every code citation in H1-H5, M1-M5, and L1-L3 was re-read against the live files and matches exactly as quoted — function boundaries, line numbers, and the surrounding logic all line up (`EditLegDialog.tsx:163-177`, `StrategyBuilder.tsx:454-463/475-478/567-574/583/858/899-932`, `strategyMath.ts:110/126-128/169/275-298/301-420/429-462/491-517`, `PayoffChart.tsx:76-84`, `TemplateDialog.tsx:46-58/84-114`, `services/strategy_chart_service.py:139-142`). No citation pointed at the wrong line or misquoted the surrounding code. The mechanisms behind H1, H2, H3, M1, M2, M3, M4, L1, L2, L3 are all objectively true of the code as written, independent of any screenshot or market-data assumption — these don't need the Iron Condor render to be correct, they follow from reading the math.

### Where the write-up overstates certainty

- **H4's "confirmed live" label is an inference, not a certainty.** The screenshot shows *an* asymmetry (clean single-segment rise vs. a two-segment call-side shoulder), and H4 (per-leg independent nearest-strike snapping against a globally-detected step) is a plausible, code-confirmed mechanism that *would* produce exactly that shape. But M5 (240 uniform samples never landing on a strike, producing its own beveled-corner artifact) would produce a visually similar shoulder on its own, from a *single, symmetric* Iron Condor with perfectly-spaced strikes — no chain irregularity required. Without the exact leg strikes/lot sizes that produced that specific render, the screenshot cannot definitively attribute the shoulder to H4 rather than M5 (or both stacking). **Correction**: downgrade the exposure table's "High (confirmed live)" for Long/Short Iron Condor to "High (screenshot consistent with, not conclusively isolated from PB-M5)" — the code-level bug is real and confirmed either way, but the screenshot is corroborating evidence for *a* rendering-fidelity problem in that render, not proof that H4 specifically (versus M5) is what's on screen.
- **H6's premise — that live NIFTY/BANKNIFTY chains actually have non-uniform strike spacing within a ±20-strike window — is asserted, not verified in this review.** The code mechanism (`strikeStep` as a global minimum, which by construction can only under-estimate local spacing, never over-estimate it) is confirmed by reading `StrategyBuilder.tsx:454-463`; that part is certain. Whether it fires in practice depends on live broker chain data this review did not pull (no `/optionchain` response was captured and inspected for actual strike gaps). **Net effect on the finding**: the bug is real and latent regardless — a genuinely uniform chain makes it inert (global min == local spacing everywhere, so no error), but the moment any part of the fetched window widens, the bug fires deterministically. Treat H6's "Batman/Double Fly wings land ~half as far out as intended" figure as an illustrative worked example (assuming a 50→100 step change), not a measured number.
- **Minor citation imprecision**: H6's "closest to the ±20-strike default chain-fetch boundary (`option-chain.ts:23`)" cites the *default* (`strikeCount ?? 20`), but `StrategyBuilder.tsx:341` always calls `optionChainApi.getOptionChain(apiKey, selectedUnderlying, exchange, expiryCode, 20)` — a literal `20`, so the `?? 20` fallback at `option-chain.ts:23` is never actually exercised from this page. The conclusion (±20 strikes fetched) is still correct; the citation should point at `StrategyBuilder.tsx:341`, not the unused default.

### Where the write-up could be read as too conservative

- **PB-H5's mechanism is stronger than "a small triangular sliver" implies in the steep parts of a curve.** Because `profitFill`/`lossFill` clamp to `0` per-sample rather than at the true crossing, the size of the visual mismatch scales with *slope × sample spacing* at the crossing, not a fixed small amount. For a steep wing (an Iron Condor's rise/fall segments, easily ±30-40 P&L per underlying point) against the default ~20-point sample spacing, the value can jump several hundred rupees between the two samples straddling the true crossing — large enough to be clearly visible, not merely a hairline. Worth noting this scales with how steep the strategy's kinks are (short-dated, high-gamma structures show it more than long-dated ones).
- **The Template-by-Template Exposure Survey's "None" bucket (single-leg / same-strike templates) is correctly scoped to H4/H6 only** — it should not be read as "these templates have no issues." Every template, including the "None" ones, still fully inherits H2/H3/H5/M5 (the universal chart/window findings), and Call/Put Calendar are fully exposed to M1 despite being "None" for H4/H6. The table already says this in prose but it is easy to skim past; flagging it here so the fix-order doesn't get read as "only condors/flies/butterflies need attention."

### Bottom line

The audit's code-level findings hold up under a second, independent re-read of every citation — nothing was found to be flat-out wrong. The one thing worth tightening before treating this as a spec for fixes is the **evidentiary weight placed on the single screenshot**: it correctly proves *something* is off in Iron Condor's render (H3's missing σ labels are unambiguous; a shoulder/shading artifact of some kind is clearly visible), but it cannot, by itself, isolate H4 from M5 as the specific cause of the shoulder shape without the underlying leg/strike data for that render. Both are real bugs either way, so this doesn't change what needs fixing — it changes how the fix should be verified (fix both H4/H6 and H5/M5, then re-render the same strategy to confirm the shoulder and shading artifacts are both gone, rather than assuming a fix to one alone will fully clean up that screenshot).

---

## Consolidated Issues To Be Fixed

A flat, ready-to-track checklist of every finding, independent of the narrative fix-order above:

- [ ] **PB-H1** — Reset `leg.iv` to `0` (and drop cached Greeks) whenever `strike`/`optionType`/`expiry` changes in `EditLegDialog.tsx:163-177`; change the refresh effect at `StrategyBuilder.tsx:583` to key off active-leg symbols, not `legs.length`.
- [ ] **PB-H2** — Replace the fixed `spotPrice * [0.9, 1.1]` window (`StrategyBuilder.tsx:858`) with a volatility-scaled range (e.g. `spot ± max(10%, 3σ)`), or compute breakevens structurally (strike-based) instead of by scanning the finite sample array.
- [ ] **PB-H3** — Clamp σ-band shapes/labels (`PayoffChart.tsx:80-84`) to the curve's actual sampled `[lo, hi]` domain; resolves automatically once H2 ties the window to the same σ measure.
- [ ] **PB-H4** — Detect `strikeStep` locally per leg/offset (or resolve against a verified-uniform sub-list of strikes) instead of one global minimum over the whole fetched chain (`StrategyBuilder.tsx:454-463`, `TemplateDialog.tsx:88-91`).
- [ ] **PB-H5** — Compute the profit/loss fill boundary from the same interpolated zero-crossing `computePayoff` already produces (`PayoffChart.tsx:76-78`), instead of a per-sample sign threshold.
- [ ] **PB-H6** — Same fix as H4; specifically re-verify against Batman Strategy, Double Fly, and Double Condor (largest offsets, most legs) once fixed, not just Iron Condor.
- [ ] **PB-M1** — Either relabel Max Profit/Loss as approximate for multi-expiry (calendar/diagonal) leg sets, or add a local refinement search (e.g. golden-section) around each strike using the smooth BS component for the far leg (`strategyMath.ts:355-405`).
- [ ] **PB-M2** — Key the Greeks/IV refresh effect (`StrategyBuilder.tsx:583`) off a derived active-symbol fingerprint instead of `legs.length`, so reactivating/swapping a leg at the same count still refetches.
- [ ] **PB-M3** — Either include a futures price-level component in the Strategy Chart's combined series (`services/strategy_chart_service.py:139-142`), or explicitly label that tab as options-premium-only.
- [ ] **PB-M4** — Recompute `nearestDays`/DTE-derived values on a coarse interval or on `spotPrice` updates (`StrategyBuilder.tsx:475-478`), not only when legs change.
- [ ] **PB-M5** — Inject each active leg's strike (plus adjacent grid points) as explicit sample x-values in `computePayoff` (`strategyMath.ts:322-323, 330-334`) so every true kink has a sample sitting exactly on it.
- [ ] **PB-L1** — Treat `Math.sign(0)` as same-sign-as-previous (or skip flat-zero runs) in the zero-crossing scan (`strategyMath.ts:336-339`).
- [ ] **PB-L2** — Resolves automatically once PB-H2 widens the sampling range to actually contain true breakevens (`strategyMath.ts:446-460`).
- [ ] **PB-L3** — Share one near-expiry epsilon constant between the frontend's `bsPrice`/`legPnlAt` floors and the backend's `calculate_time_to_expiry` floor, instead of three independent cutoffs (`strategyMath.ts:110,169` vs. `services/option_greeks_service.py`).

**Verification note for whoever picks this up**: after fixing H4/H6 and H5/M5, re-render the exact Iron Condor configuration from the audited screenshot (same underlying, expiry, strikes) and confirm both the shoulder-kink and the fill/crossing sliver are gone — per the Codex Cross-Check above, the screenshot alone doesn't prove which of the two fixes was responsible, so both need to be in place before calling that specific artifact resolved.
