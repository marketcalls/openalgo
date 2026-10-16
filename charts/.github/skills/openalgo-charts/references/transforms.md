# Transforms

*When to read this: you need a movement-driven series (Heikin Ashi, Renko, Range, Line Break, Point & Figure, Kagi) instead of a time-bucketed one, or you are debugging why a transformed chart renders scattered or why an indicator on one looks wrong.*

## Import rule

```ts
import { runTransform, RenkoTransform } from 'openalgo-charts/transform';
```

Importing the tier registers the `'point-figure'` and `'kagi'` chart types as a side effect (`registerTransformChartTypes()`, exported and idempotent for bundlers that tree-shake a bare side-effect import). Heikin Ashi, Renko, Range, and Line Break need no registration, they render as `'candlestick'`.

The tier imports `registerChartType` from `'openalgo-charts'`, never a deep path: a deep import inlines a second copy of the chart-type registry and `createChart` never sees the renderers. Same rule as the indicator tier, see [bundling-and-tiers](./bundling-and-tiers.md).

## In-chart transforms

The chart can apply a transform itself. The series is fed the host's own bars and draws the elements, formed again on every tick:

```ts
import 'openalgo-charts/transform'; // registers the six transforms and the P&F and Kagi renderers

const series = chart.addSeries('candlestick', { transform: { type: 'renko' } });
series.setData(bars);                        // the raw bars, as for any series
feed.onBar((bar) => series.update(bar));     // the forming brick moves; a closed bar keeps its bricks

chart.setSeriesTransform(series, { type: 'point-figure', options: { mode: 'atr' } }); // also selects 'point-figure'
chart.seriesTransform(series);               // { type: 'point-figure', options: { mode: 'atr' } }
chart.setSeriesTransform(series, null);      // the bars as given again
```

- **Ids.** `registeredSeriesTransforms()` lists `heikin-ashi`, `renko`, `range-bars`, `line-break`, `point-figure`, `kagi` once the tier is imported. `getSeriesTransform(type)` returns its `SeriesTransformDefinition`: `name`, `renderer`, `inputs` (its options, in the `IndicatorInput` vocabulary) and `create(options)`, which builds the `SeriesTransformRun` the chart drives. `registerSeriesTransform` is how the tier fills the base registry, so the base never loads a transform. `create` checks the options against those inputs and throws a `TypeError` naming the problem, which is also how to check a `SeriesTransformSpec` from outside (a saved layout) before applying it.
- **The handle speaks the host's bars.** `setData`, `update` and `prependData` take them and `getData` hands them back, so replay, a feed's live path and host tail math are unchanged. `chart.primaryBars()`, the data layer, the crosshair and the readouts hold the elements, with strictly increasing times.
- **Live.** The newest source bar is the forming one. Each tick is pushed through a copy of the state as of the last closed bar (`ISeriesTransform.clone`, which every built-in has), so the elements it forms are provisional: a tick back takes them off, a newer bar commits them. A run's elements always equal `runTransform` over its source bars. A tail that shrinks is written as a correction, so no study tails over an element that is gone. The element still forming dated forward at its index by a newer source bar (a Kagi vertex, a range bar it extends) is the same element revised: a live `replace`, or `append` when elements follow it, so study alerts judge each new element once, `barState.isNew` is true only when one was added, and `calcTail` still runs. An element before the forming one changed, one dated backward, or fewer elements stay a correction.
- **Trader alerts** judge the elements. When one bar completes several, each is judged in turn and a match reports its own element; the newest is forming until the next follows it (`alerts.md`, Conditions and timing).
- **Nothing transforms unless asked.** `addSeries('point-figure')` and `setSeriesType` stay renderer only, so a host that prepares its own elements (the 2.5.x path, still valid) is never transformed twice.
- **Renderer.** A new transform type selects its renderer (candlestick for the first four). `setSeriesType` afterwards picks another and keeps the transform, and a later change of options keeps that renderer.
- **Errors.** An unknown type, an option the transform does not declare, or a value out of range throws before anything changes.

