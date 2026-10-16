# openalgo-charts pitfalls

*When to read this: before writing or reviewing any openalgo-charts code, and whenever a chart "renders nothing", "ignores my setting", "scrolls when it shouldn't", or "works in the demo but not in my app". Every entry below is a verified failure mode in the current source, not a hypothetical.*

## Time and data

**`Bar.time` is UTC seconds, never milliseconds.** The internal axis is integer UTC seconds (`src/model/bar.ts`); a ms value lands ~50,000 years past the data and every derived time (crosshair, drawing anchors, markers) is garbage. Feed adapters convert at the edge (`epochMsToUtcSeconds`, `istStringToUtcSeconds` in `src/feed/time.ts`).

```ts
series.setData([{ time: Date.now(), value: 1 }]);                  // wrong
series.setData([{ time: Math.floor(Date.now() / 1000), value: 1 }]); // right
```

**Two bars at the same time do not throw and do not both draw, the last one in your array silently wins.** `sortedUniqueByTime` (`src/model/data-layer.ts`) collapses repeats because the shared axis maps times through a `Set`; the sort is stable, so *input order* decides the survivor. This is why an unseeded candle builder used to paint a red candle under a live green one: call `builder.seed(bars[bars.length - 1])` before the first live tick.

**`setData` accepts unsorted input and sorts it, but a stored `Bar` reference can be mutated under you.** `DataLayer.update` with a matching time replaces the last bar in place (`'replace'`). Treat `dataLayer.seriesBars(id)` as read-only (it is the live array); `SeriesApi.getData()` returns a copy.

**A whitespace item `{ time }` is kept as a NaN OHLC bar, not dropped.** `toBar` gives it `close: NaN` so the line renderer breaks and autoscale skips it, but `getData().length` still counts it. Any length- or reduce-based logic over `getData()` must tolerate `NaN`.

**Axis and crosshair labels default to IST (`Asia/Kolkata`), not UTC and not the host locale.** It is a default, not a fixed property: set `timezone` on `createChart` or call `chart.setTimezone('America/New_York')`. An unrecognised name **throws** at the call site (a saved layout's stale zone is skipped instead), so validate with `isValidTimezone` when the name comes from user input.

**Setting `timeFormatter` relabels the axis but does not move the calendar.** Session anchors and pivot frames resolve on `chart.timezone()`, so a formatter that prints New York hours on a chart still set to `Asia/Kolkata` draws a VWAP that restarts in the middle of its own drawn day. Set the zone too. The formatter also receives **raw UTC seconds**, so do not offset again inside it, and it takes a second `tickMarkType` argument (`year|month|day|time|timeWithSeconds`) that a one-arg formatter silently discards along with year/month boundary labelling.

**Profile session windows do not follow the chart's zone, and that is deliberate.** `SessionWindow.startMinute` / `endMinute` are minutes from midnight in the window's *own* zone (`TRADING_HOURS` presets each name one); the profile's `timezone` option only settles a window that names none. Bucketing on the display zone would cut a 09:15-15:30 Kolkata session in half when viewed from New York. See [profiles-and-orderflow](./profiles-and-orderflow.md).

**An unknown interval code now throws, and that is the fix, not the bug.** `resolveInterval` raises `UnknownIntervalError` (carrying `.code`), `intervalToSeconds` throws for an unknown code and separately for a calendar or count-driven one that has no fixed length, and `OpenAlgoLiveDataFeed.subscribeBars` resolves up front so a typo fails at subscribe time. Until 1.4.0 all of these answered 60, so `'5min'` drew one-minute bars under a five-minute label with nothing anywhere saying so. Validate a picker's input with `isKnownInterval` / `tryResolveInterval`, and do not wrap `resolveInterval` in a try/catch that falls back to a guess: that reintroduces the defect.

**A calendar interval has no seconds, so do not ask for any.** A month is 28 to 31 days, a New York month is not a Mumbai month, and `30 * 86400` is wrong for all of them. Register the code with `{ mode: 'calendar', unit: 'month' }` and bucket with `bucketStartOf` / `nextBucketStart`, which resolve at local midnight in the entry's zone (or the caller's, defaulting to IST).

**Never cache the forming bar.** The last bar is alive until its interval ends; a cache that hands back a snapshot of it puts a stale close on the last-price line, the axis tag, the header LTP and every indicator computed off it, instantly and with no spinner. `withBarCache` drops trailing unclosed bars on store for exactly this reason, so a hit is short by at most that one bar. If you write your own cache, keep the closed history and refetch the tail. A fast wrong price is a worse failure than a slow right one on a chart that draws Buy and Sell buttons.

**A cache keyed on the requested range misses on every pan.** `withBarCache` keys on `symbol|exchange|interval` only, holds the widest set fetched so far, and slices. Out of hours it still goes cold unless the host caps `to` at the newest bar it expects to exist: a hit past the entry's coverage is allowed only while the next bar is still forming, and the cache cannot know a market is closed.

