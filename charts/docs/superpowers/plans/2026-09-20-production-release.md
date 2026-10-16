# Production contracts and release completion

> Root coordinates integration under the user's existing implementation and
> publication authorization. User explicitly requested parallel agents on this
> turn. Do not ask for the same authorization again.

**Goal:** Finish P1-P6, review the whole branch and publish Charts 2.4.5 before
remaining OpenAlgo /trading integration and final connected-feed validation.

**Spec:** docs/superpowers/specs/2026-09-19-production-workspace-design.md.

## Current ownership

- Root: instrument contract/example, shared entry points, replay-status accessor,
  compatibility policy, workflow/scripts, integrated validation and release.
- adapter_conformance: completed P2 deterministic runner, now P5 capabilities and
  order-state guards. Widget changes are delegated to the widget owner.
- widget_contracts: P4 translation and P5 widget capabilities/replay guards.
- browser_endurance: P3 real browser harness, sustained process and heap diagnosis.

Ruling: the user's new parallel-agent request supersedes the earlier inline-only
execution preference. Runtime editors must hand over a stable state before root
builds or runs broad checks. Dedicated endurance snapshots isolate their inputs.

## Integration gates

- [x] Review and validate instrument metadata/calendar/format integration and the
  rendered cash/futures/crypto example, including source transitions and OI gaps.
- [x] Review P2 production adapter drivers and negative controls. Preserve authored
  synthetic labels; no new real-feed claim follows from deterministic tests.
- [x] Verify P4 English fallback, safe interpolation, translated accessible labels,
  late dialogs and narrow layouts; confirm existing async storage evidence covers
  rejected writes, migration and account namespace ownership.
- [x] Verify P5 capability changes during awaits, queued modifications, preflight
  state preservation and widget replay/selection locks before callback delivery.
- [x] Run P3 gates to terminal with actual process handles. Retain failed runs and
  distinguish measurement races from retained engine objects before changing code.
  Record exact machine/browser/backend and synthetic workload limitations.
- [x] Run full lint/types/unit/demo/build/declaration/size/shake gates once editors
  are quiescent, then affected browser checks in Chromium, Firefox and WebKit.
  Inspect screenshots. Resume only gates blocked by an explicitly recorded budget
  or harness correction; do not describe a failed verify invocation as successful.
- [x] Fresh whole-branch review, then regressions for material findings and rerun
  the affected/full gates justified by those changes. Keep the score frozen.

## Maintenance and publication

- [x] Finalize compatibility/deprecation/support boundaries and consumer guidance.
  COMPATIBILITY.md and website compatibility.mdx contain the policy. The final
  website build, three-engine rendered checks and measured-fact review pass.
- [x] Set package/lock/source version to 2.4.5. Update changelog and website release
  notes, preserving historical facts and documenting OI as a level, never a sum.
- [x] Measure final registry counts and sizes after the versioned build. Update
  README, architecture text/diagram, website landing/getting-started/theme/meta,
  reference example docs and skills, by row label rather than old numeric text.
- [x] Warning-free API generation, skills coverage, website production build,
  runtime dependency audit and local release artifact checks.
- [x] Required remote CI and registry artifact comparison.
- [x] Commit locally, integrate/push authorized release source without disturbing
  original eight OI edits or other consumer work. Verify remote branch state first.
- [x] Push immutable v2.4.5 tag, dispatch existing Release workflow and wait for npm
  trusted publishing/provenance. Publish matching GitHub release and Pages site.
- [x] Compare registry package contents with the tested candidate, inspect deployed
  website assets/examples and report immutable source/version/release agreement.
- [x] Install published Charts in isolated OpenAlgo consumer, finish remaining
  /trading workspace/replay/toolbar integration and validate its production build,
  browser interactions and authenticated broker history. No real orders.

Registry observation on this turn: npm latest and latest GitHub release both remain
2.4.0. No 2.4.5 publication has occurred. Original OpenAlgo server on port5000 is
signed in and broker-connected, but its checkout still declares Charts2.4.0.