| Type | Options (0 or omitted = from history) |
|---|---|
| `heikin-ashi` | none; one candle per bar at the bar's time |
| `renko` | `mode` `'fixed'` (default), `'percent'`, `'atr'` or `'atrPercent'`; `boxSize` (fixed); `percent` (default 1); `atrPeriod` (14); `atrMultiplier` (1); `method` `'close'` (default) or `'hl'` |
| `range-bars` | `range` (twice the history box) |
| `line-break` | `lines`, default 3 |
| `point-figure` | `mode` `'fixed'` (default), `'percent'`, `'atr'` or `'atrPercent'`; `boxSize` (fixed); `percent` (default 1); `atrPeriod` (14); `atrMultiplier` (1); `reversal` (3); `method` `'hl'` or `'close'` |
| `kagi` | `reversal` (twice the history box) |

The history box is a fortieth of the loaded range and at least a tenth of a percent of the last close, to two significant figures. It is resolved on each `setData` (a new load or symbol), never per tick, and kept through `prependData`, so paging history in never resizes every brick. An option left out stays out of the spec and of saved state, and keeps following the history.

**Studies on a transformed chart.** A study computes on the elements drawn by default (`barSource` `'chart'`), which is what it read when a host fed it the elements. `study.setBarSource('underlying')`, or `addIndicator(id, settings, { barSource: 'underlying' })`, computes on the host's bars instead, and each value is read at the bar the element was completed on (the value a trader could have read as it formed); a mark the study dates at one of those bars moves to the element it completed into. Heikin Ashi keeps one candle per bar at the same time, so there nothing is read across. On a chart with no transform the two are the same bars. A study that reads another study's output needs the same bars as that study. On `'underlying'`, `calc` computes on the host's bars but the hooks (a plot's `colorBy`, an alert's `when` and `message`, the other per-bar hooks) receive `ctx.index`, `ctx.bars` and `ctx.values` indexed by element, so per-bar state a custom descriptor keeps from `calc` and reads back by index is the wrong bar on every transform but Heikin Ashi; read per-bar values from `ctx.values`, which the chart samples onto the elements. Its alerts count the host's bars: a bar that completes several elements is judged once, at the first of them, whatever the frequency (`oncePerBar` delivers once for it, `onBarClose` waits for it to close).

**State and settings.** `SeriesState.transform` records the choice beside the series, written only for a series that has one; like the rest of `series`, the host reapplies it. `IndicatorState.barSource` is written only as `'underlying'`. The settings schema's Price tab leads with the transform's options, keyed `transform.<option>`.

**The axis and the clock.** Elements that form on one bar sit a second apart, which the time axis reads as nothing about resolution: it labels a five-minute Renko chart by the minute. The bar countdown counts the forming source bar.

## The pipeline

```ts
interface ISeriesTransform {
  reset(): void;              // start of a fresh batch
  push(bar: Bar): Bar[];      // 0..n newly completed derived elements
  flush?(): Bar[];            // optional in-progress element at end of data
}

runTransform(transform, bars): Bar[]   // reset -> push each -> flush -> ensureIncreasingTimes
```

`ensureIncreasingTimes(bars)` bumps any colliding timestamp by `+1` second. Several elements can complete inside one source bar; without distinct times the DataLayer collapses them onto one logical index. `runTransform` applies it for you, call it directly only when assembling batches by hand.

Every transform is incremental: `push` takes each source bar once, in time order, and never recomputes history. Every push moves the state, so pushing the bar still forming again on each tick counts it again: push closed bars, and push the forming one through a `clone()` of the state, which is what the in-chart transform does.

## The six transforms

