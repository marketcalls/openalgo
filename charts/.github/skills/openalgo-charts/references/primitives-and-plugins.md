# Primitives and Plugins

*When to read this: you are drawing anything on the chart that is not a series (price lines, reference levels, markers, zones, badges, on-chart controls), or registering a custom chart type.*

Source of truth: `src/primitives/primitive.ts`, `src/primitives/*.ts`, `src/core/pane.ts`, `src/core/chart.ts`, `src/model/chart-type-registry.ts`.

Everything the chart draws that is not a series is a primitive: markers, event badges, price lines, the pane legend, the time navigator, the drawing layer, and the whole trading tier. One interface covers all of them.

`PaneLegendOptions.visible` defaults to true. Setting it to false removes that
row's painting and hit targets without changing the underlying series or study.
Chart-wide `setIndicatorLegendCollapsed(true)` separately suppresses study-owned
rows and retains a count control. Expanding restores each row's own visibility;
host-added symbol and OHLC legends retain their visibility throughout.

## Table cells

`ChartTable` stays in pane screen space. `TableCell` accepts newline-separated
text, `bold`, `italic`, CSS `fontFamily`, `fontSize`, horizontal `align` and
`verticalAlign: 'top' | 'middle' | 'bottom'` (default middle). Measurement and
painting use the same font. Automatic columns measure the widest line; automatic
fonts fit the block. Text always clips to its cell.

`colSpan` and `rowSpan` merge a rectangle from its top-left cell. Positive safe
integers only, default one. The rectangle must fit inside the total rows and
maximum column count. Its anchor supplies text and appearance; covered ordinary
cells are ignored. Overlapping explicit spans throw. All spans are validated
before `setRows` replaces the previous grid. Ragged rows remain supported.
Automatic columns measure ordinary cells first, then share any merged text's
width deficit among its columns. Weighted and percentage heights also apply to
merged cells.

`ChartTableOptions.frameColor` and optional `frameWidth` (default one media pixel)
draw a separate outer frame after the cells. `borderColor`/`borderWidth` retain
their cell-border behavior. These fields also work in descriptor `table`/`tables`
results; existing compiled adapters must explicitly emit new fields to use them.

`TableCell.tooltip` adds plain-text hover detail, with explicit newlines and
automatic wrapping inside the plot. A merged cell uses only its anchor's detail.
Empty or omitted tooltips retain the existing behavior. Nonstring tooltip values
reject before replacing rows. Hover content clears when rows, sizing or ownership
change, and SVG exports omit it. A configured table `id` remains the click ID for
every cell. Without an `id`, only tooltip cells become hit targets and use an
opaque generated ID; supply an ID for stable application routing.

## `IPrimitive`

```ts
interface IPrimitive {
  zOrder(): ZOrder;                                                     // required, a METHOD
  draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void; // required
  autoscaleInfo?(): { min: number; max: number } | null;
  hitTest?(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null;
  // The box, in hitTest's coordinates, outside which hitTest answers null; null: never hit.
  hitBounds?(rc: PrimitiveRenderContext): { left: number; top: number; right: number; bottom: number } | null;
  attached?(host: PrimitiveHost): void;
  detached?(): void;
}

type ZOrder = 'bottom' | 'normal' | 'top';
interface PrimitiveHost { requestUpdate(): void; }
interface PrimitiveHit {
  externalId: string;
  hoverKey?: string;     // optional transient subtarget identity, separate from click IDs
  zOrder: ZOrder;
  distance: number;      // media px from the cursor; smaller wins; never negative
  cursor?: string;
  draggable?: boolean;   // arms a two-axis drag on press
  priceScale?: PriceScale; // coordinate scale for bound drag prices
}
```

**`zOrder` is a method, not a property.** `{ zOrder: 'bottom' }` compiles under a loose annotation and then throws at paint time when the pane calls `p.zOrder()`.

`attached(host)` is called on `pane.addPrimitive`; keep the host and call `host.requestUpdate()` whenever your state changes, it takes no arguments. `detached()` fires on `chart.removePrimitive` and on pane destruction; drop the host reference there.

**The repaint level follows your `zOrder()`, so there is nothing to opt into.** The host reads `zOrder()` on every `requestUpdate` call and schedules a `Cursor` repaint (overlay canvas only, the layer `Pane.paintTop` draws) for a `'top'` primitive and a `Light` one (base canvas) for everything else. A cursor-rate overlay therefore costs one overlay repaint rather than a full series redraw. It is read per call rather than captured at attach, so a primitive that changes layer at runtime is handled too.

### `PrimitiveRenderContext`

| Field | Type | Notes |
|---|---|---|
| `timeScale` | `TimeScale` | `indexToX(index)` returns **media** px; accepts fractional indices. |
| `priceScale` | `PriceScale` | Explicit primitive binding, or the pane's right scale when unbound. `priceToY`/`yToPrice` in media px, plus `format(price)`. |
| `readoutPriceScale?` | `PriceScale` | The primary visible price series' scale, independent of the primitive binding. |
| `dataLayer` | `DataLayer` | `timeToIndex`, `timeToIndexFloat`, `indexToTime`, `indexedBars`, `visibleBars`. |
| `plotWidth` / `plotHeight` | `number` | Media px, excluding the price axis and time axis strips. |
| `priceAxisWidth` | `number` | Bound scale's column width in media px; zero for hidden scales. |
| `priceAxisSide?` | `'left' \| 'right' \| 'hidden'` | Price-label placement; absent retains right-axis behavior. |
| `dpr` | `number` | Device pixel ratio for this frame. |
| `theme` | `ChartTheme` | Palette. `theme.background` may be the literal `'transparent'`. |
| `bars?` | `() => readonly Bar[]` | Lazy; the pane's primary price series. Optional, guard with `rc.bars?.()`. |
| `hoverId?` | `string \| null` | `externalId` currently hovered, for hover styling. |
| `hoverKey?` | `string \| null` | Optional hover subtarget, falling back to `externalId` for ordinary hits. |
| `dragId?` | `string \| null` | `externalId` currently being dragged. |

