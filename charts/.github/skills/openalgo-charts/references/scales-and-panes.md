# Scales and panes

*When to read this: configuring a price axis, pinning an overlay to part of a pane, controlling zoom or the visible bar range, or building/resizing/removing a multi-pane layout.*

Source of truth: `src/scale/price-scale.ts`, `src/scale/time-scale.ts`, `src/scale/ticks.ts`, `src/core/pane.ts`, `src/core/chart.ts`.

## PriceScaleOptions

```ts
import { DEFAULT_PRICE_SCALE_OPTIONS } from 'openalgo-charts';
// { marginTop: 0.1, marginBottom: 0.1, minMove: 0, mode: 'linear', inverted: false }
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `marginTop` | `number` | `0.1` | Fraction of **pane height** kept empty above the data band. |
| `marginBottom` | `number` | `0.1` | Fraction of **pane height** kept empty below the data band. |
| `minMove` | `number` | `0` | Instrument tick size (e.g. `0.05`); for a `TickSchedule`, its `minMove`, the grid every band lies on. `0` infers precision from the visible range. **A chart-wide setter withholds this from a pane that does not quote the instrument**: see below. |
| `minPrecision` | `number` | `0` | Least decimals a scale with no tick prints. Set to 2 on every study pane; ignored once `minMove` is set. |
| `mode` | `'linear' \| 'logarithmic' \| 'percentage' \| 'indexed-to-100'` | `'linear'` | `logarithmic` maps through `log10`, clamped at `1e-10`. The last two rebase against a baseline, below. |
| `inverted` | `boolean` | `false` | Price increases downward. |

`ChartOptions.priceScale` is applied to each pane's **right** scale as that pane is created; left and overlay scales always start from the defaults. Per scale at runtime:

```ts
series.priceScale().setOptions({ marginTop: 0.82, marginBottom: 0 });
chart.panes()[0].priceScale.setOptions({ minMove: 0.05, mode: 'logarithmic' });
```

**Margins are fractions of pane height, not of the data span.** Since 1.0.26 `autoscaleRange(low, high, marginTop, marginBottom)` gives the data band exactly `1 - marginTop - marginBottom` of the pane: `total = span / visible`, `min = low - total * marginBottom`, `max = high + total * marginTop`. Before 1.0.26 it padded the span, so `marginTop: 0.82` left the series 55% of the pane instead of 18%. Margins summing to 1 or more are clamped to a 0.01 sliver so the range stays finite. Since 2.6.3 a logarithmic scale pads in log space (the scale's `autoscale` and a comparison over it compute the same formula on `log10(low)` and `log10(high)`), so the data band is the same share of the pane as on a linear scale; through 2.6.2 it padded in price units, which left a whole empty decade under a long series such as 150 to 1230. A range a log cannot take (a low at or below zero, or a flat series) keeps the price-space padding. `autoscaleRange` itself is unchanged and works in whatever units it is given.

### The rebasing modes

`percentage` and `indexed-to-100` quote every price against a **baseline**: percent change from it (`+3.42%`), or the baseline rebased to 100 (`103.42`). They share one transform, since percent change is the index minus the 100 it rebases to.

```ts
const ps = chart.panes()[0].priceScale;
ps.setOptions({ mode: 'percentage' });
ps.setBaseline(firstVisibleClose);   // data, so the pane supplies it per frame
ps.baseline;                          // number | null
```

- **The baseline is data, not geometry**, so the scale cannot find it alone. The pane's autoscale pass feeds it the first value of the visible range each frame, which is what makes panning re-base: the axis always reads as change measured from the left edge of what is on screen.
- **No baseline means the identity transform**, so the scale behaves exactly like `linear` rather than answering with nonsense before the first frame. `setBaseline(null)` is the deliberate way to say "nothing to measure".
- **Zero and negative baselines are refused** the same way. Percent change from zero is undefined, and a negative baseline flips the sign of the transform, so a rising price would draw downward on an axis still labelling itself normally.
- **Labels switch to the rebased domain and outrank a custom price formatter.** `precision()` comes from the transformed span with two decimals as the floor; `format()` renders `+3.42%` (explicit sign, no `-0.00`) or `103.42`. A currency prefix on a percent change would read as money that is not there.
- **`reset()` drops the baseline** along with the range, so a pane that loses its last series does not keep quoting the next one against a departed price.
- **A rebase relabels the pane, it does not reshape it.** The transform is affine over a price-space range, so one series looks identical to its linear self by definition. Two instruments become comparable only when each sits on its own scale with its own baseline, which is what [replay-and-compare](replay-and-compare.md) builds on.

`PriceScale.ticks(maxTicks = 6)` is the axis ladder and belongs to the scale, not the axis renderer. Linear and log get `niceTicks` over the price range; the rebasing modes get nice values chosen over the **transformed** range and mapped back, because a nice price is an ugly percentage (`+3.47%, +6.94%` instead of `+5.00%, +10.00%`).

**How many rungs the axis asks for changed in 1.8.5.** The renderer used to pass a flat 6 whatever the pane measured, so a 700 px chart read one price every 120 px while a reference terminal read one every 30. It now derives the count from the pane height at a fixed spacing, `priceTickCount(plotHeight)` against `PRICE_LABEL_SPACING` (32 px, clamped to 2..30), which puts about twenty prices on that pane instead of six. Both live in `src/render/axis.ts` and are internal, like the axis renderer itself; the number a host sees is simply the denser ladder. The `maxTicks = 6` default on `ticks()` is untouched, and `ticks()` is public: it is a ceiling for a direct caller, not what the axis uses.

`maxTicks` remains a request rather than a promise. `niceTicks` walks the 1 / 2 / 2.5 / 5 ladder until the count fits, so a range with no round step at that density simply prints fewer.

### Range control

| Member | Notes |
|---|---|
| `autoScale` (getter) | `true` while the range tracks the data. |
| `setAutoScale(on)` | `false` freezes the current range. |
| `setPriceRange({ min, max })` | Sets the range and marks the scale as scaled. |
| `priceRange()` | `{ min, max }`. |
| `autoscale(low, high)` | Applies `autoscaleRange` with the configured margins, in log space on a logarithmic scale (since 2.6.3). |
| `scaleAroundCenter(factor)` | `>1` widens, `<1` narrows. Switches to manual. |
| `panByPixels(dy)` | Shifts in transformed space, honours `inverted`. Switches to manual. |
| `scaled` (getter) | `false` until a real range is applied; the placeholder is `0..1`. |

Freezing a range means both `setPriceRange` and `setAutoScale(false)`:

```ts
const ps = chart.panes()[2].priceScale;
ps.setAutoScale(false);
ps.setPriceRange({ min: 0, max: 100 });   // e.g. an RSI pane
ps.setAutoScale(true);                     // hand it back to the data
```

`chart.resetScale()` (also the navigator reset button and the default double-click action) re-enables autoscale and releases ratio locks on every created right, left and overlay scale, then restores the configured default view. `navigation.defaultVisibleBars: 0` fits all loaded bars; a positive count targets the newest N loaded bars plus four right-padding slots, within data and spacing limits.

Chart-wide equivalents, for a settings dialog: `chart.setPriceScaleOptions(patch, scope = 'primary')` writes each pane's right scale; scope `'axes'` selects scales configured on a visible side, and `'all'` includes hidden scales. `chart.priceScaleOptions()` reads the price pane's right scale, in whatever slot it sits (`primaryPaneIndex()`). `chart.priceScaleDefaults()` reads the chart-wide defaults those calls (and the `priceScale` option and the canvas margins) set, which a pane added later starts from and which `setPriceAxisOptions` on one axis leaves alone: compare the two to tell a chart-wide change from a one-axis one. `chart.setAutoScale(on)` updates every active visible axis across panes and releases those axes' ratio locks when enabled. It leaves hidden scales and their locks unchanged; `resetScale()` still resets every created scale. See [settings-and-menus](settings-and-menus.md).

### Conversion and formatting

## Precision follows what a pane measures, not where it sits

`minMove` is a property of the **instrument**, so it is the one field in the
chart-wide block that does not reach every pane. `Chart.setPriceScaleOptions`
withholds it from a pane that does not quote the instrument, whatever `scope` is
asked for; `mode`, `inverted` and the margins still reach every scale that scope
names. Naming an axis outright (`setPriceAxisOptions`, a series' `priceFormat`)
is the caller settling what that axis quotes, and is obeyed.

Which panes quote it:

- **The price pane** (the chart's first pane, `primaryPaneIndex()`) does, from
  construction, and keeps doing so when it is moved below its studies. A caller
  who configures nothing sees byte-identical behaviour there, its left axis and
  its hidden overlay scale included: the filter is per pane, not per scale.
- **Any other pane** starts out a study's and holds its own units, until a host
  plots a price series on it (a second symbol on a pane of its own), which
  promotes it and hands it the tick it was not given.
- An indicator's plots never promote their own pane, built in or custom.

So an overlay study (`placement: 'onchart'`) is quoted in the instrument's tick,
because it draws against the price axis and *is* a price: a Supertrend on a 0.05
tick reads `1339.70`, which is the number an order snaps to. A study on a pane of
its own (`placement: 'pane'`) is not: an RSI is a dimensionless 0..100 band and a
Williams VIX Fix is a percentage, so precision comes from that pane's own span.

The span alone reads too coarse, so those panes carry `minPrecision: 2`. A 0..100
band implies a step of one whole point, which would label the ladder `70` and round
a reading of 62.24 to `62`, past the part a trader comparing it to the level is
looking at. Two decimals is the same floor the percent-rebase branch has always
used, for the same reason. The floor lifts above five integer digits, where a
decimal stops being information: an OBV of `1234567` keeps its integer form.

**A custom descriptor gets all of this with nothing to declare.** The rule is
keyed on the pane an indicator is handed, not on anything in the descriptor, so
`registerIndicator` needs no precision field and there is no per-indicator list to
keep in sync.

`priceToY(price)` / `yToPrice(y)` are pane-local media px; `chart.priceToCoordinate` / `chart.coordinateToPrice` add the pane's top offset. `precision()` derives decimals from `minMove` (or `range/100`), `snapToTick(price)` rounds to `minMove`, `format(price)` renders the axis label, `setPriceFormatter(fn | null)` overrides it, `clampY(y)` clamps to the pane. Tick values come from `niceTicks(min, max, maxTicks = 6)` on the 1 / 2 / 2.5 / 5 / 10 ladder.

### Autoscale rules

Per frame, for each active scale on a pane: skip if `autoScale` is false; scan only visible bars of series matching that scale id and not `visible: false`; take `min`/`max` from the chart type's `extents(bar, style)`. A primitive's `autoscaleInfo()` contributes to its explicitly bound scale, including a hidden scale. Unbound primitives retain the default right-scale contribution.

## Price scale ids

`PriceScaleId` accepts `'right'`, `'left'`, `''` and names beginning with `overlay:`.

| Id | Default placement | Autoscales | Typical use |
|---|---|---|---|
| `'right'` | Right strip | Independently | Default for every series. |
| `'left'` | Left strip | Independently | A second instrument or spread at a different magnitude. |
| `''` | None (hidden) | Independently | Volume pinned inside the price pane. |
| `'overlay:name'` | None (hidden) | Independently per name | Multiple comparison instruments without sharing price units. |

A pane creates the left and overlay scales lazily when first requested. Scale
identity does not dictate placement: `setPriceAxisPlacement` can expose any scale
on either side, with one column per active scale. Attached series, including
hidden series, and explicitly bound primitives occupy columns. A configured
unused scale retains placement without reserving a column. Hidden placement
reserves no column; an empty chart keeps its default right column.

Panes share the maximum active column count on each side, keeping their plots
aligned in time. Each pane packs its columns nearest the plot. Unused outer
cells have no price-axis input target. Columns use `priceAxisWidth`, reduced
equally on narrow charts to leave at least one column-width for the plot.

Series using the same named overlay on the same pane share its scale. Named
overlays default to hidden placement and remain available while a bound primitive uses them.
Configured named scales also survive their last series being removed, so later
assignments recover their range, options and formatting. Unconfigured temporary
named scales can be released. `PriceScale.hasConfiguration()` distinguishes
configuration from a range that was only measured automatically.
`PriceScale.setComputedRange(range)` writes a derived projection while preserving
existing view ownership; host range changes continue to use `setPriceRange`.
All created scales participate in `pane.scales()` and scope `'all'`.
`pane.axisScales()` includes scales configured on either visible side and excludes
hidden placements. Exposing a named overlay therefore includes it in axis-only
settings. The empty overlay retains its hidden default.

```ts
const vol = chart.addSeries('histogram', {
  priceScaleId: '',                    // no axis of its own
  priceFormat: { type: 'volume' },
});
vol.priceScale().setOptions({ marginTop: 0.82, marginBottom: 0 });  // bottom ~18%
```

**`pane.priceScale` is the `'right'` scale only.** Reach other scales with
`series.priceScale()`, `pane.scaleOf(record)` or `pane.scaleFor(scaleId)`.

### Place and reorder columns without changing IDs

```ts
chart.setPriceAxisPlacement(0, 'overlay:spread', 'right');
chart.setPriceAxisPlacement(0, 'overlay:spread', 'right', 0);
chart.setPriceAxisPlacement(0, 'overlay:spread', 'left');
chart.setPriceAxisPlacement(0, 'overlay:spread', 'hidden');
const placement = chart.priceAxisPlacement(0, 'overlay:spread');
const slots = chart.priceAxisLayout(0);
```

`PriceAxisSide` is `'left' | 'right' | 'hidden'`. `PriceAxisPlacement` contains
`{ side, order }`, with zero nearest the plot. An explicit order must be a
nonnegative safe integer and is clamped to available ranks. Omitting it keeps
the rank on the same side and appends when changing sides. The setter returns
false for invalid or unchanged requests. The getter returns a detached placement
or null for an invalid ID, missing pane or destroyed chart.

`PriceAxisSlot` contains `{ scaleId, side, order, x, width }`. The chart's layout
getter returns active columns, with `x` at the column's left edge in absolute
pane CSS pixels and `width` for one column. The three types are base exports.
Do not cache geometry across source changes, placement changes or resizing.

Placement keeps scale and source IDs, ranges, formatters, locks, markers and
alert anchors. It emits `priceAxisPlacementChanged` with
`{ paneIndex, scaleId, side, order }` and `objects:change`. Full chart/workspace
state saves optional `PriceScaleState.placement`; omission restores defaults.
Indicator templates retain scale IDs but do not yet save pane column placement.

### Reassign a live series

```ts
chart.setSeriesPriceScale(series, 'left');
chart.setSeriesPriceScale(series, 'overlay:spread');
chart.setSeriesPriceScale(series, 'right');
```

`setSeriesPriceScale(series, scaleId): boolean` changes one host-created series
on its current pane. Its handle, data, styles, primary role and marker bindings
survive. Source and target scales retain their settings, manual ranges and ratio
locks. Vacated scales remain available for reuse without drawing unused labels;
the pane releases a column when no series or bound primitive uses that scale.
Chart-wide insets shrink when the maximum column count across panes shrinks.
Crosshair price tags are omitted when the readout scale is hidden.
Last-price and series-value tags follow their source's left or right scale.
The readout series carries the countdown, and only on the pane that shows the
chart's price source (since 2.5.9): a study pane's tag is the study's value and
stays one row. Other visible sources use their plot colors, including sources
on the opposite axis. Collisions are resolved independently per column.
Hidden-scale sources draw no axis tags.

Left tags fit their text within the reserved column and stay vertically inside
the pane at its edges. A tag is omitted when the column is absent or the pane is
too short.
`visible: false`, `lastValueVisible: false`, transparent plots and nonfinite
current values suppress their tags.

Explicit series `priceFormat` is applied to the target, followed by its style
precision, just as with `addSeries`. Formatting is shared by all series on that
target scale; the source scale's formatting is unchanged. Without an explicit
format or precision, the target keeps its formatter. The operation repaints and
emits one `objects:change`, with no data reset or indicator recalculation.

It returns false before mutation for an invalid ID, unchanged assignment,
foreign or removed handle, destroyed chart, or indicator-owned plot. A study's
plots, fills, levels and other scale-bound visuals move together through its
`setPriceScale` method. Use `setPlotPriceScales` for individual declared plots,
including related fill endpoints in the same patch.
The legacy `movePriceAxis`, deprecated and removed in 3.0.0 in favour of placement, reassigns every series and explicitly bound primitive
on the source `'left'` or `'right'` ID to the other ID, carrying its scale object
and configuration. The destination ID must be unused; other named columns on
that side do not prevent the move. Source and destination placements reset to
their named sides. Use `setPriceAxisPlacement` to retain source identities.

**Prices quoted for a pane follow its readout scale**, which is the scale its first visible price series maps to and falls back to the right one. That covers the crosshair price tag, last-price line and tag, and `chart.priceToCoordinate` / `coordinateToPrice`. `pane.readoutScale()` returns it. Axis dragging and wheel input instead act on the particular column under the pointer.

**`PrimitiveRenderContext.priceScale` reads the explicit primitive binding, or the
right scale when unbound.** `pane.bindPrimitiveScale(primitive, id)` binds an
attached primitive; `null` removes the binding. `pane.primitiveScaleId(primitive)`
returns the explicit ID or null. The owner schedules layout/repaint after its
transaction. Series-bound markers follow their series automatically.
State snapshots include the right scale and all configured secondary scales.

Primitive labels use `PrimitiveRenderContext.priceAxisSide` (`'left'`, `'right'`
or `'hidden'`), `priceAxisWidth` (one column, zero when hidden), and optional
`priceAxisOffset` (plot-relative CSS x of the column's inner edge). Native
contexts supply the offset; synthetic contexts may omit it to use zero on the
left or `plotWidth` on the right. `PriceLine` and `PriceLevels` fit their axis
labels to that column while keeping line, plot-label and hit coordinates
plot-relative. Bound `PrimitiveHit.priceScale` supplies drag prices.

### Reassign a whole study

```ts
const study = chart.addIndicator('rsi', { period: 14 }, { priceScaleId: 'left' });
study.priceScaleId();                    // 'left'; null means descriptor defaults
study.setPriceScale('overlay:momentum');
study.setPriceScale('right');
study.setPriceScale(null);               // restore declared plot scale IDs
```

An explicit override applies to all local plots and their fills, levels, drawings
and attached price primitives. Markers bound to plots follow those plots. Explicit
`overlay: true` plots and fills retain their price-pane placement and effective
scale; price-anchored markers keep their primary-series binding. Tables and
untargeted background shading remain screen-space resources; a shading column
naming a `plot` ([background targets](indicators.md#background-targets-256), 2.5.6)
is bound to that plot's scale and moves with it. Fill endpoints must share a
pane and scale, or the request returns false before changing anything. Unplotted
calculation columns used by a fill resolve against that fill's local band scale.

The instance, plot handles, data, marker layers and provider attachments survive.
No calculation or alert evaluation runs merely because the scale changes. One
`objects:change` follows a successful move, with legend readings and axis columns
updated. Invalid IDs, unchanged assignments and removed instances return false.
Overrides survive settings changes, native plot renderer changes and pane moves.
Changing a native plot renderer keeps its `SeriesApi` handle; transforms still
require host-prepared data.

Configured targets retain ranges, modes and ratio locks. Explicit plot price
formats and style precision apply in descriptor order, as at creation; the last
explicit assignment controls the formatter shared by that scale. A descriptor's
fixed range is an owned default for an eligible scale, never a replacement for
a host manual or fixed range. Moving/removing its owner releases only that
default, preserving subsequent host changes and other sources' settings.
When settings change the same owner's declared range, its fit default updates;
an existing manual view stays in force until auto-fit is enabled again.

`IndicatorState.priceScaleId` saves the override; omission restores descriptor
defaults when no per-plot override is present. `IndicatorState.plotPriceScaleIds`
saves explicit plot overrides. `PriceScaleState.indicatorRange: { instanceId, manual }` distinguishes
a study-owned default from an equal-valued host range and records later manual
view intent. Preserve this metadata with saved scales. Restore reconnects it to
the matching live study; custom formatter callbacks and source data are not
serialized.

### Reassign individual study plots

```ts
const study = chart.addIndicator('my-mixed-study', {}, {
  plotPriceScaleIds: { upper: 'overlay:band', lower: 'overlay:band' },
});
study.plotPriceScaleId('upper'); // effective ID; null for an unknown plot
study.plotPriceScaleIds();      // detached explicit override map
study.setPlotPriceScales({ upper: 'left', lower: 'left' });
study.setPlotPriceScales({ upper: null, lower: null }); // clear both overrides
```

`setPlotPriceScales` applies a partial map atomically. A missing key is untouched;
null clears that key's override. Empty or unchanged patches return false, as do
unknown plots, invalid scale IDs, accessors and fill endpoints that would use
different panes or scales. Construction and known-descriptor state restore
validate complete assignments before allocating or replacing chart resources.

Effective precedence is the per-plot override, the local whole-study override,
the descriptor's `priceScaleId`, then `right`. An explicit `overlay: true` plot
ignores the whole-study override, but its own override selects a scale on the price pane.
A successful `setPriceScale(id)` clears local plot overrides. `setPriceScale(null)`
also clears the whole-study override, restoring local descriptor defaults.
Both retain explicit price-overlay overrides; clear those individually with null.

Fills follow their common endpoint scale. Levels, unbound price drawings and
attached price primitives follow the first local plot, as does study-owned range
intent. A drawing that names a `plot` follows that plot's scale, and a price-pane
drawing (`overlay: true`) follows the scale the price pane quotes prices on, the candles' own, without binding one. Plot markers,
including marker groups that name a plot, follow their series. A shading column naming a plot
(2.5.6) is bound to that plot's scale, and price-pane shading binds none. Tables and untargeted background
shading remain in screen coordinates. Handles, data, settings and provider attachments survive
assignment changes; no calculation or alert evaluation is required.

Scale identity remains separate from column placement. Use
`setPriceAxisPlacement(study.paneIndex, id, side)` to expose a named scale after
assigning it. Target formatting is shared, so plots with different units normally
need different IDs. Explicit formats apply in descriptor order at the destination;
a price format restores the chart's price formatter in place of a prior percent
or volume formatter. Saved chart state and workspace documents retain the explicit
map. Legacy study templates retain that map too; portable pane placement and
scale-copy ownership are separate template concerns.

## TimeScaleOptions

```ts
import { DEFAULT_TIME_SCALE_OPTIONS } from 'openalgo-charts';
// { barSpacing: 8, minBarSpacing: 1, maxBarSpacing: 80, rightOffset: 4 }
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `barSpacing` | `number` | `8` | Media px per bar. Always clamped to `[minBarSpacing, maxBarSpacing]`. |
| `minBarSpacing` | `number` | `1` | Floor; read once in the constructor, not settable later. |
| `maxBarSpacing` | `number` | `80` | Ceiling; read once in the constructor, not settable later. |
| `rightOffset` | `number` | `4` | Empty bar slots kept right of the latest bar. Unclamped. |