| Class | Options (defaults) | Emits | Plot as |
|---|---|---|---|
| `HeikinAshiTransform` | none (no constructor arg) | 1 bar per input bar, real times, `volume` carried through | `'candlestick'` |
| `RenkoTransform` | `{ boxSize }` for the default `mode: 'fixed'`, must be `> 0`; or `mode` `'percent'` / `'atrPercent'` with `percent > 0`, or `'atr'`; `method` `'close'` (default) or `'hl'` | one brick per full box move (of the close, or of the low and high in bar order with `'hl'`); percent and ATR sizes re-resolve per brick; up brick `close > open`, down brick `close < open`; no `volume` | `'candlestick'` |
| `RangeBarsTransform` | `{ range: number }` required, must be `> 0` | a bar per `high - low >= range`, built from the close sequence; the partial bar comes out of `flush()` | `'candlestick'` |
| `LineBreakTransform` | `{ lines: number }`, constructor defaults to `{ lines: 3 }`, clamped to `>= 1` | a line only when the close breaks the extreme of the prior N lines; no `flush` | `'candlestick'` |
| `PointFigureTransform` | see below | `PointFigureColumn` (a `Bar` plus `boxSize` and `boxes`) | `'point-figure'` |
| `KagiTransform` | `{ reversal: number }` required, must be `> 0` | one vertex `Bar` per turning point; `volume` encodes thickness (`1` thick/yang, `0` thin/yin); `flush()` emits the live vertex dated at the newest bar (since 2.6.0; before, `time: 0`) | `'kagi'` |

```ts
const bricks = runTransform(new RenkoTransform({ boxSize: 5 }), bars);
chart.addSeries('candlestick').setData(bricks);
```

`RenkoTransform`, `RangeBarsTransform`, `KagiTransform`, and `PointFigureTransform` in `fixed`/`percent` mode **throw** on an unusable option, so validate user input before constructing. Renko is a simplified single-box step (no 2x reversal rule) so it stays deterministic and incremental.

### Construction details worth knowing

- Heikin Ashi: `haClose = (o+h+l+c)/4`; `haOpen` is `(o+c)/2` on the first bar and `(prevHaOpen + prevHaClose)/2` after; `haHigh`/`haLow` are the max/min of the real extreme and the two HA prices. It is the only transform that is 1:1 with the input and keeps real times.
- **The first source bar of Renko, Line Break, Kagi, and P&F produces nothing**: it only anchors state (Renko snaps to `floor(close / boxSize) * boxSize`). Expect a shorter output array than a naive box-count estimate, and expect an empty array from a one-bar input.
- Range bars carry the *latest* contributing bar's time, not the opening bar's.
- Line Break opens each new box at the previous line's `close`, so the boxes chain without gaps.
- P&F establishes direction on the first real move, with an outside-bar tie resolving up, and re-derives the column boundary under the new box size on every reversal (which is why `percent`/`atr` modes stay aligned).
- Kagi turns thick when the line exceeds the previous up-turn (shoulder) and thin when it falls below the previous down-turn (waist).

## Live updates

Prefer the in-chart transform above: it handles the forming bar, history paging and studies. A host that runs a transform itself keeps one instance alive across the stream rather than re-running `runTransform` over the whole history per tick:

```ts
const t = new RenkoTransform({ boxSize: 5 });
const series = chart.addSeries('candlestick');
series.setData(runTransform(t, history));   // runTransform calls reset() first

feed.onBar((bar) => { // closed bars only; see the pipeline above for the forming one
  for (const brick of t.push(bar)) series.update(brick); // update-or-append
});
```

**`runTransform` calls `reset()`, so never mix a batch run and a streaming instance.** Use one instance for history and then keep pushing into it, or reset and rebuild, not both.

**`ensureIncreasingTimes` runs only inside `runTransform`.** Elements pushed live can share a timestamp with each other or with the last historical element; de-duplicate before `update` (bump by `+1`s, the same rule) or they collapse onto one logical index.

### Point & Figure options

