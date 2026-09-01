# Pitfalls

Read this before writing an indicator. Most first drafts fail on something here.
Each entry says what happens, why, and what the validator does about it.

---

## 1. Column length must equal `bars.length`

```js
calc(bars) { return { x: bars.slice(1).map(b => b.close) } }   // WRONG: one short
```

The runtime iterates `0 .. bars.length` and reads `col[i]`. Past the end it gets
`undefined`, drawn as a gap. Nothing raises. A short column looks like an
indicator that "stops working" partway across the chart.

*Validator: ERROR.*

---

## 2. Every plot key must appear in what `calc` returns

```js
plots: [{ key: 'value', ... }]
calc() { return { val: [...] } }        // WRONG: 'value' vs 'val'
```

A missing key makes the runtime call `series.setData([])`. The plot silently
draws nothing.

*Validator: ERROR.*

---

## 3. Warmup is `null`, never `0`

`0` is a real value. It lands at the bottom of the pane, drags autoscale down and
draws a line from zero to the first real value. Use `null`, or `nulls(x)` on a
helper's NaN output. `null`, `undefined` and `NaN` are all treated as gaps.

*Validator: cannot tell 0 from a real value. Yours to get right.*

---

## 4. `na` semantics are inverted in JavaScript

In script languages with a not-available value, every comparison against it is
false, so nothing fires during warmup.
In JavaScript:

```js
5 > null        // true
null >= 0       // true
```

An unguarded crossover test therefore fires a signal on the first bar where the
level appears, and often on every warmup bar before it.

```js
if (prev == null || cur == null) continue      // do this first, always
```

*Validator: cannot detect. This is the most common logic bug.*

---

## 5. Marker positions do not mean what they say

`aboveBar` and `belowBar` resolve against **the series the markers are attached
to**, which for an indicator is its own plot. On an overlay, both pin the label
to your line and ignore the candle entirely.

```js
{ position: 'atPrice', price: bar.low - pad, shape: 'labelUp' }    // relative to the candle
```

`atPrice` adds no padding, so bring your own, and scale it to the instrument:

```js
const pad = Math.max(meanBarRange * 0.5, Math.abs(lastClose) * 0.0005)
```

A fixed number of points looks right on one symbol and wrong on every other.

*Validator: WARNING on `aboveBar`/`belowBar` for an `onchart` indicator.*

Marker text is multi-line since 1.7.1: `
` splits it into stacked rows. Earlier
guidance that it was single-line no longer applies.

---

## 6. A cleared input arrives as `''`

The settings dialog hands back `''` when a user empties a field, not the default.

```js
Number('')          // 0     -> a zero-length window
''.split('-')[1]    // undefined -> TypeError on the next call
```

Always coerce with a floor:

```js
const length = Math.max(2, Math.floor(Number(settings.length) || 20))
```

*Validator: ERROR. It runs every calc with all text and number inputs cleared.*

---

## 7. `atr` and `trueRange` take three arrays, not bars

```js
atr(bars, 14)                                                        // WRONG
atr(bars.map(b=>b.high), bars.map(b=>b.low), bars.map(b=>b.close), 14) // right
```

`rsi` takes a single numeric array. `supertrend` takes bars. There is no
consistent rule, so check `reference/api.md`.

*Validator: ERROR, as a thrown exception.*

---

## 8. Do not declare width inputs, and declare colour inputs only for fills

The chart generates colour, opacity, thickness, line style and plot style for
every plot, seeded from `plot.style`. A hand-rolled `lineWidth` input gives the
user two width fields that disagree, and only one of them works.

Set defaults on the plot instead:

```js
{ key: 'ma', type: 'line', title: 'MA', style: { color: '#4f8cff', lineWidth: 2 } }
```

**Per-bar colour now reaches line, area and step**, not only histogram and
column, since 1.7.1. The two-plot split-and-null trick is still the way to make a
line *recolour at a trend flip*, because that also breaks the line at the flip,
but a simple colour ramp no longer needs it.

