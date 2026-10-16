# OpenAlgo Charts - Architecture & Design Document

> A from-scratch, canvas-based financial charting engine for OpenAlgo.
> Historical pre-implementation target: **< 50 KB Brotli** for the full package (engine + trade overlay), no runtime dependencies. *(Brotli is the size metric we hold the budget against - see §11. Gzip runs ~10-15% larger.)*
> Goal: professional-grade interactive financial-chart rendering + advanced on-chart trading & trade management.

> **Current release: 2.6.4.** An order flow release: an untraded row inside a footprint bar counts as zero for imbalances, a delta-shaded volume view, zone alerts from the `Footprint` primitive (`onZoneAlert`), a choice of which zones extend and from how far back, a colour option for each part of a footprint and six named themes (`FOOTPRINT_THEMES`), all inside the profile tier. 2.6.3 was a finish release: the drawing tool and chrome glyphs draw one fine line (about 1.3px at 20px and 16px), the widget's drawing rail folds away behind a tab so the chart takes its width, the wheel zoom chases one target per frame so a fast wheel or a trackpad zooms in one smooth motion, a log scale pads its margins in log space and fills the pane, the widget's drag keeps the price scale automatic, and a tooltip no longer takes the click meant for the control under it. 2.6.2 fixed the bottom bar's ranges and Go to, which reported missing history across a weekend or another gap no session trades in. 2.6.1 gave the footprint order flow analytics (trade classification, a trade size filter, imbalance and delta views, zones, unfinished auctions, delta flips and session statistics), rows aligned on the even boundary, Renko and point and figure sizing from price or the ATR, and settings dialogs for both chart types in the widget and the reference host. The 2.6.4 build measures 137.65 kB base, 154.52 kB base + trade and 426.67 kB for all tiers (decimal Brotli sizes).
>
> **2.6.0.** Analysis depth and a stricter API. A chart applies Heikin Ashi, Renko, range bars, line break, point and figure and Kagi to the bars a host feeds, live (`setSeriesTransform`, with the runs installed by `registerSeriesTransform` when the transform tier is imported), and each study computes on the elements drawn or on the underlying bars (`setBarSource`). Seven built-ins are new, 112 in all, and 29 take a `timeframe` input that folds the chart's bars into a higher interval without repainting. The OpenAlgo feed searches symbols (`DataFeed.searchSymbols`), and event markers carry rich details with host actions. `ChartEventMap` types every event on the chart's bus, every tier ships as a classic script on the `OpenAlgoCharts` global, `require()` resolves to the ESM files, and all of `src` compiles under `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`. The 2.6.0 build measures 137.53 kB base, 154.41 kB base + trade and 419.05 kB for all tiers (decimal Brotli sizes).

> **2.5.10.** Persistence, saved layouts and the chart grid. The widget keeps its saved state in IndexedDB through an asynchronous store (`AsyncStorageLike`, `widget.ready`), reopens named layouts and indicator templates over a `WorkspaceStore` with revision checks, and lets a user move any shortcut from the ? panel. A bottom bar carries preset ranges sized in trading sessions, Go to, the market status and a clock with a timezone menu. Calendars know pre-open, post-close and extended hours (`phaseAt`, `marketStatusAt`), and `attachSessionShading` washes those bars in the price pane. The chart grid lays out one to sixteen charts with maximize, swap and up to sixteen named link groups, whose channels now include the chart type and drawings. UI a plain widget never opens loads on first use from hashed part files beside the widget tier, and text markers take lanes so neighbouring labels no longer overlap. The 2.5.10 build measures **134.69 kB** base, **151.38 kB** base + trade and **409.13 kB** for all tiers (decimal Brotli sizes).

