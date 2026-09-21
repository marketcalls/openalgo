---
name: chart-indicator
description: Build a custom indicator for the OpenAlgo /trading charting terminal (openalgo-charts). Use when asked to create, port, or debug a chart indicator, overlay, oscillator, band, or on-chart signal, including porting a study written for another charting platform. Writes a plain-JS descriptor into strategies/indicators/, but only after it validates against the real library. This is the chart path, not the Python openalgo.ta path used from strategies and scanners.
argument-hint: "[indicator name or a study to port]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Custom chart indicators for `/trading`

Build an indicator for the charting terminal. It becomes a picker entry with a
generated settings dialog, a legend row and saved-layout persistence, with no
build step and no restart.

**This is the chart (JavaScript) path.** It has nothing to do with the Python
`openalgo.ta` indicators used from strategies, scanners and backtests: different
language, different runtime, different API. If the request is for a Python
indicator, this skill is the wrong one.

## The one rule

**Never write a file into `strategies/indicators/` directly.** That folder is
imported by the live chart, and the runtime fails silently in the ways that
matter most: a column that is one element short, or a plot key that does not
match what `calc` returns, draws nothing at all and raises nothing anywhere.

Always: write to a scratch path, validate, install on a pass.

```bash
# 1. draft to a scratch file (never the indicators folder)
#    e.g. <scratchpad>/my_indicator.js

# 2. validate against the real openalgo-charts build
node .claude/skills/chart-indicator/validate.mjs <scratch>/my_indicator.js

# 3. only on PASSED, install it
node .claude/skills/chart-indicator/validate.mjs <scratch>/my_indicator.js --install
```

`--install` copies into `strategies/indicators/` **only** when there are zero
errors, and exits 1 otherwise. If validation fails, fix the draft and re-run.
Do not install a failing indicator, and do not weaken the validator to get a
pass. Report warnings to the user rather than silently accepting them.

**Never run `npm install` for this.** The full frontend tree is 560 MB across
521 packages; the validator needs two ES modules totalling 368 KB. It finds them
itself, in this order: `frontend/node_modules/openalgo-charts` if a React
developer already has it, then its own `.cache/`, then it fetches just that one
package at the version pinned in `frontend/package.json`. `openalgo-charts` has
zero dependencies, so that is one small download, about a second, cached after.

If the fetch fails (no network, npm unavailable), say so and offer the choice:
fix connectivity, or install without the pre-flight check and rely on the
chart's own validation, which reports the same structural problems as toasts
when the indicator loads. Do not silently skip validation.

## Recent changes worth knowing

The descriptor contract has only gained optional fields since this skill was
written, so an existing indicator keeps working on the pinned build. What
changed, newest first:

- **2.5.1: a finished alert can stop drawing its line.** Nothing an indicator
  declares changed and no export was added or removed: the index below counts
  the same 387 names it counted on 2.5.0.

  `AlertControllerOptions.spentLines: 'hide'` makes a triggered or expired alert
  keep everything except its line: the record, the scope, the checkpoints and
  the saved runtime all stay, which is what keeps a once-only alert from
  re-arming on the next reload. It is opt-in per controller, it is not written
  into an alert document, and the default is still `'show'`.

  A host API, like `hovered()` and `snapPrice()` before it. An indicator never
  reads it and never declares anything about it.

- **2.5.0: tables that fit their text.** Nothing an indicator declares
  changed and no export was added or removed: the index below counts the same
  387 names it counted on 2.4.8.

  The one thing worth knowing for a descriptor: **`ChartTableOptions.cellWidth`
  accepts `'auto'`.** A column then measures itself from its widest cell, using
  the font actually drawn, so a per-cell font override or a bold heading is
  accounted for rather than guessed at. An empty automatic column keeps a 28 px
  minimum, and percentage widths keep their measured proportions. Every cell
  also clips its text now, so a long reading can no longer spill over the
  column beside it, which is what made a wide value in one row look like a
  value in the next.

  `AlertController.hovered()` and `Chart.snapPrice(paneIndex, price)` also
  arrived. Both are host APIs: an indicator never calls either.

