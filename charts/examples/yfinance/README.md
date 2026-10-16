# yfinance historical demo

Loads historical OHLCV from [yfinance](https://pypi.org/project/yfinance/) and
renders it with OpenAlgo Charts (candles plus volume), showing how to wire any
OHLCV source through a custom `DataFeed`. It is the reference host: the place a
feature is proved usable, not just present.

Custom indicator settings support symbol lookup with a paired exchange,
validated session strings, multiline notes, finite prices and absolute UTC
timestamps. Price and time pick actions hide the settings dialog while the
chart captures a value, then resume it. Invalid drafts remain visible with an
error. Apply commits the draft; Cancel discards it. Mixed-scale studies must
declare the pane and scale for a price pick. These input kinds use native
descriptor settings and require no feed adapter.

The custom host includes linked chart grids, named layouts and indicator templates
stored through the optional workspace tier. Layout changes prepare history before
publication, retain visible storage errors and guard simulated order entry during
replay or a pending workspace switch. The main page does not use the packaged
widget shell; the grid view, `grid.html`, does (see Grid view below).

Choose **Indicators > Examples > Routed signal sample** to add a momentum study in
its own pane whose Buy and Sell plates and 30-bar range box are drawn on the
candles. Those outputs name the price pane; the dots and the latest reading stay
with the histogram. Turn off **Signals on price** in its settings to send the
plates back to the study's pane. The candles are also shaded green or red by the sign
of the momentum: that shading column names the price pane too, and **Momentum
shading** sends it behind the histogram instead or turns it off. Moving the study to
another pane leaves the plates and the shading on the candles, and moving the price
axis to the left takes the plates and the box with the candles; hiding or removing it
takes every routed layer with it.

Choose **Indicators > Examples > Anchored growth sample** to add a path that grows
from one point, a bar time and a price that belong together. It starts two thirds
across the view at that bar's close, where its orange ring sits. Drag the ring to move
the time and the price together; Ctrl+Z, the rail's Undo or the phone bar's Undo takes
the drag back, and Escape during a drag cancels it. In its settings, **Pick point on
chart** sets both from one click and Apply writes them as one change. Each drag and
each settings session is one step of the chart's timeline, so undo walks a pick, the
drags before it and your drawings back one at a time, in the order you made them.
While a drawing tool is active, a press on the ring places the drawing instead.

Choose **Indicators > Examples > Source signal sample** to add the host-owned
2.4.6 demonstration to the focused chart. It alternates Up and Down labels every
12 bars, including gaps in the first plot. Its `markerAnchor: 'price'` keeps those
labels at the displayed price bars; the transparent helper plot contributes no
legend reading. The sample is opt-in and the built-in indicators are unchanged.

Hover its legend and click **Source** to read the exact descriptor factory the
host registers. The dialog identifies the chart, symbol and indicator instance,
including repeated copies on the second chart. `hasSource` enables the button;
`indicatorSource` supplies identity, while the host supplies the text. The viewer
uses `textContent` and offers no editing or execution. Removing its instance or
rebuilding its chart closes the dialog.

**Chart settings > Readout > Legend button size** changes all legend buttons on
the selected chart from 12 to 28 pixels (default 16). Cancel restores the previous
size. Each chart keeps its own choice across chart-type changes, reloads and saved
layouts; named workspace documents store it as `reference.legendIconSize`.

The shared alert editor also uses the selected chart's labelled timezone for
expiry. New drafts start two calendar months ahead; clear the expiry for an
indefinite alert. Saving another field preserves an existing alert's expiry.
The editor keeps its opening timezone throughout the draft.

The toolbar's **Data** and **Objects** controls open a resizable information
dock for the selected chart. Data follows the crosshair and lists the candle
and running study values. Objects groups sources, studies and drawings by pane,
each pane in draw order from back to front, and exposes only actions each object
supports. Drag a row onto the upper or lower half of another, or use Earlier and
Later, to put a drawing behind the series, between two studies or in front, or the
candles over a study; a drop the chart cannot paint is refused. Each chart keeps its own dock
choice and width through rebuilds and saved layouts. A narrow chart shows the
dock as a sheet. The host mounts the library's `mountPanelDock`,
`mountDataWindow` and `createObjectsPanelContent` with a `ChartObjects` model;
it does not maintain a second object tree.

**Change symbol** searches the reference catalog by ticker or description.
The catalog provides a venue or asset class only for entries with explicit
metadata; `/api/history` supplies bars, not an instrument master. When no
catalog match exists, a raw yfinance ticker can still be entered after the
search finishes. The shared picker handles result selection and stale queries.
The shared **Indicators** picker searches categories and manages each running
instance separately. Generated chart and study settings use the shared color
picker, including alpha-bearing values; the drawing palette also offers it.
With a chart focused, typing a letter opens symbol entry and typing a number
opens interval entry. Text fields, dialogs, replay, pending loads, drawing
tools and registered shortcuts retain priority. The reference feed accepts
only the intervals listed in its toolbar.

## Run

```bash
# 1. Build the library bundles (from the package root): the demo imports /dist
npm run build

# 2. Install the one Python dependency and start the demo server
cd examples/yfinance
pip install -r requirements.txt
python server.py                 # http://127.0.0.1:8000
python server.py --port 8123     # another port (the 1.x form, python server.py 8123, still works)
```

Open **http://127.0.0.1:8000/examples/yfinance/index.html**, type a Yahoo Finance
symbol, pick an interval and range, and the chart loads.

Symbol examples: `AAPL`, `MSFT`, `RELIANCE.NS` (NSE), `^NSEI` (Nifty 50),
`BTC-USD` (crypto).

### Without yfinance, or without a network

```bash
python server.py --fixture       # synthetic bars for any symbol; nothing is imported, nothing is fetched
```

Everything else is the same page and the same URL. The server needs only the
Python standard library in this mode, so a fresh clone can run the demo before
`pip install` and without a connection. See [Offline fixture mode](#offline-fixture-mode)
for what the bars look like and how to reach the error states.

### Every flag

| Flag | Meaning |
|---|---|
| `--port N` | Listen on N (default 8000). `0` picks a free port and prints it. A bare positional `N` means the same. |
| `--host H` | Bind address (default `127.0.0.1`). |
| `--fixture` | Serve deterministic synthetic bars instead of yfinance. |
| `--quiet` | No request log. |
| `--self-test` | Run the server's own checks against an in-process fixture server, then exit 0 or 1. |

## The server

`server.py` serves the package root statically (so `/dist` and `/examples`
resolve from one origin, and `.mjs` gets a JavaScript MIME type) and answers
one JSON endpoint. It is the standard library plus yfinance, and yfinance is
imported on the first real request, so static serving and fixture mode work
without it.

Live bars are prices as they traded: the server asks the source for unadjusted
OHLC (`auto_adjust=False`), which keeps its split adjustment but not the
dividend adjustment its default applies to every past bar, so an old candle
matches the exchange's record. Fixture mode (`--fixture`) serves synthetic bars
for the tests and for offline work; its prices are not market data.

A daily chart loads at least five years (about 1,240 sessions on NSE), so it
always holds 500 candles or more where the instrument has that much history;
its range menu offers 5y and max.

```
GET /api/history?symbol=AAPL&interval=1d&period=1y
GET /api/history?symbol=AAPL&interval=5m&from=<utc seconds>&to=<utc seconds>
GET /api/history?symbol=AAPL&interval=5m&period=1mo&session=extended
```

| Parameter | Rule |
|---|---|
| `symbol` | Required. 1 to 24 characters of letters, digits, `.`, `-` or `=`, with an optional leading `^`. That covers a ticker, a venue suffix (`RELIANCE.NS`), a pair (`BTC-USD`), a future or rate (`GC=F`, `EURUSD=X`) and an index (`^NSEI`), and nothing that could be a sentence. |
| `interval` | One of `1m 2m 5m 15m 30m 60m 90m 1h 1d 5d 1wk 1mo 3mo` (default `1d`). |
| `period` | One of `1d 5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max` (default `1y`). |
| `from`, `to` | Optional UTC seconds that pin the window. `to` alone ends the period there; `from` overrides the period's length. Both must be positive, before the year 2100, and `from` before `to`. |
| `session` | `regular` (the default) or `extended`, which adds the source's own pre and post market bars (`prepost` upstream). Extended hours exist only for intraday bars of a US listed stock: a plain ticker of one to five letters with an optional share class, such as `AAPL` or `BRK-B`. |

A success is the `Bar[]` the chart consumes directly, `{ time: <UTC seconds>,
open, high, low, close, volume }`, with any row the source left without a
price dropped (yfinance emits them for suspensions and some holidays, and a
bare `NaN` is not JSON). A failure is `{ "error": <sentence>, "code": <token> }`
with the status that matches, and never a traceback: that goes to the terminal.

| Status | `code` | When |
|---|---|---|
| 400 | `bad_symbol`, `bad_interval`, `bad_period`, `bad_range`, `bad_session` | A parameter failed the rule above. The message names the rule. |
| 400 | `unsupported_session` | Extended hours asked of an instrument or interval the source has none for. Refused rather than answered with regular hours under the extended label. |
| 404 | `no_data` | The source has no bars for that ask: an unknown symbol, or a range it does not serve. |
| 404 | `not_found` | No such endpoint under `/api/`. |
| 429 | `rate_limited` | The source is throttling this address. `Retry-After` says when to try again. |
| 502 | `upstream_error` | The source failed: no network, a changed API, a symbol it choked on. The message is the exception's name and text, truncated. |
| 503 | `not_installed` | yfinance is not installed and the server was not started with `--fixture`. |
| 500 | `internal_error` | A bug in this file. The traceback is printed on the server side only. |

**Cache-Control.** Static files are `no-store`: this is a dev server for a
library you are rebuilding, and the browser's module map would otherwise keep
running the previous bundle after a rebuild. History responses follow the
forming-bar rule from `CLAUDE.md`. A window that could still contain a bar that
has not closed gets `private, max-age=5`, enough to fold the double fetch a
linked second chart makes into one and no longer. A window pinned with `to`
whose last possible bar has closed (`now >= to + one interval`) gets
`public, max-age=31536000, immutable`, because the same URL can never answer
differently. A period request always ends now, so it is never immutable.
Errors are `no-store`.

**gzip.** JSON bodies of 512 bytes or more are gzip-compressed when the
request's `Accept-Encoding` lists `gzip` with a non-zero quality; every JSON
response carries `Vary: Accept-Encoding`. A history body goes to about a
quarter of its size on the wire.

**Quotes and news.** Two more endpoints feed the Watchlist and News panels, and only
with `--fixture`. This server has no live quote or news source, so without the flag
both answer 501 `not_available` rather than making a quote up from the last bar.

```
GET /api/quotes?symbols=AAPL,RELIANCE.NS          (at most 50, each passing the symbol rule)
GET /api/news?symbol=AAPL&limit=20&cursor=<the previous page's nextCursor>
```

A quote is `{ symbol, exchange: "", last, previousClose, bid, ask, volume, time }`; an
instrument the source does not know is left out of the answer, never answered with
zeros. A news page is `{ items: [{ id, headline, source, time, summary, url? }],
nextCursor }`, newest first, with `nextCursor` null on the last page. Both are
`no-store`. A bad `limit` (1 to 50) is 400 `bad_limit`, a cursor that is not one of
this server's is 400 `bad_cursor`.

**Log line.** One line per request on stderr, `time client method path status
bytes ms`, so a slow symbol or a 4xx storm is visible without a debugger.
`--quiet` turns it off.

**Shutdown.** Ctrl+C (or SIGTERM where the platform delivers it) stops the
listener, closes the socket and prints `stopped`. Requests are handled on
daemon threads, so a yfinance call that hangs cannot hold the process open.

## Offline fixture mode

`--fixture` answers `/api/history` for any symbol from a pure function of
(symbol, bar time): the same URL returns the same bytes on any machine on any
day, as long as the window is pinned with `to`. It is what the end-to-end
suite runs against, and what a fresh clone can run before installing anything.

- `session=extended` adds New York's pre and post market (04:00 to 09:30 and
  16:00 to 20:00) on the same grid, so the regular bars are the same
  observations in both series and only the pre and post market bars differ.
- Each symbol has its own base price, drift and volatility, and a seeded random
  walk in trading time (a pure function of symbol and bar time), so two symbols
  never move together and a comparison overlay has something to show. Every bar's
  open is the previous bar's close.
- Bars sit in each symbol's own venue hours, by the rule `src/status.js` reads
  the venue by, so a chart's bars and its session calendar agree: an NSE or BSE
  symbol (and `BANDED`) on weekdays from 09:15 to 15:30 in Kolkata, a US symbol
  from 09:30 to 16:00 in New York, a `-USD` pair around the clock every day. An
  index the page has no hours for keeps the Kolkata session. New York's clock
  changes are spelled out rather than read from a zone database, which some
  systems give Python only with the tzdata package, and the self-test holds them
  to the zone database where one is installed. Daily bars land at the session open,
  weekly bars on Mondays, monthly and quarterly bars on the first of the month,
  all in the venue's own calendar.
- Intraday ranges are clamped to the limits the real source enforces (`1m`
  seven days, `5m` to `90m` sixty days, `1h` two years), so the bar counts
  match a live run. The live source answers an over-long ask with nothing,
  which the server turns into 404 `no_data`; the fixture clamps instead.
- The last bar is the one whose start is at or before now. Its values are
  fixed for the length of the bar rather than moving with every request:
  determinism was the point.

Three symbols are reserved so the page's error handling can be exercised
without breaking a network:

| Symbol | Answer |
|---|---|
| `FAIL` | 502 `upstream_error`, the state a dead source puts the page in |
| `EMPTY` | 404 `no_data`, an unknown symbol |
| `BUSY` | 429 `rate_limited` with `Retry-After: 30` |

The case does not matter (`fail` works too). Every other symbol that passes
the validation rule gets bars.

One more symbol, `BANDED`, is an instrument with a price-dependent tick
schedule. Its bars move around 100 and every price lies on a 0.01 grid below
100 and a 0.05 grid from 100, the synthetic rules `src/ticks.js` hands the
library as host-supplied metadata. Neither the server nor the library treats
these rules as a default for anything else.

Quotes and news are deterministic too. A quote is the fixture level at its own
two-second step, not the close of the last bar, with the previous trading day's
session close as its reference. News arrives on a per-symbol schedule, about three
stories in five 90-minute slots, 60 slots deep; the cursor names a slot, so older
pages do not move with the clock. One headline template carries `<b>` markup and a
`javascript:` link on purpose: the reader must show the first as text and refuse
the second. `FAIL` and `BUSY` answer news with their errors and `EMPTY` with an
empty page; all three are left out of quote answers.

`python server.py --self-test` starts a fixture server on a free port in the
process and checks the contract above: the bar shape and grid in each venue's
hours, New York's clock changes, determinism
across two server instances, every validation and error path, that a bug in
the source is a 500 with no traceback in the body, the cache and gzip
headers, static serving, the log line, and that shutdown returns promptly and
frees the port. It also checks the quote and news endpoints: unknown symbols left
out, quotes that are a pure function of symbol and step and differ from the last
bar's close, news pages that follow the cursor to the end without repeats or
clumped headlines, the markup and script-link item, validation, and the 501 answer
without `--fixture`.

## Layout

The demo is a plain native-ESM host: no bundler, no build step, relative
imports, and the library imported from `/dist/openalgo-charts.mjs` and its
tier files exactly as a page would.

```
examples/yfinance/
  index.html          markup only: the shell, the dialogs, the menus
  grid.html           the grid view: the widget tier's chart grid over the same feed
  styles.css          every rule the pages use
  server.py           static server, /api/history (yfinance or fixture), the self-test
  requirements.txt    yfinance, the one dependency, needed only outside --fixture
  src/
    alerts.js         alert controller ownership, shared editor/list and local event delivery
    timeline.js       labelled sample timeline events, group filters and event details
    main.js           composition root: the shared app state, render(), load(), boot
    ui.js             el(), number and text formatting, the candle palette, toasts, the overlay stack (focus trap, one Escape per layer), the chart loading, empty and error card, the theme switch
    hover.js          the one hover label every icon-only control shares
    intervals.js      interval registry, the picker's codes, period clamping
    goto.js           Go to a date or range: the shared navigator, loading a longer period
    feed.js           YFinanceDataFeed and its typed errors, the bar cache wrapper, the cache menu
    transforms.js     the chart type select mapped onto the chart's own transforms (Renko, P&F and the rest), and the options kept per transform
    box-settings.js   the point and figure and Renko settings dialogs: colours, box size and method, reversal, prices
    expression.js     symbol arithmetic: the operator keypad, leg fetching, folding
    status.js         venue, session hours, long names, the status-line readings
    timezone.js       the chart zone the demo carries across a rebuild
    axis-chrome.js    clock and countdown, status-line and trade palette choices
    volume.js         volume visibility and the symbol legend row
    bracket.js        the bracket panel: entry, target and stop pills
    orders.js         resting orders, market fills, the net position, trade state
    ticks.js          host instrument metadata: the tick schedule, and the venue hours the space past the last candle follows
    account.js        the sandbox broker: account figures and selection, preview, durations, native close, reverse and brackets
    indicators.js     the indicator picker and the generated settings form
    indicator-input-controls.js typed field validation, symbol search and chart picking
    indicator-source.js the opt-in sample and chart-owned read-only source dialog
    anchored-study.js the opt-in sample whose anchor time and price are one point, with a handle
    chart-settings.js the chart settings dialog, built from chartSettingsSchema()
    compare.js        multi-symbol comparison
    replay.js         market replay: the bar picker and the transport
    replay-timing.js  interval and local-calendar candle availability
    snapshot.js       save or copy the chart as a PNG
    pane-target.js    selected chart and captured request ownership for host actions
    split.js          the linked second chart and its divider
    link.js           the link-group switches
    clipboard.js      the drawing clipboard and its chords
    menus.js          the right-click menu (including Move pane up/down and Collapse pane), the price-axis menu, the popup menu
    session-marks.js  host-owned price marks: read-only, never saved, not listed
    host-study.js     a host-owned study the user cannot remove, configure or move
    session.js        regular or extended trading hours as the engine's data variant
    toolbar.js        the shell bar, chart types, chart-only full screen
    rail.js           the drawing rail: groups, pins, magnet, stay mode, selection controls, keyboard
    rail-flyout.js    the rail's flyout, context menu and dwell tooltip
    properties.js     the floating properties bar, generated from drawingSettingsSchema
    level-editor.js   the level editor popover for ladder tools (fibs, channels, fans, Gann)
    text-editor.js    inline text editing for a drawing, laid over the painted text
    drawing.js        the drawing controller, the tool picker, the clipboard chords
    drawing-scope.js  drawings per symbol: one document per chart and symbol, swapped with the symbol
    persist.js        the layout document, its schema and migrations, storage, export and import
    workspace-document.js  portable named-layout snapshots and reference-host support validation
    workspace-transition.js  cancellable history preparation and guarded publication
    workspace-host.js  reference chart ownership, pending guards and transition wiring
    workspace-catalog.js  named saves, revision conflicts, autosave ownership and storage recovery
    workspaces.js     named-layout dialog, startup selection, autosave and portable files
    grid.js           the grid view's start-up: the library's grid bar (layouts, maximize, link groups, capture, saved desks), the bar under the charts, import and export, panels
    grid-view.js      the grid view's feed adapter, layout hand-off and document helpers
  tests/              vitest specs for the modules that can run without a browser
  vitest.config.ts    the config those specs run under (see Tests)
```

Shared mutable state (the chart, the loaded bars, the orders, the replay, the
second chart) lives on one `app` object that `main.js` creates and hands to
every module's `init*(app)`. Nothing is a global: a module keeps the reference
it was given and reads `app.chart` rather than a copy, because a chart-type
switch destroys and rebuilds the chart and a copy would go stale. The two
operations everything reaches back to, `load()` and `render()`, live in
`main.js`; modules call the loader as `app.load()`.

Module top level is declarations only. Listeners, the animation loop and the
link group are created inside the `init*` functions, which `main.js` calls in
the order the page registers them, so the import graph can have cycles (the
toolbar opens the compare dialog, the compare dialog refreshes the toolbar)
without any module reading another's binding before it exists.

Opening the page with `?test=1` puts `window.__oac = { chart, draw, app }` on
the window for the end-to-end suite; `chart` and `draw` are getters, so they
follow a rebuild.

## Grid view

`grid.html` is the second page of the reference host. It builds the widget
tier's chart grid (`createChartGrid`) over the same `/api/history` feed, so each
chart is a complete widget with its own top bar, loading status and retry.

- The grid bar over the charts picks the layout (one chart to sixteen), maximizes,
  links charts in named groups, captures every chart and keeps saved desks. The
  page's own bar keeps the way back, the layout file (import and export) and the
  status line.
- Click or focus a chart to make it active: it gets the outline and the keyboard.
  Drag a gap to resize, or focus it and use the arrow keys; double click evens it.
- Below 640 CSS px only the active chart shows, with tabs to switch.
- Each chart's type menu lists the in-chart transforms under a Transforms heading (the
  page loads the transform tier), and a chart set to Renko, point and figure or any other
  transform forms its elements from the bars it loads; a reload keeps the choice.
