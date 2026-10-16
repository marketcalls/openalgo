# Guides

The website has complete guides for [alerts](https://marketcalls.github.io/openalgo-charts/docs/alerts/),
[open interest](https://marketcalls.github.io/openalgo-charts/docs/open-interest/),
[named workspaces](https://marketcalls.github.io/openalgo-charts/docs/workspaces/), and
[chart data export](https://marketcalls.github.io/openalgo-charts/docs/chart-data-export/).

## Chart types

Every chart type is a registry descriptor; `addSeries(type)` selects it:

```ts
chart.addSeries('candlestick'); // or: hollow-candle, volume-candle, bar, high-low,
                                // line, line-markers, step, area, hlc-area, baseline, column
```

Family-B (price-driven) types come from the transform tier: run a transform,
then plot the result:

```ts
import { runTransform, RenkoTransform } from 'openalgo-charts/transform';
const bricks = runTransform(new RenkoTransform({ boxSize: 5 }), bars);
chart.addSeries('candlestick').setData(bricks); // Renko renders as candles
```

Or have the chart apply the transform itself, to the bars you feed
it, live: the series keeps taking your bars, and bricks form as ticks land.

```ts
import 'openalgo-charts/transform';
const series = chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: 5 } } });
series.setData(bars);   // your own bars
series.update(bar);     // a tick moves the forming brick
```

Point &amp; Figure and Kagi have dedicated renderers registered when you import the
transform tier:

```ts
import { runTransform, PointFigureTransform } from 'openalgo-charts/transform';
const cols = runTransform(new PointFigureTransform({ boxSize: 1, reversal: 3 }), bars);
chart.addSeries('point-figure').setData(cols); // columns carry their own boxSize
```

## Multi-pane (volume / indicators)

```ts
chart.addSeries('histogram', { paneIndex: 1 }).setData(volumeBars);
```

Panes share one time axis, so they stay perfectly aligned bar-for-bar.

## Markers, events, indicators

```ts
const markers = series.createMarkers();
markers.setMarkers([{ time, position: 'belowBar', shape: 'arrowUp', size: 'medium', color: '#26a69a', text: 'BUY' }]);

chart.addEventMarkers().setEvents([{ time, type: 'earnings', label: 'E' }]);

import { emaSeries } from 'openalgo-charts';
chart.addSeries('line', { style: { color: '#f0a020' } }).setData(emaSeries(bars, 21));
```

Built-in indicators (EMA, RSI, ATR, Supertrend) mirror `openalgo.ta` semantics
and return plottable bars (warmup slots carry NaN, which the line renderer skips):

```ts
import { rsiSeries, supertrendSeries } from 'openalgo-charts';

// Supertrend overlay: green uptrend / red downtrend (direction -1 = up, +1 = down)
const { up, down } = supertrendSeries(bars, 10, 3);
chart.addSeries('line', { style: { color: '#26a69a', lineWidth: 2 } }).setData(up);
chart.addSeries('line', { style: { color: '#ef5350', lineWidth: 2 } }).setData(down);

// RSI(14) in its own pane with 70/30 guides
chart.addSeries('line', { paneIndex: 2, style: { color: '#e0b020' } }).setData(rsiSeries(bars, 14));
chart.addPriceLine({ price: 70, color: '#ef5350', lineWidth: 1, dashed: true, id: 'rsi-70' }, 2);
chart.addPriceLine({ price: 30, color: '#26a69a', lineWidth: 1, dashed: true, id: 'rsi-30' }, 2);
```

## OHLC legend / tooltip

`subscribeCrosshairMove` fires the hovered bar of the primary price series on
every cursor move (and all-null fields on pointer-leave), so the host renders the
legend or floating tooltip in its own DOM:

```ts
chart.subscribeCrosshairMove((e) => {
  const bar = e.bar ?? bars[bars.length - 1]; // fall back to the latest bar
  legend.textContent = bar
    ? `O ${bar.open} H ${bar.high} L ${bar.low} C ${bar.close}`
    : '';
  // e.point gives container-relative px to position a floating tooltip
});
```

Linked charts also call this subscriber with `source: 'linked'`, their own mapped
bar, and null pointer coordinates. A linked readout never emits `crosshair:move`
on the event bus, so it cannot become drawing input or a synchronization echo.
Native pointer hover takes precedence. Clearing or disabling the link restores
the latest-bar fallback. Study legends retain the selected candle through live
recalculation and history prepends.

For a host-owned readout, retain the selected bar's timestamp and resolve it
against the displayed series after a data update. Avoid replacing it with the
latest raw bar on every tick, especially while replay owns a truncated series.

## Chart trading

```ts
import { OrderEngine } from 'openalgo-charts/trade';

const eng = new OrderEngine({ feed, constraints: { tickSize: 0.05, priceBand, freezeQty },
  armed: false, gate: (req) => confirm(`Place ${req.side} ${req.qty}?`), mode: 'analyzer' });

await eng.placeMarket('RELIANCE', 'BUY', 10);     // one-click

// Keep draft prices out of the broker API until a valid release.
const draftPrices = new Map<string, number>();
chart.on('drag:cancel', payload => {
  const { id } = payload as { id: string };
  if (draftPrices.delete(id)) restoreOrderPreview(id);
});
chart.subscribeDrag((id, price) => {
  const line = orderLines.get(id);
  if (!line) return;
  draftPrices.set(id, price);
  line.setPrice(price);
}, (id) => {
  const price = draftPrices.get(id);
  draftPrices.delete(id);
  if (price === undefined) return;
  eng.requestModify(clientId(id), price);
  void eng.commitModify(clientId(id));
});
```

`requestModify` can send immediately; it is not a preview API. The line map,
ID mapping and cancellation rollback above are host-owned. See the
[trading guide](https://marketcalls.github.io/openalgo-charts/docs/trading/#drag-to-modify)
for the release path. `AlertController` threshold edits are separate and never
send a broker order by themselves.

The engine enforces tick-size snapping, price-band/freeze validation,
client-token idempotency, OCO (one fill cancels the peer), reconnect to stale, and
an arm/confirm gate. Use `analyzer` mode to route to a sandbox.

## Profiles &amp; order flow

```ts
import { computeVolumeProfile, HorizontalProfile } from 'openalgo-charts/profile';
const vp = computeVolumeProfile(bars, 0.05, 0.7);
chart.addPrimitive(new HorizontalProfile({ buckets: vp.buckets, poc: vp.poc, vah: vp.vah, val: vp.val, width: 140, side: 'right', barColor: '#345', vaColor: '#456' }));
```

Footprint / order flow need classified trade data (bid vs ask); see the
data-dependency note in `footprint.ts`.

## Writing a custom chart style

```ts
import { registerChartType } from 'openalgo-charts';
registerChartType('my-style', {
  defaultStyle: { color: '#fff' },
  isPriceSeries: true,
  draw: (ctx, items, toY, barSpacing, dpr, style) => { /* ... */ },
  extents: (bar) => ({ min: bar.low, max: bar.high }),
});
```

## Writing a custom primitive

Implement `IPrimitive` (`zOrder`, `draw`, optional `hitTest` / `autoscaleInfo` /
lifecycle) and attach it with `chart.addPrimitive(primitive, paneIndex)`. This
is the same API the trade layer, markers, and profiles are built on.

## Themes

Pass a full palette: `lightTheme` (the bare-chart default), `darkTheme`, or your own `ChartTheme`:

```ts
import { createChart, lightTheme } from 'openalgo-charts';
const chart = createChart(el, { theme: lightTheme });
// or a custom palette: { ...darkTheme, upColor: '#00b386', background: '#0b0f17', ... }
```

The theme drives chrome (background/grid/axes/crosshair), series defaults
(up/down, line, area gradient, last-price tag), and the trade layer
(buy/sell/profit/loss). Per-series `style` overrides always win over the theme.

## Gradient area / baseline

`area` and `baseline` use real vertical gradients. Colours come from the theme
or per-series style:

```ts
chart.addSeries('area', { style: { areaTopColor: 'rgba(79,140,255,0.5)', areaBottomColor: 'rgba(79,140,255,0)' } });
```

## Axis-drag rescale

- **Wheel**: zoom both axes around the cursor. The zoom is eased in log space over a
  few frames (`animZoom`, on by default; `false` restores the single-frame step), and
  `zoomAnchor: 'right'` pins the latest bar instead of the cursor.
- **Double-click**: reset view by default; `doubleClick: 'maximize'` toggles the pane under
  the pointer to the whole stack, `'none'` leaves it to the host's `dblclick` listener.
- **Drag the price (Y) axis** vertically: up expands, down compresses the price scale
  (switches that pane to manual scale).
- **Drag the time (X) axis** horizontally: left expands (wider bars), right compresses.
- **Drag the chart**: pressing and holding empty plot space shows a grabbing hand.
  Mouse and pen movement pans time and price by default and stops immediately on
  release. Choose `navigation.mousePan: 'horizontal'` to pan only time and preserve
  price autoscale. Touch flicks retain kinetic scrolling.
- **Reset view** in the bottom controls, or double-click with the default action:
  restore `navigation.defaultVisibleBars` and price autoscale. The bar count is
  saved in chart settings; `0` fits all loaded history. `chart.fitContent()` always
  fits all loaded bars explicitly.

## Tick aggregation &amp; live orderflow

Aggregate raw trade ticks into bars by clock interval, tick count, or volume:

```ts
import { TickBarAggregator } from 'openalgo-charts';
const agg = new TickBarAggregator({ mode: 'volume', perBar: 5000 }); // or {mode:'ticks',count:100} / {mode:'interval',seconds:60}
ws.onTrade(t => { const u = agg.onTick({ time: t.timeSec, price: t.price, qty: t.qty }); if (u) series.update(u.bar); });
```

For footprint/orderflow, feed **classified** ticks (bid vs ask) to the streaming
aggregator:

```ts
import { FootprintAggregator } from 'openalgo-charts/profile';
const fa = new FootprintAggregator({ mode: 'interval', seconds: 60 }, 0.05);
ws.onTrade(t => { const u = fa.onTick({ time: t.timeSec, price: t.price, qty: t.qty, side: t.atBid ? 'bid' : 'ask' });
  footprint.setBars(/* accumulate u.bar */); });
```

Tick-count and volume bars (and footprint) require real trade ticks: OHLCV
alone can't produce them, and bid/ask classification needs a live feed or a
tick-recorder backend.

## Performance

Enable conflation for very large, zoomed-out datasets:

```ts
createChart(el, { conflate: true, conflationFactor: 1 });
```

Bars below ~0.5px are merged OHLC-preserving (open=first, close=last, high=max,
low=min, volume=sum), never a lossy average. Conflation lowers drawing work but
does not limit retained history. For a chart that stays open through a market
session, use a bounded source window, explicit feed cleanup, and a measured
canvas-pixel budget. See the [Performance & Operations guide](https://marketcalls.github.io/openalgo-charts/docs/performance-and-operations/).

## Touch & accessibility

Touch gestures work out of the box (`touch-action: none` on the container):
single-finger drag pans, **two-finger pinch zooms**, and a two-finger drag pans
both axes.

The chart container is focusable (`role="application"`, `tabindex=0`, an
`aria-label`, override via `createChart(el, { ariaLabel })`) with a polite
`aria-live` summary (bar count + latest price) that updates on data changes.
Keyboard when focused: **Left/Right** pan time, **Up/Down** pan price, **+/-** zoom,
**Home/0** reset (`chart.resetScale()`).
