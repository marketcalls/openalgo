# Core API

*When to read this: you are creating a chart, adding or mutating series, wiring events, converting between data and pixels, or reasoning about when the chart repaints.*

Source of truth: `src/core/chart.ts`, `src/model/series.ts`, `src/index.ts`.

## First chart

```ts
import { createChart, darkTheme } from 'openalgo-charts';

const chart = createChart(document.getElementById('chart')!, { theme: darkTheme });

const series = chart.addSeries('candlestick');
series.setData([
  { time: 1700000000, open: 100, high: 104, low: 99, close: 103, volume: 1200 },
  { time: 1700003600, open: 103, high: 106, low: 102, close: 105, volume: 900 },
]);

chart.fitContent();
```

`createChart(container, options?)` returns a `Chart`; `new Chart(container, options?)` is equivalent and also exported.

**CSV data export.** `exportChartDataCsv(chart, options?: ChartDataCsvOptions)`
returns all installed primary bars as `time,open,high,low,close,volume,oi`, followed
by declared study plots and registered comparison closes. Time is UTC seconds;
missing/nonfinite readings are blank, zero remains zero and OI is never summed.
Repeated study columns include instance identity; hidden studies are included.
`indicators: false` or `[]` omits studies. An array of study instance IDs selects
those studies in the requested order. Duplicate, unknown or removed IDs throw;
use `IndicatorApi.id`, not a descriptor ID or displayed name. `range: { from, to }`
filters rows by inclusive UTC seconds after full-history calculation; either
finite boundary may be omitted. `ChartDataCsvRange` names these bounds; fractions
and negative timestamps are retained.
`comparisons` overrides the registered handles,
for example with an explicitly managed controller's `list()` or `[]` to omit them.
Comparisons retain original price units and their existing calendar/replay gaps.
Only the installed replay prefix is read; transforms retain installed OHLC and
study values precede visual plot offsets by default. `alignment: 'display'`
uses effective runtime study offsets on the shared axis, expands candle plots
into OHLC fields and adds `logical_index,time_origin` beside raw time. Primary
and comparison values stay on primary positions. Sparse projected rows contain
known study values, never future source observations. `projectTime` can override
outside-axis time labels using the frozen `ChartDataProjectionContext`; null
keeps a time unknown. Invalid or colliding positions/times throw. Time bounds
apply after shifting.
`ChartDataCsvFormatters` provides time, value and header callbacks. Time labels
add a column without replacing numeric time; only finite data values reach the
value callback. `ChartDataColumn` exposes frozen canonical key/source metadata.
All callbacks return strings; text is CSV-escaped and formula-protected. Snapshot
data is detached before callbacks, and callback exceptions abort the export.
This helper is DOM-free and does not
download, fetch or serialize trading state. See `docs/chart-data-export.md` for
the complete format and captured-source host guards.

**Rendering needs a measurable container.** A hidden chart may receive data before it has
width or height. Since 2.1.3, its initial default fit remains pending until the first
usable layout, including when `ResizeObserver` reveals the tab. Give the container a real
height; without `ResizeObserver`, call `applySize(width, height)` after showing it. Data
does not need to be loaded again.

**The chart takes over the container's inline styles.** It sets `display:flex`, `flexDirection:column`, `touchAction:none`, `background` from the theme, `position:relative` when the computed position is `static`, plus `role="application"`, `aria-label` and `tabindex`. It appends one `<div>` per pane and a visually-hidden live region.

## ChartOptions