- The grid keeps its desk in IndexedDB (the widget's `openalgo-charts-widget`
  database, namespace `yfinance-grid`); a desk an earlier release left in
  `localStorage` is copied in on the first visit. A first visit opens AAPL, MSFT,
  RELIANCE.NS and ^NSEI in a two by two grid. A saved layout the page cannot
  restore is kept, and the status line says why.
- One bar under the charts acts on the active chart: ranges, Go to, the market
  status from each chart's venue calendar (`sessionCalendarFor`), the clock and the
  scale toggles.
- The grid bar's Layouts control saves and opens whole desks, kept in the
  `yfinance-grid` workspace database; the layout that was active reopens after a
  reload, unless the main page has just handed a layout over.
- Each chart loads the history period its layout saved (`historyPeriod`, the
  main page's range) through the grid's `feed` function, when its interval can
  serve it and, for a daily chart, when it reaches five years. Otherwise, and for
  a chart with no saved period, it loads its interval's usual one (1m 5d; 5m, 15m
  and 30m 1mo; 1h 6mo; 1d 5y; 1w 10y). A chart keeps its period when its
  interval changes, for when it changes back, and a preset copies the active
  chart's period to the charts it adds. The grid writes
  the periods back into its saved layout and exports. No older history is paged,
  since the server answers by period.
