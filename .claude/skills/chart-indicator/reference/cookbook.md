# Cookbook

Every author-facing call, demonstrated. `api.md` says what exists; this says how
each one is used. If you are about to hand-roll a formula, look here first.

Checked by `node .claude/skills/chart-indicator/coverage.mjs`, which fails if an
author-facing export is named in the docs but never appears inside real code.

---

## Reuse a built-in instead of porting its formula

**The single highest-leverage technique in this skill.** The 102 built-ins are
descriptors, and a descriptor is data plus a `calc`, so any of them doubles as a
calculation. There is no reason to reimplement MACD.

```js
export default function ({ registerIndicator, getIndicator, indicatorDefaults, hasIndicator }) {
  // Run a built-in and take its columns.
  const run = (id, bars, overrides = {}) => {
    const d = getIndicator(id)
    return d.calc(bars, { ...indicatorDefaults(d), ...overrides }, {})
  }

  // ...inside calc:
  const macd = run('macd', bars, { fastPeriod: 12, slowPeriod: 26, signalPeriod: 9 })
  //   -> { macd, signal, histogram }
  const bb = run('bollinger', bars, { length: 20, stdDev: 2 })
  //   -> { upper, basis, lower }
  const obv = run('obv', bars)          // -> { obv, ma, bbUpper, bbLower }
  const rsi = run('rsi', bars, { length: 14 })   // -> { rsi }
  const atr = run('atr', bars, { period: 14 })   // -> { atr }

  // Guard when the id is user-supplied: the tier may not be loaded.
  if (hasIndicator('supertrend')) { /* safe to getIndicator it */ }
}
```

`indicatorDefaults(d)` fills every key the descriptor declares, so overriding
only the periods keeps working if the built-in gains a setting later.

**The column names are the plot keys, and they are not the built-in's id:**

| built-in | columns |
| --- | --- |
| `sma`, `ema`, `wma`, `hma`, and the other averages | `ma` |
| `macd` | `macd`, `signal`, `histogram` |
| `bollinger` | `upper`, `basis`, `lower` |
| `rsi` | `rsi` |
| `atr` | `atr` |
| `obv` | `obv`, `ma`, `bbUpper`, `bbLower` |

`run('ema', bars).ema` is `undefined` and draws nothing. Always check:

```js
getIndicator('bollinger').plots.map((p) => p.key)   // ['upper','basis','lower']
```

Why this matters beyond brevity: a table or a signal built this way **cannot
drift** from the same indicator the user has on the chart.

```js
// What else is available to reuse, and under what id.
const catalogue = registeredIndicators().map((d) => `${d.id}: ${d.name}`)
```

---

## Moving averages

```js
export default function ({ sma, ema, smaSeededEma, wma, alma, vwma, swma, nulls }) {
  // ...inside calc, `src` is a numeric column and `bars` the source bars:
  const simple   = sma(src, 20)
  const exp      = ema(src, 20)           // seeds from src[0], matches openalgo.ta
  const expRef   = smaSeededEma(src, 20)  // seeds from the SMA, matches the common reference
  const weighted = wma(src, 20)
  const arnaud   = alma(src, 20, 0.85, 6) // offset, sigma
  const volWtd   = vwma(src, bars.map((b) => b.volume ?? 0), 20)
  const symWtd   = swma(src)              // fixed 4-bar symmetric weighting

  return { ma: nulls(expRef) }
}
```

`ema` and `smaSeededEma` disagree for roughly the first `period` bars and
converge after. Use `smaSeededEma` when reproducing a published plot.

---

## Extremes, sums and running totals

```js
export default function ({ highest, lowest, highestBars, lowestBars, rollingSum, cumulative, nulls }) {
  const hi   = highest(src, 20)        // rolling max
  const lo   = lowest(src, 20)         // rolling min
  const hiAgo = highestBars(src, 20)   // bars since that max, 0 = this bar
  const loAgo = lowestBars(src, 20)
  const sum20 = rollingSum(src, 20)
  const total = cumulative(src)        // running total from bar 0, for OBV-like series

  // Donchian mid, and "how stale is the high" as a plot.
  return { mid: nulls(hi.map((h, i) => (h + lo[i]) / 2)), staleness: nulls(hiAgo) }
}
```

---

## Statistics and oscillators

