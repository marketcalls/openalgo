# Host lifecycle and compatibility

Read this when a custom terminal coordinates symbol changes, pagination, replay,
reconnect recovery, async registration, or charts initially hidden by a framework.
Use the shared controller for data ownership; hosts still own display binding,
replay controls, broker execution and teardown.

## Shared loading in 2.1.6

Prefer `DataLoadingController` for history, stream repair, paging and state.
`load(req)` changes source; `refresh()` repairs the current window. `loadMore()`
uses optional `BarsPageRequest` / `BarsPage` or bounded backward date windows.
`loadMore(until)` widens a date feed's window to reach `until` (UTC seconds) in
one request, up to `maxBars` bars of a fixed interval; a paged feed keeps its
ordinary window and returns one `countBack` page per call. Empty windows,
exhaustion and retention behave exactly as for a gesture.
`getState()` reports display bars; `bars()` is the live store. Methods resolve
retained bars on managed errors, so check state before claiming freshness.
`subscribe()` is changes-only and does not emit an initial snapshot.

Keep replay's displayed prefix isolated with `setPaused(true)` even when replay
playback is paused. Stop replay before `setPaused(false)`. `pushBar()` lets a
host keep an existing live subscription; omit `feed.subscribeBars` in that case.
`setVisible(false)` stops optional repair polling, not the stream. Destroy the
controller on unmount and let the owner close any shared feed.

Use `ChartDataContext`, `chart.getDataContext()` and `chart.setDataContext()` to
identify external-study requests. Clear old primary bars before switching context.
Preserve the visible time anchor across source replacement and release
`historyLoadComplete()` in finally. The widget supplies these bindings automatically.
For request/cache contracts and exact defaults read [feeds-and-live](feeds-and-live.md).

## Ownership across async work

Give each active chart/symbol/interval load a generation and capture its chart identity.
After every awaited request or module import, check both plus the host's disposed flag
and `chart.isDestroyed` before writing data or starting streams, timers or studies.
Guard live callbacks too: a callback queued before unsubscribe can still run afterward.

An older request's `finally` must not clear a newer request's loading flag or pagination
latch. Store the request identity and release state only while that request still owns
it. Aborting fetch is useful when the transport supports it, but does not replace these
checks. `BarsRequest.signal` and `timeoutMs` are optional in 2.1.6; pass the signal to the transport.
The shared controller supplies the generation fences for its own work.

On teardown, invalidate generations first, stop replay timers, release subscriptions,
cancel polling and remove host event listeners before destroying the chart. A shared
feed is closed by its owner once the last consumer is done.

## History paging and replay

`setHistoryLoader` triggers near the left edge; `prependData` keeps the current view.
Pair a current loader invocation with `historyLoadComplete()` on success, empty history
or failure. Keep error/retry state in the host. Before applying a page, verify that its
chart, symbol, interval and request ownership still match and replay is still inactive.
Do not let an obsolete page reset another request's loading state.

Replay controls displayed series; it does not own live feeds, polling or history jobs.
Track replay activity separately from `state().playing`: a paused replay still owns the
display. Pass every series sharing the timeline, including volume, to `ReplayController`.

Every live writer needs the same guard: streamed ticks, periodic history reconciliation,
reconnect recovery and history pagination. A terminal can keep full live history updated
in a separate buffer during replay, but none of those paths may call displayed
`setData`, `update` or `prependData` while replay owns those series.

On exit, call `replay.stop()` to restore its captured data/view, then apply the current
live buffer or refreshed history, preserve the intended viewport, and reseed the live
subscription from the newest historical bar. Calling `play()` on that stopped controller
starts its captured replay again; it is not a live-feed resume action. Clear the old
controller on symbol changes. See [replay-and-compare](replay-and-compare.md) and
[feeds-and-live](feeds-and-live.md) for the actual signatures and recovery semantics.

The companion OpenAlgo fixes described for 2.1.3 live in that application's
`frontend/src/lib/trading/terminal.ts`, `customIndicators.ts` and their tests.
Updating the Charts dependency alone
cannot repair a host path that replaces replay's displayed prefix.

## Hidden charts and preferred views

Since 2.1.3 a hidden chart can receive data before measurement; the first usable layout
applies the pending initial view. Keep a real container height and let `ResizeObserver`
report its size, or call `applySize(width, height)` after showing it when no observer is
available. Do not reload the feed just to obtain an initial fit.

```ts
const chart = createChart(el, {
  navigation: { mousePan: 'both', defaultVisibleBars: 120 },
});
const price = chart.addSeries('candlestick');
price.setData(bars);
chart.resetScale(); // preferred time window; autoscale and unlock every price scale
```

Prefer the initial automatic fit for the first load; call `resetScale()` when a later symbol load should use the preferred
window. An explicit restored viewport wins when applied after data. `fitContent()` fits
all loaded bars and therefore overrides the recent-bar window. Mouse and pen pan time
and price by default; `'horizontal'` is optional and touch still pans both axes. See [interactions](interactions.md).

## Registration and CSP

Import the relevant tier and await custom registration before adding/restoring its ids.
Concurrent split-pane restores and indicator pickers must await the same pending promise;
a boolean set before async registration finishes falsely reports readiness. Isolate
one invalid module from other valid descriptors and define an explicit retry policy.
The OpenAlgo host's `customIndicators.ts` clears its pending promise after completion,
but records processed file/mtime pairs before import, so a failed unchanged module is
skipped until its version changes or the host reloads. It is a host example, not an
export from Charts. Custom modules register through `registerIndicator` from the
package entry so the chart sees the same registry.

Ordinary registered functions and `createTier2Indicator` use no runtime code generation.
Load custom modules through native `import()` under the host's script policy; a widget
`styleNonce` only authorizes its stylesheet and grants no permission to execute fetched
code. The package supplies no general script loader or arbitrary-key async cache.
If the host adds a keyed registry/cache, use `Map` or own-key checks instead of treating
inherited properties as cached entries. Check that host implementation separately.
For Tier-2 data keys, failed fetches, stale attachment cleanup and timeline alignment,
use the existing [indicator lifecycle](indicators.md#tier-2-indicators-with-their-own-data).

## Browser validation

Upstream source checkouts contain these reproducible checks; installed npm consumers
should adapt their own harness rather than expect the scripts in the package tarball.

| Scenario | Existing check |
|---|---|
| Current bundles and real axis drags in gallery/profile/orderflow embeds | `node scripts/check-navigation-website.mjs <preview-base-url>` |
| Profile screenshot fingerprints, themes, split controls and orderflow table/lots | `node scripts/check-profile-website.mjs <preview-base-url>` |
| Depth grouping without changing candle axes | `node scripts/check-depth-demo.mjs <preview-base-url>` |
| Drawing placement, keyboard and responsive controls | `node scripts/check-drawing-demo.mjs <preview-base-url>` |
| Actual OpenAlgo consumer workflows with synthetic HTTP/WebSocket traffic | `node scripts/check-openalgo-compat.mjs --frontend /path/to/isolated-openalgo/frontend --probe-host true --output /tmp/openalgo-compatibility.json` |

The compatibility harness requires a linked OpenAlgo worktree with its own copied
dependencies and the candidate package installed. It starts the frontend with backend
proxies removed, blocks external traffic and records bundle hashes. Its replay probe's
`overwroteReplay` must be `false` for the corrected host. Passing mocked protocol cases
does not establish a broker's data quality or recover trades that were never delivered.
