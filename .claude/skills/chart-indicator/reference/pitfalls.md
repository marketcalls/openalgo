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

In Pine, every comparison against `na` is false, so nothing fires during warmup.
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

## 8. Do not declare colour or width inputs

The chart generates colour, opacity, thickness, line style and plot style for
every plot, seeded from `plot.style`. A hand-rolled `lineWidth` input gives the
user two width fields that disagree, and only one of them works.

Set defaults on the plot instead:

```js
{ key: 'ma', type: 'line', title: 'MA', style: { color: '#4f8cff', lineWidth: 2 } }
```

*Validator: no check. Style.*

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
built-in for the whole app. There are 91 of them; `sma`, `rsi`, `macd`,
`supertrend`, `vwap`, `range-analysis` are all taken.

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
