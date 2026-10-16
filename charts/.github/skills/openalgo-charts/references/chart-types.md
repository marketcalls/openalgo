# Chart types

*When to read this: choosing a `SeriesType` for `addSeries`, working out which style keys a type actually reads, or switching the chart style at runtime.*

Source of truth: `src/model/chart-type-registry.ts`, `src/transform/index.ts`, `src/render/*.ts`.

Types are resolved through a registry, so the core never switches on type. `registerChartType(name, entry)`, `getChartType(name)` and `registeredChartTypes()` are exported, a custom type is one registration (see [primitives-and-plugins](primitives-and-plugins.md)).

## Base tier: 13 types

All 13 are registered by importing `openalgo-charts`. `isPriceSeries` marks the family whose last close can drive the last-price line/tag and whose first instance becomes the chart's primary series.

| Type | Draws | `isPriceSeries` | Autoscale extents per bar | Style keys it reads |
|---|---|---|---|---|
| `candlestick` | Filled OHLC bodies with wicks | yes | `low` .. `high` | `upColor`, `downColor`, `borderUpColor`, `borderDownColor`, `wickUpColor`, `wickDownColor`, `borderVisible`, `wickVisible` |
| `hollow-candle` | Same, up bodies outlined only | yes | `low` .. `high` | same as `candlestick` |
| `volume-candle` | Candles whose body width scales by `volume / maxVisibleVolume` | yes | `low` .. `high` | same as `candlestick` |
| `bar` | OHLC bar: high-low stick, left open tick, right close tick | yes | `low` .. `high` | `upColor`, `downColor` |
| `high-low` | High-low stick only, no O/C ticks | yes | `low` .. `high` | `upColor`, `downColor` |
| `line` | Polyline through `close` | yes | `close` .. `close` | `color`, `lineWidth` (1.5), `lineStyle`, `markers`, `markersOnly`, `markerRadius` (2) |
| `line-markers` | Line with a dot on every point | yes | `close` .. `close` | as `line`; `markers` forced true |
| `step` | HV step polyline through `close` | yes | `close` .. `close` | as `line`; `step` forced true |
| `area` | Gradient fill from the line down to the pane floor | yes | `close` .. `close` | `color`, `lineWidth`, `areaTopColor`, `areaBottomColor` |
| `hlc-area` | Band filled between `high` and `low`, `close` stroked over it | yes | `low` .. `high` | `closeColor`, `lineWidth`, `areaTopColor` (fill) |
| `baseline` | Line + fill split above/below a reference level | yes | `min(baseValue, close)` .. `max(baseValue, close)` | `baseValue` (0), `topColor`, `bottomColor`, `areaTopColor`, `areaBottomColor`, `lineWidth` |
| `column` | Up/down coloured bars from `base` to `close` | **no** | `min(base, close)` .. `max(base, close)` | `upColor`, `downColor`, `base` (0) |
| `histogram` | Single-colour bars from `base` to `close` | **no** | `min(base, close)` .. `max(base, close)` | `color` (`'#3a4666'`), `base` (0), per-bar `bar.color` |

Every type also honours the universal keys `visible`, `priceLineVisible`, `lastValueVisible` and `title` from `SeriesStyle`. `lastValueVisible` covers **every** series on the pane's readout scale, not only the instrument: an overlay, a comparison line or an indicator plot each tags its own current value in its own colour, and setting it false is how a series opts out. Colour keys left unset fall back to the theme, see [themes-and-styling](themes-and-styling.md) for the exact mapping.

**`colorByPreviousClose` colours a bar against the previous bar's close** instead of its own open, which is how most terminals paint one. Body, border and wick take a single verdict per bar, so the candle cannot disagree with itself. The leftmost drawn bar has no predecessor in the batch, so the pane supplies the close of the bar left of the visible range and it does not flip colour as you scroll; with nothing to compare against (the first bar of history, or a whitespace gap) it falls back to open-vs-close.

**`precision` overrides the decimals a series' labels get** (0 to 8; undefined keeps inferring from tick size or range). It rides the price scale's *formatter*, not its `minMove`, so `precision: 0` formats to whole numbers without also snapping prices to them.

**`baseline` uses `baseValue`; `column` and `histogram` use `base`.** They are separate `SeriesStyle` keys and setting the wrong one silently leaves the default of `0`.