**Candle buckets align to `sessionAnchorSec`, which defaults to 0 (epoch), not to the session open.** For a 09:15 session, pass the anchor or your 5m bars start on the wrong minute (`src/feed/candle-builder.ts`). `lateTickPolicy` defaults to `'foldIntoBar'`; `'dropOlderThanPrevBar'` makes `onTick` return `null`, so null-check it.

See [data-and-time](./data-and-time.md), [feeds-and-live](./feeds-and-live.md).

## setData vs update vs prependData, and the viewport

**The initial view is fitted once from `navigation.defaultVisibleBars`, after non-empty data and a usable layout width.** Later `setData` calls deliberately preserve the current zoom. If a symbol switch should re-frame the chart, call `chart.resetScale()` for the preferred recent-bar window or `chart.fitContent()` to explicitly show all loaded history. A hidden first load can wait for measurement without fetching again.

**`update()` returns `'append' | 'replace' | 'insert'`, and only a *global* right-edge append auto-scrolls.** A bar newer than this series' last bar but older than the newest time on the shared axis is an `'insert'`, the chart deliberately does not treat it as a new right-edge bar, so do not infer "new bar" from `update()` being called. An out-of-order `update()` that corrects a bar the series already holds finds it by binary search and replaces it in place (since 2.5.8). One that brings a time the series does not hold is O(n): it is inserted, and the shared axis is rebuilt across every series, so batch late bars rather than streaming them.

**A longer retained history makes every live tick slower, even with the same bars in view.** Each frame that carries a tick still does work over the whole history for every study: a full recompute, or for the sixteen built-ins with a `calcTail` (since 2.5.8) a step or one window plus a copy of each output column, and for every study a comparison of each plot point with what its series holds. The frame then repaints the price pane and every pane holding a study computed from it (every pane when a bar is appended, and the panes showing the corner clock or bar countdown while those are on). The recorded endurance workload (two charts, 150 bars in view, five studies each, ten updates a second) measured a frame-interval p95 of 17 ms at 2,000 bars per chart and 717 ms at 50,000 on the 2.5.5 build on one desktop machine; see `docs/browser-endurance.md`. On 2.5.8 the render bench measured a ten-study tick at a p95 of 20.1 ms at 10,000 bars and 152.2 ms at 200,000 on `canvas2d` (`docs/performance-notes.md`). Bound the retained history to the longest lookback users need, and measure on the target device.

**`prependData` shifts every logical index, so any logical index you cached is now wrong.** The viewport survives because `baseIndex` is re-read and `rightEdge − index` is invariant, a saved `{ from, to }` logical range is not automatically re-based. This is also why drawing anchors are `{ time, price }` and never pixels or indices.

**`setVisibleLogicalRange` is a silent no-op before layout and for a non-positive span.** It returns early when `width <= 0` or `to <= from`, and bar spacing is clamped to configured limits (default `[1, 260]`), so an extreme span lands at the nearest legal zoom rather than erroring. Set custom limits through `ChartOptions.timeScale`. Restore viewports *after* data and usable layout.

**`setHistoryLoader` fires once and then latches until you call `chart.historyLoadComplete()`.** Forget the completion call and lazy paging stops after the first page, with no error.

**`chart.restoreState()` never recreates series, it returns a `RestoreReport` for you to rebuild them.** Series *data* belongs to the app. It also never throws: a malformed or newer-versioned state returns `{ applied: false, reason }`, and an indicator whose tier is not imported is skipped, not thrown.

See [events-and-state](./events-and-state.md).

## Imports, tiers, and registries

**Never deep-import into `dist/` or `src/`, a deep path inlines a second copy of the registry and your registration disappears.** Each tier is its own bundle with the package entry marked external; a relative or deep import gives the tier a private registry `Map` that `createChart` never reads. This is documented as a correctness bug in `rollup.config.js` and in every tier index.

```ts
import { registerIndicator } from 'openalgo-charts/dist/index.mjs'; // wrong: second registry
import { registerIndicator } from 'openalgo-charts';                // right
```

For the same reason `dist/openalgo-charts.all.mjs` is a docs-site bundle, excluded from `files` and `exports`, importing it in an app defeats the tiering and can reintroduce the duplicate registry.

**A missing tier throws a specific, greppable message: read it instead of guessing.** `openalgo-charts: unknown indicator "<id>", did you import 'openalgo-charts/indicators'?`; `openalgo-charts: series type "point-figure" needs the transform tier, import 'openalgo-charts/transform' first`; `openalgo-charts: unknown series type "<type>"`; `openalgo-charts: unknown drawing tool "<id>"`. Only `point-figure` and `kagi` get the friendly transform message, Heikin Ashi, Renko, Range and Line Break render as `candlestick` and need no new type.