## Integration checkpoint and size ruling

The first combined verification passed lint, types, 5704 engine tests/241 files,
387 reference tests/30 files, build and declarations. It stopped at size limits;
it did not pass the entire verify command or reach tree-shaking. Instrument and
trading contracts plus optional widget localization measured base 91.05 kB,
base + trade 99.29 kB, widget 48.26 kB, terminal 204.58 kB and all tiers 244.20 kB.
The full-package growth over the previous completed host change is about 3.7 kB.
This is deliberate additive scope. Bounded ceilings become 91.5, 100, 48.75,
205 and 245 kB respectively; unaffected tiers retain their budgets. Re-measure
the final versioned build, including the review corrections, before publication.

Independent review found that the metadata tick missed primary series using
left/hidden scales. Two regressions failed with minMove 0 and now pass with the
actual primary scale receiving the tick. All 29 Instrument cases pass. The same
review found a large fractional quantity grid tolerance defect; its fix is in
progress separately. Widget capability-provider failures now render a disabled
explanation instead of silently removing all trading context.

The first combined browser run passed 14/15 cases, including all nine translated
widget/capability cases. WebKit caught a resize feedback loop in the standalone
Instrument example. An explicit flex height fixed it; all six instrument cases
then passed in three engines. Final screenshots and browser reruns follow the
versioned build. The example uses a matching dark palette and multiple ticks per
candle so its price and OI panes are readable.

Package, lockfile and source are now prepared as 2.4.5 locally. This is a candidate
version only; registry, release and deployment verification remain open.

### Versioned package verification

The first versioned invocation stopped at a test-helper TypeScript annotation:
the new alternate-scale helper inferred string instead of PriceScaleId. No
production behavior changed to correct that annotation. The subsequent complete
`npm run verify` invocation exited 0, with 5732 engine tests/242 files, 387
reference tests/30 files, seven Node endurance-harness tests, lint, types, build,
declarations, all size limits and tree-shaking. See
artifacts/candidate/production-contracts-245-verify-final.log.

The built runtime reports 2.4.5, nine export entries, 105 indicators, 15 chart
types and 85 drawing tools. Skills coverage is 930/930; TypeDoc with
--treatWarningsAsErrors exits 0 without warnings. Final build measurements are
base 91.04 kB, base + trade 99.38 kB, indicators 29.84 kB, draw 35.43 kB,
transform 4.50 kB, profile 14.96 kB, WebGL 6.39 kB, widget 48.30 kB, workspace
5.53 kB, terminal 204.62 kB and all tiers 244.34 kB Brotli. The standalone trade
bundle is 8338 bytes. Chart-only tree shaking is 52.34 KiB against 52.50 KiB.
The terminal size label now explicitly includes built-in studies; importing the
widget does not implicitly register the indicator bundle.

Independent P5 review additionally reproduced mutable requests bypassing
capability checks across awaits, and late modify/cancel completions replacing
newer broker intent. Detached request snapshots and per-order revisions correct
both. Fourteen race regressions were added (12 failed on the baseline); the
focused trade sweep passed 158 cases before the full verification above.

P2 conformance is committed as 964bd02. Current final browser/site, sustained
candidate evidence and independent workspace review remain in progress.

### Final review corrections and checked source

Independent read-only reviews of the workspace/template lifecycle and the shared
replay/comparison paths found two additional defects. Reference autosave omitted
replayPicking from its scheduling/flush guards, allowing a queued recovery save
to block the named catalog. Both guards now include selection. Two regression
cases failed before the fix; 389 reference tests/30 files and the new real
IndexedDB browser regression in Chromium, Firefox and WebKit pass.

Comparison alignment skipped duplicate whitespace retractions, preserving an
obsolete value and common baseline. The latest gap now deletes the earlier
reading. Two regressions failed before the correction and all 46 comparison/CSV
cases pass afterwards. The bounded reviews found no further reproducible defect;
they do not establish correctness for every broker or host configuration.