**Only `histogram` honours per-bar `bar.color`.** `column` always colours by `close >= open`, so a two-tone column series needs `histogram` plus a `color` on each data item.

**`hlc-area`'s band fill is not theme-driven.** `closeColor` falls back to `theme.lineColor`, but the fill falls back to a hardcoded `rgba(79,140,255,0.15)`; set `areaTopColor` to control it.

**`area` dashes its outline with `lineStyle` and ignores `markers` and `markersOnly`.** The fill under it stays solid.

**`hlc-area` strokes its band edges only when asked.** `highColor` and `lowColor` have no default: leave them unset and the band is a fill plus the close line, as it has always drawn.

`hollow` is read by `drawCandles`, but the `hollow-candle` type sets it for you. There is no `volumeScaled` flag: body-width scaling by volume is what the `volume-candle` type does, driven by the visible maximum volume.

## Registry defaults

`createSeriesRecord` builds a series' style as `{ ...entry.defaultStyle, ...options.style }`, so these are the only per-type presets:

| Type | `defaultStyle` |
|---|---|
| `candlestick`, `hollow-candle`, `volume-candle`, `bar`, `high-low`, `point-figure` | `{}` |
| `line`, `line-markers` | `{ lineWidth: 1.5 }` (+ `markers: true` for `line-markers`) |
| `step` | `{ lineWidth: 1.5, step: true }` |
| `area`, `hlc-area` | `{ lineWidth: 1.5 }` |
| `baseline` | `{ baseValue: 0, lineWidth: 1.5 }` |
| `column` | `{ base: 0 }` |
| `histogram` | `{ base: 0, color: '#3a4666' }` |
| `kagi` | `{ thickColor: '#26a69a', thinColor: '#ef5350' }` |

## Which data shape each family reads

Every item is normalized to a `Bar` by `toBar` before it reaches a renderer (see [data-and-time](data-and-time.md)).

| Family | Fields consumed | `{ time, value }` point |
|---|---|---|
| candle / bar / `hlc-area` / `point-figure` | `open`, `high`, `low`, `close` | Becomes a flat bar, a zero-height body with no wick. |
| line / `step` / `area` / `baseline` / `kagi` | `close` only | Works as intended. |
| `column` | `close`, and `close >= open` for the colour | Flat bar means `up === true`, so every column is `upColor`. |
| `histogram` | `close`, optional `color` | Works as intended. |
| `volume-candle` | OHLC plus `volume` | No `volume` means every body renders at full width. |

A whitespace item `{ time }` becomes a NaN bar: it claims a logical index, is skipped by autoscale, and breaks the line family into separate segments. Candle and bar renderers do not special-case NaN.

## Renderer geometry

- Body/column width is `optimalBarWidth(barSpacing, dpr)`, `floor(barSpacing * dpr * 0.8)`, minimum 1 device px, parity-matched to the 1px wick so the body stays centred. Exported if a custom renderer needs to line up with it.
- A **filled** candle body takes its border only when `borderVisible` is on and the body is at least 3 device px wide, so `borderUpColor` has no visible effect zoomed right out (a 1px inset stroke would swallow the body). In hollow mode the up candle's outline *is* the body, so it always draws: `borderUpColor` when borders are on, `upColor` when they are off. Down candles are ordinary filled bodies in hollow mode and take `borderDownColor` the same way.
- `candleGeometry(x, barSpacing, dpr, widthScale = 1)` returns `{ cx, bodyX, bodyW, wickX, wickW }` in device px (every field an integer; `widthScale` clamped to `0.05..1`, `bodyW` never below 1). It is the single source of candle snapping: `drawCandles` reads it per bar, and a custom or GPU renderer that rasterises candles with its own primitives lands on the same pixels by reading it too.
- Line strokes are not rounded to whole device px, and use round caps and joins; `lineWidth` is honoured fractionally.
- `volume-candle` scales the body by `volume / maxVisibleVolume` **of the currently visible bars**, clamped to `[0.05, 1]`, so the same bar changes width as you pan.

## Lines across the edge of the view (since 2.5.9)

The types that join each bar to the next (`line`, `line-markers`, `step`, `area`, `hlc-area`, `baseline`, and `kagi` from the transform tier) set `connectsBars` in the registry. Their renderers get the series' nearest bar beyond each edge of the view as well as the bars in it, so the segment that crosses an edge is drawn.