| Option | Type | Default | Notes |
|---|---|---|---|
| `boxSize` | `number` | none | Required for `mode: 'fixed'`; throws if not `> 0`. |
| `reversal` | `number` | `3` | Boxes of counter-move needed to open a new column. Floored, min 1. |
| `method` | `'hl' \| 'close'` | `'hl'` | `'hl'` extends X columns from each bar's high and O columns from its low, what P&F means on a desk. `'close'` ignores intrabar range entirely. |
| `mode` | `'fixed' \| 'percent' \| 'atr' \| 'atrPercent'` | `'fixed'` | How the box is resolved, re-evaluated each time a column opens. `'atrPercent'` is `percent` of the ATR. |
| `percent` | `number` | none | For `mode: 'percent'` (of price) or `'atrPercent'` (of the ATR); `0.5` means 0.5%. Throws if not `> 0`. |
| `atrPeriod` | `number` | `14` | Wilder ATR lookback for `mode: 'atr'` and `'atrPercent'`. |
| `atrMultiplier` | `number` | `1` | ATR multiplier for `mode: 'atr'`. |

`PointFigureColumn` extends `Bar` with `boxSize` (price height of one glyph) and `boxes` (glyph count). `low` is the bottom edge of the lowest box and `high` is the **exclusive top edge** of the highest, so `[low, high)` is exactly the glyph stack's span and `boxes === (high - low) / boxSize`. Up column (X) is `close >= open`. The renderer reads `boxSize` off the column, so variable-box modes render correctly; `style.boxSize` remains a fallback only for hand-built data. Renderer style keys: `upColor` (`#26a69a`), `downColor` (`#ef5350`). Kagi style keys: `thickColor` (`#26a69a`), `thinColor` (`#ef5350`).

## Two rendering paths, not one

**Heikin Ashi / Renko / Range / Line Break produce ordinary bars, feed them to `addSeries('candlestick')`.** Nothing new is registered for them; they are a different array of `Bar`, not a different renderer.

**Point & Figure and Kagi require their tier-registered renderers.** `chart.addSeries('point-figure')` or `chart.addSeries('kagi')` throws if the tier was never imported (or was tree-shaken without calling `registerTransformChartTypes()`). Their emitted bars are not candles: a P&F column is a glyph stack derived from `boxSize`/`boxes`, and a Kagi bar is a single-price vertex whose `volume` is a thickness flag, so drawing either as a candlestick is meaningless.

## Transformed series and real time

A transformed series is indexed by **element**, not by clock. Every element carries its source formation time as a label only, and `ensureIncreasingTimes` may have shifted that time by seconds. Consequences:

- **Every series on a chart shares one time axis.** A transform emits fewer elements than the raw bars, so feeding a companion series (typically a volume pane) the *raw* bars puts all the raw timestamps back onto the shared axis and the bricks render scattered with gaps. Re-bucket companion series onto the transformed times, sum the raw volume behind each element, keyed by `element.time`.
- **Indicators on a transformed series measure elements, not bars.** `chart.addIndicator('rsi')` computes over whatever the primary price series holds, so on Renko an "RSI(14)" is 14 *bricks*, an interval that varies in wall-clock length. With the chart applying the transform, `setBarSource('underlying')` computes a study on the bars instead. Renko, Line Break, and P&F drop `volume` entirely, so `volume`, `obv`, `adl`, `mfi`, and `vwap` read zero or produce nothing. VWAP's session anchor is also meaningless once times are synthetic, whatever zone the chart is on.
- **Drawings anchored in time drift.** A trendline placed on a transformed series is pinned to element positions on the shared axis; the same coordinates over the raw bars land somewhere else. Do not switch a chart between raw and transformed data while keeping drawings and expect them to hold.
- `flush()` output is provisional. `RangeBarsTransform` and `PointFigureTransform` emit an in-progress element and `KagiTransform` emits a live vertex, those change as more data arrives, unlike completed elements, which are stable (an incremental run's prefix equals a batch run's prefix).

## Symbol arithmetic (2.3.0)

A chart of `NIFTY1!/NSE:RELIANCE`, `(A+B)/2`, `1/GOLD`, or any expression over
any number of legs. Two calls, deliberately separate:

