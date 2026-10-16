# Themes and styling

*When to read this: picking or building a palette, swapping dark/light at runtime, overriding colours on one series, controlling how values are formatted on an axis, or styling the host's own chrome (dialogs, menus, rails) to sit beside the chart.*

Source of truth: `src/theme.ts`, `src/render/series-style.ts`, `src/model/chart-type-registry.ts`, `src/render/gradient.ts`, `src/core/pane.ts`.

## ChartTheme

One plain object drives chrome, series defaults and the trade layer. All fields are required except the five marked optional.

**Chrome**

| Key | Type | Notes |
|---|---|---|
| `background` | `string` | Pane fill. Also written to the container's inline background. |
| `grid` | `string` | Grid line colour. |
| `axisText` | `string` | Axis tick label colour. |
| `axisLine` | `string` | Axis rule colour. |
| `paneSeparator` | `string` | 1px CSS border-top on every pane but the first. |
| `axisFontSize?` | `number` | Default `11`; renders as `${n}px system-ui, sans-serif`. |
| `gridStyle?` | `'solid' \| 'dashed' \| 'dotted'` | Default `'solid'`. Dashed is `[4,4]`, dotted `[1,3]`, scaled by dpr. |

**Crosshair**

| Key | Type | Notes |
|---|---|---|
| `crosshair` | `string` | Line colour, and the default tag background. |
| `crosshairStyle?` | `'solid' \| 'dashed' \| 'dotted'` | Default `'dashed'`. |
| `crosshairWidth?` | `number` | Device px. Default `1`. |
| `crosshairLabelBackground?` | `string` | Falls back to `crosshair`. |
| `crosshairLabelVisible?` | `boolean` | Default `true`; `false` hides both value tags. |

**Series colours**

| Key | Feeds |
|---|---|
| `upColor` / `downColor` | Candle bodies, candle borders, bar and column strokes. |
| `wickUpColor` / `wickDownColor` | Candle wicks. |
| `lineColor` | `line`, `line-markers`, `step`, `area` stroke; `hlc-area` close stroke. |
| `areaTopColor` / `areaBottomColor` | `area` vertical gradient stops. |
| `baselineTopLine` / `baselineBottomLine` | `baseline` stroke above / below the base. |
| `baselineTopFill` / `baselineBottomFill` | `baseline` fill above / below the base. |

**Last price**

| Key | Notes |
|---|---|
| `lastPriceUp` / `lastPriceDown` | Last-price tag background by direction. |
| `lastPriceText` | Tag text colour, **also the crosshair tag text colour**. |

**Trade layer**

`buy`, `sell`, `profit`, `loss`, consumed by the trading controller and its primitives, see [trading](trading.md).

## darkTheme vs lightTheme

Both are exported objects; `DEFAULT_THEME` is re-exported and **equals `lightTheme`**.

| Key | `darkTheme` | `lightTheme` |
|---|---|---|
| `background` | `#0d0e12` | `#ffffff` |
| `grid` | `#161a26` | `#eef1f6` |
| `axisText` | `#8b91a7` | `#5b6472` |
| `axisLine` | `#2a3046` | `#d4dae3` |
| `paneSeparator` | `#1e2334` | `#e6eaf0` |
| `crosshair` | `#6b7280` | `#9aa3b2` |
| `upColor` / `wickUpColor` | `#26a69a` | `#089981` |
| `downColor` / `wickDownColor` | `#ef5350` | `#e0473e` |
| `lineColor` | `#4f8cff` | `#2962ff` |
| `areaTopColor` | `rgba(79,140,255,0.40)` | `rgba(41,98,255,0.30)` |
| `areaBottomColor` | `rgba(79,140,255,0.00)` | `rgba(41,98,255,0.00)` |
| `baselineTopLine` / `baselineBottomLine` | `#26a69a` / `#ef5350` | `#089981` / `#e0473e` |
| `baselineTopFill` / `baselineBottomFill` | `rgba(38,166,154,0.20)` / `rgba(239,83,80,0.20)` | `rgba(8,153,129,0.18)` / `rgba(224,71,62,0.18)` |
| `lastPriceUp` / `lastPriceDown` | `#26a69a` / `#ef5350` | `#089981` / `#e0473e` |
| `lastPriceText` | `#0d0e12` | `#ffffff` |
| `buy` / `sell` / `profit` / `loss` | `#26a69a` / `#ef5350` (both pairs) | `#089981` / `#e0473e` (both pairs) |

Neither built-in sets the five optional keys, so the optional defaults above apply.

## Applying a theme