- **A sparse series reaches the edges of the plot.** A level held from 09:20 to 09:40 on an axis that also carries five-second bars still spans the view once the view starts at 09:30, and still spans it when none of its bars is in view at all. In 2.5.8 and before, the part entering from off screen was lost, and with no bar in view the whole line was.
- **The segment is cut at the plot edge**, a few pixels out, before it is stroked or filled. The neighbour can be millions of pixels away, and neither backend walks a dash pattern, or builds GPU quads, over that distance.
- **Dashes stay where they were.** A dashed or dotted line's pattern starts at its first bar in view, as it did before the neighbours were drawn at all, and the segments beyond the view are stroked apart from the bars' own path, so only the added segments are new pixels.
- **A gap is never bridged.** When the bar on either side of an edge has no value (a whitespace item, or a study's NaN), the segment there is dropped, so neither the line nor a fill under it reaches out from the plot edge or across the gap. A `step` still holds its level up to a bar that is a gap, as it does in view.
- **Nothing of the neighbour's own is drawn.** `line-markers` puts no dot on it, and autoscale still reads only the bars in view.
- **Under the level of detail** the neighbours go straight to the renderer, unmerged; the columns in view merge exactly as they would without them.

A custom type opts in with `connectsBars: true` and finds the neighbours by `DrawItem.edgeX` (see [primitives-and-plugins](primitives-and-plugins.md)).

## Transform tier: `point-figure` and `kagi`

These two are valid `SeriesType` names in the base typings but are registered by `src/transform/index.ts`, not the base bundle.

| Type | Draws | `isPriceSeries` | Extents | Style keys |
|---|---|---|---|---|
| `point-figure` | Stacked X / O glyph columns | yes | `low` .. `high` | `boxSize` (fallback only), `upColor`, `downColor` |
| `kagi` | Stepped line alternating thick (yang) / thin (yin) | yes | `close` .. `close` | `thickColor` (`'#26a69a'`), `thinColor` (`'#ef5350'`) |

Calling `addSeries('point-figure')` without loading the tier throws exactly:

```
openalgo-charts: series type "point-figure" needs the transform tier, import 'openalgo-charts/transform' first
```

Any other unregistered name throws `openalgo-charts: unknown series type "<name>"`.

Fix by importing the tier for its registration side effect before creating series:

```ts
import 'openalgo-charts/transform';
```

Heikin Ashi, Renko, Range and Line Break need **no** new type, their transforms emit ordinary bars that render as `'candlestick'`. Only P&F and Kagi have custom renderers. See [transforms](transforms.md) and [bundling-and-tiers](bundling-and-tiers.md).

**A `PointFigureTransform` column carries its own `boxSize`, which wins over `style.boxSize`.** Set the style key only for hand-built column data.

## Switching chart type at runtime

The registry has no "change type" operation: a `SeriesRecord`'s `type` is fixed at creation. Both demos (`examples/phase5-types.html`, `examples/yfinance/index.html`) rebuild instead.

Cheapest correct swap, replace the series, keep the chart and its viewport:

```ts
const range = chart.getVisibleLogicalRange();
series.remove();
series = chart.addSeries(nextType, { style });
series.setData(bars);
chart.setVisibleLogicalRange(range);
```

Full rebuild, what `examples/yfinance/index.html` does, because it also has to reattach indicators, drawings and the volume overlay:

```ts
function render(type: SeriesType) {
  chart?.destroy();
  container.innerHTML = '';
  chart = createChart(container, { theme: darkTheme });
  const series = chart.addSeries(type, styleFor(type));
  series.setData(barsFor(type));
}
```

**Removing the primary series clears the chart's primary-series slot.** `SeriesApi.remove` nulls it, and the *next* `addSeries` with `isPriceSeries: true` claims it, so re-add the price series before any overlay if the OHLC legend and magnet crosshair must stay bound to it.

**`baseline` needs its `baseValue` recomputed on every rebuild.** With the default `0`, a price series renders entirely above the base and the fill fills the whole pane; the demo passes the mean close.

**A rebuild produces fresh handles.** `SeriesMarkers` layers, `PaneLegend` rows and indicator handles from the old chart belong to the destroyed instance and must be recreated.