```js
export default function ({ linreg, percentRank, percentileNearestRank, correlation, stoch, cci, roc, dev, connorsStreak, nulls }) {
  const fit    = linreg(src, 20, 0)          // linear regression value, offset 0
  const rank   = percentRank(src, 50)        // where the latest sits in its own 50-bar history
  const p90    = percentileNearestRank(src, 50, 90)
  const corr   = correlation(src, other, 20) // two columns, same length
  const k      = stoch(bars.map(b => b.close), bars.map(b => b.high), bars.map(b => b.low), 14)
  const cciOut = cci(bars.map(b => (b.high + b.low + b.close) / 3), 20)
  const change = roc(src, 10)                // percent change over 10 bars
  const meanDev = dev(src, 20)               // mean absolute deviation
  const streak = connorsStreak(src)          // consecutive up or down closes, signed

  return { k: nulls(k) }
}
```

---

## Sessions and the calendar

```js
export default function ({ parseSessionSpec, inSessionAt, sessionFlags, sessionStartFlags, calendarPeriodFlags, isNewZonedDay, utcSecondsToZonedParts, zonedDayIndex, isValidTimezone, DEFAULT_TIMEZONE }) {
  const zone = isValidTimezone(userZone) ? userZone : DEFAULT_TIMEZONE
  const times = bars.map((b) => b.time)

  // A stated window, with an optional weekday filter and a midnight wrap.
  const spec = parseSessionSpec('0915-1015')        // or '0930-1600:23456'
  const inWindow = spec ? inSessionAt(bars[i].time, spec, zone) : false
  const flags = sessionFlags(times, '0915-1015', zone)   // one boolean per bar

  // Inferred boundaries, for anchoring a VWAP or a daily accumulator.
  const opens = sessionStartFlags(times, zone)      // first bar of each session
  const months = calendarPeriodFlags(times, (a, b) => isNewZonedDay(a, b, zone))

  // Calendar parts, when a rule depends on the clock rather than the session.
  const parts = utcSecondsToZonedParts(bars[i].time, zone)  // { hour, minute, weekday, ... }
  const day = zonedDayIndex(bars[i].time, zone)             // per-day bucketing
}
```

Prefer `sessionStartFlags` and `calendarPeriodFlags` to comparing bar to bar: a
session straddling a calendar boundary is not cut in half by them.

---

## Timeframes

```js
export default function ({ intervalParts, isIntradayInterval, isDailyInterval, isSecondsInterval, isTickInterval }) {
  // ...inside calc, from the 4th argument:
  calc(bars, settings, store, ctx) {
    const code = ctx?.interval
    if (!code) return { ... }                  // a host that never said

    const { multiplier, unit } = intervalParts(code) ?? {}   // '5m' -> { 5, 'm' }
    if (isTickInterval(code)) return { ... }    // no wall-clock meaning at all
    if (isSecondsInterval(code)) { ... }
    if (!isIntradayInterval(code)) { ... }      // a session window is meaningless here
    if (isDailyInterval(code)) { ... }
  }
}
```

---

## Colour, rounding and formatting

```js
export default function ({ fromGradient, withAlpha, roundToTick, precisionForStep, compactVolume, clamp, INDICATOR_SOURCES }) {
  // Heat a value across a range.
  const heat = fromGradient(rsiValue, 30, 70, '#26a69a', '#ef5350')
  const wash = withAlpha(heat, 0.15)          // same hue, low alpha, for a background

  // Snap a tradeable level, and format it to the tick's own precision.
  const tick = Number(ctx?.tickSize) || 0
  const level = tick > 0 ? roundToTick(rawLevel, tick) : rawLevel
  const label = level.toFixed(tick > 0 ? precisionForStep(tick) : 2)

  const vol = compactVolume(bars[i].volume ?? 0)   // 39.20K
  const bounded = clamp(ratio, 0, 1)

  // The canonical price sources, for a `select` that mirrors a `source` input.
  const sourceOptions = INDICATOR_SOURCES.map((s) => ({ label: s, value: s }))
}
```

`roundToTick` is the library's own rounding, so a level snapped with it agrees
with what the axis and the drawing tools do.

---

## Every plot style

A plot's `type` is any registered chart type. These six take a single column:

```js
plots: [
  { key: 'a', type: 'line', title: 'Line', style: { color: '#4f8cff', lineWidth: 2 } },
  { key: 'b', type: 'step', title: 'Step' },                      // holds until it changes
  { key: 'c', type: 'area', title: 'Area' },                      // filled to the baseline
  { key: 'd', type: 'histogram', title: 'Histogram', style: { base: 0 } },
  { key: 'e', type: 'column', title: 'Columns', style: { base: 0 } },
  { key: 'f', type: 'line-markers', title: 'Dots',
    // markersOnly draws the points without joining them: the circles style.
    style: { markersOnly: true, markerRadius: 2 } },

  // Dashed or dotted, on its own axis, coloured from an input, or hidden.
  { key: 'g', type: 'line', title: 'Dashed', style: { lineStyle: 'dashed', lineWidth: 1 } },
  { key: 'h', type: 'line', title: 'Own axis', priceScaleId: 'ratio' },
  { key: 'i', type: 'line', title: 'From input', colorKey: 'lineColor' },
  { key: 'j', type: 'line', title: 'Hidden', style: { visible: false } },

  // One plot on the price pane while the study keeps its own.
  { key: 'k', type: 'line', title: 'On price', overlay: true },

  // Four columns, drawn as candles.
  { key: 'ha', type: 'candlestick', title: 'Heikin Ashi',
    ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } },
]
```

A hidden plot is how a study that outputs only a table still satisfies the
"at least one plot" rule, and how a shared decision column is made readable by
`colorBy`, `markers`, `alerts` and `table`, none of which receive `store`.

---

## Every input type

`group` buckets them into sections in the settings dialog, which is worth doing
past about six inputs.

```js
inputs: [
  { key: 'length',  type: 'number',  label: 'Length',  default: 20, min: 1, max: 500, step: 1, group: 'Periods' },
  { key: 'enabled', type: 'boolean', label: 'Enabled', default: true, group: 'Display' },
  { key: 'lineColor', type: 'color', label: 'Line',    default: '#4f8cff', group: 'Display' },
  { key: 'note',    type: 'text',    label: 'Note',    default: '', group: 'Display' },
  { key: 'source',  type: 'source',  label: 'Source',  default: 'close', group: 'Periods' },
  { key: 'mode',    type: 'select',  label: 'Mode',    default: 'fast', group: 'Periods',
    options: [{ label: 'Fast', value: 'fast' }, { label: 'Slow', value: 'slow' }] },

  // The four semantic types. The first three are strings you parse yourself.
  { key: 'window',  type: 'session',   label: 'Session',   default: '0915-1015', group: 'Instrument' },
  { key: 'tf',      type: 'timeframe', label: 'Timeframe', default: '5m', group: 'Instrument' },
  { key: 'sym',     type: 'symbol',    label: 'Symbol',    default: '', group: 'Instrument' },
  // These two are numbers a host may also resolve from a chart click.
  { key: 'anchor',  type: 'price',     label: 'Anchor Price', default: 0, group: 'Instrument' },
  { key: 'from',    type: 'time',      label: 'Anchor Time',  default: 0, group: 'Instrument' },
]
```

Do **not** add an input for the tick size: `ctx.tickSize` carries it.

---

## Gradient fills

A fill is flat by default. `gradient` grades it between two prices, which is
what makes a band read as a scale rather than a block:

```js
fills: [
  { between: ['upper', 'lower'], colorUpKey: 'bandColor', colorDownKey: 'bandColor', opacity: 0.12 },
  { between: ['hi', 'lo'],
    gradient: { topValue: 70, bottomValue: 30, topColor: '#ef5350', bottomColor: '#26a69a' },
    opacity: 0.2 },
]
```

Omit `topValue` and `bottomValue` and the gradient spans the filled region
itself instead of being anchored in price.

---

## Tables

```js
table({ bars, values, settings }) {
  if (settings.showTable === false || bars.length === 0) return null
  const i = bars.length - 1
  const head = (t) => ({ text: t, bgColor: '#1f3a8a8c', textColor: '#e6e9ef', bold: true, align: 'center' })
  return {
    rows: [
      [head('Reading'), head('Value')],
      [{ text: 'RSI', align: 'left' },
       { text: (values.rsi[i] ?? 0).toFixed(2), align: 'right',
         bgColor: values.rsi[i] > 70 ? '#ef535059' : undefined }],
    ],
    options: {
      position: 'top-right',      // nine corner keywords, top/middle/bottom x left/center/right
      fontSize: 11,
      cellWidth: [120, 80],       // per column, or one number for all
      cellHeight: 22,
      borderColor: '#5a6b8c',
      borderWidth: 1,
    },
  }
}
```

Return `null` to draw nothing, which is how a `showTable` switch should work.
`textColor` is derived from `bgColor` for contrast when omitted.
