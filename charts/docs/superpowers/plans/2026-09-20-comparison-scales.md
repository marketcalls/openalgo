# Comparison scales and common-start implementation plan

Continue the authorized production workspace spec, F7. The preceding goal turn
was progress: reference ownership was committed as `a4a5813`. Charts 2.4.5 publishes
before the remaining consumer work, as explicitly requested on 2026-09-20.

## Design decisions

Keep raw instrument bars for API readings and exports. Add keyed hidden scales
instead of normalizing stored prices or placing every comparison on a new pane.
Normalizing bars would make host readings and updates use incompatible units;
separate panes would not provide the requested shared comparison plot.

Extend PriceScaleId with `overlay:${string}`. Existing right, left and empty ids
keep their meaning. Keyed scales are independent, hidden, included in pane-wide
scale operations, and released when their last series leaves. Comparison handles
each own a scale; the first handle retains the existing empty-overlay/left-axis
placement when those scales are free. Never take a scale occupied by another
source.

Keep the existing first-visible baseline default. Add an explicit common-start
policy for hosts needing a shared timestamp. It uses the first visible timestamp
with positive finite closes on the primary and every visible comparison. Missing
prints remain gaps. Without a shared timestamp the comparisons draw no values;
the controller reports that no common baseline is available. The reference host
opts into this policy and displays that state. Percentage and indexed-to-100
coordinates agree for equal relative moves, including panning and hiding sources.

Re-alignment must observe primary data changes, including same-length history
replacement and replay truncation. Comparisons must never preserve future axis
timestamps or disclose the completed close of a forming replay candle. Teardown
must release controller subscriptions and tolerate already-destroyed charts.

## Steps and evidence

1. Add independent hidden-scale tests through the real Chart API. Observe the
   failing coordinates/ownership/cleanup assertions, then implement keyed scales.
2. Split comparison pane mode ownership from per-handle scales. Test two or more
   differently priced instruments, occupied volume and left scales, removal in
   either order, mode changes, visibility and scale cleanup.
3. Add the explicit common-start policy and missing-calendar tests. Assert equal
   pixels from a common timestamp, gaps with no common start, and panning recovery.
4. Test same-length source replacement, live append/replacement, replay prefixes
   and forming bars, replay stop and destruction. Fix the underlying invalidation
   and replay boundary rather than asking callers to realign after every tick.
5. Update public type exports, API/skill docs, the comparison guide and reference
   host. Run affected tests, full engine/demo checks, build/declarations/size/shake
   and cross-browser comparison checks; inspect rendered evidence. Record measured
   package impact for the final release fact update. Commit locally after checks.

The controller and pane changes remain headless. Existing host APIs and default
standalone behaviour retain their meaning. Full F7 acceptance, broader chart
scope, final review and publication remain required after these steps; consumer
implementation and connected-broker deployment checks follow chart publication.

## Validated checkpoint

Steps 1-5 are implemented. Each comparison owns a scale; common-start selection
is explicit and the legacy first-visible default remains. The reference opts
into common mode. Missing overlap suppresses both series values and host legend
prices. `barAt(time)` returns only an eligible aligned reading. Primary history
replacement works even when another series holds the shared axis length fixed.
Live append/replacement, forming replay bars, sources added during replay,
replay stop, inversion, manual ranges and chart-first destruction are covered.

The final screenshot review found a stale host legend after suppression. A
browser regression failed in comparison-readout-red-browser.log; refreshing each
legend after the controller's autoscale hook fixed it. The hook retains the
selected readout timestamp, uses the aligned reading, and relies on PaneLegend's
value equality check to avoid a repaint loop. It detaches with its legend.

Validation artifacts are local under artifacts/candidate:

- comparison-verify.log: lint, types, 5531 engine tests in 230 files, build,
  278 example tests in 23 files, eight declaration checks, size and shake pass.
- comparison-final-demo.log: all 278 example tests after the legend correction.
- comparison-final-browser.log: 73 reference cases across Chromium, Firefox and
  WebKit pass. Common-start and missing-overlap screenshots were inspected.
- comparison-lifecycle-unit.log: 61 focused scale/comparison/replay tests pass.
- comparison-api.log: API generation succeeds without warnings.
- comparison-skills.log: all 917 skill coverage entries pass.
- comparison-website.log: static website build succeeds. The existing workspace
  root inference warning remains; the browser runner retains its colour warning.

Measured bundle impact: base 84.70 to 86.05 KiB, base plus trade 93.66 KiB,
terminal 197.90 KiB and all tiers 236.64 KiB. These include independent comparison
scales, shared-start fitting, replay boundaries and eligible readouts. Budgets
are now 86.25, 94, 198.25 and 237 KiB respectively. Chart-only imports grow from
51.89 to 51.96 KiB for named hidden scales; their budget is 52.10 KiB. A new
shake assertion ensures the optional comparison controller is absent. Final
release facts must be measured again after the remaining changes and version
bump, then updated across the eight documentation surfaces.

Resource review: named scales are released after their last series; repeated
add/remove does not accumulate them. Chart destruction unsubscribes the controller
and clears its source caches. Replay boundaries use weak chart keys. No new timer
or window listener was added. This is not a sustained endurance or live-feed test.

Broader chart scope, reference replay/fullscreen ownership, shared replay,
remaining workspace restoration and production gates, final branch review and
publication remain open. The consumer worktree and original OI edits are unchanged.
No package was published and the score remains frozen.
