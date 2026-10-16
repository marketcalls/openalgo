---
name: openalgo-charts
description: >-
  Use when building, configuring, extending or debugging openalgo-charts in a
  consumer app or the source repository, including chart navigation, drawing
  tools, indicators, profiles, live feeds, replay, widgets and framework hosts.
---

# OpenAlgo Charts skill

`openalgo-charts` is a from-scratch, dependency-free HTML5-canvas charting engine: a canvas rendering pipeline with vector export, no DOM per bar, nine bundle entry points, zero runtime dependencies.

Works the same whether the project is a downstream npm consumer app or an upstream `openalgo-charts` source checkout. Detect which one you are in and resolve every API name from whatever typings are locally available.

## Source lookup order

Do not assume you are inside the upstream source repository.

1. In a consumer app, inspect the installed package first:
   - `node_modules/openalgo-charts/package.json` for the actual version.
   - `node_modules/openalgo-charts/dist/index.d.ts` for the base API surface, and `dist/{trade,draw,indicators,transform,profile,webgl,widget,workspace}/index.d.ts` for each tier.
2. In the upstream repo, inspect `dist/index.d.ts` first, then `src/` if generated output is unavailable.
3. `ARCHITECTURE.md` and `website/pages/docs/*.mdx` are supporting evidence, but local typings win when they disagree.

Verify before answering (copy-paste):

```sh
node -p "require('./node_modules/openalgo-charts/package.json').version"
rg -n "createChart|addSeries|addIndicator|DrawingController|OrderEngine" node_modules/openalgo-charts/dist/index.d.ts
# upstream checkout instead of a consumer app:
rg -n "createChart|addSeries|addIndicator" dist/index.d.ts src/index.ts
# which tiers does this project actually load?
rg -n "from 'openalgo-charts" src app
```

If the relevant file is unavailable, say what could not be verified. Do not invent option names, methods, exports, event names, or indicator ids.

## Mental model

Eight layers, in dependency order. Most bugs come from confusing one for another.