**Tier imports are side effects; an over-aggressive bundler can drop them.** `package.json` `sideEffects` whitelists the tier paths. If a bare `import 'openalgo-charts/indicators'` gets shaken out, call the explicit registrar instead: `registerBuiltinIndicators()`, `registerTransformChartTypes()`, `registerBuiltinDrawingTools()`, all idempotent.

**Registering an id that already exists overwrites it silently, no warning, last write wins.** True for `registerChartType`, `registerIndicator` and `registerDrawingTool`. Namespace custom ids.

See [bundling-and-tiers](./bundling-and-tiers.md).

## Scales and panes

**Price-scale margins are fractions of the *pane height*, not padding on the data span.** The data band occupies `1 - marginTop - marginBottom` of the pane (`autoscaleRange`, `src/scale/price-scale.ts:41`). Margins summing to ≥ 1 do not throw; they clamp to a 1% sliver. The option names are `marginTop`/`marginBottom`, not `scaleMargins.top/bottom`.

**`series.priceScale().setOptions({...})` merges options but schedules no repaint.** `PriceScale.setOptions` is a plain merge; the change appears on the next invalidation from something else. Follow it with a repaint trigger such as `series.applyOptions({})` or `chart.applyOptions({})`.

**Any manual price-axis gesture disables autoscale for that scale permanently.** `panByPixels`, `scaleAroundCenter` and the axis drag all set `autoScale = false`, and `Pane.autoscale` then skips the scale entirely. Recover with `chart.resetScale()` (also bound to double-click) or `scale.setAutoScale(true)`. While autoscale *is* on, it reads only the **visible** bars (`dataLayer.visibleBars(from, to)`), so the range moves as you pan.

**Overlay IDs default to hidden placement.** `priceScaleId: ''` is shared and often holds volume; a distinct `overlay:${string}` ID creates an independent scale. Sharing an ID shares its range and baseline. `setPriceAxisPlacement` can expose either overlay form as a visible column without changing its ID. A primitive's autoscale contribution goes to its explicitly bound scale; unbound primitives use the right scale. Bind through `pane.bindPrimitiveScale` and honor `priceAxisSide`, `priceAxisWidth` and `priceAxisOffset` when drawing its axis labels.

**`percentage` and `indexed-to-100` behave exactly like `linear` until something calls `setBaseline`.** The baseline is data, so the scale cannot find it alone; the pane feeds it the first visible value each frame. A null, zero or negative baseline falls back to the identity transform on purpose, so an axis that "ignores" percentage mode is an axis with no usable baseline, not a broken transform. While a rebase is in force, `format()` outranks a custom `priceFormatter`. Log mode is unaffected and still clamps non-positive prices to `1e-10` rather than producing NaN.

**Axis columns change the plot width across the whole chart.** Panes share the maximum active column count on each side. Placement changes and adding/removing series or bound primitives can change both insets; resizing can reduce each column's width. Re-read `priceAxisLayout()` and coordinate conversions instead of caching pixel math. Configured unused scales reserve no column, but attached hidden series still occupy their scale's visible column.

**`addSeries(type, { paneIndex: 3 })` silently creates panes 1..3; it does not throw.** A typo'd pane index produces blank panes that also get persisted by `getState()`. In the other direction, `removePane` on the price pane, a `movePane` off either end and, by default, a `movePane` that would displace pane 0 return `false` rather than throwing (with `movablePrimaryPane` the price pane itself moves: `setPrimaryPaneIndex`), `maximizePane` **hides** the other panes rather than shrinking them (their stored weights are untouched, and the bottom *visible* pane takes the time axis), and `setPaneWeight` clamps to a 0.05 floor. A pane that should get out of the way without losing anything is `setPaneCollapsed(index, true)`, not a tiny weight: the weight floor keeps a squeezed plot on screen, while a collapsed pane is a header strip whose weight comes back untouched.

**A `SeriesApi` captures its pane index at creation, and `removePane`/`movePane` re-index panes.** Indicators are re-pointed automatically; host-added series are not. Call `series.remove()` before restructuring panes, or re-add the series afterwards.

**Slot 0 is not the price pane once a user moves it**, which only a chart built with `movablePrimaryPane` allows (off by default in `createChart`, `createWidget` and `createChartGrid`). A host that passes `0` to mean "the price pane" (an order line, a volume overlay, a price alert check, a coordinate call for a DOM overlay) lands on a study pane after `setPrimaryPaneIndex` or `movePane`. Omit the pane, which defaults to the price pane, or ask `chart.primaryPaneIndex()`, before turning the option on.

**With the default `minMove: 0`, price precision is inferred from the visible range, so label decimals change as you zoom, and `snapToTick` is a no-op.** Set `priceFormat: { type: 'price', minMove: 0.05 }` (or `precision`) per series for a stable instrument tick.

