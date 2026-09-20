# The descriptor contract

What `registerIndicator` accepts, and what the runtime actually does with it.
Behaviour here is read from `openalgo-charts` `src/model/indicator-instance.ts`,
not inferred from the type declarations.

## Shape

```js
{
  id: string,                    // required, unique registry key
  name: string,                  // required, picker + legend
  category?: string,             // picker rail grouping; 'Custom' by convention
  placement: 'onchart' | 'pane', // required
  inputs: IndicatorInput[],      // required (use [] for none)
  plots: IndicatorPlot[],        // required, at least one
  fills?: IndicatorFillSpec[],           // each may carry overlay: true (2.4.0)
  calc(bars, settings, store, ctx?): IndicatorValues,   // required; a throw is reported, not fatal (2.4.0)
  calcTail?(bars, settings, fromIndex, previous, store, ctx?),
  markers?({ bars, values, settings }),
  draws?({ bars, values, settings }),          // 1.7.1
  levels?(ctx),                                // 1.7.1: ctx carries bars + values
  range?(settings),
  table?({ bars, values, settings }),
  background?({ bars, values, settings }),     // 1.8.1
  barColors?({ bars, values, settings }),      // 1.8.1
  alerts?: IndicatorAlertSpec[],               // 1.8.1
  attach?(ctx),
}
```

## The calculation context (1.8.1)

`calc` and `calcTail` take an optional trailing `ctx`. Optional and last, so
nothing written before it changes.

```js
calc(bars, settings, store, ctx) {
  // ctx.barState.isNew        the last update appended a bar
  // ctx.barState.isConfirmed  the last bar is closed, not still forming
  // ctx.barState.isRealtime   a live feed is driving updates
  // ctx.barState.lastIndex
  // ctx.symbol, ctx.interval  may be undefined, see below
  // ctx.timezone, ctx.now()
  // ctx.tickSize             1.8.2, the instrument tick, or undefined
}
```

### Tick size and point value

`ctx.tickSize` is the instrument's tick, taken from the pane's price scale
`minMove`. It is the same number the axis formats to and `snapToTick` snaps to,
so **read it rather than adding an input for it**.

It is `undefined` when the host has not set `minMove`. The scale treats 0 as
"infer precision from the visible range", which is not a tick size, so guard:

```js
const tick = Number(ctx?.tickSize) || 0
const snap = (v) => (Number.isFinite(v) && tick > 0 ? Math.round(v / tick) * tick : v)
```

**Snap any level a trader would act on.** A stop, a band edge, an entry level: a
price sitting between two valid ticks cannot be traded. Do not snap a smoothed
average or an oscillator, where the extra precision is the point.

**Point value has no equivalent.** The chart knows what an instrument's prices
look like, not what a point of it is worth. If a study needs it, take it as an
input and default it to 1, which is correct for Indian equities, futures and
options.

`symbol` and `interval` are `undefined` under a plain `chart.addIndicator`: the
engine is handed bars and never an instrument. A host that knows them supplies
them through its own `IndicatorHost`. Always guard.

## Drawings (1.7.1)

`draws(ctx)` returns free-standing geometry anchored to `{ time, price }`:

| kind | shape |
| --- | --- |
| `line` | `from`, `to`, plus `extendLeft` / `extendRight` |
| `box` | `from`, `to`, `fillColor`, `opacity`, `text` |
| `label` | `at`, `text` (splits on `\n`), `align` |
| `polyline` | `points[]`, `closed`, `fillColor` |

Anchors are **times, not indices**: paging history in shifts every index, so an
index-anchored trendline slides off its pivots. The layer contributes nothing to
autoscale, and shapes fully off-pane are culled.

## Background and bar colours (1.8.1)

```js
background: ({ bars, values }) => bars.map((b, i) => cond(i) ? '#26a69a22' : null),
barColors:  ({ bars, values }) => bars.map((b, i) => cond(i) ? '#26a69a' : null),
```