Since 2.1.1, `ChartOptions.timeScale` accepts `Partial<TimeScaleOptions>` at construction.
For a wide footprint column use `createChart(el, { timeScale: { maxBarSpacing: 260 } })`.
The minimum and maximum are constructor options; tune spacing and offset on the live instance:

```ts
chart.timeScale.setBarSpacing(12);
chart.timeScale.setRightOffset(8);
chart.timeScale.fitContent(bars.length);
```

`chart.timeScale` is shared by every pane, which is why panes stay aligned bar-for-bar.

Direct spacing, offset, range, scroll, zoom and fit changes repaint the owning
chart and emit one `pan` or `zoom` event for the final changed range. Linked
charts receive these events too. Unchanged ranges emit no chart navigation event.
`setWidth` and `setBaseIndex` remain silent bookkeeping operations; use the
chart's sizing and data APIs in a host. `TimeScale.setChangeHandler` receives the
detached previous logical range. A valid explicit range request invokes the hook
even when unchanged, allowing the chart to cancel pending motion without emitting
a navigation event. The chart owns this handler, so a host must not
replace it on an attached scale.

### Default visible bars

`ChartOptions.navigation` accepts `Partial<ChartNavigationOptions>`, whose defaults are
`{ mousePan: 'both', defaultVisibleBars: 0 }`. Read the resolved values through
`chart.navigationOptions()` and merge a patch through `chart.setNavigationOptions(patch)`.