**Placement and legacy reassignment are different operations.** `setPriceAxisPlacement` retains a scale's ID and can put multiple columns on either side. `movePriceAxis` swaps the built-in side scale objects and reassigns resources from one side ID to the other; the destination ID must be unused, and its placement resets to the requested side. Other named scales can already occupy that side. `PriceAxisState.movable` describes only the legacy operation. Both are deprecated and go in 3.0.0; new code uses placement. Invalid or unchanged placement requests return false; ratio locking also returns false when nothing has been measured.

**A right-click targets an actual axis column.** Pass `target.scaleId` into the `priceAxis*` calls rather than inferring it from `side`; a named or empty overlay can have a visible column. Unused aligned cells return an empty target and never fall back to a hidden scale. Off-plot `price` and `index` are null. The bottom-left corner belongs to the time axis; a populated bottom-right column retains its price-axis target.

**Chart-wide auto-fit applies to visible columns.** `chart.setAutoScale(on)` updates all active visible axes, releasing their ratio locks when enabled. Hidden scales and their locks retain their state. Use `setPriceAxisAutoFit(paneIndex, scaleId, on)` to address a hidden scale explicitly; `resetScale()` still resets every created scale.

See [scales-and-panes](./scales-and-panes.md).

## Indicators

**A plot's colour setting key is the descriptor's declared `colorKey`, not `<plotKey>:color`.** Only `width`, `lineStyle`, `opacity` and `type` are generated as `<plotKey>:...`. Setting `'macd:color'` on MACD is silently ignored because its declared key is `macdColor`. Read the real keys from `plotStyleKeys(plot)` / `indicatorStyleInputs(descriptor)`.

```ts
macd.setSettings({ 'macd:color': '#f00' });   // wrong: silently ignored
macd.setSettings({ macdColor: '#f00', 'macd:width': 2 }); // right
```

**Indicators recompute only when the *primary* price series changes.** The primary series is the first `addSeries` of a price type; indicator plots never claim it. Updating a secondary series will not retrigger any indicator.

**`calc` must return arrays the same length as `bars`, using `null` for warmup slots.** Shorter arrays misalign the whole plot. `null`/`undefined` become `NaN`, which the renderer breaks across and autoscale skips. `calcTail` is optional; without it every live tick costs a full O(n) recompute per indicator, and returning `null` from it falls back to `calc` silently. A descriptor that spreads a built-in does not inherit its `calcTail` (the property is not enumerable); copy it by name, `calcTail: getIndicator('sma').calcTail`, only when your `calc` returns the built-in's result unchanged for the settings it is given, since a tail never calls your `calc`.

**`descriptor.range()` (e.g. RSI 0..100) applies only when the indicator created its own pane.** Two indicators sharing a pane would otherwise fight over the fixed range, so an indicator added onto an existing pane silently autoscales instead.

**There are 112 built-ins, and their ids are not derivable from the display names.** `williams-percent-r`, `bollinger-percent-b`, `smi-ergodic-oscillator`, `special-k`. Read `BUILTIN_INDICATORS` or the table in [indicators](./indicators.md) and probe with `hasIndicator(id)` rather than catching the throw from `getIndicator`. The second and later instances of the same indicator id get auto-rotated colours: only keys you left unset are filled, an explicit colour always wins, and the first instance keeps the descriptor's own choice.

**`registerIndicator` overwrites by id, and 112 ids are already taken.** Registering `momentum`, `median`, `volume` or `atr` for a custom study silently replaces the built-in for the whole page. Namespace custom ids.

**`IndicatorFillSpec.between` names `calc` output columns, not declared plots.** A fill whose `between` references a plot key that `calc` happens not to return draws nothing, with no error. The shaded overbought/oversold bands in the catalogue rely on this the other way round: they fill between two constant columns that no plot names.

**Signal markers are a separate primitive from the plots.** `descriptor.markers` attaches through `series.createMarkers()` on the *first* plot's series, lazily, and only once the hook returns a non-empty array. A plot-level style patch does not touch them, and there is no `addIndicatorMarkers` on the host: the layer is created by the plot's own series and removed by `removeIndicatorMarkers`.

See [indicators](./indicators.md).

## Transforms

**Transform output timestamps are synthetic: colliding times are bumped `+1s` so each element gets its own logical index.** You therefore cannot join a Renko/P&F/Kagi series to a raw-timestamped series (a volume pane) by time, re-bucket the companion series onto the transformed element times. Relatedly, `runTransform` calls `reset()` and is batch-only: for live ticks keep the instance and call `transform.push(bar)`.

**Point & Figure reads `column.boxSize` from the data, not `style.boxSize`, and defaults to `method: 'hl'`.** A `style.boxSize` that disagrees with the column is ignored (this footgun was removed deliberately). `method: 'close'` can legitimately produce zero columns on flat closes with wide intrabar range.

See [transforms](./transforms.md), [chart-types](./chart-types.md).

