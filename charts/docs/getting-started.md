# Getting started

OpenAlgo Charts is a dependency-free, canvas-based financial charting engine.
The base engine is **95.04 kB Brotli**; all nine tiers total **256.08 kB Brotli**,
measured with `size-limit` on the 2.5.2 build. Optional tiers are separate imports.

## Install

```bash
npm install openalgo-charts
```

## Your first chart

```ts
import { createChart } from 'openalgo-charts';

const container = document.getElementById('chart');
if (!container) throw new Error('Chart container not found');
const chart = createChart(container);
const series = chart.addSeries('candlestick');
series.setData([
  { time: 1705286700, open: 100, high: 101, low: 99.5, close: 100.6, volume: 1200 },
  { time: 1705286760, open: 100.6, high: 101.4, low: 100.2, close: 101.1, volume: 900 },
  // ...
]);
```

Give the chart container a non-zero height, for example `height: 400px`, before
creating it. Call `chart.destroy()` when the view is removed.

Time is **UTC seconds** internally. Feed adapters convert broker formats at the
edge (IST date strings, epoch milliseconds); see the OpenAlgo adapter below.

## Live updates

```ts
import { CandleBuilder } from 'openalgo-charts';

const builder = new CandleBuilder({ intervalSec: 60, volumeMode: 'ltq-sum' });
builder.seed(lastHistoricalBar);

// Your market-data adapter calls this callback for each trade tick.
function onTradeTick({ price, ltq, timeSec }: { price: number; ltq?: number; timeSec: number }) {
  const u = builder.onTick({ time: timeSec, price, ltq });
  if (u) series.update(u.bar); // mutates the last candle or appends a new one
}
```

For production history loading, paging, reconnects and partial-bar repair, use
the shared [Data Loading controller](https://marketcalls.github.io/openalgo-charts/docs/data-loading/).
`ltq-sum` requires actual trade quantities; choose `day-delta` for cumulative
day volume, and configure the instrument session anchor. A tick without OI must
not manufacture an observation. See [open interest](open-interest.md).

## Loadable tiers

Only pay for what you use: each of the nine tiers is a separate entry point.

| Import | Contents |
|---|---|
| `openalgo-charts` | base chart engine, registries, feeds, alerts, replay, comparisons, appearance linking, grouped timeline events, chart state and exports |
| `openalgo-charts/trade` | order/position/bracket lines, DOM ladder, order engine |
| `openalgo-charts/transform` | Renko, Range, Point &amp; Figure, Kagi, Line Break, Heikin Ashi |
| `openalgo-charts/profile` | Volume Profile, Market Profile (TPO), Footprint, order flow |
| `openalgo-charts/indicators` | 112 built-in indicators (SMA/EMA/MACD/Bollinger/RSI/ADX/...) + the Tier-2 contract |
| `openalgo-charts/draw` | 87 drawing tools, including Anchored VWAP and fixed-range Volume Profile, a headless controller and opt-in drawing linking |
| `openalgo-charts/webgl` | the WebGL2 series backend behind `renderer: 'auto'` |
| `openalgo-charts/workspace` | portable layouts, indicator templates, revisioned catalogs and asynchronous storage |
| `openalgo-charts/widget` | the chart with its chrome in one `createWidget` call: top bar, drawing rail, status line, dialogs, shortcuts, persistence. The only tier that supplies application controls |

## OpenAlgo data

```ts
import { OpenAlgoDataFeed } from 'openalgo-charts';

const feed = new OpenAlgoDataFeed({ baseUrl: 'http://127.0.0.1:5000', apiKey: 'YOUR_KEY' });
// from/to are UTC seconds; the adapter converts them to IST YYYY-MM-DD for OpenAlgo.
const day = 86400;
const bars = await feed.getBars({
  symbol: 'RELIANCE', exchange: 'NSE', interval: '1m',
  from: Math.floor(Date.now() / 1000) - 7 * day, to: Math.floor(Date.now() / 1000),
});
series.setData(bars);
```

Live LTP / Quote / Depth come from the WS adapter. Feed its LTP ticks through a
`CandleBuilder` and call `series.update()`:

```ts
import { OpenAlgoWsFeed, CandleBuilder } from 'openalgo-charts';
const ws = new OpenAlgoWsFeed({ url: 'ws://127.0.0.1:8765', apiKey: 'YOUR_KEY' });
const liveBuilder = new CandleBuilder({ intervalSec: 60, volumeMode: 'ltq-sum' });
const lastBar = bars[bars.length - 1];
if (lastBar) liveBuilder.seed(lastBar);
const stopTicks = ws.onLtp((event) => {
  if (event.symbol !== 'RELIANCE' || (event.exchange && event.exchange !== 'NSE')) return;
  const time = event.timeSec > 0 ? event.timeSec : Math.floor(Date.now() / 1000);
  const update = liveBuilder.onTick({ time, price: event.ltp, ltq: event.ltq });
  if (update) series.update(update.bar);
});
ws.subscribe('LTP', 'RELIANCE', 'NSE');
ws.connect();

// Call when this view is removed or the source is replaced.
function disposeLiveFeed() {
  stopTicks();
  ws.close();
}
```

The chart's market data depends only on the `DataFeed` interface, so any broker
can be wired with a small adapter. Order entry is a separate contract: the trade
tier's `OrderFeed`, which its `OrderEngine` drives, and which a chart without
trading never needs. Verify the exact REST paths against your running OpenAlgo
build before production use.

See [guides.md](./guides.md) for chart types, trading, profiles, and writing
custom chart styles / primitives, [widget.md](./widget.md) for the one-call terminal,
and [migrating-to-2.md](./migrating-to-2.md) if you are coming from 1.9.x. Runnable
demos live in [`../examples`](../examples/index.html).

## Current host guides

- [Instrument metadata](instruments.md): sessions, intervals, precision and quantity units.
- [Open interest](open-interest.md): observations, gaps and the three studies.
- [Trader alerts](https://marketcalls.github.io/openalgo-charts/docs/alerts/): standalone controller, restoration and host delivery.
- [Workspaces](workspaces.md): portable layouts, templates and asynchronous storage.
- [Chart data export](chart-data-export.md): loaded/revealed rows and host-owned CSV delivery.
- [Drawing tools](https://marketcalls.github.io/openalgo-charts/docs/drawing-tools/): time-anchored analysis drawings, volume requirements and editing.
- [Chart linking](https://marketcalls.github.io/openalgo-charts/docs/chart-linking/): independent appearance and drawing switches, with instrument identity checks.
- [Timeline events](https://marketcalls.github.io/openalgo-charts/docs/events/): host-supplied groups, clustering and widget details.