```ts
const chart = createChart(el, { navigation: { defaultVisibleBars: 120 } });
chart.addSeries('candlestick').setData(bars);
chart.setNavigationOptions({ defaultVisibleBars: 80 });  // apply the new default view now
chart.resetScale();                                    // restore it after panning
chart.fitContent();                                    // explicitly fit all loaded bars
```

Initial data and reset use the configured count. `0` fits all loaded bars; a positive N
targets the newest `min(N, loaded bar count)` bars plus four empty bar slots on the right,
with spacing bounded by the time scale's minimum and maximum. A host's explicit viewport
after loading data takes precedence. Ordinary widget loads honour the configured count.

This is a viewport preference, not a history lookback or feed-request limit: all loaded
bars stay available for panning. Explicit `fitContent` methods still fit all supplied
bars. The two navigation fields are exposed on the settings schema and round-trip in
chart state; a saved viewport is applied after navigation options on restore.

### The logical-index model

`x = width - (baseIndex + rightOffset - index) * barSpacing`. The x of a bar is a function of its **integer position in the series**, never of its timestamp. Bars get consecutive indices regardless of the real elapsed time between them, so weekends, holidays and session breaks have no index and therefore no blank space to draw, the axis is gapless by construction. `xToIndex` is the exact inverse and returns a fractional index.