## Profiles and order flow

**Footprint and cumulative delta need trade-by-trade data already classified bid/ask, OHLCV cannot be reconstructed into it.** OpenAlgo does not store classified historical trades by default, so footprint is a live-session feature unless you add a tick recorder (`src/profile/footprint.ts`, `ARCHITECTURE.md` §6A). Volume Profile and Market Profile need only bars and work on history.

**`rowTicks` is a multiplier on `tickSize`, not a row height in price.** `computeFootprint(time, trades, 0.1, 20)` and `rowTicksFor(2, 0.1) === 20` both mean "2-point rows on a 0.1 tick". The two stay separate deliberately: imbalance and single-print logic still count in real ticks, so widening rows must not change the reported tick size.

See [profiles-and-orderflow](./profiles-and-orderflow.md).

## Drawing tools

**Anchors are `{ time, price }` in data space, and a non-finite anchor is rejected outright.** A NaN anchor would serialise to `null` and produce a drawing that can never be rendered or hit-tested. Note that `coordinateToPrice`/`priceToCoordinate` are safe before the first frame, the chart scales on demand.

**The library installs no keyboard listener for drawing tools.** `Alt+T/H/J/V/C` etc. exist as declared `shortcut` metadata only; the host must wire a listener and call `matchDrawingShortcut(event)`. Modifiers must match exactly and a bare letter never matches, so ordinary typing is unaffected.

**Tools declaring `points: 0` never self-terminate.** `path` and `polyline` collect vertices until `controller.finish()` (double-click, or your own key binding). Freehand tools (`brush`, `highlighter`) declare `freehand: true` and commit on pointer release instead, a freehand tap that never moved is dropped.

**Drag-to-draw only works because the controller arms `chart.setPlacementMode(true)`.** Without placement mode a press-drag-release pans the chart and emits zero clicks. If you drive placement yourself, arm and release the mode or the chart stays un-pannable, which is also why `DrawingController.destroy()` is mandatory: `chart.destroy()` does not tear down the controller, and a leaked one can strand placement mode on. (A whole drag is a single undo step, not one per frame.)

**`copy`, `cut` and `paste` are async, and `cut`'s result is load-bearing.** They return promises because `navigator.clipboard` does. A `cut` deletes only after the write resolves, so a fire-and-forget `draw.cut()` on a page where the permission is refused (and `fallbackToMemory` is off) leaves the drawing in place with no error anywhere; check the boolean, and read `draw.clipboard().lastError()` to tell "copied in this tab only" from "copied everywhere".

**A paste of foreign content is silently empty, by design.** `paste()` resolves to `[]` for a spreadsheet cell, someone else's JSON, or a corrupt copy of our own payload, and never throws: a Ctrl+V handler must not blow up on whatever the user last copied. Do not treat an empty array as an error to report; treat it as nothing to paste. Validation is all-or-nothing, so one bad entry rejects the whole payload rather than pasting the rest.

**Pasted drawings are fresh objects with fresh ids.** They are not a second reference to the source, so do not expect a later edit of the original to follow. The copy is nudged two bars and 16 px, applied per anchor through the coordinate API so it stays a rigid screen translation on a log scale.

See [drawing-tools](./drawing-tools.md).

## Primitives and custom rendering

**Chart furniture is not pane furniture.** A price line belongs to a pane. A watermark, a
corner clock or a brand mark belongs to the chart, and pinning it to pane 0 puts it in the
middle of the chart the moment an indicator pane appears. Use
`addPrimitive(p, { anchor: 'chart-bottom' })` and the engine re-homes it as panes are added,
removed, moved and maximized. Maximize is the case a host cannot work around by hand: it
HIDES the other panes, so a mark on pane 0 disappears rather than merely sitting wrong.
`paneAdded` exists too, if you would rather position your own chrome.

**`draw(ctx, rc)` receives a context in *bitmap* (device) pixels while `hitTest(x, y)` receives *media* (CSS) pixels.** `rc.timeScale.indexToX()` and `rc.priceScale.priceToY()` also return media px, so drawing code must multiply by `rc.dpr`. Forgetting it renders at half size on a retina display while hit-testing stays correct, the classic "clicks work but it looks wrong" bug.

```ts
ctx.fillRect(rc.timeScale.indexToX(i), y, 4, 4);                       // wrong on dpr > 1
ctx.fillRect(rc.timeScale.indexToX(i) * rc.dpr, y * rc.dpr, 4 * rc.dpr, 4 * rc.dpr); // right
```

**`autoscaleInfo()` is called once per primitive on every autoscale pass, that is every pan, zoom, tick and resize.** Keep it O(1) or precompute. Return `null` to opt out entirely (drawings do), and return `null` rather than `{min: 0, max: 0}` when you hold no data.