- **2.4.8: grab to pan, and a README rewritten.** Nothing an indicator
  declares changed and no export was added or removed: the index below counts
  the same 387 names it counted on 2.4.7. Pressing and holding the plot now
  shows a grabbing hand and pans both axes, and mouse and pen panning stop the
  moment the pointer is released, while touch keeps its flick. The default
  covers both axes; a chart with a saved horizontal-only preference keeps it
  until somebody changes it in the chart navigation settings.

  The one thing worth knowing for a descriptor: **a clickable legend action
  keeps its pointer cursor and stays usable across a repaint**, which is the
  behaviour a `hasSource` braces button and a gear depend on. If a legend
  action of yours stopped responding after a redraw on an older build, that is
  what was fixed.

- **2.4.7: an alert's line can be dragged.** Nothing an indicator declares
  changed. A price or study-threshold alert line is draggable by the trader, and
  a study threshold drags on its own plot's scale rather than the instrument's,
  including an independent or left scale. Worth knowing for a descriptor whose
  plot owns a scale: the preview does not enlarge autoscale and never shows
  study units on the price axis. The on-chart badge for an armed alert reads
  "Alert"; the serialized lifecycle values are unchanged, so anything reading
  `alert.state` is unaffected.

- **2.4.6: source access, marker anchoring and a legend that reads.** Three
  optional descriptor fields, all of which an existing indicator can ignore.
  `hasSource: true` puts a braces button on the legend row beside the gear and
  emits `indicatorSource` with `{ instanceId, indicatorId, paneIndex }`; the
  host owns the code and decides what the button opens, so set it only for a
  descriptor whose source a host can actually show. `markerAnchor: 'price'`
  measures a marker's `aboveBar` and `belowBar` against the instrument's
  candles rather than the descriptor's own first plot, which is what a buy or
  sell signal on an overlay means: below is below the low. The default stays
  `'plot'`, so a mark that belongs to a line keeps sitting on the line, and the
  field is ignored on a study that owns a pane. Legend readings now skip a plot
  drawn in a fully transparent colour, which matters if you declare an
  invisible column to anchor markers or fills to: it no longer reserves the
  width of a price in the row. Legend glyphs also scale with their button
  rather than the row's text, and `ChartOptions.legendIconSize` sets that
  button across the chart.

- **2.4.5: optional open interest and host contracts.** The published build has
  105 built-ins, including `open-interest`, `open-interest-change` and
  `open-interest-buildup`. `Bar.oi` is an optional reading: preserve zero, keep
  missing readings as gaps, and never sum OI when folding bars. `securitySeries`
  exposes a nullable `oi` column. Capability comes from host instrument metadata,
  not from whether one bar has a reading. See `reference/api.md` for an example.
  Host trader alerts can target a study's stable instance id and plot key; keep
  those plot keys stable and distinguish these alerts from descriptor `alerts`.
  The host owns delivery and pauses trader evaluation during loading and replay.
  `Instrument`, `ReplayGroup`, `exportChartDataCsv` and trading capability helpers
  are host APIs, not a reason for a study to mutate the chart, control replay or
  submit orders. Workspace/template APIs live in `openalgo-charts/workspace`,
  outside the core-plus-indicators object handed to a custom module. Existing
  descriptor fields remain compatible. Calculate from the supplied bars so a
  replayed study cannot reveal later history.
- **2.4.0: the constructs a ported study most often could not express.** Every
  item is optional and needs openalgo-charts 2.4.0 or later installed; the
  validator checks against the installed build, so read
  `node -p "require('./frontend/node_modules/openalgo-charts/package.json').version"`
  before using any of them, and do not use them on an older pin.
  `securitySeries(bars, interval, opts)` folds the chart's bars to a higher
  timeframe, one value per bar, with the three readings named (as it stood at
  that bar, the default; `offset: k` for the last completed bucket;
  `lookahead: true` for final values, which repaints) and
  `session: '0915-1530'` to anchor sub-day buckets to the session open. It
  replaces every hand-rolled fold. `plot.offset` paints a column that many
  bars ahead, the tail landing in the right margin, with fills and the legend
  following. A `calc` that throws once installed is reported on the study's
  data status instead of thrown into the render loop; throw
  `IndicatorInputError` for a condition the user can fix (Pine
  `runtime.error`). `alerts[].message` may be a function of the firing bar.
  Marker shapes `cross` and `xcross`, positions `paneTop` and `paneBottom`
  (Pine `location.top` / `location.bottom`). `fills[].overlay` for a band on
  the price pane (Pine `force_overlay` on `fill`). `plot.colorParts` for a
  wick and border coloured apart from the body (Pine `plotcandle` wick
  colour). `tooltip` and `id` on `draws()` labels and boxes. Inputs
  `interval` and `time` (Pine `input.timeframe` / `input.time`).
  `table` options `fontSize: 'auto'` (Pine `size.auto`). And
  `ctx.requestBars` on the attach context for another instrument's bars,
  which `/trading` serves from the terminal's own cached feed: the same broker
  session and the same bar cache the chart uses, so a benchmark costs no
  second transport and no credential reaches a chart setting. Omit `exchange`
  to mean the chart's own. It rejects on a host that registers no provider,
  and a study should publish that as unsupported rather than invent a value.
