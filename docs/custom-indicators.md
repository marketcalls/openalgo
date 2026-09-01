# Custom Chart Indicators

Write your own indicators for the `/trading` charting terminal.

Drop a `.js` file into `strategies/indicators/`, open the indicator picker, and
it is there alongside the 102 built-ins. No build step, no Node.js, no restart of
OpenAlgo, no page reload.

## Only add indicators you have read

An indicator file is **not sandboxed**. It is JavaScript running on the OpenAlgo
origin with your logged-in session, so it can call `/api/v1/` and place orders,
read your positions, and send data anywhere. It is not a sandboxed scripting
language. It is closer to pasting a script into the browser console.

Treat an indicator copied from a forum, a chat group or a stranger exactly as you
would treat any script you are about to run on your trading machine: read it
first, or do not add it. Nothing sits between dropping a file in this folder and
it running against your live broker session.

---

## Contents

- [How it works](#how-it-works)
- [Your first indicator](#your-first-indicator)
- [The descriptor](#the-descriptor)
  - [Inputs](#inputs)
  - [Plots](#plots)
  - [calc](#calc)
  - [Optional fields](#optional-fields)
- [The API you are handed](#the-api-you-are-handed)
- [Signal markers](#signal-markers)
- [Shading between two series](#shading-between-two-series)
- [Shading, painting and alerts](#shading-painting-and-alerts)
- [Candles as a plot](#candles-as-a-plot)
- [Sessions, timeframes and colours](#sessions-timeframes-and-colours)
- [Knowing what the chart is doing](#knowing-what-the-chart-is-doing)
- [Tick size and point value](#tick-size-and-point-value)
- [Indicators that need external data](#indicators-that-need-external-data)
- [Worked example: Open Range Breakout](#worked-example-open-range-breakout)
- [Porting from other charting scripts](#porting-from-other-charting-scripts)
- [Troubleshooting](#troubleshooting)

---

## How it works

`strategies/indicators/` is gitignored, exactly like `strategies/scripts/` is for
your Python strategies. What you write there stays on your machine, is never
pushed, and survives `git pull`. On Docker the folder is already inside the
`openalgo_strategies` named volume, so it persists across container rebuilds.

The chart loads your files over HTTP at runtime rather than compiling them in:

```
/trading  ->  terminal.ts loadIndicators()
                 1. import 'openalgo-charts/indicators'      (the 102 built-ins)
                 2. GET /custom-indicators/index.json        (your file list)
                 3. import each /custom-indicators/<file>.js
                 4. call its default export with the charting API
```

Your modules register **after** the built-ins, so an indicator that reuses a
built-in id overrides it rather than being overridden.

**Why runtime and not bundled.** `frontend/dist/` is built by CI from what is
committed to the repository. A bundled indicator would have to be committed
first, and the next `git pull` would overwrite `dist/` with a build that does not
contain yours. Loading over HTTP keeps your indicators outside the build
entirely.

The trade-off is that these are plain `.js` files, not TypeScript. Nothing
compiles them, so use plain JavaScript with no types, no JSX and no imports.

---

## Your first indicator

Save this as `strategies/indicators/my_sma.js`:

```js
export default function ({ registerIndicator, sourceValues }) {
  registerIndicator({
    id: 'my-sma',
    name: 'My SMA',
    category: 'Custom',
    placement: 'onchart',
    inputs: [
      { key: 'length', type: 'number', label: 'Length', default: 20, min: 1, step: 1 },
      { key: 'source', type: 'source', label: 'Source', default: 'close' },
    ],
    plots: [
      { key: 'ma', type: 'line', title: 'MA', style: { color: '#4f8cff', lineWidth: 2 } },
    ],
    calc(bars, settings) {
      const src = sourceValues(bars, settings.source)
      const n = Number(settings.length)
      const ma = new Array(bars.length).fill(null)
      let sum = 0
      for (let i = 0; i < src.length; i++) {
        sum += src[i]
        if (i >= n) sum -= src[i - n]
        if (i >= n - 1) ma[i] = sum / n
      }
      return { ma }
    },
  })
}
```

Open the indicator picker on `/trading` and **My SMA** is under a **Custom**
category. No page reload: the picker re-reads the folder every time it opens, so
a file you just added appears immediately, and a file you just edited is
re-imported because the chart cache-busts on its modification time.

Two rules that are easy to miss:

- The module **default-exports a function**. It is called once with the charting
  API. A file that exports nothing, or exports an object, is reported as an
  error.
- `calc` returns **one array per plot key, the same length as `bars`**, using
  `null` for warmup. `null`, `undefined` and `NaN` are all treated as gaps: the
  line renderer breaks across them and autoscale skips them. `0` is **not** a
  gap, and putting one in a warmup slot drags the whole pane's scale down.

---

## The descriptor

```js
registerIndicator({
  id: 'my-thing',        // registry key, unique
  name: 'My Thing',      // shown in the picker and the legend
  category: 'Custom',    // groups it in the picker rail
  placement: 'onchart',  // 'onchart' overlays price, 'pane' gets its own pane
  inputs: [...],
  plots: [...],
  calc(bars, settings, store) { ... },
})
```

A `bar` is `{ time, open, high, low, close, volume }`, where `time` is **UTC
seconds**, not milliseconds and not local time.

### Inputs

Each input becomes a field in the settings dialog. `key` is what `calc` reads
from `settings`.

| `type` | Renders as | Extra fields |
|---|---|---|
| `number` | Number box with steppers | `min`, `max`, `step` |
| `boolean` | Tick box | |
| `color` | Colour swatch | |
| `text` | Text box | |
| `select` | Dropdown | `options: [{ label, value }]` |
| `source` | Price-source dropdown | |

Every input needs a `default`. That default is also what the dialog's
**Defaults** button restores.

You do **not** need colour or line-width inputs. The chart generates a colour,
opacity, thickness, line style and plot style control for every plot
automatically and puts them on the **Style** tab, seeded from each plot's
`style`. Declaring your own width input just gives the user two width fields
that disagree.

### Plots

```js
plots: [
  { key: 'fast', type: 'line', title: 'Fast', style: { color: '#4f8cff', lineWidth: 2 } },
  { key: 'hist', type: 'histogram', title: 'Histogram', style: { base: 0 } },
]
```

`type` is any of `line`, `line-markers`, `step`, `area`, `histogram`, `column`.
`key` must match a key in what `calc` returns.

Useful extras:

- `priceScaleId` puts a plot on its own axis (defaults to `'right'`).
- `colorBy({ value, index, values, settings })` colours a plot bar by bar, for a
  histogram that changes colour by sign. Honoured by `histogram` and `column`.

### calc

```js
calc(bars, settings, store) {
  // bars    : readonly array of { time, open, high, low, close, volume }
  // settings: current values, keyed by your input keys
  // store   : per-instance scratch object, for the external-data case
  return { fast: [...], hist: [...] }   // one array per plot key, bars.length long
}
```

`calc` runs on every data change, so keep it a single pass. Read settings
defensively (`Number(settings.length)`): a user can clear a field, and the value
arrives as `''`.

### Optional fields

| Field | What it does |
|---|---|
| `levels(settings)` | Horizontal reference lines in your pane, e.g. RSI 70/30 |
| `range(settings)` | Fixes the pane's price range, e.g. `{ min: 0, max: 100 }` |
| `markers(ctx)` | Bar-anchored signal labels, see below |
| `fills` | Shades the band between two plots, e.g. a Bollinger channel |
| `table(ctx)` | A summary grid pinned in the pane corner |
| `calcTail(...)` | Incremental recompute for live ticks, see below |
| `attach(ctx)` | Per-instance lifecycle for indicators with their own data |

**On `calcTail`.** Without it every live tick costs a full `calc`. That is a few
hundred microseconds over 50k bars, so it only matters for something running in a
busy live pane. Note that if you also implement `markers`, those re-run in full
after every recompute anyway, so adding `calcTail` alongside them saves nothing.

---

## The API you are handed

The single argument to your default export carries the whole charting library,
both the core and the indicator tier. Destructure what you need:

```js
export default function ({ registerIndicator, sourceValues, sma, rma }) { ... }
```

Commonly useful:

| Function | Use |
|---|---|
| `registerIndicator(descriptor)` | The one call that matters |
| `sourceValues(bars, source)` | Whole bar array as one price column |
| `sourceValue(bar, source)` | One bar's value for a source |
| `sma`, `wma`, `rma`, `ema`, `stdev` | Moving averages and deviation |
| `highest(values, n)`, `lowest(values, n)` | Rolling extremes |
| `nulls(n)` | An array of `n` nulls, for warmup |
| `atr`, `trueRange`, `supertrend`, `rsi` | Prebuilt studies to compose with |
| `utcSecondsToZonedParts(t, zone)` | Bar time to `{ year, month, day, hour, minute, ... }` |
| `zonedDayIndex(t, zone)` | Day bucket, for per-day logic |
| `isValidTimezone(zone)`, `DEFAULT_TIMEZONE` | Zone handling (`Asia/Kolkata`) |
| `createTier2Indicator(descriptor)` | Indicators fed by an external series |
| `indicatorDefaults`, `registeredIndicators` | Introspection |

Anything the `openalgo-charts` package exports from its root or its
`indicators` tier is on that object.

---

## Signal markers

`markers` draws a labelled plate on a bar. It runs after every `calc` and is
handed what `calc` just produced.

```js
markers({ bars, values, settings }) {
  if (settings.showSignals === false) return []   // returning [] clears the layer
  return [{
    time: bars[i].time,
    position: 'atPrice',
    price: bars[i].low - pad,
    shape: 'labelUp',      // labelUp, labelDown, arrowUp, arrowDown, circle, square, ...
    size: 'small',         // tiny, small, medium, big
    color: '#4caf50',
    text: 'Buy',
  }]
}
```

**The one trap.** `position: 'aboveBar'` and `'belowBar'` do **not** mean above
or below the candle. They resolve against the series the markers hang off, which
for an indicator is its own plot line. On an overlay indicator that means your
labels pin themselves to your line and ignore the candle entirely.

To place a label relative to the candle, use `position: 'atPrice'` with an
explicit `price`. `atPrice` adds no padding of its own, so compute the gap
yourself, and scale it to the instrument rather than hardcoding a tick count:

```js
function markerPad(bars) {
  let sum = 0, count = 0
  for (const bar of bars) {
    const range = bar.high - bar.low
    if (Number.isFinite(range) && range > 0) { sum += range; count++ }
  }
  const mean = count > 0 ? sum / count : 0
  const last = bars.length > 0 ? Math.abs(bars[bars.length - 1].close) : 0
  return Math.max(mean * 0.5, last * 0.0005)   // floor covers a run of dojis
}
```

Half a mean bar range reads the same on a 24000 index and a 100 rupee stock.

---

## Shading between two series

`fills` shades the area between two plots. Both keys must name real plots, and
the colour comes from an **input** key rather than a plot style:

```js
inputs: [{ key: 'bandColor', type: 'color', label: 'Band', default: '#4f8cff' }],
plots: [
  { key: 'upper', type: 'line', title: 'Upper' },
  { key: 'lower', type: 'line', title: 'Lower' },
],
fills: [{ between: ['upper', 'lower'], colorUpKey: 'bandColor', colorDownKey: 'bandColor', opacity: 0.1 }],
```

`colorUp` applies where the first plot is above the second and `colorDown` where
it is below, so two different colours make the band recolour where the series
cross. The same colour in both keeps one tint.

**Trend zones that flip sides, like Supertrend and HalfTrend.** A fill draws only
where *both* endpoints are non-null, and that one rule is the whole technique.
Split the level into two plots, give each `null` while the other is active, then
declare one fill per side:

```js
plots: [
  { key: 'up',       type: 'line', colorKey: 'upColor' },    // null in a downtrend
  { key: 'down',     type: 'line', colorKey: 'downColor' },  // null in an uptrend
  { key: 'upEdge',   type: 'line', colorKey: 'upColor' },
  { key: 'downEdge', type: 'line', colorKey: 'downColor' },
],
fills: [
  { between: ['up', 'upEdge'],     colorUpKey: 'upColor',   colorDownKey: 'upColor',   opacity: 0.15 },
  { between: ['down', 'downEdge'], colorUpKey: 'downColor', colorDownKey: 'downColor', opacity: 0.15 },
]
```

The line recolours at the flip because the renderer breaks across the null gap,
and each ribbon appears only during its own trend. No per-bar colour logic.

This is the one case where you should declare colour inputs. Plain plots get
their style controls generated for you, but a fill needs an input to point at.

---

## Shading, painting and alerts

Three hooks added in 1.8.1, each indexed by bar and exactly `bars.length` long,
with `null` meaning "leave this bar alone".

```js
// Shade the pane behind the plots.
background: ({ bars, values }) =>
  bars.map((b, i) => values.ma[i] == null ? null : (b.close > values.ma[i] ? '#26a69a1f' : '#ef53501f')),

// Repaint the MAIN price candles, overriding their up/down colour.
barColors: ({ bars, values }) =>
  bars.map((b, i) => values.ma[i] == null ? null : (b.close > values.ma[i] ? '#26a69a' : '#ef5350')),

// A condition the chart watches for you.
alerts: [{
  id: 'cross-up',
  title: 'Close crossed above the mean',
  when: ({ bars, values, index: i }) =>
    i > 0 && values.ma[i - 1] != null && bars[i - 1].close <= values.ma[i - 1] && bars[i].close > values.ma[i],
}],
```

Removing the indicator restores the original candle colours, and the shared bar
data is never mutated, so other indicators and the data feed are unaffected.

**Alerts fire only on new bars.** Loading history, changing a setting, paging
history in and switching symbol all fire nothing, even though `calc` re-runs over
every bar. That is deliberate: the naive version fires once per historical
crossing the moment you add the indicator. Listen with:

```js
chart.on('indicator:alert', ({ indicatorId, alertId, title, message, time, index }) => { ... })
```

## Candles as a plot

A plot can be fed by four columns instead of one, which is how a Heikin Ashi or
any custom aggregation is drawn:

```js
plots: [{ key: 'ha', type: 'candlestick', title: 'Heikin Ashi',
          ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } }],
calc: () => ({ o: [...], h: [...], l: [...], c: [...] }),
```

The plot key is only a label. A missing or wrong-length column throws rather
than silently drawing nothing.

## Sessions, timeframes and colours

The helpers that used to be hand-rolled in every ported study:

```js
const spec = parseSessionSpec('0915-1015')        // or '0930-1600:23456' for weekdays
const inWindow = inSessionAt(bars[i].time, spec, 'Asia/Kolkata')
const flags = sessionFlags(bars.map(b => b.time), '0915-1015')

isIntradayInterval(ctx.interval)                  // from the calc context
fromGradient(value, 0, 100, '#26a69a', '#ef5350') // colour ramp
withAlpha('#26a69a', 0.12)                        // alpha on any colour form
```

## Knowing what the chart is doing

`calc` takes an optional fourth argument:

```js
calc(bars, settings, store, ctx) {
  // ctx.barState.isNew / isConfirmed / isRealtime / lastIndex
  // ctx.symbol, ctx.interval   may be undefined, guard before use
  // ctx.timezone, ctx.now()
}
```

## Tick size and point value

The chart knows the instrument's tick and hands it to you, so do not add an
input for it:

```js
calc(bars, settings, store, ctx) {
  const tick = Number(ctx?.tickSize) || 0     // 0 means the host never set one
  const snap = (v) => (Number.isFinite(v) && tick > 0 ? Math.round(v / tick) * tick : v)
  ...
}
```

Snap the levels a trader would place an order at, such as stops, band edges and
entry levels: a price between two valid ticks cannot be traded. Leave moving
averages and oscillators alone, where the extra precision is the point.

**Point value is different.** Nothing in the chart describes what one point of an
instrument is worth, so a study needing it takes an input defaulting to 1, which
is correct for Indian equities, futures and options.

## Indicators that need external data

If your indicator plots something that is not derived from the chart's own OHLCV
(open interest, PCR, a series your own API computes), use `createTier2Indicator`.
You supply `fetch`, it returns an ordinary descriptor:

```js
export default function ({ registerIndicator, createTier2Indicator }) {
  registerIndicator(createTier2Indicator({
    id: 'my-oi',
    name: 'Open Interest',
    placement: 'pane',
    inputs: [{ key: 'symbol', type: 'text', label: 'Symbol', default: '' }],
    plots: [{ key: 'oi', type: 'line', title: 'OI' }],
    refetchOn: ['symbol'],                      // settings that invalidate the data
    async fetch({ settings, from, to }) {
      const res = await fetch(`/api/v1/...`)    // your own endpoint
      return (await res.json()).map((row) => ({ time: row.t, values: { oi: row.oi } }))
    },
  }))
}
```

Each bar takes the most recent external point **at or before** its time. Values
are never interpolated and never forward-looking, and bars before the first point
are `null`.

---

## Worked example: Open Range Breakout

> This example hand-rolls its session parsing, because it predates
> `parseSessionSpec`. It still runs, and it is a good read for the signal
> latch and the marker padding. For anything new, use `parseSessionSpec` and
> `inSessionAt` instead of the `parseSession` function below: they handle
> weekday filters and a window that wraps midnight, neither of which this does.


The opening range is the high and low of a fixed early window. Once the window
closes both levels freeze for the rest of the day and are traded as breakout
triggers. This example uses most of what the guide covers: a text input, per-day
state, `atPrice` markers and an exrem-style signal latch.

Save as `strategies/indicators/open_range_breakout.js`:

```js
const LEVEL_HIGH_COLOR = '#ff5252'
const LEVEL_LOW_COLOR = '#00e676'
const BUY_COLOR = '#4caf50'
const SELL_COLOR = '#ff5252'

export default function ({
  registerIndicator,
  utcSecondsToZonedParts,
  zonedDayIndex,
  isValidTimezone,
  DEFAULT_TIMEZONE,
}) {
  /** '0915-1015' to minutes-from-midnight bounds. Null when unparseable. */
  function parseSession(raw) {
    const m = /^(\d{2})(\d{2})\s*-\s*(\d{2})(\d{2})$/.exec(String(raw).trim())
    if (!m) return null
    const [sh, sm, eh, em] = [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4])]
    if (sh > 23 || eh > 23 || sm > 59 || em > 59) return null
    return { start: sh * 60 + sm, end: eh * 60 + em }
  }

  // Bar times are UTC seconds and a session is wall clock at the exchange, so
  // the two only line up through a zone.
  function zoneOf(settings) {
    const raw = typeof settings.timezone === 'string' ? settings.timezone.trim() : ''
    return raw && isValidTimezone(raw) ? raw : DEFAULT_TIMEZONE
  }

  // Half-open bounds: a bar stamped exactly at the end time opens the breakout
  // window rather than closing the range. Second branch wraps midnight.
  function inSession(minuteOfDay, start, end) {
    return end > start
      ? minuteOfDay >= start && minuteOfDay < end
      : minuteOfDay >= start || minuteOfDay < end
  }

  function computeOrb(bars, settings) {
    const orbHigh = new Array(bars.length).fill(null)
    const orbLow = new Array(bars.length).fill(null)
    const win = parseSession(settings.session ?? '')
    if (!win || bars.length === 0) return { orbHigh, orbLow }

    const zone = zoneOf(settings)
    let wasIn = false
    let runHigh = Number.NEGATIVE_INFINITY
    let runLow = Number.POSITIVE_INFINITY
    let levelHigh = null
    let levelLow = null

    for (let i = 0; i < bars.length; i++) {
      const parts = utcSecondsToZonedParts(bars[i].time, zone)
      const isIn = inSession(parts.hour * 60 + parts.minute, win.start, win.end)

      if (isIn && !wasIn) {
        runHigh = Number.NEGATIVE_INFINITY
        runLow = Number.POSITIVE_INFINITY
      }
      if (isIn) {
        if (bars[i].high > runHigh) runHigh = bars[i].high
        if (bars[i].low < runLow) runLow = bars[i].low
      } else if (wasIn && Number.isFinite(runHigh)) {
        // First bar after the window closed: latch the level.
        levelHigh = runHigh
        levelLow = runLow
      }

      // Hidden while the range is still forming, so the line starts at the
      // breakout window instead of running back across its own session.
      orbHigh[i] = isIn ? null : levelHigh
      orbLow[i] = isIn ? null : levelLow
      wasIn = isIn
    }
    return { orbHigh, orbLow }
  }

  function computeSignals(bars, values, settings) {
    const hi = values.orbHigh ?? []
    const lo = values.orbLow ?? []
    const zone = zoneOf(settings)
    const out = []
    let isLong = false
    let isShort = false
    let prevWasNewDay = false

    for (let i = 1; i < bars.length; i++) {
      const newDay = zonedDayIndex(bars[i].time, zone) !== zonedDayIndex(bars[i - 1].time, zone)

      // Crossover / crossunder against the plotted level. Both ends must be
      // present, which is what keeps signals off a range that is still forming.
      const [prevHigh, curHigh] = [hi[i - 1], hi[i]]
      const [prevLow, curLow] = [lo[i - 1], lo[i]]
      let buy =
        prevHigh != null && curHigh != null && bars[i - 1].high <= prevHigh && bars[i].high > curHigh
      let sell =
        prevLow != null && curLow != null && bars[i - 1].low >= prevLow && bars[i].low < curLow

      // exrem: one signal per direction until the other side fires.
      buy = buy && !isLong
      sell = sell && !isShort
      if (buy) { isLong = true; isShort = false }
      if (sell) { isLong = false; isShort = true }
      if (prevWasNewDay) { isLong = false; isShort = false }

      if (buy) out.push({ index: i, side: 'buy' })
      if (sell) out.push({ index: i, side: 'sell' })
      prevWasNewDay = newDay
    }
    return out
  }

  function markerPad(bars) {
    let sum = 0
    let count = 0
    for (const bar of bars) {
      const range = bar.high - bar.low
      if (Number.isFinite(range) && range > 0) { sum += range; count++ }
    }
    const mean = count > 0 ? sum / count : 0
    const last = bars.length > 0 ? Math.abs(bars[bars.length - 1].close) : 0
    return Math.max(mean * 0.5, last * 0.0005)
  }

  registerIndicator({
    id: 'oa-open-range-breakout',
    name: 'Open Range Breakout',
    category: 'Custom',
    placement: 'onchart',
    inputs: [
      { key: 'session', type: 'text', label: 'Breakout Timings', default: '0915-1015' },
      { key: 'showSignals', type: 'boolean', label: 'Show Buy/Sell Labels', default: true },
      { key: 'timezone', type: 'text', label: 'Session Timezone', default: DEFAULT_TIMEZONE },
    ],
    plots: [
      { key: 'orbHigh', type: 'line', title: 'ORB High',
        style: { color: LEVEL_HIGH_COLOR, lineWidth: 2 } },
      { key: 'orbLow', type: 'line', title: 'ORB Low',
        style: { color: LEVEL_LOW_COLOR, lineWidth: 2 } },
    ],
    calc: (bars, settings) => computeOrb(bars, settings),
    markers({ bars, values, settings }) {
      if (settings.showSignals === false) return []
      const pad = markerPad(bars)
      const out = []
      for (const sig of computeSignals(bars, values, settings)) {
        const bar = bars[sig.index]
        out.push(
          sig.side === 'buy'
            ? { time: bar.time, position: 'atPrice', price: bar.low - pad,
                shape: 'labelUp', size: 'small', color: BUY_COLOR, text: 'Buy' }
            : { time: bar.time, position: 'atPrice', price: bar.high + pad,
                shape: 'labelDown', size: 'small', color: SELL_COLOR, text: 'Sell' }
        )
      }
      return out
    },
  })
}
```

---

## Porting from other charting scripts

| Elsewhere | Here |
|---|---|
| `indicator(overlay=true)` | `placement: 'onchart'` |
| `indicator(overlay=false)` | `placement: 'pane'` |
| `input.int` / `input.bool` / `input.string` | `type: 'number'` / `'boolean'` / `'text'` |
| `input.session` | `type: 'text'`, parse it yourself |
| `input.source` | `type: 'source'` + `sourceValues(bars, settings.source)` |
| `plot(x)` | a plot key plus the matching array from `calc` |
| `plotshape` | `markers()` |
| `hline` | `levels(settings)` |
| `na` | `null` |
| `ta.sma` / `ta.rma` / `ta.stdev` | `sma` / `rma` / `stdev` from the API |
| `ta.valuewhen` | a latch variable in your `calc` loop |
| `var` state across bars | a variable outside the `calc` loop |
| `alertcondition` | no equivalent, use markers |

Three differences that catch people out:

1. **There is no `request.security`.** `calc` gets one bar array. Either derive
   the higher-timeframe value from the bars you have, or use
   `createTier2Indicator` to fetch it. Deriving is often more correct anyway: a
   `request.security` call on a 60-minute bar returns that whole bar's high, which
   is lookahead if your window is shorter than the bar.
2. **`na` comparisons.** In script languages built around a not-available value,
   every comparison against `na` is false. In
   JavaScript `5 > null` is `true`. Guard explicitly with `x != null` or your
   indicator will fire signals during its own warmup.
3. **`linewidth` is not yours to set.** The Style tab already generates it.

---

## Troubleshooting

**It does not appear in the picker.**
Check the file is `strategies/indicators/<name>.js`. The filename must be
`.js`, must start with a letter or digit, and cannot contain a path separator.
Then hard-refresh the chart (Ctrl+Shift+R).

**A red toast appears on the chart.**
That is the chart telling you what is wrong with your file, and the message is
the actual error. The other indicators keep working: one broken file never takes
the picker down.

The chart checks two things you cannot see otherwise. Before your indicator
reaches the catalogue it validates the descriptor, so a bad `placement` or an
unsupported input type is rejected with a reason instead of producing a picker
entry that breaks when clicked. Then it wraps `calc` and measures its first
result against the bars, which is what catches the two silent killers: a column
that is not `bars.length` long, and a plot key `calc` never filled.

**"module has no default-exported function".**
The file parsed but does not `export default function (api) { ... }`.

**Edits do not take effect.**
Close and reopen the indicator picker: that is when the folder is re-read, and
the chart cache-busts on the file's modification time. An indicator already on
the chart keeps the version it was added with until you remove and re-add it.

**The pane is flat or the line is missing.**
`calc` almost certainly returned `0` for warmup bars instead of `null`, or
returned an array that is not `bars.length` long. A short array does not error,
it just stops drawing partway across the chart.

**Settings show empty boxes with steppers.**
The input `type` is not one the dialog knows. Check it is one of `number`,
`boolean`, `color`, `text`, `select`, `source`.

**Nothing loads at all and there is no toast.**
The chart treats a missing index as "no custom indicators", which is also what a
logged-out session looks like. Confirm you are logged in, then check
`GET /custom-indicators/index.json` in the browser's network tab.