```ts
import { createChart, darkTheme, lightTheme } from 'openalgo-charts';

const chart = createChart(el, { theme: darkTheme });   // required: the default is light

chart.setTheme(lightTheme);                            // live swap, no recreate
chart.applyOptions({ theme: darkTheme, grid: { vertLines: false } });
```

A theme is a plain object, spread a built-in and override:

```ts
const custom = { ...darkTheme, background: '#0b0f17', upColor: '#00b386', grid: '#161b27' };
```

Renderers read the theme from the per-frame render context, so `setTheme` repaints everything and existing series pick up new defaults without being touched.

**`background: 'transparent'` skips the pane fill entirely** so the page shows through. `takeScreenshot()` fills with the same value, so screenshots then come out with a transparent backdrop.

## verticalGradient

```ts
import { verticalGradient } from 'openalgo-charts';

const fill = verticalGradient(ctx, plotHeightDevicePx, 'rgba(41,98,255,0.3)', 'rgba(41,98,255,0)');
```

Returns a top-to-bottom `CanvasGradient` for a custom renderer or primitive. Cached in a `WeakMap` keyed by the 2D context, then by rounded height plus both colour strings, a `CanvasGradient` belongs to the context that created it, so never share one across canvases.

## Series style overrides

`SeriesStyle` is one optional-field bag; each renderer reads only the keys it needs. Precedence is **series style > theme > renderer constant**, resolved at draw time.

| Style key | Theme fallback | Applies to |
|---|---|---|
| `upColor` / `downColor` | `upColor` / `downColor` | candle family, `bar`, `high-low`, `column` |
| `borderUpColor` / `borderDownColor` | `upColor` / `downColor` | candle family |
| `wickUpColor` / `wickDownColor` | `wickUpColor` / `wickDownColor` | candle family |
| `borderVisible` / `wickVisible` | none (both default `true`) | candle family |
| `color` | `lineColor` | `line`, `line-markers`, `step`, `area` |
| `closeColor` | `lineColor` | `hlc-area` |
| `areaTopColor` / `areaBottomColor` | `areaTopColor` / `areaBottomColor` | `area` |
| `topColor` / `bottomColor` | `baselineTopLine` / `baselineBottomLine` | `baseline` |
| `areaTopColor` / `areaBottomColor` | `baselineTopFill` / `baselineBottomFill` | `baseline` |
| `color` | **none**: hardcoded `#3a4666` | `histogram` |
| `lineWidth` | none (default `1.5`) | line family |
| `lineStyle` | none (default `'solid'`) | `line`, `line-markers`, `step` |
| `markers`, `markersOnly`, `markerRadius` | none (radius default `2`) | line family |
| `visible`, `title`, `priceLineVisible`, `lastValueVisible` | none (all default on/true) | every type |

`lastValueVisible` tags every series on the readout scale, each in its own plot colour, not just the instrument. A series currently plotting a non-number draws no tag, so a study that is `na` says nothing rather than repeating a stale reading. Tags resolve against the ladder and each other by priority: the last price wins, a series value beats a plain tick, and two series values a tag-height apart resolve by series order rather than flickering.

```ts
const series = chart.addSeries('candlestick', {
  style: { upColor: '#16a34a', downColor: '#dc2626', borderVisible: false },
});
series.applyOptions({ downColor: '#b91c1c' });   // merge + repaint, no recreate
series.applyOptions({ visible: false });          // hides it and drops it from autoscale
```

**`histogram` is the one series colour the theme cannot reach.** Its `color` falls back to `#3a4666` regardless of palette, so a themed volume overlay must set `style.color` (or per-item `bar.color`) itself.

**`priceLineVisible: false` and `lastValueVisible: false` only take effect on the first `isPriceSeries` series mapped to the pane's right scale**: that is the only series the last-price line and tag follow.

## legendOffset

```ts
createChart(el, { legendOffset: { top: 34, left: 12 } });   // default { top: 6, left: 8 }
```

Media px where **indicator** legend rows start inside the price pane, wherever it sits (`primaryPaneIndex()`, the top pane unless the host moved it below its studies). Every other pane keeps `{ top: 6, left: 8 }`, and host-added `PaneLegend` rows are never repositioned. Raise it when the app draws its own symbol or OHLC overlay in the price pane's corner, otherwise indicator rows render underneath it and their buttons become unclickable. The offset follows a maximized study pane, which then fills the corner the price pane left. A host overlay drawn as DOM over the price pane should follow `panes()[primaryPaneIndex()].element` after a `paneMoved`.

