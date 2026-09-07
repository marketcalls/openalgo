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

The descriptor contract has not changed, so an existing indicator keeps working.
Three things did:

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
   that saves the most work: the 102 built-ins are descriptors, so
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

Then the two that need thought:

**A higher-timeframe request.** There is no `request.security`. Either fold the
chart's own bars up to the higher timeframe, or fetch with
`createTier2Indicator`. Folding is usually more correct: a request against a
60-minute bar returns that whole bar's high, which is lookahead if your window
is shorter than the bar.

**Anything drawn at a future bar.** Not expressible: a column is one value per
bar and there is no bar yet. Shift the meaning back onto existing bars, or drop
it. This is the one thing that can make a study genuinely unportable today.

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

- Add colour or line-width inputs. The chart generates colour, opacity,
  thickness, line style and plot style per plot automatically, seeded from each
  plot's `style`. Your own width input becomes a second control that disagrees.
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
  `overlay: true` rather than reaching for a precision knob.
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
| `.claude/skills/chart-indicator/examples/` | three validated worked examples |
| `.claude/skills/chart-indicator/reference/` | contract, API surface, pitfalls, cookbook |
| `.claude/skills/chart-indicator/coverage.mjs` | fails if an API or capability is documented but never demonstrated |
| `docs/custom-indicators.md` | the user-facing guide |
| `blueprints/custom_indicators.py` | serves the folder to the chart |
| `frontend/src/lib/trading/customIndicators.ts` | the loader |

Indicators are loaded over HTTP at runtime, not bundled, so they survive
`git pull` and need no rebuild. They run with full access to the logged-in
session: treat an indicator file from an untrusted source as you would any
script you are about to run.
