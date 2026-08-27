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
  fills?: IndicatorFillSpec[],
  calc(bars, settings, store): IndicatorValues,   // required
  calcTail?(bars, settings, fromIndex, previous, store),
  markers?({ bars, values, settings }),
  levels?(settings),
  range?(settings),
  table?({ bars, values, settings }),
  attach?(ctx),
}
```

## Bars

```js
{ time: number,   // UTC SECONDS, not milliseconds
  open: number, high: number, low: number, close: number,
  volume?: number }
```

`volume` is genuinely optional. Index series carry none, so guard any divide by
it.

## `calc` and how its output is consumed

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

Every input needs `key`, `type`, `label`, `default`. Valid sources: `open`,
`high`, `low`, `close`, `hl2`, `hlc3`, `ohlc4`, `volume`.

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
  colorKey: 'lineColor',     // optional: an input key holding the colour
  colorBy({ value, index, values, settings }) { return '#ef5350' } }
```

Single-column plot types: `line`, `line-markers`, `step`, `area`, `histogram`,
`column`. The full registry also has `candlestick`, `hollow-candle`,
`volume-candle`, `bar`, `high-low`, `hlc-area`, `baseline`, which expect richer
data and are rarely right for an indicator.

`colorBy` is honoured by `histogram` and `column`. It is skipped for non-finite
values.

**Style controls are generated for you.** `indicatorStyleInputs` derives colour,
opacity, thickness, line style and plot style per plot, defaulting from
`plot.style.color` (or the input named by `colorKey`) and `plot.style.lineWidth`.
Do not hand-roll them.

## Fills

```js
fills: [{ between: ['upper', 'lower'], colorUp: '#4f8cff', colorDown: '#4f8cff', opacity: 0.08 }]
```

Both keys must name real plots. `colorUp` applies where the first is above the
second.

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
levels: (settings) => [{ price: 70, title: '70', color: '#ef5350', dashed: true }]
range:  (settings) => ({ min: 0, max: 100 })     // or null
table:  (ctx) => ({ rows: [['VWAP', '123.45'], ['Side', 'Above']] })   // or null
```

`range` applies only when the indicator created its own pane; two indicators
sharing a pane would otherwise fight over it. `table` is for things that are not
a value per bar, such as a scoreboard or a seasonality matrix.

## calcTail

```js
calcTail(bars, settings, fromIndex, previous, store) -> values | null
```

Called **instead of** `calc` when only the tail changed. The runtime uses it when
`bars.length === previousCount` or `previousCount + 1`, passing
`fromIndex = previousCount - 1` (the previously-last bar may have been replaced
by a tick). Return values for `[fromIndex, bars.length)`, which the runtime
splices onto the previous result, or `null` to fall back to a full `calc`.

Without it every tick costs a full recompute: a few hundred microseconds over
50k bars, so it only matters in a busy live pane. **If you also implement
`markers`, skip `calcTail`** — markers re-run in full after every recompute, so
it saves nothing.

A `calcTail` that disagrees with `calc` makes the live chart differ from what a
reload shows. The validator checks the two agree at the boundary index.

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