- **2.3.0: charts can be arithmetic over several instruments.**
  `openalgo-charts/transform` gains `parseExpression` and `evaluateExpression`,
  so `/trading` can chart `NIFTY/RELIANCE`, `2*CE25000 - CE25200` or any
  expression over any number of legs. These belong to the **transform tier**,
  not to the API object a custom indicator module receives, so nothing about
  writing an indicator changes. Worth knowing for one reason: a study added to
  a computed chart runs on the folded series, whose bars have no `volume` and
  whose high and low are a bound rather than a measurement unless the host
  asked for close-only. Volume studies read zero there, which is honest rather
  than broken.
- **2.2.1: inputs can carry help text, and a plot can label its own axis.**
  Every `IndicatorInput` variant now takes an optional `tooltip`, which the
  settings dialog renders as a small focusable `?` beside the label. Put the
  explanation there rather than in a parenthetical that stretches the row.
  `IndicatorPlot` now takes an optional `priceFormat`, the same `PriceFormat`
  union `addSeries` uses, with a new `percent` variant: it suffixes the value
  and does **not** scale it, so a study returning 0..1 reads `0.62%` and one
  returning 0..100 reads `62.24%`. Multiplying inside `calc` to make the axis
  read better would change the legend, the crosshair and everything computed off
  the value. Like `style.precision` it belongs to a plot that owns its pane.
  Both fields are optional, so an existing descriptor is unaffected.
- **2.2.0: hosts can offer 85 drawing tools.** The draw tier adds channels,
  pitchforks, Fibonacci and Gann geometry, wavefronts and manual patterns.
  `ADVANCED_LINE_TOOLS`, `ADVANCED_GEOMETRY_TOOLS` and `PATTERN_DRAWING_TOOLS`
  belong to `openalgo-charts/draw`; they are not part of the custom indicator's
  API object. The indicator descriptor contract and its 102 built-ins are
  unchanged. Drawing documents retain version 2 and existing tool IDs.
- **2.1.9: chart hosts gain built-in branding and
  an optional text watermark.** `ChartOptions.branding` defaults to the
  OpenAlgo mark, while `ChartOptions.watermark` defaults off. Hosts can update
  them with `setBranding` and `setWatermarkOptions`, inspect them with
  `brandingOptions` and `watermarkOptions`, and follow branding changes through
  `branding:changed`. Blank watermark text follows the symbol and interval from
  `setDataContext`. The public types are `LogoWatermarkOptions`,
  `ChartWatermarkOptions`, and `BrandingChangedEvent`. These are host APIs and
  do not change or belong inside an indicator descriptor.
- **2.1.8: navigation can ease automatic price ranges as it reveals new
  extrema.** `animAutoscale` follows `animZoom` by default, while a manual scale
  and a descriptor's fixed `range()` remain authoritative. Normalized wheel and
  trackpad gestures and the packaged widget's responsive controls are host
  features; they do not change a descriptor. OpenAlgo `/trading` constructs a
  bare `Chart`, so it receives the engine gestures but keeps its own toolbar,
  rails and panels rather than receiving `WidgetOptions.mobile` controls.