The complete browser sweep preceding those corrections passed 425 cases, with
one explicit skip because dist-baseline was absent. Instrument and translated
widget screenshots were inspected. Subsequent capture review showed that painted
pixels alone could accept the old wide bitmap before resize observation. The
narrow instrument capture now requires matching container/canvas dimensions,
painted pixels and two frames, then records viewport and chart separately.
All six targeted cases pass and their actual captures were inspected. The
original blank screenshot and diagnostics remain preserved. Final browser
execution is in progress.

The corrected source passed another full `npm run verify`: 5734 engine tests in
242 files, 389 reference tests in 30 files and seven Node harness tests. It also
passed lint, types, build, declarations, size and tree-shaking. Final Brotli byte
measurements are in production-245-reviewed-sizes.json; base 91002, base + trade
99340, terminal 204579 and all tiers 244302. The other tier bytes are unchanged
from the preceding measured build. The corrected base SHA-256 is
9415d9e48f37417c5e35c26fb0134643ccbe7a0ad47847e8e69e25eaef1b24ff.
Earlier endurance manifests remain attached to their earlier bytes. A new
30-minute run is requested for this exact candidate before release.

### Website and browser finalization

The final website production build exits 0. Rendered upgrade, compatibility,
instrument and release pages plus the runnable OI example pass in Chromium,
Firefox and WebKit. Two Markdown demo links initially repeated the deployment
prefix; the corrected generated links and actual requests pass. The OI line,
change histogram, futures pane and architecture diagram were visually inspected.
All six existing website checks (depth, profiles, navigation, loading, objects
and drawings) also exit 0. Runtime dependency audit reports zero vulnerabilities.
The homepage market-feed tests pass 11 cases and indicator benchmarks pass.

The reviewed 429-case browser sweep passed 427, skipped the missing baseline
case and timed out once during WebKit reference startup before chart creation.
Fifteen targeted reruns passed without production changes. Startup diagnostics
now retain pending/failed requests, HTTP errors, page/console errors and load
milestones on failure while preserving the original timeout/error. A negative
control verifies reporting and listener cleanup. No root cause is claimed for
the original startup timeout.

The actual published 2.4.0 package was downloaded and its dist extracted to the
ignored baseline directory after checking archive paths. The next complete
browser sweep therefore includes the rendering parity case rather than skipping
it. Its output is production-245-final-browser.log. Current runtime and build
inputs remain frozen at the reviewed SHA-256 during browser and endurance runs.

The next full browser sweep completed 428 checks and failed one Chromium startup
before any autosave action. Its preserved diagnostics and trace identify
net::ERR_NO_BUFFER_SPACE loading the required indicators module. Three targeted
reruns pass with unchanged timeouts and no source correction. The published
2.4.0 rendering baseline check passes. Compact panel checks also pass all nine
browser/container combinations. A final sweep after rebuilding remains planned.

Final package inspection reproduced separate TradingCapabilityError constructors
in the base and trade entries. Trade runtime imports and re-exports now use the
public base specifier, following the existing shared-identity bundling rule.
The post-build declaration guard first failed against the old package, including
both cross-entry instanceof checks. Focused source regressions pass 78 cases;
coordinated full verification will establish the corrected built result.
An added-line scan also removed four prohibited long dashes, including one
workspace validation message. No comparison-name additions were found.

### Corrected publish candidate

The corrected source passes the complete npm run verify command, including 5734
engine tests/242 files, 389 reference tests/30 files, seven harness tests and the
new built shared-error identity gate. Both import paths now expose the same
constructor and both refusal paths satisfy instanceof against either entry.
API generation with warnings treated as errors and skills coverage 930/930 pass.
The final website build also exits 0 after updating measured facts by row label.

Final measurements: base 91002, trade 8006, base + trade 99008, indicators 29841,
draw 35433, transform 4501, profile 14961, WebGL 6393, widget 48303, workspace
5524, terminal 204579 and all tiers 243964 Brotli bytes. Chart-only tree-shaking
remains 52.34 KiB. Registry counts remain 105 indicators, 15 chart types and
85 drawing tools, with nine public entries. Current facts in 49 table rows and
10 diagram measurements were independently checked against the size artifact.