`visibleRange()` returns `{ from, to }` as fractional logical indices, unclamped to the data (it can run negative or past the last bar). `setVisibleLogicalRange({ from, to })` picks `barSpacing = width / span`, anchors the right edge at `to`, and fires the repaint hook, it is a no-op when width or span is not positive, and an extreme span lands at the nearest clamped zoom. `zoomAtX(focusX, factor)` keeps the index under `focusX` pinned. `fitContent(barCount)` sets `baseIndex = barCount - 1`, resets `rightOffset` to `4`, and sizes bars to `width / (barCount + rightOffset)`.

## How interaction mutates the scales

Details in [interactions](interactions.md); what matters here is which gesture leaves a scale in **manual** mode.

| Gesture | Effect | Leaves manual? |
|---|---|---|
| Vertical wheel over the plot | proportional `timeScale.zoomAtX`, eased by default; `zoomAnchor` selects cursor or right edge, except Ctrl/Meta pinch-style wheel always uses the pointer | no |
| Horizontal wheel or Shift-wheel over the plot | time `scrollByPixels` | no |
| Wheel over a visible price axis | scale that column's range at the pointer price | **yes**, for that scale |
| Drag inside the plot | time `setRightOffset` and vertical `panByPixels` on the pressed pane by default; `navigation.mousePan: 'horizontal'` limits mouse and pen to time | only when panning price; horizontal-only mouse/pen panning preserves autoscale |
| Drag a visible price-axis column | `setPriceRange` around the centre by `exp(dy * 0.005)` on **that column's** scale, then `setAutoScale(false)` | **yes** |
| Drag the time axis strip (bottom pane, last `timeAxisHeight` px) | `setBarSpacing(start * exp(-dx * 0.005))`: left expands, right compresses; preserves the logical right edge | no |
| Two-finger pinch | zoom time, pan time, `panByPixels` on the pinched pane | **yes** (price scale) |
| Double-click | `chart.resetScale()` | no, restores autoscale everywhere |
| `panUp` / `panDown` shortcuts | `panByPixels(±20)` on **the price pane only**, wherever it sits | **yes** |