One entry per bar, exactly `bars.length` long, `null` to leave a bar alone.
`background` shades the pane behind the plots; `barColors` repaints the **main
price candles**, overriding the up/down verdict for that bar. Removing the
indicator restores the original colours, and the shared bar data is never
mutated.

## Candle and bar plots (1.8.1)

A plot may be fed by four columns instead of one:

```js
plots: [{ key: 'ha', type: 'candlestick', title: 'Heikin Ashi',
          ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } }]
calc: () => ({ o: [...], h: [...], l: [...], c: [...] })
```

The plot key is only a label. A missing or wrong-length column throws out of
`addIndicator`.

## Alerts (1.8.1)

```js
alerts: [{
  id: 'cross-up',
  title: 'Close crossed above the mean',
  message: 'optional, defaults to title',
  when: ({ bars, values, settings, index }) => /* boolean */,
}]
```

Evaluated **once per bar, only on a tail-only change**. Loading history,
changing settings, paging history and switching symbol fire nothing. Delivery is
`chart.on('indicator:alert', cb)` with `{ indicatorId, instanceId, alertId,
title, message, time, index }`.

`ctx.emit(event, payload)` on the attach context covers the imperative case.

The development candidate also exports `AlertController` for trader-created
price, study-plot, drawing and named candle conditions. These use
`alert:triggered`, whose delivery fields `alertId`, `title`, `message`, `time`
and `index` match the descriptor event above. The terminal displays both locally;
neither event places an order. A trader alert defaults to `onBarClose` and
`once`. Descriptor alerts retain their existing timing contract.

Saved chart studies carry `instanceId` so plot alerts restore to the same study.
An indicator template deliberately drops this identity when creating a new
instance. Custom hosts must restore drawings before their alerts and retain
unrelated alert/drawing documents when applying a partial chart restore.

The context-menu target identifies a clicked study plot with `instanceId` and
`plotKey`. Legend targets omit `plotKey`. Use the clicked logical index to seed
its reading, and keep absent readings unavailable rather than substituting zero.
Named workspace alert lifecycle snapshots are isolated by account and pane and
merged only onto matching saved definitions before evaluation resumes. This
preserves a fired once-only record when workspace autosave is off; it does not
implicitly save new alert definitions or changed conditions.

## Bars

```js
{ time: number,   // UTC SECONDS, not milliseconds
  open: number, high: number, low: number, close: number,
  volume?: number,
  oi?: number }
```

`oi` is a level, not a flow. When folding bars, retain the latest defined
reading in the bucket and never sum readings. Zero is a real value; absence
means unavailable. Instrument capability is separate from per-bar availability:
`chart.hasOpenInterest` is true for a supported instrument, false for an
unsupported one, and undefined when metadata is unknown. A supported instrument
can still have no reading on its forming candle.

`volume` is genuinely optional. Index series carry none, so guard any divide by
it.

## `calc` and how its output is consumed

**When it runs (changed in 1.8.4).** A data update marks the indicators stale and
schedules a frame; `calc` runs in that frame, before the paint. So it is called
**once per frame, not once per tick**, and a burst of ticks between two frames
collapses into a single call. Reading `chart.indicators()`, or an instance's
`values()`, flushes any pending recompute first, so a caller that updates a bar
and reads a value back in the same turn still gets the fresh number.

Two consequences for a descriptor:

- **`calc` must be a pure function of `(bars, settings)`.** It always had to be,
  but before 1.8.4 it happened to run on every tick, so an indicator that counted
  its own calls or accumulated into `store` could look like it worked. It no
  longer will: the number of calls is now a property of the frame rate.
- Do not use `calc` as a tick hook. If you need per-tick work, that is what
  `attach` and its own subscription are for.

The runtime does this, per plot, every recompute:

```js
const col = values[plot.key]
if (col === undefined) { series.setData([]); continue }   // plot draws NOTHING
for (let i = 0; i < bars.length; i++) {
  const v = col[i]
  const value = (v === null || v === undefined) ? NaN : v
  ...
}
```

Three consequences that matter:

- **A missing plot key is silent.** The series is emptied, no error.
- **Length is not checked.** Iteration is over `bars.length`, so a short column
  reads `undefined` past its end (drawn as a gap) and a long one has its tail
  ignored. Neither raises.
- **`null`, `undefined` and `NaN` are equivalent** and all become gaps. The
  declared type is `number | null`; the shipped helpers emit `NaN` and `nulls()`
  converts. Either is safe. `0` is not a gap and will distort autoscale.

Non-finite points break the line renderer cleanly and are skipped by autoscale,
which is exactly what a warmup gap should do.

## Inputs

| type | Renders as | Extra |
| --- | --- | --- |
| `number` | number box with steppers | `min`, `max`, `step` |
| `boolean` | tick box | |
| `color` | colour swatch | |
| `text` | text box | |
| `select` | dropdown | `options: [{ label, value }]` |
| `source` | price-source dropdown | default must be a valid source |
| `interval` | timeframe select (2.4.0) | a code the engine can bucket by; `''` means the chart's own interval |
| `time` | wall-clock text (2.4.0) | `YYYY-MM-DD HH:MM` in the chart zone; `zonedStringToUtcSeconds` makes a bar time |

Every input needs `key`, `type`, `label`, `default`. Valid sources: `open`,
`high`, `low`, `close`, `hl2`, `hlc3`, `ohlc4`, `volume`.

**Those eight are the whole union** (six before 2.4.0). There is no `session`,
`symbol`, `price` or `enum` input type. A renderer switches on `input.type`
with no default case, so an unrecognised type is dropped in silence: the
default still applies and the study computes correctly, while the control never
appears and the user cannot change it. A session is a `text` input you parse
yourself; a fixed set of choices is a `select`. `/trading`'s own dialog
whitelists input types, so `interval` and `time` reach it only once it lists
them; on an older host they are dropped the same silent way.

Any input may also carry `tooltip` (2.2.1), help text the dialog renders as a
focusable `?` beside the label. A label has to stay short enough for a dense
panel, so put the explanation here rather than in a parenthetical:

```js
{ key: 'per', type: 'number', label: 'Days per bar unit', default: 1, min: 1,
  tooltip: 'Calendar days each bar covers: 1 for intraday and daily, 7 for weekly and above.' }
```

An empty string draws nothing, which is the difference between no help and a
mark with nothing behind it.

A cleared text or number field arrives as `''`, not as the default. Always
coerce: `Math.max(2, Math.floor(Number(settings.length) || 20))`.

`group` buckets inputs in the dialog.

## Plots

```js
{ key: 'ma',                 // must match a calc output key
  type: 'line',              // registered chart type
  title: 'MA',               // legend label
  style: { color: '#4f8cff', lineWidth: 2, lineStyle: 'dashed' },
  priceScaleId: 'right',     // own axis if you name a different one
  priceFormat: { type: 'percent' },  // 2.2.1: axis/crosshair format for this plot's scale
  offset: 26,                // 2.4.0: paint the column 26 bars to the right (a displaced cloud)
  colorKey: 'lineColor',     // optional: an input key holding the colour
  colorBy({ value, index, values, settings }) { return '#ef5350' },
  colorParts({ value, index, values, settings }) { return { body: '#ef535080', wick: '#ef5350' } } }  // 2.4.0, candle plots
```

Single-column plot types: `line`, `line-markers`, `step`, `area`, `histogram`,
`column`. The full registry also has `candlestick`, `hollow-candle`,
`volume-candle`, `bar`, `high-low`, `hlc-area`, `baseline`, which expect richer
data and are rarely right for an indicator.

`colorBy` is a **function**, not the name of a column: passing a string means the runtime calls it, and the chart dies with `a is not a function`. It reaches the renderer as `Bar.color`, so every Family-A plot type honours it: `histogram`, `column`, candles, OHLC bars, `line`, `step` and `area`. It is skipped for non-finite
values.