**The exception is `fills`.** A fill takes `colorUpKey` / `colorDownKey`, and
those name an **input** key, not a plot style. A shaded indicator therefore has
to declare its colours as inputs, and its plots should reference the same ones
via `colorKey` so a line and its ribbon cannot drift apart. This is what every
built-in with a band does. See `examples/shaded_trend_zone.js`.

*Validator: ERROR if a fill names a colour key with no matching input.*

---

## 9. Volume can be missing

Index series carry no volume. `bars[i].volume` is `undefined`, so any VWAP-style
weight divides by zero and the whole plot blanks.

```js
const v = Number.isFinite(bar.volume) && bar.volume > 0 ? bar.volume : 1
```

*Validator: partial. The fixtures all carry volume; the flat fixture catches the
related zero-range divide.*

---

## 10. Guard every divide

A flat series makes `high - low` zero, a doji run makes a mean range zero, and a
zero standard deviation is normal on a halted instrument. Division yields
`Infinity` or `NaN`, which draws as a gap at best and destroys autoscale at
worst.

*Validator: ERROR via the flat-series fixture.*

---

## 11. Never use the browser's local time

Bar times are UTC seconds; sessions are exchange wall clock. `new Date(t*1000)
.getHours()` gives the viewer's timezone, so the same chart computes differently
in Mumbai and London.

```js
const parts = utcSecondsToZonedParts(bars[i].time, zone)
const minuteOfDay = parts.hour * 60 + parts.minute
```

Default the zone to `DEFAULT_TIMEZONE` and validate a user-supplied one with
`isValidTimezone`.

*Validator: no check. The fixtures are IST.*

---

## 12. `time` is seconds, not milliseconds

`Date.now()` is milliseconds. A marker at `bar.time * 1000` matches no bar and
never draws.

*Validator: ERROR for markers whose time matches no bar.*

---

## 13. Reusing a built-in id overrides it

Custom modules register after the built-in tier, so a duplicate id replaces the
built-in for the whole app. There are 102 of them; `sma`, `rsi`, `macd`,
`supertrend`, `vwap`, `range-analysis` are all taken.

**The catalogue grew from 91 to 102 in 1.8.3, so a file written before that can
shadow a built-in that did not exist when it was named.** The ids added were
`t3`, `hull-suite`, `consolidation-breakout`, `smma`, `net-volume`,
`linreg-slope`, `ma-channel`, `chaikin-volatility`, `standard-deviation`,
`standard-error` and `standard-error-bands`. The loader now reports a collision
against a built-in at load time, so an accidental one shows up in the chart's
problem list rather than as an indicator that quietly draws the wrong thing.

Overriding on purpose is still allowed and still works; the report is a warning,
not a refusal.

*Validator: WARNING.*

---

## 14. `calcTail` must agree with `calc`

If it drifts, the live chart shows different values from what a reload shows, and
the bug only appears after a session of ticking. Note the runtime passes
`fromIndex = previousCount - 1`, because the previously-last bar may have been
replaced by a tick, so the tail always **re-computes at least one existing bar**.

Skip `calcTail` entirely if you implement `markers`: markers re-run in full after
every recompute, so there is nothing left to save.

*Validator: ERROR if the boundary value disagrees with `calc`.*

---

## 15. `range` only applies to an indicator's own pane

Two indicators sharing a pane would fight over the scale, so the runtime applies
`range` only when the indicator created the pane. On a shared pane it is ignored.

*Validator: no check.*

---

## 16. Per-instance state belongs in `store`, not module scope

A module-scope variable is shared by every instance of the indicator. Add the
same indicator twice with different settings and they corrupt each other. `calc`
receives a per-instance `store` object for scratch.

Pure `calc` functions of `(bars, settings)` need no state at all, which is the
better answer where possible.

*Validator: no check. It validates one instance.*

---

## 17. `background` and `barColors` are indexed by bar

