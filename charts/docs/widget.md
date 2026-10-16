# The widget tier

`openalgo-charts/widget` turns the engine into a working terminal in one call: a chart
with a top bar (symbol, interval, chart type, theme, settings, indicators, objects), a drawing
rail down the left, a status line, the dialogs behind each of those buttons, keyboard
shortcuts with a `?` panel that lists them, and optional persistence of the layout. It
is one of nine loadable tiers and the only tier that supplies application controls.

<a id="the-engine-still-ships-no-dom"></a>

## Engine and interface separation

`openalgo-charts` and the seven non-widget optional tiers contain no toolbar, no dialog, no menu and no
stylesheet. The engine creates canvas and container elements; it does not provide application controls. The widget is a host,
packaged: everything it draws in HTML it drives through the same public API a host of
your own would use (`createChart`, `DrawingController`, `chartSettingsSchema`, the
`contextmenu` event, the indicator registry).

That promise is enforced, not stated:

- **The tier ACL** (`eslint.config.js`). Nothing under `src/` except `src/widget/` may
  import the widget, and the widget may reach the engine and the draw tier only through
  their package specifiers, so it can never be inlined into another bundle.
- **`npm run shake`** bundles an entry that imports only `createChart` and asserts the
  widget's CSS scope (`oac-widget`) is absent from the result, on every build.
- **The size budgets** (`.size-limit.json`). The base engine row did not move when the
  widget arrived; the widget has its own row, and a `Widget terminal` row measures what
  one `createWidget` call actually loads.

Importing the module touches no DOM either; only `createWidget` does. The module can
therefore be imported by code that also runs on a server, and called once a container
exists. `npm run skills:coverage` imports the built tier under Node and fails if a
module-scope DOM access ever creeps in.

## Install

```bash
npm install openalgo-charts
```

The widget entry imports `openalgo-charts` and `openalgo-charts/draw` itself. The
indicator picker offers whatever the indicator registry holds, so import
`openalgo-charts/indicators` alongside it for the 112 built-ins; without that import the
picker offers only what you registered yourself.

## One call

```ts
import { createWidget } from 'openalgo-charts/widget';
import 'openalgo-charts/indicators';
import { OpenAlgoDataFeed } from 'openalgo-charts';

const widget = createWidget('#terminal', {
  feed: new OpenAlgoDataFeed({ baseUrl: 'http://127.0.0.1:5000', apiKey: 'YOUR_KEY' }),
  symbol: 'RELIANCE',
  exchange: 'NSE',
  interval: '5m',
  theme: 'dark',
  persist: true,
});
```

The container is an element, a CSS selector or an element id, and it needs a non-zero size before the
call, the same rule `createChart` has. What comes back is a `Widget`:

```ts
widget.chart;                 // the Chart underneath, every base API available
widget.draw;                  // the DrawingController the rail drives
widget.objects;               // live ChartObjects inventory and supported actions
widget.series;                // the primary series; setChartType replaces it
widget.root;                  // the .oac-widget element
widget.context;               // what every dialog was handed, for a panel of your own
widget.symbol(); widget.exchange(); widget.interval(); widget.chartType(); widget.theme();
widget.setSymbol('INFY', 'NSE');
widget.setInterval('15m');    // throws UnknownIntervalError for a code the registry lacks
widget.setChartType('area');
widget.setTheme('light');
widget.openSettings();        // false when no settings dialog is registered
widget.openIndicatorPicker();
widget.openObjects();         // searchable object management
await widget.reload();        // fetch again for the current symbol and interval
const saved = widget.getState();   // { version, symbol, exchange, interval, chartType, theme, chart, rail }
widget.restoreState(saved);        // { applied, reason?, chart? }
widget.destroy();                  // saves if persisting, removes the chrome, destroys the chart
widget.isDestroyed;
```

`restoreState` applies a saved viewport only when the state was captured on the same
symbol and interval; on any other dataset the indicators, drawings and panes still land
and the view is dropped, because a range of bar indices means nothing on different bars.

A `Widget` is a thin owner. Anything the chrome does not expose, do on `widget.chart` or
`widget.draw` directly; the chrome observes the chart and stays in step.

## Objects and compact dialogs