| Key | Type | Default | Notes |
|---|---|---|---|
| `document` | `Document` | `container.ownerDocument` | Element factory (SSR / multi-window). |
| `pixelRatio` | `() => number` | `window.devicePixelRatio ?? 1` | Called per frame; canvases resize to media x dpr. Read again whenever the device ratio changes: the chart watches a `(resolution: Xdppx)` query, made again for each new ratio, and the window's `resize`, and re-sizes and repaints every canvas at once. |
| `raf` | `{ schedule, cancel? }` | `requestAnimationFrame` | Injectable frame scheduler (deterministic tests). Supplied, it runs every frame the chart paints, including the repaint after a resize or a new pixel ratio, which the default one paints at once inside the callback that reports it. Kinetic scroll and the eased wheel zoom are stepped inside those frames (since 2.5.8) and ask it for one frame per glide frame. |
| `theme` | `ChartTheme` | `DEFAULT_THEME` | See [themes-and-styling](themes-and-styling.md). |
| `priceAxisWidth` | `number` | `56` | Media px. Also the width reserved for a left axis when one exists. |
| `timeAxisHeight` | `number` | `22` | Media px, bottom pane only. |
| `timeScale` | `Partial<TimeScaleOptions>` | `DEFAULT_TIME_SCALE_OPTIONS` | Initial spacing, offset, and spacing limits. Added in 2.1.1; use live scale setters for spacing/offset changes. |
| `legendOffset` | `{ top?, left? }` | `{ top: 6, left: 8 }` | Where indicator legend rows start in the price pane, the top-most pane unless `movablePrimaryPane` let it move. |
| `priceOnlyAutoScale` | `boolean` | `false` | Fit the primary series' actual scale using only that series. Does not enable auto-fit. |
| `indicatorLegendCollapsed` | `boolean` | `false` | Suppress study legend rows while retaining plots and a count toggle. |
| `crosshairMode` | `'normal' \| 'magnet'` | `'normal'` | `magnet` snaps to O/H/L/C, price pane only, wherever it sits. |
| `now` | `() => number` | `performance.now` | Time source for kinetic pan / navigator fade. `WidgetOptions.now` is a different clock (the widget's wall clock, epoch milliseconds) and is not passed to the widget's chart. |
| `animZoom` | `boolean` | `true` | Ease a wheel zoom over a few frames instead of landing the whole step on one. Since 2.6.3 each wheel event moves one target bar spacing and every frame closes `1 - e^(-dt/70ms)` of the remaining distance in log space, by the real frame time: events between two frames never move the chart twice, every step eases (a trackpad's smallest included), and the speed is the same at 60Hz and 144Hz. A zoom that starts from rest moves on the event itself by what its first frame would have moved, so `barSpacing` has changed by the time anything reads it synchronously, and the zoom lands on exactly the single-frame result. **On by default**, which a 1.9.x host sees as a change; `false` restores the single-frame step. Not re-appliable. |
| `animAutoscale` | `boolean` | value of `animZoom` | Ease automatic price-range changes while navigation reveals new extrema. Manual and fixed scales remain authoritative. Programmatic viewport replacement, primary data replacement, reset and destruction cancel pending navigation motion. Not re-appliable. |
| `zoomAnchor` | `'cursor' \| 'right'` | `'cursor'` | What a wheel zoom holds still: the bar under the cursor, or the right edge (the latest bar), which a live chart usually wants. Not re-appliable. |
| `doubleClick` | `'reset' \| 'maximize' \| 'none'` | `'reset'` | Restore the configured default view and autoscale, toggle that pane to the whole stack, or only emit `dblclick`. A listener that sets `handled` on the event suppresses the action for that press. |
| `movablePrimaryPane` | `boolean` | `false` | Let the price pane leave slot 0: `movePane`, `setPrimaryPaneIndex`, a study pane's up control and a restored layout can put it below its studies. Off, the price pane is pinned at the top exactly as in 2.5.4 and earlier, so an explicit pane `0` always means the price. Turn it on only once the host stops passing `0` for the price pane. Not re-appliable; read it with `chart.movablePrimaryPane()`. See [scales-and-panes](scales-and-panes.md#moving-the-price-pane-opt-in). |
| `navigation` | `Partial<ChartNavigationOptions>` | `{ panEnabled: true, zoomEnabled: true, mousePan: 'both', defaultVisibleBars: 0 }` | Independent native user navigation, mouse/pen plot-pan direction and the initial/reset view. Touch retains two-axis panning. Use `setNavigationOptions` at runtime. |
| `conflate` | `boolean` | `true` | Level of detail for a zoomed-out chart. Under about one CSS px per bar (exactly one at a whole pixel ratio) the bars sharing a device-pixel column draw as one OHLC-preserving stick; lines keep each column's first, lowest, highest and last values and histograms its lowest and highest. Above that spacing nothing changes, and the default `timeScale.minBarSpacing: 1` never zooms out past it. `false` draws every bar at every zoom. See [data-and-time](data-and-time.md#level-of-detail-conflate). Not re-appliable. |
| `conflationFactor` | `number` | `1` | Column width in sticks: `2` merges into two-stick columns, from spacings under two CSS px. Not re-appliable. |
| `renderer` | `'canvas2d' \| 'webgl2' \| 'auto'` | `'canvas2d'` | Which backend paints the series. `'webgl2'` throws until `openalgo-charts/webgl` has been imported, and on a device without WebGL2 falls back to `canvas2d` with one console warning; `'auto'` takes `webgl2` when it is registered and works on this device, else `canvas2d`, silently. Decided once, at construction; read the result from `chart.rendererKind`. See [Render backends](#render-backends). |
| `renderBackend` | `RenderBackendFactory` | from `renderer` | Build the backend yourself, one call per pane, bypassing `renderer` and the registry. A factory that returns `null` gets the 2D backend for that pane. |
| `grid` | `Partial<GridOptions>` | `vertLines`/`horzLines` `true` | Visibility plus per-axis colour, dash, width and spacing. Unset colours fall through to the theme. |
| `canvas` | `CanvasOptions` | `{}` | Grid, crosshair, scale text/lines, plot margins in one block. See [settings-and-menus](settings-and-menus.md). |
| `statusLine` | `LegendStatusLineOptions` | all on | Per-field status-line switches applied to every pane legend. |
| `ariaLabel` | `string` | `'Interactive financial chart'` | |
| `shortcuts` | `ShortcutManager \| Partial<ShortcutManagerOptions> \| false` | built-in keymap | `false` disables keyboard control. |
| `priceFormatter` | `(price: number) => string` | tick-size-aware `toFixed` | Applies to each pane's **right** scale: axis labels, last-price tag, price-line labels. |
| `priceScale` | `Partial<PriceScaleOptions>` | `DEFAULT_PRICE_SCALE_OPTIONS` | Applied to each pane's **right** scale as the pane is created. See [scales-and-panes](scales-and-panes.md). |
| `timeFormatter` | `(utcSeconds, tickMark?) => string` | built-in labels in `timezone` | Time axis and crosshair time tag. Outranks `timezone` for labels. |
| `timezone` | `string` (IANA name) | `'Asia/Kolkata'` | Zone the axis, crosshair tag and calendar-anchored indicators resolve in. **Throws** on a name the runtime does not recognise. See [data-and-time](data-and-time.md). |
| `timeNavigator` | `boolean \| Partial<TimeNavigatorOptions>` | `true` | Hover-revealed zoom, reset and step controls above the time axis. |
| `axisChrome` | `AxisChromeOptions` | `{}` (nothing drawn) | `sessionClock` (corner clock in the chart's zone), `barCountdown` (second row in the last-price tag), and `clock`, a **wall-clock UTC seconds** source defaulting to the system clock. Not re-appliable through `applyOptions`; use `setAxisChromeOptions`. See [scales-and-panes](scales-and-panes.md). |

**`DEFAULT_THEME` is `lightTheme`, not `darkTheme`.** A dark shell must pass `{ theme: darkTheme }` explicitly even though the `theme` JSDoc says otherwise.

There is no `width`/`height` option; size comes from the container plus `applySize`.

## addSeries

```ts
const vol = chart.addSeries('histogram', {
  // No paneIndex: the price pane, wherever it sits.
  priceScaleId: '',                      // hidden overlay scale
  style: { color: '#33415e', base: 0 },
  priceFormat: { type: 'volume' },
});
```

`AddSeriesOptions`:

| Key | Type | Default | Notes |
|---|---|---|---|
| `paneIndex` | `number` | the price pane (`primaryPaneIndex()`) | Panes are created on demand; the first pane gets weight 1, later panes 0.32. |
| `style` | `SeriesStyle` | `{}` | Merged over the chart type's `defaultStyle`. See [chart-types](chart-types.md). |
| `priceScaleId` | `PriceScaleId` | `'right'` | Selects scale identity. `'right'` and `'left'` default to their named side; `''` and `overlay:name` default to hidden. `setPriceAxisPlacement` can expose or move any scale's column. |
| `priceFormat` | `PriceFormat`: `{ type: 'price', precision?, minMove? } \| { type: 'volume' } \| { type: 'percent', precision? } \| { type: 'custom', formatter }` | none | Applied to the series' *price scale*, not the series. `percent` suffixes the value at `precision` decimals (default 2) and does **not** scale it, so 0.62 reads `0.62%`. The type is exported as `PriceFormat`, and `IndicatorPlot.priceFormat` takes the same union. |

The first `addSeries` call whose type has `isPriceSeries: true` becomes the primary series: it drives the magnet crosshair, `CrosshairMoveEvent.bar`, the last-price line/tag, and the bars indicators compute from. Indicator-created series never claim it.

## SeriesApi

Returned by `addSeries`. Full surface (`src/model/series.ts`):

| Method | Signature | Notes |
|---|---|---|
| `setData` | `(items: readonly SeriesDataItem[], options?: BarConfirmationOptions) => void` | Historical replacement; forces full indicator calculation. The first non-empty call applies the configured default view once. |
| `prependData` | `(items: readonly SeriesDataItem[]) => void` | History paging; viewport is preserved. |
| `update` | `(item: SeriesDataItem, options?: SeriesUpdateOptions) => void` | Updates or appends. Older timestamps are historical corrections. |
| `getData` | `() => Bar[]` | Normalized OHLC, oldest first. |
| `applyOptions` | `(style: Partial<SeriesStyle>) => void` | Merge + repaint. **Not** `setStyle`. |
| `remove` | `() => void` | Detaches from the pane and frees its data rows. |
| `priceScale` | `() => PriceScale` | The live scale this series maps to. |
| `createMarkers` | `() => SeriesMarkers` | Markers layer bound to this series. |

Items are `{ time, open, high, low, close, volume?, color? }`, `{ time, value, color? }`, or `{ time }` (whitespace gap). See [data-and-time](data-and-time.md).

`BarConfirmationOptions.confirmation` is `'auto' | 'forming' | 'confirmed'`.
Explicit states override clock inference for the current tail. An omitted value
on a same-time update retains that state; `'auto'` clears it. Replacement data,
a new tail, or a changed instrument/timeframe clears the old state. Prepending
history retains an unchanged tail's state. Confirmation on an older correction
does not change the current tail. `SeriesUpdateOptions.source` is `'live'`
(default) or `'history'`; older corrections always count as history.

Native `SeriesDataState` contains readonly `sourceId`, `revision`, `historyRevision`,
`provenance`, `change`, and optional `confirmation`/`confirmationSource`. Custom
`IndicatorHost.sourceState()` implementations may supply this snapshot; hosts
without it retain their legacy inference. Source revisions count mutations,
while history revisions invalidate cached prefixes across coalesced updates.
`sourceId` identifies the source series within its chart/host, so replacing the
primary cannot reuse another series' calculation cache when revisions overlap.

`chart.setSeriesPriceScale(series, scaleId): boolean` reassigns a host-created
series to `'right'`, `'left'`, `''` or `overlay:name` on its current pane. Its
handle, data, styles, primary ownership and bound markers remain intact. Both
scale objects keep their settings, including manual ranges and ratio locks.
Explicit series `priceFormat` and style precision apply to the target as with
`addSeries`, affecting any other series sharing that target; the source scale's
formatting remains unchanged. The change updates axis columns, repaints and emits
one `objects:change` without replacing data or recalculating studies. It returns
false for an unchanged assignment, invalid ID, foreign or removed handle,
destroyed chart, or indicator-owned plot. Use the study's `setPriceScale` to move
its local resources together, or `setPlotPriceScales` for declared plots. See
[scales-and-panes](scales-and-panes.md#reassign-individual-study-plots).

`chart.setSeriesType(series, type): boolean` switches a registered renderer on a
live series. The handle, data, pane, price scale, primary ownership, explicit
styles and bound markers remain intact. Outgoing inherited renderer defaults are
removed and missing target defaults are applied, so switching a default step
series to a line removes the stepping while an explicit step style survives.
It repaints and emits `objects:change` without replacing data or recalculating
indicators. It returns false for the same type, foreign or removed handles, and
destroyed charts. An unknown type on a live owned series throws without mutation.
It never transforms data: `point-figure` and `kagi` draw the bars they are
given, which keeps a host that prepares its own elements working.

`chart.setSeriesTransform(series, spec | null): boolean` has the
chart apply a transform itself (Heikin Ashi, Renko, range bars, line break, point
and figure, Kagi, once `openalgo-charts/transform` is imported): the series
keeps taking the host's bars through `setData`, `update` and `prependData`,
`getData` returns them, and the chart draws the elements, formed again on every
tick. A new transform type selects its renderer. `chart.seriesTransform(series)`
reads the spec; `AddSeriesOptions.transform` sets one at creation. See
[transforms](transforms.md#in-chart-transforms).

`chart.seriesType(series): SeriesType | null` reads the current renderer for a
live owned series, including one that is not primary. It returns null for foreign
or removed handles and destroyed charts. Use it when a host tracks series types
that may also change through native chart calls.

`chart.seriesStyle(series): Readonly<SeriesStyle> | null` returns a frozen,
detached snapshot including current renderer defaults and direct style changes.
Read `barOffset` from this snapshot when aligning data with the rendered plot;
the descriptor's original offset may have been overridden. An omitted offset
means zero. Old snapshots do not change after `applyOptions`. Foreign or removed
handles and destroyed charts return null.

## Requested bar providers

`ChartOptions.barsProvider` and `chart.setBarsProvider(provider | null)` accept
the existing `IndicatorBarsProvider` function or an `IndicatorBarsProviderAccess`
object with `requestBars` and optional `requestSnapshot`. The chart owns no
transport. `hasBarsProvider()` tests registration; `hasSnapshotProvider()` tests
the explicit snapshot capability. Replacing or removing a provider cancels its
outstanding requests and announces the new provider revision. Setting the same
provider object again is a no-op; call `invalidateRequestedData()` when that
provider has new observations, value versions or confirmation metadata.

```ts
chart.setBarsProvider({
  requestBars: request => history.loadBars(request),
  requestSnapshot: request => history.loadSnapshot(request),
});
chart.invalidateRequestedData();
```

`IndicatorBarsRequest` contains `symbol`, optional `exchange`, `interval`,
opening-time bounds `from`/`to` in UTC seconds, and optional `signal`.
`IndicatorSnapshotRequest` adds optional `asOf`, the inclusive historical
knowledge cutoff. `RequestedBarsSnapshot`, exported from both base and indicators,
contains equally sized `bars`, `availableAt: (number | null)[]` and
`confirmed: boolean[]`. Openings must be finite and strictly increasing;
availability is null for unknown or a finite time at or after opening.
Confirmation is explicit, independent of the interval or the next observation.

An attach context exposes `requestBars`, `requestSnapshot`, `requestState()` and
`subscribeRequestChanges(listener)`. `IndicatorRequestState` includes optional
native source provenance, `providerRevision`, `dataRevision`, `supportsSnapshots`
and optional `replay: { time, asOf?, forming }`. Read it at request time. The
subscription observes source changes, provider replacement, requested-data
invalidation and replay clock movement even within one source observation; its
return value unsubscribes. These revisions identify data generations, not a
count of calculation executions.

Requests compose caller, instance-lifetime and chart-provider cancellation.
Consumers must also prevent a late completion from publishing into a newer
generation; the indicators tier's `createRequestedIndicator` manages that
lifecycle. A provider should honor the signal to release its own work.

Availability-aware replay clamps a snapshot request's `asOf` to the replay clock.
The provider must return point-in-time value versions or reject an unsupported
cutoff; filtering today's final bars by timestamp cannot recover those versions.
Strict snapshot requests reject legacy replay without an `asOf` clock. Existing
raw `requestBars` behavior is unchanged. See [indicators](indicators.md#managed-requested-snapshots).

## Whole-study scale assignment

```ts
const study = chart.addIndicator('rsi', { period: 14 }, { priceScaleId: 'left' });
study.priceScaleId();                    // 'left', or null for descriptor defaults
study.setPriceScale('overlay:momentum');  // true when the assignment changes
study.setPriceScale(null);               // restore each descriptor assignment
```

`chart.addIndicator(id, settings?, { paneIndex?, priceScaleId?, plotPriceScaleIds? })` returns
`IndicatorApi`. Its scale override moves local plots, fills, levels, drawings and
attached price primitives together. Plot-bound markers follow their series;
explicit price-pane overlays keep their effective scales. Screen-space tables and
background shading retain their placement. Invalid, unchanged or removed requests
return false; incompatible fill endpoints also reject the whole move.

The move preserves plot handles, data and lifecycle attachments, updates legend
formatting and axis columns, and emits one `objects:change` without recalculation.
Native plot renderer changes through `setSettings({ 'plotKey:type': 'area' })`
also retain the plot handle, scale and marker binding. Transform data stays
host-owned. A successful `setPriceScale`, including null, clears local per-plot
overrides and retains explicit price-overlay overrides. `IndicatorState.priceScaleId`
stores the whole-study override and `plotPriceScaleIds` stores explicit plot
overrides. Omission restores descriptor defaults. See [scales-and-panes](scales-and-panes.md#reassign-a-whole-study)
for shared formatting, fixed-range ownership and saved scales.
`movePriceAxis` (deprecated, removed in 3.0.0: use `setPriceAxisPlacement`) refuses
mixed local study assignments and explicit price overlays;
its `priceAxisState().movable` result (deprecated with it) reflects that conservative legacy-operation
limit, even though saved state can represent mixed plot assignments. Uniform local and
primitive-only studies adopt a successful whole-axis move. `setPriceScale` remains
the operation for moving all local study resources while keeping overlays fixed.

### Per-plot scale assignment

`study.plotPriceScaleId(plotKey)` reads a declared plot's effective `PriceScaleId`,
or null for an unknown key. `study.plotPriceScaleIds()` returns a detached map of
explicit overrides. `study.setPlotPriceScales(patch)` applies a partial
`Readonly<Record<string, PriceScaleId | null>>` atomically; null clears one
override. Unknown keys, invalid IDs, accessor properties, empty/unchanged patches
and incompatible fill endpoints return false without moving resources.

Precedence is per-plot override, local whole-study override, descriptor scale,
then `right`. Explicit `overlay: true` plots ignore the whole-study override but
accept per-plot assignments on the price pane. Move both endpoints of a fill in
one patch so they retain the same pane and scale. Levels and unbound price
drawings follow the first local plot; plot-bound markers follow their series.

Creation's `plotPriceScaleIds` map accepts scale IDs, with omission meaning no
overrides. Invalid maps or conflicting fills throw before chart resources are
allocated. Chart restore validates known descriptors before mutation; workspace
and legacy template parsing retain structurally valid maps for later validation.

## Lifecycle and sizing

- `chart.destroy()`: the only teardown method. **There is no `chart.remove()`.** It stops the render loop and kinetic animation, removes every indicator, disconnects the `ResizeObserver`, unbinds all pointer/wheel/keyboard listeners, destroys every pane, and clears the container's cursor hint.
- `chart.applySize(width, height)`: media px; no-ops when unchanged. A `ResizeObserver` on the container calls it automatically, so manual calls are only needed in hosts without `ResizeObserver`. The chart paints inside that observer's callback, which runs after the frame's animation callbacks and before the browser paints, so a resize never shows a cleared canvas for a frame.
- **Device pixels.** Pane boundaries land on whole device pixels: every boundary between panes is rounded onto one (within half a device pixel of its weighted share; the outer edge stays the container's), at the ratio the panes were laid out at, so each canvas covers whole device pixels, and where the browser reports a canvas's `devicePixelContentBoxSize` (Chromium, Firefox) the backing store takes exactly that size. At a whole-number ratio (1, 2, 3) the separator between panes is the pane's 1 px top border, the canvases starting under it, as in every earlier release; a chart whose panes share the height in whole pixels is laid out and painted exactly as before. At a fractional ratio (1.25, 1.5) it is a box one device pixel tall laid over the lower pane's first row, the canvases starting at the pane's own top. A pane's height can differ from its exact weighted share by up to one device pixel. `exportSVG` lays panes out at ratio 1 on every screen.
- `chart.applyOptions(opts: ChartApplyOptions)` takes a runtime subset only: `theme`, `grid`, `canvas`, `statusLine`, `legendIconSize`, `priceScale`, `priceFormatter`, `timeFormatter`, `timezone`, `crosshairMode`, `crosshairSnapToBar`. Nothing else from `ChartOptions` is re-appliable. `ChartApplyOptions` is the exported name of that shape (since 2.6.0).

## Object inventory and management

Use the base-tier `ChartObjects` for a custom host's Objects list. It creates no DOM
and imports no optional tier. A widget already owns one at `widget.objects`; its
`openObjects()` and reusable `mountObjectsPanel` are in the
[widget tier](widget.md#objects-panel).

```ts
import { ChartObjects } from 'openalgo-charts';

const objects = new ChartObjects(chart, {
  drawings: draw, // optional structural DrawingController from openalgo-charts/draw
  onSettings: row => openExistingEditor(row.kind, row.sourceId),
});
const off = objects.subscribe(rows => renderInventory(rows));
const drawing = objects.list().find(row => row.kind === 'drawing');
if (drawing?.capabilities.lock) objects.setLocked(drawing.id, true);

off();
objects.destroy(); // releases observers, not the chart or its objects
```

`ChartObjectsOptions` contains optional `drawings: ChartObjectDrawingSource`,
`onSettings(object: ChartObjectSnapshot)` and, since 2.5.10, `drawingName(tool)`,
which names a drawing row (pass the draw registry's `getDrawingTool(tool).name`;
without it the row is named from the tool id, "Trend line"). `ChartObjectDrawingSource` describes
`drawings`, `get`, `selection`, `select`, `update`, `remove` and an optional `removeMany`; the draw tier's
`DrawingController` satisfies it. `ChartObjectDrawing` is the structural record
with `id`, `tool`, `paneIndex`, `points: { time, price }[]`, optional `visible`, `locked`
and `policy`. The inventory honours the drawing policy (see
[drawing policies](drawing-tools.md#drawing-policies)): `listed: false` leaves the
drawing out of the list and out of its group's row, `selectable: false` withholds
`select`, and `editable: false` withholds `visibility`, `lock` and `remove`, for the
drawing and for any group holding it. A group that holds an unlisted drawing removes
only its listed members (through `removeMany`, one undo step), and `ungroup` refuses it.
The optional `hiddenOnInterval()` lists the drawings whose interval range leaves out
the chart's interval, asked once per refresh; each keeps its row with
`hiddenOnInterval: true` (a group row too, when every member is left out) and offers no
`focus`, while `visible` stays the user's switch (see Visibility per interval in
[drawing tools](drawing-tools.md)).

`ChartObjectSnapshot` is immutable: `{ id, sourceId, kind, name, paneIndex, visible,
selected, locked?, dataStatus?, capabilities }`. `ChartObjectKind` is
`'source' | 'indicator' | 'drawing' | 'profile'`. `ChartObjectCapabilities` contains
boolean `select`, `visibility`, `lock`, `remove`, `settings`, `focus`. `paneIndex` is
zero-based; the widget displays pane numbers starting at 1 and names the price pane
**Price pane** wherever it sits, read from `objects.primaryPaneIndex()`. `dataStatus` uses
`IndicatorDataStatus`, including loading, ready, empty, unsupported and error.

| Method | Contract |
|---|---|
| `list()` / `get(id)` | Current immutable rows / one row or `undefined`; reads also refresh unsignalled host state. |
| `subscribe(listener)` | Immediately supplies current rows, then inventory changes; returns an unsubscribe function. |
| `select(id: string \| null, additive = false)` | Selects an object, or clears selection with `null`. Additive selection applies to drawings. |
| `setVisible(id, on)` / `setLocked(id, on)` | Delegates to the owning subsystem when the capability exists. |
| `remove(id)` / `openSettings(id)` / `focus(id)` | Delegates the supported action. |
| `register(provider)` | Adds explicit host-owned state; returns idempotent registration cleanup. |
| `stack(paneIndex)` | The pane's stack rows in draw order, back to front (see Draw order below). |
| `canPlace(id, targetId, where)` / `place(id, targetId, where)` | Whether a row can move directly `'above'` or `'below'` another row of its pane's stack, and the move. `false` for a move the bands cannot paint or one that changes nothing. |
| `refresh()` | Re-reads provider state without polling. |
| `paneCount()` / `primaryPaneIndex()` | The pane count (a move target list adds one new pane after it) and the price pane's slot, so a list can name the price pane in any slot. |
| `destroy()` | Releases chart/provider observations without deleting objects; idempotent. |

All six action methods return `false` for missing, unsupported or failed actions.
The primary price row, `source:primary`, is protected: it offers only settings when
`onSettings` exists. Indicator rows use `indicator:<instanceId>`, drawings use
`drawing:<drawingId>`. Pass the snapshot's `id` to inventory actions, and `sourceId`
to existing editors. Drawing selection follows the canvas. Drawing visibility,
lock and removal delegate to the controller, preserving its undo history; focus
brings anchors, including future anchors, into view and sets the pane price range
to manual. Indicator removal releases its data lifecycle and removes an empty pane.

Profiles require explicit registration. Arbitrary primitives and trading overlays
do not automatically become removable objects. `ChartObjectProvider` takes `id`,
`get(): ChartObjectDefinition | null`, optional `subscribe(listener): () => void`,
and optional synchronous `select`, `setVisible(on)`, `setLocked(on)`, `remove`,
`openSettings`, `focus` callbacks. Only supplied callbacks enable capabilities.
`ChartObjectDefinition` contains `kind`, `name`, and optional `paneIndex`, `visible`,
`locked`, `selected`, `dataStatus`. Return `null` when the object does not exist.

```ts
let visible = true;
let exists = true;
const unregister = objects.register({
  id: 'session-profile',
  get: () => exists ? { kind: 'profile', name: 'Session profile', visible } : null,
  setVisible(on) {
    if (on === visible) return;
    visible = on;
    if (on) chart.addPrimitive(profile); else chart.removePrimitive(profile);
  },
  remove() { chart.removePrimitive(profile); exists = false; },
});
```

This assumes `profile` is already attached. The provider offers visibility and
removal, with no fabricated lock, focus or settings controls. Provider IDs become
`custom:<id>`, so they cannot shadow built-ins; empty or duplicate IDs throw.
Registration cleanup stops observation and removes the row, leaving primitive
teardown to the host. Call `objects.refresh()` after host-side state changes, or
notify through the provider's subscription. Provider definitions, callbacks and
state are not serialized in chart layouts. See
[events and state](events-and-state.md#object-inventory-lifecycle) for observation
and indicator visibility persistence.

## Viewport

```ts
const range = chart.getVisibleLogicalRange();  // { from, to } fractional bar indices
mainSeries.setData(fullHistory);
chart.setVisibleLogicalRange(range);           // restore the user's zoom
```

- `chart.fitContent()`: fit all bars; no-op on an empty chart.
- `chart.resetScale()`: restore `navigation.defaultVisibleBars` **and** re-enable autoscale and release ratio locks on every right, left and overlay price scale. This is what the navigator reset button, `Home` / `0`, and the default double-click action run.
- `chart.timeScale`: the live `TimeScale`; mutating it repaints via an injected change handler.

**A logical range is meaningless before data lands.** `setVisibleLogicalRange` indexes bars, so apply it after `setData`, not before.

### ChartNavigationOptions

Exported from `openalgo-charts`:

```ts
interface ChartNavigationOptions {
  panEnabled?: boolean;
  zoomEnabled?: boolean;
  mousePan: 'horizontal' | 'both';
  defaultVisibleBars: number;
  defaultBarSpacing?: number;
}

const chart = createChart(el, {
  navigation: { mousePan: 'both', defaultVisibleBars: 120 },
});
chart.navigationOptions();  // Readonly<ChartNavigationOptions>
chart.setNavigationOptions({ defaultVisibleBars: 80 });  // Partial<ChartNavigationOptions>, returns void
```

`mousePan` defaults to `'both'`: mouse and pen plot drags move time and price.
Choose `'horizontal'` to move only time while preserving price autoscale.
Touch retains two-axis panning for either value.

`panEnabled` and `zoomEnabled` default to `true` independently. Pan controls plot
translation, horizontal/shift wheel, pinch translation, keyboard steps and
momentum. Zoom controls ordinary/control wheel, axis drags and wheels, pinch
scaling, zoom keys and user reset/fit actions. Disabled native navigator actions
are hidden. Turning an action off cancels its active motion; enabling it again
does not resume the cancelled pointer sequence. Rejected wheel input remains
available to the page. Crosshair, selections, drawings and chart picks remain
usable. Programmatic scale setters, `fitContent`, `resetScale`, linked charts,
data updates and state restoration remain available.

Both fields accept own boolean data properties. Missing, inherited, accessor
or malformed values are ignored without invoking a getter; unchanged patches
do not interrupt motion. Old state without these keys retains the current policy.

`defaultVisibleBars` defaults to `0`, fitting all loaded bars. A positive count targets
the newest N loaded bars plus four empty slots on the right, bounded by available data
and the time scale's spacing limits. Initial data loads and `resetScale()` honour this
count; changing it applies the default view immediately. `fitContent()` still explicitly
fits all loaded bars. The count does not change history requests or discard loaded data.
Apply a host's custom viewport after loading data when it should take precedence. The
widget's ordinary load views use the configured count.

The Axes / Navigation settings fields include `navigation.panEnabled`,
`navigation.zoomEnabled`, `navigation.mousePan` and
`navigation.defaultVisibleBars`, plus `navigation.defaultBarSpacing`. They round-trip through `readChartSettings` /
`applyChartSettings` and the optional `navigation` block in `getState` / `restoreState`.

Set `defaultBarSpacing` to a positive CSS pixel value for consistent candle density
across screen widths. It takes precedence over the count for initial loads and reset.
Zero disables the spacing preference. A count-only edit selects count mode again.
Resizing preserves the current zoom, and explicit `fitContent()` still fits all history.
The widget defaults to 8 CSS pixels per bar unless a count or spacing is supplied.

## Coordinates

| Method | Direction | Notes |
|---|---|---|
| `timeToCoordinate(time)` | UTC seconds -> container x, media px | Interpolates and extrapolates past the right edge. |
| `coordinateToTime(x)` | container x -> UTC seconds | |
| `priceToCoordinate(price, paneIndex = primaryPaneIndex())` | price -> container y, media px \| `null` | `null` when the pane does not exist or is collapsed to its header strip (`setPaneCollapsed`), which plots no price. Uses the pane's **readout** scale, which is the one its first visible price series maps to, so it is right on a pane whose axis was moved to the left strip. |
| `coordinateToPrice(y, paneIndex = primaryPaneIndex())` | container y -> price \| `null` | Same scale, and `null` on the same panes. |

Both price conversions force an autoscale pass first, so they are correct before the first paint.

## Formatters

```ts
chart.setPriceFormatter((p) => 'Rs ' + p.toFixed(2)); // every pane's right scale
chart.setPriceFormatter(null);                        // back to tick-size default
chart.setTimeFormatter((s) => new Date(s * 1000).toISOString().slice(11, 16));
chart.setTimeFormatter(undefined);                    // back to the built-in labels
chart.setTimezone('America/New_York');                // which zone those labels are in
chart.timezone();                                     // read it back
```

Per-series formatting goes through `addSeries({ priceFormat })` or `series.priceScale().setPriceFormatter(fn)`.

**`setTimezone` is not only a relabelling.** It also recomputes every calendar-anchored indicator (VWAP, TWAP, CPR, Seasonality), because moving the calendar moves where a session, week or month starts. It throws on a name the runtime does not recognise, so validate with `isValidTimezone(zone)` first if the name comes from user input. The default is `'Asia/Kolkata'`; a chart that sets no zone labels exactly as it always did. See [data-and-time](data-and-time.md).

## Screenshots and vector export

`chart.takeScreenshot(): HTMLCanvasElement` composites every pane's base + top canvas onto one opaque canvas at device resolution. `chart.downloadScreenshot(filename = 'chart.png')` does that and triggers a PNG download. Use these instead of the browser's native "Save image", which only captures the transparent overlay layer.

`chart.exportSVG(options?: ExportSvgOptions): string` is the same frame written as a standalone SVG document: every pane's base and top paint in DOM order, at pixel ratio 1, with axis labels and tags as `<text>` and no crosshair, hover or drag state. `ExportSvgOptions` takes `width` and `height` (media px; absent means the live size, and a different size lays the chart out for the export and puts the live layout back without a blank frame), `background` (default `true`; `false` leaves the document transparent for an embedded figure) and `dpr`, which only accepts `1` and throws on anything else. Saving is the host's job: `new Blob([svg], { type: 'image/svg+xml' })` and an anchor.

The serialiser behind it, `SvgContext`, is exported (with `SvgLinearGradient` and `SvgContextOptions`) so a host can run its own primitive or a bare renderer into one: construct it at the document size, pass `asCanvasContext()` to whatever paints, read `toString()`. Calls with no vector form (`setTransform`, radial gradients, `Path2D`, image data) throw with `strict: true` and are otherwise listed in `unsupported` and skipped; `measureText` is approximate (a per-character width table), which the tag boxes and label culling tolerate.

## Events

Two surfaces. The typed `subscribe*` helpers, and the string bus.

```ts
chart.subscribeClick((externalId) => { /* hit-tested primitives only */ });
chart.subscribeCrosshairMove((e) => { /* CrosshairMoveEvent */ });
chart.subscribeDrag(
  (id, price, time) => { /* per move */ },
  (id, price, time) => { /* on release */ },
);
```

**The `subscribe*` helpers take several subscribers and each call returns its unsubscribe** (since 2.6.0; before, each stored one callback, a second call replaced the first, and they returned `void`). The bus is the other surface: `chart.on(name, cb)` returns an unsubscribe function and types `cb`'s payload by the name (`ChartEventMap`); `chart.once` and `chart.off(name, cb?)` are also public, and `chart.emit(name, payload)` is deprecated (removed in 3.0.0). See [events-and-state](events-and-state.md).

Core event names: `ready`, `crosshair:move`, `click`, `hover`, `drag`, `drag:end`, `pan`, `zoom`, `resize`, `dblclick`, `contextmenu`, `lazy-load`, `paneResized`, `paneMoved`, `paneMaximized`, `paneCollapsed`, `paneRemoved`, `indicatorRemoved`, `indicatorSettings`. `ReplayController` adds `replay:start|frame|play|pause|end|stop`, and the trading tier routes `trading:*` through the same bus. See [events-and-state](events-and-state.md).

`CrosshairMoveEvent`: `time: number | null`, `index: number | null`, `price: number | null`, `bar: Bar | null`, `point: { x, y } | null`, `paneIndex?: number | null`, and on a move (not the all-null leave payload) `pressed: boolean`, `modifiers: PointerModifiers` (`{ shift, alt, ctrl, meta }`), `pointerType: PointerKind` (`'mouse' | 'touch' | 'pen'`), `pressure` (0..1 as the pointer events spec defines it: measured, else 0.5 while a button is held, else 0) and, only while pressed, `samples: PointerSample[]` (`{ x, y, pressure }` per coalesced position, container x and pane-local y). The same three pointer facts (`PointerInfo`) ride on `ChartClickEvent`, `ChartDragEvent` (which adds `point` and `samples`) and `ChartDragEndEvent` (which adds `point` and also describes `drag:start`); all seven types are exported from the base entry.

Two pure helpers from the input and render layers are exported for a host that wants the same feel outside the chart: `ZoomGlide` (with `DEFAULT_ZOOM_GLIDE_OPTIONS`, a `ZoomGlideOptions`) is a closed-form exponential approach in log space for a host that eases one zoom step outside the chart (the chart itself chases a moving target per frame since 2.6.3, and uses `ZoomGlide.leadFraction` for its first-frame lead); `candleTier(bodyW, wickW, style)` says whether a candle this narrow still shows a body (`'full'`) or only its wick (`'wick'`), which the candle renderer uses to skip a body the wick has already painted, and which a custom renderer can use to draw the same pixels.

## History paging

```ts
chart.setHistoryLoader(async () => {
  const older = await fetchOlderBars();
  series.prependData(older);
  chart.historyLoadComplete();   // re-arms the trigger
});
```

Fires when the visible range's `from` drops below logical index 10, and re-fires only after
`historyLoadComplete()`. A `lazy-load` event with `{ from, to, direction: 'backward' }` is
emitted alongside. A custom async loader owns error handling, replay gating and stale
request checks; see [host-integration](host-integration.md).

## Panes and primitives

`chart.panes(): readonly Pane[]` exposes the live panes (each with `.priceScale`, `.weight`, `.series()`, `.primitives()`, `.base`, `.top`). Pane management lives in [scales-and-panes](scales-and-panes.md); `chart.addPrimitive(primitive, paneIndex?)` (the price pane when none is named) and `chart.removePrimitive(primitive)` in [primitives-and-plugins](primitives-and-plugins.md).

`chart.getState()` / `chart.restoreState(state)` serialise viewport, grid, crosshair mode, timezone, pane weights and price scales, indicators, the settings block (canvas, navigation, status line, trading colours, event filters), and an opaque `drawings` slot. **Series data is never captured**: `restoreState` returns a `RestoreReport` listing series descriptors for the host to rebuild. Navigation options restore before the saved viewport, so its explicit range wins; an older state without `navigation` keeps the chart's current navigation options.

### Multiple price-axis columns

Scale identity and placement are independent. Keep a source on `overlay:spread`
while exposing its axis beside the main price axis:

```ts
const spread = chart.addSeries('line', { priceScaleId: 'overlay:spread' });
spread.setData(spreadPoints);
chart.setPriceAxisPlacement(0, 'overlay:spread', 'right');
chart.setPriceAxisPlacement(0, 'overlay:spread', 'left', 0);
chart.setPriceAxisPlacement(0, 'overlay:spread', 'hidden');
```

| Method | Result | Contract |
|---|---|---|
| `priceAxisPlacement(paneIndex, scaleId)` | `PriceAxisPlacement \| null` | Detached `{ side, order }`; reads placement even when the scale has no active column. |
| `setPriceAxisPlacement(paneIndex, scaleId, side, order?)` | `boolean` | Places an axis on `'left'`, `'right'` or `'hidden'`. Invalid and unchanged requests return false before mutation. |
| `priceAxisLayout(paneIndex = primaryPaneIndex())` | `readonly PriceAxisSlot[]` | Active columns with `{ scaleId, side, order, x, width }`. `x` is the column's left edge in absolute pane CSS pixels; width is one column. |

Order zero is nearest the plot. An explicit order is a nonnegative safe integer,
clamped to the side's available ranks. Omitting it retains the rank on the same
side and appends when changing sides. Placement preserves the scale object,
range, formatter, ratio lock, series and study IDs, markers and alert anchors.
The getter returns null for an invalid ID, missing pane or destroyed chart;
layout returns an empty array for a missing pane or destroyed chart. Successful
changes emit `priceAxisPlacementChanged` with `{ paneIndex, scaleId, side, order }`
and `objects:change`.
`movePriceAxis` retains its legacy resource reassignment behavior and is
deprecated, removed in 3.0.0; use placement to move a column while preserving IDs.

Attached series, including hidden series, and explicitly bound primitives occupy
columns. An unused configured scale retains placement but reserves no width.
Hidden scales draw no column or axis tags. Panes share the maximum column count
on each side, pack their own columns inward, and leave unused outer cells without
price input targets. Narrow charts reduce column widths equally to retain plot
space. The primary crosshair price remains on the primary source's scale.

`PriceAxisSide`, `PriceAxisPlacement` and `PriceAxisSlot` are base exports.
Full chart/workspace snapshots retain optional `PriceScaleState.placement`;
omission restores default placement. Indicator templates retain scale IDs but
do not yet preserve pane column placement.

## Option accessors

Beyond `applyOptions`, the chart reads and writes its own option blocks so a settings dialog has something to bind to: `setCanvasOptions` / `canvasOptions`, `setNavigationOptions` / `navigationOptions`, `setGridOptions` / `gridOptions`, `setStatusLineOptions` / `statusLineOptions`, `setPriceScaleOptions` / `priceScaleOptions` (the price pane's own scale) / `priceScaleDefaults` (the chart-wide defaults a new pane starts from, which a one-axis change leaves alone), `setAutoScale`, `setAxisChromeOptions` / `axisChromeOptions`, `setEvents` / `setEventOptions` / `eventOptions`, `tradingSettings` / `setTradingSettings`, `primarySeries` / `primarySeriesInfo`, `theme`, `crosshairMode`, `setTimezone` / `timezone`. One axis at a time there is `priceAxisState`, `setPriceAxisOptions`, `setPriceAxisAutoFit`, `setPriceAxisLockRatio`, `priceAxisPlacement`, `setPriceAxisPlacement`, `priceAxisLayout` and the deprecated `movePriceAxis`. Each of these setters that has no event of its own is followed by `layout:change` (see [events-and-state](events-and-state.md)). `chart.setSessionCalendar(calendar)` sets the trading hours the axis follows past the last bar and repaints; see [data-and-time](data-and-time.md). The declarative schema over the settings is in [settings-and-menus](settings-and-menus.md).

## Render model

Each pane owns two stacked canvases: `pane.base` (z-index 0: background, grid, series, axes, bottom/normal primitives) and `pane.top` (z-index 1: top primitives and the crosshair). Both are sized media x `dpr`; all drawing happens in device-pixel scope.

`chart.invalidate((mask) => ...)` folds work into a single pending `InvalidateMask` and asks the `RenderLoop` for a frame; repeated requests inside one tick coalesce into one `rAF` callback. `InvalidationLevel` (exported):

| Level | Value | Work done |
|---|---|---|
| `None` | 0 | Nothing. |
| `Cursor` | 1 | Repaint the top canvas only. |
| `Light` | 2 | Repaint the base canvas at current scales, no rescale. |
| `Full` | 3 | Autoscale every price scale, then repaint everything. |

The effective level per pane is `max(globalLevel, paneLevel)`. Crosshair moves raise `Cursor` globally; hover changes raise `Light` globally; a primitive's `requestUpdate` raises `Light` on its pane only; pan, zoom, resize, theme and grid changes raise `Full` globally. A data write raises `Full` (with an autoscale) on the panes whose data it changed when it leaves the shared index and the time scale's window where they were, and globally when it moves them (since 2.5.8): a tick that replaces the forming bar repaints its series' pane, and a study recompute the panes its output lands on, while an appended bar, a host `setData` or `prependData` and a study that opens a pane repaint every pane. While `axisChrome.sessionClock` is on such a pane-scoped write also raises `Light` on the bottom pane, and while `axisChrome.barCountdown` is on, on every pane with a price series, because neither reading has a timer.

**Every `series.update()` schedules a `Full` repaint** of the panes it changes. A high-frequency feed therefore re-autoscales those panes each frame; batch ticks upstream (see [feeds-and-live](feeds-and-live.md)) rather than calling `update` per tick.

## Render backends

The per-frame series pass on each pane goes through an `IRenderBackend` (`src/render/backend.ts`). The pane paints everything else (background, grid, axes, primitives) on the 2D context the backend hands back from `overlay2d()`, so a backend only has to own the one pass that maps onto a batch of GPU geometry. How the two backends compare in frame time has not been measured. `Canvas2dBackend` ships in the base tier, registers itself under `'canvas2d'`, and draws through the very same 2D context the pane already holds, so its op stream is byte for byte the one every chart drew before the port existed (`tests/e2e/render-parity.spec.ts` holds it to zero differing pixels).

```ts
interface IRenderBackend {
  readonly kind: RenderBackendKind;                       // 'canvas2d' | 'webgl2'
  readonly device?: RenderDevice;                         // { available, lost }; a GPU backend only
  mount(canvas: HTMLCanvasElement, ctx2d: CanvasRenderingContext2D | null): void;
  resize(widthPx: number, heightPx: number, dpr: number): void;
  beginFrame(clear: boolean): void;
  drawSeries(entry, items, priceToY, barSpacing, dpr, style, rc): void;  // RendererEntry.draw minus the context
  endFrame(): void;
  overlay2d(): CanvasRenderingContext2D | null;
  destroy(): void;
}
```

The `items` array `drawSeries` receives, and the objects in it, belong to the pane (since 2.5.8): the pane reuses them and rewrites them in place the next time it draws that series, so a backend that keeps them past the call must copy them. `priceToY` is one stable function per series. Under the level of detail (`conflate`, on by default) a built-in type's items are one merged stick or a few kept bars per device-pixel column, not every bar.

`mount` takes the pane's existing 2D context as its second argument (the pane's base `CanvasLayer` already asked the canvas for one; a second `getContext` would split a frame across two contexts). A backend that owns its canvas ignores it.

Choosing one: `chart.rendererKind` (a `RenderBackendKind`; the deprecated `chart.renderer`, removed in 3.0.0, is the same value under the name it first shipped with) reports what the chart actually paints with. It differs from the `renderer` option when the chosen factory declined (no WebGL2 on this device) and the 2D backend stood in, and from the moment a GPU backend degrades (see the fallback below). The registry behind the option is exported for a tier or host that brings a backend:

| Export | What it does |
|---|---|
| `registerRenderBackend(kind, factory)` | Register or replace the factory for a `RenderBackendKind`. `RenderBackendFactory` is `() => IRenderBackend \| null`; returning `null` declines at run time. |
| `unregisterRenderBackend(kind)` | Drop a registered backend. Refuses `'canvas2d'`, the fallback every other choice lands on. |
| `registeredRenderBackends()` | The kinds currently registered. |
| `resolveRenderBackend(choice?: RendererChoice)` | Turn the option into a factory: an unregistered explicit kind throws, a factory that declines falls back to `canvas2d`. |
| `createRenderBackend(choice?)` | One backend instance for the choice, via `resolveRenderBackend`. |
| `backendDegradation(backend)` | `RendererFallbackReason \| null`: `'context-lost'` while a GPU backend's context is away, `'unavailable'` when its device never came up (the program failed to compile on a live context), `null` for a healthy backend and always for `canvas2d`. What the chart polls after each frame. |

The export path bypasses the backend: `exportSVG` calls each renderer's `draw` directly on the serialising context, because a document has no pixels to take from a GPU. `candleGeometry` in [chart-types](chart-types.md#renderer-geometry) is the shared snapping source a second backend must reproduce.

### The WebGL2 tier (`openalgo-charts/webgl`)

```ts
import { createChart } from 'openalgo-charts';
import 'openalgo-charts/webgl';                 // registers the 'webgl2' backend

const chart = createChart(el, { renderer: 'auto' });
chart.rendererKind;                             // 'webgl2' where WebGL2 works, else 'canvas2d'
chart.on('renderer:fallback', (e) => { /* e.from, e.to === 'canvas2d', e.reason */ });
```

The GPU series backend is its own lazy tier (6.39 KB Brotli; nothing of it is in the base bundle, which `tests/renderer-option.test.ts` and `npm run shake` both check). Importing it registers the backend under `'webgl2'`, so `renderer: 'auto'` picks it up wherever WebGL2 is available and `renderer: 'webgl2'` stops throwing. The bare import is enough; `registerWebGL2Renderer()` is exported (idempotent) for a bundler that would drop a side-effect-only import. Its other exports:

| Export | What it does |
|---|---|
| `createWebGL2Backend(device?)` | One backend for one pane, or `null` when WebGL2 is unavailable on this device. The registered factory is this call, so an explicit `renderer: 'webgl2'` on such a device gets `canvas2d` and one console warning. |
| `isWebGL2Supported()` | Whether this browser hands out a WebGL2 context. A cached probe; always `false` outside a browser. |
| `WebGL2Backend` | The backend class, `new WebGL2Backend(device = sharedGlDevice())`, for a host that injects it through `renderBackend`. |
| `GlDevice`, `sharedGlDevice()` | The holder of the one page-wide context and the offscreen surface it draws on. `device.available` and `device.lost` are what `backendDegradation` reads. |
| `GlSurface` (type) | What the context is created on: a detached canvas or an `OffscreenCanvas`, or a stand-in in tests. |
| `WEBGL_TIER` | `'webgl'`, the tier's identity constant. |
| `VertexBatch`, `ColorCache`, `PremultipliedRgba` (types) | What `WebGL2Backend.batch` and `GlDevice.colors` are: the frame's vertex batch and the parsed, premultiplied colour cache. Type-only exports, for a host that reads them off a backend. |

**How it paints.** The pane keeps its base canvas and its 2D context; the backend is handed that context at `mount` like the 2D backend is. It batches every native series into one offscreen WebGL2 surface shared by every pane of every chart on the page (browsers allow around sixteen live contexts, so one per pane would fail a dashboard of a few multi-pane charts) and at `endFrame` composites the result into the pane's base canvas with a single `drawImage`, under the plot clip and exactly where the 2D backend would have painted the series. The DOM is unchanged, so `takeScreenshot`, `exportSVG` and the context-menu snapshot read the same canvases they always did, and axes, text, price lines, markers and drawings stay on the 2D path. Drawn natively: `candlestick`, `hollow-candle`, `volume-candle`, `bar`, `high-low`, `line`, `line-markers`, `step`, `area`, `hlc-area`, `baseline`, `column`, `histogram`. Rect-based types land on the same device pixels as the 2D renderers because both read the same geometry helpers; anti-aliased edges (lines, fills, markers) differ by sub-pixel fringe amounts. `kagi`, `point-figure` and any custom chart type flush the batch and draw through the 2D context, so z-order between series holds.

**Falling back.** The chart reads `backendDegradation` on every pane after each frame. When a GPU backend loses its context, or its program fails to compile on a live context, the chart moves every pane to `canvas2d` for the rest of the session (a pane added later matches), `rendererKind` reads `'canvas2d'`, and one `'renderer:fallback'` event fires with a `RendererFallbackEvent` (`{ from: RenderBackendKind; to: 'canvas2d'; reason: RendererFallbackReason }`, the reason `'context-lost' | 'unavailable'`). The frame in which the context went away is painted through the backend's own 2D fallback, so the chart never shows a blank frame. The types `RenderDevice`, `RendererFallbackReason` and `RendererFallbackEvent` are exported from the base entry.

## The rest of the base surface

These are exported and supported, but sit outside the paths above. Signatures are
from `dist/index.d.ts`.

**Defaults you can read rather than retype.** Each is the exact object the engine
starts from, so spreading one keeps your override honest when a new key is added.

| Export | Type |
|---|---|
| `DEFAULT_CANDLE_STYLE` | `CandleStyle` |
| `DEFAULT_HISTOGRAM_STYLE` | `HistogramStyle` |
| `DEFAULT_CANDLE_BUILDER_OPTIONS` | `CandleBuilderOptions` |
| `DEFAULT_CHART_TABLE_OPTIONS` | `ChartTableOptions` |
| `DEFAULT_TIME_NAVIGATOR_OPTIONS` | `TimeNavigatorOptions` |

**Primitives you can attach directly.** Both implement `IPrimitive`, so they follow
the rules in [primitives-and-plugins](./primitives-and-plugins.md).

- `ChartTable` - a grid pinned to a pane corner. `cellWidth: 'auto'` fits each
  column to its widest rendered cell; fixed widths and per-column arrays remain
  supported. Every cell clips its own text. What an indicator's `table` hook
  builds for you; attach it yourself when the table is not tied to a study.
  `TableCell` supports multiline text, `italic`, CSS `fontFamily`, `verticalAlign`,
  `rowSpan` and `colSpan`. `ChartTableOptions.frameColor`/`frameWidth` draw an
  independent outer frame. Span validation is atomic in `setRows`; see the
  table contract in `primitives-and-plugins.md`.
- `IndicatorDrawings` - the primitive behind a descriptor's `draws` hook. One
  primitive holds the whole shape list, because a descriptor rebuilds its shapes on
  every recompute and per-shape primitives would re-sort z-order on every live tick.
  `new IndicatorDrawings(priceScale?)` optionally measures prices on the scale the
  callback returns each frame, given that frame's `PrimitiveRenderContext`, instead
  of the pane's binding for the layer.
- `IndicatorBackground` - the primitive behind a descriptor's `background` hook, one
  per shading target (the study's own pane, and, since 2.5.6, the price pane or a named plot's pane:
  see [background targets](indicators.md#background-targets-256)).
  Full-height per-bar columns in the bottom layer, behind every series.

**Calendar boundaries, zone-aware.** The `zone` argument defaults to
`DEFAULT_TIMEZONE`; never let it fall through to the browser's local zone.

```ts
isNewZonedWeek(prev, now, zone?)   isNewZonedMonth(prev, now, zone?)
isNewZonedQuarter(prev, now, zone?) isNewZonedYear(prev, now, zone?)
startOfZonedWeek(utcSeconds, zone?) startOfZonedMonth(utcSeconds, zone?)
formatZonedDate(utcSeconds, zone?)  formatZonedTimeSeconds(utcSeconds, zone?)
formatIstCrosshairLabel(utcSeconds)
```

`barCloseSec(interval, barStartSec, zone?)` returns when a bar closes, or `null` for
a code with no clock length - tick, Renko and range bars. Do not treat `null` as zero.

**Cache and feed plumbing.** `barCacheKey(req)` is the key
[`withBarCache`](./feeds-and-live.md) stores under; build it the same way if you
pre-seed the store. `backoffDelayMs(attempt, opts)` is the reconnect schedule.
`classifyAuthAck(raw)` returns `'ok' | 'failed' | null`, `parseTopic(topic)` splits a
subscription topic, and `readSequence(raw)` pulls a sequence number when present.
`decodeOrder(raw, path?)` returns an `OrderDecodeResult` rather than throwing, and
`mapOrderStatus(s)` narrows a broker string to `OrderStatus | 'unknown'` - an
unrecognised status stays visible instead of being silently dropped.

**Geometry, for a primitive doing its own drawing.**

- `bitmapSize(mediaWidth, mediaHeight, dpr)` - device-pixel size of a canvas
- `snapToDevicePixel(mediaCoord, dpr)` - the half-pixel alignment that keeps a
  1 px line from rendering as a 2 px blur
- `precisionForStep(step)` - decimal places implied by a tick size
- `watermarkRect(position, margin, w, h, plotW, plotH)` and
  `tableOrigin(position, margin, w, h, plotW, plotH)` - corner placement

**Interaction.** `beginPick(host, kind, cb)` starts a price, time or `'point'` pick
and returns its callable `PickHandle`; call it to tear the pick down. `handle.active()` is
true only while this invocation owns the capture, including after synchronous
cancellation or replacement during a start notification. `isRebasing(mode)` reports whether
a `PriceScaleMode` re-bases the series, which is true for `percentage` and
`indexed-to-100` and is why a rebased pane cannot share an axis with an absolute one.

`chart.beginPick(kind, cb, options?: PickOptions)` also checks actual plot bounds
and accepts `paneIndex` and a price-only `priceScaleId`. Explicit scales must
already exist. A scale without a pane targets the primary series' pane. The
selected scale converts pane-local coordinates, including hidden overlays.
Panning and primitive controls do not select values. Active drawing placement
refuses the pick; starting placement, data replacement, context changes, restore
and destruction cancel it. Cancelled picks emit `pick:end` with a null value.

`chart.beginPick('point', cb, options?)` captures a time and a price from one
click and hands `cb` a `PickPoint`, `{ time, price }`: the time of the bar under
the click (projected past the last bar) and the price on the target scale, which
`priceScaleId` names as it does for a price pick. `pick:start` and `pick:end`
carry `kind: 'point'`, and `pick:end.value` is the point or null. It answers only
when both halves resolve, so a study input pairing a time with a price
(`timeKey`, see [indicators](indicators.md#paired-time-and-price-inputs)) is
never written half from one click and half from another.

## Plot rectangle

`chart.plotRect(paneIndex): PlotRect | null` is a pane's plot in container media
px: `{ left, top, width, height }`, inside the price axis columns and above the
time axis strip, the same size a primitive on that pane paints into. Lay an HTML
overlay against it rather than working the rectangle out from `priceToCoordinate`,
the axis layout and the time scale. It is null for a pane collapsed to its header
strip, one hidden behind a maximized pane, and an index with no pane. It scales
the pane first, as `priceToCoordinate` does, so a pane no frame has painted yet
(just added or moved) answers with its own prices, not the 0..1 placeholder. The
draw tier measures viewport drawings by it, so a pinned drawing and a host overlay
read one rectangle.

```ts
const rect = chart.plotRect(0)!;
badge.style.left = `${rect.left + rect.width - 120}px`;
badge.style.top = `${rect.top + 8}px`;
```

## Tick schedule on the chart

`chart.setTickSchedule(schedule | null)` hands the chart the instrument's
price-dependent ticks (a `TickSchedule`; anything without `round` and `step`
throws a `TypeError` there, not on the first drag), and
`chart.tickSchedule()` reads it back, null for a constant tick, the default.
`Instrument.applyTo` sets it from `instrument.tickSchedule`; a host keeping its
own instrument metadata calls it directly. `chart.snapPrice(paneIndex, price)`
then rounds a price on the price pane with the band the price falls in rather
than the scale's one `minMove` (the grid every band lies on, which accepts 105.87
where a 0.25 band trades only 105.75 and 106), and a dragged price alert lands on
that band's tick, its range bound stopping a whole band tick inside an off-tick
opposite bound. Other panes keep their own scale's tick. It also reaches
`chart.trading`, now or when that layer is built. It describes the loaded
instrument and is not saved in the chart state. With no schedule every path
rounds exactly as before.

## Types that name a public signature

These sit in public signatures and are now exported, so a host can annotate what
it receives instead of restating the shape:

| Type | Where it shows up |
|---|---|
| `ChartSettingsInput` | `ChartSettingsTab.inputs`. A union of `IndicatorInput` and `ChartSettingsColorPairInput` |
| `ChartSettingsColorPairInput` | The settings-dialog control that edits an up/down colour pair as one field |
| `AxisStyle` | What `resolveScaleStyle` returns |
| `OrderUpdateEvent` | The argument to `OpenAlgoWsFeed.onOrderUpdate` |

They were referenced by the public API long before they were exported, which
meant a host writing its own settings dialog had to infer the shape or copy it.

## Chart branding and optional watermark (2.1.9)

`ChartOptions.branding` is `boolean | LogoWatermarkOptions`, default true.
`setBranding` replaces the chart-owned mark configuration and `brandingOptions` returns
its current configuration or false. Host branding does not belong in saved user layouts.

`ChartOptions.watermark` is `boolean | ChartWatermarkOptions`, default false.
`setWatermarkOptions` patches visibility/text/style, and `watermarkOptions` reads the
preferences. `ChartWatermarkOptions` extends `Partial<TextWatermarkOptions>` with a
`visible` switch. Automatic text reads the current data context. These settings are in
`ChartSettingsState` and the Appearance schema. See the detailed examples and migration
rules in [primitives-and-plugins](primitives-and-plugins.md).

`BrandingChangedEvent = false | LogoWatermarkOptions` is the defensive snapshot emitted
synchronously as `branding:changed` after `setBranding`. Host-accessible links subscribe
to this event and unsubscribe on teardown, so disabling or replacing a logo cannot leave
an old destination in the toolbar.


## Study policies

`IndicatorPolicy` (from `openalgo-charts`) restricts what a user may do with a study,
flag by flag; each defaults to `true`, mirroring the drawing policy. Pass it to
`chart.addIndicator(id, settings, { policy })`, read it with `indicator.policy()` (only
the flags that are `false`) and replace it with `indicator.setPolicy(policy | null)`,
which is always the host's act. `parseIndicatorPolicy(input)` validates one and keeps
only the four boolean flags (it throws on a non-boolean flag).

| Flag | `false` restricts |
|---|---|
| `removable` | `chart.removeIndicator(id)`, `indicator.remove()`, `chart.removePane(index)` for a pane holding it; the legend close button; `ChartObjects` `remove`; the widget's menu row and picker remove button (greyed, note "protected"). |
| `configurable` | `indicator.setSettings(patch)`, `setPriceScale`, `setPlotPriceScales`; the legend gear (no `indicatorSettings` event); `ChartObjects` `settings`; the widget settings dialog declines. |
| `movable` | `chart.moveIndicator`, `chart.reorderIndicator`, `chart.moveInSeriesStack` for it; `ChartObjects` `reorder`, `move`, `place`. Others still move past it; pane controls still move its pane. |
| `listed` | Its row in `ChartObjects` and every panel on it, the widget's picker list and alert source lists. The legend still shows it. |

Every restricted call treats its caller as the user and returns `false` with nothing
changed; the owning host passes `{ force: true }` (`IndicatorEditOptions`). `setSettings`
and `remove` now return a boolean. A restore is the host's act and replaces a protected
study. Hiding stays allowed. `IndicatorState.policy` saves only the restrictions, so an
unrestricted layout is unchanged; a malformed policy refuses the restore. A legend row
whose buttons the host set (`indicator.legend().setOptions({ actions })`) keeps them
through every restack; the policy only withholds close and settings from them. Workspace
documents keep policies. Portable templates leave out every study the host keeps from
the user (not `removable` or not `listed`) and the studies reading its output, and copy
any other study without its policy; a `replace` template plan keeps the host's studies.

`chart.addIndicator(indicatorId, settings?, { instanceId })` gives a new study that id
instead of a fresh one, so a host bringing a removed study back (an undo) restores its
identity for the studies reading its output and the alerts naming it. An id a study on
the chart holds throws; a removed study's id is free to take back. A new study without
one never reuses a removed study's id.

## Draw order

A pane paints in bands, back to front: `'bottom'` primitives and drawings behind the
series; the series band; `'normal'` primitives (price lines, markers, study levels);
`'top'` primitives and drawings in front. The series band's entries are the price source
and each study living on the pane that plots a series there:

- `chart.seriesStack(paneIndex?)`: entry ids in paint order, `'source:primary'` and
  `'indicator:<instance id>'` (the inventory's ids).
- `chart.moveInSeriesStack(id, target, 'above' | 'below', options?)`: move the source or a
  study directly above or below another entry of the same pane. Studies take their slots
  in the study list in the new order, so their fills, levels and markers follow. The
  drawings placed on an entry move with it. `false` for another pane, a no-op, or a study
  that is not `movable` (unless forced). A moved source saves `ChartState.sourceAbove`
  (the study id it sits on, written only then); it stays the pane's instrument for the
  readout, the last-price line and a rebased axis.
- `chart.setPrimitiveStackAbove(primitive, entry | null)`: paint an attached primitive
  right after that entry's last series on its pane; a batching backend flushes first.
  While the entry plots nothing there the primitive paints in its own band.
- Hits rank by paint band first: whatever paints over the series (`'normal'` and
  `'top'` primitives in their own bands) beats whatever paints with or behind it (a
  primitive or drawing placed in the series band, a drawing behind the series, a
  `'bottom'` primitive) wherever both answer, whatever the distance; on either side
  the nearest wins, then the higher band. Press, hover, click and the context menu
  all use it, so a box placed under an order line gives the line the press.
- Context menus rank a drawing or placed primitive against a series by paint order: a
  hit whose `PrimitiveHit.paintedBy` paints under the series under the pointer gives
  way to it (the pane sets `paintedBy` on a hit from a primitive placed in the band).

`ChartObjects.stack(paneIndex)` joins them: drawings behind the series, each entry followed
by the drawings placed on it, then drawings in front. Rows gain `band` (`ChartObjectBand`:
`'below' | 'series' | 'above'`), `stackAbove` for a drawing in the series band, and the
`place` capability. `place(id, target, where)` moves a drawing anywhere in its pane and a
source or study only between whole slots; an entry between another entry and a drawing
placed on it, out of the series band, or onto another pane is refused. A drawing source
supports placement through the optional `ChartObjectDrawingSource.placeInStack`.
`ChartObjectDrawing` gains optional `stackAbove`. `reorder` keeps its per-kind order.

## Study movement and object order (2.5.3)

`chart.moveIndicator(instanceId, paneIndex)` moves a study without replacing its
instance ID or plot handles. Alerts keep their references and move with the study.
`chart.reorderIndicator(instanceId, direction)` takes -1 or 1 and changes actual
paint/legend order. Both return false for unavailable actions. Empty source study
panes are pruned after owned visuals relocate.

`ChartObjects` adds reorder(id, direction), move(id, paneIndex), canGroup(),
createGroup(name, ids), renameGroup(id, name), and ungroup(id). Object snapshots
can have kind group and optional groupId. Providers may add reorder/move callbacks;
missing callbacks keep those optional capabilities unavailable. Use inventory IDs
for ChartObjects actions and native IDs for Chart/DrawingController methods.