1. **Chart** - `createChart(container, options)` returns a `Chart`. One chart per container element. It owns everything below.
2. **DataLayer** - one per chart. Merges every series by time onto a single shared **logical index** space `0..N-1`. This is the load-bearing idea; see rule 2 below.
3. **Scales** - `chart.timeScale` maps logical index to x; each pane's `PriceScale` maps price to y. Panes autoscale independently.
4. **Panes** - vertically stacked drawing regions, each with two canvases (base + overlay) and up to three price scales (`'right'`, `'left'`, `''` overlay).
5. **Series** - `chart.addSeries(type, options)` returns a `SeriesApi`. The type names an entry in the chart-type **registry**; the core never switches on type.
6. **Registries** - chart types, indicators, and drawing tools are all descriptors in a Map. Adding one is a registration, never a core change.
7. **Primitives** - the extension point. Anything that draws but is not a series: price lines, markers, legends, profiles, trading pills, drawings.
8. **Tiers** - `indicators`, `draw`, `transform`, `profile`, `trade`, `webgl` are separate bundles that register what they add on import (the draw tier into its own tool registry, the others into the base engine's registries); `widget` sits above them all and is the one tier that builds DOM.

## Install and tiers

```bash
npm install openalgo-charts
```

Import only what you use. Each tier is a separate entry point, so a feature you do not load costs zero bytes. The workspace tier is pure configuration and persistence; it registers nothing.

| Import | Contents | Brotli limit |
|---|---|---|
| `openalgo-charts` | Engine, 13 chart types, panes and scales, primitives, registries, chart state and settings schema, market replay, symbol comparison, chart linking with appearance adapters, grouped timeline events, shared loading controller, request pool, warm-load bar cache, interval registry, chart timezone, trading visualization, OpenAlgo feeds, EMA/RSI/ATR/Supertrend calculators, vector SVG export, the render backend port | 95.50 kB |
| `openalgo-charts/indicators` | 112 built-in indicators + the Tier-2 external-data contract | 30 kB |
| `openalgo-charts/draw` | 87 drawing tools, including Anchored VWAP and fixed-range Volume Profile, opt-in drawing links and a headless `DrawingController` with multi-select, z-order, a per-tool settings schema, the 1.9.x migration, the clipboard and the icon builders | 41 kB |
| `openalgo-charts/transform` | Heikin Ashi, Renko, Range bars, Line Break, Point and Figure, Kagi | 6 kB |
| `openalgo-charts/profile` | Volume Profile, Market Profile (TPO), Footprint, order flow | 15 kB |
| `openalgo-charts/trade` | Order engine, state machine, order/position/bracket lines, DOM ladder | 103.50 kB with base |
| `openalgo-charts/webgl` | The WebGL2 series backend behind `renderer: 'auto' \| 'webgl2'`; composites into the pane's canvas, falls back to 2D for the session on context loss | 7 kB |
| `openalgo-charts/widget` | `createWidget`: the chart with a top bar, drawing rail, responsive mobile controls, status line, settings and indicator dialogs, drawing properties, event details, right-click menu, keymap and optional persistence. The only tier that ships DOM; imports the draw tier itself | 51.50 kB |
| `openalgo-charts/workspace` | Portable workspace/template documents, asynchronous catalog repository and atomic IndexedDB adapter; no UI or market data | 6 kB |

Limits are the CI-enforced budgets in `.size-limit.json`. This reference targets 2.6.4; a
section marked (unreleased) is on the main branch only and is not in that release.
In a source checkout, run `npm run size` before quoting byte counts. In a consumer app,
check the installed version and measure its actual imports with the app's bundler.
Reference measurements and every budget row live in [bundling-and-tiers](references/bundling-and-tiers.md).

The clipboard lives in the **draw** tier, not the base one, because it needs the drawing-tool registry. `DrawingClipboard` and friends come from `openalgo-charts/draw`.

## The 60-second chart

```ts
import { createChart } from 'openalgo-charts';

const chart = createChart(document.getElementById('chart')!);
const series = chart.addSeries('candlestick');

series.setData([
  { time: 1705286700, open: 100, high: 101, low: 99.5, close: 100.6, volume: 1200 },
  { time: 1705286760, open: 100.6, high: 101.4, low: 100.2, close: 101.1, volume: 900 },
]);

chart.fitContent();
```

`time` is **UTC seconds**. The container must have a non-zero size before the chart can lay out.

## Non-negotiable rules

1. **Time is UTC seconds everywhere, never milliseconds.** `Math.floor(Date.now() / 1000)`, not `Date.now()`. Feed adapters convert broker formats at the edge. Which wall clock those seconds are *labelled* in is `ChartOptions.timezone`, an IANA name defaulting to `Asia/Kolkata`; never offset the timestamps themselves to fake a zone, or every session anchor and gap moves with them.
2. **The time axis is gapless and index-based, not timestamp-proportional.** x is `logicalIndex * barSpacing`, so weekends, holidays and session breaks have no index and collapse to nothing. Never compute an x from a timestamp difference; use `chart.timeToCoordinate(t)` or `chart.timeScale`.
3. **One bar per time per series, ascending.** Duplicate times collapse to the last one written.
4. **Nothing crosses a chart boundary as a logical index. Sync by instant.** Because rule 2 makes the index a property of *that chart's own bars*, index 300 is a different moment on every chart in a grid. Any value passed between charts (a linked crosshair, a shared viewport, a highlighted bar) converts index to time on the sender with `indexToTimeFloat` and time back to index on the receiver with `timeToIndex` / `timeToIndexFloat`, against that chart's own `DataLayer`. `createLinkGroup`, `followerIndex` and `followerRange` do this; a hand-rolled `b.setVisibleLogicalRange(a.getVisibleLogicalRange())` does not, and it looks correct until the two charts hold different bars. An instant outside the receiver's first or last bar is an **absence**: draw nothing rather than clamping to an edge bar. See [chart-linking](references/chart-linking.md).
5. **Never cache the forming bar.** A closed bar is immutable; the last bar is alive until its interval ends. Serving a snapshot of it puts a stale close on the last-price line, the axis tag, the header LTP and every indicator computed off it, with no spinner and no staleness badge. `withBarCache` drops trailing unclosed bars for this reason. A fast wrong price is a worse failure than a slow right one on a chart that draws Buy and Sell buttons.
6. **Never deep-import.** `import { X } from 'openalgo-charts'` or a published tier specifier only. A deep path into `dist/` internals inlines a second copy of the registry Map, and `createChart` will never see what your tier registered. See `rollup.config.js`.
7. **A tier must be imported before its features resolve.** `chart.addIndicator('macd')` needs `import 'openalgo-charts/indicators'`; `addSeries('kagi')` needs `import 'openalgo-charts/transform'` and throws a specific tier-naming error without it.
8. **Price-scale margins are fractions of the pane height, not padding on the data span.** The data band occupies `1 - marginTop - marginBottom` of the pane.
9. **Drawing anchors are `{ time, price }`, never pixels.** Pixel anchors slide the moment a gap collapses or the user zooms.
10. **Canvas drawing happens in bitmap pixels.** Multiply media px by `dpr` in any custom primitive, or it blurs and misaligns on HiDPI.
11. **`chart.trading` renders trade state; it does not place orders.** The host pushes exchange state in and turns the emitted `trading:*` events into broker calls. The transactional path is `openalgo-charts/trade`.
12. **The engine ships no DOM chrome; `openalgo-charts/widget` is the one tier that does.** The base and the seven non-widget optional tiers have no toolbar, no dialogs, no settings forms, no command palette. Drawing tools, indicator settings, replay transports and order menus are the host's UI, driven by descriptors and events. A host that does not want to write that chrome imports the widget tier and calls `createWidget` (see [widget](references/widget.md)); a host that does gets the *description* of that UI: `chartSettingsSchema(chart)` for a settings dialog, the `contextmenu` event for a right-click menu, and `chart.priceAxisState(...)` for a menu raised on a price axis. Chrome you write is held to the UI standard in [themes-and-styling](references/themes-and-styling.md#host-chrome-the-ui-standard): styled scrollbars, small square swatches, paired up/down colours on one row, themed form controls, and no control with nothing behind it.
13. **A control with no data in the current context is rendered disabled, not hidden.** `PriceLevels.available(kind)` and `PriceAxisState.active` / `scaled` / `movable` exist to be read for exactly this. Hiding it loses the information that the state is off.
14. **Never use emojis or icons in code, comments, logs, or generated UI text.** Project rule.

## References

Detailed reference for each topic is in `references/`. Read the one that matches the task before writing code.

| Reference | Topic |
|---|---|
| [core-api](references/core-api.md) | `createChart`, `ChartOptions`, `SeriesApi`, lifecycle, coordinate conversion, the render/invalidation model |
| [chart-types](references/chart-types.md) | All 13 base series types, their styles and autoscale rules, runtime type switching |
| [scales-and-panes](references/scales-and-panes.md) | Price/time scale options, log and inverted modes, left/right/overlay scales, per-axis state and moves, axis chrome (corner clock, bar countdown, tick priority), pane weights and layout |
| [themes-and-styling](references/themes-and-styling.md) | `ChartTheme` keys, dark/light, gradients, `SeriesStyle` precedence, price formatting, and the UI standard for host chrome |
| [data-and-time](references/data-and-time.md) | `Bar` shape, UTC seconds, the chart timezone and the time helpers, setData/update/prependData, the logical-index model, history paging, tick and volume bars |
| [feeds-and-live](references/feeds-and-live.md) | `DataFeed` contract, OpenAlgo REST/WS/live feeds, `CandleBuilder`, the interval registry, `withBarCache` warm loading, writing a custom feed |
| [events-and-state](references/events-and-state.md) | The full event catalogue with payloads, `getState`/`restoreState`, saved layouts |
| [alerts](references/alerts.md) | Headless trader alerts, confirmed versus intrabar timing, lifecycle, expiry and host delivery |
| [indicators](references/indicators.md) | The 112 built-ins with exact ids, placements and input defaults, the settings model, levels/ranges/fills, signal markers, `registerIndicator`, the Tier-2 external-data contract |
| [transforms](references/transforms.md) | Heikin Ashi, Renko, Range, Line Break, Point and Figure, Kagi |
| [drawing-tools](references/drawing-tools.md) | The 87 tools, `DrawingController`, anchors, magnet, undo, copy/cut/paste and the clipboard payload, persistence, shortcuts, custom tools |
| [primitives-and-plugins](references/primitives-and-plugins.md) | `IPrimitive`, z-order, hit-testing, the dpr contract, built-in primitives including the `PriceLevels` reference-level family, `registerChartType` |
| [replay-and-compare](references/replay-and-compare.md) | `ReplayController` and its transport events, `addComparison`, the overlay-scale mechanism, timestamp alignment |
| [chart-linking](references/chart-linking.md) | `createLinkGroup`, the sync-by-instant rule, `followerIndex` / `followerRange`, the linked crosshair, host-driven symbol, interval and chart type sync, appearance adapters, the drawings channel over `DrawingLinkGroup`, and saved link groups (`WorkspaceSync`) |
| [settings-and-menus](references/settings-and-menus.md) | `chartSettingsSchema` and its round trip, the five tabs, the `colorPair` row, the timezone control, canvas options (grid, crosshair, scales, margins), status-line switches, the `contextmenu` event and the price-axis menu |
| [trading](references/trading.md) | The data-driven on-chart trading layer, `trading:*` events, order/position/bracket lines |
| [trade-tier](references/trade-tier.md) | `OrderEngine`, order state machine, validation, analyzer mode, DOM ladder, broker adapters |
| [profiles-and-orderflow](references/profiles-and-orderflow.md) | Volume Profile, Market Profile (TPO), Footprint, cumulative delta, the trade-data dependency |
| [react-integration](references/react-integration.md) | React and Next.js lifecycle, keeping orchestration out of React, SSR, resize |
| [vue-integration](references/vue-integration.md) | Vue 3 composable and component, keeping the chart out of `ref()`/`reactive()`, props to data, KeepAlive, Nuxt |
| [bundling-and-tiers](references/bundling-and-tiers.md) | Entry points, registry identity, tree-shaking, script/ESM/import-map loading, size budget |
| [widget](references/widget.md) | `createWidget` and the widget tier: options, the handle, events, the context every dialog is handed, the keymap scopes, the tokens, every exported mount and helper, packaging |
| [workspaces](references/workspaces.md) | Portable multi-chart workspaces, indicator templates, async catalog transactions, account namespaces and atomic browser storage |
| [interactions](references/interactions.md) | Two-axis panning, optional horizontal mouse/pen pan, axis drag, navigator reset, default visible bars, keyboard and accessibility |
| [host-integration](references/host-integration.md) | Hidden-tab startup, paging/replay isolation, stale async work, registration readiness, and upstream browser validation |
| [pitfalls](references/pitfalls.md) | The verified foot-gun list. Read this when something behaves unexpectedly |

## Triage

| User asks about | First check | Answer with | Avoid |
|---|---|---|---|
| First chart / blank chart | container size, `dist` present | `createChart` + `addSeries` + `setData`; hidden charts fit on their first measurable layout | assuming data needs to be fetched again when a tab opens |
| Upgrade a 1.9.x drawing host | [drawing model](references/drawing-tools.md#the-20-drawing-model) | `DrawingText`, `FibLevel[]`, versioned drawings, multi-selection and schema controls | writing text into `DrawingStyle` or treating `toJSON()` as an array |
| Recent-bar default / chart drifts vertically | [navigation](references/interactions.md#navigation-options) | `navigation.defaultVisibleBars`, horizontal `mousePan`, `resetScale()` | trimming history or overriding the preference with `fitContent()` |
| Trackpad zoom or price jumps during navigation | [interactions](references/interactions.md) | normalized proportional wheel input, price-axis scaling and `animAutoscale` | mapping every wheel event to the same zoom step or replacing a manual price range |
| Touch controls or a narrow dashboard chart | [widget](references/widget.md) | `mobile: 'auto'`, `'always'` or `'never'`; shared drawing state and tool allowlist | assuming the headless engine supplies widget chrome |
| Compact TPO or demo palettes | [profiles](references/profiles-and-orderflow.md#compact-profiles-and-demo-themes) | per-session split, markers, explicit palette options | inventing a library theme preset |
| Replay changes during recovery / late symbol response | [host integration](references/host-integration.md) | generation and request-owner guards around every writer | assuming replay owns the host feed or timers |
| Bars in the wrong place | units of `time` | UTC seconds | `Date.now()` milliseconds |
| Axis shows the wrong hours | `chart.timezone()` | `timezone: 'America/New_York'` on `createChart`, or `setTimezone` | shifting bar timestamps, or a `timeFormatter` that only relabels |
| Gaps for weekends | the gapless-axis rule | it is intended; whitespace points if you want a gap | shifting timestamps |
| Realtime ticks | last-bar vs full replace | `series.update(bar)` | `setData` on every tick |
| Loading older history | `setHistoryLoader` | `prependData` + `historyLoadComplete` | rebuilding and re-fitting |
| Indicator not found | is the tier imported | `import 'openalgo-charts/indicators'` | registering it by hand |
| Which indicator id to use | the catalogue in [indicators](references/indicators.md) | the exact id from the 112-row table, guarded with `hasIndicator(id)` | guessing an id from the display name |
| Indicator settings UI | descriptor `inputs` + generated style keys | build the form from the descriptor, apply with `setSettings`; or `openalgo-charts/widget` (`mountIndicatorSettings`, or the whole terminal via `createWidget`) for a host that does not want to write chrome | expecting the engine itself to have a dialog |
| Drawing tools | `DrawingController` | headless controller + host toolbar; or `createWidget` from `openalgo-charts/widget`, which ships the rail | expecting the engine itself to have a toolbar |
| Volume in its own pane | `paneIndex` and `priceScaleId` | `addSeries('histogram', { paneIndex: 1 })` | a second chart |
| Volume inside the price pane | overlay scale | `priceScaleId: ''` plus scale margins | manual y math |
| Placing real orders | which layer | `openalgo-charts/trade` `OrderEngine` | `chart.trading` (visualization only) |
| Order lines on the chart | which layer | `chart.trading` sync + `trading:*` events | drawing your own price lines |
| Custom overlay | primitive vs chart type | `IPrimitive` + `addPrimitive` | a custom chart type for decoration |
| Bar-by-bar replay | `ReplayController` | headless controller + host transport bar; indicators rebuild from the prefix | a second chart, or slicing data by hand |
| Two symbols on one chart | `addComparison` | hidden overlay scale + a rebasing pane mode | a second series on the same price axis |
| A grid of charts moving together | `createLinkGroup` | independent cursor, viewport, symbol, interval, chart type, appearance and drawings channels (drawings moved by the draw tier's `DrawingLinkGroup`); everything syncs by **time**, never by logical index | copying `getVisibleLogicalRange()` between charts |
| Linked crosshair shows the wrong bar | the index-to-time conversion | `followerIndex(target.dataLayer, time, whenMissing)` | assuming index N is the same instant on both charts |
| Port a study that reads a higher timeframe, draws ahead of the last bar, or compares against another symbol | [coverage additions (2.4.0)](references/indicators.md#coverage-additions-240) | `securitySeries`, `plot.offset`, `ctx.requestBars` with `chart.setBarsProvider`, `IndicatorInputError` | folding bars by hand, emitting future times into the axis, or fetching a benchmark from inside `calc` |
| Slaving the symbol across charts | who owns the instrument | the host emits `'symbol'` / calls `setSymbol`, each member gets an `onSymbol` loader | expecting the engine to know what a symbol is |
| Copy and paste a drawing | `draw.copy()` / `cut()` / `paste()` | await them; the host owns the key chords | a synchronous call, or throwing on foreign clipboard text |
| Refetching the same bars on every switch | `withBarCache(feed, opts)` | wrap the feed; key is symbol/exchange/interval, range is sliced | caching the forming bar, or keying on the range |
| A monthly / tick / volume timeframe | `registerInterval` | a `Bucketing` rule (`calendar`, `ticks`, `volume`), then `bucketStartOf` | `intervalToSeconds` on a code that has no fixed length |
| Unknown interval code | `isKnownInterval(code)` | validate the picker; `resolveInterval` throws `UnknownIntervalError` | catching the throw and defaulting to 60 seconds |
| Percent / rebased axis | `priceScale.mode` | `'percentage'` or `'indexed-to-100'` plus a baseline | recomputing the data into percentages |
| Settings dialog | `chartSettingsSchema(chart)` | render the tabs, round-trip with `read`/`applyChartSettings`; or `mountSettingsDialog` / `createWidget` from `openalgo-charts/widget` | hardcoding a control list |
| Right-click menu | `contextmenu` event | `preventDefault()` + `target.kind` | hit-testing the pointer yourself |
| Menu on a price axis | `target.side` / `target.scaleId` | `chart.priceAxisState(pane, scaleId)`, acted on by the `setPriceAxis*` calls | assuming pane 0's right scale |
| Previous close, session high/low, bid/ask lines | `PriceLevels` | one primitive, one options group per level, `line` and `label` together | a `PriceLine` per level with its own tag bookkeeping |
| A level or axis row with no data | `available(kind)`, `state.active` | render it disabled with its state visible | hiding the control |
| Corner clock, bar-close countdown | `ChartOptions.axisChrome` | `{ sessionClock: true, barCountdown: true }`, plus a `clock` for a delayed feed | a DOM overlay positioned over the axis |
| Named multi-chart layouts and templates | [workspaces](references/workspaces.md) | `WorkspaceRepository` plus a storage adapter; each pane carries `getState()` | treating a single chart snapshot as the whole host workspace |
| Watchlists with live prices, or symbol news | [widget](references/widget.md#watchlist-and-news-panels-255), [workspaces](references/workspaces.md#named-watchlists-255) | `WatchlistRepository` plus a `QuoteFeed` and a `NewsFeed`, as the widget's `watchlist` and `news` options | pricing a row from the last candle, or rendering provider text as HTML |
| React lifecycle | where the chart instance lives | create in an effect, hold in a ref, `chart.destroy()` on cleanup | chart instance in state |
| Vue lifecycle, or replay and picks misbehaving in a Vue app | is the chart in `ref()` or `reactive()` | `shallowRef` or `markRaw`, create in `onMounted`, `destroy()` in `onBeforeUnmount`; see [vue-integration](references/vue-integration.md) | `ref(chart)`, which hands back a proxy the library does not recognise as its chart |
| Bundle size | which tiers are imported | drop the unused tier import | code-splitting the base |

## Core API cheat sheet

Verified names. Get these wrong and nothing works.

```ts
// chart
const chart = createChart(el, options);
chart.addSeries(type, { paneIndex, style, priceScaleId, priceFormat });
chart.addIndicator(id, settings, { paneIndex });   // needs the indicators tier
chart.addPriceLine(opts, paneIndex);
chart.addPrimitive(primitive, paneIndex);
chart.fitContent();                       // explicitly fit all loaded history
chart.resetScale();                       // preferred default view + all price scales
chart.setNavigationOptions({ mousePan: 'both', defaultVisibleBars: 120 });
chart.navigationOptions();
chart.applyOptions({ theme, grid, canvas, statusLine, priceScale, priceFormatter, timeFormatter, timezone, crosshairMode });
chart.setTheme(theme);
chart.setTimezone('America/New_York') / chart.timezone();   // IANA name, default 'Asia/Kolkata'
chart.panes();                          // readonly Pane[]
chart.primarySeries() / chart.primarySeriesInfo();
chart.setCanvasOptions(opts) / chart.setStatusLineOptions(opts) / chart.setPriceScaleOptions(opts);
chart.setAxisChromeOptions({ sessionClock: true, barCountdown: true }) / chart.axisChromeOptions();

// one price axis at a time (what a menu on an axis strip acts on)
chart.priceAxisState(paneIndex, scaleId);               // PriceAxisState | null
chart.setPriceAxisOptions(paneIndex, scaleId, patch);
chart.setPriceAxisAutoFit(paneIndex, scaleId, on);
chart.setPriceAxisLockRatio(paneIndex, scaleId, on);    // boolean
chart.movePriceAxis(paneIndex, 'right', 'left');        // boolean
PRICE_SCALE_MODES;                      // ['linear','logarithmic','percentage','indexed-to-100']
chart.getState() / chart.restoreState(state);
chart.on(event, cb);                    // returns an unsubscribe function
chart.subscribeCrosshairMove(cb);
chart.timeToCoordinate(t) / chart.coordinateToTime(x);
chart.priceToCoordinate(p, paneIndex) / chart.coordinateToPrice(y, paneIndex);
chart.destroy();                        // idempotent; emits 'destroy', then drops every listener
chart.isDestroyed;                      // getter, not a method

// getters, not methods
chart.timeScale;   // TimeScale
chart.dataLayer;   // DataLayer
chart.trading;     // TradingController, created on first access
chart.shortcuts;   // ShortcutManager | null

// series handle
series.setData(items);
series.update(item);
series.prependData(items);
series.getData();
series.applyOptions({ visible: false });   // not setStyle
series.priceScale();
series.createMarkers();
series.remove();

// headless controllers, base bundle, no tier import
new ReplayController(chart, { bars, startIndex, barMs });  // seek/step/play/pause/stop/state
addComparison(chart, { symbol, bars });                    // setBars/remove/list/alignment
chartSettingsSchema(chart) / readChartSettings(chart) / applyChartSettings(chart, patch);

// linked chart grid (base bundle). Syncs by INSTANT, never by logical index.
const group = createLinkGroup({ crosshair: true, viewport: true, symbol: false, whenMissing: 'nearest' });
group.add(chart, { symbol: 'RELIANCE', onSymbol: (s, c) => loadBars(s, c) });
group.remove(chart) / group.setOptions(patch) / group.setSymbol(chart, s) / group.destroy();
group.members() / group.has(chart) / group.symbol() / group.crosshairIndex(chart);
followerIndex(followerDataLayer, timeSec, 'nearest' | 'hide');   // number | null
followerRange(leaderDataLayer, followerDataLayer, range);        // LogicalRange | null

// warm-load bar cache: wraps ANY DataFeed (base bundle)
const feed = withBarCache(sourceFeed, { ttlMs, max, maxBars, storage, now, barCloses });
feed.getBars({ symbol, exchange, interval, from, to, noCache: true });
feed.invalidate({ symbol, exchange, interval }) / feed.clear() / feed.stats() / feed.source;

// interval registry (base bundle): a bucketing rule, not a duration
registerInterval({ code: '1MO', bucketing: { mode: 'calendar', unit: 'month', count: 1 } });
resolveInterval(code)        // throws UnknownIntervalError
tryResolveInterval(code) / isKnownInterval(code) / registeredIntervals() / unregisterInterval(code);
bucketStartOf(bucketing, timeSec, zone?) / nextBucketStart(...) / isTimeBucketed(bucketing);

// drawing clipboard (draw tier) - all async
await draw.copy(target?) / await draw.cut(target?) / await draw.paste();
draw.clipboard().lastError();

// reference levels (a primitive: previous close, session high/low, bid/ask, ...)
const levels = new PriceLevels({ levels: { previousClose: { line: true, label: true } } });
chart.addPrimitive(levels);   // the price pane, wherever it sits
levels.setLevel(kind, patch) / levels.setQuote(q) / levels.values() / levels.available(kind);
computePriceLevels({ bars, anchorTime });   // the same numbers, pure, no canvas
```

`chart.fitContent()` takes no arguments; `chart.timeScale.fitContent(barCount)` does.

## Code-generation rules

- **Verify option names against local typings before writing them.** Many similarly named options exist at chart, series, pane and scale level. Confirm which level owns the option.
- **Minimal snippets.** One feature per code block. Combining an indicator, a drawing tool and a trading line in one snippet hides which API does what.
- **Import from the package entry or a published tier specifier.** Never a deep path.
- **Match the user's host.** A React user wants the effect lifecycle; a Vue user wants the composable with a `shallowRef`; a vanilla user wants neither; a no-bundler user gets `<script type="module">` from `dist/` or a CDN, or the script-tag files when the page cannot load modules.
- **State which tier a feature needs** whenever the answer uses one.
- **Do not invent.** If a name does not appear in the installed typings or upstream source, it does not exist.

## Answer contract

When answering an openalgo-charts question:

1. Name the API and the tier it lives in.
2. Show one minimal snippet, not a mega-demo.
3. Call out the main foot-gun for that task, from [pitfalls](references/pitfalls.md).
4. Say what local source was checked (version, typings), or state that it could not be verified.