**Once a scale goes manual it stops tracking new data.** A live feed that keeps printing highs can run off the plot on that scale. Call `chart.setPriceAxisAutoFit(paneIndex, scaleId, true)` for the affected column or `chart.resetScale()` for all scales.

**Each visible column is draggable.** The gesture reads and writes that column's scale. Blank aligned cells do not target another column or a hidden scale.

`ChartOptions.animAutoscale` eases automatic price-range changes while navigation reveals
new extrema. It defaults to `animZoom`. Manual and fixed scales bypass the transition.
Programmatic viewport replacement, primary data replacement, reset and destruction cancel
pending navigation motion so an earlier animation cannot overwrite newer state.

## One axis at a time

`setPriceScaleOptions` and `setAutoScale` are chart-wide. A menu or an inspector raised on one strip wants one scale, and wants to read every item back so it can draw its own ticks:

```ts
const st = chart.priceAxisState(paneIndex, scaleId);   // PriceAxisState | null
chart.setPriceAxisOptions(paneIndex, scaleId, { mode: 'logarithmic' });
chart.setPriceAxisAutoFit(paneIndex, scaleId, true);   // also releases the ratio lock
chart.setPriceAxisLockRatio(paneIndex, scaleId, true); // false when it could not be taken
chart.setPriceAxisPlacement(paneIndex, scaleId, 'left'); // retains the scale ID
```