The tested candidate archive contains 33 files, 1261530 compressed bytes and
4102636 unpacked bytes. It is preserved outside the checkout at
D:/OpenAlgo-Voice/artifacts/charts-245-publish-candidate/openalgo-charts-2.4.5.tgz.
Its integrity is
sha512-Dy8qdtL7wUOiWEqkUwEy/BrrFqHhYG0dYSrySV8jOZVjwiCDIzCF72T55xgZP1FkEd248bEHmW/XvtSV+e7bTQ==.
Publication verification must compare every archive file with this candidate.

The endurance workload's dependency closure contains only base and indicators.
Both remain byte-identical after the packaging correction: base SHA-256
9415d9e48f37417c5e35c26fb0134643ccbe7a0ad47847e8e69e25eaef1b24ff and indicators
1f51fd2cf579c8460c10021738f6d87317c4434c9621e8c3c13b2e8971baafa9.
The unchanged run remains applicable to that declared workload. Its external
final-artifact-comparison.json separately records changed unused package files.
No endurance claim is made for trading or workspace operations by this workload.

The corrected candidate's full browser sweep passes all 429 cases with no skips
or failures, using two workers. This includes the published 2.4.0 rendering
baseline and the startup diagnostics added after the preserved earlier failures.
Final generated website pages and runnable OI/instrument examples pass again in
Chromium 149.0.7827.55, Firefox 151.0 and WebKit 26.5. The current architecture
diagram, OI gap/change plots and narrow instrument pane were visually inspected.
Logs: production-245-publish-browser.log and
production-245-publish-website-browser.log in artifacts/candidate.

The reviewed endurance process reached terminal exit 0 with all 24 gates passing:
1800.1599 seconds, 17905 synthetic ticks, 61 memory samples and 107904 measured
frames. Frame p95/p99 were 17 ms, maximum gap 50 ms, pointer p95 31 ms and maximum
31.7 ms. Collected peak growth was 403280 bytes, slope 6181.40 bytes/minute and
30-cycle teardown retention 10147.33 bytes/chart. Bar counts remained 2000 per
chart; collection updates, browser errors, teardown node/listener growth and
final canvases were all zero. One 56 ms diagnostic long task occurred during
concurrent host work. Sampling pauses totaled 6565.2 ms and remain included in
wall/frame measurements. Start/end pixels were inspected. This is the declared
Chromium Canvas2D synthetic workload on Ryzen 7 7700, not live-broker or full-day
evidence. Both earlier and final reports remain preserved externally.

### Publication complete

Verified source db8bcce6a8d2237113d78561cad1161f8ae3b070 was committed and pushed
as a fast-forward to master without changing the original checkout. CI run
35506378753 passed every job, including Linux package verification, browser
checks, website interaction checks, code analysis and supply-chain checks.
Pages run 35506378723 succeeded. The immutable v2.4.5 tag resolves to that source.

Release run 35506904073 completed verification, version agreement, runtime audit,
SBOM generation and npm trusted publication with provenance. npm initially
reported processing and returned 404 for the version. No second publication was
attempted. Once available, npm latest resolved to 2.4.5 and its gitHead matched
the verified source. All 33 downloaded archive files match the tested candidate
byte-for-byte, including the same full archive SHA-512 integrity recorded above.
A fresh isolated registry installation loads all nine entries and passes the
runtime version/registry-count/shared-error checks. npm audit signatures verifies
one registry signature and one provenance attestation.

GitHub release https://github.com/marketcalls/openalgo-charts/releases/tag/v2.4.5
is public, final and carries the matching changelog. The deployed site at
https://marketcalls.github.io/openalgo-charts/ serves ten runtime bundles and the
architecture diagram byte-identical to the local build. Its changed pages and
OI/instrument examples pass Chromium, Firefox and WebKit checks; deployed pixels
were inspected. No site or package publication work remains for Charts 2.4.5.