**Hit-testing is nearest-distance-first; `zOrder` only breaks exact ties.** A `'bottom'` primitive 1px from the cursor beats a `'top'` one 3px away. Two further overrides sit above all primitives: a pane divider within 4px, and pane-legend button ids the chart consumes before `subscribeClick`.

**`zOrder: 'top'` moves the primitive to a different canvas, not just later in the paint order.** Top-layer primitives repaint on every crosshair move and are frozen while the native context menu is open. `bottom`/`normal` share the base canvas with the series.

**`rc.priceScale` is the pane's *right* scale, not its readout scale.** A primitive on a pane whose series were moved to the left strip is drawing against a scale nothing has measured, so its output lands at the `0..1` placeholder. Coordinate conversions on the chart (`priceToCoordinate`) follow the readout scale; the primitive context does not.

**`PriceLevels` drawing nothing is usually correct, not broken.** A level with no data is `null` and draws nothing: `previousClose` on a series holding one session, the four extended-hours levels with no `marketPhase` classifier, `bid` and `ask` with no `quote`. `available(kind)` is the check, and `lastPrice` is **off by default** because the pane already draws it from `SeriesStyle.priceLineVisible` / `lastValueVisible`. Turning it on as well paints the line twice.

See [primitives-and-plugins](./primitives-and-plugins.md).

## Trading, orders, and money

*Every entry here was a shipped defect. This is the section to read twice.*

**A partial modify must not default the fields it does not mention to zero.** OpenAlgo's
`modifyorder` takes the WHOLE order, not a delta, so every field is sent on every call.
Until 1.6.0 `modify()` rebuilt symbol, action, exchange, pricetype, product and quantity
from its cached context but took the two price fields from the patch with `?? 0`. A
stop-limit carries both a limit and a trigger, and dragging its line sends only the trigger,
so that path sent `price: 0` and wiped the limit off a live working order at the broker.
The cache now carries both prices, seeded on place and on order-book load. If you write an
adapter for a broker whose modify is whole-order, this is the trap.

**Never fail open on a broker payload.** The old `mapOrder` mapped an unknown status to
`working`, a missing action to **BUY**, and an unreadable number to 0. A fail-open BUY is
the worst possible default in a trading payload: a corrupt row rendered as a live buy order.
Use `getOrderBook()`, which returns `{ orders, quarantined }`, and treat `status: 'unknown'`
as something to reconcile, never as tradable.

**A guarantee reachable only through a wrapper is not a guarantee.** Quantity validation and
idempotency lived in `OrderEngine`, and the largest consumer of this library calls
`feed.place()` directly and never constructs one. Both now sit in the feed as well. When you
add a safety check, ask which layer a real host actually calls, and put it there.

**Do not release an idempotency token when a place fails.** A failed write says the RESPONSE
did not arrive. It says nothing about whether the REQUEST did. Releasing makes the retry
indistinguishable from a first attempt and can double a live position. Keep the claim, mark
it ambiguous, and release only when the request provably never left, which the feed signals
with a pre-flight error. `feed.tokenState(token)` reports it.

**Validate quantity for EVERY order type, not just the ones with a price.** The old engine
put the whole validate call behind `if (req.price !== undefined)`, so a MARKET order, the one
that cannot be taken back, skipped the exchange freeze-quantity check entirely.

**A client-side check is a UX affordance, not a risk control.** Anyone can call the broker
from devtools. The broker RMS must enforce the same rules independently. Say so in the code
so the next reader does not mistake one for the other.

**Analyzer or sandbox mode is a server property.** Do not put a `mode` field in an order body
that the server ignores: a control that looks real and does nothing is worse than no control.
OpenAlgo decides analyzer server-side, so the feed reads `/api/v1/analyzer/` and REFUSES to
place when the server disagrees with the caller's expectation.

## Events and state

**A listener that throws does not stop the chart.** Since 2.6.0 an exception thrown by a listener on the chart bus, `chart.trading.on` or `chart.shortcuts.on` is reported through `reportError` (the browser console and the window `error` event) and the other listeners and the render loop carry on. Before 2.6.0 the chart bus dropped it silently, so on an older release wrap handler bodies in your own try/catch while debugging.

**`subscribeClick`/`subscribeCrosshairMove`/`subscribeDrag` add a subscriber each call (since 2.6.0; before, a second call replaced the first) and `subscribeClick` is hit-only.** Keep the unsubscribe each returns: a host that subscribes again on the same chart without it hears every click twice. Use `chart.on('click', ...)` for clicks on empty plot, which carry `id: null` plus `price`, `time` and `point`. Event names are plain strings, so a typo silently never fires; the crosshair-leave payload is all-null and must be handled.

**`chart.off('click')` with no callback removes *every* listener for that event, including the drawing tier's and the trade layer's.** Always pass the callback, or keep the unsubscribe function `on()` returns.

See [events-and-state](./events-and-state.md), [interactions](./interactions.md).

