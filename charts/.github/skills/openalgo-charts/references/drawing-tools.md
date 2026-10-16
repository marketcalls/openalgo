# Drawing Tools

*When to read this: you are adding chart annotations (trendlines, fibs, shapes, text) wiring a drawing toolbar, persisting drawings, or registering a custom tool.*

Source of truth: `src/draw/analysis.ts`, `src/draw/analysis-tools.ts`, `src/draw/advanced-lines.ts`, `src/draw/advanced-geometry.ts`, `src/draw/pattern-tools.ts`, `src/draw/types.ts`, `src/draw/registry.ts`, `src/draw/tools.ts`, `src/draw/fib-tools.ts`, `src/draw/measure-tools.ts`, `src/draw/annotation-tools.ts`, `src/draw/controller.ts`, `src/draw/layer.ts`, `src/draw/geometry.ts`, `src/draw/index.ts`.

## Setup

```ts
import { createChart } from 'openalgo-charts';
import { DrawingController } from 'openalgo-charts/draw';

const chart = createChart(el);
chart.addSeries('candlestick').setData(bars);

const draw = new DrawingController(chart, { magnet: 'weak' });   // or 'strong', 'off'; true means 'strong'
draw.setTool('trend-line');   // the next two clicks place it
```

Importing `openalgo-charts/draw` calls `registerBuiltinDrawingTools()` as a side effect, registering all 87 tools into the tier's own tool registry. No separate registration call is needed.

**The controller is headless: it ships no toolbar, no dialogs, no key listener.** It owns the model (`Drawing[]`), placement, selection, dragging, undo, and serialisation. Every button, flyout, colour picker, and text prompt is the host's.

`DrawingController` takes a structural `DrawingChartHost`, not the `Chart` class, so the chart from `createChart()` is accepted with no cast (`src/draw/controller.ts:33`).

## The model

```ts
interface Drawing {
  id: string;
  tool: string;              // a registered tool id
  points: DrawingPoint[];    // { time: UTC seconds, price: number, pressure? }; [] on a viewport drawing
  space?: DrawingSpace;      // 'data' (absent, the default) or 'viewport' (see Viewport-anchored drawings)
  viewportPoints?: ViewportPoint[];  // { x, y } fractions of the pane's plot; only when space is 'viewport'
  style: DrawingStyle;
  text?: DrawingText;        // the label, or for the text tool the whole content
  props?: Record<string, unknown>;   // per-tool extras, JSON-safe, persisted verbatim
  paneIndex: number;
  locked?: boolean;          // renders, but cannot be selected or dragged
  policy?: DrawingPolicy;    // host restrictions: selectable, editable, persistent, listed (see Drawing policies)
  visible?: boolean;         // default true
  zIndex: number;            // paint order; below 0 paints under the series. add() fills in 0
  createdAt?: number;        // epoch ms, set by add()
}

interface DrawingStyle {
  color?: string; lineWidth?: number; lineStyle?: 'solid' | 'dashed' | 'dotted';
  fill?: boolean; fillColor?: string; fillOpacity?: number;      // default 0.12
  extendLeft?: boolean; extendRight?: boolean;
  showLabels?: boolean;                                           // level / price / ratio labels where the tool has them
  levels?: FibLevel[];                                            // fib and gann family; defaults per tool
  accountSize?: number; risk?: number;                            // position tools
  showStats?: boolean;                                            // line family: midpoint readout
  pressure?: boolean;                                             // brush: pen pressure drives the width
}

interface DrawingText {
  value: string;                                                  // `\n` starts a new line
  color?: string;                                                 // falls back to style.color
  fontSize?: number; fontFamily?: string;                         // media px (default 12); UI sans stack
  bold?: boolean; italic?: boolean;
  align?: 'left' | 'center' | 'right';                            // default 'left'
  valign?: 'top' | 'middle' | 'bottom';                           // default 'top'
  wrap?: boolean; wrapWidth?: number;                             // default 220 media px
  background?: boolean; backgroundColor?: string; backgroundOpacity?: number;   // plate; opacity default 1
  border?: boolean; borderColor?: string;
  position?: 'inside' | 'outside';                                // shapes only: where the label sits
}

interface FibLevel { ratio: number; color?: string; enabled?: boolean; label?: string; }
```

Unset `color` falls back to `theme.lineColor`, unset `lineWidth` to `1.5`. `style.color` strokes the outline; `text.color` paints an attached label, so one shape carries two colours. `text.position: 'outside'` parks the label above the shape and ignores `valign`. Nothing about text lives on `style`: a 1.9.x `style.text`, `fontColor`, `fontWeight`, `fontStyle`, `textAlign`, `textVAlign` or `textPosition` is a type error in 2.0, and `migrateDrawings` lifts them into `drawing.text` on load. `levels` is a list of `FibLevel` objects, never bare ratios.

## Anchors are `{ time, price }`, never pixels

The time axis is gapless (weekends, holidays, and session breaks collapse) so a pixel anchor would slide the instant the viewport, interval, or dataset changed. Anchors resolve through `DataLayer.timeToIndexFloat`, which is *fractional*, and that has two consequences worth relying on:

- An anchor can sit **inside a collapsed gap** (a Saturday between Friday and Monday) and still map to a stable x.
- An anchor can sit **past the last bar**, which is where trend projections, `forecast`, and the position tools' targets live. The bar times there come from the session calendar when the host set one (`chart.setSessionCalendar`, `SessionCalendar.applyTo`, `Instrument.applyTo` or `chart.dataLayer.setSessionCalendar`), so an endpoint drawn past Friday's close lands on Monday's session; without one they run at the median recent bar interval, never at a night- or weekend-sized last gap. See [times past the last bar](data-and-time.md#times-past-the-last-bar).

Drag deltas are computed in data space too (`p.time - start.from.time`), so translating a shape keeps it on the same bars.

The one exception is a drawing pinned to the screen (`space: 'viewport'`), whose anchors are fractions of its pane's plot in a field of their own, `viewportPoints`. Its time and price are never overloaded with pixels. See [Viewport-anchored drawings](#viewport-anchored-drawings-255).

## Anchored analysis drawings

`ANCHORED_VWAP` (`anchored-vwap`) is a one-anchor `DrawingTool`;
`FIXED_RANGE_VOLUME_PROFILE` (`fixed-range-volume-profile`) takes two anchors.
They use the owning pane's primary OHLCV bars through `DrawContext.rc.bars`.
Arm them with `draw.setTool(id)`, or `draw.add()` the usual `{ tool, points,
style, props, paneIndex }` model. They use ordinary selection, drag, undo,
delete and version-2 JSON persistence. They require no profile or indicator tier.

Anchors remain UTC seconds across data reloads. VWAP starts at the first loaded
bar at or after its time. Profile includes bars within the two timestamps,
regardless of anchor order. The stored price positions the editing handle; it
does not change the data calculation. Calculations use loaded data only and
recompute forming-bar changes, including in-place changes with the same timestamp.

| Tool | `props` | Effective default and bounds |
|---|---|---|
| Anchored VWAP | `source` | `hlc3`; alternatives `close`, `hl2`, `ohlc4` |
| Anchored VWAP | `showBands`, `bandMultiplier` | `true`, `1`; multiplier 0..5 |
| Volume profile | `rows` | `48`; requested count rounded and clamped to 4..200, reduced for indistinguishable price edges, flat prices use one row |
| Volume profile | `valueArea` | `70`; percent clamped to 1..100 |
| Volume profile | `width`, `side` | `35` percent of anchor span (5..100), `left` or `right` |
| Volume profile | `showPoc`, `showValueArea` | Both `true` |

VWAP bands use volume-weighted population standard deviation of the selected
source. Profile distributes each candle's volume uniformly over its low-to-high
range. This is an estimated candle profile, not exchange trade-by-trade volume.
Its POC is the largest row's midpoint (lower row wins a tie), and the contiguous
value area grows toward the larger adjacent volume row (lower on ties).
Histogram allocation is O(selected bars log(rows) + rows), with at most 200
row boundaries. Rounded duplicate boundaries are merged and allocation uses
the remaining row widths to conserve volume. Both tools expose line and
label settings; profile histogram opacity is `style.fillOpacity`, default `0.4`.

Missing, negative or nonfinite volume is unavailable; zero is known and carries
no weight. Partially available data is labelled partial. Fully missing and
zero-volume results remain distinct. Unavailable-price/overflow results report
`invalid-data`. Data-quality notices stay visible even with `showLabels: false`.
No-value results paint selectable anchor crosses, so restored drawings remain
editable before history or volume is available.

Both result types expose `historyPartial: boolean`. It is true when the requested
anchor or range start precedes the earliest supplied bar. A usable calculation
then reports `status: 'partial'` and the drawing labels it as partial history,
separately from missing volume. Prepend history through the requested start to
obtain a complete calculation; the original anchor timestamps remain unchanged.

```ts
import {
  anchoredVwapAnalysis, fixedRangeVolumeProfileAnalysis,
  ANCHORED_VWAP, FIXED_RANGE_VOLUME_PROFILE,
} from 'openalgo-charts/draw';

const vwap = anchoredVwapAnalysis(bars, anchorTime, { source: 'close' });
const profile = fixedRangeVolumeProfileAnalysis(bars, fromTime, toTime, {
  rows: 48, valueArea: 70,
});
```

Pure calculator inputs are sorted by ascending timestamp. `AnchoredVwapOptions`
contains `source?: AnchoredVwapSource`; `AnchoredVwapResult` contains `status`, `historyPartial`,
`points: AnchoredVwapPoint[]`, `missingVolumeBars` and `invalidPriceBars`.
Each point has `time`, `value`, `deviation`, `breakBefore` (do not connect a
curve across omitted observations). `FixedRangeVolumeProfileOptions` contains
`rows?` and `valueArea?`. `FixedRangeVolumeProfileResult` contains `status`, `historyPartial`,
`rows: AnalysisProfileRow[]`, `totalVolume`, nullable `poc`, `valueAreaLow`,
`valueAreaHigh`, `missingVolumeBars` and `invalidPriceBars`. A profile row has
`low`, `high`, `volume`, `valueArea`. All these types are exported by the draw tier.
`AnalysisStatus` is `ready | partial | missing-volume | zero-volume | empty |
invalid-data`. Check the status before presenting a calculation as complete.

`SettingsField.defaultValue?: string | number | boolean` supplies the effective
default for an unset property. `readDrawingSettings()` resolves it without
mutating the drawing. Use the schema to render the settings dialog; do not
show an unchecked band toggle when the effective `showBands` default is true.

## Annotations

Six one-anchor tools whose job is a human sentence on the chart. They share
plate-and-tail machinery, so what separates them is where the tail leaves the
plate and how the plate is shaped:

| `id` | Shape | Anchored to |
|---|---|---|
| `note` | Pin at the bar, plate up-right, stem between | A bar |
| `balloon` | Speech bubble above, tail pointing down | A bar |
| `comment` | Quieter square box, tail off the bottom left | A bar |
| `signpost` | Vertical post with the plate at the top | **Time**, not price |
| `price-note` | The anchor's price, with text beneath | A level |
| `table` | A grid of cells | A corner |

Two conventions worth knowing:

- **`price-note` reads its price off the anchor** rather than storing one, the
  same as `price-label`. A typed price is a number that was true once, which on
  a chart is worse than no number.
- **`table` encodes its cells in `text.value`**: a newline starts a row, a pipe
  separates columns, and the first row is drawn bold as a header. One editable
  string, so a table needs no new shape in the drawing model and survives
  `getState` unchanged.

Everything else comes from the shared text block, `drawing.text`: `value`,
`fontSize`, `color`, `backgroundColor`, `border`, plus `style.fillOpacity`.

## Icons

The tier ships a glyph for every tool, as path data:

```ts
import { drawingToolIcon, drawingToolAccent, ICON_ATTRS } from 'openalgo-charts/draw';

const accent = drawingToolAccent('trend-line');   // the two anchor dots, for a fill
<svg {...ICON_ATTRS} width={24} height={24}>
  <path d={drawingToolIcon('trend-line')} />
  {accent && <path d={accent} fill="currentColor" stroke="none" />}
</svg>
```

Each path is the whole glyph. The marks that tell siblings apart (a trend
line ends in two dots, a ray starts at one, a path ends in a head) are drawn in
the path itself as small closed outlines, so a host that renders only the path
data still shows every one of them. An **accent** repeats those marks for a
fill on top: it adds weight, never identity. The builders below always draw it,
as a second `<path>` with `fill="currentColor" stroke="none"`; a host wrapping
the raw path data may do the same, and loses only the fill if it does not.