`PriceAxisState` is `{ paneIndex, scaleId, side, active, autoFit, inverted, mode, scaled, lockRatio, movable }`, and `PRICE_SCALE_MODES` lists the four modes in menu order. Use the exact `scaleId` from a `contextmenu` target, including named or empty overlays explicitly exposed as columns. An id that names no scale (`'Left'`, `'x'`) changes nothing: since 2.6.0 the setters return early (`setPriceAxisLockRatio` returns false) and `priceAxisState` returns null, as `setPriceAxisPlacement` always refused it. Before, they fell through to the right scale. `side` reports right for hidden placement for compatibility; use `priceAxisPlacement` to distinguish hidden state. `movable` describes only the legacy reassignment method and is deprecated with it, removed in 3.0.0; placement needs no such check.

- **Placement preserves identity.** `setPriceAxisPlacement` moves or reorders a column even when other scales use that side. The legacy `movePriceAxis(pane, from, to)` (deprecated, removed in 3.0.0) instead swaps the built-in side scale objects and reassigns their resources to the destination ID. It requires an unused destination ID and resets both placements to their named sides. A `priceAxisMoved` event, deprecated with the method, follows a successful legacy move; placement emits `priceAxisPlacementChanged`.
- **Whole-axis study moves require one local assignment.** `movePriceAxis` conservatively refuses a study with mixed local scale assignments or explicit price overlays. This is a guard on the legacy operation, not a saved-state limitation. `priceAxisState().movable` reports that restriction. Uniform local studies and primitive-only studies adopt the moved side. Use `study.setPriceScale` for all local resources or `study.setPlotPriceScales` for selected plots.
- **The ratio lock pins price-per-bar.** The pane remembers the geometry the lock was taken at and rescales the visible span by height over bar spacing each frame, in transformed space, so a logarithmic axis keeps its angle too. Auto-fit and `resetScale` release it, and it is refused on a scale nothing has measured (`scaled: false`), because there is no ratio to hold.
- **`active: false`** means no series or explicitly bound primitive maps to that scale. It is a row to render disabled with its state showing, not one to leave out.

See [settings-and-menus](settings-and-menus.md) for the menu around these.

## Axis chrome

Two optional readings on the axis strips, both **off** unless a chart asks for them, so a chart that omits the block draws the axes it always drew.

```ts
const chart = createChart(el, {
  axisChrome: {
    sessionClock: true,                    // or { showOffset: false }
    barCountdown: true,
    clock: () => feedTimeUtcSeconds(),     // defaults to the system clock
  },
});

chart.setAxisChromeOptions({ barCountdown: false });   // merged field by field
chart.axisChromeOptions();
```

| Option | Draws |
|---|---|
| `sessionClock` | A live clock in the corner where the price and time strips meet, formatted in the **chart's** timezone with that zone's offset from UTC on a second row. `{ showOffset: false }` drops the row, and it drops itself in a strip too short to carry it. Nothing is drawn when either strip is hidden. |
| `barCountdown` | A second row inside the last-price tag counting down to the current bar's close. The tag grows from 16 to 28 media px and its width follows the wider row. Only the pane showing the chart's price source carries it (since 2.5.9): it counts that bar, and a study pane's tag stays one row. |
| `clock` | Wall-clock **UTC seconds**, not a monotonic animation clock. Pass the feed's clock to keep a delayed or replayed chart honest about the time its data thinks it is. |

**The bar interval is read back off the bars**, as a median of the recent gaps, not configured: the chart is never told its own timeframe, and one that switches mid-session has to follow. A median rather than a minimum, so a backfilled duplicate two seconds apart cannot halve the cadence; and only the tail is sampled, so a year of daily history does not outvote the intraday feed running now. Past a bar's close the count rolls into the next bar's cycle instead of stalling at `00:00:00`, because a feed a second late with the new bar should still show a running clock. With no readable cadence the row reads `--:--:--` rather than vanishing.

**Price-axis ticks give way to the labels above them.** The pane reserves the band the last-price tag will occupy before the ladder is drawn, and a tick colliding with it is dropped instead of drawn through. The priority order is crosshair, then last price, then a price line, then a session level, then previous close, then a plain tick, on the principle that the label a reader could interpolate from its neighbours is the one to lose.

Since the ladder became denser in 1.8.5 this is no longer a rare event: rungs sit about a tag-height apart, so the last-price tag now essentially always suppresses the label beside it. That matches a reference terminal, which hides the prices either side of its own tag for the same reason. The rule did not change, only how often it fires.

**A tick label is drawn whole or not at all** (since 2.5.9). A rung within half a tag height (8 media px) of the pane's top or bottom edge would print a price the edge cuts in half, which reads as a different number, so its label is left out on either axis; the gridline stays. The margin is the label's band, the same one the collision rule above gives it, not its measured ink, so every engine labels the same rungs.