## Replay and comparison

**Constructing a `ReplayController` enters replay immediately.** It snapshots the driven series' data and the viewport and jumps to `startIndex`; there is no separate `start()`. `stop()` is what puts the data, bar spacing and right offset back.

**Replay drives series through `setData`, so a live feed fights it.** Detach the feed (or stop calling `series.update`) for the duration, and pass *every* series that shares the timeline in `options.series`: one left at full length keeps future timestamps on the shared axis and the replay appears not to hide anything.

**A comparison must not be fed or removed through its own series.** `handle.series.setData` skips alignment (a foreign timestamp then shifts the primary's bars), and `handle.series.remove()` leaves the pane rebased with nothing on it. Use `handle.setBars` and `handle.remove`.

**A comparison print with no primary bar is dropped, not inserted.** Check `handle.alignment().dropped` before concluding the second symbol "has no data": a different exchange calendar or a different interval drops everything, because matching is on the exact timestamp with no tolerance window.

See [replay-and-compare](./replay-and-compare.md).

## Chart linking

**Never copy a logical index or a logical range from one chart to another.** This is the defining mistake of the feature. The x axis is a gapless index over *that chart's own bars*, so index 300 is a different instant on every chart in a grid: the copy looks perfect on two charts of the same symbol and interval and is wrong the moment the intervals, the history depth or the holiday calendars differ. Convert index to time on the sender (`indexToTimeFloat`) and time back to index on the receiver (`timeToIndex` / `timeToIndexFloat`), or use `LinkGroup`, `followerIndex` and `followerRange`, which do it for you.

**A linked crosshair draws no horizontal line, and that is not an omission.** The price under a cursor on another instrument is not a price on this one. If you build your own mirror, mirror the instant, never the price.

**An instant outside a follower's coverage is an absence, not a gap.** `followerIndex` returns `null` before the first bar and after the last one under **both** `whenMissing` policies. Clamping to the edge bar instead asserts an alignment that does not exist, and looks convincing.

**Symbol sync does nothing without the host.** The engine has no instrument concept: nothing happens until a member has an `onSymbol` callback that loads bars, and until the host reports changes by emitting `'symbol'` or calling `group.setSymbol`. A member with no `onSymbol` broadcasts but never follows, which is the supported way to pin one chart.

**A freshly loaded follower must not broadcast its own `fitContent`.** Since 1.4.0 `fitContent`, `setVisibleLogicalRange`, `resetScale` and the keyboard pan/zoom commands all emit `pan`/`zoom`, so loading bars into a new member and fitting them throws the leader off the user's window. Suspend viewport sync across the load and let the two converge on the first pan.

See [chart-linking](./chart-linking.md).

## Trading

**`chart.trading` is a visualization layer: it draws lines and markers and emits `trading:*` events. It places no orders.** Your app owns the broker call. The order *write* path is `OrderEngine` in the trade tier.

**`TradingTrade.timestamp` is in milliseconds, the only ms-based time in the public API.** Everything else is UTC seconds. A seconds value here snaps every fill marker to the first bar.

**`OrderEngine` defaults to `armed: false` with no gate, so `placeOrder` silently resolves `{ ok: false, reason: 'not confirmed' }`.** Nothing throws and nothing reaches the broker. Supply `gate` (a confirm dialog) or `armed: true`. Separately, `mode` defaults to `'live'`, pass `mode: 'analyzer'` for the sandbox; arming and mode are independent switches.

**`requestModify` drops an invalid price instead of sending it, and reports only through `onValidationError`.** It is fire-and-forget: no throw, no rejected promise. Wire `onValidationError` or a rejected drag looks like a frozen line.

**`OpenAlgoTradeFeed.modify(orderId, ...)` rejects for any order it has not seen this session.** It reconstructs the full OpenAlgo payload from a cached context: `openalgo-charts: cannot modify <id>, unknown order context (place it or load the order book first)`. Also note `product` defaults to `'MIS'` and the wire renames `side->action`, `type->pricetype`, `qty->quantity`, and verify these field names against your running OpenAlgo build, because the adapters are tested offline against injectable transports, not against a pinned schema (README and `ARCHITECTURE.md` §13a are still accurate on this).

See [trading](./trading.md), [trade-tier](./trade-tier.md).

## Lifecycle and hosting

**`createChart` mutates your container.** It sets `display:flex`, `flexDirection:column`, `background`, `touchAction:none`, `role="application"`, `aria-label`, `tabindex`, forces `position:relative` when the computed position is `static`, and appends a hidden live region. Give the chart its own element rather than a shared layout node.

**`destroy()` removes listeners, panes, indicators and the live region, but does not undo those container style and ARIA mutations.** Under React StrictMode's double mount, or any remount into the same node, create the chart in an effect keyed to a dedicated `<div>` you own.

**Do not infer destruction from an empty pane list.** `chart.isDestroyed` and the `'destroy'` event say so directly. The event fires last, with the chart already torn down, so a listener is there to let go of the chart rather than to read it; `destroy()` is idempotent, so a second call emits nothing; and every listener is dropped afterwards, so a subscription on a corpse no longer retains its closure.

**The keyboard listener is attached to `document`, not the container, so a chart you forget to destroy keeps intercepting keys page-wide.** Scope defaults to `'hover'` (keys act when the pointer is over the chart or focus is inside it); `ShortcutManager.shouldIgnore` skips `INPUT`/`TEXTAREA`/`SELECT`/`contenteditable`.

**There is no SSR path, and the degradations are silent.** No `window` means no input handlers at all; no `ResizeObserver` means the chart never auto-resizes and you must call `chart.applySize(w, h)`. A missing 2D context throws `openalgo-charts: 2D canvas context is not available`. Construct the chart only in a client-side effect, and give the container explicit dimensions, the initial size is read from `container.clientWidth/clientHeight`, so a height-`auto` flex child renders at height 0 until the observer fires.

**The library default theme is `lightTheme`, despite the `ChartOptions.theme` JSDoc saying "pass `darkTheme` (default)".** `DEFAULT_THEME = lightTheme` in `src/theme.ts`; the doc comment is stale. Always pass a theme explicitly in a dark UI. A `background` of exactly `'transparent'` skips the fill entirely, which is what layered hosts want.

**The browser's native right-click "Save image as…" captures the clicked pane only.** Use `chart.takeScreenshot()` / `chart.downloadScreenshot()` for the full multi-pane composite; `downloadScreenshot` swallows failures (tainted canvas, no DOM) silently.

**A chart held in Vue's `ref()` or `reactive()` is a proxy, not the chart.** Registries keyed on the chart (replay window, picks, comparisons, alert and replay-group owners) see two different objects, and methods called through the proxy write wrapped objects into the chart's own records: replay started through a `ref()`-held widget leaves its order menu enabled, and a series added through the proxy answers `seriesType(series) === null` on the chart itself. Hold it in a `shallowRef` or `markRaw` it; the same goes for bar arrays, which `setData` stores as given. See [vue-integration](./vue-integration.md).

See [react-integration](./react-integration.md), [vue-integration](./vue-integration.md), [core-api](./core-api.md), [themes-and-styling](./themes-and-styling.md).

## Verify before answering

Never assume the version, an API name, or which tiers are loaded. Run these first; each pair covers a consumer app and an upstream checkout of this repo.

```bash
# 1. Which version is actually present
grep -m1 '"version"' node_modules/openalgo-charts/package.json   # consumer app
grep -m1 '"version"' package.json                                 # upstream checkout
# The exported VERSION / version() constant is hand-maintained and has drifted before; trust package.json.

# 2. Does the symbol exist in THIS build? Typings are ground truth.
grep -n "setPlacementMode\|legendOffset\|matchDrawingShortcut" node_modules/openalgo-charts/dist/index.d.ts
grep -n "setPlacementMode\|legendOffset\|matchDrawingShortcut" dist/index.d.ts

# 3. Which tier owns it (each tier has its own .d.ts)
ls node_modules/openalgo-charts/dist/*.d.ts node_modules/openalgo-charts/dist/*/index.d.ts
ls dist/*.d.ts dist/*/index.d.ts

# 4. Which tiers the user's source actually imports, and any illegal deep imports
grep -rn "openalgo-charts" src/ app/ components/ 2>/dev/null | grep -i "import\|require" | sort -u
# Anything matching openalgo-charts/dist/ or openalgo-charts/src/ is the duplicate-registry bug.

# 5. Enumerate what is registered at runtime, rather than trusting a docs list
#    registeredChartTypes(), registeredIndicators(), BUILTIN_DRAWING_TOOLS
grep -n "BUILTIN_INDICATORS\|BUILTIN_DRAWING_TOOLS" node_modules/openalgo-charts/dist/*/index.d.ts
```

On Windows PowerShell substitute `Select-String -Pattern` for `grep` and `Get-ChildItem` for `ls`.

If a symbol is absent from the local `.d.ts`, it does not exist in the installed version, say so and check `CHANGELOG.md` for the release that added it rather than writing code against it.

## A transformed series speaks two sets of bars

With `chart.setSeriesTransform` (or a widget chart type such as Renko), the series handle takes and returns the host's own bars: `getData()` is the raw history, not the bricks. What the chart draws, and what `chart.primaryBars()`, the crosshair, the readouts, `data:update` times and studies on `'chart'` bars see, is the elements. Index the view, a readout or a replay cut with `primaryBars()`, and feed updates with raw bars. Never hand a transformed series elements you prepared yourself: the chart transforms them again. A host that prepares its own elements picks the renderer alone, with `addSeries('point-figure')` or `setSeriesType`, which never transform.