| Export | |
|---|---|
| `DRAWING_TOOL_ICONS` | `Record<string, string>` of tool id to `d` attribute |
| `drawingToolIcon(id)` | One glyph, or `undefined` when there is none |
| `DRAWING_TOOL_ACCENTS` / `drawingToolAccent(id)` | The optional fill per tool glyph: marks its path already outlines, as a second `d`; `undefined` when a glyph has none |
| `drawingToolIconIds()` | Every id the set covers |
| `ICON_VIEWBOX` | `'0 0 24 24'` |
| `ICON_SIZE` | `20`: the CSS pixel size the tool tier is drawn for, and `iconSvg`'s default size (since 2.6.3; it was the 24px grid size) |
| `ICON_STROKE` | `1.6`: about 1.3px at `ICON_SIZE` (it was `2` through 2.6.2) |
| `ICON_ATTRS` | The whole attribute bag for the `<svg>` (an `IconAttrs`) |
| `CHROME_ICONS` | `Record<string, string>` of chrome id to `d` attribute, on a 16 grid: the buttons, bars, menus and dialogs around a chart (the ids are listed below), and a glyph per chart type under `chart-<id>` |
| `chromeIcon(id)` / `chromeIconIds()` | One chrome glyph or `undefined`; every chrome id, the `chart-` ones included |
| `CHROME_ICON_ACCENTS` / `chromeIconAccent(id)` | The chrome fills (the eye's pupil, the camera lens, slider knobs, pole caps, a drawing's anchors, a head, a line's markers), each also outlined in its glyph's path |
| `CHROME_ICON_VIEWBOX` / `CHROME_ICON_SIZE` / `CHROME_ICON_STROKE` / `CHROME_ICON_ATTRS` | `'0 0 16 16'`, `16` (since 2.6.3), `1.3` (2 from 2.5.6 through 2.6.2, 1.5 before; pass `{ stroke: 2 }` to keep the heavier weight), the attribute bag |
| `CHROME_ICON_FILLED` | The chrome ids painted solid rather than stroked: `star-filled`, `pin-filled`, the media controls (`replay`, `play`, `stop`, `step-forward`, `step-back`, `record`), `buy`, `sell`, `moon` and `market-closed` (`chromeIconSvg` consults it; a host wrapping raw path data must too) |
| `chartTypeIcon(type)` | The chrome glyph for a chart type or a transform (`candlestick`, `point-figure`, `heikin-ashi`, `renko`, `range-bars`, `line-break`, ...): the `chart-<type>` entry of `CHROME_ICONS`, so `chromeIconSvg('chart-' + type)` draws it. `undefined` for a type a host registered itself |
| `layoutIconPath(rows, columns, slots?)` | A chrome `d` for a grid of charts: the frame split into `rows` by `columns`, one to four each, with no divider inside a slot that spans cells (a `LayoutIconSlot[]`: `row`, `column`, optional `rowSpan` and `columnSpan`). Cells no slot claims are panes of their own. Throws a `RangeError` for more than four a side, a slot outside the grid, or two slots that overlap. A chart grid itself takes up to eight a side, so a button that shows the current layout draws `layout` past four |
| `iconSvg(id, opts?)` / `chromeIconSvg(id, opts?)` | A complete inline `<svg>` string in `currentColor`, the accent included; `size` in px or `'1em'` (an `IconSvgOptions`). Throws on an unknown id |
| `iconSprite(ids?)` / `iconUse(id, opts?)` | One hidden symbol sheet (ids `oac-icon-<id>`, `ICON_SYMBOL_PREFIX`) and the per-glyph `<use>`; symbols carry no stroke weight, so it inherits from the frame, and an accent carries only `fill="currentColor" stroke="none"` |
| `toolCursor(id, opts?)` | A CSS `cursor` value carrying the glyph over a contrasting halo, its accent filled; `size` 1..128 (default 20), `hotspot` (default the centre), `color`, `halo`, `fallback` (a `ToolCursorOptions`) |

The chrome ids a host may code against, besides the chart types, are
(the 29 of the first row since 2.5.9, the rest since 2.5.10):

| Group | Ids |
|---|---|
| Shipped through 2.5.9 | `cursor` `magnet` `lock` `unlock` `eye` `eye-off` `star` `star-filled` `trash` `settings` `undo` `redo` `copy` `paste` `duplicate` `front` `back` `text` `chevron-down` `chevron-right` `close` `plus` `minus` `search` `grid` `link` `unlink` `camera` `download` |
| Capture and navigation | `capture-grid` `chevron-up` `chevron-left` `chevrons-left` `chevrons-right` (2.6.3) `check` `more` `grip` `refresh` `swap` |
| A grid of charts | `layout` `maximize` `restore` `fullscreen` `fullscreen-exit` `link-group` `drawing-sync` `crosshair` `time-range` `palette` |
| Time and the session | `calendar` `clock` `globe` `market-open` `market-pre` `market-post` `market-closed` `market-holiday` |
| Replay | `replay` `play` `pause` `stop` `step-forward` `step-back` `record` |
| Price scale | `scale-auto` `scale-log` `scale-percent` |
| Layouts and files | `folder` `save` `save-as` `autosave` `rename` `recent` `template` `keyboard` |
| Status | `bell` `bell-off` `pin` `pin-filled` `info` `warning` `error` `sun` `moon` |
| Drawing and text | `eraser` `measure` `fill` `bold` `italic` |
| Panels | `watchlist` `news` `account` `compare` `indicators` |
| Trading | `buy` `sell` `close-position` `reverse` `bracket` `dom-ladder` |
| Settings tabs and menu marks | `legend` `axes` `panels` `trading` `brush` `above-series` `behind-series` `fit` `coordinates` `line-dashed` `line-dotted` `line-mixed` (the solid line style is `minus`) |
| Chart types (read with `chartTypeIcon`) | `chart-candlestick` `chart-hollow-candle` `chart-volume-candle` `chart-heikin-ashi` `chart-bar` `chart-high-low` `chart-line` `chart-line-markers` `chart-step` `chart-area` `chart-hlc-area` `chart-baseline` `chart-column` `chart-histogram` `chart-point-figure` `chart-kagi` `chart-renko` `chart-range-bars` `chart-line-break` |

```ts
import { chartTypeIcon, chromeIconSvg, layoutIconPath, CHROME_ICON_ATTRS } from 'openalgo-charts/draw';

// A chart-type menu row: the glyph when the type has one, an empty slot otherwise.
const glyph = chartTypeIcon(type) !== undefined ? chromeIconSvg(`chart-${type}`) : '';

// A layout picker tile: one tall chart beside two.
const d = layoutIconPath(2, 2, [{ row: 0, column: 0, rowSpan: 2 }, { row: 0, column: 1 }, { row: 1, column: 1 }]);
<svg {...CHROME_ICON_ATTRS} width={16} height={16}><path d={d} /></svg>
```

The widget tier draws every picture it shows from this set (since 2.5.10): the
chart-type menu, the type button and the phone layout's sheet show
`chart-<type>`, the theme button `sun` or `moon`, and the settings tabs, the
stacking rows, the drawing toolbar's line styles, the menu tick and the level
editor's remove cross the ids above. None is hand-drawn in a widget file, so
the grid, overlap and weight checks on this registry cover the widget too.

The path data is data, not DOM: the host still builds its own rail and
flyouts. The string builders derive from that one set, so the rail, a flyout
and the tool cursor cannot drift apart. What the host no longer does is draw
a glyph per tool before it can show a toolbar, which is what every adopter had
to do before, each drifting on weight and grid independently until the set
read as many icons rather than one. Measure the count with
`drawingToolIconIds().length` before quoting it: the tool set covers more ids
than there are tools (the cursor, the magnet, and glyphs drawn ahead of tools
not yet registered).

**Render tools at `ICON_SIZE` (20px) and chrome at `CHROME_ICON_SIZE` (16px).**
Since 2.6.3 each tier's stroke is set so that its line is about 1.3px on
screen at that size, so a rail of tools and the chrome under it read as one
fine set. Through 2.6.2 both tiers drew a 2px line at their grid size (24px
and 16px): every straight edge sat on a pixel boundary, but a line half
again as wide on tool glyphs a fifth larger is nearly twice the ink, and a
rail of them read as heavy beside the chart. A host that shows a glyph at
another size scales the line with it; to keep the same line, set the stroke
for that size: the line in pixels is `stroke * size / 24` for a tool glyph
and `stroke * size / 16` for a chrome glyph, each tier's viewBox width. A host that wants the heavier set back passes it explicitly
(`iconSvg(id, { size: 24, stroke: 2 })`, `chromeIconSvg(id, { stroke: 2 })`, or
`stroke-width` in its own frame or stylesheet). `toolCursor` keeps a 2-unit
line: a cursor sits over candles and grid lines, not a quiet panel.

The set is held to one grid by `tests/draw-icons.test.ts`, which checks each
glyph and accent for the live area (2..22 and 2..14), whole units, a single
weight, complexity and span, that every accent mark is also in its glyph's
path, that no hollow shape is filled in by the glyph's other strokes, and
rejects two glyphs that are the same drawing written differently.
`tests/e2e/icon-raster.spec.ts` rasterises both tiers in Chromium, Firefox and
WebKit, as the builders draw them and as bare path data, and fails when two
glyphs overlap at an intersection over union of 0.85 or more (only the star,
eye, link and pin state pairs may), when a named sibling pair reaches 0.7, or
when the two tiers stop drawing one line weight at their sizes. The siblings are the members of one menu or bar:
the replay controls, the market session, the scale modes, the three levels,
the layout menu, the trading actions, the line styles, the link channels, and
every chart type against every other. The layout tiles share their frame by
design, so they are held to a different rule: every two differ by at least a
short divider's pixels, and each is crisp. A glyph added to either registry has
to pass both files, and a chrome id added or removed changes the published id
list in the unit test, since hosts name these ids in their own code.

## Tool catalogue

87 built-in tools. `Clicks` is what the user does; `Anchors` is what ends up in `drawing.points` (they differ only where `expand` is involved).

| Family | `id` | Clicks | Anchors | Shortcut |
|---|---|---|---|---|
| Lines | `trend-line` | 2 | 2 | `Alt+T` |
| Lines | `ray`, `extended-line`, `arrow` | 2 | 2 | |
| Lines | `horizontal-line`, `horizontal-ray`, `vertical-line`, `cross-line` | 1 | 1 | `Alt+H`, `Alt+J`, `Alt+V`, `Alt+C` |
| Shapes | `rectangle`, `ellipse`, `circle` | 2 | 2 | |
| Shapes | `triangle`, `rotated-rectangle` | 3 | 3 | |
| Paths | `path`, `polyline` | n, double-click to end | n | |
| Paths | `arc`, `curve`, `double-curve` | 3 | 3 | |
| Channels | `parallel-channel`, `fib-channel` | 3 | 3 | |
| Fibonacci | `fib-retracement`, `fib-time-zone`, `fib-fan` | 2 | 2 | |
| Fibonacci | `fib-extension` | 3 | 3 | |
| Gann | `gann-fan`, `gann-box` | 2 | 2 | |
| Cycles | `cyclic-lines`, `time-cycles`, `sine-line` | 2 | 2 | |
| Forecasting | `long-position`, `short-position` | 2 | 3 (via `expand`) | |
| Forecasting | `forecast` | 2 | 2 | |
| Measurers | `measure`, `price-range`, `date-range` | 2 | 2 | |
| Arrows | `arrow-up`, `arrow-down` | 1 | 1 | |
| Text / notes | `text`, `price-label`, `flag-mark` | 1 | 1 | |
| Annotations | `note`, `balloon`, `comment`, `signpost`, `price-note`, `table` | 1 | 1 | |
| Marks | `arrow-up`, `arrow-down`, `arrow-left`, `arrow-right` | 1 | 1 | |
| Text / notes | `callout` | 2 | 2 | |
| Brushes | `brush`, `highlighter` | press-drag-release | n samples | |
| Lines | `info-line`, `trend-angle` | 2 | 2 | |
| Channels | `disjoint-channel` | 4 | 4 | |
| Channels | `flat-top-bottom` | 3 | 3 | |
| Channels | `regression-channel` | 2 | 2 | |
| Pitchforks | `pitchfork`, `schiff-pitchfork`, `modified-schiff-pitchfork`, `inside-pitchfork` | 3 | 3 | |
| Fibonacci | `fib-extension-two-point`, `fib-speed-resistance-fan`, `fib-circles`, `fib-speed-resistance-arcs`, `fib-spiral` | 2 | 2 | |
| Fibonacci | `trend-fib-time`, `fib-wedge` | 3 | 3 | |
| Gann | `gann-square` | 2 | 2 | |
| Geometry | `dedekind-tessellation`, `sonic`, `supersonic`, `golden-sonic`, `golden-supersonic` | 2 | 2 | |
| Marks | `icon-stamp` | 1 | 1 | |
| Patterns | `xabcd-pattern`, `gartley`, `bat`, `butterfly`, `crab`, `shark`, `cypher` | 5 | 5 | |
| Patterns | `abcd-pattern` | 4 | 4 | |
| Patterns | `elliott-correction` | 3 | 3 | |
| Patterns | `elliott-impulse` | 5 | 5 | |
| Patterns | `head-shoulders` | 7 | 7 | |
| Analysis | `anchored-vwap` | 1 | 1 | |
| Analysis | `fixed-range-volume-profile` | 2 | 2 | |

Those five are the only shortcuts. `registeredDrawingTools()` returns every descriptor (`id`, `name`, `points`, `shortcut`, `defaultStyle`); `BUILTIN_DRAWING_TOOLS` is the same list in toolbar order.

Tool-specific `defaultStyle` values that change behaviour, not just colour:

| Tool | `defaultStyle` |
|---|---|
| `trend-line` / `ray` / `extended-line` / `arrow` | `extendLeft`/`extendRight` = `false,false` / `false,true` / `true,true`; `showStats: true` adds a midpoint readout (price change, percent, bars, angle) |
| `rectangle` / `ellipse` / `circle` / `triangle` / `rotated-rectangle` | `fill: true`; a label comes from `drawing.text` (`align`, `valign`, `position: 'inside' | 'outside'`), 14 px when the block sets no size |
| `fib-retracement` / `fib-extension` / `fib-channel` | `levels: cloneLevels(DEFAULT_FIB)` (ratios 0 to 1 with the conventional colours), `showLabels: true`. The anchor leg is stroked in `style.color`; bands are tinted by the level that closes them unless `fillColor` is set; `extendLeft` / `extendRight` are honoured |
| `fib-fan` / `gann-fan` / `gann-box` / `fib-time-zone` | `levels: cloneLevels(DEFAULT_FIB_FAN / DEFAULT_GANN_FAN / DEFAULT_GANN_BOX / DEFAULT_FIB_TIME_ZONE)` |
| `long-position` / `short-position` | `accountSize: 100000, risk: 1, fillOpacity: 0.13, showLabels: true`; the zones take the theme's `upColor` / `downColor` unless `props.profitColor` / `props.lossColor` are set, and `measure`, `price-range`, `forecast` and a line's `showStats` readout are tinted by direction the same way |
| `text` / `callout` | `defaultText: { value: 'Text', fontSize: 14 }` / `{ value: 'Note', fontSize: 12 }` (a `DrawingText`, merged under the caller's `text`) |
| `brush` / `highlighter` | `lineWidth: 2` / `lineWidth: 12, fillOpacity: 0.28`; `pressure: true` lets a pen's per-sample `DrawingPoint.pressure` drive the width (off by default, so a mouse stroke is constant) |
| `cyclic-lines` / `forecast` | `lineStyle: 'dashed'` |

`fib-time-zone` uses the Fibonacci **sequence** (`0,1,2,3,5,8,13,21,34,55` bar multiples), not ratios, and its levels carry no colour (they fall back to `style.color`). `gann-fan` levels are price-per-time ratios (`1x1` = 1, `1x2` = 0.5, `2x1` = 2), coloured by `cycleColor(i)` and labelled by `gannLabel`; `gann-box` applies `DEFAULT_GANN_BOX` (0, .25, .382, .5, .618, .75, 1) to both axes plus the 1x1 diagonal. `circle` measures its radius in screen px so it stays round. `arc` passes *through* its middle anchor; `curve` treats it as an off-curve control.

## The 2.0 drawing model

`Drawing` is `{ id, tool, points, style, text?, props?, paneIndex, locked?, visible?, intervals?, zIndex, createdAt? }`.

- **`text` is its own block (`DrawingText`)**, not a set of keys on `style`: `{ value, color?, fontSize?, fontFamily?, bold?, italic?, align?, valign?, wrap?, wrapWidth?, background?, backgroundColor?, backgroundOpacity?, border?, borderColor?, position? }`. A 1.9.x `style.text` / `fontColor` / `textAlign` / `textVAlign` / `textPosition` / `fontWeight` / `fontStyle` is lifted into it on load and paste. The text tool is its content; a shape's text is a label placed by `position`.
- **`style.levels` is `FibLevel[]`** (`{ ratio, color?, enabled?, label? }`; `enabled: false` hides a rung without forgetting it, `label` prints instead of the ratio), not `number[]`. A bare ratio takes the conventional colour from `levelColor(ratio)` (`LEVEL_NEUTRAL` for 0, 1, 2, 3 and anything unnamed); the migration attaches those colours, and `cloneLevels` copies a ladder so a tool default is never shared. `formatRatio` prints a level label, `CYCLE_PALETTE` / `cycleColor(i)` colour a sequence, and `DEFAULT_FIB`, `DEFAULT_FIB_FAN`, `DEFAULT_GANN_BOX`, `DEFAULT_GANN_FAN`, `DEFAULT_FIB_TIME_ZONE` are the frozen defaults.
- **`zIndex` is paint order.** Below zero paints under the series, at or above zero over it; ties break by list order, so `drawings()` is the paint order. `sortByZIndex(list)` is the stable sort the layer uses, and `DrawingLayerOrder` (`'bottom' | 'series' | 'top'`) is which layer a pane primitive is. A default of 0 paints exactly where 1.9.2 painted.
- **`stackAbove` places a drawing in the series band.** It names an entry of `chart.seriesStack(paneIndex)` (`'source:primary'` or `'indicator:<id>'`); the drawing paints right after that entry's series and before the next entry's, and `zIndex` orders the drawings on the same entry. The controller keeps a `'series'` layer per used entry, placed with `chart.setPrimitiveStackAbove`, and the front layer answers hits for every layer of the pane, front to back (body hits from a lower layer carry `paintedBy`). While the entry plots no series on the drawing's pane it paints in front by `zIndex`; `stackAbove` is kept, saved, migrated (a non-string is dropped) and carried by duplicate and the clipboard. `DrawingPatch.stackAbove` sets it or, with `null`, clears it. A host without `seriesStack` / `setPrimitiveStackAbove` (both optional on `DrawingChartHost`) paints every drawing by `zIndex`.
- **`props`** is a JSON-safe bag for a tool's extras (a table's cells, a callout's tail side), persisted verbatim.
- **`intervals`** (`DrawingIntervalRange`, `{ from?, to? }`) is the range of chart intervals the drawing is shown on; absent means every interval. See the Visibility per interval section below.
- **`DRAWING_STATE_VERSION`** (`3`) is the newest document version this build reads and writes. A document is written as the lowest version that holds it: `3` when a drawing carries an interval range, else `2`, so a save without one is byte for byte what 2.5.8 wrote.

### Settings schema

Every tool declares which of its fields a host may show, as dot paths with a control kind, and **only fields its `draw` reads**: a control with nothing behind it is a bug, not a style choice.

```ts
import { drawingSettingsSchema, readDrawingSettings, applyDrawingSettings } from 'openalgo-charts/draw';

const schema = drawingSettingsSchema(d.tool);          // { fields, textIsContent? }
const values = readDrawingSettings(d, schema);         // { 'style.color': '#..', 'text.value': 'Hi', ... }
draw.update(d.id, applyDrawingSettings(d, formState, schema));
```

`SettingsField` is `{ path, label, kind, min?, max?, step?, options?, group? }`; `FieldKind` is `'color' | 'number' | 'select' | 'lineStyle' | 'boolean' | 'text' | 'opacity' | 'levels' | 'interval'` and `FieldGroup` is `'line' | 'fill' | 'text' | 'levels' | 'behavior' | 'visibility'`. A path is two segments under `style`, `text`, `props` or `intervals`, or one of `locked`, `visible`, `zIndex`, `space`. `textIsContent` is true for `text`, `callout`, `note`, `balloon`, `comment`, `signpost`, `price-note` and `table`: ask for the text the moment the tool is placed. `readDrawingSetting(d, path)` reads one value (`levels` comes back as a copy). `coerceSettingValue(field, raw)` turns a form string into what the kind stores. `applyDrawingSettings` returns whole `style` / `text` bags; with a schema it coerces and drops undeclared paths, and a value of `undefined` deletes the key (the host's "reset to default"). A custom tool builds its own with `composeSettings([LINE_FIELDS, FILL_FIELDS], { textIsContent })`, from the shared lists `LINE_FIELDS`, `FILL_FIELDS`, `EXTEND_FIELDS`, `LEVEL_FIELDS`, `TEXT_FIELDS`, `FONT_FIELDS`, `SHAPE_TEXT_FIELDS`, `PLATE_TEXT_FIELDS`, the single fields `COLOR_FIELD`, `LINE_WIDTH_FIELD`, `LINE_STYLE_FIELD`, `SHOW_LABELS_FIELD`, `TEXT_VALUE_FIELD`, the interval pair `INTERVAL_FIELDS` (no tool declares it; a host that lists intervals adds it, see the Visibility per interval section below), and the option lists `LINE_STYLE_OPTIONS`, `ALIGN_OPTIONS`, `VALIGN_OPTIONS`, `TEXT_POSITION_OPTIONS`, `FONT_OPTIONS`. `drawingSettingsSchema` is a registry lookup (a tool without a declaration gets the line fields), which is why it lives in registry.ts rather than with the pure schema helpers.

## DrawingController API

For numeric alerts, `draw.alertInfo(id)` returns an `AlertDrawingInfo` with
availability, reason, paneIndex and named `AlertDrawingLevel` choices.
`draw.valueAt(id, time, level?)` returns `AlertDrawingValue` (price, optional
upperPrice, paneIndex), or undefined when the geometry has no value there.
These structural types come from the base entry and are consumed by its
AlertController. See [alerts](alerts.md) for timing and source choices.

Supported tools currently include trend-line, ray, extended-line, horizontal-line,
horizontal-ray, trend-angle, parallel-channel, disjoint-channel, flat-top-bottom,
fib-retracement, fib-extension, fib-extension-two-point and fib-channel. Channel
choices are band, base, boundary and middle; fib choices are stable ratio ids
such as ratio:0.5 from active levels. A tool without a numeric hook reports an
unavailable reason. The API uses the renderer's geometry, including its existing
extension semantics, rather than inventing a price-time interpolation.

Custom DrawingTool descriptors can opt in with `alertValue(context, level?)`
and `alertLevels(drawing)`. `DrawingValueContext` contains the drawing, anchors
as media-pixel pts, query time and x, and fromY for that pane. The value hook
returns price and optional upperPrice; the controller adds paneIndex and rejects
non-finite output. The level hook returns readonly id/title choices. No DOM or
delivery logic belongs in these hooks.

```ts
new DrawingController(chart, {
  magnet: 'off',            // 'weak' | 'strong' | 'off'; true = 'strong'. Snap anchors to the bar's O/H/L/C, or a study pane's plotted values
  stayInDrawingMode: false, // stay armed after a shape completes
  historyLimit: 50,         // undo depth
  defaultStyle: {},         // merged UNDER each tool's own defaults
  clipboard: undefined,     // ClipboardPort; defaults to navigator.clipboard, null disables it
  clipboardFallbackToMemory: true, // a refused write still lands in the in-process clipboard; false makes cut safe
  pasteOffsetBars: 2,       // how far a paste is nudged along time
  pasteOffsetPixels: 16,    // how far a paste is nudged down the price axis
  inputAnchors: true,       // draw the anchor of every paired study input that declares one (read once, at construction)
  gestures: {},             // DrawingGestureOptions: turn a modifier gesture off, e.g. { snapModifier: false }
});
```

**Study input anchors.** A study `price` input paired with a `timestamp`
(`timeKey`) and declared with `anchor: true` gets a handle at its point, drawn by
the controller on the pane and scale `studyInputTarget(chart, study, key)` names
(the same target a pick of that price uses; `StudyInputTarget` is
`{ paneIndex, priceScaleId }`). A drag writes both settings in one patch and is one
step of this controller's undo history, in order with the drawings; `undo()` and
`redo()` walk it, and a step whose study has gone is passed over. A point written
through the study's settings instead (a settings dialog's Pick point, a price typed
in) is one step of this history as well, so an undo takes it back first and never
passes over it to a drawing made before it; a write inside `untracked`, or forced on
a study the user may not configure, is the host's own and no step. The
step emits `drawing:change` with `ids: []` (and again on undo and redo), so a
control showing whether Undo is available refreshes. An active drawing tool or a pick takes
the press instead, and choosing a tool, starting a pick or a `data:context` change drops a
drag in hand. `draw.moveInputAnchor(studyId, key, { time, price })` moves an anchor the way
a drag release does (snapped, bounded, refused for a study that is not `configurable`) as
one step, for a host control that sets the point another way such as its own point pick;
false for no such anchor, a refusal, or the point already held. A host keeping one timeline
of its own takes these steps with `draw.delegateInputAnchorSteps(record)` (2.5.6):
`record` gets each move's `InputAnchorStep` (`{ undo(): boolean; redo(): boolean }`, each
false once the settings have moved on) as the move ends, this history records nothing and
emits no `drawing:change` for it, and the returned function gives the steps back; the
widget tier's `ChartHistory` does this. A point written through the settings is not
handed over, since that timeline sees the write itself. A move inside `untracked` is a
step nowhere. See
[indicators](indicators.md#paired-time-and-price-inputs).

| Member | Behaviour |
|---|---|
| `setTool(id \| null, options?)` | Arms a tool; throws on an unregistered id. Also calls `chart.setPlacementMode(true/false)`. `options` is a `DrawingPlacementOptions`: `{ space: 'viewport' }` places the next drawing pinned to the screen, and throws for a tool without `viewport` support. Emits `draw:tool` as `{ tool }`, or `{ tool, space: 'viewport' }` when armed for the viewport. |
| `activeTool()` / `activeToolSpace()` | Armed id, or `null`; the space it places in (`'data'` unless armed for the viewport). |
| `screenPoints(id)` | A drawing's anchors in container media px (the space `timeToCoordinate` and `priceToCoordinate` answer in), for either space. What a host places an overlay by. `null` for an unknown id or a pane with no place on screen (collapsed, or hidden by a maximize). |
| `setOptions(patch)` | Live-patch the options above, all but `inputAnchors`, which is read once when the controller is built. |
| `drawings()` / `get(id)` | Read the model. `drawings()` is the live array, in **paint order** (creation order until a reorder; `createdAt` keeps the creation time). |
| `add(drawing)` | `add({ tool, points, style, paneIndex, text?, props?, id?, locked?, visible?, zIndex?, policy? })` (a `DrawingInput`) returns the created `Drawing`, with `zIndex` 0, `createdAt` and a minted id (a supplied id that collides with a restored one is replaced). The tool's `defaultText` merges under `text` the way `defaultStyle` merges under `style`. Adding a drawing whose `policy` sets any flag to false records no undo step: it is the host's. The `policy` object is copied. |
| `update(id, patch, options?)` / `updateMany(patches, options?)` | Patch `points` \| `style` \| `text` \| `props` \| `locked` \| `visible` \| `zIndex` \| `policy` \| `space` \| `viewportPoints` (a `DrawingPatch`). `space` alone converts the anchors at the view on screen (see Viewport-anchored drawings). `style`, `text`, `props` and `policy` merge; `points` replaces. `updateMany([{ id, patch }])` is one undo step and one `drawing:change`. A read-only drawing is refused (`update` returns false, `updateMany` skips it) unless `options` is `{ force: true }` (`DrawingEditOptions`). `update` also returns false when the patch asks for a `space` the drawing could not be moved to; the rest of that patch still applies. A patch that carries `policy`, and any forced call, records no undo step, and every recorded step takes it as well, so no later undo or redo reverses it. |
| `remove(id, options?)` / `removeMany(ids, options?)` / `clear(options?)` | Delete one / several (one undo step) / all. Read-only drawings stay unless `{ force: true }`. A forced delete records no undo step and takes the drawing out of every recorded step, so no redo brings it back. |
| `finish()` | Commit a `points: 0` tool at the anchors placed so far. Returns whether it committed. |
| `cancel()` | Drop the anchors placed so far; disarms the tool unless `stayInDrawingMode` keeps it (a second call then disarms). Also ends a drag in hand or a temporary measure first. Returns whether anything changed. |
| `measuring()` | Whether a temporary measure (Shift+click on empty space) is on the chart; `draw:measure` (`{ active }`) fires as one starts and goes. (since 2.5.9) |
| `setEraser(active)` / `erasing()` | Eraser mode: a click on a drawing deletes it, a drag deletes what it crosses, one undo step each; read-only, locked, unselectable and hidden drawings stay. Turning it on disarms any tool; `setTool`, `cancel()` and `setEraser(false)` turn it off. `draw:eraser` (`{ active }`) fires on each change. (since 2.5.9) |
| `popAnchor()` | Remove the last anchor of a `points: 0` tool still being placed (the Backspace of placement). Fixed-anchor and freehand tools have nothing to pop. |
| `hovered()` | Id of the unselected drawing under the pointer, or `null`. Fed by the chart's `hover` event; `drawing:hover { id }` fires when it changes. |
| `magnetMode()` | The resolved `MagnetMode` (`'off' | 'weak' | 'strong'`), after the boolean shorthand is mapped. |
| `select(id \| ids \| null, additive = false)` / `selected()` / `selection()` | Selection. `additive` toggles each id (shift, ctrl or meta click does this for you); unknown ids and drawings with `policy.selectable: false` are ignored. `selected()` is the primary (first picked) id; `selection()` is the list in pick order. Events fire only when the selection actually changes. |
| `duplicate(ids)` | Clones with the paste offset (`pasteOffsetBars` / `pasteOffsetPixels`), selects the clones, one undo step. Returns the clones. A clone carries no `policy`. |
| `nudge(ids, dx, dy)` | Moves by a screen distance in media px (right and down positive); locked and read-only members stay. One undo step. Needs `timeToCoordinate` / `coordinateToTime` on the host for the horizontal half, else assumes the default 8 px bar spacing. |
| `setZIndex(id, z)` / `bringToFront(id)` / `sendToBack(id)` | Paint order. The two shortcuts are **slot-local**: they set `zIndex` to the max / min of the same pane's slot (its side of the series, or the entry it is placed above) and move the drawing to the end / start of the list, never crossing the series. |
| `reorder(id, direction)` | One step within the same slot, one undo step. |
| `placeInStack(id, target, where)` | Move directly `'above'` or `'below'` another drawing (`{ drawing: id }`) or a series-band entry (`{ entry }`, a `DrawingStackTarget`) of its pane; one undo step, renumbering the landing slot (below the series up to -1, elsewhere from 0). Next to a drawing it joins that drawing's slot; above an entry it goes on that entry; below an entry on top of the slot under it (behind the series for the first entry). `false` for another pane, an unknown target, or a no-op. Outside the drawing policy, like every stacking call. |
| `sendBehindSeries(id)` / `bringAboveSeries(id)` | Set `zIndex` to -1 / 0 and leave the series band. No-ops (no history) when already on that side. |
| `undo()` / `redo()` / `canUndo()` / `canRedo()` | History. A step left with nothing to do, once a drawing in it is made read-only or the host's own act has overtaken it, is dropped, so `canUndo()` and `canRedo()` report only a press that changes something. |
| `historySteps()` | `{ undo: number[], redo: number[] }`, oldest first: the steps each branch holds, by the number `drawing:change` reported them under. A step in neither branch was taken away (a reset, a trim, a host's forced edit). For a host keeping one timeline across drawings and its own edits, such as the widget tier's `ChartHistory`. A step still being recorded (a drag in progress) is not listed. Step numbers are unique across controllers on the page. (2.5.6) |
| `untracked(fn)` | Runs `fn` as the host's own act and returns what it returns: an edit inside records no undo step and leaves both branches (redo included) as they are, and every recorded step takes it in, as a forced edit does, so no later undo or redo reverses it. Unlike `force` it reaches no read-only drawing; `undo`/`redo` inside it still move along the branches. `ChartHistory.ignore` and every history press run through it. (2.5.6) |
| `delegateInputAnchorSteps(record)` | Hands the step each study input anchor move makes (a drag, `moveInputAnchor`) to `record` instead of this history, until the returned function gives them back; a later call takes them from an earlier one. `record` receives an `InputAnchorStep` (`{ undo(): boolean; redo(): boolean }`) once the patch is written. For a timeline that already records the settings patch the move writes, such as `ChartHistory`, which would otherwise see one move as two steps. A point written through the study's settings, which this history otherwise holds as a step, is not handed over: the timeline sees that write itself. (2.5.6) |
| `copy(target?)` / `cut(target?)` / `paste()` | **Async.** See the clipboard section. |
| `clipboard()` | The `DrawingClipboard` behind them, for reporting failures. |
| `toJSON()` / `fromJSON(data)` | `{ version, drawings, groups? }` (a `DrawingsDocument`, `version` 3 when a drawing carries an interval range, else 2) out, deep-copied, without transient drawings (`policy.persistent: false`); replace-all in (and clears history + selection, transient drawings included). `fromJSON` accepts a 1.9.x bare `Drawing[]` too and upgrades it. |
| `migrateDrawings(input)` | The upgrade `fromJSON` runs, exported for a host reading a saved layout on its own: any 1.9.x array or v2 or v3 document in, a current `DrawingsDocument` out (a v2 document comes back unchanged, version and all), never throws. |
| `interval()` / `shownOnInterval(id)` / `hiddenOnInterval()` | The chart interval drawings are shown for (the data context's `interval`, or `null`), whether a drawing's `intervals` range admits it, and the ids of every drawing it hides, in model order. See the Visibility per interval section below. |
| `destroy()` | Unhooks listeners, removes every pane layer, releases placement mode. |

Events on the chart bus: `draw:tool`, `draw:add`, `draw:update`, `draw:remove`, `draw:select` (the primary id), `draw:copy`, `draw:cut`, `draw:paste`, plus the 2.0 pair `drawing:select` (`{ ids }`, the whole selection) and `drawing:change` (`{ ids, kind: 'add' | 'update' | 'remove' | 'reorder' }`, one per mutation, after the per-drawing `draw:*` events; `ids` is empty for a history step that changed no drawing, a study anchor's drag and its undo or redo), and `drawing:hover` (`{ id: string | null }`, when the unselected drawing under the pointer changes). `DrawingChangeKind` names the `kind` union. `DrawingChangeEvent` names the whole payload: `linked: true` on a linked chart's commit, and `step` (2.5.6) on the change that closes a recorded undo step, the number `historySteps()` lists it under; a forced edit, a linked commit, a restore and an `undo`/`redo` carry none.
The modifier gestures (since 2.5.9) add `draw:measure` (`{ active }`), as a temporary measure starts and goes, and `draw:eraser` (`{ active }`), as eraser mode turns on and off; see Modifier gestures.
Since 2.6.0 importing the tier adds every one of these names to `ChartEventMap`, so `chart.on('draw:add', (e) => e.drawing)` is typed; the payload types `DrawingEvent`, `DrawingListEvent`, `DrawingIdsEvent`, `DrawingIdEvent`, `DrawingToolEvent` and `DrawingModeEvent` are exported beside `DrawingChangeEvent`. The two families are two granularities and both stay: `draw:*` per drawing (carrying it) and per tool, `drawing:*` per mutation and per selection change. See [events-and-state](events-and-state.md).

**The controller listens on `chart.on(...)`, not `subscribeClick` / `subscribeDrag`.** A drag subscription is what makes an `ns-resize` order line draggable, and drawings do not need one; the host keeps either surface for its own order lines.

### Placement lifecycle

Since 2.1.5, when `crosshair:move.time` is null but the pointer is still over the
plot, the controller uses `DrawingChartHost.coordinateToTime(point.x)` for the
preview and freehand samples. The built-in Chart provides this mapping. Custom
hosts need the same mapping to support empty-space placement. Keep the crosshair's
bar time and OHLC null outside loaded data; do not invent bars or snap a future
endpoint to the last candle. Pointer leave still clears the preview. Drawing-state
formats are unchanged. Which time an x in the empty space stands for is the data
layer's answer: see [times past the last bar](data-and-time.md#times-past-the-last-bar).


1. `setTool(id)` arms the tool and puts the chart in placement mode, so a press places an anchor instead of panning.
2. Each `click` appends an anchor. Between anchors, a translucent preview (alpha 0.7) follows the live cursor.
3. When `pending.length >= tool.points`, `expand()` runs (if the tool has one) and the drawing is committed, selected, and (unless `stayInDrawingMode`) the tool disarms.
4. `points: 0` tools (`path`, `polyline`) never self-complete: double-click, or `finish()`. Fewer than 2 anchors discards the attempt.
5. `freehand` tools (`brush`, `highlighter`) ignore clicks and sample the cursor while the pointer is held; the release commits. A tap that never moved is discarded.
6. A press-drag-release also draws a two-anchor shape in one gesture: the chart emits the press point, then the release point tagged `viaDrag`.
7. **Shift locks the angle** on tools with `angleLock` (the line family): the free end is projected onto the nearest 45 degree ray on screen, while placing and while dragging a handle. It projects rather than rotates, so a level line ends under the pointer's x. It needs the host's four pixel mappings and is inert without them.
8. **The magnet ring.** With `magnet` on, or Ctrl (Cmd) held, the layer paints a ring where the next click will land (the hovered bar's time and the nearest O/H/L/C, so a snapped anchor sits on the bar centre; on a study pane the nearest value a study plots there). `'weak'` pulls only when a value is within 8 px, and needs `priceToCoordinate` to judge that; `'strong'` always pulls. Shift's angle lock wins over the magnet and hides the ring. See [the magnet everywhere](#the-magnet-everywhere-since-259).
9. **Freehand strokes** read the coalesced `samples` a pressed `crosshair:move` carries, so a fast stroke inks every position the pointer passed through rather than one per frame; on release the trail is thinned (`rdpSimplify`, a pixel and a half) and painted as a spline (`catmullRom`). A pen stores `pressure` per sample (a mouse stores nothing), and `style.pressure` on the brush and highlighter lets it drive the width (`pressureWidth`).
10. **Escape, Enter and Backspace** while a tool is armed mean `cancel()`, `finish()` and `popAnchor()`; `keyToDrawingAction` says so when the host passes `placing: true`.

### Selection and dragging

Hit ids are `draw:<id>` for the body and `draw:<id>#<n>` for anchor `n`. A body drag on an unselected drawing selects it alone first; then the **whole selection** moves as one undo entry (locked members stay, other-pane members through `priceToCoordinate` / `coordinateToPrice`, and a member on a pane collapsed to its strip, where those return `null`, keeps its prices and moves in time only); dragging a handle moves that one anchor to the cursor (or where the magnet lands it). `draw:update` fires per moved drawing on `drag:end`, plus one `drawing:change`. The grab radius is 6 media px for a body, 7 for a handle; handles of the selected drawing win over its own body.

Freehand strokes expose only their first and last handle: one handle per sample would bury the ink.

The controller also tracks the unselected drawing under the pointer from the chart's `hover` event (`hovered()`, `drawing:hover`), and the layer paints its handles faintly so a drawing reads as grabbable before it is grabbed. A hover change between two drawing layers costs the overlay tier only. The layer sizes its grab targets by the last pointer device (`setPointerType`, fed from the payload's `pointerType`), so a touch gets a larger radius than a mouse. Dragging an under-series drawing lifts it to the top layer for the gesture and re-lists it on release, one Light repaint each; the drag itself is Cursor-only.

### Undo, lock, visibility

**A whole drag is one undo step.** The snapshot is pushed once per gesture, on the first `drag` event, not per frame. Any new edit clears the redo branch. Snapshots are `JSON.stringify` of the full list, capped at `historyLimit`.

`update(id, { locked: true })` keeps the drawing rendered but removes it from hit-testing entirely, it cannot be selected or dragged, and it draws no handles. `update(id, { visible: false })` removes it from both rendering and hit-testing.

### Drawing policies

`locked` is the user's own switch, and it couples two things: no selection on the
chart and no dragging. A host that places drawings of its own (a signal level, a
session marker, a replay annotation) needs restrictions the user cannot lift, and
needs them separately. `drawing.policy` is a `DrawingPolicy`: four independent
flags, each defaulting to `true`, so a drawing without one behaves exactly as
before. `locked` is unchanged.

```ts
const mark = draw.add({
  tool: 'horizontal-line', paneIndex: chart.primaryPaneIndex(), style: { lineStyle: 'dashed' },
  points: [{ time, price }],
  policy: { editable: false, persistent: false, listed: false },
});
draw.update(mark.id, { points: [{ time, price: next }] }, { force: true });   // the host moves it
draw.remove(mark.id, { force: true });                                       // and retires it
```

| Flag | `false` means | Binds |
|---|---|---|
| `selectable` | Never joins the selection. A click passes through to what lies under it; no hover, handles, drag or context-menu target. | Every caller: `select()` ignores it, so a host UI (an objects list, select-all) cannot select it either. |
| `editable` | Read-only. It still selects (a click selects it; a press-drag on it pans the chart), copies and duplicates. Nothing moves, reshapes, restyles, retexts, hides, locks, cuts, deletes or regroups it: drag and handles, `nudge`, `cut`, `update`, `updateMany`, `remove`, `removeMany`, `clear`, a group's hide, lock or remove. `createGroup` leaves it in the group it is in, and `renameGroup` and `removeGroup` refuse a group that holds it. Undo and redo never change its content or its group: they leave it where it is, keep the group that holds it and that group's name, and still move the user's own drawings in and out. A selected read-only drawing shows its anchors at the faint hover weight. | User operations. The controller cannot tell a click from a call, so every mutating method treats a call as the user's unless it passes `{ force: true }` (`DrawingEditOptions`). The host's own calls (adding a restricted drawing, a patch that carries `policy`, any forced call) record no undo step and leave the redo branch alone, and every recorded step takes them too: an undo or redo of the user's own steps never reverses a forced move, delete, regroup or rename. `fromJSON` (a restore) and linked-chart commits are not user edits and always apply. |
| `persistent` | Transient. Left out of `toJSON()`, and so out of `chart.getState().drawings`, every saved layout and workspace document, and the saved membership of its group. It renders, selects and undoes as usual in the session. | Every caller: the serializer. A restore (`fromJSON`, `chart.restoreState`) replaces it with what was saved, and a rebuild that round-trips the document drops it, so re-add it after one. |
| `listed` | Left out of the object inventory (`ChartObjects`), its group's row and every group-wide action there (a group row's remove deletes only its listed members, and `ChartObjects.ungroup` refuses the group), and so out of every objects panel and the widget's alert source picker. `drawings()` still returns it. | Every caller of the inventory. |

The inventory also honours the other two: a read-only drawing's row offers no
visibility, lock or remove (a group holding one offers none group-wide), and an
unselectable drawing's row offers no select. The widget draws every edit control
for a read-only selection disabled with the note "read-only" (context menu rows,
the properties dialog's fields and actions, the rail's lock, eye and trash, the
mobile selection bar) and declines to open the text or level editor; "Remove all
drawings" counts only what it removes.

A copy is the user's own drawing: `paste()` and `duplicate()` never carry a
policy, and the clipboard payload does not include one. A policy is data: it
survives `toJSON` for persistent drawings and `migrateDrawings`, which keeps only
the four boolean flags. It is never history: a change to it records no step, and
every recorded step takes the drawing's policy as it is now, so no undo or redo
brings an older one back. A host importing documents it does not trust
can strip `policy` before `fromJSON`. Stacking order (`bringToFront`,
`sendToBack`, either side of the series, `reorder`) is outside the policy.

Cost of the host's acts: taking one into the recorded steps is one pass over
the undo and redo history, parsing and rewriting both snapshots of every step,
so it grows with the number of recorded steps (see `historyLimit`) times the
drawing count. A forced delete, a forced grouping call, a forced patch to a
drawing the user may edit or one that carries `zIndex`, any patch that carries
`policy` and a linked chart's change of policy make that pass. A forced patch
to a read-only drawing that carries neither `policy` nor `zIndex` makes none,
so trailing a level on every tick is cheap: history cannot reach that drawing
while it stays read-only, and the patch goes in with the next pass, which a
change of its policy always makes. Move a trailing level with `points` (and
`style`) alone; putting `zIndex` or `policy` in the same patch pays for the
pass on every tick.

## Clipboard: copy, cut, paste

```ts
// The host owns the key bindings; the engine installs no listeners.
window.addEventListener('keydown', async (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  if (e.key === 'c') await draw.copy();
  if (e.key === 'x') await draw.cut();
  if (e.key === 'v') await draw.paste();
});
```

**All three are `async`**, because `navigator.clipboard` is: it returns promises and can reject on a permission the user has not granted. Awaiting them is not optional for `cut`, whose result is the difference between "deleted" and "left alone".

| Member | Signature | Notes |
|---|---|---|
| `copy` | `(target?: string \| string[] \| null) => Promise<boolean>` | Defaults to the selection. `false` means nothing to copy, or the payload could not be stored anywhere. |
| `cut` | `(target?: string \| string[] \| null) => Promise<boolean>` | Deletes **only** after the write resolves successfully. One undo step. |
| `paste` | `() => Promise<Drawing[]>` | Empty array when the clipboard holds nothing of ours. Never throws on foreign content. |

### The payload, and why foreign text is safe

The clipboard is shared with everything else on the machine, so a paste can arrive from a spreadsheet, another charting product, or a hand-edited copy of our own JSON. Two defences:

1. **One namespaced top-level key**, `openalgo-charts/drawings`, carrying a `version`. Anything else is recognised as not ours by looking at one property, and pastes nothing. A Ctrl+V handler must not throw at the user because the last thing they copied was a spreadsheet cell.
2. **Field-by-field validation**, all-or-nothing. The tool must be registered (`hasDrawingTool`), every anchor must be finite, `paneIndex` must be a non-negative integer, style values must be renderable primitives or a short array of numbers, and there are caps on counts and string length. One corrupt entry rejects the whole payload, because pasting the other nine silently is worse than pasting none.

`encodeClipboardPayload`, `decodeClipboardPayload` and `sanitizeDrawing` are exported from `openalgo-charts/draw` if you want to move drawings through your own transport (a websocket, a saved template). `decodeClipboardPayload` validates exactly as a paste does. `sanitizeDrawing` is the per-entry gate alone, without the migration a paste runs after it: it keeps a style key this build does not declare, where a paste drops it.

### Degrading instead of breaking

Every write also lands in a **module-level in-memory clipboard shared by every controller in the page**. That is what makes chart-to-chart paste work with the OS clipboard permission refused, and it is why the store is a singleton rather than per-controller state.

```ts
const ok = await draw.cut();
if (!ok) toast('Nothing was cut');
const why = draw.clipboard().lastError();   // set when memory worked but the OS clipboard did not
if (why !== null) toast('Copied in this tab only');
```

Turn the backstop off with `clipboardFallbackToMemory: false` on the controller (at construction or through `setOptions`), or `new DrawingClipboard({ fallbackToMemory: false })` for a clipboard of your own, when a cut that cannot reach the OS clipboard must not delete the drawing. Pass `clipboard: null` to `DrawingController` to disable the system port entirely (tests, non-browser runtimes), or `clipboard: myPort` to inject one; `setOptions({ clipboard })` swaps the port at runtime, which is how you hand one over after the user grants permission.

### What a paste actually inserts

Fresh objects with **fresh ids**, never a second reference to the drawing that was copied, so editing the paste cannot alter its source or the clipboard. One undo step for the whole paste, and the last one is selected.

The copy is nudged so it is visibly a second shape: `pasteOffsetBars` (2) along time, and `pasteOffsetPixels` (16) down the price axis. The vertical nudge is applied **per anchor** through `priceToCoordinate` / `coordinateToPrice`, not as one price delta, so it is a rigid *screen* translation and a shape keeps its proportions on a logarithmic scale.

The clipboard counts panes **price pane first**: the price pane is `0` and the study panes follow in their order, whatever slot the price pane held on the source chart. `copy` and `paste` convert, so a drawing copied beside the candles pastes beside the candles on a chart that keeps its price pane below its studies (`movablePrimaryPane`), and a study-pane drawing lands on the study pane in the same position. On a chart with the price pane on top, which is every chart without the option, that is the chart's own slot, as it always was.

A `paneIndex` the receiving chart does not have is folded onto one it does, counted the same way, so a drawing from a taller stack lands on the last study pane rather than on the price pane. Without that, `addPrimitive` would conjure an empty pane on the target chart.

## Persistence

Every mutation writes `chart.setDrawingState(this.toJSON())`, so drawings ride along in `chart.getState().drawings` with no extra plumbing.

```ts
localStorage.setItem('layout', JSON.stringify(chart.getState()));   // includes drawings

chart.restoreState(JSON.parse(localStorage.getItem('layout')!));
const draw = new DrawingController(chart);   // reads the state in its constructor
```

The constructor reads `chart.drawingState()`, and an attached controller handles
`drawings:restore` during later `chart.restoreState` calls. Both attachment orders
restore the drawing list. Do not call `fromJSON` again after chart restoration;
the drawing phase already precedes alert restoration.

The controller and its layers belong to the chart they were built on, so a rebuild (interval, chart type, or theme swap) needs `const saved = draw.toJSON(); draw.destroy();` before `chart.destroy()`, then `new DrawingController(newChart).fromJSON(saved)`. Anchors are data, so the shapes land on the same bars even at a different interval.

The chart state holds one drawing document, the one on screen. A host that
loads several symbols into one chart keeps a document per symbol with
`InstrumentDrawings` (Drawings per instrument, below): without it the drawings stay on
screen whatever symbol is loaded.

## Keyboard

```ts
import { matchDrawingShortcut, drawingShortcuts } from 'openalgo-charts/draw';

drawingShortcuts();      // { 'trend-line': 'Alt+T', 'horizontal-line': 'Alt+H', ... }
matchDrawingShortcut(e); // tool id, or null
```

**The library installs no key listener.** Only the host knows whether the chart has focus, a dialog is open, or the user is typing in a field. `matchDrawingShortcut` is pure and takes any `{ key, code?, altKey?, ctrlKey?, metaKey?, shiftKey? }`. Pass the event itself, with its `code`: under Alt, when `e.key` is not a letter, the letter is read from `code`, since macOS Option turns `e.key` into a symbol (Option+T is a dagger). A letter in `e.key` still wins, so a non-QWERTY layout keeps its own letters. Since 2.5.10.

Editing chords are the same shape: `keyToDrawingAction(e, { hasSelection, hasTarget, editingText, placing? })` returns a `DrawingKeyAction` (`{ type: 'undo' | 'redo' | 'copy' | 'cut' | 'paste' | 'duplicate' | 'delete' | 'cancel' | 'finish' | 'popAnchor' }` or `{ type: 'nudge', dx, dy }`) or `null`. With `placing: true` (pass `draw.activeTool() !== null`), a bare Escape, Enter or Backspace maps to `cancel`, `finish` or `popAnchor` before anything else is considered, so Backspace never deletes the selection while an anchor is being placed; `hasTarget` is `draw.hovered() !== null`. Ctrl/Cmd+Z undoes, Ctrl+Shift+Z or Ctrl+Y redoes, Ctrl+C / X / D need a selection or a hovered target, Ctrl+V always pastes, Delete / Backspace need a selection or target, and the arrows nudge the selection by `NUDGE_STEP_PX` (1) or `NUDGE_STEP_SHIFT_PX` (10) with Shift. `editingText`, any Alt, or an extra Shift on a chord returns `null`. `DrawingKeyEvent` and `DrawingKeyContext` type the two arguments. The host maps each action to the matching controller call: `duplicate(selection())`, `removeMany(selection())`, `nudge(selection(), dx, dy)`.

Matching rules, all verified in `tests/draw-tier.test.ts`:

- Key comparison is case-insensitive (`'t'` and `'T'` both match `Alt+T`).
- **Modifiers must match exactly.** `Alt+T` does *not* fire for `Ctrl+Alt+T` or `Shift+Alt+T`, so a tool can never shadow a browser or host chord.
- `metaKey` counts as Ctrl, so a Mac Cmd chord does not arm an Alt-only tool.
- A bare letter never matches, without Alt or Ctrl the function returns `null` immediately, so ordinary typing is safe.

## Registering a custom tool

A tool is a descriptor. `draw` receives anchors in **device** px (already multiplied by `rc.dpr`); `distance` receives them in **media** px, the same space as the cursor. The hit-test field is named `distance`, not `hitTest`.

```ts
import { registerDrawingTool, distToSegment } from 'openalgo-charts/draw';

registerDrawingTool({
  id: 'vwap-band',
  name: 'VWAP Band',
  points: 2,
  shortcut: 'Alt+B',
  defaultStyle: { color: '#f5a623', lineWidth: 2, fillOpacity: 0.15 },
  draw: ({ ctx, rc, pts, style }) => {
    const band = 8 * rc.dpr;                       // pts are already device px
    ctx.globalAlpha = style.fillOpacity ?? 0.15;
    ctx.fillStyle = style.color;
    ctx.fillRect(pts[0].x, pts[0].y - band, pts[1].x - pts[0].x, band * 2);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = style.color;
    ctx.lineWidth = Math.max(1, style.lineWidth * rc.dpr);
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    ctx.lineTo(pts[1].x, pts[1].y);
    ctx.stroke();
  },
  // media px to the shape; 0 means "inside"; null means a miss.
  distance: (x, y, { pts }) => {
    const d = distToSegment(x, y, pts[0], pts[1]);
    return d <= 8 ? 0 : d;
  },
});
```

Exported geometry helpers: `distToSegment`, `distToLine`, `distToPolyline`, `distToRect`, `distToEllipse`, `rectOf`, `boundsOf`, `extendSegment`. Freehand geometry, pure and DOM-free, for a custom tool or a host that captures its own trail: `rdpSimplify(points, epsilonPx)` thins a `ScreenPoint[]` to the corners its shape needs; `catmullRom(ctx, points, tension = 0.5)` traces a smooth spline through them (it neither begins nor strokes the path, so the caller sets the style); `pressureWidth(baseWidth, pressure, range = 0.6)` swells or thins a width by a 0..1 pressure around the 0.5 mouse stand-in. The built-in brush and highlighter use all three.

Three optional descriptor fields change *placement*, not rendering:

| Field | Effect |
|---|---|
| `freehand: true` | Sample the cursor while held, commit on release. Requires `points: 0`. Only the end anchors get handles. |
| `angleLock: true` | Shift snaps the free end of a two-anchor tool to 45 degree steps on screen, while placing and while dragging a handle. The line family sets it; a rectangle's opposite corner is not a line end, so shapes leave it off. |
| `expand(clicked, { barSeconds, visibleBars, toPixel?, fromPixel? })` | Turn the clicked anchors into the full anchor set, so fewer clicks can drop a complete editable default. Every returned point stays a draggable handle. `toPixel` / `fromPixel` are present only when the host can map coordinates; a tool that sizes in pixels falls back to chart units without them. |
| `constrain(points, handle)` | The anchors to keep after one moved: `handle` is the dragged index, or `null` for a `points` patch. Pure. The position tools reflect the level that was NOT moved across the entry when both land on one side, so the one under the hand stays put. |

Size an `expand` default against `visibleBars`, not a fixed bar count, a fixed count is a hairline zoomed out and pane-filling zoomed in. The position tools size on screen instead, through `toPixel` / `fromPixel`: 64 px of risk and 150 px of width read the same on every instrument and at every zoom, where 1% of a 2.87 stock and 1% of an index are the same fraction and very different boxes.

**A non-finite `distance` must be a miss.** The layer treats `null`, `NaN`, and `Infinity` as misses; returning `NaN` from a degenerate shape would otherwise swallow every click on the pane.

## Host UI wiring

The pattern the OpenAlgo terminal uses (`D:\testing\openalgo\frontend\src\lib\trading\terminal.ts`, rail in `src/components/trading/DrawingRail.tsx`, tool catalogue in `src/lib/trading/drawTools.tsx`): the tier is dynamically imported on first use, the controller is the only stateful thing, and React only ever sees a derived stats object.

```ts
// Lazy-load the tier the first time a drawing control is touched.
const { DrawingController, drawingShortcuts, matchDrawingShortcut, drawingSettingsSchema } =
  await import('openalgo-charts/draw');

const draw = new DrawingController(chart, { magnet, stayInDrawingMode: false });
draw.fromJSON(savedDrawings);           // survive a chart rebuild
const chords = drawingShortcuts();      // id -> 'Alt+T', rendered next to tool names

// One handler for every mutation: persist, then re-derive toolbar state.
for (const ev of ['draw:tool', 'draw:add', 'draw:update', 'draw:remove', 'draw:select']) {
  chart.on(ev, () => {
    localStorage.setItem('draw', JSON.stringify(draw.toJSON()));
    setStats({
      tool: draw.activeTool(), count: draw.drawings().length,
      canUndo: draw.canUndo(), canRedo: draw.canRedo(),
      hasSelection: draw.selected() !== null, shortcuts: chords,
    });
  });
}

// A text tool is useless empty: open the host's dialog as soon as one lands.
chart.on('draw:add', (p) => {
  const d = (p as { drawing: { id: string; tool: string; text?: { value: string } } }).drawing;
  if (drawingSettingsSchema(d.tool).textIsContent) openTextDialog(d.id, d.text?.value ?? '');
});

// Keys: the host decides when the chart owns them.
window.addEventListener('keydown', (e) => {
  const t = e.target as HTMLElement | null;
  if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
  if (e.key === 'Escape') return draw.setTool(null);
  if (e.key === 'Delete') { const id = draw.selected(); if (id) draw.remove(id); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === 'z') { e.shiftKey ? draw.redo() : draw.undo(); return; }
  const id = matchDrawingShortcut(e);
  if (id !== null) { e.preventDefault(); draw.setTool(id); }
});

// A style bar patches the selection.
draw.update(draw.selected()!, { style: { color, lineWidth, lineStyle, fillOpacity } });
```

## Foot-guns

**Tool `defaultStyle` beats the controller's `defaultStyle`.** The merge order in `add()` is `{ ...controller.defaultStyle, ...tool.defaultStyle, ...drawing.style }`, so a controller-wide `{ fill: false }` will not turn off a rectangle's fill. Patch the drawing, or pass `style` on `add`.

**`drawings()` returns the live array, not a copy.** Mutating it desynchronises the pane layers and the chart state. Use `toJSON()` when you need a snapshot.

**`boundsOf(points)`** (with `rectOf` and the `distTo*` helpers) is the screen-space bounding box a custom tool's `distance` or a host's marquee wants; it is exported so nobody restates it.

**A drawing renders only once it has `max(1, tool.points)` anchors.** A partially-placed `points: 0` shape lives in the preview slot, not the model, so it is absent from `toJSON()` until committed.

**The magnet snaps to candles on the price pane only,** in whatever slot the host keeps it (`chart.primaryPaneIndex()`, read through the optional `DrawingChartHost.primaryPaneIndex`; a host without it means slot 0). A study pane snaps to its studies' plotted values instead, and only on a host with `indicators()`, `panes()` and `priceToCoordinate`; a study overlaid on the price pane is not a snap target there.

Related: [primitives-and-plugins](primitives-and-plugins.md) (the `IPrimitive` contract `DrawingLayer` implements), [events-and-state](events-and-state.md) (the bus and `getState`), [interactions](interactions.md) (placement mode, pan/zoom), [bundling-and-tiers](bundling-and-tiers.md) (lazy-loading the tier).

## Named tool exports

Individual tools are exported too, under the UPPER_SNAKE form of the id:
`NOTE`, `BALLOON`, `COMMENT`, `SIGNPOST`, `PRICE_NOTE`, `TABLE`, `CALLOUT`,
`FLAG_MARK`, `ARROW_UP`, `ARROW_DOWN`, `ARROW_LEFT`, `ARROW_RIGHT`.

As with the indicator tier, importing `openalgo-charts/draw` registers all 87 tools,
but each descriptor is also exported by name for selective registration:

```ts
import { registerDrawingTool } from 'openalgo-charts/draw';
import { TREND_LINE, FIB_RETRACEMENT, RECTANGLE } from 'openalgo-charts/draw';

for (const t of [TREND_LINE, FIB_RETRACEMENT, RECTANGLE]) registerDrawingTool(t);
```

| Export: id | Export: id | Export: id |
|---|---|---|
| `ARROW`: `arrow` | `CROSS_LINE`: `cross-line` | `ELLIPSE`: `ellipse` |
| `EXTENDED_LINE`: `extended-line` | `FIB_EXTENSION`: `fib-extension` | `FIB_RETRACEMENT`: `fib-retracement` |
| `HORIZONTAL_LINE`: `horizontal-line` | `HORIZONTAL_RAY`: `horizontal-ray` | `LONG_POSITION`: `long-position` |
| `MEASURE`: `measure` | `PARALLEL_CHANNEL`: `parallel-channel` | `PATH`: `path` |
| `RAY`: `ray` | `RECTANGLE`: `rectangle` | `SHORT_POSITION`: `short-position` |
| `TEXT`: `text` | `TREND_LINE`: `trend-line` | `VERTICAL_LINE`: `vertical-line` |

The 2.0 entry also names the measurement, shape, freehand, fib and cycle families:
`FORECAST`, `PRICE_RANGE`, `DATE_RANGE`, `CIRCLE`, `TRIANGLE`, `POLYLINE`, `ARC`,
`CURVE`, `ROTATED_RECTANGLE`, `DOUBLE_CURVE`, `HIGHLIGHTER`, `BRUSH`, `FIB_CHANNEL`,
`FIB_TIME_ZONE`, `FIB_FAN`, `GANN_FAN`, `GANN_BOX`, `CYCLIC_LINES`, `TIME_CYCLES`,
`SINE_LINE`. The remaining tools are registered by `registerBuiltinDrawingTools()` and reachable
through `getDrawingTool(id)` / `hasDrawingTool(id)` / `registeredDrawingTools()`.

Clipboard persistence uses `DRAWING_CLIPBOARD_KEY` (`'openalgo-charts/drawings'`)
and `DRAWING_CLIPBOARD_VERSION` (`3`, tracking `DRAWING_STATE_VERSION`: the newest payload version
read. A payload is written as the lowest version that holds it, 3 only when a drawing carries an
interval range, and a version 1 body is accepted and upgraded); `systemClipboard` and
`clearMemoryClipboard` are the two backing stores. `cloneDrawing` is the deep copy a
copy or a `duplicate` makes. `DRAW_TIER` is the tier constant.

## Types for a custom tool

| Type | Where it shows up |
|---|---|
| `DrawingChartHost` | What `new DrawingController(chart)` accepts. Wire the controller to something other than a `Chart` by satisfying this |
| `ExpandContext` | The argument to `DrawingTool.expand`, so a custom tool can type its own implementation |
| `DrawingInput` / `DrawingPatch` / `DrawingsDocument` | What `add` accepts, what `update` accepts, what `toJSON` returns |
| `DrawingText` / `FibLevel` | The text block and one level of a ladder (see the 2.0 model above) |
| `MagnetMode` | `'off' | 'weak' | 'strong'`, what `magnet` resolves to and `magnetMode()` returns |
| `DrawingGestureOptions` | `DrawingControllerOptions.gestures`: the modifier gestures a host turns off (see Modifier gestures) |
| `DrawingPointerKind` | `'mouse' | 'touch' | 'pen'`, what `DrawingLayer.setPointerType` takes; a touch gets larger grab targets |
| `DrawingPoint.pressure` | Optional 0..1 pen pressure on a freehand sample; kept by the clipboard and the migration |
| `IconAttrs` / `IconSvgOptions` / `ToolCursorOptions` | The icon attribute bag, and the option bags of `iconSvg` and `toolCursor` |

## Plot clipping and moved axes (2.1.6)

Drawing bodies, previews, selection handles and snap rings are clipped to their
pane's plot. Anchors remain valid beyond the newest candle; clipping does not
truncate saved drawing coordinates. Moving the primary price scale to the left
keeps drawing placement, rendering and hit testing on the same price scale.
`PrimitiveRenderContext.readoutPriceScale` exposes that primary scale for custom
primitives; `priceScale` retains the existing right-scale contract.


## Advanced descriptor families (2.2.0)

`ADVANCED_LINE_TOOLS`, `ADVANCED_GEOMETRY_TOOLS` and `PATTERN_DRAWING_TOOLS` are
readonly arrays of `DrawingTool` descriptors exported by `openalgo-charts/draw`.
They also appear in `BUILTIN_DRAWING_TOOLS`; importing the tier registers every
family. Hosts should enumerate `registeredDrawingTools()` and inspect
`drawingSettingsSchema(id)` rather than maintain a second catalogue.

Use `draw.setTool('gartley')` to collect its anchors or `draw.add(...)` to supply
existing `{ time, price }` points. The maintained example at
`examples/drawings/index.html` demonstrates every descriptor with real controller
placement, selection, properties and persistence. Its OHLC data is simulated.

Keep these distinctions when migrating a host:

- `fib-fan` keeps the existing price-ray geometry and is named Fib Fan. The full
  two-family fan is `fib-speed-resistance-fan`.
- `fib-extension` keeps three stored anchors. The two-point swing tool is
  `fib-extension-two-point`.
- Regression fits `PrimitiveRenderContext.bars()` closes in the selected range.
  Its `props.deviation` scales residual standard deviation. It rereads live bars.
- Trend Fib Time uses logical bar indices for spacing across closed sessions.
  Radial studies use media-pixel radii. Apply DPR only when painting.
- Named harmonic patterns annotate manual anchors and ratio ranges. They do not
  detect signals or send orders. Do not interpret a ratio label as a trade action.
- Multi-point guides are temporary preview state, never a saved incomplete drawing.
  Drawing document version 2 and old IDs stay unchanged.

For drawing performance changes, run the complete catalogue's real-browser
placement, touch, body/handle drag, undo, pixel and persistence sweeps. Inspect
screenshots and verify forward-space clipping. Keep text measurements scoped to
a paint so font changes cannot leave stale hit boxes. Bound recursive geometry
and curve work; never cache forming-bar calculations by array identity.

`sonic` and `supersonic` use `props.waveCount` as a cap on sorted enabled
`style.levels`: default 6, range 1..12. Their default ladder has 12 eligible
levels, so increasing the cap adds waves without rewriting enabled flags.
Golden variants use all enabled Fibonacci levels. Supersonic tools also read
`props.mach` (1.01..20, default 2); tessellation reads `props.maxCurvature`
(1..64). Every field is available through the descriptor's settings schema.

Dense labels on advanced geometry use bounded vertical spacing. Labels with no
room in a tiny plot are omitted without changing saved anchors, level values or
hit regions. Zoom in or disable unneeded levels to inspect crowded values.


## Named drawing groups (2.5.3)

`DrawingGroup` contains an id, name and drawing ids. `DrawingController.groups()`,
`createGroup(name, ids, options?)`, `renameGroup(id, name, options?)`, and
`removeGroup(id, removeDrawings = false, options?)` manage membership. A read-only
drawing (`policy.editable: false`) keeps the group the host gave it: `createGroup`
leaves it out, and a group that holds one is renamed or removed only with
`{ force: true }`. Undo and redo follow the same rule, and every step already
recorded takes a forced grouping call as well, so no press reverses it.
`createGroup` mints an id (`group-N`) that neither a live group nor any undo or
redo step holds, so a step that brings back an old group never lands on a new
one. A drawing belongs to
at most one group. Invalid/missing members are discarded on restore. Optional
`DrawingsDocument.groups` preserves old drawing documents and round-trips named
groups. Group changes participate in undo/redo. `ChartObjectDrawingGroup` is the
base tier's structural view, avoiding an import from the draw tier.


## Viewport-anchored drawings (2.5.5)

A drawing's `space` says which coordinates its anchors are in. `'data'`, the
default and never written out, is time and price: the drawing follows the bars.
`'viewport'` pins it to the screen: the anchors are `viewportPoints`, `{ x, y }`
fractions of the plot area of the pane that holds it, and `points` is empty.
Pan and zoom leave it where it is, a chart resize keeps it in proportion, and it
paints at any device pixel ratio the way every drawing does.

**Pane-relative, not whole-chart-relative.** `x` is 0 at the plot's left edge
and 1 at its right edge (the price axes are outside that span); `y` is 0 at the
top of the pane and 1 at the bottom of its plot (above the time axis on the
lowest pane). The pane's own layer paints, clips and hit-tests the drawing, so
these are the coordinates that follow the pane when it moves (`movePane`), is
resized by its separator, or is collapsed and opened again. Whole-chart
coordinates are not offered. Sizes a tool sets in pixels (a font size, a wrap
width) stay in pixels: a resize moves a note in proportion without scaling its
type, while both corners of a box scale with the pane.

**Which tools.** `text`, `rectangle`, `ellipse` and `table` declare
`DrawingTool.viewport`, and only those accept the space. Their geometry and
text come from the screen anchors alone and nothing they print is a price or a
time. The note family points at a bar, the fib, measure and position tools
print prices, and the analysis tools compute from bars, so a fixed place on
screen would contradict what each of them says. A custom tool opts in with
`viewport: true` when its `draw` and `distance` read only `pts`; `expand`,
`constrain` and `alertValue` apply to data space only. A saved viewport entry
whose tool lacks the flag is kept in the model and neither painted nor hit.

```ts
// Programmatic: the fractions are the anchors.
draw.add({ tool: 'text', paneIndex: 0, style: {}, points: [], space: 'viewport',
  viewportPoints: [{ x: 0.02, y: 0.04 }], text: { value: 'Session plan' } });

// Placement: clicked where the user clicks, pinned from then on.
draw.setTool('rectangle', { space: 'viewport' });

// Conversion at the view on screen, one undo step each way.
draw.update(id, { space: 'viewport' });
draw.update(id, { space: 'data' });
```

`add` throws for a tool without viewport support or anchors that are not finite
numbers. A conversion the controller cannot make (a tool without support, a
pane folded to its strip or hidden) is left out of the patch and the rest
applies, and `update` returns false so a host can tell; with the new space's
anchors in the patch they are taken as given. Pinning a drawing that is part
way or wholly off the plot brings it onto the plot, since no pan could reach it
afterwards, and one wider or taller than the plot is cut to it on that axis, so
every handle is on screen. Editing is native: the body drags by the pointer's
travel as a fraction of the pane, a handle lands under the pointer, `nudge`
moves by screen pixels. Placement with a tool armed for the viewport lands where
the user clicks: the magnet does not pull and shows no ring. `alertInfo` reports
a pinned drawing unavailable: it has no price to watch.

**The whole drawing stays on the plot.** A text note and a table are laid out
right of and below one anchor, so holding the anchors inside the pane would
still let a note sit wholly outside it, clipped away and out of reach of the
pointer. What is kept inside is the drawing's box instead:
`DrawingTool.bounds(pts, drawing)` returns it in media px (the text tool and the
table declare it from the same measurement their hit test uses, and the
rectangle and the ellipse from the label they paint, which with
`position: 'outside'` sits above the shape and can run past its sides; without
it the box is the anchors' bounds). The layer paints and hit-tests a pinned
drawing with its box moved inside the plot, and where the box is larger than the
plot its top-left corner is kept in view. A handle dragged toward an edge that
the box reaches first (a label above a box, at the top) stops short of it, so
the other corners stay where they are, and a box cut to the plot when it is
pinned leaves room on the plot for its label.
Every gesture (body drag, handle drag, nudge, paste, duplicate, placement,
conversion) starts from where the drawing is painted and stores the result
with the box inside, so what is stored is what is on screen. Fractions a host
stores outside 0..1 are kept as given and painted with the box on the plot. A
chart resize can make a note's pixel box overflow the fraction it sits at; the
layer moves it back in, so it stays visible and clickable at every size.

The settings schema carries the choice as `SPACE_FIELD` (path `space`, a select
over `SPACE_OPTIONS`: Time and price, Screen), declared by exactly the four
tools, so a generated properties panel offers it where it works and nowhere
else. The widget's drawing properties show it as the Anchor row, and the
reference host's properties bar as a pin toggle. Both read the model back after
the write and say why when a folded or hidden pane left the drawing where it was.

Persistence and transfer: `migrateDrawings` keeps a viewport entry and drops
one without usable `viewportPoints`; a document with no viewport drawing loads
byte for byte as before, still version 2. The clipboard payload carries the
space and the fractions, so a paste lands at the same place on a chart of any
size, offset by `pasteOffsetPixels` on both axes; `duplicate` does the same.
Drawing links never share a viewport drawing (the same fraction of another
chart's pane sits over different bars at a different size), and pinning a
shared drawing takes it out of the link on that chart alone, dropping its
lineage mark, while the other charts keep their copy. Undoing the pin brings the
mark back and the drawing joins the link again, its state going to the peers as
any undo on a linked drawing does; if the peers deleted their copies meanwhile,
it stays on this chart alone and loses the mark, so a later restore does not
apply their deletion to it.

The controller measures a viewport anchor by the plot the chart reports,
`DrawingChartHost.plotRect(paneIndex)` (`chart.plotRect`, `{ left, top, width,
height }` in container px, null where the pane has no plot on screen), the same
rectangle the chart hands the layer that paints it, and converts time and price
through `DrawingChartHost.timeScale` and each pane's `priceToY` / `yToPrice`,
which the built-in `Chart` provides. A host without them still paints viewport
drawings but cannot place, move or convert them. `screenPoints` adds the plot's
left edge and top from that rectangle, so an HTML overlay a host lays against
`chart.plotRect` lines up with the drawing. Types: `DrawingSpace`,
`ViewportPoint`, `DrawingPlacementOptions`.


## Drawings per instrument (since 2.5.9)

The controller holds one document and the engine has no instrument concept, so
a host that loads another symbol into the same chart keeps the previous
symbol's drawings on screen, and a delete there deletes them for every symbol.
Traders expect the opposite: levels belong to the symbol they were drawn on.
`InstrumentDrawings` keeps one document per instrument in a store the host
chooses and swaps them as the chart's data context moves. It is DOM-free and
ships in the draw tier; the widget uses it by default (see widget.md,
`drawingScope`).

```ts
import {
  DrawingController, InstrumentDrawings, createInstrumentDrawings, instrumentDrawingsKey,
  memoryDrawingStore, webStorageDrawingStore, migrateUnscopedDrawings,
} from 'openalgo-charts/draw';

const draw = new DrawingController(chart);
// localStorage only because the host hands it over; the default is memoryDrawingStore().
const store = webStorageDrawingStore(localStorage, 'my-app:p0:drawings:');
// One-off migration: a pane-wide document saved before drawings were per
// instrument belongs to the symbol the pane was saved with.
migrateUnscopedDrawings(store, instrumentDrawingsKey({ symbol: savedSymbol, exchange: savedExchange }),
  JSON.parse(localStorage.getItem('my-app:p0:draw') ?? 'null'));
const scoped = new InstrumentDrawings(chart, draw, { store, onError: e => console.warn(e.operation, e.key) });
// or createInstrumentDrawings(chart, draw, { store })

chart.setDataContext({ symbol: 'INFY', exchange: 'NSE', interval: '5m' });  // loads INFY's drawings
chart.setDataContext({ symbol: 'TCS', exchange: 'NSE', interval: '5m' });   // saves INFY's, loads TCS's
```

| Export | What it is |
|---|---|
| `InstrumentDrawings(chart, controller, options?)` | The helper. `chart` is `InstrumentDrawingsChart`: `on`, and `getDataContext` to read the instrument at the start. |
| `createInstrumentDrawings(chart, controller, options?)` | The same, as a function. |
| `instrumentDrawingsKey(instrument)` | The default key: `NSE:INFY`, or `AAPL` with no exchange; each part URI-encoded; null without a symbol. Case is kept. |
| `memoryDrawingStore()` | The default store, in memory for the life of the page, a copy per entry. |
| `webStorageDrawingStore(storage, prefix)` | One JSON entry per instrument under `prefix` in any `DrawingTextStorage` (`getItem`, `setItem`, `removeItem`). |
| `migrateUnscopedDrawings(store, key, document)` | Writes an old pane-wide document (2.0 or a 1.9 array) under `key` only when the store has nothing there and the document has drawings; true when written. A store whose `get` throws is not written over. |

`InstrumentDrawingsOptions`: `store` (a `DrawingDocumentStore`: `get(key)`,
`set(key, document)` where false or a throw is a failure, `remove(key)`), `key`
(`(instrument: DrawingInstrument) => string | null`, for one set per data
variant or a namespace per chart), `prefer` (`'stored'`, the default, or
`'live'`) and `onError` (an `InstrumentDrawingsError`: `operation` `'read' |
'write' | 'remove'`, `key`, `error`). Methods: `key()`, `setInstrument(instrument
| null)` for a host that switches ahead of its data context or publishes none,
`document(instrument)` (a copy, the live drawings for the current instrument,
null when there are none), `setDocument(instrument, document)` (the
controller's `fromJSON` for the current instrument, the store for another),
`save()` (writes now and retries refused writes; false while one is still
refused), `destroy()`, `isDestroyed`.

What it decides, and why:

- **When it swaps.** On `data:context` naming another symbol or exchange, in
  the same turn, before later listeners (an alert controller, a link group)
  run their own. An interval or a data variant is the same instrument; a
  context that names none (cleared, or no symbol) changes nothing, and the
  drawings stay with the last instrument. The store is synchronous for that
  reason: an answer arriving after the context moved would land on whatever the
  chart shows by then. A host with drawings on a server keeps a synchronous
  copy here and syncs it in the background.
- **When it writes.** On every `drawing:change`, only when the saved document
  changed; an instrument left with no drawings has its entry removed. Transient
  drawings (`policy.persistent: false`) are never written and do not survive a
  swap: a host keeping one per instrument places it again after the swap
  (`draw:restore` fires on the load). Anything else that replaces the whole
  document, a host's `fromJSON` or `chart.restoreState`, is the current
  instrument's new document and is written as such.
- **At the start.** With a stored document for the current instrument,
  `prefer: 'stored'` loads it; `prefer: 'live'` keeps what the controller holds
  (even nothing) and writes it, for a host that has just loaded that
  instrument's drawings itself (a layout, a chart rebuilt from the one it
  replaces). With nothing stored, the controller's drawings are adopted as the
  instrument's. A helper built before the chart names any instrument adopts
  them for the first one named. That adoption is the migration path for a host
  that restored its old pane-wide document into the controller.
- **Undo.** A swap is not an edit: it records no step and, like any `fromJSON`,
  clears the controller's undo history, so no undo on one instrument restores or
  removes a drawing of another. The widget's `ChartHistory` drops every drawing
  step and every drawing a removed pane took with it when the controller loads
  another document (`draw:restore`); the steps of studies, panes and settings
  stay, since those belong to the chart.
- **A gesture in progress.** A drag is put back first (the outgoing document is
  saved as it was before the drag) and goes no further; anchors placed for an
  unfinished shape are dropped with the outgoing instrument, and the tool stays
  armed, so the next click on the new symbol is its first anchor.
- **Drawings pinned to the viewport** swap with the rest of the document. A
  group or a stacking order can span both spaces, so splitting the document
  would break both, and a note pinned to the screen is nearly always about the
  instrument on it. A host wanting a label on every symbol uses a primitive or
  the watermark.
- **Alerts.** An alert anchored to a drawing keeps its drawing id while its
  instrument is off the chart: `AlertController` removes a drawing alert whose
  drawing is gone only when the alert's instrument is the one the chart shows,
  both on `objects:change` and on restore. On another instrument it neither
  evaluates nor draws (availability says the instrument context differs), even
  over a drawing there that happens to share its id.
- **Drawing links.** A swap loads with `fromJSON`, which announces no
  `draw:add`, so a `DrawingLinkGroup` never broadcasts one instrument's drawings
  as another's; the group rebinds the loaded document's own shared drawings by
  their lineage for the new context, as after any restore.
- **The clipboard** is separate from the document: copy on one symbol and paste
  on another is the user's own act and lands on the new symbol.
- **A failing store.** A refused write or removal is reported through `onError`
  and the document is held in memory, read back from there for the session, and
  written again with the next change or `save()`. An unreadable entry is
  reported and shows no drawings; the next change on that instrument writes
  over it.

## Modifier gestures (since 2.5.9)

Pointer gestures a held modifier key starts. Ctrl means Cmd as well, so macOS
users press Cmd. None of them is a key chord, so none collides with
`matchDrawingShortcut` (Alt+letter arms a tool) or `keyToDrawingAction`
(Ctrl+Z, Ctrl+C and the rest): those read key events, these read the modifier
state a pointer payload carries. Each is on by default, and
`DrawingControllerOptions.gestures` (a `DrawingGestureOptions`) turns one off
for a host whose own chart gestures already use that key; `setOptions` merges
it flag by flag.

| Gesture | Where | Flag |
|---|---|---|
| Ctrl held | placing an anchor, dragging a handle or a shape: the strong magnet while held | `snapModifier` |
| Shift+click | empty chart space, no tool armed: a temporary measure | `measure` |
| Ctrl+drag | empty chart space, no tool armed: box select (Ctrl+Shift+drag adds to the selection) | `boxSelect` |
| Alt+drag | a drawing's body: drag a copy, leaving the drawing | `dragCopy` |

### The magnet everywhere (since 2.5.9)

The magnet (`magnet: 'weak' | 'strong'`) pulls a handle in hand and a whole
shape in hand, not only a placement:

- **A handle** lands on the nearest value of the bar under it, at that bar's
  time, the same as a placement. Shift's angle lock still wins on a line.
- **A shape grabbed by its body** moves rigidly, shifted by whatever lands its
  anchor nearest the press on a value: that one anchor lands on the bar's time
  and value, the others keep their offsets from it. Every other selected
  drawing moves by the same shift.
- **A study pane** snaps to the values its studies plot there, read the way the
  legend reads them (the value painted under the bar, after the plot's
  `offset`; all four columns of a bar-shaped plot). A hidden study, a plot with
  `visible: false` and a plot in a fully transparent colour are skipped, so an
  anchor never lands on a line that is not drawn. Candidates are compared on
  screen, since plots on one pane can sit on different scales, and the anchor
  takes the price the pane's own scale reads there. The price pane keeps
  snapping to the candles' O/H/L/C.
- **Ctrl (Cmd) held** is the strong magnet for as long as it is held, whatever
  `magnet` is, including `'off'`: while placing (the ring shows), and while
  dragging a handle or a shape. Letting go returns to the mode.

A drawing pinned to the viewport never snaps. The chart reports no bar under
the pointer during a drag, so a drag reads the bar at its time through
`DrawingChartHost.primaryBars`; a study pane needs `indicators` and `panes`
(each pane's `scales()`, `priceToY` and `yToPrice`), and `seriesStyle` to skip
a hidden plot. All are optional on `DrawingChartHost`, and a chart from
`createChart()` has them all; a host without them snaps placements on the price
pane as before.

### Temporary measure (since 2.5.9)

Shift+click on empty chart space, with no tool armed, lays down a ruler: the
`measure` tool drawn from the click to the pointer, its far end following the
pointer on the pane it started on (a pointer elsewhere leaves the end where it
last was). Both ends go through the magnet. The next click, anywhere, takes it
away and does nothing else (it does not select what it lands on), and so does
`cancel()`, which is what Escape maps to; arming a tool, a restore, a pane
removed and a change of data context take it away too.

It is a preview, painted in the slot a shape being placed uses: never in
`drawings()` or `toJSON()`, never an undo step, never a `draw:add` or a
`drawing:change`, so no `DrawingLinkGroup` carries it to another chart and no
host autosave sees it. `measuring()` says whether one is up, and `draw:measure`
(`{ active: boolean }`) fires as it starts and goes. `keyToDrawingAction` maps
Escape to `cancel` only while `placing` is true, so a host that routes keys
through it passes `placing: draw.activeTool() !== null || draw.measuring()`.
Shift+click keeps its other meanings: on a drawing it adds to the selection,
and with a tool armed Shift is the angle lock.

### Box select (since 2.5.9)

Ctrl plus a drag on empty chart space, with no tool armed, draws a box on the
pane it started on and selects every drawing on that pane the box touches,
live as the box grows (a box whose sampling would cost more than a frame's
budget selects once, on release). With Shift held as well it adds to the
selection the drag started with; without, it replaces it.

**Touches** means the box intersects the drawing's geometry, not merely an
anchor: a line that crosses the box, a fib level inside it whose anchors are
both outside, a filled shape the box sits inside, and a label all count. It is
measured with the tool's own `distance`, the answer a click gets, sampled over
the box finely enough that any part of a drawing inside it is found, to the
6 px a click reaches; an outline the box sits wholly inside does not count,
since a click there would not select it either. Hidden and locked drawings,
and drawings whose policy sets `selectable: false`, stay out, as they do for a
click; a read-only drawing selects, as it does for a click.

The chart pans on a press over empty space, so the box is made ready before
the press: while Ctrl is held over empty space (the chart's `hover` reports no
hit and a `crosshair:move` carries Ctrl) with no tool armed and no pick
waiting, the controller puts the chart in placement mode, and gives the pan
back on the first report that no longer holds. The tier reads the keys from
pointer reports only, so Ctrl pressed with the pointer standing still just
before the press still pans; moving the pointer once with Ctrl held is enough.
A Ctrl+click on empty space that
never becomes a drag is the click it always was, and Ctrl+drag that starts on a
drawing drags it (with the strong magnet). The box is painted by the pane's top
layer (a `DrawingLayer` subclass), a thin solid rim over a translucent fill in
the theme's `lineColor` (solid, so it never reads as the dashed crosshair), and
is gone on release.

### Drag to copy (since 2.5.9)

Alt (Option on macOS) plus a drag on a drawing's body leaves the drawing where
it is and moves a copy of it instead: the whole selection, as a plain drag
would move it (locked and read-only members are neither moved nor copied), and
the copies end up selected. The copy is made once the pointer has travelled 3
px from the press, so an unsteady click leaves no copy hidden under the
drawing. It is one undo step: the step's `drawing:change` is `kind: 'add'` with
the copies' ids, and undo takes the copies away. The copies are announced
once, at the drop (`draw:add`, then the `drawing:change`), never at the place
they were copied from, so a `DrawingLinkGroup` sends each linked chart one new
drawing where it landed. Like `duplicate`, each copy is the user's own: a new
id, no `policy`, and no link lineage. A cancelled drag (`drag:cancel`, Escape,
a pane removed) takes the copies back out and gives the selection back, with
no step recorded. The magnet lands a copy the way it lands a moved shape, and
Ctrl with Alt copies with the strong magnet. A handle drag with Alt is a
handle drag.

### Eraser mode (since 2.5.9)

`draw.setEraser(true)` turns eraser mode on: a click on a drawing deletes it,
and a drag deletes every drawing it crosses, as one undo step when the pointer
lets go (one `drawing:change`, `kind: 'remove'`, with every id). What it
touches is measured the way a click is, within the grab radius of the path
the pointer took (twice that for a touch), so a fast sweep takes a thin line
it passed between two pointer reports. Drawings the drag has touched are left
unpainted while it goes on and deleted on release; an interrupted drag (a
change of data context, a restore) gives them back and records nothing. It
takes only what the user could select and delete: a read-only drawing
(`policy.editable: false`), a locked, an unselectable and a hidden one stay. A
click on empty space does nothing.

While it is on the chart is in placement mode, so a drag erases rather than
pans, and the pane under the pointer shows a ring the size of the eraser's
reach. Turning it on disarms any armed tool (`draw:tool` fires with `null`);
`setTool` (with a tool or `null`), `cancel()` and `setEraser(false)` turn it
off, and `draw:eraser` (`{ active }`) fires on each change. `erasing()` reads
it. A host routing Escape through `keyToDrawingAction` passes
`placing: draw.activeTool() !== null || draw.measuring() || draw.erasing()`
so that Escape reaches `cancel()`. It is a mode, not a modifier, so it has no
`gestures` flag: a host that offers no eraser control never turns it on.

## Visibility per interval (since 2.5.9)

A drawing can carry the range of chart intervals it is shown on:
`Drawing.intervals`, a `DrawingIntervalRange` of interval codes, `{ from?, to? }`,
both ends included. Absent means every interval. A level drawn on hourly bars
is often noise on the one minute chart and too fine to matter on the weekly
one, so `{ from: '1m', to: '1h' }` keeps it to those.

```ts
import { DrawingController, drawingShownOnInterval, INTERVAL_FIELDS, composeSettings } from 'openalgo-charts/draw';

chart.setDataContext({ symbol: 'INFY', exchange: 'NSE', interval: '15m' });
const draw = new DrawingController(chart);
const level = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time, price }],
  intervals: { from: '1m', to: '1h' } });
draw.update(level.id, { intervals: { to: '4h' } });   // replaces the range, one undo step
draw.update(level.id, { intervals: null });            // every interval again ({} does the same)

chart.setDataContext({ symbol: 'INFY', exchange: 'NSE', interval: 'D' });
draw.shownOnInterval(level.id);      // false while the chart is on daily bars
draw.hiddenOnInterval();             // [level.id]: every drawing the interval hides, in one pass
drawingShownOnInterval(level, '5m'); // the same test for any interval, no controller needed
```

How intervals compare:

- **By bar length, from the interval registry.** `60m` and `1h` are one interval,
  and a host's own codes (`registerInterval`) take part like the built-in
  tokens. A calendar interval counts a mean month per month: it has no fixed
  length, but a month still sorts above a week and below a quarter.
- **The ends either way round.** The range is the span between them; an absent
  end is no limit on that side (`{ to: '1h' }` is everything up to hourly).
- **A comparison that cannot be made hides nothing.** An end nothing resolves
  to a length (an unknown code, a tick or volume interval) is no limit, and a
  chart interval of that kind, or none at all, shows every drawing.
- A stored or requested range keeps only ends that are non-blank strings, and
  one naming neither end is no range.

**The chart's interval is its data context's.** The controller reads
`chart.getDataContext()?.interval` (optional on `DrawingChartHost`) when it is
built, and follows every `data:context`; a host with no `getDataContext` is
followed through the event's payload. `interval()` returns it, or `null` for
none or a blank one. The change applies the moment the chart announces it, and
the layers are listed again only when the set of hidden drawings changed, so a
new symbol on the same interval repaints nothing. The context
`publishDataContext` passes through on a change of data variant alone, whose
interval is cleared, is not followed, as the chart's other listeners skip it:
the interval, the layers and the selection stay as they were until the real
context arrives within the same call.

**Outside its range a drawing is kept but not on the chart.** It stays in
`drawings()`, `toJSON()`, the undo history and every link, but no layer lists
it, so:

- nothing paints it, and `chart.exportSVG()` and `takeScreenshot()` leave it out;
- a click passes through it, and a box select or an eraser drag does not reach it;
- an interval change drops it from the selection and the hover. Picked on
  purpose (`select(id)`, an objects panel row) it is selectable all the same,
  so a settings panel can widen its range; it has no handles to show.
- the object inventory lists it with `hiddenOnInterval: true` and withholds
  `focus`, which would bring into view a place where nothing is drawn. A group
  row is marked when every drawing in it is hidden. The row's `visible` stays
  the user's own switch. The controller answers the inventory through the
  optional `ChartObjectDrawingSource.hiddenOnInterval()`, asked once per
  refresh rather than once per row.
- `visible` is untouched: the range is not the user's show and hide switch.
  An alert on the drawing keeps firing, since a display choice is not a
  change of the level it watches. `clear()` still takes every drawing the user
  may delete, hidden ones included. A host's "select all" should take
  `hiddenOnInterval()` out, as the reference host's does, or the delete that
  follows removes drawings nobody can see on this interval.

A copy carries the range: `duplicate`, Alt+drag and the clipboard keep it.
**A paste never lands hidden:** a copy whose range leaves out the receiving
chart's interval is pasted without it, since a paste that shows nothing looks
like a paste that failed. A `DrawingLinkGroup` shares the range, and each linked
chart shows the drawing by its own interval.

**Settings.** The pair is two dot paths, `intervals.from` and `intervals.to`,
of kind `'interval'` in the `'visibility'` group: `INTERVAL_FIELDS`. No tool
declares them, because the engine cannot list a host's intervals. A host that
offers the control adds them and renders its own interval list, with an empty
choice for no limit:

```ts
const schema = composeSettings([drawingSettingsSchema(d.tool).fields, INTERVAL_FIELDS]);
readDrawingSettings(d, schema);          // { ..., 'intervals.from': '1m', 'intervals.to': '1h' }
draw.update(d.id, applyDrawingSettings(d, { 'intervals.to': 'D' }, schema));
```

`coerceSettingValue` trims an `'interval'` value and turns an empty one into
`undefined`, which removes that end; `applyDrawingSettings` returns the pair
whole as `intervals`, and `{}` once neither end is left, which the controller
takes as no range. `DrawingPatch.intervals` replaces the range; `null` or `{}`
clears it. A forced patch on a read-only drawing is held and taken into the
history like any other forced patch.

**Document version 3.** The range is the one field version 3 added.

- A version 2 document is a valid version 3 one and loads unchanged, version
  and all: `migrateDrawings` keeps `version: 2` for a document with no range.
- `toJSON()`, `migrateDrawings` and a clipboard payload are written as version
  3 only while a drawing carries a range, and as version 2 again once none
  does. `InstrumentDrawings` stores what the controller writes, so a stored
  version 2 document is read through the migration and written back only when
  something in it changes, then as whichever version holds it.
- **An older reader and a version 3 document.** A build before this one reads
  version 2. Its clipboard refuses a payload newer than it reads, so it pastes
  nothing from a copy that carries a range, and still pastes a copy without
  one (written as version 2). Its migration never refused a document: it keeps
  the fields it knows and drops the rest, so it opens a version 3 layout with
  every drawing, shows the ranged ones on every interval, and writes the next
  save without their ranges. Keep a layout with ranges away from an older
  build, or expect to set the ranges again.
- This build reads a document from a later version the same lenient way:
  what it knows is kept and the rest dropped, since refusing it would empty
  the chart on load. The clipboard, which can refuse without losing anything,
  refuses a payload newer than `DRAWING_CLIPBOARD_VERSION`.