**Style controls are generated for you.** `indicatorStyleInputs` derives colour,
opacity, thickness, line style and plot style per plot, defaulting from
`plot.style.color` (or the input named by `colorKey`) and `plot.style.lineWidth`.
Do not hand-roll them.

## Fills

Shade the area between two plots.

```js
fills: [{ between: ['upper', 'lower'], colorUp: '#4f8cff', colorDown: '#4f8cff', opacity: 0.08 }]
```

Both keys must name real plots. `colorUp` applies where the first plot is above
the second, `colorDown` where it is below, so pointing them at two different
colours makes the band recolour where the series cross. Point both at the same
colour to keep one tint regardless.

`colorUpKey` / `colorDownKey` take the colour from an **input** key instead of a
literal, which is what makes a ribbon restyleable from the settings dialog. They
name an input, never a plot style, so a shaded indicator has to declare colour
inputs even though plain plots do not need them.

**A fill draws only where both endpoints are non-null.** That single rule is how
Supertrend and HalfTrend get a ribbon that flips sides and recolours with the
trend, with no per-bar colour logic:

```js
// The level is split in two. Each carries null while the other is active, so
// the line recolours at a flip and each ribbon appears only in its own trend.
plots: [
  { key: 'up',       type: 'line', colorKey: 'upColor' },
  { key: 'down',     type: 'line', colorKey: 'downColor' },
  { key: 'upEdge',   type: 'line', colorKey: 'upColor' },
  { key: 'downEdge', type: 'line', colorKey: 'downColor' },
],
fills: [
  { between: ['up', 'upEdge'],     colorUpKey: 'upColor',   colorDownKey: 'upColor',   opacity: 0.15 },
  { between: ['down', 'downEdge'], colorUpKey: 'downColor', colorDownKey: 'downColor', opacity: 0.15 },
]
```

Worked out in full in `examples/shaded_trend_zone.js`.

## Markers

```js
{ time,                    // must equal a bar's time exactly
  position,                // 'aboveBar' | 'belowBar' | 'inBar' | 'atPrice'
  price,                   // required for 'atPrice'
  shape,                   // arrowUp arrowDown circle square triangleUp
                           // triangleDown diamond flag text labelUp labelDown
  size,                    // 'tiny' | 'small' | 'medium' | 'big'
  color, text }
```

Runs after every `calc` and is handed the values it just produced. Returning
`[]` clears the layer, which is how a `showSignals` toggle should work.

**Anchoring.** The renderer resolves `aboveBar` from `a.high` and `belowBar`
from `a.low`, where `a` is a point of **the series the markers are attached to**.
For an indicator that is its own plot, so on an overlay both resolve against your
line, not the candle. `atPrice` uses `price` directly and adds no padding, so
compute the gap yourself and scale it to the instrument.

`labelUp` puts the plate below the anchor with the tail pointing up; `labelDown`
puts it above with the tail pointing down. Plate text colour is automatic.

## Levels, range, table

```js
levels: (settings) => [{ price: 70, title: '70', color: '#ef5350', lineStyle: 'dotted', lineWidth: 1 }]
range:  (settings) => ({ min: 0, max: 100 })     // or null
table:  (ctx) => ({
  rows: [
    [{ text: 'VWAP', bold: true }, { text: '123.45', align: 'right' }],
    [{ text: 'Side' }, { text: 'Above', bgColor: '#26a69a' }],   // textColor derives from bgColor
  ],
  options: { position: 'top-right', cellWidth: [64, 80], cellHeight: 18, fontSize: 11 },
})   // or null
```

A level's `lineStyle` is `'solid' | 'dashed' | 'dotted'` (a Pine `hline` with
`line.style_dotted` maps directly); `dashed: true` is the older two-state form
and `lineStyle` wins when both are given.

`range` applies only when the indicator created its own pane; two indicators
sharing a pane would otherwise fight over it. It is a fixed range, so navigation
and the automatic-range animation added in 2.1.8 leave it authoritative.