- Each chart's top bar opens the Watchlist and News panels in its own dock, through
  the widget's `watchlist` and `news` options, which the grid passes to every chart.
  They share the main page's list store, one quote poll for every visible row and
  the same `/api/news` source; choosing a row charts it in that chart, and the symbol
  link carries it to the others when it is on.
- Import accepts a portable workspace document or payload whose charts use those
  intervals (`1wk` from the main page opens as `1w`) and periods the server knows.
  It is validated in full, then applied all at once; on failure nothing on screen
  changes and the status line says why. Comparison symbols are refused, since a
  widget draws none, and so are the main page's folded calendar frames (`1mo`,
  `1q`).

The main page draws one chart or two side by side. Importing a layout with more
charts, or with rows, into its Layouts dialog offers **Open in grid view**, which
hands the document over through `sessionStorage` (`oac-grid-handoff`). The main
page checks first that the grid view can open it, and refuses there otherwise. The
link menu on the main page also opens the grid view. Open `grid.html?test=1` to
expose the grid as `window.__grid` for the end-to-end suite.

A one or two chart layout exported from the grid view opens on the main page
through the same Layouts import. The widget's `1w` becomes the page's `1wk`, the
per-chart theme is dropped because the main page has one theme for the page, and
each chart opens fitted to its data with its studies and drawings, because the
saved window counts the grid view's bars. A saved history period the main page
has no range for opens as the nearest range it has (`1d` and `5d` as `1mo`, `3mo`
as `6mo`, `ytd` and `2y` as `1y`, `10y` as `5y`), and every saved period is then
clamped to what the chart's interval can serve, as the main page clamps its own.
The main page still refuses what it cannot show, such as a `1m` chart or two
charts with different drawing magnet or stay settings.

## How it connects

```
yfinance (Python)  ->  server.py /api/history  ->  YFinanceDataFeed.getBars()  ->  series.setData()
```

- `server.py` maps the yfinance DataFrame (or the fixture) to the chart's
  `Bar` shape and answers with the status codes above.
- `src/feed.js` defines a small `YFinanceDataFeed` implementing `getBars()`,
  the same broker-agnostic `DataFeed` interface the OpenAlgo adapter uses,
  turns the status codes into typed errors the shell can act on, and wraps the
  feed in the engine's bar cache. Swapping data sources is a different
  `getBars()`.

## Navigation

Press and hold the plot to show a grabbing hand, then drag left, right, up or down.
Mouse and pen movement stops immediately on release, including outside the chart.
Touch flicks retain momentum. Mouse and pen drags pan time and price by default. In Settings, open
Axes, then Navigation, and choose **Horizontal only** for time-only movement.
An existing saved horizontal preference stays intact after upgrading; select
**Mouse drag > Time and price** to restore two-axis panning.
Touch continues to pan both axes. Drag the time axis left to expand bar spacing or right
to compress it.

The demo inherits wheel behavior from the engine without host wiring. Pixel, line and
page deltas are normalized and applied proportionally. A vertical wheel over the plot
zooms time; horizontal input or Shift-wheel pans it. A wheel over the visible price axis
scales price at the pointer and makes that scale manual. Browser pinch input reported as
Ctrl-wheel or Meta-wheel zooms at the pointer. Plot drags remain two-axis by default.

Automatic price ranges ease while navigation reveals new extrema. When the operating system
requests reduced motion, both the main and split chart constructors disable zoom and autoscale
animation. A manually panned or scaled price axis remains authoritative until Reset view or
another explicit autoscale action. An older navigation animation cannot overwrite a
programmatic viewport replacement, primary data replacement, reset or teardown.

The same Navigation group offers **Default visible bars (0 = all)**. `0` fits all loaded
bars; a positive value targets the newest N loaded bars plus four empty slots on the
right, within the available data and bar-spacing limits. Changing it applies the new
default view immediately. The navigator's **Reset view** button, `Home` / `0`, and the
default double-click action restore that view and price autoscale.

This is a viewport setting, separate from the demo's history lookback. It does not change
the `/api/history` request or remove loaded bars, so older data remains available by
panning. Hosts can set it through `createChart(el, { navigation: { defaultVisibleBars: 120 } })`
or `chart.setNavigationOptions(...)`; `chart.fitContent()` explicitly fits all loaded
history. Navigation settings are included in the schema's read/apply helpers and chart
state. A host that reapplies an explicit viewport after loading data controls that view.

Fresh charts use `navigation.defaultBarSpacing: 8` for consistent candle density
across desktop and mobile. The Axes setting **Default bar spacing (0 = use bar count)**
stores CSS pixels per bar and applies to initial loads and reset. Editing the visible-bar
count switches back to count mode. Existing saved navigation preferences are retained.