**The last-price tag is painted over a price line's tag** (since 2.5.9), after the pane's price lines rather than before them, so where the two meet (a study's 70 level against its value, an order resting at the touch) the price in force stays readable, as its priority says.

**A host drawing its own last-price line should stop.** The engine already draws a dashed line across the plot and a filled axis tag at that price, coloured by the forming candle's direction. A second `PriceLine` at the same price puts two tags on one pixel row, printed through each other. The engine's is also the one to keep: it reserves its band before the ladder is drawn, so neighbouring prices yield to it rather than being painted over, and it carries the bar-close countdown. A `PriceLine` takes part in neither, since its tag is drawn straight onto the strip, under the last-price tag where they overlap.

## Panes

A pane is one stacked drawing region with its own scales and canvases. Reference a `paneIndex` in `addSeries` (or `addIndicator`) and every missing pane up to it is created: the first pane with weight `1`, later panes with weight `0.32`. Every `paneIndex` is a visual slot counted from the top.

```ts
chart.addSeries('candlestick');                       // pane 0
chart.addSeries('histogram', { paneIndex: 1 });       // pane 1, created here
chart.addSeries('line', { paneIndex: 2 });            // pane 2
```

Heights are **relative weights**, not pixels: pane height is `chartHeight * weight / sumOfWeights`.

| Method | Returns | Notes |
|---|---|---|
| `chart.setPaneWeight(index, weight)` | `void` | Clamped to a minimum of `0.05`. Unknown index, or a weight that is not a finite number (since 2.6.0), is a silent no-op. |
| `chart.paneWeight(index)` | `number` | `0` for an unknown index. |
| `chart.removePane(index)` | `boolean` | Removes its series, data rows and indicators. `false` for the price pane, in any slot. |
| `chart.movePane(index, -1 \| 1)` | `boolean` | Swaps with the neighbour and re-appends the DOM in order. By default the price pane is pinned: a move that takes it off slot 0 or displaces it is refused. With `movablePrimaryPane` any pane moves, the price pane included. |
| `chart.primaryPaneIndex()` | `number` | The slot the price pane holds now: always `0` without `movablePrimaryPane`, and `0` until something moves it with it. |
| `chart.setPrimaryPaneIndex(index)` | `boolean` | Move the price pane to a slot, one `movePane` step at a time (one `paneMoved` per step). `false` for an unknown slot or the one it holds, and always `false` without `movablePrimaryPane`. |
| `chart.movablePrimaryPane()` | `boolean` | Whether the chart was built with `movablePrimaryPane`. |
| `chart.maximizePane(index)` | `boolean` | Toggle: one pane takes the whole chart and the rest are **hidden**, not shrunk. False for an index that names no pane, a fractional one included (since 2.6.0). Stored weights are untouched, so un-maximizing restores the stack exactly. |
| `chart.maximizedPane()` | `number \| null` | |
| `chart.setPaneCollapsed(index, collapsed)` | `boolean` | Fold a study pane to its header strip, or open it again. `false` for the price pane in any slot, an unknown index, a non-boolean, or no change. |
| `chart.paneCollapsed(index)` | `boolean` | The pane's own setting, kept while it is maximized. Always `false` for the price pane. |
| `chart.panes()` | `readonly Pane[]` | Live array. |

Each call emits an event: `paneRemoved`, `paneMoved`, `paneMaximized`, `paneCollapsed`, and `paneResized` after a divider drag.

**Pane 0 is pinned by default.** `removePane(0)` and any `movePane` that would displace pane 0 return `false`, including `movePane(1, -1)`, so the up control on the first study pane does nothing and an explicit pane `0` always means the price. Both also return `false` for an out-of-range index, so check the boolean rather than assuming success.

### Moving the price pane (opt-in)

`createChart(el, { movablePrimaryPane: true })` lets the price pane (primary pane) leave slot 0. It is the pane the chart is built with, and it holds the price series a host adds without naming a pane and the on-chart studies. With the option it can sit in any slot: `movePane(0, 1)`, `movePane(1, -1)` on the study below it (the study row's up control does exactly that), or `setPrimaryPaneIndex(panes().length - 1)` put it below its studies. `primaryPaneIndex()` says where it is now. The option is decided at construction. `createWidget` and `createChartGrid` take it too and hand it to their charts as given, off by default like the chart; the reference host opts in on every chart it builds.

It is opt-in because the move changes what slot 0 means. A host that passes `0` for the price pane would, once a user put a study above the candles, place order and price lines on the study, price a right-click order in the study's units through `coordinateToPrice(y, 0)` and test price alerts against the wrong pane. Before turning it on:

- **Drop every explicit `0` that means the price pane**, or pass `chart.primaryPaneIndex()` read at the moment of use. Omitting the pane is the simplest: every call listed below defaults to the price pane wherever it sits. `panes()[0]` is the top pane, not the price pane.
- **Follow `paneMoved`.** Anything keyed by slot moves with it, including a DOM overlay drawn over the price pane: position it from `panes()[primaryPaneIndex()].element` after each move.
- **Persist `primaryPane`.** A host that saves `getState()` through a field allowlist must keep `primaryPane` (and the version 2 it comes with), or a reload puts the price pane back on top.
- **Forward `plan.primaryPane` when applying a template.** `planIndicatorTemplateState` returns the destination's price-pane slot beside `plan.panes`; restore them together in a version 2 state, and roll back with `getState().primaryPane`, or the restore returns the price pane to the top. `planIndicatorTemplate` takes the slot as its sixth argument.
- **Structural hosts** (`IndicatorHost`, `DrawingChartHost`, `AlertChartHost`, `ComparisonChartHost`) have an optional `primaryPaneIndex()`; a custom host that omits it keeps slot-0 semantics.

**Opting in.** A host that passes an explicit `0` for the price pane changes those calls first, then turns the option on. Omit the pane argument, which defaults to the price pane wherever it sits, or pass `chart.primaryPaneIndex()` read at the moment of use:

```ts
// Before: 0 means the price pane only while it is pinned on top.
chart.addPriceLine({ price: 101.5, id: 'stop' }, 0);
const price = chart.coordinateToPrice(y, 0);

// After: name no pane, or ask where the price pane is now.
chart.addPriceLine({ price: 101.5, id: 'stop' });
const price = chart.coordinateToPrice(y, chart.primaryPaneIndex());
```

Then build with `createChart(el, { movablePrimaryPane: true })`, or pass the same option to `createWidget` or `createChartGrid`. A host that keeps even one such `0` (a volume histogram added with `paneIndex: 0` on `widget.chart`, say) leaves the option off, and nothing about its price pane changes.

Everything that means "the price pane" follows it rather than slot 0: `addSeries`, `addPriceLine`, `addEventMarkers`, `setEvents`, `addPrimitive` and `tradeHost` with no pane, `priceToCoordinate` / `coordinateToPrice` / `priceAxisState` / `priceAxisLayout` with no pane, `priceScaleOptions()`, the `panUp` / `panDown` shortcuts, an `onchart` study and every `overlay` plot, band, table and price-anchored mark, comparisons, price alerts, the drawing magnet, drawing copy and paste (the clipboard counts panes price pane first, so a drawing copied beside the candles pastes beside the candles on any chart) and a drawing link. The legend offset, the `Indicators N` count and the chart's background text sit on it (anchor `'primary-pane'`); the time navigator and the brand mark stay on the bottom open pane, which is the price pane when it is at the bottom.

It is never removed and never collapses, in any slot. A study pane moved above it, to slot 0, removes, folds and prunes like any other study pane, and its first study row carries the pane controls; the price pane's rows never do. Out-of-range moves return `false`, so check the boolean rather than assuming success.

A moved price pane is saved: `getState()` writes version 2 with `primaryPane` (see [events-and-state](events-and-state.md)). A chart built without the option refuses to restore such a layout (`restoreState` returns `applied: false` with the reason) rather than laying the price pane's scales, studies and drawings on the study pane in slot 0.

**Removing a pane re-indexes everything below it.** Indicators shift with their pane, but any `paneIndex` a host has cached is stale afterwards.

Panes with no series left are pruned automatically: `removeIndicator` drops an emptied study pane in any slot, and `restoreState` sweeps every empty study pane backwards. The price pane is never pruned.

### Collapsing a pane

`chart.setPaneCollapsed(index, true)` folds a study pane to a strip one legend row tall (the row height plus a `6` px inset above and below, so `30` px at the default icon size). It is a view of the pane, not an edit to it:

- Its series keep taking data and its studies keep recomputing.
- Its drawings, scales, ratio locks and stored weight are untouched, so `setPaneCollapsed(index, false)` brings back exactly the height it had. `setPaneWeight` on a collapsed pane stores the weight for when it opens.
- The strip shows one legend row and nothing else: the pane's first study row, whose buttons include the collapse control, even when the host added its own row to the pane first (that row returns above it once the pane opens). A pane with no study shows its first host row. Rows below the strip neither draw nor answer the pointer. Whichever study row is first on a study pane carries the pane controls, open or folded: a row that becomes first because the study above it was removed (including by the close button on the strip) or moved gains them, a study added below a host row has them, and a row that stops being first loses them. Series, grid, price ladder, crosshair and every other primitive neither paint nor hit-test on it. `priceAxisLayout(index)` is empty, `click`, `crosshair:move` and `contextmenu` report `price: null` there, and `priceToCoordinate` / `coordinateToPrice` return `null` for the pane, so a drawing tool, a price alert, a pick or a host overlay cannot land on a pane nobody can see. Alerts on the pane's studies and drawings keep firing: the draw tier reads a drawing on a strip through the pane's own scale.
- The open panes share the rest of the height by weight. Strips taller than the whole chart shrink together rather than overflow it.

The price pane never collapses, in whatever slot it sits, so a chart always keeps one open pane. A collapsed bottom pane keeps the time axis under its strip, at the foot of the chart; the time navigator and chart-bottom furniture (the brand mark) move to the lowest open pane. Maximizing a collapsed pane shows it whole, and un-maximizing folds it again. Collapsing the maximized pane ends the maximize (`paneMaximized` with `null`). The fold follows its pane through `movePane` and through removals above it, and `getState` writes `collapsed: true` on it. A `restoreState` that lists panes or rebuilds studies opens every pane its layout does not fold, including a pane it does not list, so a study rebuilt onto an existing pane never opens inside a stale strip; a restore that touches neither leaves folds alone.

The first study row of a study pane, above or below the price pane, carries a `collapse` action (`PaneLegendAction`) between `down` and `maximize`, open or folded; its glyph is a header bar over a chevron that points up while the pane is open and down once it is folded (`PaneLegendOptions.collapsed`). This is separate from `setIndicatorLegendCollapsed`, which hides study legend rows behind a count and never changes a pane. With both on, a strip keeps its first study row, because its collapse control is the only way back on the canvas; the row folds behind the count again once the pane opens.

### Divider dragging

Pressing within `4` media px of a boundary starts a resize; the cursor becomes `row-resize` on hover. The drag moves height between the two adjacent panes only, conserving their summed weight so the rest of the stack is untouched, and clamps each side to at least `min(24px, total/4)`. A boundary beside a collapsed strip moves height between the nearest open panes either side of it, and is not a divider when there is no open pane on one side. While a pane is maximized there is no divider at all. A pane boundary wins over a primitive hit, because legend rows sit directly below one.

`chart.getState()` persists every pane's weight and all configured scales: margins,
tick size, precision floor, mode, inversion, auto-fit state, manual/fixed ranges,
ratio locks and study-range ownership. The right scale stays in `priceScale`;
secondary scales use `scales[id]`. Indicator entries carry explicit study scale
overrides. See [events-and-state](events-and-state.md).

## Fit the primary prices only

Use `chart.setPriceOnlyAutoScale(true)` to fit the primary series' current scale
without including overlays or primitive extents on that scale. Read it with
`chart.priceOnlyAutoScale()`. The constructor option is `priceOnlyAutoScale`,
defaulting to `false`.

The preference follows the actual primary series across panes and named scales.
Other axes still fit their own data. Studies continue to calculate and draw;
values outside the fitted range can be clipped. A hidden or empty primary does
not substitute indicator extents. Explicit `afterAutoscale` extensions retain
their authority to adjust the resulting range.

Toggling this preference preserves manual ranges and ratio locks. Enable
`chart.setPriceAxisAutoFit(paneIndex, scaleId, true)` separately when auto-fit is
wanted. With auto-fit active, the primary price range follows visible bars as
navigation changes the time window.

The widget and reference host expose **Fit primary prices only** in Axes settings
and on the primary scale's context menu. The schema key is `scales.priceOnly`.
The preference is saved per chart in native state and portable workspaces.