Since 2.1.7, the Objects control lists the protected primary source, indicator
instances, drawings and explicitly registered profiles. Its actions use the existing
drawing controller and settings editors. Indicator visibility survives saved layouts;
older layouts without a `visible` field restore indicators as visible. Drawing
visibility, locking and removal remain part of the drawing undo history.

The shared `ChartObjects` model creates no DOM and can drive a custom broker UI.
`mountObjectsPanel` reuses the widget panel with an existing `WidgetContext`. Register
profile operations explicitly rather than enumerating arbitrary chart primitives.
See the [Objects API and live example](https://marketcalls.github.io/openalgo-charts/docs/objects/).

Dialogs fit the actual widget container, including a 350px pane on a wide page.
Tabs adapt to a horizontal row, fields wrap and content scrolls inside the dialog
while its actions remain reachable.

## Watchlist and news panels

The panel dock can carry two more panels beside Data and Objects: a Watchlist of
named lists with quote rows, and a News reader for the chart's instrument. Each is
optional, and its tab, top bar button and mobile More entry appear only when the host
supplies its source. Both need `panels` on. Added in 2.5.5.

```ts
import { createWidget } from 'openalgo-charts/widget';
import { WatchlistRepository, createIndexedDbWatchlistStorage } from 'openalgo-charts/workspace';

const widget = createWidget('#chart', {
  feed, symbol: 'INFY', exchange: 'NSE',
  watchlist: { store: new WatchlistRepository(createIndexedDbWatchlistStorage(indexedDB), 'user-42'), quotes },
  news: { feed: newsFeed, pageSize: 20 },
});
widget.openWatchlist(); // false without a watchlist source, with panels off, or after destroy()
widget.openNews();
```

- **Prices come only from a `QuoteFeed`.** `quotes.getQuotes({ instruments, signal })`
  answers snapshots, and the optional `subscribeQuotes(instruments, { onQuote,
  onStatus })` streams them. The panel never reads the chart's bars: without a quote
  source every row shows its symbol and `n/a`. Change figures come from the provider's
  `previousClose`.
- **Only rows on screen hold a stream.** Rows subscribe one instrument per call as
  they scroll into view and release as they leave; a list switch, a hidden page,
  closing or switching the panel and `destroy()` release them all.
- **Stale is shown, and costs nothing while it lasts.** A quote held while its stream
  reconnects or disconnects, or a snapshot older than `staleAfterMs` (60 seconds), is
  shown muted as stale. The panel waits only for the next row that can still age into
  stale, so a quiet board holds no timer. A source without `subscribeQuotes` is polled
  every `pollMs` (15 seconds; 0 turns it off) while rows are visible.
- **Rows name what the widget charts.** Choosing a row calls `setSymbol(symbol,
  exchange)`, which upper-cases the symbol, so the widget compares and saves entries in
  that form: a lower-case entry is the chart's own row, and its upper-case twin is
  refused as already listed.
- **Sorting holds still, and survives.** Sort by symbol, last, change or percent change
  from the headers; a third click returns to list order. The sort outlives a panel
  switch, and with `persist` it is saved with the widget's other preferences. While
  the pointer or focus is on the rows, prices update in place
  but rows do not move. Alt+ArrowUp and Alt+ArrowDown reorder a row in list order, one
  saved move at a time.
- **News is text.** The `NewsFeed` answers `getNews({ symbol, exchange, cursor, limit,
  signal })` with `{ items, nextCursor }`. The reader follows the chart's instrument,
  cancels on a switch, drops repeats across pages and shows every provider string as
  text. It links an article only for `safeNewsUrl(url)`: absolute http or https
  without credentials, opened with `rel="noopener noreferrer"`.

A host with its own chrome can mount the same panels into `mountPanelDock` with
`mountWatchlistPanel(ctx, host, options)` and `mountNewsPanel(ctx, host, options)`;
the watchlist then takes `onSelect` and an optional `normalize(instrument)` for its
host's own naming. `WATCHLIST_PANEL_CSS` and `NEWS_PANEL_CSS` are part of the widget
stylesheet. The DOM-free `QuoteBoard` and `NewsReader` controllers, and
`quoteChange(quote)`, serve a host that draws its own view. The yfinance reference host
mounts the panels in both of its pages. See
[workspaces](./workspaces.md#named-watchlists) for the lists themselves.

## Saved layouts

`createLayoutsController(store, target, options?)` (since 2.5.10) holds one saved layout
for a widget or a chart grid, DOM-free, over a `WorkspaceStore` from
`openalgo-charts/workspace` that it takes as a type only. Its target captures and applies
workspace payloads (`grid.getWorkspace()` and `grid.applyWorkspace(payload)` for a grid),
and it runs save, save as, rename, delete, open and autosave one at a time with revision
checks. See [workspaces](./workspaces.md#catalog-transactions-and-storage) and the
website's Workspaces page for its state and conflict rules.

Since 2.5.10 `createWidget(el, { workspaces })` builds that controller over the widget
itself (`widget.layouts`) with a Layouts menu in the top bar and the More sheet
(`widget.openLayouts()`, and `openLayoutsMenu(ctx, controller, anchor?)`, which resolves
with the menu's handle once the menu has loaded, and rejects when it cannot load or the
widget was destroyed by then), reopens the active
layout on load, and offers indicator templates in the picker when the store has
`planIndicatorTemplateState` (`applyIndicatorTemplate`, `saveIndicatorTemplate`).
`widgetLayoutTarget(widget)` is the widget's own target.

## Mobile controls and navigation

`mobile: 'auto'` selects compact controls when the widget container is at most 640 CSS
px wide, or, with a coarse primary pointer, at most 960 px wide and under 600 px tall
(a phone on its side); tablets and touch laptops keep the desktop controls. From 2.1.8
to 2.5.9 any coarse pointer selected them. Use `'always'` to force them or `'never'` to
keep desktop controls. The mobile symbol header, interval picker, bottom bar and
drawing sheets reuse the existing drawing controller, object inventory and dialogs.
Changing layout retains drawings, selection and undo history; `rail.tools` restricts
the same tool ids in both layouts.

Vertical wheel input zooms time proportionally; dominant horizontal input and Shift-wheel
pan time. A vertical wheel movement over a visible price axis scales that axis around
the pointer price. Ctrl-wheel and Meta-wheel zoom time at the pointer inside the plot.
`animAutoscale` eases automatic price ranges during navigation and defaults to `animZoom`.
Manual and fixed price scales remain authoritative. Programmatic viewport replacement,
primary data replacement, reset and destruction cancel pending navigation motion.

The widget disables omitted `animZoom` and `animAutoscale` options when the user prefers
reduced motion; explicit host settings win. A bare `createChart` host manages that
preference and its own mobile controls. See the [mobile guide and live example](https://marketcalls.github.io/openalgo-charts/docs/mobile/).

## Bottom bar

Since 2.5.10 the widget mounts a 28 px bar under the chart (`bottombar`, default on):
preset ranges sized in trading sessions (`ranges`, `widget.setRange('1D')`), **Go to**,
the market status from the chart's session calendar, a clock in the chart's timezone
that opens a timezone menu, and the Auto, Log and Percent price scale toggles. Go to
lives in this bar; with `bottombar: false` it is back in the top bar and the status line
shows the market status. `sessionCalendar` gives the chart its trading hours, and
`sessionShading` (default on) washes pre-open, post-close and extended-hours bars. The
phone layout hides the bar and lists its controls in the More sheet. In a chart grid the
bar is the grid's: `ChartGridOptions.bottombar` (default false) puts one bar under the grid
for the active chart; see the
[chart grid](https://marketcalls.github.io/openalgo-charts/docs/chart-grid/). See the
[bottom bar](https://marketcalls.github.io/openalgo-charts/docs/widget/#bottom-bar) on the
website.

## Options

`WidgetOptions` is `ChartOptions` plus the fields below. Every `ChartOptions` key
(`timezone`, `grid`, `priceScale`, `axisChrome`, `renderer` and the rest) passes through
to `createChart` unchanged.

| Option | Type | What it does |
|---|---|---|
| `feed` | `DataFeed` | Where bars come from. The widget calls `getBars` for the current symbol and interval (and `subscribeBars` when the feed has it), and again on every `setSymbol` / `setInterval` / `reload`; with no feed, put data on `widget.series` yourself. |
| `symbol` | `string` | The instrument shown at start and in the top bar. Upper-cased. |
| `exchange` | `string` | Passed to the feed with the symbol. Default `''`. |
| `interval` | `string` | An interval code the interval registry knows (`'1m'`, `'5m'`, `'1d'`, or one you registered with `registerInterval`). An unknown code throws `UnknownIntervalError`; a persisted code this build does not know falls back to `'1d'`. Default `'1d'`. |
| `intervals` | `string[]` | The interval pills. Default: `DEFAULT_INTERVALS` (`1m 5m 15m 1h 1d 1w`) plus every other registered code. |
| `chartType` | `string` | The primary chart type: a registered chart type id or a transform the chart applies to the bars it loads (`heikin-ashi`, `renko`, `range-bars`, `line-break`, `point-figure`, `kagi`, with the transform tier imported). Without a `feed`, point and figure and Kagi stay renderers over the elements the host feeds `widget.series`, as before. Default `'candlestick'`. |
| `theme` | `'dark'` \| `'light'` \| `ChartTheme` | A named palette or a full theme object. Drives both the canvas and the chrome tokens (see below). Default `'dark'` (the engine's own default is light). |
| `rail` | `boolean` \| `RailOptions` | The drawing rail. `false` hides it; `tools` restricts which registered tool ids appear (the order follows the rail's own groups); `favorites` seeds the pins when nothing is stored. |
| `topbar` | `boolean` | The symbol, interval, chart type, indicators, capture, settings and theme controls. |
| `statusline` | `boolean` | The status line under the chart. |
| `mobile` | `'auto'` \| `'always'` \| `'never'` | Responsive touch controls; default `'auto'`. Observes container width and primary pointer capability. |
| `indicators` | `boolean` | The Indicators button and picker. Turn it off for a host that manages indicators itself. |
| `persist` | `boolean` \| `string` | `true` saves the state under the `default` namespace (`oac-widget:default:state`) and restores it on the next `createWidget`; a string names the namespace, for more than one widget per origin. Since 2.5.10 the state lands when `widget.ready` settles (see [Persistence](#persistence)). |
| `storage` | `StorageLike` \| `AsyncStorageLike` \| `null` | The store behind `persist`. Default: IndexedDB (since 2.5.10), else the page's `localStorage`. Pass `localStorage` to restore synchronously, as before. |
| `locale` | `string` | A BCP 47 tag the status line formats numbers with. |
| `symbolSearch` | `(query, { signal }?) => SymbolMatch[] \| Promise<SymbolMatch[]>` | Called as the user types in the symbol box; the results open as a menu under it. `signal` aborts once a newer query makes the answer stale. Default (since 2.6.0): the feed's `searchSymbols`, when it has one. |
| `lookbackBars` | `number` | Bars per load. Default 500. |
| `now` | `() => number` | The clock for the load window and the capture filename. Default `Date.now`. |
| `onOrder` | `(order: OrderRequest) => void` | Order entry from the right-click menu (`{ side, type, price, paneIndex }`). Without it the menu draws no trade rows. |
| `watchlist` | `WidgetWatchlistOptions` | A docked Watchlist: `store` (a `WatchlistStore`), `quotes?` (a `QuoteFeed`), `staleAfterMs?`, `pollMs?`, `formatPrice?`. See [Watchlist and news panels](#watchlist-and-news-panels). |
| `news` | `WidgetNewsOptions` | A docked News reader: `feed` (a `NewsFeed`), `pageSize?`, `staleAfterMs?`, `maxItems?`. |

The chrome switches (`rail`, `topbar`, `statusline`, `indicators`) default to on, so a
bare `createWidget(el)` is the full terminal. `persist` defaults to off: nothing is
written to storage until you ask.

## Persistence

With `persist` the widget keeps its layout, rail preferences, panels and each
instrument's drawings in IndexedDB (since 2.5.10; before, `localStorage`). IndexedDB
answers later, so the widget is built on its defaults, kept out of sight, and asks the
feed for nothing until the saved layout has been read; then it applies it and loads the
saved instrument. Await `widget.ready` before reading or editing the restored state:

```ts
const widget = createWidget(el, { feed, persist: 'desk' });
await widget.ready;
widget.symbol();   // the saved symbol
```

- **Upgrading.** The first visit copies the `oac-widget:<namespace>:` keys an earlier
  release left in `localStorage` into IndexedDB, once, and leaves them where they were.
- **Several tabs.** Each write that lands is announced to the other tabs on the
  database, so a tab opened earlier shows the lines another tab drew since and does not
  write over them. A hidden tab writes its layout only when it has a change pending.
- **Unload.** The writes still pending when the page hides or closes are kept in a small
  `localStorage` journal and written at the next load.
- **Failures.** A store that cannot be read runs the session on memory; a refused write
  is sent again with the next change. Both are reported on the status line.
- **Keeping localStorage.** `storage: localStorage` (or any synchronous `StorageLike`)
  restores before `createWidget` returns, exactly as before 2.5.10.
- **Another store.** `createIndexedDbWidgetStorage(indexedDB, 'my-app-charts')` names the
  database. Any object with `entries(prefix)`, `setItem` and `removeItem` returning
  promises (`AsyncStorageLike`) works too. An optional `subscribe(listener)` lets the widget
  follow the changes others make to it.

## Events

```ts
widget.on('symbol', (e) => console.log(e));    // { symbol, exchange }: picked in the top bar, or setSymbol
widget.on('interval', (e) => console.log(e));  // { interval }
widget.on('theme', (e) => console.log(e));     // { theme, chartTheme }
widget.on('layout', (e) => console.log(e));    // { reason, chartType? }: getState() would now return differently
widget.on('data', (e) => console.log(e));      // { symbol, interval, bars, error? }: a load finished or failed
widget.on('status', (e) => console.log(e));    // { text, kind }: the status line's message changed
```

`on` returns the unsubscriber; `off(event, cb?)` is the same thing by name. The six
events are what a host needs to keep its own state (a URL, a workspace, a
watchlist) in step with the chrome. Everything the chart itself emits (`crosshair:move`,
`contextmenu`, `trading:*`, the drawing controller's `drawing:*`) is still there on
`widget.chart` and `widget.draw`. See `Widget` in `dist/widget/index.d.ts` for the exact
callback payloads.

## Theming tokens

The chrome never carries a colour of its own. `widgetTokens(theme)` in
`src/widget/tokens.ts` derives every chrome colour from the active `ChartTheme`: panels
are the theme `background` stepped towards white or black, borders come from `axisLine`
and `paneSeparator`, text from `axisText` lifted for legibility, the accent from
`lineColor`, and the buy and sell colours from `upColor` and `downColor`. Spacing,
radius and font are added, and the set is written as `--oac-` custom properties on the
widget root, `.oac-widget`. One `<style>` element is injected per page, scoped under
that class, so nothing leaks into the host page and nothing from the host page leaks
in. Calling `setTheme` rewrites the tokens; every control follows without a repaint of
its own.

| Token group | Names (each prefixed `--oac-`) |
|---|---|
| Surfaces | `bg`, `panel`, `panel-2`, `elev`, `elev-2`, `elev-3`, `scrim`, `shadow` |
| Borders | `bd`, `bd-soft`, `bd-hover` |
| Text | `tx`, `tx-strong`, `mut`, `faint` |
| Accent and state | `acc`, `acc-2`, `on-bg`, `on-bd`, `ring`, `ring-soft`, `buy`, `sell`, `amber`, `danger` |
| Scrollbars | `sb-thumb`, `sb-thumb-hover` |
| Type and metrics | `font`, `mono`, `fs`, `radius`, `rail-w`, `topbar-h`, `status-h`, `ctl-h` |

The tokens are set as inline custom properties on the root (that is how `setTheme` can
swap them without touching the stylesheet), so a host override in a stylesheet has to
outrank an inline declaration:

```css
#terminal .oac-widget {
  --oac-font: "IBM Plex Sans", system-ui, sans-serif !important;
  --oac-radius: 4px !important;
}
```

Override tokens, not controls: a rule written against an internal class name is a rule
against an implementation detail.

Everything the UI standard in `CLAUDE.md` asks of a host is already done: styled
scrollbars, small square swatches, up and down colours on one row, themed checkboxes and
selects, tab lists with glyphs, dialog furniture in the standard places.

Every glyph comes from the draw tier's icon registry: the rail and its flyouts, the menus
and dialogs, the chart type menu and button (each type beside its `chart-<type>` glyph, on
a phone too), and the theme button, a sun on the dark theme and a moon on the light one,
whose tip and accessible name say the theme a click switches to. Since 2.5.10 no widget
file draws a picture of its own, so the registry's grid, overlap and weight checks cover
all of them. Since 2.6.3 tool glyphs show at 20px and chrome glyphs at 16px, both at about a
1.3px line, so the rail reads as one fine set beside the chart. A row of `openMenu` takes an optional `icon`, a chrome icon id, for a host that
builds its own menu the same way, and `placement: 'beside'` opens the menu beside its
button, as the rail's right-click menus do, with the same arrow keys as every other menu.

The last button of the rail (chevrons pointing left, since 2.6.3) folds the rail away and
gives the chart its width; a small tab at the bottom left of the chart brings it back. The
fold is remembered with the rail's other preferences and travels in `getState().rail`.

## Extending the rail with your own tools

The rail is a view of the draw tier's tool registry. Register a tool the way
`openalgo-charts/draw` documents, then name it in `rail.tools`:

```ts
import { createWidget } from 'openalgo-charts/widget';
import { registerDrawingTool, LINE_FIELDS, type DrawingTool } from 'openalgo-charts/draw';

const midline: DrawingTool = {
  id: 'midline',
  name: 'Midline',
  points: 2,
  angleLock: true,
  shortcut: 'Alt+M',
  settings: LINE_FIELDS,
  draw(c) {
    // paint a horizontal line at the midpoint of the two anchors
  },
  distance(x, y, c) {
    // media px from the cursor to the line, or null for a miss
    return null;
  },
};
registerDrawingTool(midline);

createWidget('#terminal', {
  rail: { tools: ['trend-line', 'horizontal-line', 'midline', 'fib-retracement'], favorites: ['midline'] },
});
```

Register before you call `createWidget`: the rail reads the registry once when it
builds, shows only ids it finds there, and drops a favourite it cannot resolve. The rail
labels every button with the tool's `name` and draws a glyph when the draw tier's icon
registry (`DRAWING_TOOL_ICONS`) has one for the id; the built-in 51 all do.
A tool that declares `shortcut` is bound by the widget's keymap and listed in the `?`
panel, and a binding that collides with an existing one is reported rather than
silently overridden. `settings` decides what the drawing properties dialog shows for the
tool: a control appears only for a field the tool's `draw` reads, which is how the widget
avoids ever showing a control with nothing behind it.

## Loading without a bundler

Every tier bundle imports its neighbours by sibling path (`./openalgo-charts.mjs`,
`./openalgo-charts.draw.mjs`), so `dist/` served as-is is enough and no import map is
needed:

```html
<div id="terminal" style="height: 600px"></div>
<script type="module">
  import { createWidget } from '/dist/openalgo-charts.widget.mjs';
  import '/dist/openalgo-charts.indicators.mjs';
  createWidget(document.getElementById('terminal'), { symbol: 'RELIANCE', interval: '5m' });
</script>
```

A page that cannot load modules uses the script-tag build instead: classic scripts for the
base, the indicator and draw tiers and the widget, in that order, and
`OpenAlgoCharts.widget.createWidget`. The widget's file reads the engine and the draw tier
from the `OpenAlgoCharts` global, so there is one engine, and it carries the parts below in
itself rather than fetching them.
Never load `openalgo-charts.widget.mjs` beside the classic base: a module imports its own
second engine.

```html
<script src="/dist/openalgo-charts.standalone.js"></script>
<script src="/dist/openalgo-charts.indicators.standalone.js"></script>
<script src="/dist/openalgo-charts.draw.standalone.js"></script>
<script src="/dist/openalgo-charts.widget.standalone.js"></script>
<script>
  OpenAlgoCharts.widget.createWidget(document.getElementById('terminal'), { symbol: 'RELIANCE', interval: '5m' });
</script>
```

Some of the widget loads on first use. The shortcuts panel, the Layouts menu, the
indicator templates list, the chart data dialog, a chart grid's bar and menus, and the
IndexedDB store a persisting widget reads are not in `openalgo-charts.widget.mjs` but in
files beside it (`openalgo-charts.widget.<part>-<hash>.mjs`), fetched with `import()`
the first time they are needed. A part resolves against the tier's own URL, so `dist/`
or a CDN path needs nothing more, and a bundler splits it the same way. Under a Content
Security Policy, `script-src` must allow the tier's origin, as it already must for the
tier itself; a part's rules join the widget's stylesheet and keep its nonce. A part that
cannot load says so in a toast (the store, on the status line) each time it is asked
for, and the rest of the widget goes on working; a browser keeps a failed module fetch
until the page reloads. While a part loads, a control pressed again asks once, the last
control pressed is the one answered, and a user who has moved on by the time it arrives
(a press elsewhere, Escape, or typing into another field) is not interrupted by it.

A tier file and its parts must come from the same release, because a part uses the
tier's internals and those change from build to build. The hash in a part's name is of
its content, so a new tier file asks for its own parts, never for a copy a cache kept. A
host serving `dist/` itself should serve the tier files, whose names stay the same from
release to release, with revalidation (`Cache-Control: no-cache`), and may cache the
hashed parts for a long time (`max-age=31536000, immutable`). A CDN URL must pin the
exact version, never a range or no version at all. A `script-src` that lists files
cannot name a part either: allow the origin, or the directory as a path ending in `/`.

## Size

Budgets from `.size-limit.json` and measurements from the 2.6.4 build, Brotli, enforced by
`npm run size`:

| Row | Files | Budget | Actual |
|---|---|---|---|
| Widget tier | `openalgo-charts.widget.mjs` | 124.94 kB | 124.94 kB |
| Widget first-use parts | `openalgo-charts.widget.<part>-<hash>.mjs`, eight files | 21.00 kB | 21.00 kB |
| Widget terminal | base + draw + indicators + widget | 364.05 kB | 364.04 kB |

The widget is a tier because of these rows. A host that never calls `createWidget`
downloads none of it, and the base engine's own budget is unchanged. Measure, do not
quote: `npm run size` prints the figures for the build in front of you.

## In a framework

Create the widget in a mount effect, hold it in a ref, and `destroy()` it on cleanup,
the same lifecycle as a bare chart. The widget instance is never framework state: it
owns DOM of its own and re-rendering around it is wasted work.

## Navigation preferences

The widget defaults to 8 CSS pixels per bar. Wider containers show more bars while
preserving candle width. Set `navigation.defaultBarSpacing` to customize the density;
the preference survives load, reset and saved layouts. Resize preserves current zoom.
Pass `navigation: { mousePan: 'both', defaultVisibleBars: 100 }` to
`createWidget` to open on the latest 100 bars. Axes settings expose both
preferences and saved widget layouts retain them. The count controls the initial
view, new symbol/interval loads and Reset view; it does not limit retained
history. Use 0 to fit all loaded bars. Since 2.6.3 mouse and pen pan time alone by
default (`mousePan: 'horizontal'`), so a price scale on auto keeps fitting what is in view
through any drag and every wheel zoom after it, and the wheel zooms about the latest bar
(`zoomAnchor: 'right'`; Ctrl or Cmd with the wheel zooms about the cursor). Pass
`mousePan: 'both'` to drag price as well, which puts the pane on manual scaling, or
`zoomAnchor: 'cursor'`. The engine's own defaults are `'both'` and `'cursor'`. Saved
explicit preferences are retained. Touch gestures are unchanged.

## Live recovery and CSP in 2.1.2

The widget passes the last historical bar as the live subscription seed and
refreshes history on `onResync`. Recovery buffers live bars during the fetch,
bypasses `withBarCache`, merges the observations and preserves the viewport.
Overlapping volumes use the maximum snapshot. Whole-bar merging can retain seed
extrema corrected by history; unseen trades are not replayed.
A failed refresh retains visible history marked stale while live buffering and
reconnect monitoring continue. Call `reload()` to retry with fresh history;
manual reload keeps its usual fit/saved-view behavior. Custom hosts reconcile through
the optional `BarSubscriptionOptions` contract. See the
[live data guide](https://marketcalls.github.io/openalgo-charts/docs/live-data/).

Pass `styleNonce` when the host CSP authorizes widget stylesheets with a nonce.
The injector preserves existing populated host styles and can fill an empty
SSR placeholder. This authorizes the style element only; the host must also
permit the widget's style attributes. See the
[widget CSP guide](https://marketcalls.github.io/openalgo-charts/docs/widget/).