> **2.5.9.** Drawing interaction and replay. Drawings belong to the instrument they were drawn on (`InstrumentDrawings`, the widget's default), and the drawing controller gains the magnet on every pane and in every drag, box select, drag to copy, an eraser, a temporary measure and visibility per interval (drawings document version 3 when a drawing carries a range). A drawing layer keeps a hit box per drawing, so a hover asks only the drawings near the pointer. Replay holds its forming bar inside the bar it closes on and can form a bar with no finer data over simulated steps. Line-family series draw the segment that crosses each edge of the view (`connectsBars`), and the price axis keeps edge labels whole and value tags over level tags. The 2.5.9 build measured **131.68 kB** base, **148.36 kB** base + trade and **381.78 kB** for all tiers (decimal Brotli sizes).
>
> **2.5.7.** An internal release: the chart's logic moved out of `chart.ts` into collaborator modules behind the unchanged `Chart` class (see Chart internals below), with the same public API and the same pixels as 2.5.6. The 2.5.7 build measured **126.91 kB** base, **143.60 kB** base + trade and **357.50 kB** for all tiers (decimal Brotli sizes).
>
> **2.5.6.** Nine independently loadable tiers. Studies carry policies the way drawings do, and sources, studies, drawings and primitives share one draw order per pane that the pointer follows. A `price` input can pair with a `timestamp` input and be picked or dragged as one point, a study's background shading can target the price pane or a plot's pane, and inputs can be shown or enabled by other settings. Data variants (regular or extended hours, adjusted or raw prices, a quote currency or unit) are separate provider series, never converted locally. A session calendar lays the space past the last bar out in the venue's hours. Pane boundaries land on whole device pixels, the chart follows a change of pixel ratio and repaints in the same frame as a resize. The widget walks one undo timeline for the whole chart (`ChartHistory`). The 2.5.6 build measured **125.39 kB** base, **142.07 kB** base + trade and **355.97 kB** for all tiers.
>
> **2.5.5.** The engine gains an opt-in movable price pane (`movablePrimaryPane`), an identity rather than slot 0, and indicator gap recovery, so a missing bar costs a running study only the bars it covers. The draw tier pins drawings to the viewport. The trade tier gains account state, order preview, durations, native close, reverse and bracket commands, and price-dependent tick schedules that validation, dragging and the ladder follow. The workspace tier keeps named watchlists, and the widget adds Watchlist, News and account panels over optional quote, news and account contracts. The 2.5.5 build measured **119.15 kB** base, **135.79 kB** base + trade and **335.15 kB** for all tiers. Current measurements are in the README size budget; historical estimates and release measurements below remain labeled as such.
>
> **Earlier implementation history.** Version 2.2.0 expands the drawing registry to 85 tools, adds native curve geometry and guided multi-point placement, and tightens label, volume-window and hit-test work. Version 2.1.9 adds chart-owned vector branding, optional persisted text watermarks and guarded logo gestures.  Version 2.1.8 normalizes trackpad and wheel input, routes gestures by axis, eases automatic price projections and adds dedicated mobile widget controls. Version 2.1.7 adds shared object management, a searchable Objects panel and dialogs sized to their host. Version 2.1.6 adds shared history ownership, request scheduling, resilient cache snapshots, managed external-study context and visible widget retry states. The design below includes the footprint styles, configurable statistics table and quantity/lot display. Version 2.1.4 restores two-axis mouse and pen panning by default, while retaining horizontal-only panning as an explicit preference. Version 2.1.3 added saved navigation preferences and a reset control. Version 2.1.2 isolates external-study data contexts, strengthens history/live recovery, accepts current OpenAlgo protocol frames and adds optional widget stylesheet nonces. The pre-implementation size estimates in this document have been superseded by measured `size-limit` (Brotli) figures, which live in the README size budget and are re-measured on every release: on the 2.2.0 build the base engine is **76.22 KB**, base + trade **83.83 KB**, and everything (all eight tiers) **212.52 KB**. The original "under 50 KB" target below is kept as history; the budgets that are enforced are the per-tier rows in `.size-limit.json`. See the *Revision log* for the point-by-point mapping and §13a for the honest deferred list.

<p align="center">
  <img src="docs/architecture-diagram.svg" alt="OpenAlgo Charts 2.5.7: host boundary, base engine data flow and controllers, and eight optional capability tiers" width="900" />
</p>

The diagram separates host orchestration from the base engine and its eight optional
tiers. Alerts, replay groups, comparison and shared loading belong to base. The
workspace tier supplies portable documents and storage; the host builds and activates
the grid, or the widget's `createChartGrid` does it for widget cells. Brokers remain authoritative for execution, and the host delivers alert
notifications. Pipeline arrows show data flow, not package dependencies.

---

## Current integration map

For 2.6.2 integrations, start with these current guides and implementation
boundaries. The numbered design sections below retain historical plans and
explicitly labeled estimates; use the current API types for implementation.

| Responsibility | Current implementation | Guide |
|---|---|---|
| Loading and metadata | Shared data controller, instrument adapter, request pool and closed-bar cache; host applies snapshots to series | [Data loading](https://marketcalls.github.io/openalgo-charts/docs/data-loading/) |
| Open interest | Optional `Bar.oi`, latest-observation aggregation and separate instrument capability | [Open interest](docs/open-interest.md) |
| Trader alerts | Base `AlertController`, committed evaluation thresholds, durable lifecycle and host-owned delivery | [Trader alerts](https://marketcalls.github.io/openalgo-charts/docs/alerts/) |
| Replay and linking | Base `ReplayController`, `ReplayGroup` and `LinkGroup`; availability clock and host callbacks | [Replay](https://marketcalls.github.io/openalgo-charts/docs/market-replay/) |
| Analysis drawings | Draw-tier Anchored VWAP and fixed-range Volume Profile use timestamp anchors, pane OHLCV and ordinary drawing properties | [Drawing tools](https://marketcalls.github.io/openalgo-charts/docs/drawing-tools/) |
| Linked views | Base appearance and drawings adapters, chart type channel and draw-tier `DrawingLinkGroup`; matching symbol and exchange, separate local history and persisted lineage; named link groups saved in workspaces | [Chart linking](https://marketcalls.github.io/openalgo-charts/docs/chart-linking/) |
| Timeline events | Base grouping and clustering model, with host-supplied data and widget details | [Events](https://marketcalls.github.io/openalgo-charts/docs/events/) |
| Workspaces | Optional portable documents, revisioned repository and async storage; host builds and activates charts | [Workspaces](docs/workspaces.md) |
| Chart grids | Widget-tier `createChartGrid`: layouts from one to sixteen charts, a grid bar, splitters, maximize and swap, one active chart, named link groups over the base `LinkGroup`, a whole-grid capture and workspace payloads; a bar under the charts, saved desks, the desk kept in IndexedDB | [Chart grid](https://marketcalls.github.io/openalgo-charts/docs/chart-grid/) |
| Date navigation | Widget-tier `DateNavigator` and panel; the host's loader reaches older history, the chart places the view | [Data loading](https://marketcalls.github.io/openalgo-charts/docs/data-loading/) |
| Pane layout | Base pane weights, maximize and collapse to a strip, and an opt-in movable price pane, saved in pane state and workspaces | [Scales and panes](https://marketcalls.github.io/openalgo-charts/docs/scales-and-panes/) |
| Drawing policies | Draw-tier `policy` on each drawing; forced host calls bypass it and record no undo step | [Drawing tools](https://marketcalls.github.io/openalgo-charts/docs/drawing-tools/) |
| Watchlists, quotes and news | Workspace-tier `WatchlistRepository`; optional `QuoteFeed` and `NewsFeed` beside `DataFeed`; widget panels never present a candle as a quote | [Widget](docs/widget.md) |
| Accounts and position commands | Trade-tier `AccountManager`, `TradingFeatures`, `previewOrder`, durations and native close, reverse and brackets, each declared by the broker and never simulated | [Trading](https://marketcalls.github.io/openalgo-charts/docs/trading/) |
| Tick schedules | `TickSchedule` bands as instrument metadata, followed by validation, dragging and the ladder; one constant tick by default | [Instruments](https://marketcalls.github.io/openalgo-charts/docs/instruments/) |
| Viewport drawings | Draw-tier `space: 'viewport'` anchors as fractions of the pane's plot; never linked across charts | [Drawing tools](https://marketcalls.github.io/openalgo-charts/docs/drawing-tools/) |
| Study policies | Base `IndicatorPolicy` (`removable`, `configurable`, `movable`, `listed`); user controls are refused, `{ force: true }` and restores are the host's act; saved only as restrictions | [Indicators](https://marketcalls.github.io/openalgo-charts/docs/indicators/) |
| Draw order | Base series stack per pane (`seriesStack`, `moveInSeriesStack`, `setPrimitiveStackAbove`) and draw-tier `stackAbove` / `placeInStack`; hit testing follows paint order | [Scales and panes](https://marketcalls.github.io/openalgo-charts/docs/scales-and-panes/) |
| Chart-wide undo | Widget-tier `ChartHistory`: studies, settings, scales, panes, chart settings and drawings on one timeline, replayed through public calls and never past a policy | [Widget](docs/widget.md) |
| Data variants | `BarsRequest.variant` and `DataFeed.dataVariants`; each variant its own cache key, request and alert scope; an undeclared variant is reported, never derived | [Data variants](https://marketcalls.github.io/openalgo-charts/docs/data-variants/) |
| Session calendar | `SessionCalendar` or an `Instrument` set with `chart.setSessionCalendar`; times past the last bar follow the venue's hours | [Instruments](https://marketcalls.github.io/openalgo-charts/docs/instruments/) |
| Session phases and shading | `phaseAt`, `phaseSpans` and `marketStatusAt` on `SessionCalendar` and `Instrument` from optional `preMarketMinutes`, `postMarketMinutes` and `extendedHours`, resolved in the calendar's IANA zone; `attachSessionShading` washes pre-open, post-close and extended-hours bars, off until a host attaches it | [Instruments](https://marketcalls.github.io/openalgo-charts/docs/instruments/#market-phases-and-status) |
| Study inputs | `visibleWhen`, `activeWhen` and `inline` on `IndicatorInput`; paired `timeKey` point inputs with an optional on-pane anchor; presentation only, `calc` sees every setting | [Indicators](https://marketcalls.github.io/openalgo-charts/docs/indicators/) |
| Chart export | Loaded or revealed bars, study values and comparison closes; host delivers the CSV | [Chart data](docs/chart-data-export.md) |
| Custom studies | Descriptor registry in base; optional built-ins and external-data helpers | [Indicators](https://marketcalls.github.io/openalgo-charts/docs/indicators/) |
| Rendering cost | Level of detail on by default (`conflate`), plot writes in place on a tick, `calcTail` of their own on twenty-three built-ins, repaint scoped to the panes a write changes, optional `IPrimitive.hitBounds`, and render-bench budgets per bar count | [Performance and operations](https://marketcalls.github.io/openalgo-charts/docs/performance-and-operations/) |
| Host interface | Canvas containers in base; toolbar, Data/Objects dock, rich symbol search, dialogs and translated controls in the widget | [Widget](docs/widget.md) |

## Chart internals

`Chart` (`src/core/chart.ts`) is the facade: it holds the state every concern shares
(panes, time scale, data layer, series and studies), builds the frame, runs the event bus
and the lifecycle, and keeps every public method with its documentation. Until 2.5.7 it
also held all the logic, 6,729 lines of it. Each concern now lives in a collaborator of its
own, created by the chart and reaching the rest of it through a host interface declared in
the collaborator's file. The chart is that host: every interface member is typed as
`Chart['name']`, so the compiler rejects a member the chart does not have, and no
forwarding object is built.

| File | Holds |
|---|---|
| `chart-types.ts` | The public option, event and payload types, re-exported from `chart.ts` |
| `chart-events.ts` | `ChartEventMap`, every name on the bus with its payload (the draw tier merges its own in from `src/draw/events.ts`), and the listener registry behind `on`, `once`, `off` and the engine's typed `_emit` |
| `chart-series.ts` | Series creation, series type changes, price formats and the data writes behind a series handle |
| `chart-studies.ts` | The study host: adding, moving and removing studies, the `IndicatorHost` they run against, bar colours and the recompute queue |
| `chart-panes.ts` | The pane stack and its layout: creating, removing, moving, maximizing and folding panes, axis columns and divider hits |
| `chart-legends.ts` | Legend rows per pane, their controls and the collapsed indicator list |
| `chart-scales.ts` | The price-scale patches behind the chart-wide and one-axis setters, and axis placement |
| `chart-primitives.ts` | Primitives on panes, the draw order (series stack) and the event strip |
| `chart-appearance.ts` | Branding, the text watermark, the option batch and the image and SVG exports |
| `chart-input.ts` | Pointer, wheel, double-click, pinch, keyboard, shortcut, context-menu, hover and cursor routing |
| `chart-motion.ts` | Kinetic scroll and the eased wheel zoom, stepped at the top of each render frame |
| `chart-pixels.ts` | Following the container's size and the device pixel ratio |
| `chart-state.ts` | `getState` and `restoreState` |

The split moved code and changed nothing else: no test assertion changed (one
compatibility inventory now names the file three moved comments live in), and the
render-parity spec painted the same pixels as 2.5.6 at every zoom. Private members stay private, so the published declarations show
only `private` names for the collaborators. `scripts/line-caps.json` holds every source file
to 1,500 lines through ESLint, with the few older files over the limit capped at their
size so that they can only shrink. `scripts/function-caps.json` does the same for
functions at 150 lines (`tests/function-caps.test.ts`), since a file cap does not bound
a module that is one long mount closure.

## 0. Why from scratch (and the principles we follow)

We are writing our own engine from scratch, with no external charting dependency. We deliberately follow the well-established design principles that make minimal canvas charting engines small and fast, because they are the right ideas:

| Principle we adopt | Why |
|---|---|
| **Base + top canvas per pane** (no SVG, no DOM-per-bar); the price and time axes paint on the pane's base canvas | The two-canvas split (data vs cursor/overlay) lets a crosshair move repaint the overlay canvas alone. See §3.1. |
| **Shared data/time layer** merging all series by time to logical indices | Keeps price + volume + indicator panes perfectly aligned on one x-axis. See §4. |
| **Indexed plot rows with cached visible range** | O(log n) visible-range lookup, so the series pass walks the *visible* bars. A study still does work over its full history once per frame that carries a tick: a full recompute, or for a study with a `calcTail` a copy of each output column, and a comparison of each plot point with what its series holds; §1 records what that costs. |
| **Bitmap vs media coordinates** | Draw in device pixels so 1px lines stay crisp on HiDPI/retina without blur. |
| **Per-pane invalidation mask** (global level + per-pane map) | A crosshair move repaints the overlay canvas only. A live tick repaints the price pane and the panes of the studies computed from it, and a study recompute repaints only the panes its output lands on, until a write moves the shared time scale. See §3.2. |
| **Renderers are pure functions of draw-data** | Renderer takes a plain data object + canvas context, draws, returns. No state, easy to test, tree-shakeable. |
| **Primitive/plugin extension API** with views + lifecycle + z-order + hit-test | The trade layer (order lines, DOM ladder) and markers/events are *primitives*, not hardcoded, keeps core lean. See §8. |

The original scope excluded yield-curve charts, an options-mode chart and multiple horizontal-scale behaviors. The widget now supplies typed translation keys with English fallback; hosts translate their own content and supply provider data. **We keep line/area/baseline/HLC-area**: they're cheap Family-A renderers (see §6A) and are in the requested type list. Heavy chart types (footprint/orderflow/profile) and the trade layer are opt-in tiers (§2).

### 0.1 Licensing & attribution (decision: locked)

**OpenAlgo Charts is released under Apache-2.0.** This is the project's chosen license:

- **Permissive by design.** Apache-2.0 is permissive (not copyleft), it imposes no copyleft obligation on users of the library, and incorporating any compatibly-licensed third-party routine is straightforward.
- **Default stance: clean-room, original code.** We write our own implementation from documented design principles; we don't copy/paste third-party source or line-by-line port another library's renderers. This keeps the codebase genuinely ours.
- **If any third-party (Apache-2.0 or compatibly licensed) code is ever incorporated** (e.g. a tricky tick-mark or coordinate-snapping routine), §4 obligations are met by preserving that code's copyright/license headers and adding a `NOTICE` entry crediting its original authors. No relicensing needed.
- **Shipping requirements:** include our `LICENSE` (Apache-2.0), a `NOTICE` file listing any third-party attributions, and preserve attribution headers. The `NOTICE` is created in Phase 0 and maintained as code lands.

Net: Apache-2.0 keeps the project permissive *and* lets us incorporate a hard algorithm with attribution if it's ever the pragmatic choice, without a clean-room purity constraint.

---

## 1. Goals & constraints

### Functional
- Candlestick / line / histogram (volume) series, multi-pane (price pane + volume pane + indicator panes).
- Smooth pan, wheel-zoom, pinch-zoom, kinetic flick scrolling, double-click to reset.
- Crosshair with synced price-axis & time-axis labels; OHLC legend.
- Autoscale price (linear / log / percentage), fixed scale, fit-content.
- Live updates: append or replace the last bar as ticks arrive; updates that land before one animation frame paint once.
- **Chart trading**: drag-to-place order lines, position marker with live P&L, SL/TP bracket lines, one-click buy/sell, DOM ladder, OCO visualization.
- Indicator overlays (EMA/VWAP/Bollinger as line/band primitives) and sub-pane indicators (RSI/MACD).

### Non-functional
- **< 50 KB Brotli** total (engine + trade overlay). Stretch: < 30 KB Brotli engine-only. *(All size numbers in this doc are Brotli. These are estimates until the Phase 1 prototype is measured, see §11.)*
- Zero runtime dependencies. We write our own HiDPI canvas sizing (~30 lines) rather than pulling a separate canvas-sizing helper package, so nothing is excluded from the size measurement.
- TypeScript source, ESM output, tree-shakeable, framework-agnostic (works in plain JS, React wrapper optional).
- Design goal: 60 fps with 50k bars loaded, 1.5k visible. **Not met in 2.5.8.** The live workload of `scripts/browser-endurance.mjs` (two charts, 150 bars in view, ten forming-bar replacements per second per chart, five studies each, Canvas2D, DPR 1, 1440 by 900) measured a frame-interval p95 of 17 ms at 2,000 bars per chart, 134 ms at 10,000 and 717 ms at 50,000, on the 2.5.5 build in headless Chromium 149 on an 8-core desktop CPU, 2026-09-26, and has not been rerun since. The same 150 bars are in view in all three runs, so the growth is work over the whole history, such as the study recompute. 2.5.8 cut that work: a study writes only the plot points a tick moved, the shared time index is no longer rebuilt on a tick, and sixteen common built-ins take a `calcTail`. On the render bench (`npm run bench:render`, measured on an 8-core desktop in headless Chromium 149, `docs/performance-notes.md`) a forming-bar tick with ten studies at 50,000 bars fell from a p95 of 1166.3 ms to 49.2 ms on `canvas2d`, still more than one 60 Hz frame, and it still grows with the loaded history rather than the view; what remains has not been profiled. The endurance commands, conditions and the rest of each report are in `docs/browser-endurance.md`. The render bench also budgets a pan with about 200 bars in view and a frame with every loaded bar in view; a 1.5k-bar view has not been measured.
- Works in OpenAlgo's existing frontend (it can be dropped into any page; React/HTMX/vanilla all fine).

### Size accounting rule
We measure **Brotli** bytes via `size-limit` in CI. Every PR that grows the Brotli size is flagged. Raw-minified ≈ 3 to 3.5× the Brotli number; gzip ≈ 1.1 to 1.15× Brotli. Brotli is what most CDNs/servers actually serve and is the metric we hold the budget against.

---

## 2. Module map & size budget

Directory layout under `openalgo-charts/src/`, as first planned. The tree has grown and been reorganised since (for example `input/` now holds `kinetic.ts`, `wheel.ts`, `touch.ts`, `pick.ts`, `zoom-glide.ts`, `crosshair.ts` and `shortcuts.ts`, and hit testing lives in `core/pane.ts`), so read `src/` for the current modules:

```
src/
├── index.ts                 # public API surface (createChart, addSeries, …)
├── core/
│   ├── canvas.ts            # HiDPI canvas pair (media+bitmap), resize observer
│   ├── render-loop.ts       # rAF scheduler + invalidate mask
│   ├── chart.ts             # top-level orchestrator (owns panes, scales, model); see Chart internals
│   └── pane.ts              # a stacked drawing region (price pane, volume pane…)
├── model/
│   ├── data-layer.ts        # shared DataLayer: merge-by-time, logical indices, prepend/merge (§4)
│   ├── indicator-plot-writes.ts # what each study plot holds, so a tick writes only the points that moved
│   ├── conflation.ts        # the level of detail: one OHLC-preserving stick per device-pixel column (§4.4)
│   ├── bar.ts               # bar/point types, plot-row shape
│   └── series.ts            # one series (data + style + which renderer)
├── scale/
│   ├── time-scale.ts        # index to x mapping, bar spacing, tick marks, pan/zoom state
│   ├── price-scale.ts       # price to y mapping, linear/log/percent, autoscale
│   └── ticks.ts             # "nice number" tick generation (shared)
├── render/
│   ├── candles.ts           # candle / hollow / volume-candle / heikin-ashi
│   ├── bars.ts              # OHLC bars + high-low
│   ├── line.ts              # line / line+markers / step / area / HLC-area / baseline
│   ├── histogram.ts         # volume / columns
│   ├── crosshair.ts         # crosshair lines + magnet
│   ├── grid.ts              # background grid
│   ├── axis.ts              # price-axis & time-axis label rendering
│   ├── draw-items.ts        # the visible bars walked in place into draw items each series keeps (§4.4)
│   ├── backend.ts           # IRenderBackend port + registry for the series pass (§3.4)
│   └── webgl/               # the WebGL2 backend; shipped by the webgl tier, never by the base
├── transform/               # Family B: price/movement-driven series (opt-in)
│   ├── transform.ts         # ISeriesTransform interface + pipeline
│   ├── heikin-ashi.ts       # 1:1 smoothed candles
│   ├── renko.ts             # brick series (fixed / ATR box size)
│   ├── range-bars.ts        # new bar every N ticks of range
│   ├── point-figure.ts      # X/O column series
│   ├── kagi.ts              # reversal line (thick/thin)
│   └── line-break.ts        # N-line break
├── profile/                 # Family C: price×{vol|time|bid-ask} (separate bundle)
│   ├── volume-profile.ts    # volume-at-price (session / visible / fixed range)
│   ├── tpo.ts               # Time Price Opportunity / Market Profile
│   ├── footprint.ts         # per-candle bid/ask cells + delta + imbalance
│   └── orderflow.ts         # cumulative delta, stacked imbalance overlays
├── input/
│   ├── pointer.ts           # unified mouse/touch/pointer events
│   ├── pan-zoom.ts          # drag-pan, wheel-zoom, pinch, kinetic
│   └── hit-test.ts          # what's under the cursor (for primitives)
├── primitives/
│   ├── primitive.ts         # IPrimitive interface (the extension point)
│   ├── price-line.ts        # horizontal line at a price (base for orders/SL/TP)
│   ├── markers.ts           # buy/sell signals + shapes (tiny/small/medium/big)
│   └── event-markers.ts     # Earnings / Dividend / Split badges (time-axis strip)
├── trade/                   # the advanced trade-management layer (separate entry point)
│   ├── order-line.ts        # draggable working-order line
│   ├── position.ts          # position marker + live P&L + breakeven
│   ├── bracket.ts           # SL/TP/OCO bracket group tied to a position
│   ├── dom-ladder.ts        # vertical price ladder (DOM) docked to right axis
│   └── trade-controller.ts  # binds gestures to OpenAlgo REST/WS order calls
├── feed/
│   ├── openalgo-rest.ts     # history + books + orders (REST adapter, §10)
│   ├── openalgo-ws.ts       # live tick/quote/depth subscription
│   └── candle-builder.ts    # ticks/quotes to interval OHLC (§10.2)
└── widget/                  # the chrome as a tier (separate entry point, §8.5); the only DOM under src/
    ├── widget.ts            # createWidget: the shell, symbol/interval/theme, the chrome wiring
    ├── widget-keys.ts       # the shell's key scopes, pointer tracking and key bindings
    ├── widget-persist.ts    # the saved layout: read and applied, per-instrument drawings, restoreState, debounced save, pagehide flush, the late restore over an async store
    ├── context.ts           # WidgetContext, bus, storage, overlay stack, tips, the dialog registry
    ├── storage.ts           # createIndexedDbWidgetStorage and the default store, over storage-idb.ts, which loads on first use
    ├── storage-idb.ts       # the IndexedDB store, its change announcements, the one-time copy from localStorage, the fallback
    ├── keymap.ts            # one capture-phase keymap with scopes and conflict reporting
    ├── keymap-editor.ts     # the ? panel: lists every chord, records a new one, names conflicts, resets (loads on first use)
    ├── lazy.ts              # the parts that load on first use: one shared load, a failure reported and forgotten
    ├── grid.ts              # createChartGrid: cells, focus, splitters, maximize, swap, workspace
    ├── grid-layouts.ts / grid-links.ts / grid-cells.ts / grid-capture.ts / grid-text.ts / grid-styles.ts
    ├── grid-bar.ts / grid-menus.ts # the grid bar and its menus (load on first use)
    ├── grid-saved.ts        # the desk's saved layouts
    ├── grid-payload.ts      # the workspace check, each chart's drawings
    ├── rail.ts / topbar.ts / statusline.ts / toast.ts
    ├── tokens.ts / styles.ts# --oac- tokens derived from the ChartTheme; one scoped stylesheet
    ├── form.ts              # one control renderer for every schema-generated form
    └── dialogs/             # settings, indicator picker and settings, drawing properties, levels, text, context menu
```

> **model/ note:** `data-layer.ts` is the *shared* DataLayer (merges all series by time to logical indices), not a per-series store, see §4. Per-series plot rows hang off it.

### Size budget (raw minified to est. Brotli)

> **Methodology (point of record):** numbers are **Brotli-compressed**. Since we have zero runtime dependencies, nothing is excluded from the measurement. Raw-minified ≈ 3 to 3.5× the Brotli figure; gzip ≈ 1.1 to 1.15× Brotli. **All figures below are pre-implementation estimates** and the first deliverable of Phase 1 is to wire `size-limit` and replace them with measured values.

The current package has **nine loadable tiers**, selected through separate entry points or dynamic `import()`: base, trade, transform, profile, indicators, draw, webgl, widget and workspace. The widget supplies interface controls (§8.5); workspace supplies validated portable documents, indicator templates, revisioned catalogs and asynchronous storage without DOM or registration side effects. Measured sizes for every tier are in the README size budget. The three groups below preserve the original pre-implementation estimates.

**Tier 1, Base bundle (always loaded):**

| Module | Raw min | Brotli (est.) |
|---|--:|--:|
| core (canvas, render-loop, chart, pane) | 7 KB | 2.4 KB |
| model (shared data-layer, bar, series, candle-builder) | 9 KB | 3.0 KB |
| scale (time, price + edge cases, ticks; incl. ordinal mode) | 14 KB | 4.6 KB |
| render, all Family-A types: bars, candles, hollow, volume-candle, line, line+markers, step, area, HLC-area, baseline, columns, high-low, crosshair, grid, axis | 16 KB | 5.2 KB |
| input (pointer, pan-zoom, hit-test) | 8 KB | 2.6 KB |
| primitives (base + price-line + markers + event-markers) | 5 KB | 1.7 KB |
| feed (rest + ws + candle-builder wiring) | 4 KB | 1.4 KB |
| **Tier 1 subtotal** | **~63 KB** | **~21 KB Brotli** |

**Tier 2, Trade layer (opt-in, `openalgo-charts/trade`):**

| trade (order-line, position, bracket, dom-ladder, controller, state machine) | 16 KB | 5.2 KB |

**Tier 3, Advanced chart types (each lazy-loaded only when selected):**

| Module | Raw min | Brotli (est.) |
|---|--:|--:|
| transform/ (Family B: heikin-ashi, renko, range, P&F, kagi, line-break) | 9 KB | 3.0 KB |
| conflation (planned as optional; shipped in the base, on by default since 2.5.8 as the level of detail, §4.4) | 3 KB | 1.0 KB |
| profile/ volume-profile + tpo | 7 KB | 2.3 KB |
| profile/ footprint + orderflow | 10 KB | 3.4 KB |

**Verdict (estimates, to be confirmed by measurement):**
- **Base chart ≈ 21 KB Brotli**: well inside budget for the full set of standard chart types, because we ship fewer base features and lazy-load the heavy ones.
- **Base + trade layer ≈ 26 KB Brotli**: under 50 KB with headroom.
- **Everything (all tiers) loaded at once ≈ 36 KB Brotli**: *still* under 50 KB, and in practice footprint/orderflow code only downloads when selected.

(We get a wide range of chart types in a small base size by lazy-loading the advanced ones. **These ratios are the design intent; the prototype's measured `size-limit` output is the source of truth.**)

---

## 3. The core engine

### 3.1 DOM & canvas layout model (`core/canvas.ts`, `core/pane.ts`)

**Explicit layout.** The chart is a column of panes. **Each pane holds exactly *two* stacked canvases** spanning its full width, and the axes have none of their own: the price-axis strips (left and right) are painted on the pane's own base canvas, and the bottom pane paints the time axis along its lower edge. The WebGL backend adds no canvas to the pane (§3.4).

```
chart container
├── pane 0 (price)     [ base canvas: left axis | plot | right axis ] + top canvas over it
├── pane separator (drag to resize)
├── pane 1 (volume)    [ base canvas: left axis | plot | right axis ] + top canvas over it
└── pane 2 (RSI)       [ base canvas: left axis | plot | right axis, time axis below ] + top canvas
```

- **base canvas**: background, grid, series, indicator lines, the bottom- and normal-layer primitives, and the axis strips with their tags. Repainted on `Light`/`Full`. The order and position lines are `PriceLine`s on the normal layer, so every step of an order-line drag repaints its pane's base canvas at `Light` (§9.3), and so does a hover change on a primitive of this canvas.
- **top canvas**: the crosshair with its price and time tags, and the top-layer primitives: drawings over the series and any drawing lifted for a drag, with their hover rings, handles and magnet ring, and the pane legends, tables, buy and sell buttons, trade markers and time navigator. Repainted on `Cursor`, without touching the base canvas.
- **The axes share the base canvas.** An axis-label change repaints the pane's base canvas, and every base repaint redraws the axes. Separate axis canvases were the original plan and remain unbuilt (§13a).

Each canvas has two coordinate systems:
- **media size** = CSS pixels (what you reason about: "draw at x=100").
- **bitmap size** = `media × devicePixelRatio` (the real backing buffer).

```
class CanvasLayer {
  el: HTMLCanvasElement
  ctx: CanvasRenderingContext2D
  dpr: number          // window.devicePixelRatio
  mediaW, mediaH       // CSS px
  bitmapW, bitmapH     // device px = media * dpr

  resize(w, h) {
    this.mediaW = w; this.mediaH = h
    this.dpr = devicePixelRatio
    this.el.style.width  = w + 'px'
    this.el.style.height = h + 'px'
    this.el.width  = bitmapW = round(w * dpr)
    this.el.height = bitmapH = round(h * dpr)
  }
}
```

**Two scopes for drawing:**
- *Media scope*: `ctx.scale(dpr,dpr)` applied, draw in CSS px (text, anti-aliased fills).
- *Bitmap scope*: no scaling, draw in device px, snap line edges to integer pixels for crisp 1px lines (candles, grid, crosshair). This integer-snapping is what keeps lines sharp instead of blurry on HiDPI displays.

A single `ResizeObserver` on the container drives `resize()`, and the chart paints inside its callback: resizing a canvas clears it, and the callback runs after the frame's animation callbacks and before the browser paints, so a repaint left to the next frame would show one cleared frame per resize step. A host that injects its own `raf` scheduler owns every frame, so with one the repaint waits for it. We inline the HiDPI sizing rather than depend on a separate package.

**Device pixels, exactly.** Three things keep every canvas one to one with the screen:
- *Pane boundaries on device pixels.* `_paneLayout` rounds each boundary between panes (the running total, not each height) onto a device pixel with `alignToDevicePixels`, within half a device pixel of its weighted share; the container's own outer edge is left alone. It rounds at the ratio the panes were last laid out at, not the ratio now, so DOM boxes, canvases and hit testing all read one layout even when the ratio moves with no event. `exportSVG` lays its panes out at 1, the ratio of the document.
- *The separator's form follows the ratio* (`separatorIsBorder`). At a whole-number ratio it is the pane's 1 px top border, with the canvases starting under it and their last row clipped: 1 px is whole device pixels there, and it is the layout, and the pane-local y, of every earlier release. At a fractional ratio a 1 px border is 1.25 or 1.5 device pixels, which would start the canvases part way into a pixel, so the rule is an element `hairlineHeight(dpr)` CSS px tall (one device pixel) laid over the lower pane's first row, and the canvases start at the pane's own top.
- *The browser's own device box where it gives one.* A second `ResizeObserver` watches every canvas's `device-pixel-content-box` (Chromium and Firefox report it) and `CanvasLayer.setDeviceSize` takes that size when the box starts part way into a pixel; a report more than a pixel from `media × dpr` (what an emulated device scale reports) is refused. The browser reports the box only when it changes, so `CanvasLayer.resize` keeps the last reported size through a resize that leaves it within a pixel of the estimate.

The ratio itself is watched: a `(resolution: Xdppx)` media query for the ratio in force, made again after each change, plus the window's `resize` (a zoom fires it, and it is the one signal left where a query takes no change listener). A change re-lays the panes, re-sizes every canvas and paints at once. A device-scale override that keeps the CSS viewport (a DevTools scale-only emulation) changes `devicePixelRatio` with no resize, query change or ResizeObserver entry at all, so nothing can follow it; a zoom-shaped override, the viewport shrinking as the scale grows, fires both.

### 3.2 Render loop & invalidation (`core/render-loop.ts`, `core/invalidate-mask.ts`)

The central trick for performance: **never redraw more than necessary.** A single global level is too coarse for multi-pane indicators and trade overlays (review point 2). The mask is a **global level + a per-pane map.**

```ts
const InvalidationLevel = { None: 0, Cursor: 1, Light: 2, Full: 3 }

interface PaneInvalidation { level: InvalidationLevel; autoScale: boolean }   // per-pane, merges by max + OR

class InvalidateMask {
  globalLevel: InvalidationLevel
  panes: Map<paneIndex, PaneInvalidation>   // a pane can be invalidated without touching others
  merge(other): void                         // coalesce multiple invalidations in one frame
}
```

What the chart does with it:
- **Cursor work stays on the overlay.** A crosshair move, and a hover change between top-layer primitives, raise `Cursor`: every pane repaints its top canvas and no base canvas is touched.
- **Per-pane invalidation is used by primitives.** A primitive's `requestUpdate` raises its own pane only, at `Cursor` for a top-layer primitive and `Light` otherwise; attaching or removing a primitive and dragging a price axis are pane-local too.
- **A data write repaints the panes whose data or scale moved.** Each write compares what every pane shares, the shared index (its length and the times at either end) and the time scale's window, before and after. A live tick that replaces the forming bar moves neither, so it repaints only its own series' pane, at `Full` so the scale re-measures. The studies computed from that series recompute at the start of the frame that paints the tick, before its mask is taken, and a study recompute repaints only the panes its output lands on: every pane holding one of its plots or primitives, which is its own pane and any pane it targets, such as the price pane for a plot sent to the candles. Legends and the crosshair are on the overlay canvas of the pane they describe and repaint with it. An unrelated pane, and the time axis on the bottom pane, keep their pixels, except while the corner clock is on (`axisChrome.sessionClock`): it has no timer of its own and reads the wall clock as the bottom pane paints, so each such write also repaints that pane's base canvas at `Light`. The bar countdown (`axisChrome.barCountdown`) is read the same way inside the last-price tag, so while it is on each such write also repaints every pane with a price series at `Light`.
- **A write that moves the shared index or the time scale repaints every pane.** An appended bar grows the index, and with the view at the right edge it scrolls every pane by a bar, so every pane and the time axis repaint. A host's own `setData` and `prependData` repaint every pane as well, and so does a study that opens a pane, because making room resizes every pane's canvases.
- **`autoScale` flag per pane**: separates "rescale this pane's price axis" from "repaint at current scale". A `Full` level autoscales every pane it reaches, all of them when it is global.
- **Glides step inside the frame.** Kinetic scroll and the eased wheel zoom schedule no animation frames of their own (`input/kinetic.ts` holds the flick's maths; the wheel zoom chases one target bar spacing, closing `1 - e^(-dt/tau)` of the remaining log distance per frame by real frame time (tau is `ZOOM_CHASE_TAU` in `chart-motion.ts`), with a frame longer than `ZOOM_CHASE_MAX_DT` counted at that cap so a stall never makes the zoom leap, so wheel events between two frames only move the target and never the chart twice; a zoom that starts from rest moves on the event itself by one 60 Hz frame's share, so `barSpacing` has changed before anything reads it). The frame steps them (`ChartMotion._step`) before it takes the mask, so each frame paints the step it made, and a glide asks for one animation frame per frame.
- **No time-scale operation queue.** Fit, bar spacing, right offset, scroll-to-realtime and both glides change the time scale directly, and the repaint goes through the ordinary invalidation. The public mask keeps `addTimeScaleOp` and `timeScaleOps` for compatibility, deprecated and removed in 3.0.0, but `addTimeScaleOp` has no caller in the chart and the frame never reads the queue.
- `chart.invalidate(mask)` merges into the pending mask and schedules one rAF; multiple calls per frame coalesce. What the frame's own first steps invalidate, a glide step or a study recompute, lands in that frame's mask and asks for no frame after it.

```
function frame(now) {                                // Chart._onFrame
  moving = stepGlides()                              // kinetic scroll and eased zoom move the time scale
  flushIndicators()                                  // coalesced recompute, before the mask is taken
  const mask = takePendingMask()
  for (const [i, pane] of panes) {
    const level = max(mask.globalLevel, mask.pane(i)?.level)
    if (level >= Full || mask.pane(i)?.autoScale || easing) autoscale(pane)
    if (level >= Light) pane.paintBase()             // grid, series, primitives, axes
    if (level >= Cursor) pane.paintTop()             // crosshair, hover, dragged primitives
  }
  if (autoscaleStillEasing) invalidate(Light)        // re-arms the next frame
  if (moving) requestFrame()                         // the next glide step, once this one is painted
}
```

Repeated invalidations coalesce into one animation frame. Visible-range reads keep the
series pass bounded by the viewport, but the recompute that runs before it still works over
the full history (a study with a `calcTail` copies its columns and every study compares its
plot points), so retained history and indicator count remain the main sustained-session
budgets (§1).

### 3.3 Chart & Pane orchestration: panes stay in sync

- `Chart` owns: the **single shared time scale** + shared `DataLayer` (§4), an ordered list of `Pane`s, the input manager, the invalidate mask, and the primitive list.
- `Pane` owns: its own price scale(s), its series, its base+top canvases (the axis strips paint on the base one, §3.1), and a height (resizable via pane separators).
- **Top (price) pane and bottom (volume/indicator) panes are always x-synced.** This is structural, not bookkeeping: every series across every pane writes into the *one* `DataLayer`, which assigns a single set of **logical indices** shared by all of them. The shared time scale maps that one index space to x. Therefore:
  - Pan/zoom changes the shared time scale once, and every pane's x-axis moves together, bar-for-bar aligned, by construction.
  - The crosshair's vertical line and time label are computed from the shared time scale, so hovering bar *i* highlights bar *i* in **all** panes simultaneously.
  - A volume bar is guaranteed under its candle because they share the same logical index, even with whitespace/holidays (gapless, §5.3).

There is no "sync the panes" code path that could drift, alignment falls out of the single shared index space.

### 3.4 The render backend port (`render/backend.ts`)

The series pass in `Pane.paintBase` goes through an `IRenderBackend`: `beginFrame` clears the base bitmap, `drawSeries` is called once per series with the same arguments `RendererEntry.draw` takes minus the context, and `endFrame` flushes whatever the backend batched, still inside the plot clip and before the normal-layer primitives so batched series land under the price lines and markers rather than over them. Everything else on the base canvas (background, grid, axes, primitives) the pane draws itself on the 2D context `overlay2d()` returns. The port is that narrow on purpose: the per-frame series pass is the one part of a frame that maps onto a batch of GPU geometry, and text, dashed lines, gradients and the drawing tools are things the 2D context already does well. How the two backends compare in frame time has not been measured.

`Canvas2dBackend` is the shipped backend and the reference the others are held to. It is handed the pane's existing 2D context at `mount` (the base `CanvasLayer` already owns one, and a second `getContext` would split a frame across two op streams) and calls each renderer on it as is, so its op stream is the one every chart drew before the port existed; `tests/e2e/render-parity.spec.ts` diffs it against a frozen pre-port build at zero differing pixels. Which backend a chart gets is decided once, at construction, from the `renderer` option (`'canvas2d'`, `'webgl2'`, or `'auto'`) or an injected `renderBackend` factory, one instance per pane. A factory may decline at run time (no WebGL2 on this device) and the 2D backend stands in, which is why `chart.rendererKind` (and the deprecated `chart.renderer`, the same value under its first name) reports the kind in use rather than the kind asked for. The vector export bypasses the port and calls the renderers directly on the serialising context: a document has no pixels to take from a GPU.

`WebGL2Backend` (`render/webgl/`, shipped as the `openalgo-charts/webgl` tier, which does nothing but call `registerRenderBackend('webgl2', ...)` on import) is the second backend. It does not put a WebGL canvas in the pane. The pane keeps its base canvas and 2D context, and the backend draws the series into one page-wide offscreen WebGL2 surface shared by every pane of every chart, then blits that surface into the base canvas at `endFrame` with a single `drawImage`, under the pane's transform and plot clip. Two reasons. A browser allows around sixteen live WebGL contexts, so one per pane would fail a dashboard of a few multi-pane charts; and a blit into the canvas the pane already owns leaves the pile, `takeScreenshot`, the context-menu snapshot and the parity spec's canvas count untouched, with no `preserveDrawingBuffer` because the copy is synchronous in the same task as the draw. Every Family-A type is emitted natively into one vertex batch (one program, one draw call per flush, in submission order so a wick stays under its body and a fill under its line) with analytic anti-aliasing in the shader: coverage is `0.5 - d` in device pixels, which gives an integer-aligned rect exact coverage and is why the rect-based types land on the very same pixels as the 2D renderers, both reading `candleGeometry`, `barGeometry` and `valuePoints`. A type the batch cannot express (kagi, point and figure, a custom renderer) flushes the batch and draws on the 2D context, so z-order between series is exact. A lost context takes that 2D fallback for the whole frame, and the chart polls `pane.backendDegradation` after each frame: on `'context-lost'` or `'unavailable'` it swaps its factory to `canvas2d` for the rest of the session, moves every pane (later panes match), and emits `'renderer:fallback'` once. Session-long rather than per-frame because a device that has dropped a context once tends to do it again, and a chart that flickers between backends is worse than one that settles on the 2D path.

### 3.5 Vector export (`render/svg-export.ts`)

`chart.exportSVG()` is the frame above run once more, into a context that writes SVG instead of pixels. `SvgContext` implements the subset of the 2D canvas API the renderers, primitives and drawing tools call and serialises each call: paths become `<path>`, text stays `<text>`, and `save`, `translate` and `clip` open nested `<g>` elements that `restore` closes. The export therefore has no renderer of its own to drift from the canvas one. `Pane.paintBase` and `Pane.paintTop` take an optional target, and the export hands them the serialiser with the same `PaneRenderContext` a Full frame builds, minus the crosshair and with hover and drag cleared, so nothing transient reaches the file. Each pane is wrapped in a translated, clipped group that reproduces the DOM box (separator row included), which is why a second pane sits where the screen shows it and not one pixel higher.

Two decisions worth recording:

- **It is synchronous and returns a string**, the way `takeScreenshot` returns a canvas, so the serialiser ships in the base tier rather than behind a lazy import. That cost 3.7 KB Brotli on the base engine and on the chart-only shake reading, and both budgets moved with it. A lazy tier would have made the call async for a document a host almost always wants on a click.
- **A different export size never touches the DOM.** Width and height go through a geometry-only relayout (pane layout size, scale heights, time-scale width) that leaves canvases and flex boxes alone, is put back in `finally`, and is followed by a Full invalidation so every auto scale re-measures against the screen. Resizing a canvas clears it, so the ordinary path would blank the chart for a frame.

Calls with no vector form (`setTransform`, radial gradients, `Path2D`, image data) throw under `strict` (how the tests run, so a renderer that grows a new call fails loudly) and are otherwise recorded in `unsupported` and skipped: a missing logo is a better export than a thrown one. `measureText` is a per-character width table, close enough for the tag boxes and label culling that read it. The e2e spec rasterises the document back through an `<img>` and diffs it against the composited pane canvases, because a string test cannot see an arc flag the wrong way round.

---

## 4. Data model: shared DataLayer + per-series rows

### 4.0 Time representation (single internal model): review point 6

OpenAlgo hands us time in **two formats**: REST history returns **IST date/time strings** (and/or epoch depending on endpoint), while the WS feed returns **epoch milliseconds**. Mixing them is a bug factory. So we define one internal representation and convert at the edges:

- **Internal time = `UTC seconds`** (integer). One number, sortable, timezone-free, what scales and the DataLayer operate on.
- **`originalTime` is preserved** on every data item, the exact value the caller passed in, returned untouched in API callbacks/markers so round-tripping never loses precision or format.
- **Display timezone is separate** from storage. Axis labels and the crosshair format `UTC seconds to IST` (default `Asia/Kolkata`, configurable) at render time only. Storage never shifts by timezone.

Conversion rules (in `feed/`, never in the core):
- REST IST string, parsed as IST, to `UTC seconds`. (Be explicit about the IST offset; do not rely on the host machine's locale.)
- WS epoch ms, `floor(ms / 1000)`, to `UTC seconds`.
- Intraday bar timestamps are the **bar-open** time, bucketed by the candle builder (§10.2).

### 4.1 Shared DataLayer (`model/data-layer.ts`): review point 3

`Bar.oi?: number` carries open interest at the bar's timestamp. It is a level,
where volume is a flow: historical conflation and higher-timeframe buckets take
the latest defined open-interest reading and sum volume. Missing open interest
remains missing, including an entire bucket with no readings; zero is a valid
observation. One-to-one transforms preserve it and price-generated bars omit it.
Live builders clear a prior level when the current tick has no reading, and
partial replay cannot read the completed bar's level before it is revealed.

The store is **not per series.** There is one `DataLayer` per chart that merges *all* series (price, volume, every indicator, across every pane) onto a single time axis. This is what guarantees pane sync (§3.3) and correct alignment of price + volume + indicators.

```ts
class DataLayer {
  // one sorted, de-duplicated set of time points across ALL series to logical indices 0..N-1
  private _sortedTimes: number[]                    // UTC seconds, the shared index space
  private _pointByTime: Map<UTCSeconds, TimePointData>   // merge bucket per time
  private _rowsBySeries: Map<Series, PlotRow[]>     // per-series rows aligned to logical index
  private _baseIndex: number                        // logical index of the latest *real* bar
  // whitespace: a time can exist (for alignment) with no value for some series, which keeps the axis gap-free,
  // but that series simply isn't drawn at that index.

  setSeriesData(series, items): DataUpdateResponse  // bulk; re-merges time points
  update(series, item): DataUpdateResponse          // single point (live); see §4.2
  prependData(series, older): DataUpdateResponse     // history paging; see §4.2
}
```

**As shipped** (`model/data-layer.ts`): each series keeps its bars in one time-sorted array, and one shared `_sortedTimes` array with an `_indexByTime` map is the index space over all of them; there is no `PlotRow` type. A count of how many series hold each time keeps that index in step: a write touches only the bars past the prefix it shares with the series' previous data, and the index changes only where a time enters or leaves the union, merged in from the first position that moved (`addBars`, an out-of-order insert of a new time, a `setSeriesData` that adds a time inside the axis or drops one no other series holds, `removeSeries`). A `setSeriesData` that keeps the set, such as a study's plot rewritten with the source's times, leaves the index as it is or adds its new times at the end. Replacing the last bar leaves it as it is, and appending past the right edge adds one time at its end without a rebuild. On a live tick a study writes its plots in place (`model/indicator-plot-writes.ts`): only the points that moved, and the last one, go through `update`, which finds an older point by binary search.

Key responsibilities:
- **Merge by time, assign logical indices.** Each distinct timestamp across all series gets one logical index; every series maps its data onto that shared index. Adding an indicator that only has values for some bars uses **whitespace** for the rest, so it stays aligned without inventing bars.
- **`baseIndex`** tracks the latest real bar so "scroll to realtime," right-offset, and the last-price line all reference one anchor.
- Per-series `PlotRow[]` are the index-addressable arrays the renderers actually read (the old "indexed OHLC store" idea, now *derived from* the shared layer rather than owned per series).

Why index-based throughout: the time scale maps **logical index to x** linearly, so pan and zoom change two numbers (bar spacing and right offset) rather than any bar data, and non-trading gaps (weekends/holidays/lunch) collapse because absent times simply have no logical index (§5.3).

### 4.2 Data mutation API (review point 4: prepend / merge / out-of-order)

`setData()` + `update(last)` alone can't express history paging or corrections. Full contract:

| Method | Use | Semantics |
|---|---|---|
| `setData(series, bars)` | Initial/bulk load, full replace | Re-merge time points; recompute logical indices; autoscale + fit. |
| `update(series, bar)` | Live tick (hot path) | `time == lastTime`: **replace the stored last bar**, leaving the shared index alone. `time > lastTime`: **append**, advance `baseIndex`, maybe auto-scroll. `time < lastTime`: **out-of-order correction** (see below). |
| `prependData(series, older)` | Lazy history paging on left-pan | Upsert the bars by time, wherever they fall; **shift all logical indices** by the inserted count; **preserve the viewport** by adjusting `rightOffset`/range so the screen doesn't jump. Re-merge time points with existing series. |
| `mergeRange(series, bars)` | Backfill / replace an arbitrary window | **Not implemented.** Planned as a range-bounded replace; `prependData` upserts by time at any position, which covers a backfill that only adds or corrects bars. |

**Out-of-order / late ticks & corrections:** a tick whose time is older than the last bar (late print, exchange correction, reconnect replay) is **upserted by time** into the correct bucket, not appended. The candle builder (§10.2) defines the *policy* (accept within the current bar, reject older than a threshold, or fold into the matching historical bar). The DataLayer just guarantees the merge stays sorted and indices stay consistent. After any prepend/merge, primitives and the trade layer re-anchor to *time*, not to a frozen index, so order/position lines don't drift when indices shift.

### 4.3 Series (`model/series.ts`)

A series is `{ rows: PlotRow[] (in DataLayer), style, kind, priceScaleId, paneIndex }`. `kind` selects the renderer (via the chart-type registry, §6A). Series contribute autoscale info (min/max over the visible logical range, plus any primitive `autoscaleInfo`) to their pane's price scale.

### 4.4 Level of detail (conflation): review point 7

When zoomed far out, many bars share one device-pixel column and drawing each of them paints the same pixels again. The pane's level of detail, on by default (`conflate`) since 2.5.8, draws one OHLC-preserving stick per column instead, so a frame costs the plot's width, not the bar count: 200,000 candles and their volume on a 944 px plot paint 2,886 marks instead of 400,051 (`node scripts/bench-pane.mjs`), and the render bench measures the zoomed-out frame (§11).

- **Trigger**: bar spacing under one candle stick (`floor(dpr)` device px, times `conflationFactor`), which is under one CSS px at a whole pixel ratio. The default `minBarSpacing: 1` never reaches it, and above it the frame is identical (the render-parity spec, every built-in type at pixel ratios 1 and 2).
- **Candles, OHLC bars and high-low bars** merge a column into one stick: `open` = first, `close` = last, `high` = max, `low` = min, `volume` = sum, the last open interest and the closing bar's colours. The shape is preserved at coarser granularity, never a lossy average. **Lines, steps, areas and baselines** keep the first, lowest, highest and last bar of each run per device pixel, a gap kept as a gap; **columns and histograms** keep the lowest and highest. Other renderers, including a host's registered under a built-in name, are drawn in full: they may read fields or neighbours a merge cannot know about.
- **The HLC area** keeps what lines keep plus each run's highest high and lowest low, in order and each once, with one gap bar per gap, so its close line, band edges and gaps match the full frame.
- **Lives in `model/conflation.ts`** (`createLodColumns`), streamed by `render/draw-items.ts` while the pane walks the visible bars in place. Each series keeps its draw items from frame to frame (a renderer or backend that keeps them must copy), and the line renderers draw from point buffers they keep, so the series pass allocates nothing per bar. `conflate: false` draws every bar at every zoom. Data, autoscale, indicators and the crosshair still see every bar. Profile primitives are not series and are unaffected.

---

## 5. Scales: the coordinate math

### 5.1 Time scale (`scale/time-scale.ts`)

State: `barSpacing` (px per bar), `rightOffset` (how many bars of empty space on the right). Mapping:

```
indexToX(i)  = width - (rightVisibleIndex - i) * barSpacing   // media px; renderers snap to device px
xToIndex(px) = rightVisibleIndex - (width - px) / barSpacing
```

- **Pan** = change `rightOffset` by `dx / barSpacing`.
- **Zoom** = change `barSpacing` around a focus index (the cursor), clamped to `[minBarSpacing, maxBarSpacing]`.
- **Tick marks**: pick a "nice" stride (1, 2, 5, 10, 30 min; hourly; daily; monthly) based on `barSpacing` and the bars' interval; label boundaries (a new day shows the date, else the time). NSE-aware: day boundaries and session opens get emphasis.

### 5.2 Price scale (`scale/price-scale.ts`)

Three modes (`linear`, `logarithmic`, `percentage`). Linear mapping:

```
priceToY(p) = height * (1 - (p - min) / (max - min))      // + margins
yToPrice(y) = min + (1 - y/height) * (max - min)
```

Log uses `log10(p)`; percentage normalizes to the first visible bar. **Autoscale**: each frame (on Full or a pane `autoScale` flag), gather min/max `low`/`high` over the visible logical range from each series **plus each primitive's `autoscaleInfo`** (so order/SL/TP lines and indicator bands are never clipped), add top/bottom margins, and snap the range to nice tick boundaries via `scale/ticks.ts`.

`ticks.ts` implements the classic "nice number" algorithm (round step to 1/2/2.5/5 × 10ⁿ) for the price axis; the time axis picks its labels from calendar boundaries instead.

#### 5.2.1 Price-scale features & edge cases (review point 9)

These directly affect Indian instruments, options, MCX, label correctness, and order-line snapping, so they're first-class, not afterthoughts:

- **Tick size / `minMove` + `precision`**: every instrument has a tick (e.g. 0.05 for many NSE stocks, 0.01, 0.10; MCX varies). Drives price formatting *and* order-line snapping: a dragged SL/TP rounds to the nearest valid tick. Sourced per symbol (from instrument metadata, §10).
- **Price formatters**: pluggable `formatPrice(p)`: default decimal by precision, plus percent and custom (e.g. paise, lots, bps). Currency/grouping for ₹ labels.
- **Scale modes**: `linear`, `logarithmic`, `percentage`, and **indexed-to-100** (rebase visible series to 100 at the left edge) comparison mode. **Inverted scale** (flip y, for spreads/short views).
- **Margins & padding**: configurable top/bottom scale margins (fraction), and **edge tick padding** so the top/bottom labels aren't clipped at the pane border.
- **Custom visible price range**: pin the scale to an explicit `[min,max]` (disable autoscale) or set it programmatically; needed for fixed-grid views and replay.
- **Multiple / overlay price scales**: `priceScaleId` lets several series share or split scales: right scale (price), left scale (e.g. a second instrument), and **overlay scales** (volume drawn in the *same* pane as price but on its own hidden scale). Each pane can host a main scale + N overlay scales.
- **Label collision rules**: axis labels (ticks, last price, crosshair, order lines, alerts) compete for vertical space. A label-layout pass de-overlaps them (priority order: crosshair > order/position lines > last price > regular ticks), hiding or nudging lower-priority labels.

### 5.4 Time-scale features & edge cases

- **`fitContent` / `setVisibleRange` / `setVisibleLogicalRange` / `scrollToRealtime`** change the time scale directly (§3.2).
- **Right offset** (empty bars after the last) and **bar-spacing clamp** `[min,max]`.
- **Animations**: kinetic scroll decay and eased wheel zoom are stepped by the render frame, before it paints, and schedule no animation frames of their own (§3.2).
- **Whitespace handling**: times that exist for alignment but carry no value for a series don't break tick generation.

### 5.3 Non-trading gaps: gapless by default (locked decision)

**The chart NEVER shows gaps for non-trading time. This is the default and there is no setting to undo it.** Weekends (Sat/Sun), market holidays, and intraday session breaks (e.g. NSE 15:30 to 09:15) all collapse to nothing.

This is not a feature with logic behind it, it falls straight out of the **index-based** time scale. Because x is `index × barSpacing` and there is **no bar row** for any non-trading period, there is no slot to leave blank. Friday's candle is pixel-adjacent to Monday's; a holiday Wednesday's candle is adjacent to Tuesday's and Thursday's. No holiday calendar, no `get_holidays` call, and no "hide gaps" toggle are involved, gaps are *structurally impossible* in the default path.

Consequences to honor in the implementation:
- The time-axis tick logic reads each bar's real timestamp **only to choose labels** (a new day shows the date), never to position bars. A weekend boundary shows the date jump (Fri to Mon) at adjacent pixels, correct and expected.
- Live mode appends Monday's first bar right after Friday's last with no spacer, since the tick bucket simply differs.
- A *"show real gaps"* mode (time-proportional axis) remains possible as an explicit opt-in **later**, relevant only for 24/7 instruments (crypto). For all NSE/BSE/MCX equities, F&O, and commodities it stays off forever.

---

## 6. Renderers

Each renderer is a pure-ish function: `(ctx, drawData, scope) => void`. No internal state beyond style caches. This keeps them independently tree-shakeable (importing only `LineSeries` shouldn't pull candle code).

- **candles.ts**: compute `barWidth = optimalBarWidth(barSpacing, dpr)` (odd/even parity matched to crosshair for symmetry, a subtle but important parity trick); draw body rect + high/low wick; up/down/doji colors; hollow option. Colours are set bar by bar (a per-bar colour can override any candle), and a body that would repaint its own wick at the `wick` width tier is skipped.
- **line.ts**: walk-line algorithm, single `ctx.beginPath()` over the visible range, `lineTo` each point, one `stroke()`. Optional area fill with a cached vertical gradient. Step/curved/straight modes.
- **histogram.ts**: volume bars in the volume pane; per-bar color (up/down). Base value configurable.
- **crosshair.ts**: vertical + horizontal dashed lines on the overlay canvas. Default 'normal' mode tracks the pointer exactly; opt-in 'magnet' mode snaps the horizontal line to the nearest OHLC value (price pane only). Drives the axis labels.
- **grid.ts**: vertical lines at time ticks, horizontal at price ticks, drawn on the data canvas behind series.
- **axis.ts**: price-axis labels (right), time-axis labels (bottom), the moving crosshair label box, and last-price label.

---

## 6A. Chart type catalog & the three rendering families

The full set you want spans **three architecturally distinct families**. The key design decision: a **Series Type Registry** where every chart type registers a descriptor `{ dataKind, transform?, renderer, scaleMode }`. The chart core doesn't know about specific types, it just runs the descriptor. Adding a new style = adding one descriptor. This is how we support a long list without bloating the core, and how *you* (or users) can author **custom chart styles**.

```ts
interface ChartTypeDescriptor {
  name: string                       // "renko", "footprint", …
  dataKind: 'ohlc' | 'tick' | 'bidask'   // what feed granularity it needs
  scaleMode: 'time' | 'ordinal'      // x-axis: real time, or per-element (brick/column)
  transform?: ISeriesTransform       // raw to derived series (Family B); omit for A
  renderer: ISeriesRenderer          // how to paint it
  bundle: 'base' | 'transform' | 'profile'  // which tier it ships in
}
registerChartType(renkoDescriptor)   // pluggable
```

### Family A: Time-indexed (1 element per time bar): **pure renderer swap, Tier 1**

Same `DataStore`, same time/price scales as candles; only the renderer differs. From your screenshot, all of these are Family A:

| Type | Renderer notes |
|---|---|
| **Bars** (OHLC) | left tick = open, right tick = close, vertical = range |
| **Candles** | body + wicks (the baseline renderer) |
| **Hollow candles** | body hollow when `close ≥ open`, filled when down; color by close-vs-prevclose |
| **Volume candles** | candle **body width ∝ volume** (needs per-bar width from volume, not fixed bar spacing) |
| **Line** | walk-line over `close` |
| **Line with markers** | line + a dot at each point |
| **Step line** | horizontal-then-vertical segments |
| **Area** | line + gradient fill to baseline |
| **HLC area** | three lines (H, L, C) with fill between H and L |
| **Baseline** | area split above/below a reference price, two colors |
| **Columns** | vertical bars from a base value (close-based) |
| **High-low** | thin vertical line per bar from low to high (no open/close) |

These cost almost nothing to add, they're variations of three renderers (`bars.ts`, `line.ts`, `histogram.ts`, `candles.ts`). **Heikin Ashi** also lands here visually but is technically a transform (see Family B) since it derives smoothed OHLC; it stays 1:1 with time so it keeps the time scale.

### Family B: Price/movement-transformed (derived elements, **non-uniform x**): **Tier 3 `transform/`**

Renko, Range bars, Point & Figure, Kagi, Line Break. These **re-bucket** raw data into a *new* synthetic series driven by **price movement, not the clock**. One source bar can produce zero, one, or many output elements (e.g. a big move = many Renko bricks). Architecture:

1. A **transform pipeline** stage sits between the raw `DataStore` and the renderer:
   ```ts
   interface ISeriesTransform {
     // incremental: feed each raw bar once, in order, emit derived elements
     reset(params): void
     push(bar: Bar): DerivedElement[]   // 0..n new elements (bricks/columns/lines)
     // each DerivedElement carries the source time it formed at, for axis labels
   }
   ```
2. Output goes into a **derived store** that the renderer draws.
3. The **time scale switches to `ordinal` mode**: x = `elementIndex × spacing` (uniform per brick/column), and `index to label` reads each element's *formation time* (so the time axis still shows real dates, just non-uniformly spaced). The price scale is unchanged.

| Type | Transform logic | Renderer |
|---|---|---|
| **Heikin Ashi** | `haClose=(o+h+l+c)/4`, `haOpen=(prevHaO+prevHaC)/2`, … (1:1, keeps `time` scale) | candle renderer |
| **Renko** | emit a brick each time price moves ≥ boxSize (fixed or ATR-based); reversal needs 2×box | brick rects, ordinal |
| **Range bars** | new bar when `high−low` reaches the range setting | candle/bar renderer, ordinal |
| **Point & Figure** | columns of X (up) / O (down); reversal threshold flips column; box size quantizes price | X/O glyph columns, ordinal |
| **Kagi** | single line; flips between thick and thin on a reversal beyond threshold; direction changes at shoulders/waists | variable-width polyline, ordinal |
| **Line Break** | new line only if close breaks the high/low of the prior N lines | rect series, ordinal |

Transforms must be **incremental**: `push` takes each source bar once and never recomputes history, the same `series.update` hot-path discipline as Family A (§4.2). Every push moves the state, so a bar that is still forming is not pushed tick by tick; it goes through a copy of the state (the run below), which is the part that makes live Renko and range bars work.

**In-chart transforms.** The chart applies a Family B transform itself: `Chart.setSeriesTransform(series, spec)` (or `AddSeriesOptions.transform`). The pieces, and where each lives:

- **Registry (base, `model/series-transform.ts`).** `registerSeriesTransform` holds a `SeriesTransformDefinition` per id: its renderer, its options as `IndicatorInput`s, and `create(options)`, which returns the `SeriesTransformRun` the chart drives. The transform tier fills it on import, so the base never loads a transform, the same inversion as the chart-type registry.
- **Run (transform tier, `transform/live.ts`).** Holds the host's bars and the transform's state as of the last closed bar. The newest bar is forming: each tick pushes it through a copy of that state (`ISeriesTransform.clone`), so its elements are provisional and never baked into the state (CLAUDE.md, never cache the forming bar); a newer bar commits it. Elements get the same one-second bumps `runTransform` gives, so a run's elements are always the batch transform of its bars. Sizes a spec leaves at 0 are resolved from the history on each load, never per tick, and kept through a history page.
- **Routing (base, `core/chart-series.ts`).** A transformed series keeps the run beside its data id. `setData`, `update` and `prependData` feed the run the host's bars and write its elements to the DataLayer; `getData` returns the run's bars, so replay and a feed's live path see what they wrote. A tick writes only the tail that moved: in place through the DataLayer's live path when it grew or was replaced, whole otherwise, recorded as a correction so a study never splices a tail onto an element that is gone. The one rewrite that stays live is the element still forming dated forward at its index by a newer source bar (a Kagi vertex, a range bar it extends): the same element revised, recorded as a replace or an append. That tick and the switch into or out of a transform live in `core/chart-series-transform.ts`, which `registerSeriesTransform` installs: no series can hold a transform before something is registered, so a chart-only import, which registers nothing, carries neither.
- **Studies (base, `model/indicator-bar-source.ts`).** A study computes on the elements (`'chart'`, the default) or on the host's bars (`'underlying'`), whose values are then read at the source bar each element was completed on, so its points stay on the elements' times and the shared axis stays the elements'.

### Family C: Profile & order-flow (price × {volume | time | bid-ask}): **Tier 3 `profile/`**

These are not OHLC series at all, each x-slot (or session) holds a **distribution over price**. This is the heaviest family and has a hard **data dependency** (flagged below).

| Type | What it draws | Data needed |
|---|---|---|
| **Volume Profile** | horizontal histogram of volume-at-price (POC, Value Area 70%), as session / visible-range / fixed-range | OHLCV (approx: spread each bar's volume across its H-L) **or** ticks (exact) |
| **TPO / Market Profile** | letters/blocks marking which time-periods (e.g. 30-min) traded at each price; POC, Value Area, Initial Balance, single prints | intraday bars (e.g. 1-min, bucketed into TPO periods) |
| **Volume Footprint** | per-candle grid: each price row shows **bid volume × ask volume**, colored by delta; imbalance highlighting (diagonal bid/ask) | **trade-level data classified bid/ask** (or L1 bid/ask + trade prints) |
| **Orderflow** | footprint **+ cumulative delta** line, **stacked imbalances**, absorption/exhaustion markers | same as footprint |

**Profile data model:** a price-bucketed array per slot/session:
```ts
interface PriceBucket { price: number; bidVol: number; askVol: number; tpoCount: number }
interface ProfileSlot { startTime; endTime; buckets: PriceBucket[]; poc; vah; val }
```
Renderers draw **horizontally** (volume profile / footprint cells) rather than the vertical OHLC paradigm, but reuse the **same price scale** (price to y), they just bucket price into rows of `tickSize × N`.

**Data dependency (be honest about this):**
- Family A & B + Volume Profile + TPO are all derivable from what OpenAlgo already serves (`get_historical_data` OHLCV + intraday bars). Volume Profile/TPO from OHLCV are *approximations* (volume distributed across the bar's range); good enough for most, but not "true" tick-accurate.
- **Footprint & Orderflow require trade-by-trade data with bid/ask classification** (was each print at the bid or the ask?). OpenAlgo gives live `get_market_depth` (current L1/L2) and tick LTP via WS, but **historical footprint needs recorded tick/trade history**, which OpenAlgo does not store by default. Two paths:
  1. **Live-only footprint**: build footprint in real time by classifying incoming WS trade ticks against the live bid/ask, and persist a rolling buffer for the session. Works for today's session, not for arbitrary history.
  2. **Tick recorder**: add an OpenAlgo-side tick/depth recorder (DB table) so historical footprint/orderflow can be replayed. This is a backend feature, not a charting one, flag it as a prerequisite.

This data-tiering is why footprint/orderflow ship as a **separate lazy-loaded bundle**: most users won't have tick history, and we shouldn't tax the base bundle for a feature gated on a data pipeline.

### Custom chart styles (extensibility)

Because every type is just a `ChartTypeDescriptor`, **custom styles are first-class**: a user provides a `transform` (optional) + a `renderer` and calls `registerChartType()`. The four built-in families are themselves authored this way, there's no privileged "core" type. This directly satisfies "ensure we can create custom chart styles like Renko, Range bars, P&F." (Those four ship built-in; the *mechanism* is open for anything else, e.g. a custom "Better Renko", Heikin-Renko, or a proprietary footprint variant.)

## 7. Input handling (`input/`)

- **pointer.ts**: normalizes mouse + touch + pen into one stream (pointerdown/move/up, wheel, gesture). Tracks single vs multi-touch.
- **pan-zoom.ts**:
  - mouse and pen drags pan time and price by default; `navigation.mousePan: 'horizontal'` limits them to time. Touch keeps two-axis panning. Drag the price axis to rescale price (manual mode); drag the time axis left to expand spacing or right to compress it.
  - wheel to zoom around cursor (Shift = horizontal pan, Ctrl/Cmd = faster zoom).
  - two-finger pinch to zoom; flick to **kinetic** momentum (velocity decay each frame).
  - double-click or the bottom Reset view control restores the preferred visible bar count and price autoscale. `navigation.defaultVisibleBars: 0` fits all loaded bars; positive counts show the latest requested bars without discarding history.
- **hit-test.ts**: on move, ask each primitive "are you under (x,y)?" so order lines highlight and become draggable. Returns the topmost hit with a cursor hint (e.g. `ns-resize` over an order line). As shipped (`core/pane.ts`), a primitive that declares `hitBounds` is asked only when the pointer is inside its box, which the pane keeps until the scales, the layout, hover or drag, or the primitive's own `requestUpdate` change, and the walk stops at an exact hit (`distance: 0`) among the primitives painted in front, which nothing after it can outrank.
- **Pointer facts on every gesture payload.** `crosshair:move`, `click`, `drag` and `drag:end` carry `modifiers`, `pointerType` and `pressure`, built by one pair of module-level helpers so a field a browser omits degrades to the pointer events spec's stand-in (0.5 while a button is held, 0 otherwise) rather than to `undefined`. A pressed move also carries the coalesced `samples` since the last event, projected through one `getBoundingClientRect` and one pane layout per event rather than per sample. Click pressure is the press pressure, because a release always reads 0.

---

## 8. Primitive / plugin API (`primitives/`)

The extension point that keeps the core small and powers the trade layer. The earlier minimal interface was too small for real trading tools (review point 8). The full `IPrimitive` API provides multiple **view surfaces**, **lifecycle hooks**, **z-order**, **autoscale contribution**, and **hit-testing**.

```ts
interface IPrimitive<TParams = AttachedParams> {
  // ── lifecycle ──
  attached?(p: TParams): void          // p = { chart, series, requestUpdate } refs
  detached?(): void
  updateAllViews?(): void              // viewport changed, recompute view data
  // primitives call the injected requestUpdate() to schedule a repaint when their
  // own state changes (e.g. an order moved), drives a targeted per-pane invalidation.

  // ── view surfaces (each returns cached arrays; new array only when changed) ──
  paneViews?(): readonly IPaneView[]              // main chart area
  priceAxisPaneViews?(): readonly IPaneView[]     // drawing inside the price-axis strip
  timeAxisPaneViews?(): readonly IPaneView[]      // drawing inside the time-axis strip
  priceAxisViews?(): readonly IAxisView[]         // FIXED labels on the price axis (e.g. order price)
  timeAxisViews?(): readonly IAxisView[]          // fixed labels on the time axis (e.g. event time)

  // ── autoscale ──
  autoscaleInfo?(start: Logical, end: Logical): { priceRange: {min,max} } | null

  // ── hit-test (priority + distance for disambiguation) ──
  hitTest?(x: number, y: number): {
    zOrder: 'bottom' | 'normal' | 'top'   // ties broken by z-order
    cursor?: string                        // e.g. 'ns-resize' over an order line
    externalId: string                     // which element (for click/drag routing)
    // engine picks the nearest hit by pixel distance, then by z-order
  } | null
  hitBounds?(rc): { left, top, right, bottom } | null  // box outside which hitTest answers null; the pane asks
                                                       // hitTest only inside it and keeps the box until scales,
                                                       // layout, hover or the primitive's requestUpdate change
}

// each IPaneView exposes its z-order so primitives layer correctly vs series:
interface IPaneView { zOrder(): 'bottom' | 'normal' | 'top'; renderer(): { draw(ctx, scope) } | null }
```

Notes that matter for the trade layer:
- **`requestUpdate`** (injected at `attached`) is how an order line says "I moved, repaint me" without the app polling, it raises a per-pane `Cursor`/`Light` invalidation (§3.2).
- **Z-order** (`bottom`/`normal`/`top`) controls layering: grid/zones at `bottom`, order/position lines at `normal`, the line being dragged + crosshair at `top`.
- **Fixed axis labels** (`priceAxisViews`) are how an order line gets its price tag pinned on the right axis, and an event marker gets its time tag, distinct from drawing in the pane.
- **Hit-test returns distance + z-order** so when an order line, an alert line, and a position line stack near the cursor, the engine drags the intended one.

`price-line.ts` is the reusable base (a horizontal line at a price with a fixed right-axis label, color, style, optional drag handle); orders, SL, TP, breakeven, alerts, and indicator levels are all `PriceLine`s. Primitives register per-series or per-pane and draw in z-order after series. The same API powers user price lines, trend lines, and price alerts, with the trading equivalents built in as first-class.

### 8.1 Series markers: buy/sell signals & shapes (`primitives/markers.ts`)

Price/bar-anchored glyphs attached to specific bars, added via a `createSeriesMarkers(series, [...])` factory. This covers buy/sell **signals** (strategy entries/exits, actual fills) and arbitrary **shapes**.

```ts
interface SeriesMarker {
  time: Time
  position: 'aboveBar' | 'belowBar' | 'inBar' | 'atPrice'
  price?: number                     // required when position === 'atPrice'
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square' | 'triangleUp'
       | 'triangleDown' | 'diamond' | 'flag' | 'text'
  size: 'tiny' | 'small' | 'medium' | 'big'   // four discrete sizes (see below)
  color: string
  text?: string                      // e.g. "BUY", "SELL", "EMA cross"
  id?: string                        // for hit-test / click callbacks
}
const markers = createSeriesMarkers(series, [...])   // add/update/remove later
```

Behavior:
- A **BUY signal** = `{ shape:'arrowUp', position:'belowBar', color:'#26a69a', text:'BUY' }`; a **SELL** = `{ shape:'arrowDown', position:'aboveBar', color:'#ef5350', text:'SELL' }`.
- Markers outside the visible range are skipped before drawing (a marker with styled text is still laid out). The skip is a test per marker, not a binary search, so the cost grows with the marker count. The bar under a drawn marker is found by binary search in its own series, and where that series has no point, in the host's fallback bars; those are indexed into a map, once per paint, only when that search misses. So the history length enters a paint only for a mark the fallback search cannot find.
- Multiple markers on one bar **stack** (vertical offset accumulates). Markers with text above or below the bar, or on a pane edge, also take **lanes**: each is pushed outward just past any earlier label on its side whose box it overlaps, on one bar or on neighbouring bars, by at most five of its own heights, and a label that overlaps nothing is not moved. Where labels outnumber the room (a wide zoom) the rest overlap on their bars. The layout reads at most two windows of 256 marks before the first one drawn, from a start that moves in whole windows, so lanes hold while the view pans and a paint does not grow with the history.
- `aboveBar`/`belowBar` offset from the bar's high/low; `inBar` sits at the body; `atPrice` pins to an exact price-y.
- Hit-test enabled: hover highlights, click fires `onMarkerClick(id)`.
- **OpenAlgo tie-in**: auto-plot real executions from `get_trade_book` (buy fills as up arrows, sell fills as down arrows at fill price), and let strategies push live signal markers via the API.

#### Shape sizing: tiny / small / medium / big (locked)

Markers (and shape glyphs generally) support **four discrete size presets**, not a free pixel value, so they stay visually consistent and DPI-crisp:

| Size | Base glyph px (CSS) | Use |
|---|--:|---|
| `tiny` | 6 px | dense scalping signals, many markers per screen |
| `small` | 9 px | default for high-frequency signals |
| `medium` | 12 px | standard buy/sell arrows |
| `big` | 16 px | emphasis / sparse swing signals |

The renderer multiplies the base by `devicePixelRatio` and snaps to integer device pixels, and clamps the glyph so it never exceeds the current `barSpacing` (a `big` marker auto-shrinks toward `small` when bars are tightly packed, so it never swamps the candles). Text labels scale their font with the same four-step ladder.

### 8.2 Event markers: Earnings / Dividends / Splits (`primitives/event-markers.ts`)

The **E / D / S badges** shown just above the time axis (earnings/dividend/split events). These are **time-anchored only** (no price), so they're a *pane* primitive drawn in a dedicated strip above the time-axis, not a series marker.

```ts
interface ChartEvent {
  time: Time
  type: 'earnings' | 'dividend' | 'split' | 'news' | string   // custom types allowed
  label: string                     // 'E', 'D', 'S', or short text
  color?: string                    // defaults per type
  guideLine?: boolean               // dotted vertical line up through the chart
  tooltip?: Record<string, unknown> // EPS est vs actual, div amount + ex-date, ratio…
}
const events = createEventMarkers(chart, [...])
```

Behavior:
- Rendered as small rounded badges in a bottom strip; same gapless index to x mapping, so a badge sits under its bar regardless of weekends/holidays.
- Hover (hit-test) opens a tooltip overlay with the `tooltip` payload (earnings: estimate vs actual, surprise %; dividend: amount, ex/record dates; split: ratio). Click to `onEventClick(event)`.
- Reuse the same four-size ladder (`tiny`/`small`/`medium`/`big`) for badge size.

**Data dependency (honest note):** OpenAlgo serves market data and orders but **not a corporate-actions / earnings calendar**. So earnings/dividend/split events need an external source (NSE/BSE corporate-announcements feed, or a third-party calendar API) normalized into `ChartEvent[]`. Buy/sell signals and trade-fill markers have **no** such dependency (they come from your strategy or `get_trade_book`). The event-marker *renderer* ships regardless; only the data feeding it is your integration step.

Both 8.1 and 8.2 live in the **base bundle** (they're tiny, part of the ~1.8 KB primitives budget plus a little for the event strip) and need no engine changes.

---

### 8.3 The drawing tier (`draw/`): the 2.0 model

Drawings are pane primitives (a `DrawingLayer` per pane, implementing `IPrimitive`), driven by a headless `DrawingController` that owns the model, the history and the selection and ships no DOM. Four decisions from the 2.0 rebuild are worth recording, because each replaced something that had shipped and looked fine:

- **Paint order is a field, not a side effect of creation.** `zIndex` below zero paints under the series, at or above zero over it, with ties broken by list order; two layers per pane (`'bottom'` and `'top'`) are what lets a drawing sit behind the candles at all. The default of 0 reproduces 1.9.2 pixel for pixel, which the render-parity harness enforces at zero differing pixels, so "add an ordering" could not quietly move anything. A drawing can also sit inside the series band, directly above the price source or one study (`stackAbove`): the controller keeps one `'series'` layer per entry it is placed on, and the pane paints a primitive placed with `chart.setPrimitiveStackAbove` right after that entry's last series, flushing a batching backend first. Only orders the bands can paint are offered (`ChartObjects.place` refuses the rest), and the front layer answers hits for every layer of its pane front to back, so the pointer takes what is painted on top.
- **Text is its own block.** Seven text keys had accumulated on `DrawingStyle`, where every trend line carried them and no host could tell a label colour from a stroke colour without knowing the tool. `drawing.text` is closed to the `DrawingText` keys; `style` stays what a stroke needs.
- **A tool declares which of its fields a host may show** (`schema.ts`, `drawingSettingsSchema`), as dot paths with a control kind, and only fields its `draw` reads. A schema is not a wish list: a control backed by nothing is a defect (see CLAUDE.md). The registry lookup lives in `registry.ts`, not `schema.ts`, because `registry.ts` reads the field constants at module-evaluation time and the reverse import would throw on the temporal dead zone.
- **Load is lenient, paste is strict.** `migrate.ts` upgrades any 1.9.x array or v2 document and keeps whatever it can render, dropping a malformed optional field on its own rather than the drawing; the clipboard sanitiser rejects a body all-or-nothing. A saved layout is the user's own work and deserves the benefit of the doubt; a paste is foreign input.

The level palette (`levels.ts`) is the one statement of the conventional colour per Fibonacci ratio. Before it, each ladder tool restated those colours, and restated colours drift.

**Where the code lives.** The registry is `registry.ts`, and what the built-in tools paint with (stroke, fill, text face, readout plates, text layout) is `tool-paint.ts`. The tools come in families: `tools.ts` (lines, shapes, curves, freehand, cycles, and `BUILTIN_DRAWING_TOOLS` in registration order), `fib-tools.ts`, `measure-tools.ts`, `annotation-tools.ts`, `advanced-lines.ts`, `advanced-geometry.ts`, `pattern-tools.ts` and `analysis-tools.ts`. `DrawingController` is a facade the way `Chart` is (see Chart internals): it keeps every public method with its documentation, and three collaborators hold the rest, each reaching it through a host interface typed from its own members: `drawing-history.ts` (the undo and redo branches, the step being recorded and the host's own edits), `drawing-drag.ts` (a drag from its start to its end or cancel) and `pane-layers.ts` (each pane's layers, the preview and the magnet ring). `screen.ts` (every conversion between data space and the screen) and `gestures.ts` (the measure, box select and eraser) predate them.

**Interaction feel (2.0).** The second half of the rebuild is about how a drawing behaves under the hand, and each piece was placed where it was for a cost reason:

- **Hover is a controller fact, painted by the layer.** The chart already emits `hover` at state-change rate; the controller keeps the id (`hovered()`, `drawing:hover`) and hands it to the layer, which paints that drawing's handles faintly. Both drawing layers report their hits at `'top'`, whichever band they paint in, so a hover change between drawings raises `Cursor` rather than `Light`, and the base and the series never repaint for a pointer that merely passes over a line.
- **Freehand reads the crosshair, not the drag.** Placement mode swallows the pan path and never arms a drag, so the coalesced `samples` a fast stroke needs ride on `crosshair:move` while `pressed` (and on `drag` for a primitive being moved). The chart projects the batch through one `getBoundingClientRect` and one pane layout per move event rather than per sample, because that is the pointer path. On release the trail is thinned (`rdpSimplify`) and painted as a spline (`catmullRom`) by `freehand.ts`, which is pure and exported; a pen's pressure is stored per anchor and kept by the clipboard and the migration, and the thinning is why a straight stroke persists as two anchors.
- **The magnet lands on the bar, not on the price alone.** A snapped anchor takes the hovered bar's time as well as its O/H/L/C, so it sits on the bar centre where the ring is drawn; `'weak'` needs `priceToCoordinate` to judge "within a few pixels" and does not pull without it. Shift's angle lock projects the pointer onto the nearest 45 degree ray (it does not rotate), so a level line ends under the pointer's x, and it bypasses the magnet, ring included.
- **An under-series drawing is lifted for the length of a drag.** Moving something that paints below the candles would otherwise repaint the base tier every frame. The bottom layer re-lists on the first drag frame and on release (one `Light` each) and the drag itself is `Cursor` only, the same cost as dragging an over-series drawing.
- **Pointer payloads grew, nothing changed.** `crosshair:move`, `click`, `drag` and `drag:end` gained `modifiers`, `pointerType` and `pressure` with the pointer events spec's stand-ins, so a host never reads `undefined` or a value outside 0..1; key sets are pinned by test so a later addition is a deliberate one.
- **Icons are one registry, three surfaces.** `icons.ts` holds the path data for both grids (24 for tools, 16 for chrome); `icon-svg.ts` derives inline markup, a sprite and a CSS cursor from it, so the rail, a flyout and the tool cursor cannot drift apart. Each tier's stroke is set so its line is about 1.3px at the size it is drawn for (`ICON_SIZE` 20 for tools, `CHROME_ICON_SIZE` 16 for chrome), so both rails show one fine line. Through 2.6.2 both drew a 2px line at their grid size, crisp on every straight edge but heavy beside the chart; weight is what reads first. Each path is the whole glyph: the marks that tell siblings apart (anchor dots, pole caps, arrowheads) are outlined in it, so a host that draws only the path data loses nothing that identifies a glyph. An accent registry repeats those marks for a fill, which the builders paint as a second, unstroked path in `currentColor`. Unit tests hold the grid, margins, stroke and marks, and a browser spec rasterises both tiers in three engines at their display sizes, as markup and as bare path data, and fails on look-alike pairs and on the two tiers drawing different weights.

### 8.4 The reference host (`examples/yfinance`)

The engine ships no DOM, so every toolbar, dialog, rail and popover a user meets is host code, and the yfinance demo is where that code is held to the same standard as the engine. In 2.0 it stopped being one 5,700-line page and became a native-ESM host: `index.html` is markup, `styles.css` is every rule, and `src/` is thirty modules that share one `app` object handed to each `init*(app)`. Three decisions shaped it:

- **No bundler, and the library imported by the URL a page would use.** The modules import `/dist/openalgo-charts.mjs` and its tier files directly, so the demo proves the published shape and not a rewritten one. Its own vitest config (`examples/yfinance/vitest.config.ts`, `npm run test:demo`) maps that URL onto `dist/`, which is why the demo suite runs after the build in `npm run verify`. Module top level is declarations only, so the import graph may have cycles (the toolbar opens the compare dialog, the compare dialog refreshes the toolbar) without any module reading another's binding before it exists; a test imports every module outside a DOM to keep it that way, because in the page the failure would be a blank document.
- **The drawing chrome is built from what the tier ships, not redrawn.** The rail and its flyouts render from the icon sprite, the cursors and the chord table the draw tier exports; the properties bar is generated from `drawingSettingsSchema`, so a control exists only where a tool's `draw` reads the field. A schema-driven bar cannot show a control with nothing behind it, which is the defect CLAUDE.md names.
- **The data path is typed and the layout is versioned.** The feed turns the server's status and `code` into `NotFoundError`, `RateLimitedError`, `NetworkError` and `AbortedError`, with a deadline, one retry where a retry can help, and per-slot cancellation so a fast symbol switch cannot land the older answer under the newer name. The layout document carries its own schema number beside the engine's and the draw tier's, runs migrations in order, and quarantines rather than deletes what it cannot read: the layout is the user's work, and the fault may be in the reader. The server (`server.py`, standard library plus yfinance) validates every parameter, answers every fault with a status and a token, and has a `--fixture` mode of deterministic synthetic bars, which is what the end-to-end spec (`tests/e2e/yfinance.spec.ts`) drives the page against.

### 8.5 The widget tier (`widget/`): the chrome as a package

Every claim in 8.4 about the host still holds for the engine: the base creates chart containers and canvases, while application controls remain outside the eight non-widget tiers. What 8.4 left every host to write, though, is the same toolbar, rail, settings dialog and right-click menu, and a host that only wanted a terminal was rebuilding the demo. `openalgo-charts/widget` is that host, packaged: `createWidget(container, options)` puts a `.oac-widget` root into the container with a top bar, a stage (the rail beside the chart) and a status line, creates the chart and the drawing controller inside it, and hands every mounted piece one `WidgetContext`. It is a tier rather than a base feature for the same reason the trade layer is: a host that never calls it downloads none of it, and the base row in `.size-limit.json` did not move.

- **It drives the engine only through the public API, and the build proves it.** The widget imports `openalgo-charts` and `openalgo-charts/draw` by their package specifiers and nothing by path; the ESLint tier ACL rejects a relative import of `../core` or `../draw` in `src/widget/` (which would inline a second `Chart` or `DrawingController` into the bundle) and rejects any import of the widget from another tier. Rollup marks every `openalgo-charts/<tier>` specifier external and emits sibling paths, `check-dts.mjs` fails a widget declaration file that declares `DrawingController`, and `check-shake.mjs` asserts the `oac-widget` CSS scope is absent from a chart-only build. The skills coverage script imports the built tier under Node, so a module-scope `document` access fails the release: only `createWidget` may touch the DOM.
- **Every dialog is generated, never hand-listed.** Chart settings come from `chartSettingsSchema`, indicator settings from the descriptor's inputs and generated style keys, drawing properties from `drawingSettingsSchema`, the right-click menu from the `contextmenu` payload and `priceAxisState`. One control renderer (`form.ts`) draws them all, which is how the paired up/down colour row, the styled checkbox and select and the swatch size from the UI standard are decided once. A control therefore exists only where the engine has something behind it, which is the defect CLAUDE.md names.
- **The shell owns the theme, the symbol and the interval; the chart owns everything else.** The engine has no instrument concept, so symbol and interval live in the shell, drive the feed from there, and are published on the widget bus (and `symbol` on the chart's bus, for a link group). The chrome's colours are `--oac-` custom properties derived from the active `ChartTheme` by `tokens.ts` and written inline on the root, so canvas and chrome cannot disagree and `setTheme` recolours both. Persisted state is validated field by field and the viewport is applied only to the dataset it was captured on: a range of bar indices means nothing on other bars, so a saved layout landing on another symbol keeps its indicators, drawings and panes and drops its view.
- **One keymap, capture phase, scoped.** Every chord (the rail's, the editing keys, the tool chords, the dialogs') registers with a scope, and the shell resolves the active scopes once per key: `overlay` alone while anything is open, else rail, chart, widget, global. A claimed chord is stopped before the engine's `ShortcutManager` sees it; a binding may decline (the nudge arrows with nothing selected) so the chart still pans. Collisions with the engine's own table are reported and struck through in the `?` panel rather than silently winning.

The e2e spec (`tests/e2e/widget.spec.ts`) mounts the built tier from the static server the way a page would, because a stylesheet that failed to apply or a dialog that opened behind the chart passes every fake-DOM test.

## 9. The trade-management layer (`trade/`): advanced on-chart trading

This is the differentiator and ships as a **separate entry point** (`openalgo-charts/trade`) so chart-only users don't pay for it. Everything here is built on the primitive API above; the chart core stays trading-agnostic.

### 9.1 Components

- **order-line.ts**: `WorkingOrderLine`: a draggable horizontal line for each open/working order (LIMIT/SL price). Shows side (BUY/SELL), qty, order type, distance-from-LTP in ticks/₹, and a close (x) to cancel. Dragging it calls `modify_order`; dropping it on the LTP cancels or converts. Color-coded buy=green / sell=red.
- **position.ts**: `PositionMarker`: a line at average entry price with a filled band to LTP showing **live unrealized P&L** (₹ and %), quantity, and breakeven (entry ± charges). Updates on every tick from the WS feed.
- **bracket.ts**: `BracketGroup`: SL line + Target line linked to a position as **OCO**. Dragging SL/TP modifies the child orders; visually shows risk (red zone below entry) and reward (green zone above) with R:R ratio. This delivers the core advanced-trade-management ("ATM strategy") workflow.
- **dom-ladder.ts**: `DomLadder`: an optional vertical price ladder docked to the right axis showing bid/ask sizes per price level (from `get_market_depth`), with click-to-place at a level and visual order/position rows. This is a full depth-of-market ladder docked to the chart. **Depth-agnostic by design**: see §9.3: it adapts to whatever level count the broker returns (5 / 20 / 30 / 50 / 200).
- **trade-controller.ts**: the brain. Subscribes to OpenAlgo order book / position book / depth, reconciles them into primitives, translates gestures into OpenAlgo REST calls, and handles optimistic UI + rollback on reject.

### 9.2 Gesture to action mapping

| Gesture | Action | OpenAlgo call |
|---|---|---|
| Drag on price axis at price P (armed BUY) | Place LIMIT buy @ P | `place_order(LIMIT, BUY, qty, P)` |
| Drag a working-order line to P′ | Modify order price | `modify_order(orderid, P′)` |
| Click the close segment on an order line | Cancel order | `cancel_order(orderid)` |
| Drag SL line | Modify stop child order | `modify_order(sl_orderid, …)` |
| Drag TP line | Modify target child order | `modify_order(tp_orderid, …)` |
| One-click BUY/SELL button | Market order at qty | `place_order(MARKET, side, qty)` |
| "Close" on position marker | Flatten | `close_all_positions` / `place_smart_order(qty=0)` |
| Reverse | Flip position | `place_smart_order` with opposite target |

All destructive/outward actions (place/modify/cancel) go through a **confirm + arm** gate (configurable: confirm dialog, or "armed" click-to-trade mode like pro DOMs), never fire an order on a stray drag.

### 9.3 State reconciliation

`trade-controller` is the single source of truth:

```
on WS order update / poll order_book:
  diff against current WorkingOrderLines to add/move/remove primitives
on WS position update / poll position_book:
  update PositionMarker price, qty, P&L
on WS depth (get_market_depth):
  update DomLadder bid/ask sizes
on every LTP tick:
  recompute P&L, breakeven, R:R; the position line asks for a repaint
```

The position and order lines are `PriceLine`s, which paint on the normal layer of the base canvas, so a P&L update (`updatePositionPnl`) raises `Light` on the line's own pane, not `Cursor`. A tick that also moves the price series repaints the price pane at `Full` anyway, and every pane when it appends a bar (§3.2). The cost of either has not been measured.

### 9.4 Variable market depth (5 / 20 / 30 / 50 / 200 levels)

Depth is **broker-dependent**: standard NSE Level-2 is 5 bid + 5 ask, but some brokers stream 20, 30, 50, even 200 levels. Every depth-consuming component (`dom-ladder.ts`, footprint/orderflow) is built **depth-agnostic**: it reads the level count from the payload at runtime, never assumes 5.

```ts
interface MarketDepth {
  bids: { price: number; qty: number; orders?: number }[]   // length = broker's level count
  asks: { price: number; qty: number; orders?: number }[]
  ltp: number; ltq?: number; totalBidQty?: number; totalAskQty?: number
}
```

Rendering rules that scale from 5 to 200:
- **Viewport virtualization**: the ladder draws only the price rows currently visible in its strip (a window centered on the LTP), not all 200 (`visibleRows`, capped at `maxRows` nearest the centre). Scroll/recenters on LTP. With 5 levels this is a no-op; with 200 it bounds the rows drawn to what fits. Its frame cost has not been measured. (Same culling discipline as the bar renderer.)
- **Price-bucket aggregation**: optional: group every N ticks into one row when the book is deep, so a 200-level book can be shown compactly (configurable tick grouping / price-step).
- **Size heatmap**: per-row background opacity ∝ qty / maxVisibleQty, so large resting liquidity stands out. With deep books this is the basis of an optional **depth-heatmap over time** (liquidity as a 2D color field), a natural future feature *enabled* by 20 to 200 level data, parked in the `profile/` tier.
- **Auto-detect**: on subscribe, request the broker's max available depth; the component sizes its row pool to `max(bids.length, asks.length)` from the first message and adapts if it changes.

This means the same `DomLadder` works unchanged whether a broker gives 5 or 200, deeper books just unlock richer visuals (full ladder, heatmap), never break the component.

**Graceful degradation (review point 13):** the ladder declares a capability tier from the live payload, **(a) 5-level** compact ladder (default, every broker), **(b) 20/30/50-level** full ladder + heatmap when the broker streams it, **(c) none** to if depth isn't available for an instrument/broker, the DOM simply doesn't render and chart trading falls back to axis-drag / one-click order entry. No depth ≠ broken chart.

### 9.5 Order/trade state machine (review point 12)

Chart trading mutates real money, so the trade layer is a **strict state machine**, not optimistic guesswork. Each working order is tracked through explicit states:

```
            placeOrder()                 ack (orderid)            (fill events)
  [idle] ---------------> PENDING_PLACE -----------> WORKING --+-> PARTIAL --> FILLED
                              |  reject                  |       |
                              v                          |       '-> FILLED
                          REJECTED <--------reject-------+
                                                          | modifyOrder()
                                          MODIFY_PENDING <+-------------------> WORKING (new price)
                                          CANCEL_PENDING <' cancelOrder() ----> CANCELLED
   (on reconnect, any non-terminal order whose id is absent from a fresh orderbook) -> STALE to reconcile
```

Hardening rules each transition obeys:
- **Idempotency**: every outbound action carries a client token; a retry after a timeout never double-places. Reconcile by `orderid` from the orderbook, not by assuming the request succeeded.
- **Optimistic UI + rollback**: show the order line immediately on `PENDING_PLACE` (greyed/dashed); solidify on `WORKING`; **remove and toast on `REJECTED`**. Never show a *filled position* optimistically, positions update only from the position book.
- **Reconnect recovery**: on WS reconnect, refetch order/position/trade books and **diff** against on-chart primitives: add missing, remove vanished (`STALE`), reconcile prices. The chart's truth is always the latest book snapshot.
- **Tick-size rounding**: any dragged price snaps to the instrument's `minMove` (§5.2.1) *before* sending; reject sub-tick prices client-side.
- **Price-band / freeze-qty validation**: pre-validate against the instrument's allowed price band and freeze quantity; block and explain rather than letting the broker reject. Margin pre-check via `getFunds()` before arming.
- **Rate limiting**: coalesce rapid drag-modifies (debounce) and cap order actions/sec so a frantic drag doesn't spam `modifyorder`.
- **Analyzer / sandbox mode**: OpenAlgo's analyzer (paper) mode is a first-class switch: the same gestures route to the sandbox, the chart badges itself "ANALYZER" so a paper order is never mistaken for live. The state machine is identical; only the endpoint target differs.
- **Confirm + arm gate**: destructive actions pass through the §9.2 confirm/arm gate before entering `PENDING_PLACE`.

---

## 10. OpenAlgo integration (`feed/`)

### 10.0 Adapter contract vs naming (review point 11)

**Three different naming surfaces exist for the same operations, don't conflate them:**

| Our adapter method (stable) | OpenAlgo **REST** endpoint (what we actually call) | MCP tool name | Python SDK |
|---|---|---|---|
| `getBars()` | `POST /api/v1/history` | `get_historical_data` | `client.history()` |
| `getQuote()` | `POST /api/v1/quotes` | `get_quote` | `client.quotes()` |
| `getDepth()` | `POST /api/v1/depth` | `get_market_depth` | `client.depth()` |
| `placeOrder()` | `POST /api/v1/placeorder` (+ `/placesmartorder`, `/basketorder`, `/splitorder`) | `place_order` | `client.placeorder()` |
| `modifyOrder()` | `POST /api/v1/modifyorder` | `modify_order` | `client.modifyorder()` |
| `cancelOrder()` | `POST /api/v1/cancelorder` | `cancel_order` | `client.cancelorder()` |
| `getOrders()` | `POST /api/v1/orderbook` | `get_order_book` | `client.orderbook()` |
| `getPositions()` | `POST /api/v1/positionbook` | `get_position_book` | `client.positionbook()` |
| `getTrades()` | `POST /api/v1/tradebook` | `get_trade_book` | `client.tradebook()` |
| `getFunds()` | `POST /api/v1/funds` | `get_funds` | `client.funds()` |
| `getHolidays()` | `GET /market/holidays` | `get_holidays` | none |
| `getTimings()` | `GET /market/timings` | `get_timings` | none |
| `getIntervals()` | `POST /api/v1/intervals` | `get_available_intervals` | `client.intervals()` |

> The chart depends **only on the left column** (our `DataFeed`/`TradeFeed` adapter methods). The `OpenAlgoFeed` adapter is the *only* file that knows the REST paths/payloads. The MCP/Python names earlier in this doc were convenience labels, the **REST endpoints are the real contract** (market routes are registered under `/market/...`, order/data routes under `/api/v1/...`). Verify exact paths/auth against the running OpenAlgo build before coding the adapter, and pin them in one constants file.

- **History** (`feed/openalgo-rest.ts`): `POST /api/v1/history` to bulk `setData()`. Intervals from `/api/v1/intervals`. Indian specifics: NSE/BSE/NFO/MCX exchanges; `/market/holidays` and `/market/timings` feed *session-awareness extras* only (not gap logic, §5.3).
- **Live** (`feed/openalgo-ws.ts`): OpenAlgo WebSocket for LTP / Quote / Depth to the **candle builder** (§10.2) to `series.update()`; Depth to DOM ladder; LTP to P&L.
- **Trading**: the order/book/funds endpoints above, behind the `TradeFeed` adapter + state machine (§9.5).
- **Options** (later): option chain / greeks (Black-76 off the synthetic future for Indian F&O, see your `black76-indian-options` note) / synthetic future / expiries to indicator primitives (IV bands, max-pain line).

### 10.2 Live candle aggregation (`feed/candle-builder.ts`): review point 5

**The WS feed does not give interval candles.** OpenAlgo's LTP mode gives a tick *price* (+ last-traded-qty); Quote mode gives *day* OHLC + *cumulative day* volume, neither is the OHLC of the current 1-/5-/15-min bar. So the client **builds** interval candles. This is its own module with explicit policies:

```ts
class CandleBuilder {
  constructor(intervalSec, opts: {
    sessionResetAt?: 'daily',          // start a fresh first-bar each session
    volumeMode: 'ltq-sum' | 'day-delta', // LTP: sum ltq; Quote: diff cumulative day volume
    lateTickPolicy: 'foldIntoBar' | 'dropOlderThanPrevBar',
    tz: 'Asia/Kolkata',
  })
  onTick(price, ltq, cumDayVol, tsMs): Bar   // returns the (mutated or new) current bar
}
```

Rules:
- **Bucketing**: `bucket = alignToSession(floor(tsUTC / intervalSec) * intervalSec)`. The same bucket as the current bar updates `high/low/close`; a new bucket emits/appends a fresh bar (`open = price`).
- **Session reset**: the first bar of each session starts at the session open from `/market/timings`, not at an arbitrary `floor`, so daily/weekly buckets and the 09:15 open are correct (and align with gapless indices, §5.3).
- **Volume handling**: *LTP mode*: accumulate `ltq` into the bar's volume. *Quote mode*: volume arrives as **cumulative day total**, so the bar's volume = `cumDayVol − cumDayVolAtBarStart` (a delta), never the raw cumulative number. This distinction is a classic bug source; it's explicit here.
- **Late-tick policy**: a tick older than the current bar's open is either folded into the matching (current/previous) bar or dropped if older than a threshold; it never silently appends out of order. Ties into the DataLayer's out-of-order upsert (§4.2).
- **Timezone normalization**: all bucketing is on `UTC seconds` (§4.0); IST appears only in labels.
- **History-to-live seam**: the builder is seeded with the last historical bar so the first live tick continues that bar (or correctly starts the next), implementing the buffered handoff from §10.1.

### 10.1 Live + historical (one consistent API surface)

The engine handles both modes through a **simple two-method contract**, so the mental model is consistent:
- **Historical**: `series.setData(bars)`, bulk-load a fetched range; autoscale + fit-content; this is the static/backtest/replay case.
- **Live**: `series.update(bar)` applies a same-time bar as the stored last candle and appends a newer-time bar. Updates arriving before one animation frame are coalesced into one paint of the price pane and of the panes of the studies computed from it; an appended bar repaints every pane (§3.2). Each such frame still recomputes the studies before it paints, so hosts should bound retained history for sustained sessions.

Standard live behaviors: **auto-scroll to realtime** only when the user is already at the right edge (don't yank the view if they've scrolled into history), a **last-price line + label**, and **lazy history paging**: when the user pans left past the loaded range, fire `getBars(olderRange)` and prepend. Family B transforms and Family C profiles consume the *same* `setData`/`update` stream; the transform/profile pipelines are incremental so live ticks extend Renko bricks / footprint cells correctly without recompute.

A thin `DataFeed` interface decouples the chart from OpenAlgo so the engine itself stays broker-agnostic and independently testable. **Note:** `subscribeBars` is *optional*, `OpenAlgoDataFeed` is history-only (REST), and live bars come from `OpenAlgoLiveDataFeed` (REST + WS + candle builder) or by wiring `OpenAlgoWsFeed` LTP ticks through a `CandleBuilder` yourself.

```ts
interface DataFeed {
  getBars(req): Promise<Bar[]>
  subscribeBars(req, onBar): UnsubscribeFn
  subscribeDepth?(req, onDepth): UnsubscribeFn
}
interface TradeFeed {
  placeOrder(o): Promise<{orderid}>
  modifyOrder(id, patch): Promise<void>
  cancelOrder(id): Promise<void>
  subscribeOrders(cb): UnsubscribeFn
  subscribePositions(cb): UnsubscribeFn
}
```

`OpenAlgoDataFeed` / `OpenAlgoTradeFeed` implement these against OpenAlgo's REST + WS. Swapping brokers later = new adapter, zero chart changes.

---

## 11. Build, tooling, size enforcement & testing

- **Language**: TypeScript, `const enum` for zero-cost enums, strict mode.
- **Bundler**: Rollup + `@rollup/plugin-terser`. Output: ESM (primary), one entry point per tier, nine in all (§2), so they tree-shake and lazy-load independently; and a script-tag build of the same nine entries as classic scripts (IIFE) for a page that loads no modules. `openalgo-charts.standalone.js` defines the `OpenAlgoCharts` global and each `openalgo-charts.<tier>.standalone.js` adds itself to it under the tier's name. A tier's script leaves the base (and, for the widget, the draw tier) external exactly as its ESM file does and reads it from the global, so every tier registers into the one base on the page; a banner stops a file loaded before what it reads. The widget's script carries its first-use parts, since a classic script cannot share a split chunk. `npm run check:exports` holds each global key set to its tier's `.d.ts`. There is no CommonJS build for the same reason: a second copy of the code would hold a second set of registries (chart types, indicators, drawing tools, render backends, widget dialogs) that `createChart` never reads. Each export's `default` condition resolves `require()` to the ESM files (Node 20.19+ and 22.12+ load them synchronously, as the same instance `import` gets).
- **Size CI**: `size-limit` with **Brotli** targets per tier. Since we have zero runtime dependencies, nothing is excluded from the measurement. PRs exceeding a limit fail CI. The planned hard ceilings of 30 KB Brotli for the engine and 50 KB for base + trade were pre-implementation targets and were never enforced; the enforced ceilings are the per-tier rows in `.size-limit.json`, quoted in the README size budget.
- **Performance is budgeted per bar count.** `tests/e2e/render-bench.perf.ts` (`npm run bench:render`, a CI job of its own) holds pan, full zoom-out and ten-study tick frames at 10,000, 50,000 and 200,000 bars, on `canvas2d` and WebGL2, to the budgets in `scripts/render-bench-budgets.mjs`, and `docs/performance-notes.md` records the measurements. `npm run bench` holds indicator calculation to CI budgets and fails unless a burst of ticks recomputes each study once per frame. `scripts/browser-endurance.mjs` records frame, pointer, memory and teardown gates for a declared Chromium workload, run nightly with the soak (§1, `docs/browser-endurance.md`).
- **No dependencies**: HiDPI sizing, resize observation, and event handling are hand-rolled (~50 lines total).

### 11.1 Testing: starts in Phase 2, not "once stable" (review point 14)

Charts are visual and interaction-heavy; deferring tests guarantees regressions. The test pyramid comes online alongside the code:

- **Unit (Phase 2+)**: pure math: scale mappings, `ticks.ts` nice-numbers, DataLayer merge/prepend/index-shift, candle-builder bucketing + volume-delta + late-tick policy, timezone/session conversions. Fast, run on every commit.
- **Renderer pixel-diff (Phase 2 to 3)**: puppeteer + pixelmatch: snapshot each renderer (candles/line/histogram/bars/…) at fixed data + DPR, diff against golden PNGs. Catches sub-pixel/HiDPI regressions.
- **Interaction (Phase 3)**: scripted pan / wheel-zoom / pinch / crosshair / fit-content asserting scale state and that **all panes stay x-synced**.
- **HiDPI (Phase 2 to 3)**: run pixel tests at `devicePixelRatio` 1, 1.5, 2, 3 to lock crisp-line behavior.
- **Timezone/session (Phase 2)**: IST-string and epoch-ms inputs produce identical internal `UTC seconds`; session resets land on 09:15; weekends/holidays stay gapless.
- **Fake OpenAlgo feed + order simulator (Phase 2 to 3)**: a deterministic in-memory `DataFeed`/`TradeFeed` that replays recorded history, emits scripted ticks/depth, and simulates the full order state machine (acks, partials, rejects, reconnect-with-stale-orders). Lets the chart and trade layer be tested with **zero broker/network**, including reconnect-recovery and out-of-order ticks.

---

## 12. Implementation roadmap

Build in vertical slices so there's always a runnable chart. **Testing infra (size-limit + unit + pixel + fake feed) lands in Phase 1 to 2 and grows with each phase (§11.1).**

0. **Project + measurement harness**: repo, Rollup tiers, `size-limit` (Brotli) wired, fake `DataFeed`/`TradeFeed` stub, pixel-diff harness skeleton. *(so every later phase is measured, not guessed)*
1. **Skeleton**: DOM/canvas layout (base+top per pane, axis strips on the base canvas), render loop + per-pane invalidate mask + resize. Hardcoded grid. *(proves HiDPI + loop)* + first `size-limit` numbers replace the estimates.
2. **Static candles**: shared DataLayer + time/price scales (incl. tick-size formatting) + candle renderer + axes. Load history (`setData`) via the REST adapter. *(proves core math)* + unit + pixel + timezone/session tests.
3. **Interaction**: pan, wheel-zoom, crosshair, autoscale, fit-content, kinetic, lazy history paging (`prependData` + viewport preserve). *(this is "a chart")* + interaction + HiDPI tests; assert pane x-sync.
4. **Live**: WS to candle builder (§10.2, volume-delta + late-tick + session reset) to `series.update`; last-price line, auto-scroll, volume pane. *(historical + live parity)* + fake-feed tick/out-of-order tests.
5. **Family A complete**: Series Type Registry + all 12 time-indexed renderers from the screenshot (bars/hollow/volume-candle/line+markers/step/area/HLC-area/baseline/columns/high-low). *(cheap, high payoff)* + per-renderer pixel goldens.
6. **Primitives**: full primitive API (views/lifecycle/z-order/hit-test) + price-line base + markers + event-markers + one indicator (EMA) to validate it.
7. **Family B (`transform/`)**: transform pipeline + ordinal scale mode; Heikin Ashi, Renko, Range, P&F, Kagi, Line Break, each incremental for live.
8. **Trade layer (read-only)**: order/position/bracket primitives + live P&L, driven by the state machine reconciling the books. No order placement yet.
9. **Chart trading (write)**: arm/confirm gate + drag-to-modify + one-click + brackets/OCO + tick-size/price-band validation + analyzer mode. Tested entirely against the order simulator first.
10. **DOM ladder** (5-level to deep + heatmap, graceful degradation) + polish.
11. **Family C (`profile/`)**: Volume Profile + TPO from OHLCV first; Footprint + Orderflow once the OpenAlgo tick-recorder backend exists. *(gated on data pipeline, §6A)*
12. **Conflation** (§4.4) + cross-tier `size-limit` hardening.

Each phase is independently demoable and measurable against the size budget. Phases 1 to 6 deliver a full professional-grade chart with every standard style; 7+ are the differentiators.

### 12.1 Documentation & developer experience (docs-as-you-go track)

Documentation is a **first-class deliverable, produced alongside the code, not deferred.** Every public API gets TSDoc when it's written; every phase ships at least one runnable example. The doc set:

| Artifact | What | When | Tooling |
|---|---|---|---|
| **TSDoc on public API** | Doc comments on every exported type/method give IDE intellisense + source for the API reference | continuous, from Phase 1 | TSDoc, lint-enforced |
| **API reference** | Auto-generated from the bundled `.d.ts` / TSDoc | regenerated each phase | dts-bundle-generator + TypeDoc |
| **Getting started** | Install (npm + CDN), "chart in 10 lines", OpenAlgo data wiring | Phase 2 | Markdown |
| **Guides** | One per topic: chart types & custom styles, multi-pane/sync, live+historical feed, markers/signals/events, indicators | grows per phase (5 to 11) | Markdown + live demo |
| **Trade-layer guide** | Chart trading, order/position/bracket lines, DOM ladder, the order state machine, arm/confirm **safety**, analyzer mode | Phase 8 to 10 | Markdown + demo |
| **Primitive/plugin authoring** | How to write a custom chart style (`ChartTypeDescriptor`) and a custom primitive (the §8 API), extensibility is a headline feature, so this guide is essential | Phase 6 to 7 | Markdown + template |
| **Examples gallery** | Runnable demos, one per chart type + trade scenarios | per phase | Vite demo app |
| **Migration / interop note** | API shape and how to port from other charting libraries | Phase 5 | Markdown |
| **README + CHANGELOG + LICENSE/NOTICE** | Repo basics; NOTICE per §0.1 licensing stance | Phase 0, maintained | Markdown |

Two principles: **(1) the API reference is generated, never hand-maintained** (it can't drift from the types); **(2) each guide links a live, runnable demo** so docs are verified by the example actually working. A "docs lint" (TSDoc coverage on public exports, dead-link check) runs in CI like `size-limit` does. This adds a documentation checkpoint to phases 0, 2, 5, 6 to 10 rather than a separate phase.

### 12.2 Releasing a version

A release is a documentation change first and a version bump second, because
once a version is on the registry the docs that shipped with it are what every
reader of that version sees. Three rules fell out of getting this wrong:

- **A major ships its own migration guide.** 2.0.0 changed the drawing model
  (`toJSON` returns a document, text is `drawing.text`, fib levels are objects,
  `select` takes a list) and one default (`animZoom`). Each is small on its own
  and easy to miss in a changelog, so `docs/migrating-to-2.md` walks a 1.9.x host
  through every change with the old code, the new code and the reason, and the
  README, the changelog and the website link it. Stored 1.9.x drawings are
  upgraded on load rather than rejected, so persistence is the one thing a host
  need not touch.
- **Every repeated fact is measured on the build that ships**, never copied
  from the previous release: tier sizes from `npm run size`, counts from the
  registries at runtime, test totals from the runner. They move by hundredths
  whenever the bundle changes at all, so a figure quoted from memory is already
  wrong, and a substitution keyed on the old number silently does nothing. The
  full list of surfaces is in `CLAUDE.md`.
- **The website builds as a gate.** It is a separate build with its own failure
  modes (a colon in MDX frontmatter is a YAML error, an asset path without the
  base path 404s only on Pages), none of which the library's own checks see.

---

## 13. Risk notes & decisions to revisit

- **Touch/pinch correctness** is the fiddliest part, budget extra time; mature charting engines have years of edge-case fixes here that we'll have to earn ourselves.
- **Order-line dragging vs pan**: must hit-test primitives *before* starting a pan, or drags will scroll the chart instead of moving the order. Resolve in `input/hit-test.ts` priority order.
- **Optimistic UI**: show the order line immediately on `PENDING_PLACE`, reconcile/rollback on the book's confirm/reject (§9.5), otherwise chart trading feels laggy. But never show a *filled* position optimistically.
- **Confirm gating**: default to explicit confirm; offer "armed" mode for experienced users. This is a safety + trust decision, not just UX.
- **Time-axis labels**: gaps collapse automatically (§5.3), but tick-label logic must know the instrument's session (from `/market/timings`) to label day/session boundaries and seed the candle builder's session reset correctly.
- **Live performance at 50k bars**: still open. The live workload in `docs/browser-endurance.md` missed its own frame gates at 10,000 and 50,000 bars per chart on 2.5.5 (§1), with only 150 bars in view, so the cost is in work over the whole history rather than in drawing. 2.5.8 writes study plots in place, stops rebuilding the time index on a tick and gives sixteen built-ins a `calcTail`, and the render bench now budgets the tick per bar count, but a tick still grows with the loaded history. The level of detail (§4.4) addresses the zoomed-out draw, not this.
- **`originalTime` round-trip**: every callback/marker/event must echo the caller's original time value, not the internal UTC-seconds, verify in unit tests (§11.1) to avoid format drift.

---

---

## 13a. Deferred / not-yet-implemented (honest status)

The current implementation keeps these boundaries in 2.6.2:

- **Separate price/time axis-widget canvases** - axes draw within the pane
  canvas by design (small-engine simplification).
- **The time-scale operation queue** - `InvalidateMask` keeps
  `addTimeScaleOp` for compatibility (deprecated, removed in 3.0.0), and nothing in the chart queues an
  operation or reads the queue; the time scale is changed directly (§3.2).
- **A tick that does not grow with the history** - the render bench enforces
  frame budgets per bar count (`npm run bench:render`,
  `docs/performance-notes.md`), but a ten-study tick still grows with the
  loaded history rather than the view, about 7.6 times from 10,000 to 200,000
  bars on `canvas2d`; what remains is not profiled yet. The endurance workload
  at 10,000 and 50,000 bars per chart missed its gates on 2.5.5 and has not
  been rerun (§1, `docs/browser-endurance.md`).
- **Hit boxes on the built-in primitives and drawings** - `hitBounds` is
  optional and no built-in primitive declares one yet; the draw tier's
  drawings sit inside one layer primitive per pane that tests every drawing,
  so 500 drawings cost what they did before (`node scripts/bench-pane.mjs`).
- **Primitive price/time axis *views*** - primitives draw in the pane + hit-test
  + autoscale + lifecycle; dedicated fixed axis-label views are future work.
- **OpenAlgo adapter conformance**: injectable transports and offline fixtures
  cover REST and WebSocket wire fields. Validate each connected provider's
  capabilities, timestamps, session rules and reconnect behavior in the host.
- **Independent comparison scales are implemented.** Each comparison retains its
  source units and baseline through named scales. Comparisons are no longer
  restricted to one shared hidden overlay scale per pane.
- **Theme awareness in the profile primitives** - only `Footprint` reads
  `rc.theme`; `VolumeProfile`, `MarketProfile` and `HorizontalProfile` carry
  dark-tuned defaults and need explicit colours on a light theme.
- **The WebGL2 backend covers the standard chart types.** Kagi, point-and-figure
  and custom types, drawings, text and every primitive stay on the 2D context;
  the backend moves the series pass of the standard types to the GPU and is not
  a second renderer. Its frame time against Canvas2D has not been measured.

Shipped since the first draft (were previously deferred): the `percentage` and
`indexed-to-100` price-scale modes, a Playwright/Chromium E2E suite
(`npm run e2e`, with a pixel-level render-parity harness), multi-touch pinch
(zoom + two-finger pan), binary-search visible-range lookup, WebSocket
auto-reconnect with resubscribe, a unified `chart.on(...)` event bus, a
data-driven trading overlay, custom price and time formatters, per-pane
price-scale options, hidden overlay price scales, the Footprint renderer's
visual pass (`setOptions`, three display modes, theme-driven colours, drawn
stacked imbalances), and in 2.0.0 the DOM chrome as a package
(`openalgo-charts/widget`, §8.5), which had been the last item on this list.

## 14. Revision log: v2 (implementation-review responses)

Point-by-point mapping of the implementation review to where each is now addressed:

| # | Review point | Resolution | Section |
|---|---|---|---|
| 1 | Canvas/layout underspecified ("one canvas") | Explicit base+top canvas per pane; the axes paint on the base canvas (separate axis canvases deferred, §13a); layout diagram | §0 table, **§3.1** |
| 2 | Invalidation too simple (global only) | Global level **+ per-pane map (+autoScale flag)**; primitives, live ticks and study recomputes repaint the panes they change, and a write that moves the shared time scale repaints every pane | **§3.2** |
| 3 | Shared time/data layer missing | Single `DataLayer` merges all series by time to shared logical indices, whitespace, `baseIndex`; per-series rows derive from it | **§4.1**, §3.3 |
| 4 | History prepend/update semantics | Mutation API: `setData` / `update` / **`prependData` (index-shift + viewport preserve)**; out-of-order upsert; `mergeRange` not implemented | **§4.2** |
| 5 | Live candle aggregation missing | `candle-builder.ts`: bucketing, **session reset, volume-delta (cumulative-day vs ltq), late-tick policy, tz** | **§10.2** |
| 6 | Time model not explicit | Internal **UTC seconds + `originalTime`**; IST-string (REST) and epoch-ms (WS) convert at edges; display tz separate | **§4.0** |
| 7 | No conflation/downsampling | **OHLC-preserving** level of detail, on by default since 2.5.8: one stick per device-pixel column under about one CSS px per bar | **§4.4** |
| 8 | Primitive API too small | Lifecycle (`attached`/`detached`/`updateAllViews`), `requestUpdate`, **z-order, hit-test w/ distance+priority, autoscaleInfo(start,end)**, and since 2.5.8 an optional `hitBounds` box that spares the hit test; the price/time axis views are designed in §8 and deferred (§13a) | **§8** |
| 9 | Price-scale edge cases | tick size/`minMove`, formatters, inverted, indexed-to-100, custom range, overlay scales, margins, edge padding, label collision | **§5.2.1**, §5.4 |
| 10 | Size claims (gzip vs brotli; area/baseline contradiction) | All numbers in **Brotli** w/ methodology + "measure in Phase 1"; **kept** line/area/baseline/HLC (correction noted); zero-dependency so nothing excluded from measurement | header, §0, **§2**, §11 |
| 11 | Adapter names ≠ real endpoints | Adapter-method / **REST `/api/v1/*` & `/market/*`** / MCP / Python mapping table; chart depends only on adapter | **§10.0** |
| 12 | Trade layer needs a state machine | Explicit states (pending/ack/partial/filled/modify/cancel/rejected/**stale-on-reconnect**) + idempotency, rollback, reconnect recovery, rate-limit, tick rounding, price-band, **analyzer mode** | **§9.5** |
| 13 | DOM ladder depends on depth | Depth-agnostic + **graceful degradation**: 5-level / 20 to 50 deep+heatmap / none, fallback entry | §9.4, **§9.5 note** |
| 14 | Testing too late | Test pyramid from **Phase 1 to 2**: unit, pixel-diff (HiDPI), interaction, tz/session, **fake feed + order simulator** | **§11.1**, §12 |
| 15 | Licensing/attribution | **Project licensed Apache-2.0** (permissive, no copyleft); default clean-room original code; any incorporated third-party routine keeps headers + `NOTICE` attribution | **§0.1** |

**Biggest-gap priority for implementation (per the review):** shared data/time model (§4), then live candle aggregation (§10.2), then per-pane invalidation (§3.2), then primitive lifecycle/hit-test (§8) to realistic size/API contracts (§2, §10.0). These front-load into Phases 0 to 6.

---

*End of document. Next deliverable options: (a) start Phase 0 to 3 as a working prototype in `D:\testing\openalgo-charts` (repo + size-limit harness + shared DataLayer + static candles + interaction), (b) detailed TypeScript interface stubs for every module (DataLayer, scales, primitive API, candle-builder, feed adapters, trade state machine), or (c) the trade-layer + OpenAlgo adapter spec expanded with sequence diagrams.*