- **2.1.7: hidden indicators remain hidden through layout restoration and style
  edits.** Reference levels now follow the instance's visibility along with its
  plots and other visuals. The new `ChartObjects` inventory also exposes an
  indicator's visibility and Tier-2 data status to host and widget object
  panels, but it does not change the descriptor contract or add work to a
  custom indicator.
- **2.1.6: Tier-2 studies follow the chart's data context and loaded source
  range.** `createTier2Indicator` receives `dataContext` with the host's symbol,
  exchange and interval, cancels obsolete fetches, extends history when older
  bars arrive and refreshes when the host changes instrument. A descriptor can
  use `supports(ctx)` to report that its provider cannot serve a context. The
  managed lifecycle publishes loading, ready, empty, unsupported and error
  states with an explicit retry action, so provider failure is visible without
  putting network state into `calc`. Existing Tier-2 descriptors get the range,
  cancellation and status behavior through the wrapper without changing shape.
- **2.1.2: a Tier-2 study's data requests are keyed by data setting.** Changing
  the symbol or any other data input clears the previous values immediately, and
  a response that arrives for the setting you just left cannot land on the new
  one. A style-only change reuses the history already in flight instead of
  refetching, and a live observation wins over a historical point for the same
  time. An `attach` that used to guard against its own stale responses no longer
  has to.
- **1.8.9: precision is keyed on the pane, not the descriptor.** An `onchart`
  plot prints at the instrument's tick; a plot on its own pane prints at that
  pane's span with a floor of two decimals. A study pane is no longer formatted
  in the instrument's tick, which is why an RSI reads `70.00` rather than `70.0`.
  Custom descriptors get this with nothing to declare, and a precision input is
  still the wrong answer. See **Do not**, below.
- **1.8.4: `calc` runs once per animation frame, not once per tick.** A data
  update marks the indicators stale and the flush happens before the paint, so a
  burst of ticks collapses into one call. `calc` must therefore be a pure
  function of `(bars, settings)`. It always had to be, but running per tick used
  to hide an indicator that counted its own calls or accumulated into `store`.
  Reading `chart.indicators()` or an instance's `values()` flushes first, so a
  read-after-update in the same turn still sees fresh numbers.
- **1.8.4: `calcTail` is rarely worth it now.** The tick-rate problem it existed
  to solve is gone. It only pays when one pass over the loaded history is itself
  slow, which means deep history, not a fast feed.
- **1.8.3: the catalogue went from 91 to 102 built-ins**, so a file written
  earlier can shadow an id that did not exist when it was named. The new ids are
  listed in `reference/pitfalls.md` under the collision entry. That release also
  corrected nine built-ins and moved ten defaults, so an indicator that compares
  itself against a built-in may need its expectations re-derived rather than
  assumed unchanged.

## Workflow

1. **Read the request.** If it is a study from another platform, read it fully
   and identify:
   what is plotted, what is a signal, what state carries across bars, and what
   resets per day or per session.
2. **Before writing a formula, check `reference/cookbook.md`.** Every
   author-facing call is demonstrated there, and the first section is the one
   that saves the most work: the 105 built-ins are descriptors, so
   `getIndicator('macd').calc(bars, settings, {})` gives you MACD's own columns
   rather than a reimplementation that can drift from the chart's.
3. **Load the context you need.** `reference/contract.md` for the descriptor
   shape and the runtime's exact behaviour, `reference/api.md` for what is
   available inside the module, `reference/pitfalls.md` for the traps. Read
   `reference/pitfalls.md` before writing anything; most first drafts fail on
   something in it.