`pane.bindPrimitiveScale(primitive, id)` binds an attached primitive to `'left'`,
`'right'`, `''` or `overlay:name`; null removes the override. It returns false for
invalid, unavailable or unchanged requests. `pane.primitiveScaleId(primitive)`
returns the override or null. The owner schedules layout and repaint after the
resource transaction. Study-owned price resources use this binding automatically.

Bindings route every paint layer, hit-test and SVG export through the same scale,
follow pane transfers and whole-axis moves, and clear on removal. Bound resources
keep their scale alive and count toward visible axis occupancy. The pane adds
`PrimitiveHit.priceScale` to explicitly bound hits without mutating the primitive's
hit object. Chart retains that coordinate scale for drag start, movement and end;
unbound hits keep their legacy readout routing. Pointer cancellation retains it
through the compatibility release before clearing it.

`PriceLine` draws its axis pill in the bound left or right column and omits it for
hidden scales. Left pills fit inside the column and pane edges. The plot line,
its optional segmented label and its hit-test remain active on hidden scales.

## The dpr contract

**The canvas context is in bitmap (device pixel) scope; every media-px value you compute must be multiplied by `rc.dpr` before you draw it.**

The reason is in `src/core/canvas.ts`: the backing buffer is sized `round(media * dpr)` and `clearBitmap()` resets the transform with `setTransform(1,0,0,1,0,0)`. No `ctx.scale(dpr, dpr)` is ever applied. So:

- `timeScale.indexToX()`, `priceScale.priceToY()`, `rc.plotWidth`, `rc.plotHeight` are all **media** px. Multiply.
- Font sizes, line widths, radii, and paddings are yours to scale: set the font from `11 * dpr` px, and `ctx.lineWidth = Math.max(1, Math.round(w * dpr))`.
- `hitTest` receives `x`/`y` in **media** px relative to the plot's top-left, and must return `distance` in media px. Do **not** scale in `hitTest`.
- Snap 1px strokes with `Math.round(v * dpr) + 0.5`, the pattern every built-in uses.
- When a left price axis exists the pane translates the context by `round(plotLeft * dpr)` before calling you, so `(0, 0)` is always the plot's top-left.

## Paint order

`pane.paintBase()` draws to the base canvas (z-index 0) in this exact order:

1. Pane background
2. Grid
3. **`zOrder() === 'bottom'` primitives**
4. Series (registry-driven)
5. Left and right price axis ticks, with per-side value-tag reservations
6. Last-price line and tag
7. **`zOrder() === 'normal'` primitives**
8. Time axis (bottom pane only)

`pane.paintTop()` clears the overlay canvas (z-index 1) and draws:

1. **`zOrder() === 'top'` primitives**
2. Crosshair, price tag, time tag

A primitive placed with `chart.setPrimitiveStackAbove(primitive, entry)` paints inside step 4 instead of its own band: right after the last series of that entry (`'source:primary'` or `'indicator:<id>'` from `chart.seriesStack(paneIndex)`) on its pane, with a batching backend flushed first. `null` puts it back; an entry with no series on the pane leaves it in its own band, and such a primitive repaints with the base canvas whatever its `zOrder()`. The price source stays the pane's instrument (readout, last-price line, rebased axis) wherever the series band puts it.

Within a z-order band, primitives paint in attach order. `top` sits on the cheap-repaint canvas, so anything that must react to the cursor without a full repaint belongs there. `normal` deliberately paints *after* the last-price line so order pills stay legible when the LTP crosses them.

**Steps 3 and 4 are clipped to the plot; nothing else is (1.8.5).** Bottom-layer primitives and the series draw inside a clip of `plotWidth` by `plotHeight`, which is released before the axis ladder. A bar is positioned by its centre and drawn outward, so without it the newest bar against the right edge put half a body and a wick into the price-axis strip, behind the labels.

The practical consequence for a primitive author: a **`bottom`** primitive can no longer paint into the axis strips, which is what you want for a background zone or a shaded region. A **`normal`** or **`top`** primitive still can, deliberately, because that is where an axis tag or a price-line pill belongs. If your background shading suddenly stops at the plot edge, that is this change and it is the correct picture.

## Hit-testing and `externalId`

The chart hit-tests one pane at a time and reduces the results with `bestHit`:

```ts
function bestHit(hits: readonly (PrimitiveHit | null)[]): PrimitiveHit | null
```

Smallest `distance` wins; on a tie the higher z-order wins (`top` > `normal` > `bottom`). `null` entries are skipped. Use it directly inside a composite primitive that delegates to sub-objects.

The pane ranks its primitives' hits by paint band before distance: a hit painted over the series (a `'normal'` or `'top'` primitive in its own band) beats one painted with or behind the series (a primitive placed with `chart.setPrimitiveStackAbove`, a drawing layer under the front one, a `'bottom'` primitive) wherever both answer. Within each side it is `bestHit`'s order: nearest, then the higher band.