This example is a custom host around the DOM-free engine and draw tier. Its responsive
controls belong to `examples/yfinance`; it does not use the packaged widget's
`WidgetOptions.mobile`. At 900 CSS pixels or less, or with a coarse primary pointer at
most 960 pixels wide and under 600 tall (a phone on its side), the desktop drawing rail yields to a bottom touch bar and the top toolbar
becomes one scrollable row. A tablet or touch laptop keeps the rail only when it is wider
than 900 pixels, so a tablet in portrait (820 pixels, say) gets the touch bar. Every touch bar control is at least 44 CSS pixels high, and
any coarse pointer grows the other controls to 40 pixel targets. The native drawing picker exposes
the registered tools, followed by Cursor, Undo, Redo, Magnet, Zoom out, Zoom in and Fit.
Drawing actions use the existing controller and navigation uses the chart's public logical
range and reset APIs. In split view the controls act on the last plot touched. Rotating or
resizing changes only the CSS layout, so loaded bars and drawings stay in place.

### Bottom bar

The widget tier's bottom bar (`mountBottombar`) sits under the stage and acts on the
focused chart: preset ranges, **Go to**, the market status, a clock in the chart's
timezone that opens a timezone menu, and the Auto, Log and Percent scale toggles. A range
picks the nearest interval the page offers among those with a history period that
reaches its first session, and the shortest such period, then places it; a range on the
history already loaded only moves the view, and a range wider than the plot keeps its
latest bars in view. A timezone picked there survives the next rebuild. Session shading
(`attachSessionShading`) is attached to each chart as it is built.

Where the bar shows, its **Go to** and its clock are the page's only ones: the toolbar
keeps its **Go to** and the chart its corner clock for the phone shell, which hides the
bar, and both follow the bar as a window crosses the phone rule. The Corner clock switch
in the chart settings overrides that, and the choice is kept in `localStorage`.

### Go to a date or range

**Go to** in the bottom bar (in the toolbar beside the history range, in the phone
shell) opens the widget tier's go-to panel for the selected chart; while the chart's
history is still loading it says to wait instead, and after a failed load that there is
no date to go to. **Date** centres one date at the
current zoom; **Range** fits two dates or date and time pairs. Times are read in the
chart timezone. When the date is older than the loaded period, the page loads the
shortest longer period that reaches it (the range menu shows the result), then places
the date once that load has been accepted. That load rebuilds the chart, and the panel
with it, so the page opens the panel again on the new chart, at the control it was
opened from (the toolbar's **Go to** when a narrower window has hidden the bar
meanwhile), to carry the request through: an interval
that cannot serve an older period reports there where history starts. Daily and
longer frames take a date alone, since a time could not change the bar it names.
Closing the panel while history loads drops the request, and the view stays where
it was; so does a pan or zoom on the chart while the longer period loads. Replay
never loads history, a symbol or interval change cancels a pending request, and
the linked second chart follows the placement by time. The navigation rules are
the widget tier's `DateNavigator`; only the period loader and the pan and zoom
watch in `src/goto.js` belong to this page, since only the page knows which view
moves are its own.

## What each module proves

The engine ships no DOM, so every control here is host code; each module
exists to show one engine surface carrying real use, not just being present.