4. **Pick the closest example** in `examples/` and work from it:
   - `simple_zscore.js` — one pane, one plot, rolling window, levels, range
   - `intermediate_keltner_squeeze.js` — several plots, `fills`, `colorBy`, a
     second price scale, a boolean that hides part of the drawing
   - `shaded_trend_zone.js` — shading between two series, where the ribbon
     flips sides and recolours with the trend
   - `complex_session_vwap.js` — per-session state, `markers` with a signal
     latch, `table`, `calcTail`, zone-aware day boundaries
   - `regime_shading.js` — `background()`, `barColors()`, declared `alerts`
     and a data-derived `levels(ctx)`
   - `zones_with_draws.js` — `draws()` with all four kinds, driven by
     `pivotHigh` / `pivotLow`. The pattern behind structure studies
   - `heikin_ashi_candles.js` — a plot fed by four columns via `ohlc`
   - `session_range_modern.js` — `parseSessionSpec`, `inSessionAt` and the calc
     context, replacing a hand-rolled session parser
   - `tier2_external_data.js` — `createTier2Indicator` and the manual `attach`
     lifecycle, for data the chart does not have
   - `higher_timeframe_bands.js` (2.4.0) — `securitySeries` with two of its
     three readings, a study in its own pane whose bands and fill carry
     `overlay: true` onto the candles, an `interval` input, a marker pinned to
     the pane edge, an alert message built from the firing bar, and
     `IndicatorInputError` for an input the user can fix
   - `displaced_cloud_zones.js` (2.4.0) — `plot.offset` for a cloud painted
     ahead of its data, `colorParts` for a wick coloured apart from its body, a
     `draws()` zone with a hover `tooltip`, a `time` input, and a table that
     sizes its own type. Read it for the difference between a plot, which
     cannot leave the bars, and a drawing, which never was on them
5. **Draft to scratch. Validate. Iterate until it passes.**
6. **Install**, then tell the user to reopen the indicator picker on `/trading`.
   No page reload is needed: the catalogue re-reads the folder every time the
   picker opens, and an edited file is re-imported because the URL carries the
   file's modification time. A reload is only needed for a chart that was
   already open before the app itself changed.

## Migrating a study, construct by construct

Work through the source in this order. Each row is a mechanical translation;
the judgement is in the last two.

| In the source | Here |
| --- | --- |
| `overlay=true` / `false` | `placement: 'onchart'` / `'pane'` |
| every `input.*` | one `inputs[]` entry, matching type |
| every `plot()` | a plot key plus that column from `calc` |
| `plotshape` / `plotchar` / `plotarrow` | `markers()` |
| `hline` | `levels(ctx)` |
| `fill()` | `fills`, or `background()` if it shades the whole pane |
| `bgcolor()` | `background()` |
| `barcolor()` | `barColors()` |
| `plotcandle` / `plotbar` | a plot with `ohlc: { open, high, low, close }` |
| `line.new` / `box.new` / `label.new` / `polyline.new` | `draws()` |
| `alertcondition()` | an `alerts[]` entry |
| `var` state across bars | a variable outside the `calc` loop |
| `x[1]`, `x[n]` | `arr[i - 1]`, `arr[i - n]` |
| `na` | `null`, and guard every comparison |
| `barstate.*` | `ctx.barState` on the 4th `calc` argument |
| session strings | `parseSessionSpec` + `inSessionAt` |
| `ta.*` | the exported helper of the same job, see `reference/api.md` |
| `request.security(syminfo.tickerid, tf, ...)` | `securitySeries(bars, tf, opts)` (2.4.0), see below |
| `plot(x, offset = n)` | `plot.offset: n` (2.4.0) |
| `input.timeframe` / `input.time` | `type: 'interval'` / `type: 'time'` (2.4.0) |
| `runtime.error(msg)` | `throw new IndicatorInputError(msg)` (2.4.0) |
| `alert(dynamic message)` | `alerts[].message` as a function of the bar (2.4.0) |
| `plotshape(location.top / location.bottom)` | `position: 'paneTop'` / `'paneBottom'` (2.4.0) |
| `shape.cross` / `shape.xcross` | `shape: 'cross'` / `'xcross'` (2.4.0) |
| `plotcandle(wickcolor = ...)` | `plot.colorParts` returning `{ body, wick, border }` (2.4.0) |
| `label.new(..., tooltip = ...)` | `tooltip` on a `draws()` label or box (2.4.0) |
| `table.new(..., text_size = size.auto)` | `table` options `fontSize: 'auto'` (2.4.0) |
| `indicator(precision = n)` | `style.precision: n` on the plot that owns the pane, never an input |

Then the two that need thought:

**A higher-timeframe request on the chart's own symbol.** From 2.4.0 this is
`securitySeries(bars, interval, opts)`: one fold, three readings. The default
reads the bucket as it stood at that bar and never uses a later one, which is
what the live bar sees and what a non-repainting port wants. `offset: 1` is
the last completed bucket, the `close[1]` pattern. `lookahead: true` is the
source's `lookahead_on`: it reads final values on every bar of the bucket and
repaints, so use it only to reproduce a source that did. Pass
`session: '0915-1530'` so a 30-minute bucket on a 09:15 open runs 09:15 to
09:45 rather than 09:00 to 09:30. On an older pin, fold by hand with
`bucketStartOf` / `zonedDayIndex`, and say which reading you chose.

**A request against another symbol.** A screener over a pasted list of tickers
is not a chart study and cannot be expressed: `calc` is flushed every frame,
and forty requests belong to a scanner page. A single benchmark (a ratio, a
beta, a spread) can be, from 2.4.0, through `ctx.requestBars` on the attach
context or a Tier-2 descriptor's `series` and `calc`. `/trading` registers the
provider, so this works here today; fetch in `attach`, stash in `store`, call
`requestRecompute()`, and read it in `calc`. On a host that registers none the
request rejects, which the study should publish as unsupported.

**Anything drawn at a future bar.** Two cases, and they differ. A `draws()`
line, box or label anchored at a time past the last bar renders: the time
scale extrapolates at the last bar spacing, so a right-margin tag, a projected
zone or a `bar_index + 3` label works today. A **plot column** cannot reach
past the last bar, because a column is one value per bar; from 2.4.0
`plot.offset: n` paints it `n` bars ahead instead, which is what a displaced
cloud or `plot(x, offset = n)` means. On an older pin, shift the meaning back
onto existing bars, or drop it and record the gap.

## Two layers of validation

`validate.mjs` is a pre-flight check, and it is the one that can refuse to
install. The chart validates again at load time, in the browser, where the
library already is: it checks the descriptor before it reaches the catalogue,
and wraps `calc` so its first result is measured against the bars. Anything
wrong surfaces as a toast naming the file.

That second layer is why a trader with no Node.js at all still gets told what is
wrong instead of an indicator that quietly draws nothing.

## What the file has to look like

Plain JavaScript. Nothing compiles it: no TypeScript, no JSX, no imports. The
module default-exports one function and is handed the whole charting API.

```js
export default function ({ registerIndicator, sourceValues, sma, nulls }) {
  registerIndicator({
    id: 'my-thing',        // unique slug; prefix your own to avoid overriding a built-in
    name: 'My Thing',      // picker and legend
    category: 'Custom',    // groups it in the picker rail
    placement: 'onchart',  // 'onchart' overlays price, 'pane' gets its own pane
    inputs: [ ... ],       // becomes the settings dialog
    plots: [ ... ],        // each key must appear in what calc returns
    calc(bars, settings, store) {
      return { /* one array per plot key, exactly bars.length long */ }
    },
  })
}
```

A `bar` is `{ time, open, high, low, close, volume }` with `time` in **UTC
seconds**.

## What the library gives you

The descriptor is much wider than the plot-plus-calc it started as. Before
hand-rolling anything, check whether one of these already covers it:

| Want | Use |
| --- | --- |
| A trendline, zone, box or free label | `draws(ctx)` |
| Shade the pane by state | `background(ctx)` |
| Repaint the price candles | `barColors(ctx)` |
| A horizontal level from the data | `levels(ctx)`, which receives `bars` and `values` |
| A condition the chart watches | `alerts[]` with a `when(ctx)` predicate |
| One plot on price from a pane study | `plot.overlay: true` |
| Candles or bars as a plot | `plot.ohlc: { open, high, low, close }` |
| Know the bar state, symbol, interval, clock | the 4th `calc` argument |
| The instrument's tick size | `ctx.tickSize`, never an input for it |
| The decimals your plots print at | Nothing: it follows the pane, see below |
| Parse a session window | `parseSessionSpec`, `inSessionAt`, `sessionFlags` |
| Reason about the timeframe | `intervalParts`, `isIntradayInterval`, ... |
| A colour ramp or alpha | `fromGradient`, `withAlpha` |
| Pivots, rank, correlation, linreg | `pivotHigh`, `pivotLow`, `percentRank`, `correlation`, `linreg`, ... |
| A higher timeframe of the chart's own bars | `securitySeries(bars, interval, opts)` (2.4.0), never a hand-rolled fold |
| A plot painted N bars ahead | `plot.offset` (2.4.0) |
| Another instrument's bars | `ctx.requestBars` on the attach context (2.4.0), once the host registers a provider |
| A table positioned, sized or coloured per cell | `table()` `options` (`position`, `cellWidth`, `widthPercent`, `fontSize`) and `TableCell` `bgColor` / `textColor` |
| A dotted reference line | `levels()` entries take `lineStyle: 'dotted'` |
| **Any built-in's maths** | `getIndicator(id).calc(bars, settings, {})`, never a reimplementation |