A primitive answering for others sets `PrimitiveHit.paintedBy` to the primitive that painted the hit (the draw tier's front layer does for the layers under it), and the pane sets it on a hit from a primitive placed in the series band. The band ranking reads it, and for the context menu target the chart compares paint order: where that primitive paints under the series under the pointer, the series is the target. A hit without `paintedBy` keeps the menu, as before.

Routing, from `src/core/chart-input.ts`:

- **Click**: on pointerup without movement, the pane is hit-tested at the press point. A hit fires `chart.subscribeClick(cb)` with the `externalId`, and the `click` bus event carries `{ id, price, time, paneIndex, point }` with `id: null` on empty plot.
- **Drag**: on pointerdown, a hit arms a drag when `hit.draggable === true`, or when `hit.cursor === 'ns-resize'` and `subscribeDrag` has a callback. The press emits `drag:start`. Moves fire `subscribeDrag(onDrag)` and a `drag` bus event `{ id, price, time, paneIndex, fromPrice, fromTime }`; release fires `onDragEnd` and `drag:end`. Listen for `drag:cancel` to discard drafts on pointer cancellation or pinch. Set `PrimitiveHit.cancelOnEscape: true` only when the consumer handles cancellation without requiring an end notification; it enables Escape rollback, including with shortcuts disabled. Pointer cancellation retains the legacy end notification after cancellation.
- A drag that never moved is replayed as a click, so a draggable primitive is still clickable.
- `hoverId` / `dragId` are pushed back into `PrimitiveRenderContext` each frame, which is how `PriceLine` renders its hover and dragging states without any state of its own.
- A composite primitive can return a unique `hoverKey` for each region while keeping one `externalId`. Key changes repaint the hover state without adding duplicate public `hover` events for the same external ID. SVG export clears both hover fields.

Namespacing convention used by the built-ins, one primitive, several targets:

| Primitive | `externalId` |
|---|---|
| `PriceLine` | `id`, and `${id}::close` for the cancel segment |
| `PaneLegend` | `${id}::close` / `::hide` / `::settings` / `::source` / `::up` / `::down` / `::collapse` / `::maximize`, `${id}::row` |
| `BuySellButtons` | `${id}:buy` / `${id}:sell` / `${id}:qty` |
| `TimeNavigator` | `${id}::zoomIn` / `::zoomOut` / `::panLeftBar` / `::panRightBar` |
| `DrawingLayer` | `draw:<drawingId>`, `draw:<drawingId>#<anchorIndex>` |
| `SeriesMarkers` | the caller's `marker.id` (no hit when absent) |
| `EventMarkers` | a unique caller `event.id` for a single event; a generated stable handle for anonymous events, duplicate IDs and clusters; details retain original event IDs |

Record hit geometry during `draw` and read it in `hitTest`, that is how `PriceLine`, `BuySellButtons`, and `PaneLegend` stay in sync with what was actually painted, and it means a primitive that has not drawn yet correctly reports no hit.

### Hit boxes (`hitBounds`)

A pointer move asks `hitTest` of every primitive on the pane unless it declares where it can answer. `hitBounds(rc)` returns that box in the same media px, relative to the plot (edges inclusive, a side may be infinite), or `null` when nothing of it can be hit. The pane then asks `hitTest` only when the point is inside, so 500 annotations cost the handful near the pointer (4.5 asked per move instead of 500 in `node scripts/bench-pane.mjs`).

```ts
hitBounds(rc) {
  const x0 = rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(this.t0));
  const x1 = rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(this.t1));
  const y0 = rc.priceScale.priceToY(this.p0), y1 = rc.priceScale.priceToY(this.p1);
  const pad = GRAB + 0.5; // cover everything hitTest answers, rounding included
  return { left: Math.min(x0, x1) - pad, top: Math.min(y0, y1) - pad, right: Math.max(x0, x1) + pad, bottom: Math.max(y0, y1) + pad };
}
```

- **The box must hold every point `hitTest` can answer.** A point outside it is never asked, so a box that is too tight loses hits. A NaN edge makes the pane ask anyway.
- **The pane keeps the box** while nothing it follows changes: the time scale and the bars' times, the pane's price scales, size and axes, the pixel ratio, hover and drag, the theme and session calendar, and the primitive's own state, announced through `host.requestUpdate()`. A box that depends on anything else (bar prices) must request an update when that changes, or leave the hook out.
- **Compute it from the same geometry `hitTest` uses**, `rc` or what the last `draw` recorded. A box asked for between a change and the frame that paints it is asked for again once that frame is painted.
- The pane also stops walking at an exact hit (`distance: 0`) among the primitives painted in front, which nothing after it can outrank. `hitTest` must be free of side effects either way: a primitive can be skipped.
- **A primitive that declares `hitBounds` is attached with a host that wraps the chart's**, so the pane hears its `requestUpdate`. Do not compare that host with another primitive's by identity.

The hook arrived in 2.5.8. The built-in primitives do not declare boxes yet, so they are asked on every move as before. The draw tier's layers keep a box per drawing of their own instead (since 2.5.9): the pane asks a layer on every move, and the layer asks only the drawings whose box the pointer is in, 4.5 of 500 trend lines per move in `node scripts/bench-pane.mjs`. The boxes follow the same scales and plot size, and a new drawing list; a host driving a `DrawingLayer` itself hands a drawing edited in place over again with `setDrawings`, as the controller does, for a hover to see where it now is.

## `autoscaleInfo`

Returning `{ min, max }` expands the primitive's bound price scale while that scale
is on `autoScale`. Unbound primitives contribute to the right scale. Each primitive
is consulted once per applicable autoscale pass, alongside that scale's visible bars.

Return `null` for anything that overlays rather than drives the range, the drawing layer, indicator fills, watermarks, legends, and on-chart buttons all do. `PriceLine` returns `{ min: price, max: price }`, which is what keeps an order line on screen.

Keep it cheap: it runs on every `Full` invalidation, which includes every `series.update()`.

## Built-in primitives

| Primitive | z | Purpose | Key options / methods |
|---|---|---|---|
| `PriceLine` | `normal` | Horizontal level with a right-axis tag and an optional broker-style pill group. | `price`, `color`, `lineWidth`, `dashed`, `id`, `label`, `badge`, `qty`, `leftLabel`, `extentFromRight`, `closeButton`, `cursor`; `setPrice`, `setOptions`, `setLeftLabel`, `setDragGhost`, `options()` |
| `PriceLevels` | `normal` | The ten **derived** reference levels (previous close, session high / low, last price, four extended-hours levels, bid, ask), each a line plus an axis tag. It computes its own prices from the bars and the viewport; you do not set them. | `levels` (per-kind `{ line, label, color, lineWidth, lineStyle, text, extentFromRight }`), `timezone`, `marketPhase`, `quote`; `setLevel`, `setOptions`, `setQuote`, `values()`, `available(kind)`, `level(kind)`. See below |
| `SeriesMarkers` | `normal` | Bar-anchored signal glyphs, visible-range culled and stacked per bar; markers with text above or below the bar (or on a pane edge) take lanes, so labels on neighbouring bars do not overlap: a label moves outward by at most five of its own heights, one that overlaps nothing does not move, and past five (a wide zoom) labels overlap on their bars as before. `MarkerShape` covers `arrowUp`/`arrowDown`, `circle`, `square`, `triangleUp`/`triangleDown`, `diamond`, `flag`, `text`, and the `labelUp`/`labelDown` text plates (tail pointing at the anchor price, `text` required). | `setMarkers(SeriesMarker[])`; renderers `drawShape`, `drawLabel`, `markerSizePx`, `effectiveMarkerPx` |
| `EventMarkers` | `normal` | Timeline badge strip with optional group filtering and clustering. | `setEvents`, `events`, `setGroups`, `groups`, `setGroupVisible`, `isGroupVisible`, `setOptions`, `options`, `detailsForHit` |
| `LogoWatermark` | `top` (option) | Corner brand mark with an optional hover-revealed label and link. | `src`/`image`, `position`, `height` (28), `margin` (12), `opacity` (0.7), `tint`, `label`, `padding`, `href`; `setOptions`, `href()` |
| `TextWatermark` | `bottom` (option) | A word stamped faintly across the plot to say what mode the chart is in, `Replay` being the case it exists for. Shrinks to fit a narrow pane, hit-tests to nothing, and is captured by `takeScreenshot()` because it is drawn on the canvas. | `text`, `fontSize` (64), `opacity` (0.08), `color`, `font`, `zOrder`; `setOptions` |
| `ReplayShade` | `top` (option) | Dims every bar after `index` and rules a line at the cut. Used while a replay start bar is being chosen: picking one while the next twenty bars are readable is picking on hindsight. Add one per pane, or a bright volume pane gives away what the price pane is hiding. | `index` (null draws nothing), `color`, `lineColor`, `lineWidth`, `lineVisible`; `setOptions` |
| `SessionShade` | `bottom` | Faint wash behind pre-open, post-close and extended-hours bars, from a session calendar's `phaseSpans`. Nothing is shaded until a host attaches it; a regular-hours feed, daily bars and views wider than 90 days shade nothing. `attachSessionShading(chart, options?)` adds one per chart to the price pane (anchored `primary-pane`, so it follows a moved price pane and fills a maximized one) and returns a `SessionShading` handle; attaching again merges the options and puts back a shade a host removed. | `calendar` (absent or null reads the chart's calendar each frame), `preColor`, `postColor`, `extendedColor` (null leaves that phase unshaded; defaults are faint theme tints, with the built-in theme's colour standing in for a named or hsl() theme colour), `visible`; `setOptions`, `options`; handle `setOptions`, `options`, `destroy` |
| `BuySellButtons` | `top` | Docked in-plot BUY / qty / SELL panel. | `id` (`trade`), `position` (`top-left`), `margin` (12), `qty`, `buyColor`, `sellColor`, `showPrices`, `scale` (0.6 to 1.5); `setPrices`, `setMark`, `setQty`, `setColors` |
| `PaneLegend` | `top` | Canvas-drawn legend row: swatch, title, params, live values, action buttons, and the status line. | `id`, `title`, `params`, `color`, `valueColor`, `row`, `actions`, `hidden`, `maximized`, `collapsed` (the collapse glyph points the way the pane will go), `font` (11), `left` (8), `top` (6), `statusLine` (per-field switches), `status` (host data or a per-frame getter); `setValue`, `setValues` (readings may carry `field: 'ohlc' \| 'change' \| 'volume'`), `setOptions`. See [settings-and-menus](settings-and-menus.md) |
| `TimeNavigator` | `top` (option) | Hover-revealed zoom, reset and step controls above the time axis. | Created by the chart itself from `ChartOptions.timeNavigator` (default `true`); `buttons`, `size` (26), `bottomMargin` (10), `revealHeight` (64), `labels`, `hints`, `showTooltip`. `TimeNavigatorAction` includes `'resetScale'`, placed between zoom and step controls by default, with the **Reset view** tooltip and `Home` hint. |
| `LinkCrosshair` | `top` | The crosshair a linked chart shows for a cursor in **another** chart: a vertical line only, at `LINK_CROSSHAIR_ALPHA` (0.55) of the pane's crosshair colour. A mirrored horizontal line would assert a price belonging to another instrument. Normally created for you by `LinkGroup`, one per pane. | `setIndex(index \| null)`, `index()`. See [chart-linking](chart-linking.md) |
| `IndicatorFill` | `bottom` | Two-tone band between two indicator `calc` columns (Ichimoku cloud, Keltner, a shaded overbought/oversold band), split at exact crossings. The columns need not be plotted. | `colorUp`, `colorDown`, `opacity` (0.12); `setPoints(FillPoint[])`, `setOptions`, `setVisible` |

Attachment:

```ts
// Every paneIndex below defaults to the price pane: slot 0, or wherever it sits
// on a chart built with movablePrimaryPane. Omit it for price-pane furniture.
chart.addPrimitive(primitive, paneIndex?);
chart.removePrimitive(primitive);

chart.addPriceLine({ price, color, lineWidth, dashed, id }, paneIndex?);    // returns PriceLine
chart.addEventMarkers(paneIndex?, { clustering: false });                   // returns EventMarkers
series.createMarkers();                                                     // returns SeriesMarkers, wired to that series
chart.tradeHost(paneIndex?);                                                // { addPrimitive, removePrimitive } for the trade tier
```

`PaneLegend` fits its row inside the plot, including hover actions and hit areas.
On narrow plots it shortens the title and omits whole label/value pairs; widening
the plot restores the original readings. `LegendValue.priority` selects which
readings survive first without changing their order. Series readings default to
1 and status metadata ranks lower. For example, give the close reading
`{ label: 'C', text: '123.45', field: 'ohlc', priority: 10 }` to retain it before
other prices. Status-line switches still apply before fitting. If only some
configured `actions` fit, the end of that list stays visible. Full-width rows keep
their existing content and ordering.

**`id` on `PriceLine` is not patchable.** `setOptions` accepts `Partial<Omit<PriceLineOptions, 'id'>>`, because swapping the routing handle mid-drag would strand the gesture.

## Timeline events and details

`ChartEvent` keeps the existing `time`, `type`, `label`, `id?` and `color?` fields
and adds optional `title`, `group` and `details`. `time` is finite UTC seconds.
Events between candles and inside session gaps use fractional chart time; stored
timestamps are never moved to a candle. `details` is a string or `ChartEventDetails`
with `summary?: string` and `fields?: readonly EventDetailField[]`, where each field
has text `label` and `value` strings. Events and nested detail fields are copied on
assignment and on return.

`ChartEventDetails.blocks?: readonly EventDetailBlock[]` carries rich
content as structure, never markup, so a feed's text cannot run as code:
`{ type: 'heading' | 'paragraph', text: EventDetailInline }` or
`{ type: 'list', items: readonly EventDetailInline[] }`. `EventDetailInline` is a
plain string or `readonly EventDetailSpan[]`, where a span is
`{ text, strong?, em?, href? }`. Blocks are copied all the way down, whatever
shape a feed sends, and a malformed block never makes `setEvents` throw. All
three types are exported from the base package.

```ts
details: {
  summary: 'Quarter in brief.',
  blocks: [
    { type: 'heading', text: 'Highlights' },
    { type: 'paragraph', text: [{ text: 'Margins ' }, { text: 'widened', strong: true },
      { text: ' Filing', href: 'https://example.com/filing' }] },
    { type: 'list', items: ['Volume up 9%', [{ text: 'Guidance kept', em: true }]] },
  ],
}
```

`EventGroup` is `{ id, label, parentId?, visible? }`. `setGroups` replaces the
hierarchy atomically, rejecting empty or duplicate IDs, missing parents and cycles.
`setGroupVisible(id, visible)` sets local visibility; a hidden ancestor hides every
descendant. `isGroupVisible(id)` reports effective visibility. Ungrouped events and
unconfigured group IDs remain visible. Event type filters are independent.

```ts
chart.setEventGroups([
  { id: 'calendar', label: 'Calendar' },
  { id: 'company', label: 'Company', parentId: 'calendar' },
]);
chart.setEvents([
  { id: 'sample-results', time: 1705315500, type: 'earnings', label: 'E',
    group: 'company', title: 'Sample results', details: 'Demonstration data.' },
]);
chart.setEventMarkerOptions({ clustering: true, clusterRadius: 18 });
chart.setEventGroupVisible('calendar', false);
chart.setEventGroupVisible('calendar', true);
chart.setEventOptions({ news: false });
```

`EventMarkersOptions` has `clustering` (default false) and `clusterRadius` (default
18, from 1 to 200 CSS pixels). The constructor and `setOptions` accept partial
options. Clusters split as zoom increases the members' pixel separation. Their
identity depends on their members, so panning and reordering distinct caller IDs
do not change a cluster handle while its membership is unchanged. The original
badge appearance and individual event IDs remain the default.

`EventMarkerDetails` is `{ id, cluster, events }`; every member is an independent
`ChartEvent` copy. `detailsForHit(id)` resolves the latest drawn layout and returns
`null` for a stale or unknown handle. Hit areas and drawing output stop at the plot
edges. `events()`, `groups()` and `options()` return independent snapshots.

Chart conveniences:

| API | Contract |
|---|---|
| `setEvents(events, paneIndex = primaryPaneIndex())` | Owns the event data and applies `setEventOptions` type filters. |
| `eventMarkers()` | Returns that chart-owned primitive, or null before data/options install it. |
| `setEventMarkerOptions(options)` | Configures clustering on the chart-owned strip. |
| `setEventGroups(groups)` / `setEventGroupVisible(id, visible)` | Configures its hierarchy and visibility. |
| `addEventMarkers(paneIndex = primaryPaneIndex(), options = {})` | Creates a separately owned primitive; the host supplies its data and filters. |

For chart-owned markers, `chart.on('event:click', handler)` delivers `ChartEventClick`,
which extends `EventMarkerDetails` with `point: { x, y }` and `paneIndex`. A custom
primitive resolves the existing `click` or `hover` ID through its own
`detailsForHit`. `events:change` lets hosts dismiss details after event data or
visibility changes. Chart data-context changes clear chart-owned events when the
symbol or exchange changes; an interval change alone retains them. The host owns
the calendar feed and supplies new instrument events.

### Widget details popup

The widget tier exports `EventDetailsPopup`, `EVENT_DETAILS_CSS`, `EventDetailsLoader`,
`EventDetailsLabels`, `EventDetailsPopupOptions` and `EventDetailAction`. `createWidget` opens details
for chart-owned markers by default. `WidgetOptions.eventDetails: false` disables
the popup; an options object customizes it:

```ts
const widget = createWidget(container, {
  eventDetails: {
    loadDetails: (event, { signal }) => calendarDetails.load(event.id, { signal }),
    labels: { title: 'Calendar details', close: 'Close' },
  },
});
```

`EventDetailsLoader` returns `Promise<ChartEventDetails | string | null>`.
`null` retains supplied details. Selection changes, close and destruction abort
the prior signal and invalidate late results, including loaders that ignore abort.
Errors retain supplied text and show a generic status. There is no built-in fetch
or live calendar service. Label demonstration data explicitly.

Custom hosts can use `new EventDetailsPopup(container, options)`, then
`open(details, { x, y })`, `close()` and `destroy()`. Anchor coordinates are CSS
pixels relative to that container. `element` exposes the dialog element.
Options accept `formatTime`, `labels`, `styleNonce`, a shared widget `overlays`
stack and `injectStyles: false` if the host bundles `EVENT_DETAILS_CSS` itself.
`EventDetailsLabels` supplies `title`, `close`, `events`, `loading`, `empty` and
`error`. Standalone time formatting defaults to `Asia/Kolkata`. All supplied
content is rendered as text. Cluster-member buttons, focus containment, focus
restoration, Escape/Close and pointer isolation are built in.

Rich blocks and host actions. The popup renders `details.blocks`
after the fields: `heading` as a subheading, `paragraph` as a paragraph, `list`
as a bulleted list, each built with elements and text nodes only, never
`innerHTML`. A span's `strong` and `em` wrap it in those elements; its `href`
becomes a link only for an absolute http or https URL without credentials (the
news reader's `safeNewsUrl` check), opened in a new tab with
`rel="noopener noreferrer"` and no referrer. `javascript:`, `data:`,
`vbscript:`, relative and protocol-relative values show the span's text alone.
A block of any other shape, or one that renders no text, is skipped.

`EventDetailsPopupOptions.actions(event)` returns `readonly EventDetailAction[]`
(`{ label, run(event) }`) for the event on show, asked each time a member is
selected. The buttons sit bottom right; a label is text. A press closes the popup
first, so whatever the action opens is not closed under it, then calls `run`
with a copy of the event. No actions, no buttons.

```ts
const widget = createWidget(container, {
  eventDetails: {
    actions: event => event.type === 'earnings'
      ? [{ label: 'Add alert', run: shown => openAlertAt(shown.time) }]
      : [],
  },
});
```

## `PriceLevels`: the reference-level family

```ts
import { PriceLevels, PRICE_LEVEL_KINDS, computePriceLevels } from 'openalgo-charts';

const levels = new PriceLevels({
  levels: {
    previousClose: { line: true, label: true },
    sessionHigh: { line: true, label: false },     // line on the plot, no tag on the axis
    sessionLow: { line: false, label: false },
  },
  timezone: 'America/New_York',
});
chart.addPrimitive(levels);   // the price pane, wherever it sits

levels.setLevel('previousClose', { color: '#8b95a8', lineStyle: 'dashed' });
levels.values().previousClose;      // number | null, as of the last frame
levels.available('bid');            // false until a quote is fed
```

`PriceLevelKind` is `'previousClose' | 'sessionHigh' | 'sessionLow' | 'lastPrice' | 'preMarketOpen' | 'preMarketClose' | 'postMarketOpen' | 'postMarketClose' | 'bid' | 'ask'`, and `PRICE_LEVEL_KINDS` is that list in the order a settings panel should show it.

**A level's line and its axis tag are two flags in one group.** `line` draws across the plot, `label` draws the tag on the price axis, and neither implies the other. Do not model them as two separate menus: that is exactly how a tag ends up on the axis for a line nobody is drawing.

Defaults: `previousClose`, `sessionHigh` and `sessionLow` are on (dashed); every other kind is off. `lastPrice` is off **because the core already draws it** (see below).

| Option | Notes |
|---|---|
| `levels` | Per-kind partial style, merged over the defaults. |
| `timezone` | IANA name, used only for the calendar fallback when the bars show no readable session break. |
| `marketPhase` | `(bar) => 'pre' \| 'regular' \| 'post' \| null`. **Required for the four extended-hours levels**: the OHLC feed carries no phase, and the primitive will not guess one. |
| `quote` | `{ bid?, ask? }` or a function returning one, read each frame. **Required for bid and ask.** `setQuote(null)` clears it. |

### What the numbers mean

- **The session comes from the bar gaps**, through `sessionStartFlags`, not from a calendar midnight. The calendar is the fallback for a series with no readable break, which is the right answer for daily bars.
- **The session in view is the one containing the viewport's right edge** (`dataLayer.indexToTimeFloat(timeScale.visibleRange().to)`), so panning back through history moves previous close back with it. The right-offset gap past the last bar still resolves to the newest session.
- **Previous close is the previous session's last *traded* close**, walked back over a whitespace tail so a halted closing minute does not blank the level.
- **Session high and low ignore whitespace**, because `NaN` loses every comparison silently.
- **A level with no data is `null`, never `0`.** Nothing is drawn for it. `available(kind)` is the host's signal to render that control **disabled with its state visible**, not to hide it: "no previous session yet" is information, an absent checkbox is not.
- **There is no `autoscaleInfo`.** A previous close a gap away from the session in view would stretch the range and flatten the bars the chart is for. A reference level that scrolls off the top is the lesser harm, and it is what the last-price line already does.

### Do not double-draw the last price

The pane already draws the last-price line and tag from `SeriesStyle.priceLineVisible` / `lastValueVisible`. Two owners would paint it twice, so the `lastPrice` level defaults to off and two helpers translate between the shapes:

```ts
import { lastPriceLevelFromSeriesStyle, seriesStyleForLastPriceLevel } from 'openalgo-charts';

const style = chart.primarySeriesInfo()!.style;
const row = lastPriceLevelFromSeriesStyle(style);            // { line, label } for your menu
chart.primarySeries()!.applyOptions(seriesStyleForLastPriceLevel({ line: true, label: false }));
```

Present it as one more row in the same family; write the answer back to the series it belongs to.

### The numbers without a canvas

`computePriceLevels({ bars, anchorTime, timezone, marketPhase, quote })` is pure and exported, returning the same `PriceLevelValues` the primitive computes. Use it for a readout, a test, or an alert check with no chart attached. `values()` on the primitive is the last frame's answer, so every level reads `null` before the first frame.

Session boundaries are cached per bar array (a `WeakMap` keyed on identity plus length and the first and last timestamp), because boundaries cannot move under an intra-bar tick. Replacing the array with `setData` invalidates it by identity.

## A custom primitive

Complete, HiDPI-correct, and hit-testable:

```ts
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit } from 'openalgo-charts';

class SupplyZone implements IPrimitive {
  private host: PrimitiveHost | null = null;
  private y0 = 0;                       // last painted bounds, media px
  private y1 = 0;

  constructor(private lo: number, private hi: number, private id = 'supply-zone') {}

  attached(host: PrimitiveHost) { this.host = host; }
  detached() { this.host = null; }
  zOrder() { return 'bottom' as const; }

  // Keep the band on screen even when price leaves it.
  autoscaleInfo() { return { min: this.lo, max: this.hi }; }

  setRange(lo: number, hi: number) {
    this.lo = lo; this.hi = hi;
    this.host?.requestUpdate();         // schedules a repaint; takes no arguments
  }

  draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext) {
    const d = rc.dpr;
    this.y0 = rc.priceScale.priceToY(this.hi);   // media px, remembered for hitTest
    this.y1 = rc.priceScale.priceToY(this.lo);
    const w = rc.plotWidth * d;                   // media -> device

    ctx.save();
    ctx.fillStyle = rc.hoverId === this.id ? 'rgba(239,83,80,0.22)' : 'rgba(239,83,80,0.12)';
    ctx.fillRect(0, this.y0 * d, w, (this.y1 - this.y0) * d);

    ctx.strokeStyle = '#ef5350';
    ctx.lineWidth = Math.max(1, Math.round(d));
    ctx.beginPath();
    for (const y of [this.y0, this.y1]) {
      const yy = Math.round(y * d) + 0.5;         // crisp 1px line
      ctx.moveTo(0, yy); ctx.lineTo(w, yy);
    }
    ctx.stroke();

    ctx.font = `${11 * d}px system-ui, sans-serif`;
    ctx.fillStyle = '#ef5350';
    ctx.textBaseline = 'top';
    ctx.fillText(rc.priceScale.format(this.hi), 6 * d, this.y0 * d + 4 * d);
    ctx.restore();
  }

  // x / y arrive in MEDIA px relative to the plot. No dpr here.
  hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    if (x < 0 || x > rc.plotWidth) return null;
    if (y < this.y0 || y > this.y1) return null;
    return { externalId: this.id, zOrder: 'bottom', distance: 0, cursor: 'pointer' };
  }
}

chart.addPrimitive(new SupplyZone(24100, 24250));   // the price pane
chart.subscribeClick((id) => { if (id === 'supply-zone') openZoneEditor(); });
```

## A custom chart type

`registerChartType(type, entry)` adds a per-bar renderer the core dispatches to; there is no core change and no `switch`.

```ts
import { registerChartType } from 'openalgo-charts';

registerChartType('range-band', {
  defaultStyle: { lineWidth: 1.5, color: '#4f8cff' },
  isPriceSeries: true,          // its last close drives the last-price line and tag
  draw: (ctx, items, toY, barSpacing, dpr, style, rc) => {
    const w = Math.max(1, Math.floor(barSpacing * 0.7)) * dpr;
    ctx.fillStyle = style.color ?? rc.theme.lineColor;
    for (const { x, bar } of items) {
      const yh = toY(bar.high) * dpr;             // toY returns MEDIA px
      const yl = toY(bar.low) * dpr;
      ctx.fillRect(Math.round(x * dpr - w / 2), yh, w, Math.max(1, yl - yh));
    }
  },
  // Per-bar autoscale contribution for this series' own price scale.
  extents: (bar) => ({ min: bar.low, max: bar.high }),
});

chart.addSeries('range-band').setData(bars);
```

`RendererEntry` in full: `defaultStyle: SeriesStyle`, `isPriceSeries: boolean`, `connectsBars?: boolean`, `draw(ctx, items, toY, barSpacing, dpr, style, rc)`, `extents(bar, style)`. `items` is `DrawItem[]`, each `{ x: number /* bar centre, media px */, bar: Bar, prevClose?: number, edgeX?: number }`, already culled to the visible range. Set `connectsBars: true` (since 2.5.9) for a renderer that draws a segment from each bar to the next (the built-in line, line-markers, step, area, hlc-area and baseline do, and so does the transform tier's kagi): its `items` then also carry the series' nearest bar beyond each edge of the view, off screen, so the segment crossing an edge is drawn. Without it a sparse line loses the part entering from off screen.

Those two neighbours, and only they, carry `edgeX` (since 2.5.9): the x (media px) of the plot edge between them and the bars in view, `0` on the left and the plot width on the right. A neighbour can sit millions of pixels away (a level held for a session on an axis of five-second bars), so cut the segment to it at `edgeX`, plus whatever your stroke needs, rather than stroke it all the way out: a renderer that builds its own geometry (a quad per dash, a vertex per step) would otherwise pay for the whole off-screen length on every frame. Draw nothing of the neighbour's own (a dot, a body); it is there for the segment. A neighbour is the series' very next bar, value or not: when it, or the bar in view next to it, has no value (a whitespace item or a study's NaN), join nothing across it. Autoscale still reads only the bars in view, through `extents`. The built-in renderers also keep a dashed line's pattern anchored to the first bar in view, so drawing the neighbours moves no dash that was already on screen. A custom type is never reduced by the level of detail (`conflate`), even one registered under a built-in name; the built-in renderers are below one CSS px per bar. The array and its objects belong to the pane, which rewrites them in place the next time it draws the series: copy anything kept past that. `rc` is `{ plotHeight, maxVolume, theme }`, media px, the visible-window volume peak, and the palette.

`registeredChartTypes()` lists every registered id. `'point-figure'` and `'kagi'` live in the transform tier and only resolve once `openalgo-charts/transform` is imported.

**Write a chart type only when the thing is one mark per bar on the time axis, driven by `Bar` fields, and it should feed autoscale through `extents`.** Everything else is a primitive: zones spanning arbitrary prices, bands between two other series, chrome and controls, anything hit-testable, anything anchored to `{ time, price }` rather than to a bar, and anything that must sit on the overlay canvas.

## Foot-guns

**A primitive that draws nothing until it has data must still return a real `zOrder()`.** The pane calls it on every frame for every primitive, before `draw`.

**`hitTest` geometry must come from the last `draw`, not from a fresh computation.** If you recompute layout in `hitTest` you will drift from what is on screen the moment a scale changes between frames.

**`rc.theme.background` can be the string `'transparent'`.** Built-ins branch on it (`PriceLine`, `PaneLegend`) rather than filling with it; a plate filled with `'transparent'` disappears against a busy chart.

**`rc.bars()` returns the live array the data layer holds.** Treat it as read-only, and guard the call, a synthetic render context may not supply it.

**`series.update()` schedules a `Full` repaint** of the panes it changes (the series' own pane and those of the studies computed from it; every pane when it appends a bar), which re-runs every `autoscaleInfo()` and every `draw` on them. Cache anything expensive across frames.

Related: [core-api](core-api.md) (`addPrimitive`, invalidation levels, the event bus), [chart-types](chart-types.md) (the built-in renderers), [drawing-tools](drawing-tools.md) (`DrawingLayer`, a primitive built on this contract), [trading](trading.md) and [trade-tier](trade-tier.md) (order lines and `tradeHost`), [indicators](indicators.md) (`IndicatorFill`, `PaneLegend`), [events-and-state](events-and-state.md) (click and drag routing), [scales-and-panes](scales-and-panes.md) (which scale a primitive sees).

## Anchoring to the chart instead of a pane (1.6.0)

```ts
chart.addPrimitive(mark, { anchor: 'chart-bottom' })   // or 'chart-top', or 'primary-pane'
```

Pass a placement instead of a pane index and the engine re-homes the primitive whenever a
pane is added, removed, moved, maximized or collapsed. Use it for anything that is chart furniture
rather than pane furniture: a watermark, a corner clock, a brand mark. `'chart-bottom'`
resolves to the lowest open pane, so a collapsed bottom pane, which draws only its legend
row, hands the primitive to the pane above it. `'chart-top'` is the top pane with a share of
the chart. `'primary-pane'` follows the price pane to whatever slot it is moved to
(`setPrimaryPaneIndex`), and the pane maximized over it while it is hidden: use it for
furniture that describes the price, such as a symbol badge. The chart's own background
text and study count use it. `addPrimitive(p)` with no second argument is a plain pane
primitive on the price pane at the time of the call, and moves with that pane.

Maximize is the reason this exists rather than a `paneAdded` listener. It HIDES the other
panes, so a primitive pinned to the price pane disappears with it instead of merely sitting in the
wrong place, and no amount of host bookkeeping fixes that from outside.

`removePrimitive` also clears the anchor registration, so a removed primitive stays removed;
before that was wired, the next pane change resurrected it.

## Chart branding and optional text watermark (2.1.9)

`createChart` now owns one OpenAlgo corner logo by default, including inside `createWidget`.
Do not add the old manual default `LogoWatermark` as well. Use `branding: false` when a
host deliberately owns all branding, or `branding: { src, label, href }` for a custom
mark. `chart.setBranding(options)` changes it live and `chart.brandingOptions()` returns
its current options or false. The engine handles completed clicks on its owned mark;
manually attached `LogoWatermark` instances still use host click handlers.

The separate text watermark defaults off. `ChartWatermarkOptions` extends the optional
`TextWatermarkOptions` fields with `visible?: boolean`. Blank `text` uses the current
`chart.getDataContext()` symbol and interval, so setDataContext must follow instrument
changes. Custom text stays custom across context changes. Do not persist generated symbol
text as a user's custom string.

```ts
const chart = createChart(el, { watermark: false })
chart.setDataContext({ symbol: 'NIFTY', exchange: 'NSE', interval: '5m' })
chart.setWatermarkOptions({ visible: true })
chart.setWatermarkOptions({ text: 'Research', opacity: 0.08, fontSize: 64 })
chart.setWatermarkOptions({ text: '' })
chart.setWatermarkOptions(false)
const preferences = chart.watermarkOptions()
```

The Appearance schema exposes `watermark.visible`, `watermark.text`, `watermark.color`,
`watermark.opacity` and `watermark.fontSize`. Chart state saves these preferences, not
host branding URLs or image objects. Old layouts default off. Keep the independent Replay
mode mark: switching the optional watermark off must not hide the replay indicator.

Validate actual desktop/mobile pixels and PNG/SVG export, both themes, pane add/maximize,
context changes, restore/cancel and logo tap-versus-drag behavior. Background text must
not intercept drawing/navigation or spill over the price axes. A custom image source
still has the host's loading/CORS responsibilities; the default vector glyph loads no
external image. Host UI supplies keyboard-accessible link access without covering chart
input targets.