```ts
import { parseExpression, evaluateExpression, isPlainSymbol } from 'openalgo-charts/transform';

const expr = parseExpression('NSEIX:NIFTY1!/NSE:RELIANCE+NASDAQ:META');
expr.symbols;  // ['NSEIX:NIFTY1!', 'NSE:RELIANCE', 'NASDAQ:META'] -> fetch exactly these
const bars = evaluateExpression(expr, { 'NSEIX:NIFTY1!': a, 'NSE:RELIANCE': b, 'NASDAQ:META': c });
chart.addSeries('line').setData(bars);
```

`parseExpression` names the legs **before** anything is fetched, which is the
point: a host resolves and loads exactly those symbols. The engine fetches
nothing, the same way `addComparison` takes bars rather than a symbol.
`isPlainSymbol` tells an ordinary symbol from arithmetic, so one code path
serves both. `ExpressionError` carries the offending character's index, so a
search box can underline it.
`SymbolExpression.ast` is an `ExpressionNode` (its `fn` members name an
`ExpressionFunctionName`), exported for typing only: build one with
`parseExpression`, never by hand.

Grammar: `+ - * / ^` with the usual precedence and `^` right associative, unary
minus, parentheses, numeric constants, and `abs sqrt ln log log10 exp min max
pow`. The keypad glyphs a search box prints are accepted too. A ticker
containing `-` goes in quotes (`'BRK-B'/SPY`), because bare `-` is subtraction
and no lookahead settles `A-B` in general.

### Weighted legs: options combinations

Numeric coefficients make this an options-combination tool as much as a ratio
tool:

| Expression | What it is |
| --- | --- |
| `2*CE25000 - CE25200` | 1x2 ratio spread |
| `CE25000 + PE25000` | Long straddle |
| `-CE25000 - PE25000` | Short straddle, a credit, so negative |
| `75*(CE25000 - CE25200)` | The spread scaled by lot size |

A sold combination is a credit, so the series goes negative, and that is allowed
rather than clamped. Two consequences. A series reaching zero or below cannot be
drawn on a **logarithmic** price scale, so leave a spread pane on the regular
one. And a leg that did not print gaps the whole combination rather than pricing
it from an earlier minute: for an illiquid strike that is the normal case, and a
premium carried forward is exactly the number that gets someone hurt.

### Open and close are exact; the high and low are a bound

A bar records where a market opened, closed and how far it travelled, but not
*when* it was at each price, so the true high of a ratio is not recoverable from
two OHLC bars.

| `ohlc` | What you get |
| --- | --- |
| `'close'` (default) | A flat bar from the legs' own opens and closes, which are simultaneous by definition. Exact. |
| `'interval'` | Additionally bounds the high and low by interval arithmetic. Guaranteed to contain the truth, usually wider than it. |

The bound assumes each leg hit its extreme at the worst possible moment, so it
overstates the range. It also cannot see that two mentions of one symbol move
together, so `A/A` bounds rather than collapsing to 1: the classic dependency
problem, and the reason `'close'` is the default.

Three more behaviours worth knowing. A bar the other legs did not trade produces
a **gap**, not a value carried forward, because a ratio against another minute's
price was never true. A divisor reaching zero gaps rather than spiking. And the
result carries no `volume` by default. `EvaluateOptions.volume: 'sum'` opts into
combined leg activity: sum the volume of each distinct expression symbol once,
without price signs or coefficients. This is activity of the legs, not a traded
quantity of the synthetic instrument. Zero is valid. A missing, negative,
nonfinite or overflowing amount leaves volume absent for that bar. The reference
host and OpenAlgo expression adapter opt into this rule.

Related: [chart-types](./chart-types.md), [data-and-time](./data-and-time.md), [indicators](./indicators.md), [drawing-tools](./drawing-tools.md), [bundling-and-tiers](./bundling-and-tiers.md), [pitfalls](./pitfalls.md).
