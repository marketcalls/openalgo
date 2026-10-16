# Chart correctness validation and fixes

Source: https://github.com/marketcalls/openalgo/issues/2077.
The user added this issue to the existing production and 2.4.5 release scope,
explicitly requiring validation before fixes. Use systematic debugging, observed
failing regressions and the existing isolated chart/consumer checkouts. The named
grid UI, all earlier feature requirements and the final release remain required.

## Reported behavior to validate

1. Index charts display volume although the underlying index has no traded volume.
2. Volume values are missing from the legend. Check current positive, zero and
   unavailable volume before deciding whether the current readout already satisfies
   part of this report.
3. Live updates replace the hovered candle's OHLC/study readouts. Preserve the
   hovered time; off-chart and future-space positions may use the latest candle.
4. Mouse plot panning disables automatic price fitting. Compare plot, touchpad,
   time-axis and price-axis gestures before choosing the narrow behavior change.
5. Synthetic option combinations lose volume. Validate historical and live paths,
   then define and document a consistent leg-volume aggregation rule.
6. Linked crosshairs move but other charts' readouts do not follow their bars.
   Check different intervals, missing times, clear events and feedback prevention.

## Work sequence

- [x] Trace each report through the current host and engine, and classify it as
  reproduced, partially addressed or not reproduced using concrete evidence.
- [x] Add meaningful failing tests and browser assertions before each correction.
  Use synthetic input for deterministic live updates and label it accurately.
- [x] Correct each confirmed cause, preserving shared API contracts, trading
  authority, per-pane ownership and the default timezone. Never add comparison
  product names to source, documentation, comments or commits.
- [x] Test the built engine and actual consumer in Chromium, Firefox and WebKit;
  inspect pixels. Test connected history where useful without sending orders.
- [x] Run the affected suites and full release gates at the appropriate boundaries,
  document measured results, commit locally, and return to the remaining workspace
  and production requirements before the authorized final release.

## Evidence and boundaries

Library `deb6de3` and consumer `9860b3b69` implement these corrections. The initial
browser probe reproduced all six areas, with the volume legend report partially
addressed already: positive values existed, but zero values disappeared. The
linked regression uses overlapping history; an initial daily/intraday fixture
had no corresponding bar and was corrected before claiming reproduction.

The host hides built-in index volume and its average without losing the user's
preference, renders zero volume, retains the selected timestamp across ticks and
history replacement, and defaults mouse/pen plot panning to horizontal. Direct
price-axis adjustment remains available and an explicitly saved two-axis pan
preference remains honored. Replay readouts use only the displayed prefix.

The engine retains selected study readouts through recalculation and history
prepends. Linked markers update the follower's own OHLC/study values, never emit
pointer movement or move a replay picker, and clear on unlink/missing time.
Expression evaluation defaults to absent volume; both adapters explicitly opt
into the sum of each distinct expression symbol's reported activity. Price signs
and coefficients do not weight that activity. Invalid/missing amounts leave it
unavailable; price-only live quotes preserve reconciled volume.

Full library verification: 5,339 tests in 221 files, 232 reference-host tests in
17 files, lint/types/build, declaration checks, bundle limits and tree-shaking.
API documentation has zero warnings; reference coverage is 901/901. Chart-only
size is 50.13 KiB versus 49.92 KiB before these corrections. Its documented guard
is now 50.25 KiB. Other tier limits are unchanged; aggregate is 223.43 kB Brotli.

The 1,144,741-byte candidate archive matches all 33 installed files. Consumer
validation passes 2,221 tests in 133 files, types, changed-file checks and the
production build. Existing canvas-test diagnostics and the large visualization
chunk warning remain. Generated tracked assets were restored. Added-text scans
found zero prohibited comparison names.

All 34 compatibility checks pass in Chromium, Firefox and WebKit. Firefox first
reported a visibility/render warning under the synthetic timer scheduler. The
harness now freezes only Date and keeps native timers; two subsequent Firefox
runs passed. Native timer timing also exposed an import attempted while the file
input was disabled after export. The harness now waits for it to be enabled.
Reports are `correctness-*-final.*`; screenshots were inspected. Narrow-pane
toolbar crowding remains in the original shared-toolbar scope.

At 18:03 UTC the authenticated history check passed with 1,512 BHEL bars and 1,575
index bars. Hover survived reconciliation, index volume stayed hidden, and one
matched combined candle reported 212,469 from leg amounts 148,608 and 63,861.
No execution request was sent. These are connected-history checks, not evidence
of fresh market trades. A later additional study probe restarted the dedicated
browser and lost its session; the latest `correctness-live.json` records that
failed retry, while the earlier successful tool result and screenshots preserve
the prior observation. Final connected release validation must use a fresh
signed-in session. The separate deterministic study checks verify Volume and its
average against combined leg data.

This closes the bounded issue fixes, not the production goal or final release.
Resume named-grid publication and management, then every remaining spec row.