Remaining goal work is the published-package OpenAlgo consumer migration,
comparisons/shared replay/CSV integration and final connected-broker validation.
The score remains frozen and no live orders were placed.


### OpenAlgo consumer acceptance and delivery

The published-package consumer is committed as 6e914b354 on
feat/production-chart-workspace and is under CI in
https://github.com/marketcalls/openalgo/pull/2083. It adds comparison persistence,
shared replay with workspace execution guards, selected-chart CSV and the final
OI/alert/workspace integration. The canonical guide, changelog and indicator
references describe the resulting controls.

The frozen consumer passes 2403 frontend tests across 150 files, TypeScript,
production build, lint and metadata/skill checks. Browser acceptance passes all
201 checks, 67 each in Chromium, Firefox and WebKit. Screenshots were inspected;
there are no unexpected console errors, runtime events or external HTTP. All 649
recorded source/configuration/harness hashes remain unchanged. Reports are in
D:/OpenAlgo-Voice/artifacts/consumer-245-final-browser-summary.json and the
consumer-245-final-{engine}-acceptance files.

The compatibility harness now supports consumer-owned acceptance modules,
subscription-aware LTP delivery, shared replay controls and OI-unavailable text.
A paint boundary before automated reload resolves the observed departing-document
visibility warning; failed reports remain preserved and assertions are unchanged.
No Charts engine, package, version or immutable release tag changed.

Authenticated cash-history validation passes on the final production build with
1440 historical bars plus one forming bar, blank OI and no invented study values.
The interface reports the cash instrument's unavailable OI explicitly. Futures
OI equality and final GitHub/actual-checkout rollout are still pending. The test
session uses real broker history and the installation's 502 custom indicators;
routed browser timings are not uninstrumented host performance evidence. No live
orders were placed, saved chart state is preserved and the score remains frozen.


### Consumer rollout complete

OpenAlgo PR https://github.com/marketcalls/openalgo/pull/2083 passed all CI jobs
(run 35517952000) and merged as 621eaab62. Its tree matches verified consumer
commit 6e914b354. Main CI run 35518540216 passed all jobs, including the frontend
matrix, browser checks, production assets and both container architectures.
The generated-assets commit is 1c3d11cbd. Issue 2077 closed with the merge.

The final broker check matches every one of 1309 futures OI readings by timestamp
against fresh broker history; plotted and exported readings agree, while three
forming/live gaps remain blank. Cash instruments retain blank OI and their explicit
unavailable message. Comparisons, alert bar-close defaults and shared replay/live
restoration pass. The corrected runner captures CSV in memory with no downloads.
The market was closed, so this is historical-data/UI evidence, not full-day
open-market endurance. No live orders were placed.

The original OpenAlgo checkout fast-forwarded cleanly to 1c3d11cbd, installed
registry Charts 2.4.5 and refreshed asset compression. Actual served-page checks,
without any asset overlay, pass with zero page/module errors, execution attempts
or browser downloads. Chart storage is preserved and validation databases/pages
are removed. Served HTML matches tracked dist exactly. Broker evidence is in
D:/OpenAlgo-Voice/artifacts/consumer-245-broker-recovered-2026-09-20T15-01-10-800Z
and consumer-245-broker-2026-09-20T15-16-28-877Z.

The user's refreshed /trading page now shows candle-colored volume. The reported
screen-width issue came from the test browser's fixed viewport. Relaunching that
browser with viewport=null preserved authentication and restored 1920-pixel width
through reload and new-tab creation, with 1822-pixel chart canvases. No application
patch was needed. Screenshots and dimensions are preserved as
consumer-245-original-final-colored-volume.png and
consumer-245-original-final-viewport.json under the artifacts directory.

Charts follow-up harness commit c54626d also passed its complete CI run
35518044292. Package source/tag db8bcce and the published 2.4.5 archive are unchanged.
The original Charts checkout's eight OI edits remain preserved. User guide,
changelog, indicator references and the consumer verification plan are updated.
All requested release and /trading delivery work is complete; the score stays frozen.