| Module | Proves |
|---|---|
| `expression.js` | A symbol box holding arithmetic (`AAPL/MSFT`, `NSEIX:NIFTY1!/NSE:RELIANCE+NASDAQ:META`) charts the result. `parseExpression` names the legs before anything is fetched, so exactly those are loaded, in parallel, with the first failure winning: a ratio missing a leg is not a chart with a gap. `evaluateExpression` folds them onto the first leg's time grid, gapping any bar the others did not trade rather than carrying a stale price forward. Closes are exact; a high and low can be bounded by interval arithmetic, which is offered rather than assumed because the bound assumes each leg hit its extreme at the worst possible moment. |
| `feed.js` | A `DataFeed` is one method. The bar cache wrapper (`withBarCache`) keys on symbol, exchange, interval and the data variant, snaps `from` to the bar grid so a reload inside the same bar hits, stops `to` at the last seen bar while the venue is shut (for an extended-hours chart, shut means outside its pre and post market too), and refetches only the forming bar. The cache holds back a bar that has not closed, so a warm answer that ends before the newest bar this page has already shown (the forming candle, or the day's candle after the close) is asked of the wire again: the page has no live subscription to supply that bar, and an older close would stand as the last price. A 404, 429 or 5xx becomes a typed error (`NotFoundError`, `RateLimitedError`, `NetworkError`) with a deadline and one retry, so the readout can say "check the symbol" or "try again in a minute" rather than printing whatever the server wrote. A staleness badge says when the newest bar is older than the venue's clock allows, on the clock of the chart's session: an extended-hours chart can go stale in the pre and post market. |
| `intervals.js` | The interval registry accepts codes the built-in grammar does not (`1wk`, a calendar month, a quarter). Monthly and quarterly bars are folded from daily ones through `bucketStartOf`, so a month runs first-to-first in the chart's zone and February is 29 days long in 2024. Ranges are clamped to what the interval can serve. |
| `history.js` | One undo timeline per chart through the widget tier's `ChartHistory`: a study added or removed (with its settings, pane and scale), its settings, the chart type, the price scales, pane moves, folds and heights, and drawings, in the order they were made. Ctrl+Z and Ctrl+Y and the mobile bar walk the focused chart's; the drawing toolbar's Undo and Redo and the rail's walk the main chart's, as the rest of that toolbar and the rail act on the main chart. The study settings dialog is one step per session, however many tabs commit its form, and an appearance change a linked chart applies from the other one is never a step of its own. The chart is rebuilt on every load and type switch, so the timeline lives on the app and each new chart is attached to it; the type switch itself is recorded as a command that rebuilds again. The chart settings dialog is one step per session, and a Cancel leaves none. Comparisons, the volume row and a loaded layout are the demo's own and go through `ignore`; a loaded layout starts a new timeline. No undo writes bars, fires an alert or places an order. |
| `indicators.js` | The picker is built from `registeredIndicators()`, so built-ins and the host's opt-in example appear grouped by category. The gear opens a form generated from the descriptor's `inputs`; the same code renders MACD, Bollinger or your own indicator. An input's `visibleWhen` and `activeWhen` are read against the drafts on every committed edit with the widget's own `inputStates`, so a row appears, leaves or greys out as the settings it depends on change (a number box commits as the widget's does, clamped to its bounds, a blank one getting its last value back); a hidden draft is kept, an invalid hidden one never blocks Apply, and the change is announced in a polite live region. Inputs sharing an `inline` id sit on one row. An `interval` input, such as the Timeframe of a built-in moving average, RSI or MACD, is a select of Chart and the intervals the page serves, and a saved code outside that list stays an entry of its own. On a transformed chart the form leads with Compute on (Chart bars or Underlying bars). A study that stops drawing (a timeframe refused on Renko bricks, a calculation that fails) says why on the status line and in a toast, once per new reason. |
| `indicator-input-controls.js` | Validates typed drafts and connects shared symbol lookup and chart picking to the reference modal, preserving its Apply and Cancel behavior. |
| `indicator-source.js` | Registers the Source signal sample and resolves source requests against the emitting chart and live instance. The read-only dialog shows the actual host factory and closes when its owner is removed or destroyed. |
| `anchored-study.js` | Registers the Anchored growth sample, whose anchor time and price are one point (`timeKey`) with a handle on the chart (`anchor: true`): the settings form picks both from one click, and the drawing controller draws the ring, commits a drag as one settings change, and hands the step to the chart's timeline (`history.js`), which walks it with the drawings. `indicators.js` seeds a new sample at a bar in view, since its defaults cannot know the loaded history. |
| `routed-study.js` | Registers the Routed signal sample: a momentum histogram in its own pane whose Buy and Sell plates, range box and momentum shading name the price pane (`overlay: true`), while its crossing dots and "Now" label (`plot: 'momentum'`) stay with the histogram. The Signals on price input sends the plates back to the study's pane; Momentum shading sends the shading there as a column naming no target, or turns it off. |
| `canvas-tips.js` | Hover labels for the controls the chart paints on its canvas: a legend row's eye, gear and cross and the close box on an order or position line have no element to carry a name, so the chart's `hover` id raises the shared tip at the pointer ("Hide RSI", "Remove TSLA", "Cancel order"). |
| `chart-settings.js` | The settings dialog is generated from `chartSettingsSchema()`, including the paired up and down colour control on one row, and a control the current context cannot back is drawn disabled with its state visible. |
| `transforms.js` | Heikin Ashi, Renko, Range Bars, Line Break, Point and Figure and Kagi, applied by the chart itself (`setSeriesTransform`, through `addSeries(..., { transform })`): the series is fed the raw bars, the chart forms the elements live, and a replay shows bricks forming bar by bar. A size left out is taken from the loaded history. Point and figure and Renko are drawn with the options their settings dialogs keep, one set per transform, so Renko set up once is still set up after a detour through candles; until then point and figure opens on a box of one ATR(14) with a three box reversal over highs and lows, and Renko on a fixed brick sized from the history over closes. New options form other columns, so the view is fitted again; the same options keep it. Studies stay on a transformed chart, and each one's settings lead with the bars it computes on: the chart's elements, or the underlying bars read at the bar each element formed on. |
| `box-settings.js` | While point and figure or Renko is drawn, a settings button sits beside the chart type. Its dialog has the up and down colours on one row (X and O columns, or up and down bricks, a brick's border taking its colour too), percent presets that set the Percent method at that value, a size with its method (Absolute, in price, 0 sizing it from the history; Percent of price; ATR, a multiple of the 14-bar ATR; ATR %, a percent of it), a reversal of 1 to 10 boxes for point and figure, and Close only or High and low. Nothing applies until OK: new options rebuild the chart as one undo step, carrying any new colours with them, and colours alone recolour it in place as a step of their own. Cancel, the close button, Escape and a click outside write nothing. An option changed from the chart settings dialog's Price tab is kept the same way. |
| `volume.js` | Volume rides an overlay price scale (`priceScaleId: ''`) inside the price pane, pinned to the bottom fifth, so the right-hand axis stays a clean price ladder. It hides and shows from the legend eye and the right-click menu, and the choice survives a reload and a chart-type switch. |
| `status.js`, `axis-chrome.js`, `timezone.js` | The status line, the clock and the countdown are fed by the host: venue, session hours by IANA zone (never a fixed offset) handed to the library as a `SessionCalendar` whose phases give the market status (`venueCalendar`; a closed date listed in `SESSIONS` reads "Market holiday"; the phase is asked once and held until it changes), and long names. A chart on extended hours reads "Pre-market" or "Post-market" while its extra bars are arriving rather than "Market closed". The chart zone is a runtime setting the demo carries across a rebuild. |
| `orders.js`, `bracket.js` | Chart trading: right-click for single orders, Buy and Sell brackets with OCO target and stop, drag any line to re-price it, and per-symbol trade state that survives a symbol switch. |
| `ticks.js` | Price-dependent ticks supplied by the host. Load `BANDED` in fixture mode: it trades around 100 with a 0.01 tick below 100 and a 0.05 tick from 100 (synthetic rules, not any venue's). Right-click prices, dragged order lines, dragged price alerts, market fills and every bracket leg snap to the band they land in, the status line names the tick in force, and a bracket exit stays one tick of its own band from the entry as it crosses the boundary. The rules are `InstrumentMetadata` with `tickBands`, validated by `Instrument` before anything snaps to them, and the price axis takes the instrument's `priceTick`, the grid both bands lie on. The host hands the schedule to each chart with `chart.setTickSchedule`, which is what rounds a dragged alert by band. Every other symbol keeps two-decimal order prices. The same module gives each chart its venue's calendar from `status.js` (`venueCalendar`, through `dataLayer.setSessionCalendar`), pre-open and post-close included, which the bottom bar's market status and the session shading read; the future is laid out in the regular session only, so on an intraday chart a drawing placed past Friday's last candle ends on Monday's session bars; crypto and venues without hours keep the median bar spacing, and there is no holiday list, the same limit the status line states. |
| `account.js` | The Account button opens a sandbox broker: the trade tier's `OrderEngine` and `AccountManager` against a `FakeBroker` with account ledgers, in analyzer mode. The widget tier's account summary shows the selected account's equity and margin and switches account; a live account the provider also offers is never listed. Place stays disabled until that exact ticket is previewed, durations (DAY, IOC, GTC, GTD with an expiry) and leverage are sent only because the provider declares them, and Close, Close part, Reverse and Place bracket are the provider's own commands, never an opposite order. Drop connection marks the figures stale; Reconnect reads the provider's order history for every account the panel has written to and settles every write from it (a lost answer by the token the provider echoes, a write the history never mentions released), so the legs of a bracket whose entry has filled stay live orders, before reading the account again. These orders are separate from the page's own simulated orders. |
| `replay.js`, `replay-timing.js` | One replay transport drives the captured chart or all captured charts from a shared availability clock. Scope controls appear in the picker and transport. Finer history uses separate request slots and each chart's captured instrument, interval and timezone. Cancellation discards late responses; exit restores data and viewports. A coarse candle forms from a contiguous prefix of finer observations, held inside the candle it closes on. Finer history is asked for only as far back as the source keeps it (five days of 1-minute bars under a month of 5-minute ones). A candle with no finer history forms along a simulated path from its open to the nearer extreme, the other extreme and its close, at the finer rung's pace (`REPLAY_SIMULATED_STEPS`), and the replay bar marks those steps Simulated. |
| `compare.js`, `split.js`, `link.js` | Each selected chart owns its comparison symbols, scale mode, hidden rows and history requests. Each source has an independent scale, rebased at the first visible timestamp shared by all visible sources. Missing overlap shows "No common starting bar" and draws gaps. Replay readouts withhold forming comparison closes. The dialog retains its owner across focus changes; changing or closing a chart cancels stale loads. Source failures remain visible with Retry. The linked second chart has independent switches for crosshair, viewport, symbol and interval. Interval sync is off by default. |
| `drawing.js`, `rail.js`, `rail-flyout.js` | The 2.0 drawing model from the host's side: the controller, the tool picker built from `BUILTIN_DRAWING_TOOLS` with the tier's own icon sprite and cursors, keyboard chords from `drawingShortcuts()`, and a rail whose flyouts and tooltips are host chrome built from the shipped glyphs. The toolbar's Del, Clear, Undo and Redo are off whenever pressing them would do nothing: Del and Clear leave read-only drawings alone, and Undo and Redo follow the main chart's timeline (its `ChartHistory`'s `canUndo()` and `canRedo()`, the controller's own before the chart has one). |
| `drawing-scope.js` | Drawings per instrument from the host's side: `InstrumentDrawings` over `webStorageDrawingStore`, one per chart. The chart's data context names the symbol, and the helper swaps the drawings as it changes; the host only chooses the store and passes `prefer: 'live'` when it rebuilds a chart from the state of the one it replaces. A layout for another symbol goes to that symbol through `setDocument`. See Persistence. |
| `properties.js` | The floating properties bar is generated from `drawingSettingsSchema`, which declares only the fields a tool's `draw` reads: a field in the schema is a control with something behind it, a field absent from it is a control not shown. With several drawings selected it edits the fields their schemas share, as one undo entry. A read-only selection shows "Read-only" and a Duplicate button instead of controls the controller would refuse. For text, rectangle, ellipse and table the schema's `space` field becomes a pin toggle: pinned, the drawing keeps its place on screen through pan and zoom and scales with the chart, and unpinning puts it back on the bars under it. The bar and the inline text editor place themselves by `draw.screenPoints(id)`, since a pinned drawing has no time and price to map. |
| `host-study.js` | Study policies from the host's side. **Add protected VWAP** in the right-click menu adds a VWAP with `policy: { removable: false, configurable: false, movable: false }`. Hide it, read it and raise an alert on it as usual; its legend row has no gear and no close button, its Objects dock row has no remove, settings, move, Earlier or Later and does not drag, its chip has no remove button, and the settings dialog and menu rows say it is protected. The policy is saved with the layout, so a reload brings the study back protected, and importing or loading a layout keeps it (a layout file's own restricted studies are left out, `untrustedStudies` in `persist.js`); a saved indicator template leaves it out, so applying one never copies it. If the host locks a study while its settings are open, Apply and Reset say so instead of closing as if they had applied. The same row, now **Remove protected VWAP**, takes it away with `removeIndicator(id, { force: true })`, the one call in the host that overrides the policy. |
| `session-marks.js` | Drawing policies from the host's side. **Mark ... for this session** in the right-click menu places a dashed price line with `policy: { editable: false, persistent: false, listed: false }`. Select it to read it, copy it, duplicate it into your own drawing or raise an alert from it; it cannot be dragged, nudged, restyled, cut or deleted, undo does not remove it, it is left out of saved layouts and it is absent from the Objects dock. The host keeps the marks per symbol for the life of the page and puts them back, with their ids, after every chart-type switch, reload and layout restore. **Clear session marks** removes them with `removeMany(ids, { force: true })`, the one call in the host that overrides the policy. |
| `session.js` | Trading session as a data variant. The session menu beside the range offers regular hours and, for intraday bars of a US listed stock (the one place this source has them), extended hours: the source's own pre and post market bars, asked for with `session=extended` and never derived from the regular series. The feed declares what it serves through `dataVariants`, so a request for extended hours anywhere else is refused before it is sent and the chart says so, with a button back to regular hours, rather than showing regular bars under the extended label. The session is part of the bar cache key, the chart's data context, comparisons (asked for in their chart's session), replay's finer history, the saved layout and named workspaces. In fixture mode extended hours are New York's pre and post market, the same regular bars in between, byte for byte on every run. |
| `clipboard.js` | One in-memory clipboard shared by both charts' controllers, so copy here and paste there works even when the browser refuses the OS clipboard; the OS read is bounded so a paste never hangs on a permission popup. |
| `level-editor.js` | A ladder tool's levels (retracement, extension, channel, fan, time zones, the Gann pair) edited one row each: enable, ratio, colour, label, add, remove, reset. Every edit is one undo entry through the controller. |
| `text-editor.js` | Inline text editing over the painted text, sized by the same rules the text tool paints with, with every pointer and key event stopped at the box so the chart under it does not pan. |
| `menus.js`, `toolbar.js`, `hover.js` | Host chrome to the standard in `CLAUDE.md`: styled scrollbars, no native form controls on a dark panel, real tooltips that flip inside the window, and dialog furniture in one arrangement. The right-click menu offers **Move pane up** and **Move pane down** over any pane (`chart.movePane`, the price pane included) and **Collapse pane** and **Expand pane** over a study pane (`chart.setPaneCollapsed`), on either chart of a split. |
| `snapshot.js` | `chart.takeScreenshot()` saved as a PNG or copied to the clipboard, with chart branding, an enabled watermark and the replay mark in the image because they are on the canvas. |
| `pane-target.js` | Captures the selected chart and request for host actions. A menu cannot act on a rebuilt chart or changed instrument, and asynchronous image export retains its original filename. |
| `persist.js` | A versioned layout document with migrations, quarantine instead of deletion, memory-only degradation when storage refuses a write, and export and import as a file. An imported file, here or in the Layouts dialog, loses every drawing `policy`: a policy is a host's restriction on its own drawings, and one arriving in a shared file would plant a drawing no control here could remove. See the next section. |
| `workspace-document.js` | Converts the full reference snapshot to the optional workspace tier and back. Preserves source settings, study identities, anchored alert state, comparison settings and split geometry. Rejects settings or geometry this host cannot represent before any live restore. Named catalog controls are a separate host layer. |
| `workspace-transition.js`, `workspace-host.js` | Prepare every chart's raw history before changing the displayed workspace. Source changes, cancellation and failed writes leave the current charts intact. Synchronous installation failures restore the previous raw histories and configuration, including transformed charts. Pending switches pause alerts, replay entry, autosave and simulated order entry. |
| `workspace-catalog.js`, `workspaces.js` | Bind the workspace repository to prepared chart publication and the Layouts dialog. Serialize named saves, retain recent ordering, coalesce active-layout autosaves, and reject unacknowledged revisions from another session. Selection failures compensate storage with a new atomic revision. Startup restores the saved named document; recovery does not overwrite it with autosave disabled. |
| `indicator-templates.js`, `templates.js` | Capture repeated studies with parameters, styles, visibility and pane grouping. Apply shared replace/append planning to the captured chart while preserving drawings and valid alert anchors. Save named templates in the same revision-aware catalog as layouts, with explicit application after import. |
| `chart-data.js` | Download the captured chart's loaded OHLC/volume/OI, study plots and eligible comparison closes through the shared CSV serializer. Reject obsolete/loading owners and release file resources on success or failure. |
| `chart-data-controls.js` | Capture a study checklist and visible time bounds, validate custom UTC bounds, and choose source or display alignment before download. |
| `alerts.js` | The Alerts toolbar button opens the focused chart's lifecycle list and source editor. Price, study plots, supported drawing levels and registered candle conditions use the same controls as the packaged widget. Local notices display fired events; the demo does not send notifications or orders for an alert. |
| `timeline.js` | The Events menu enables labelled sample events, clustering and group visibility. Click a marker to read its details: the sample results event carries rich content (a heading, emphasis, a link and a list whose markup stays text), and **Mark on chart** draws a vertical line at the event through the popup's `actions` option. These are demonstration events, not a company calendar feed. |
| `market-panels.js` | The Watchlist and News buttons open the widget's panels in each chart's dock. Named lists live in IndexedDB through the workspace tier's `WatchlistRepository`, one store for both charts, with a first list on a first visit. Quotes come from `/api/quotes` only, through one shared poll for every visible row's stream; a failed poll reports the stream as reconnecting, so the rows go stale until the next good answer. An arithmetic symbol has no quote and shows `n/a`. The watchlist sort sits in `localStorage` under the `yfinance-panels` namespace, so it survives the dock rebuild every symbol load causes. News pages come from `/api/news` with the server's cursor. Without `--fixture` the endpoints answer 501. The first 501 is the page's only quote request: from then on the quote source answers every snapshot and poll with that error itself, each row shows `n/a`, and the status line reads "Quotes disconnected." with no claim about values shown. The news panel shows the server's message. |

### Analysis and linking in 2.5.2

The Volume studies drawing group contains Anchored VWAP (one anchor) and Fixed
Range Volume Profile (two anchors). Move their anchors and open drawing properties
to change the price source, bands, rows or value area. Profiles estimate volume
from candle ranges. Missing volume and incomplete loaded history are labelled.

Open two charts, select the same ticker, then enable **Drawings (same instrument)**
in the linking menu. Different intervals are supported. Use **Share existing
drawings from selected chart** for drawings made before linking. Appearance has
its own switch for supported chart settings. Both switches start off. The feed
namespace used for drawing matching does not change saved alert scopes.

The Events button opens sample timeline controls. Enable **Show sample events**,
then click a marker or clustered count to read details. Group filters include
child groups. The sample results event shows rich details, and **Mark on chart**
draws a vertical line at the event on the chart it was clicked on. Your
production host must supply its own event data.

Click or focus a chart, or use the Chart selector, to select it for symbol,
interval, history range, chart type, study, grid, drawing, alert and snapshot
controls. Hovering another chart leaves that selection unchanged. Menus retain
the chart that opened them and reject an action after its chart or request has
changed. Snapshot keyboard shortcuts use the current selection; asynchronous
image conversion retains the captured symbol and interval in its filename.

The second chart retains its type, its point and figure and Renko options, study identities/settings and grid
through rebuild and reload. The selected pane and link preferences are saved
with the layout. Its symbol/readout is drawn on the chart, stacks above studies
and appears in exported images. Symbol search accepts a ticker or expression.
Changing its request or closing it aborts pending history, including expression
legs. Loading and failed history remain silent for alerts and do not overwrite
the saved layout. The reference trading simulation belongs to chart 1; its Buy
and Sell controls are disabled while chart 2 is selected.

Chart settings keep the chart that opened the dialog, including when focus
changes. Cancel restores that chart's edited fields; removing it closes the
dialog. Each chart retains its own timezone, readout options and saved price
style. For calendar intervals, accepting a timezone change rebuilds the owning
chart's buckets. Cancel leaves the original history intact.

The Volume settings tab controls each chart's visibility, candle colours and
moving average (period, colour, thickness and line style). The average shares
the histogram's scale, keeps warmup and missing-volume gaps, and follows live
replacement/append and the displayed replay prefix. Its settings survive reload
and returning from a transformed chart. Heikin Ashi retains volume and matches
its displayed candle colours. Transforms without a per-bar volume mapping
disable these controls with a reason. Volume colours follow candle
overrides, previous-close direction and theme changes. The daily-change readout
also uses displayed bars during replay.

Comparisons follow the selected chart. Replay captures that chart as its focused
owner and starts after the selected candle closes. The scope button switches
between that chart and all captured charts without changing UTC time. Toolbar
focus changes do not redirect replay. The slider addresses available observations,
so several finer observations may form one displayed candle. The shared clock is
formatted in the focused owner's timezone; local daily/weekly boundaries account
for daylight changes, and calendar month/quarter ends come from the interval registry.

Every participant has its own history request slot, replay mark, volume and
readout. A chart with no observation yet stays empty. Finer gaps hold the last
known prefix until the completed candle; finer-history failure is identified in
the status line. A transformed chart takes the finer bars too, and forms its
elements from them as they land. Histories with overlapping or unordered
bar times cannot enter shared replay. A newly opened or changed chart requires a
new capture before it can join all-chart replay.

Both charts' alert evaluation and every order-entry route remain paused during
selection, finer-history loading, scope changes and playback. Closing or changing
an active participant ends replay and restores the surviving charts. Changing an
inactive chart preserves focused replay. Cancellation aborts every participant's
request and rejects late responses. Controls span the workspace in both scopes
and remain usable in either chart's fullscreen view; the chart label identifies
the captured focused owner. They wrap on narrow screens. Exit restores data/viewports;
replay state is not saved as a live layout.

Fullscreen expands the selected chart while retaining the shared toolbar,
drawing controls and dialogs. Its chart selector switches the visible owner;
closing that owner leaves fullscreen and restores the workspace. The selector
stays visible when the toolbar scrolls on small screens. Shared replay is opt-in
through ReplayGroup; existing per-chart library defaults are unchanged.

Canvas legends fit inside each plot on small screens. The close reading has
priority over other prices, lower-priority fields disappear as whole readings,
and long source names shorten. Hover actions stay out of the price axis. Widening
the pane restores its full readout.

From 2.5.1, custom hosts may construct `AlertController` with
`{ spentLines: 'hide' }` to hide triggered and expired lines without removing
saved records. This reference host keeps the default `'show'` behavior in both
panes. Apply the option at each controller's construction if adapting the demo.
Keep the saved runtime when restoring alerts, and reapply this constructor policy.
See the website's finished-alert-lines example for both display choices.

Alerts default to confirmed bar closes. Intrabar touch can fire on a wick that
the provider later removes from final history. Absent study readings remain
unavailable, including OI on this OHLCV-only provider. Alerts keep their symbol,
exchange and interval scope, and loading history never evaluates past signals.
In 2.5.0, alert drags snap to the source scale's tick in preview and on release.
Hover an armed alert line and press Delete or Backspace to remove it. Selected
or hovered drawings and active drawing tools keep their shortcut priority;
editing a field never removes an alert.

In 2.5.0, fixed price levels stay visible after an interval change. Their labels
show the original interval, with a Paused badge while another interval is open.
Return to the original interval to resume evaluation or drag the threshold.
Study and drawing levels stay on their original interval; all records remain
in the Alerts list. Switching intervals does not retime a saved alert.
To test this, create a price alert on 1D, select 5M, reload, then return to 1D.
The level stays visible on 5M without firing for its loaded history.
Expiry is entered in the labelled chart timezone, stored as UTC epoch seconds,
and progresses while the page is open, even without ticks.
Triggered once alerts remain visible after a reload. Evaluation stops during
replay selection, finer-history loading and playback, then resumes from a fresh
baseline. This browser demo cannot deliver alerts while its page is closed.

Right-click either chart to create an alert from the clicked price, study plot
or supported drawing, or open that chart's Alerts list. The action stays bound
to the clicked chart if focus moves. A chart rebuild or symbol/interval change
invalidates an old menu action. Unsupported drawing levels show a disabled
action with an explanation. Oscillator context menus do not offer price-order
actions at oscillator values.

To try line dragging, create a price alert from either chart's context menu, then
drag its dashed line or **Alert** badge. The line previews the new value while the
saved threshold stays unchanged; releasing commits once. Press Escape before
release to cancel. Touch cancellation, starting a pinch, a symbol/interval change,
alert pause or replay entry also discard an unfinished drag.

Choose a range condition to drag its lower and upper boundaries independently;
each stops at the other boundary. Create a study alert to move a threshold in that
plot's own axis units, including an independent or left scale. A drawing-owned
alert level follows its drawing and cannot be dragged separately. This uses the
same alert controller as the packaged widget, on the chart that owns the alert.

## Chart data download

Choose **Download chart data (CSV)** in Layouts or the chart snapshot menu. Layouts
names the chart/source captured when it opened; changing focus does not retarget
the download. If that chart is rebuilt or its source changes, reopen the controls.
Loading, failed history and pending replay selection block export. The filename
identifies the source, interval and chart type, with a replay marker for a chart
participating in active replay.

The dialog starts with all installed bars and studies. Select individual study
instances, enter inclusive bounds as a date and a time on the chart's clock (the
zone is named under the fields; a To written to the minute takes in the whole
minute), or use the visible bounds captured when the dialog opened. Hidden studies remain selectable; adding another study
later does not silently include it. Removed selected studies report an error.
Comparison closes can be omitted separately.

The default file contains all installed bars, including only the revealed replay prefix,
with UTC seconds and unrounded numeric values. OI and volume gaps remain blank,
while zero remains zero. Configured study plots include repeated and hidden
studies, before visual offsets. Comparison columns use eligible aligned closes in
their original price units. There is no extra history fetch, aggregation or
trading/account data in the file. Display alignment follows current study plot
offsets and labels each time as loaded, interpolated, projected or unknown.
Projected rows contain known study values with blank future primary/comparison
fields. They do not promise a future market session. See
[the CSV format](../../docs/chart-data-export.md).

## Indicator templates

Open **Templates** in the shared toolbar. The dialog names the chart and source it
captured when opened. Enter a name and choose **Save new template** to capture that
chart's studies. **Update selected** replaces the studies in the selected saved
template; rename, duplicate, delete and portable JSON import/export use the same
catalog and storage revision guard as Layouts. Import creates a saved copy and
leaves the displayed chart unchanged until an apply action is chosen.

**Replace studies** removes the captured chart's current studies before installing
the template. **Append studies** retains their identities and adds separate copies,
placing imported pane groups after the existing panes. Both preserve parameters,
plot styles, visibility and repeated instances. An empty replacement clears the
studies; an empty append does nothing. Custom descriptors must be registered before
application. A failed restore attempts to recover the previous study state and
reports an unsuccessful recovery explicitly.

Templates retain drawings and price/drawing alerts. Alerts attached to retained
study identities survive append; replacing their study drops those alerts through
the engine's normal lifecycle. Triggered alerts remain visible and restoring a
template does not evaluate history. Applying during active replay uses its current
data prefix. Loading, replay selection and settings previews block application.
If the captured chart or its source changes, reopen Templates to select its current
owner. Storage errors remain visible and **Reload templates** explicitly refreshes
the shared catalog after a conflict.

## Persistence

Open **Layouts** in the shared toolbar to create a named save from the current
charts, save changes, open a selection or recent layout, rename, duplicate, delete,
import or export. The selection controls act on the selected saved document;
**Save current** and the toolbar's **Save layout** act on the displayed named layout.
Duplicate keeps the current charts; import validates and opens the imported copy.
Delete asks for confirmation. Deleting the displayed layout leaves the charts
unnamed, so autosave cannot write them into another entry.

Named documents use WorkspaceRepository with the IndexedDB database
`openalgo-reference-workspaces` and namespace `yfinance:reference`. New catalogs
start with autosave off. With **Autosave current layout** off, reloading restores
the last saved version, including its sources, chart settings and drawing-rail
preferences. Enabled autosave coalesces changes to the current named owner. A
storage error stays visible; a failed save is not reported as durable and does not
switch storage backends. Another session's newer revision requires **Reload saved
layouts** before an explicit retry. Exporting does not clear a failed-save warning.

Opening prepares every chart history before changing the display. Closing the
dialog during preparation cancels the switch. Replay, pending history and settings
edits disable source-changing layout actions. Missing custom studies or drawing
tools at startup leave the named document intact and block automatic replacement;
restore the missing extension or explicitly save a new layout from the current chart.

The session recovery snapshot remains under the local-storage key `oa-charts:layout`.
It does not override a saved named document. On the first successful catalog boot,
an existing snapshot becomes **Previous layout** with autosave enabled; the original
snapshot is retained. An empty catalog after deliberate deletion is not remigrated.
The sections below describe this recovery format and its compatibility helpers.
A 1.x page used `oa-charts-layout`; that key is upgraded, moved, and removed on boot.

**Schema version.** The document carries `schema: 2` (`LAYOUT_SCHEMA` in
`src/persist.js`). Inside it ride two versions the demo does not own: the
engine's `version` (what `chart.getState()` produced: 1, or 2 when the price pane
was moved below its studies; `CHART_STATE_VERSION` is the newest this engine reads)
and, under `drawings`, the draw tier's document with its own `version`
(`DRAWING_STATE_VERSION`). The demo's number says what shape the wrapper is;
the engine's numbers say what shape the parts are.

```
{
  schema: 2,
  version: <CHART_STATE_VERSION>,   ...chart.getState(): viewport, panes, price scales, indicators
  drawings: { version: <DRAWING_STATE_VERSION>, drawings: [...] },
  dataset: "AAPL|1d|1y",            what the view was captured on
  request: { symbol, interval, period },
  chartType, transforms: { "point-figure": {...}, renko: {...} },
  comparisons: [{ symbol, color, hidden }],
  compareMode, compareBaseMode, volume, volumeSettings,
  focusPane, linkOptions,
  secondary: { request, chartType, transforms, width, state, volumeSettings,
               comparisons: [{ symbol, color, hidden }], compareMode, compareBaseMode }
}
```

`transforms` holds the options each transform was given in its settings dialog,
as the engine takes them (`{ mode: "percent", percent: 0.25, reversal: 3, method: "hl" }`);
a transform it leaves out draws with its defaults. Layouts written before the
dialogs carry `pfmode` instead, the old point and figure box mode, and open on the
options that mode drew: `atr` as a box of one ATR(14), `percent` as 1 percent of
price and `fixed` as a box sized from the history, each with a three box reversal
over highs and lows. The next save writes `transforms`. A named workspace keeps
each option as a pane setting of its own (`reference.transform.renko.mode`), and
one saved with `reference.pfmode` opens the same way.

On startup, the primary request, chart type, transform options and timezone are restored
before the first history request. Calendar month and quarter bars therefore fold
in the saved timezone on their first load. These fields are optional additions to
schema 2. Older documents can recover a request from an unambiguous, supported
`symbol|interval|period` key; state-only documents keep the default source. Invalid
explicit selection fields are quarantined with the document, before changing any
controls. The startup helper does not switch an already running chart.

The comparison fields contain source identity and display preferences. History,
handles and credentials are not saved. Each chart refetches comparisons at its own
interval, range and timezone. A missing `hidden` field means visible. The optional
`compareBaseMode` preserves the mode to return to when the last comparison leaves,
including after a chart type change or reload; older documents retain their saved
axis mode. An unavailable source stays in the list with its error so it can be
retried or removed, without showing prices fetched for the previous interval.

**Where migrations live.** `MIGRATIONS` in `src/persist.js`, one step per
schema version keyed by the version it upgrades from; `upgradeLayout()` runs
them in order until the document is at `LAYOUT_SCHEMA`. Step 1 stamps the
schema, stamps a missing chart-state version, and hands `drawings` to the draw
tier's own `migrateDrawings()` (`src/draw/migrate.ts` in the engine), which
is the one place the 1.x drawing shape is understood: text moved out of the
style bag, fib levels became objects, every drawing gained a z-order. The
chart state itself is checked by `chart.restoreState()`, which refuses a
state without a version or with one newer than the engine's. A document
written by a newer demo, or carrying a chart state newer than this engine, is
refused rather than guessed at, before anything has been applied.

**What happens to a document that cannot be read.** It is not deleted. It is
renamed under `oa-charts:quarantine:layout:<timestamp>` (the newest five are
kept), the page says so in a notice that outlives the status line, and the
session starts clean. The layout is the user's own work, and the fault may be
in the reader.

**When recovery storage refuses a write** (quota, a private window), the snapshot is
kept in memory for the session, the user is told once, and Save tries storage
again. Autosave is debounced 250 ms, skipped during replay (a viewport over a
truncated session would restore the user into a truncated chart), and flushed
on `pagehide`. Restoring onto a different dataset keeps the workspace
(indicators, pane sizes, styles) and drops the view (viewport and pinned price
ranges), because a bar-index range means nothing on other bars.

**Drawings per symbol.** A line drawn on AAPL belongs to AAPL (`drawing-scope.js`,
over the draw tier's `InstrumentDrawings`). Loading MSFT into the same chart saves
AAPL's drawings and shows MSFT's own; AAPL's come back with AAPL, and deleting
everything on MSFT leaves them alone. Each symbol's drawings sit in local storage
under `oa-charts:drawings:<chart>:<symbol>`, written on every change, and each chart
of the split view keeps its own set. The layout carries the drawings of the symbol
it was captured on: restored onto that symbol they are its drawings, and a layout
file captured on another symbol keeps them for that symbol rather than laying them
over the one on screen. A layout saved before drawings were per symbol attaches
them to its own symbol the first time it loads. A symbol change is not an undo step
and clears the drawing steps of the timeline, so an undo on MSFT never brings back a
line of AAPL; the steps of studies and panes stay. When storage refuses a write the
page says so once and keeps the drawings for the session.

**Files.** The Layouts dialog exports portable workspace documents and imports each
with a fresh identity. It also accepts older wrapped or bare reference snapshots
when their source request can be recovered unambiguously; invalid or unsupported
files leave both the live charts and saved catalog intact. The compatibility
helpers `exportLayout()` and `parseLayoutFile()` still write/read the recovery
wrapper and its older forms. Legacy hidden controls remain available to embedders.
The synchronous recovery snapshot can flush on `pagehide`; an asynchronous named
write is not guaranteed to finish after the page closes. Use **Save current** and
wait for its confirmation when saving before leaving with autosave disabled.

## Tests

The repository's vitest config collects `tests/**` only, so the demo carries
its own. From the package root:

```bash
npm run test:demo                                             # the modules (also part of npm run verify)
python examples/yfinance/server.py --self-test                # the server
npx playwright test --project=yfinance-demo                   # desktop page against the fixture server
npx playwright test tests/e2e/yfinance-mobile.spec.ts         # compact touch flow in all configured browsers
```

The specs cover what runs without a browser: every module evaluates outside a
DOM (a module that touched `document` at import time would be a blank page),
the interval registry and period clamping, the feed's request window, error
classification and cache verdict, the layout schema, migrations and
quarantine, the feed's typed errors, retry, cancellation and staleness, the
shell furniture (toasts, the overlay stack, the chart-state card, the theme),
the rail, the properties bar and its editors, the venue and session readings,
order and position arithmetic, the bracket, and the transforms. The server's own checks
are described under [Offline fixture mode](#offline-fixture-mode). Anything
that draws is checked in a real browser against `index.html`, and the fixture
server is what that browser talks to: `tests/e2e/yfinance.spec.ts` drives the
page through the rail, the mouse and the transport, and reads the result back
through the `?test=1` handle. `tests/e2e/yfinance-mobile.spec.ts` adds fixture-mode touch
drawing, undo, navigation, reduced-motion and portrait-to-landscape checks for the compact
host controls. `tests/e2e/yfinance-history.spec.ts` walks a study from the picker, a line
placed with two clicks, a price scale inverted from its axis menu and a chart-type rebuild
back and forth with Ctrl+Z, Ctrl+Y and the rail's Redo.

## Notes

- Intraday intervals (`1m` to `90m`, `1h`) are limited by Yahoo to recent history
  (about 7 to 60 days, two years for `1h`); daily and weekly go back years.
  The range menu only offers what the interval can serve, and the server
  answers an over-long ask with 404 `no_data` rather than an empty chart.
- Times are converted to **UTC seconds** internally; the chart renders a gapless
  axis (weekends and holidays collapse) and formats labels in IST by default.
- yfinance is unofficial and rate-limited. A throttle surfaces as 429 with a
  `Retry-After`, and the page says to wait rather than retrying at once. For
  production use OpenAlgo's own `/api/v1/history` via `OpenAlgoDataFeed`.
- An error from the feed lands in the status readout, in an error card over the
  chart with a retry, and in a toast; the shell, the rail and the last chart stay
  up. An unknown symbol (yfinance answers with an empty frame) reads as
  `SYMBOL: no bars` rather than an empty chart; a throttle says so and is not
  retried; a dropped connection is retried once. A `STALE` badge beside the
  readout means the newest bar has closed while the venue is open: the feed is
  behind, or the load was warm and the cache held back a forming bar the page had
  not seen yet (reload ignoring the cache from the cache menu).


### Drawing catalogue (2.2.0)

The rail's last button folds it away so the chart takes its width; the tab that
appears at the chart's bottom left brings it back, and the choice is remembered.
Below 900 pixels, where the rail is the bottom touch bar, the fold waits until the
window is wide again. The page runs on a neutral palette: a near-black chart
(#151619) with grey chrome, a blue accent and the #089981 / #f23645 candle pair,
and a selected tool shows as a light wash with bright ink rather than a coloured
frame.

The drawing rail includes 87 tools: the existing annotations plus pitchforks,
regression and disjoint channels, advanced Fibonacci and Gann geometry, wavefronts
and harmonic or Elliott patterns. Open a rail group's chevron to choose a tool; edit
its settings from the selected drawing's properties. Mobile drawing controls use
the same catalogue and saved document format.

For a prepared, editable sample of every tool, open
`/examples/drawings/index.html` on this server. The gallery uses simulated NIFTY
prices near 23800; it does not request a live feed. Choose a tool and Show sample,
or press Draw and place its anchors. Undo, redo and body/handle dragging use the
packaged widget and public controller.

### Primary price fitting and compact study legends

Chart settings > Axes > **Fit primary prices only** excludes overlays from the
primary scale's auto-fit. The same choice appears on that scale's context menu.
It preserves manual ranges; enable auto-fit separately when needed.

Chart settings > Readout > **Collapse indicator legends** hides study rows while
retaining the plots and live readings. The **Indicators N** canvas control toggles
the rows directly, including on touch screens. Both choices are per chart and
survive ordinary reloads and named-workspace restoration.

### Collapsed panes

Right-click a study pane and choose **Collapse pane** to fold it to its legend
row; the row's collapse button, or **Expand pane** from the same menu, opens it
again at the height it had. The study keeps calculating and its drawings stay
put while it is folded, and nothing on the strip can be picked or drawn on.
The price pane is never offered the row, and collapsing the bottom pane leaves
the time axis at the foot of the chart. The choice is per chart and survives
reloads and named-workspace restoration. This is not the compact study legend
above, which hides legend rows and leaves every pane open.

### The price pane below the studies

Right-click the price pane and choose **Move pane down** (or a study pane and
**Move pane up**) to read the studies first and the price last. The candles
take their volume, the symbol row, the moving averages drawn on them, order and
bracket lines, price alerts, session marks and drawings with them; the price
ladder chords, the order menu and the price alert row follow the price pane
wherever it sits (`chart.primaryPaneIndex()`), and so does a template applied
to the chart. The price pane never folds, in any slot. The arrangement is per
chart and survives a chart-type switch, reloads and named-workspace restoration
(it is saved as a version 2 chart state). A drawing copied beside the candles
pastes beside the candles on either chart, wherever each keeps its price pane.

The engine keeps the price pane pinned on top unless a chart is built with
`movablePrimaryPane: true`, which both of this host's charts are (`main.js`,
`split.js`), and so is every chart of its grid view (`grid.js`); the widget
leaves the option off unless a host passes it. That option is a promise that
nothing in the host passes pane `0` to mean the price pane: this host names no
pane or asks `primaryPaneIndex()` for its order and price lines, volume,
legends, price levels, replay marks, session marks, alert and order rows and
axis chords, keeps `primaryPane` in its named-workspace allowlist, and forwards
`plan.primaryPane` when it applies a template.

### One undo timeline

Each chart keeps one timeline: a study added from the picker or removed from its
chip or legend, its settings, the chart type, a price scale's mode, invert, auto-fit
or placement from the axis menu, pane moves, folds and heights, the chart settings
and study settings dialogs (one step per session; Cancel leaves none), a drag of a
study's anchor ring and drawings, in the order they were made. A study brought back
returns to its pane, height and fold, with the drawings its pane held, and under the
id it had. The protected VWAP is the host's: adding or removing it from the menu is
never a step, and no undo or redo removes, reconfigures or moves it, though a study
you move past it in its pane's stack is a step like any other and goes back past it.

Ctrl+Z and Ctrl+Y (and Ctrl+Shift+Z) over a chart and the mobile bar's Undo and Redo
walk the focused chart's timeline. The rail and the drawing toolbar belong to the main
chart, as their tools, lock, hide and delete do, so their Undo and Redo walk the main
chart's timeline whichever chart has the focus. With appearance linked, a change one
chart makes reaches the other outside that chart's timeline: undoing it on the chart
that made it takes it back on both.

The chart is rebuilt on every load and chart-type switch, and the timeline carries
over: each new chart and drawing controller is attached to it. The chart type is a
rebuild here, so the switch is recorded as a command that rebuilds with the type
it replaced. Comparisons, the volume row and a loaded layout or workspace are the
host's own and never steps; loading a layout or a workspace starts a new timeline.
Undo never refetches or rewrites bars, fires an alert or places an order.