`table` is for things that are not a value per bar, such as a scoreboard or a
seasonality matrix. Its `options` are the whole `ChartTableOptions` geometry:
`position` (nine keywords, `top-left` through `bottom-right`), `margin`,
`cellWidth` (a number or a per-column array), `cellHeight`, `widthPercent` /
`heightPercent` to stretch to a share of the plot, `rowWeights`, `fontSize`
(a number, or `'auto'` from 2.4.0 to fit each cell), `borderColor`,
`borderWidth` and `background`. Each cell is a `TableCell` with `text`,
`bgColor`, `textColor`, `align`, `fontSize` and `bold`. So a source's dashboard
position, size, text size and per-cell colours all port; what does not exist is
a cell tooltip.

## calcTail

```js
calcTail(bars, settings, fromIndex, previous, store) -> values | null
```

Called **instead of** `calc` when only the tail changed. The runtime uses it when
`bars.length === previousCount` or `previousCount + 1`, passing
`fromIndex = previousCount - 1` (the previously-last bar may have been replaced
by a tick). Return values for `[fromIndex, bars.length)`, which the runtime
splices onto the previous result, or `null` to fall back to a full `calc`.

Without it a recompute is a full pass over every bar. **Since 1.8.4 that is paid
once per animation frame, not once per tick**: the engine marks the indicators
stale on a data update and flushes them before the next paint, so a burst of
ticks between two frames costs one recompute rather than one per tick. That
removed the tick-rate problem, so `calcTail` now only matters when a single pass
over the loaded history is itself too slow, which means deep history rather than
a fast feed.

No built-in implements `calcTail` today. Reach for it when your `calc` is heavy
and the chart carries tens of thousands of bars, not by default.

**If you also implement `markers`, skip `calcTail`**: markers re-run in full
after every recompute, so it saves nothing.

A `calcTail` that disagrees with `calc` makes the live chart differ from what a
reload shows. The validator checks the two agree at the boundary index.

## The attach context

`attach(ctx)` runs once per instance and returns a teardown function. It is how
an indicator that owns external data fetches it, and it is the only hook that
can reach the chart rather than just the bars.

```js
attach(ctx) {
  ctx.settings()          // live settings, read at call time
  ctx.bars()              // the chart's current source bars
  ctx.store               // the same scratch object calc receives
  ctx.requestRecompute()  // re-run calc and repaint, after data arrives
  ctx.timezone()          // the chart's configured zone
  ctx.now()               // UTC seconds from the chart clock
  ctx.paneIndex()         // which pane this instance landed on
  ctx.symbol?.()          // may be undefined: the engine is handed bars
  ctx.interval?.()        // may be undefined, same reason
  ctx.addPrimitive(p)     // attach your own IPrimitive to this indicator's pane
  ctx.removePrimitive(p)  // and detach it; do this in the teardown
  ctx.emit(event, data)   // imperative alert, alongside the declarative slot
  return () => { /* teardown: remove primitives, cancel timers, close sockets */ }
}
```

`requestRecompute` is the one to understand: `calc` is pure and synchronous, so
anything asynchronous lands in `store` and then asks for a recompute. Everything
returned from `attach` must be undone in the teardown, or a symbol change leaks
it.

`addPrimitive` / `removePrimitive` are the escape hatch for drawing something the
descriptor cannot express. Prefer `draws()`, which needs no lifecycle management.

## attach (Tier 2)

For data the chart does not have. Prefer `createTier2Indicator`, which wraps
`fetch` / `subscribe` into an ordinary descriptor:

```js
createTier2Indicator({
  id, name, placement, inputs, plots,
  refetchOn: ['symbol'],
  async fetch({ settings, bars, from, to }) {
    return [{ time: 1700000000, values: { oi: 12345 } }]
  },
  subscribe({ settings }, push) { return () => {} },
})
```

Each bar takes the most recent external point **at or before** its time. Never
interpolated, never forward-looking; bars before the first point are `null`.

## Registration order

The chart imports the built-in tier first, then user modules, so a custom
indicator with a built-in id **overrides** it. Prefix your ids.