Full list in `reference/api.md`, which is generated from the installed build.

## The four things that go wrong most

Full list in `reference/pitfalls.md`. These four account for most failures:

1. **Column length.** Every array must be exactly `bars.length`. Short arrays do
   not error, they just stop drawing partway.
2. **Warmup.** Use `null` (or `nulls(...)` on a helper's NaN output). A `0` puts
   a spike at the bottom of the pane and wrecks autoscale.
3. **`na` semantics.** Script languages with a not-available value treat every
   comparison against it as false. In
   JavaScript `5 > null` is **true**. Guard with `x != null` or signals fire
   through the warmup gap.
4. **Marker anchoring.** `aboveBar` / `belowBar` anchor to *this indicator's own
   plot line*, not to the candle. To place a label relative to a bar, use
   `position: 'atPrice'` with an explicit price.

## Do not

- Add colour or line-width inputs **for plots**. The chart generates colour,
  opacity, thickness, line style and plot style per plot automatically, seeded
  from each plot's `style`. Your own width input becomes a second control that
  disagrees. That rule is about plots only: a colour that `markers()`,
  `draws()` or `background()` reads has no generated control, so a
  `type: 'color'` input for it is right (the source's `input.color` for a
  marker maps to exactly that), and a `fills` band takes its colours through
  `colorUpKey` / `colorDownKey`.
- Reuse a built-in id unless overriding it is the actual intent. Custom modules
  register last, so they win. The validator warns on this.
- Add a precision or decimals input. Precision follows the pane, not the
  descriptor, so there is nothing to declare and an override would only let a
  plot disagree with the axis it is drawn against. An `onchart` plot is a price
  and prints at the instrument's tick (Supertrend on a 0.05 tick reads
  `1339.70`); a plot on its own pane prints at that pane's own span with a floor
  of two decimals (an RSI reads `70.00`, a percentage study `0.61`). A study pane
  is not quoted in the instrument's tick, because an RSI is a dimensionless
  0..100 band. If a plot of yours really is a price, put it on the candles with
  `overlay: true` rather than reaching for a precision knob. A source's
  `indicator(precision = n)` is a declared `style.precision: n` on the plot
  that owns the pane, which is a style the chart honours, not an input the
  user can turn.
- Add an input for the tick size. `ctx.tickSize` carries it, and an
  input is a second source of truth that disagrees with the axis. Point value is
  the exception: the chart does not know it, so that one is an input at 1.
- Assume the browser's local time. Use `zonedDayIndex` /
  `utcSecondsToZonedParts` with a zone, defaulting to `DEFAULT_TIMEZONE`.

## Where things live

| Path | |
| --- | --- |
| `strategies/indicators/*.js` | installed indicators, gitignored, never pushed |
| `.claude/skills/chart-indicator/validate.mjs` | the gate |
| `.claude/skills/chart-indicator/examples/` | twelve validated worked examples |
| `.claude/skills/chart-indicator/reference/` | contract, API surface, pitfalls, cookbook |
| `.claude/skills/chart-indicator/coverage.mjs` | fails if an API or capability is documented but never demonstrated |
| `.claude/skills/chart-indicator/generate-api-index.mjs` | regenerates the export index in `reference/api.md`; `--check` fails when it is stale |
| `docs/custom-indicators.md` | the user-facing guide |
| `blueprints/custom_indicators.py` | serves the folder to the chart |
| `frontend/src/lib/trading/customIndicators.ts` | the loader |

Indicators are loaded over HTTP at runtime, not bundled, so they survive
`git pull` and need no rebuild. They run with full access to the logged-in
session: treat an indicator file from an untrusted source as you would any
script you are about to run.