Both return one entry per bar, `null` to leave that bar alone, and both must be
exactly `bars.length` long. One short and every colour shifts onto the wrong bar,
which reads as an indicator that is subtly, confusingly wrong rather than broken.

`barColors` recolours the **main price candles**, so two indicators publishing at
once is last-writer-wins. Removing an indicator restores what was there before.

*Validator: ERROR on a length mismatch or a non-string, non-null entry.*

---

## 18. Alerts fire only on new bars, by design

`alerts[].when(ctx)` is evaluated on a tail-only change. Loading history,
changing a setting, paging history in, and switching symbol all fire **nothing**,
even though `calc` re-runs over every bar.

That is what you want: the naive implementation fires once per historical
crossing the moment the indicator is added, then again on every settings change.
Do not try to defeat it by keeping your own state in `store`.

Every alert needs an `id` and a `title`. The `title` is what a host shows.

*Validator: ERROR on a missing id or title, or a `when` that throws.*

---

## 19. A candle plot is fed by four columns, not one

```js
plots: [{ key: 'ha', type: 'candlestick', title: 'HA',
          ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } }]
calc: () => ({ o: [...], h: [...], l: [...], c: [...] })   // four columns, not 'ha'
```

The plot key is a label; the four names in `ohlc` are what `calc` must return. A
missing or wrong-length column throws out of `addIndicator` rather than drawing
nothing.

*Validator: ERROR on an incomplete ohlc group or a bad column.*

---

## 20. The calc context is optional, and so is everything on it

`calc(bars, settings, store, ctx)` gains a fourth argument carrying `barState`,
`symbol`, `interval`, `timezone` and `now()`. It is optional and last, so every
existing indicator is untouched.

`symbol` and `interval` can be `undefined`: the engine is handed bars, not an
instrument, and only a host that supplies them will have them. Guard before use.

---

## 21. Do not ask the user for the tick size

Since 1.8.2 the chart tells you: `ctx.tickSize` on the fourth `calc` argument,
sourced from the price scale's `minMove`. An input for it is a second source of
truth that will disagree with the axis the moment the user edits it.

```js
const tick = Number(ctx?.tickSize) || 0          // 0 means the host never set one
```

Guard for `undefined`, because a host that has not set `minMove` genuinely does
not know, and the scale's `0` means "infer precision from the range" rather than
one paisa.

Snap the levels a trader acts on, and only those:

| Snap | Leave alone |
| --- | --- |
| stops, band edges, entry and target levels | moving averages |
| anything an order gets placed at | oscillators, ratios, z-scores |

**Point value is different: the chart does not know it.** Nothing in the engine
describes what one point of an instrument is worth, so a study needing it takes
an input defaulting to 1, which is right for Indian markets.

*Validator: no check. It cannot tell a tradeable level from a smoothed average.*

---

## 22. A built-in's column is not named after the built-in

```js
run('ema', bars, { length: 20 }).ema     // WRONG: undefined
run('ema', bars, { length: 20 }).ma      // right
```

Every moving-average built-in plots under `ma`. `macd` plots `macd`, `signal`
and `histogram`. `bollinger` plots `upper`, `basis`, `lower`, not `middle`.
Check before assuming:

```js
getIndicator('bollinger').plots.map((p) => p.key)   // ['upper','basis','lower']
```

Reading the wrong key yields `undefined`, and a column of `undefined` draws
nothing and raises nothing, so the cell or plot simply goes blank.

*Validator: ERROR. Any column returned as `undefined` is reported, and so is any
column a hook reads that `calc` never produced.*

---

## 23. Columns only a hook reads are still columns

`markers`, `table`, `background`, `barColors` and `alerts` all receive `values`
and none of them receives `store`, so anything they need has to be returned from
`calc`, even when no plot draws it.

Those columns sit outside the plot checks: nothing verifies a key the table reads
unless it is also plotted. A typo there is invisible.

*Validator: ERROR. The hooks are handed a recording view of `values`, so a read
of a column that does not exist is caught.*