## priceFormat

Set on `addSeries`; it configures the series' **price scale**, so it affects that scale's axis labels and crosshair tag.

```ts
chart.addSeries('line',      { priceFormat: { type: 'price', minMove: 0.05 } });
chart.addSeries('line',      { priceFormat: { type: 'price', precision: 4 } });
chart.addSeries('histogram', { priceScaleId: '', priceFormat: { type: 'volume' } });
chart.addSeries('area',      { priceFormat: { type: 'custom', formatter: (v) => 'Rs ' + v.toFixed(2) } });
```

- `'price'`: sets `minMove` on the scale. `precision: n` is converted to `minMove = 10^-n`. With neither key the option does nothing.
- `'volume'`: installs `compactVolume` (exported): `1.20K` / `3.40M` / `5.60B`, and `Math.round` below 1000.
- `'custom'`: installs `formatter` directly. The variant accepts **only** `type` and `formatter`; to also change tick precision call `series.priceScale().setOptions({ minMove })`.

Chart-wide formatting is `ChartOptions.priceFormatter` / `chart.setPriceFormatter(fn | null)`, which overrides every pane's right-scale formatter, see [core-api](core-api.md).

## Host chrome: the UI standard

The engine ships no DOM, so the settings dialog, the context menus, the toolbars and the rails are all yours. The chart is finished work; chrome that is not held to the same bar is what makes the whole app look unfinished. Each rule below is here because it was got wrong once.

**Borrow the craft, not the design.** Professional terminals set the bar for density, crispness and finish, and that bar is the one to clear. They do not set the layout, the grouping or the words. Shared domain vocabulary is plain property and should be used plainly: logarithmic, percent, indexed to 100, auto, invert, precision, timezone, session. Another product's turns of phrase and its particular way of carving settings into tabs are not; write your own labels and your own grouping.

**Never leave a default scrollbar on a dark surface.** A white OS scrollbar against a dark panel is the single most obvious tell that a UI was not finished. Style it once at the root so every scrollable surface inherits it:

```css
* { scrollbar-width: thin; scrollbar-color: #2c3547 transparent; }
*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-track { background: transparent; }
*::-webkit-scrollbar-thumb { background: #2c3547; border-radius: 4px; }
*::-webkit-scrollbar-thumb:hover { background: #3a465c; }
```

The thumb belongs a step lighter than the panel, never white; the track should read as part of the panel.

**A colour control is a small rounded square, not a bar.** Roughly 26 to 28 px with a 5 to 6 px radius. A full-width 140 px colour block is a bug, not a style choice.

**Up and down colours share one row**, with the row's switch in front of them:

```text
[x] Body      [up] [down]
[x] Borders   [up] [down]
[x] Wick      [up] [down]
```

Not a BODY section header followed by separate Up and Down rows. The stacked form triples the height of every panel and is what forces a scrollbar to appear at all. The settings schema's `colorPair` control exists so this shape is renderable straight from the descriptor, including the case where a pair has **no** switch behind it: leave the switch slot empty and keep the swatches aligned. See [settings-and-menus](settings-and-menus.md).

**No browser-default form controls on a dark panel.** A native blue checkbox and a native `<select>` chevron both break the theme. Style checkboxes (dark fill, subtle border, a clear tick when checked) and selects (`appearance: none`, panel background, an inline-SVG chevron).

**Crisp and compact beats roomy.** Prefer a panel that fits without scrolling. Section headers small, uppercase and muted; rows tight; a tab rail with a small glyph per tab, inline SVG rather than an icon font.

**Dialog furniture.** Title left, close affordance top right, actions bottom right with the confirming action last, and any secondary control (a template picker, a "restore defaults" for the visible tab) bottom left.

**Never ship a control with nothing behind it.** A checkbox that does nothing is worse than an absent one. If the engine cannot back a control another terminal offers, leave it out.

**A control with no data in the current context is a different case: render it disabled with its state visible, never hidden.** "No previous session yet" is information; a missing checkbox is not. The engine reports this for you:

| Reading | Disable when |
|---|---|
| `PriceLevels.available(kind)` | `false`: that level has no data (no previous session, no quote feed, no market-phase classifier). |
| `PriceAxisState.active` | `false`: no series maps to that scale. |
| `PriceAxisState.scaled` | `false`: nothing has measured it yet, so a price-per-bar lock cannot be taken. |
| `PriceAxisState.movable` | `false`: nothing to move, or the other side is occupied. |

**No emoji and no icon-font glyphs in labels, code, comments or logs.** Plain text, everywhere.
