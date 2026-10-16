---
name: openalgo-chart-indicator
description: Add a built-in openalgo-charts indicator, restyle it, build a settings UI from its descriptor, or author a custom indicator with registerIndicator or the Tier-2 external-data contract. Use when the user asks to add RSI/MACD/Bollinger/Supertrend or any indicator, change indicator colors or periods, or write their own indicator.
argument-hint: "[indicator-id] [pane]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Add or author an indicator. Read [indicators](../openalgo-charts/references/indicators.md) for the full built-in catalogue with exact ids, inputs and defaults before writing code - do not guess an id. There are 112 built-ins and the ids are hyphenated lowercase, not derivable from the display name (`williams-percent-r`, not `willr`).

## Arguments

- `$0` = indicator id, or a plain-language name to resolve to an id.
- `$1` = target pane. Default: whatever the descriptor's `placement` says.

## Step 0 - the tier must be imported

```ts
import 'openalgo-charts/indicators';   // side effect: registers the 112 built-ins
```

Without it `chart.addIndicator` throws. Add this import once, at the app entry, not in every module. Verify it is present before adding an indicator:

```sh
rg -n "openalgo-charts/indicators" src app
```

If loading custom indicator modules asynchronously, await registration before adding ids
or restoring layouts. Concurrent panes and pickers must share the pending promise, not a
premature ready flag. The package does not load arbitrary user scripts; see
[host-integration](../openalgo-charts/references/host-integration.md#registration-and-csp).

## Path A - add a built-in

```ts
chart.addIndicator('bollinger');                            // overlays the price pane
const macd = chart.addIndicator('macd', { fastPeriod: 8 }); // gets its own pane
```

Resolve the id against the source, not from memory. The catalogue is one array, so read it rather than grepping descriptor files:

```sh
node --input-type=module -e "import * as i from 'openalgo-charts/indicators'; for (const d of i.BUILTIN_INDICATORS) console.log(d.id, '|', d.name, '|', d.category, '|', d.placement)"
# upstream checkout: the tier bundle resolves as a relative path
node --input-type=module -e "import * as i from './dist/openalgo-charts.indicators.mjs'; for (const d of i.BUILTIN_INDICATORS) console.log(d.id, '|', d.name, '|', d.inputs.map(x => x.key + '=' + x.default).join(' '))"
```

At runtime, `hasIndicator(id)` is the guard and `registeredIndicators()` the live list. If the user names an indicator that has no built-in descriptor, say so plainly and go to Path C rather than substituting a different indicator.

## Path B - restyle an existing instance

Every plot gets colour, opacity, thickness, line style and plot style for free, generated from the descriptor. The keys are `<plotKey>:opacity`, `:width`, `:lineStyle`, `:type`.

**Colour is the exception.** The colour key is `plot.colorKey` when the descriptor declares one, and `<plotKey>:color` only when it does not. **Every built-in declares one**, so `'macd:color'` is silently ignored while `'macdColor'` works. Resolve the real key with `plotStyleKeys(plot)` rather than composing it by hand.

28 built-ins also declare `fills` (shaded channels, and background overbought/oversold bands). A fill is restyled through its `colorUpKey` / `colorDownKey` settings keys, not through any plot key.

```ts
macd.setSettings({ 'macd:width': 2, 'macd:lineStyle': 'dashed', macdColor: '#26a69a' });
```

To build a settings dialog, generate it from the descriptor rather than hand-writing a form. The descriptor's own `inputs` are the parameters tab; `indicatorStyleInputs(descriptor)` gives the style tab. The chart emits `indicatorSettings` when the user clicks the gear on a pane legend - that event is the hook to open your dialog. The library ships no dialog.

## Path C - author a custom indicator

Use `registerIndicator` when the value is computed from the chart's own OHLCV. A descriptor is data: id, name, placement, inputs, plots, optional levels, and a pure `calc`. Each plot names a registered **chart type**, so you write no drawing code.

Since 1.7.1 a descriptor can also return free-standing geometry from `draws(ctx)` (lines, boxes, labels and polylines anchored to `{ time, price }`, with ray extension and multi-line text), derive its `levels` from `ctx.bars` / `ctx.values` rather than settings alone, and send a single plot to the price pane with `overlay: true` while the rest of the study keeps its own pane. `colorBy` now reaches line, area and step, not just histogram and column. The `./calc` helpers are all exported, including `pivotHigh`, `pivotLow` and `smaSeededEma`, so a ported study composes them instead of re-deriving them.

Since 1.8.1, and the reason to reach past a plot before hand-rolling something:

- **`calc` takes an optional fourth argument**, `IndicatorCalcContext`: `barState` (`isNew`, `isConfirmed`, `isRealtime`, `lastIndex`), plus `symbol`, `interval`, `timezone` and `now()`. `calcTail` takes it sixth. Optional and trailing, so an existing descriptor is untouched. `isConfirmed` is inferred from the last bar's gap against the chart clock, so a holiday or a session break widens it: it means "this bar's span has elapsed", not "the exchange is closed".
- **`alerts`** declares conditions the runtime watches, emitted as `'indicator:alert'` on the chart bus. They fire **only on a live tail change**, so adding the indicator to a loaded chart, changing a setting, paging history or switching symbol announces nothing.
- **`background(ctx)`** shades the indicator's own pane per bar (pass a translucent `rgba()`, it draws over the grid); **`barColors(ctx)`** recolours the **main price candles**, one publisher at a time, last writer wins.
- **`plot.ohlc`** names four `calc` columns so one plot draws as candles or OHLC bars.
- **`withAlpha` / `fromGradient`** from the package root, for any per-bar colour rule. Do not write a hex parser.
- **`intervalParts` and `isIntradayInterval` / `isDailyInterval` / `isSecondsInterval` / `isTickInterval`** answer what kind of bar the chart is on. Never branch by matching the interval string.
- **`parseSessionSpec` / `inSessionAt` / `sessionFlags`** for a window you state (`'0915-1015'`, `'0930-1600:23456'`), as opposed to `sessionStartFlags`, which reads the trading day back out of the bar gaps.

Since 2.4.0, for the constructs a ported study most often could not express (every one optional, nothing older changes):

- **`securitySeries(bars, interval, opts)`** from `openalgo-charts/indicators` folds the chart's bars to a higher timeframe, one value per bar. The default reads the bucket as it stood at that bar and never repaints; `offset: k` reads the last completed bucket; `lookahead: true` reads final values and repaints. `session: '0915-1530'` anchors sub-day buckets to the session open. This replaces every hand-rolled fold.
- **`plot.offset`** paints a column that many bars to the right, the tail landing in the right margin (a displaced cloud). Fills follow the first plot's offset; the legend reads what is drawn under the cursor. `SeriesStyle.barOffset` is the same thing on any series.
- **A thrown `calc` no longer takes the frame down**: it is published as `{ state: 'error' }` on the instance data status and `indicator:data-status`, the previous plots stay up, and the next good pass publishes `ready`. Throw `IndicatorInputError` for a condition the user can fix. `addIndicator` still refuses a descriptor whose first pass throws.
- **`alerts[].message`** may be a function of the firing bar's context.
- **Markers**: shapes `cross` and `xcross`; positions `paneTop` and `paneBottom`, pinned to the plot edge with no bar or `price` needed.
- **`fills[].overlay`** puts a band on the price pane beside `overlay` plots.
- **`plot.colorParts`** returns `{ body, wick, border }` per bar, carried as `Bar.wickColor` / `Bar.borderColor` and honoured by both candle renderers; `colorBy` is unchanged.
- **`draws()` labels and boxes take `tooltip` and `id`**: hit-testable, reported through `subscribeClick`, tooltip painted on hover by the layer itself.
- **Inputs `interval` and `time`**: a timeframe code (select over the built-in tokens plus registered codes) and a wall-clock string in the chart zone.
- **`table` options `fontSize: 'auto'`** fits each cell.
- **`ctx.requestBars(request)`** on the attach context asks the host for another instrument's bars; the host registers a provider with `chart.setBarsProvider` (or `ChartOptions.barsProvider`) and it rejects with a clear message when there is none. See Path D for the Tier-2 half.

Full semantics for all of these are in [indicators](../openalgo-charts/references/indicators.md#coverage-additions-240).

From 2.5.6, an input that only matters for some settings takes `visibleWhen` or
`activeWhen`, a condition over the other settings such as
`{ key: 'mode', is: 'bands' }` (also `isNot`, `all`, `any`), and related inputs
share one row with the same `inline` id. The widget and reference host forms honour
them; `calc` still receives every setting. A ported study whose inputs were greyed
or hidden by another input keeps that behaviour this way instead of listing every
parameter as always editable. See
[indicators](../openalgo-charts/references/indicators.md#conditional-inputs-and-inline-rows-256).

Full semantics for every one of these, including the firing rules and the known gaps, are in [indicators](../openalgo-charts/references/indicators.md). Read them before using `barColors` or `alerts`: both have behaviour that is deliberate and surprising.

```ts
import { registerIndicator, sourceValues } from 'openalgo-charts';

registerIndicator({
  id: 'my-ma',
  name: 'My MA',
  placement: 'onchart',
  inputs: [{ key: 'length', type: 'number', label: 'Length', default: 20 }],
  plots: [{ key: 'ma', title: 'MA', type: 'line', style: { lineWidth: 1.5 } }],
  calc(bars, settings) { /* return { ma: (number | null)[] } aligned to bars */ },
});
```

Confirm the exact `IndicatorDescriptor` field names and the `calc` return shape against `dist/index.d.ts` before writing - the reference file documents them, but the typings are authoritative.

Two optional hooks are worth knowing before you reach for a plot that cannot express the idea:

- `markers(ctx)` returns bar-anchored `SeriesMarker[]` and runs after every `calc`, so it reads the values `calc` just produced. Use it for discrete named events (a crossover arrow, a "Buy" plate) rather than trying to encode them as a price column. The `labelUp` / `labelDown` shapes are text plates whose tail points at the anchor price; both require `text`. Return `[]` to clear the layer. `halftrend`, `williams-fractals` and `rsi-divergence` are the built-in examples.
- `fills` shades a band, and `between` resolves against `calc` output columns rather than declared plots. A background band is therefore a fill between two constant columns that are never plotted.

`registerIndicator` overwrites an existing id. With 112 built-ins registered, namespace a custom id (`my-momentum`, `acme-vwap`) unless replacing a built-in is the intent.

**If the indicator anchors on a calendar (a session, week or month reset), it needs the chart's zone.** `calc` is handed `(bars, settings, store)` and never the chart, so the chart injects its timezone into the settings blob under a reserved `timezone` key. Read it defensively (missing or unrecognised means `DEFAULT_TIMEZONE`, never a throw), do not write it back into your own settings, and prefer `sessionStartFlags(times)` over any calendar rule when what you actually mean is "the trading session". The recipe is in [indicators](../openalgo-charts/references/indicators.md#trading-sessions).

## Path D - Tier-2, data not derived from OHLCV

Open interest, cumulative volume delta, PCR, any external analytics feed. Use `createTier2Indicator`, which wraps a fetch/subscribe lifecycle into an ordinary descriptor so panes, settings, levels and removal all work identically.

```ts
import { createTier2Indicator } from 'openalgo-charts/indicators';
```

The alignment rule matters and is not negotiable: each bar takes the most recent external point **at or before** that bar's time. Never interpolated, never forward-looking. Bars before the first point are `null`.

Since 2.4.0 a Tier-2 descriptor can also combine: `series` names external columns to align besides the plots, `calc(bars, external, settings, store, ctx)` folds them into the chart's own bars, and `Tier2Context.requestBars` carries the host's bar provider into `fetch`. A relative strength or a beta against a benchmark is therefore one descriptor, with no transport of its own. Without `calc` the wrapper returns the aligned plot columns exactly as before.

## Rules

1. **Never invent an indicator id or input key.** Resolve both from source.
2. **Placement is the descriptor's decision.** Only override `paneIndex` when the user explicitly wants it elsewhere.
3. **`calc` runs on every data change.** Keep it O(n) and allocation-light; do not fetch inside it.
4. **Removing an indicator prunes its pane** if that leaves the pane empty. Do not also remove the pane yourself.
5. **Indicator plots are not the price series.** They never drive the magnet crosshair or the last-price line.
6. No emojis or icons in code, labels, or log output.

## Verify

```sh
npx tsc --noEmit
```

Then confirm on a live chart that the plot appears in the expected pane, the legend shows a reading, and changing a setting repaints. Report the id used, the pane it landed in, and the settings keys you exposed.
