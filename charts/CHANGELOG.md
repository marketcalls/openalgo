# Changelog

All notable changes to OpenAlgo Charts.

## 2.6.4

2026-10-14

An order flow release. A footprint finds the imbalances beside a row that
never traded, prints volume shaded by delta, extends and alerts on the zones
a host picks, and takes a named colour theme or a colour for each of its
parts. A new Order flow page on the website walks through footprint and
market profile charts with live examples.

### Changed

- **An untraded row inside a bar counts as zero for imbalances.** A row
  between a bar's high and low that no trade reached holds zero volume, so the
  cell beside it is compared with zero: the ask above such a row, or the bid
  below it, is an imbalance whenever it traded at all, subject to
  `imbalanceThreshold`. Through 2.6.3 such a cell was not compared, so a thin
  ladder showed fewer imbalances than it had. The rows beyond the bar's high and
  low are still not compared, and a stacked run still stops at the untraded
  row. `diagonalImbalances`, `stackedImbalances`, `footprintSignals` and the
  `Footprint` primitive all follow the rule; the imbalance view fills such a
  cell at full strength.

### Added

- **Delta-shaded volume.** `displayMode: 'deltaShadedVolume'` prints each
  row's volume on a cell coloured by the side that won the row and shaded by
  the size of its delta, so a busy row with little conviction reads pale.
- **Zone alerts.** `footprint.onZoneAlert(handler)` calls the handler once
  for each zone `showZones` extends when a bar's high to low range comes back
  to it after it became active (a jump across it counts), with `{ zone, time }`, and returns the unsubscribe. The first
  bars a footprint is given, and new zones that `setOptions` makes, are
  recorded without a call. Each later `setBars` is the live tail: a touch in
  the bar that was newest at the previous call, or in a later one, is
  reported, so prints batched across a new bar lose nothing. `setBars([])`, or
  bars that start again from an older bar, begin a new history. `FootprintZone` gains `touchTime`, the first bar after `activeTime`
  whose range reached the zone.
- **Which zones extend.** `zoneKinds` picks any of `'stacked'`, `'node'` and
  `'absorption'` (default all three) for `showZones` to extend and alert on,
  and `zoneLookback` (default 0, every bar; also a `footprintSignals` option)
  starts zones only in the newest that many bars.
- **A colour for each part.** `imbalanceBuyColor` and `imbalanceSellColor`
  (imbalanced cells, stacked brackets and stacked zones), `volumeColor` (the
  volume view), `candleUpColor` and `candleDownColor`, `profileAskColor` and
  `profileBidColor` (the visible-range profile), `sessionColor` (session
  letters) and `tableBackground` (the statistics table). Each is optional and
  falls back to the colour it used before.
- **Named themes.** `FOOTPRINT_THEMES` holds six colour sets as options
  patches: `ocean`, `ember`, `forest`, `neon` and `monochrome` for a dark
  chart, `daylight` for a light one. `new Footprint({ ...FOOTPRINT_THEMES.ocean })`.
- **An Order flow page** on the website: footprint and market profile charts
  as live examples, each with a short explanation of how to read it.

### Size

The profile tier is 20.83 kB (was 19.54 kB): about 0.57 kB for the six named
themes and 0.72 kB for the alerts, the colours, the new view and the zone
options. All tiers come to 426.67 kB and the nine classic scripts to
440.43 kB. The base engine, trade, draw and widget bundles differ from 2.6.3
only in their version string, which Brotli turns into a few dozen bytes either
way: the base is 137.65 kB, base plus trade 154.52 kB, the widget terminal
364.04 kB and the base classic script 137.69 kB. Each budget moved to its
measured need. The chart-only import is unchanged at 87.30 KiB.

### Performance

- **Measured against 2.6.3** on the release bench (five runs of each build in
  one session, `benchmarks/releases.json`, the website's Benchmarks page). The
  base engine is the same code as 2.6.3 apart from its version string, so the
  two columns time one renderer twice and their differences are the bench's
  own spread: with Canvas 2D at 200,000 bars a pan, a full zoom-out and a
  ten-study tick measure 2.1, 55.3 and 146.6 ms against 2.1, 53.0 and 150.3 ms
  (each the lowest p95 of its five runs), and no cell differs by more than 10
  percent either way. Every cell is within its frame budget.

### Tests

11690 engine tests across 516 files and 730 reference-host tests across 68
files. Each new behaviour has a test that fails without it: the comparison
across an untraded row and the limit on a gap too wide to be one, the zone
lookback, the touch time, an alert for a live touch, for a touch batched with
the next bar, never for history or a cleared footprint, and only for the kinds
extended, the delta-shaded view, each colour option and the themes. The
widget storage pins no longer change with the library version.

## 2.6.3

2026-10-13

A finish release. The drawing tools and the chrome around them draw one fine
line, the drawing rail folds away so the chart can take its width, the wheel
zoom moves in one smooth motion however fast the wheel turns, and in the widget
and the reference host a drag keeps the price scale fitting what is in view, so
every zoom after it refits. A log scale fills the pane again (#53), and a
tooltip no longer takes the click meant for the control under it. The
reference host moves onto a neutral palette.

### Changed

- **One fine line for every glyph.** `ICON_STROKE` is 1.6 (was 2) and
  `CHROME_ICON_STROKE` 1.3 (was 2). Two new constants, `ICON_SIZE` (20) and
  `CHROME_ICON_SIZE` (16), name the size each tier is drawn for, and `iconSvg`
  now defaults to 20px (it was the 24px grid size). At those sizes both tiers
  draw a line of about 1.3px: through 2.6.2 a rail of tools showed a 2px line,
  half again as wide, on glyphs a fifth larger, crisp on every straight edge
  but nearly twice the ink, and it read as heavy beside the chart it frames. The path data is unchanged except where
  the finer line needed it: the horizontal ray now leaves from two fifths of the
  way in (from a third, it measured 0.71 overlap with the horizontal line at the
  finer line, over the 0.7 the sibling check allows), the paste glyph's clip is
  filled, and the two candle chart-type glyphs draw their solid body as three
  strokes so it stays solid at any line. `toolCursor` keeps a 2-unit line,
  since a cursor sits over candles rather than a quiet panel. A host that wants
  the heavier set passes `{ size: 24, stroke: 2 }` to `iconSvg` and
  `{ stroke: 2 }` to `chromeIconSvg`. The widget's rail, flyouts and menus show
  tools at 20px and chrome at 16px from these constants, and the magnet in the
  rail's controls block is the chrome glyph, so the block is one size.
- **A smoother wheel zoom.** Each wheel event now moves one target bar spacing,
  and every frame closes `1 - e^(-dt/70ms)` of what is left in log space, by the
  real frame time. Before, each event applied part of the zoom on the event
  itself and started a new curve, so three events between two frames painted
  about 60 percent of the outstanding zoom at once, every notch read as a jolt
  then a decay, and a trackpad's small steps were applied unsmoothed. Measured on
  five notches 48 ms apart at 60fps, the largest frame was 5.6 times the frame
  before it and is now 2.8 times. The first notch from rest still moves on the
  event, so `barSpacing` changes before anything reads it synchronously, and
  `animZoom: false` still applies each step at once. `ZoomGlide` is unchanged.
- **The reference host's palette.** The yfinance demo runs on a near-black
  chart (#151619) with neutral grey chrome, a blue accent, the #089981 and
  #f23645 candle pair, and a selected tool shown as a light wash with bright ink
  rather than a coloured frame. The engine's own `darkTheme` and `lightTheme`
  are unchanged. Text on a green or red fill passes 4.5:1: the buy and sell
  buttons and the bracket labels fill with #077d69 and #d32f3c under white
  (5.1 and 5.0 to 1; the candle pair is 3.6 and 3.9), and the price tag on the
  chart carries dark ink.
- **In the widget and the reference host, a drag moves time and the wheel zooms
  about the latest bar.** `createWidget` now defaults `navigation.mousePan` to
  `'horizontal'` and `zoomAnchor` to `'right'`, and the reference host does
  the same. A drag that also moved price switched the pane to manual scaling,
  and from then on a wheel zoom left bars off the pane until auto was pressed
  again; now the scale keeps fitting what is in view through any number of
  drags and zooms. The price axis still drags and scales price, Ctrl or Cmd
  with the wheel still zooms about the cursor, and a host that passes either
  option, or the chart settings' Mouse drag row, keeps its choice. The engine's
  own defaults (`'both'` and `'cursor'`) are unchanged. Through 2.6.2 the
  chart state recorded every navigation option, chosen or not, so every layout
  saved on the default says `mousePan: 'both'`: `getState()` now stamps the
  widget state with `savedBy` (the library version), and a state without the
  stamp, whether restored by `restoreState` or by `persist` on a reload, drags
  the way the widget was built to (its default or the host's option) rather
  than by that recorded value. The reference host does the same through its layout schema 3. A
  drag chosen after this is saved and kept.

### Added

- **The drawing rail folds away.** The last button of the widget's rail
  (chevrons pointing left) hides the rail and gives the chart its column; a
  small tab at the chart's bottom left brings it back. Focus follows the
  control that replaces the one pressed, the tab stops `pointerdown` so the
  chart cannot take the press, and the fold is a rail preference: it persists
  with the pins and the magnet, travels in `getState().rail` (`collapsed: true`)
  and comes back with `restoreState`. `RailHandle` gains `collapsed()` and
  `setCollapsed(on)`, both optional members so a handle a host wrote for
  `mountMobile` still fits. The tab is hidden on the phone layout and in a dense
  grid cell, where the rail already is. The reference host's rail folds the
  same way, below 900 pixels leaving its bottom touch bar alone.
- **Chrome glyphs `chevrons-left` and `chevrons-right`**, for the fold and its
  tab.

### Fixed

- **A log scale fills the pane (#53).** Autoscale padded the margins in price
  units and then drew them in log units: a monthly series from 150 to 1230 got
  a floor near 15, a whole empty decade under its lowest bar, and its bars
  filled the top 42 percent of the pane. The margins are fractions of the pane
  in every mode, so a log scale now pads in log space and the data takes the
  same 80 percent of the pane it takes on a linear scale. A comparison over a
  log scale fits the same way. A range a log cannot take (zero or below, or a
  flat series) keeps the price-space padding.
- **A tooltip no longer takes the click meant for the control under it.** The
  overlay layer turned pointer events back on for everything mounted in it,
  later in the stylesheet and at the same specificity as the tooltip's own
  `pointer-events: none`, so it won: a tip over a button swallowed the press. It
  showed when the bottom bar's range tip sat over the folded rail's tab.
- **Tools that scroll under the rail's controls fade out** instead of being cut
  through by the block's edge, in the widget and in the reference host.
- **The reference host's fold follows the rail.** A full-screen second chart
  takes the rail into its own pane, and the tab and the chart's offset now go
  with it; and the fold waits on the same touch layout that hides the rail (a
  short coarse-pointer window up to 960 pixels wide, as well as anything under
  900). A 24-unit glyph shown at 16px in the rail's menus is drawn at the
  tier's line rather than 1.07px.

### Size

The base engine is 137.61 kB (was 137.44 kB) and base plus trade 154.49 kB, for
the zoom chase and the log padding; the draw tier is 58.44 kB (58.36 kB), the
widget tier 124.94 kB (124.13 kB), the widget terminal 364.01 kB, all tiers
425.35 kB, the nine classic scripts 439.11 kB and the widget classic script
138.53 kB. Each budget moved to its measured need, the base classic script's
to 137.72 kB (137.65 kB). The chart-only import rises 111 bytes to 87.30 KiB for the
zoom chase and the log padding, which every chart carries.

### Performance

- **Measured against 2.6.2** on the release bench (five runs of each build in
  one session, `benchmarks/releases.json`, the website's Benchmarks page). With
  Canvas 2D at 200,000 bars a pan, a full zoom-out and a ten-study tick measure
  2.0, 51.5 and 149.9 ms against 2.0, 53.6 and 150.8 ms (each the lowest p95 of
  its five runs). The tick cells spread widely: at 200,000 bars it ran 149.9 to
  225.2 ms on 2.6.3 and 150.8 to 202.7 ms on 2.6.2, and at 50,000 bars its
  lowest run is 58.1 against 42.6 ms. The script times all five runs of the new
  build before the old one, so both tick cells were timed again with the two
  builds alternating, twelve passes outside the published entry. The lowest
  runs match at 200,000 bars (150.0 against 149.5 ms) and favour 2.6.3 at
  50,000 (49.8 against 56.4 ms), while the medians swing by up to a fifth from
  one session to the next on this machine, in either direction. Nothing in the
  tick path changed beyond a mode check in autoscale. Every cell is within its
  frame budget.

### Tests

11674 engine tests across 516 files and 730 reference-host tests across 68
files. The log scale test fails against 2.6.2 (its bars sat at y 9 rather than
40 of a 400 pixel pane), as do the widget tests for the drag default and for an
unstamped layout. Three wheel zoom tests fail against 2.6.2: events between two frames
move only the target, a trackpad step is eased, and no frame after a new notch
jumps past 3.5 times the one before it. The tooltip test fails against the old
stylesheet. The fold is covered in the widget (folding, focus, the open list
closing, the tab keeping the press from the chart, a reload and a saved state)
and in the reference host. The icon tests now hold each tier to about a 1.3px
line at its display size and the two tiers to one weight, where they held a
2-unit stroke on pixel boundaries; the browser spec rasterises both tiers at 20
and 16px in Chromium, Firefox and WebKit and compares their weight. One
reference-host browser test read the selected chart's frame as the old teal
pixel; it now reads the frame's colour from the page's stylesheet.

## 2.6.2

2026-10-13

A fix for the bottom bar's ranges and the Go to panel, which reported missing
history when the only thing before the first loaded bar was a weekend, a
holiday or the hours before the market opens. Nothing else changes.

### Fixed

- **A range or a date no longer reports history that is not missing.** The
  1M range on a New York stock, run on a Tuesday in India, asked for the month
  from Sunday midnight; the loaded history starts at Monday's 19:00 open, and
  the bottom bar said "Older history cannot load now" for a month that was
  whole. `DateNavigator` (behind `widget.goTo`, the bottom bar's ranges and
  the Go to panel) now asks the chart's session calendar whether any session
  opens between the request and the first loaded bar. When none does, the
  request is `placed` rather than `partial`, and no older page is loaded for
  it. A chart without a session calendar counts any gap as before, and a gap a
  session did trade in is still reported. It failed on any day a month back
  landed on a Sunday or a Monday for that stock, about two days in seven.

### Size

The widget tier is 124.13 kB (was 124.08 kB), the widget terminal 362.94 kB,
all tiers 424.27 kB and the nine classic scripts 438.25 kB. The base classic
script grows 180 bytes from the version string alone: one byte changes, and
Brotli encodes the file differently. The widget classic script (137.78 kB)
carries the fix as well as its own version string. Each budget moved to its
measured need. The chart-only import is unchanged at 87.19 KiB.

### Performance

- **Measured against 2.6.1** on the release bench (five runs of each build in
  one session, `benchmarks/releases.json`, the website's Benchmarks page):
  frames are on par, as this release changes no rendering path. With Canvas 2D
  at 200,000 bars a pan, a full zoom-out and a ten-study tick measure 2.2, 56.0
  and 154.3 ms against 2.2, 55.6 and 157.8 ms (each the lowest p95 of its five
  runs); every cell of both renderers is within 10 percent of 2.6.1.

### Tests

11641 engine tests across 515 files and 726 reference-host tests across 68
files. Five new tests cover the gap rule: the two that check a sessionless gap
is placed, and that no loader is asked across it, fail against 2.6.1, and one
keeps the gap counted when the calendar finds no session at all. The
reference host's one-day range test no longer assumes the session fills the
view: in the first hour or so of a trading day it holds fewer bars than the
closest zoom spreads across the plot, and the session sits whole inside a wider
view.

## 2.6.1

2026-10-13

Order flow depth for the footprint and box sizing for the brick and box charts.
The footprint gains trade classification, a trade size filter, an imbalance view
and two more single-value views, and order flow signals read across bars:
multiple nodes, big limit orders, absorption, aggressive delta flips,
price/delta divergence, zones that extend until price deals with them, and
unfinished auctions. Footprint rows now put a price exactly between two row
centres on the even row. Renko sizes its bricks from price or the ATR and can
build them from the high and low, point and figure gains a box that is a
percent of the ATR, and the widget and the reference host each get a settings
dialog for both chart types. Every new footprint layer is off by default, so a
chart that changes nothing draws as before, apart from the row rule and the
empty rows below.

### Added

- **Trade classification.** `createTradeClassifier(mode)` in
  `openalgo-charts/profile` returns a stateful classifier for raw prints:
  `'tickRule'` (a print above the previous one is a buy, below it a sell, an
  unchanged price keeps the previous side) or `'quote'` (the recorded bid and
  ask first, the tick rule inside the spread or without a valid quote).
- **Trade size filter.** `computeFootprint` and `FootprintAggregator` take
  `FootprintBuildOptions` (`{ minTradeSize }`). Only single prints at least that
  large are counted; smaller ones still open their row, which shows zero, and
  still set the bar's open, high, low and close. Count and volume bars close on
  every print.
- **Unfinished auctions on every bar.** A built bar carries `auction`, every
  print's bid and ask volume at its exact high and low, before any filter.
- **Order flow signals.** `footprintSignals(bars, options?)` and
  `DEFAULT_FOOTPRINT_SIGNAL_OPTIONS` compute multiple nodes, big limit orders,
  absorption, aggressive delta flips, divergence, zones (stacked imbalances,
  nodes, absorption) with an end rule (`'closeInside'`, `'traverse'`,
  `'touch'`) and the time each becomes active, and unfinished auctions. The
  newest bar is treated as forming, so its close never ends a zone and its high
  and low set no auction until it closes. `Footprint.signals()` returns the
  same for a primitive's bars, so a host can raise its own zone alerts.
- **Footprint views and layers.** `displayMode` adds `'imbalance'` (plain cells,
  diagonal imbalances filled by strength, candle body rows shaded and outlined),
  `'deltaPct'` and `'volumeDelta'`. New options: `intensityScope` (shade
  against the busiest row on screen), `compactNumbers`, `multipleNodeBars`,
  `bigOrderMultiple`, `absorptionMultiple`, `signalLookback`,
  `nearExtremeRows`, `flipBars`, `flipMinDeltaPct`, `showZones`, `zoneEnd`,
  `zoneActiveAfter`, `showUnfinishedAuctions`, `showDeltaLabels`,
  `markDivergence`, `showVisibleProfile` (ask and bid volume at price of the
  visible bars against the left edge), `lastPriceColor` and `formingLastBar`,
  with their colours.
- **Session statistics.** `FootprintStatRow` adds `'cumVolume'`, `'cvdRatio'`
  (cumulative delta over cumulative volume) and `'session'` (the period letter,
  anchored the way the market profile anchors its periods). `cvdReset: 'session'`
  restarts cumulative delta and volume at each open of `sessionWindow` on
  `timezone`; `tpoMinutes` sets the letter period.
- **Renko sizing and prices.** `RenkoTransform` takes `mode` (`'fixed'`,
  `'percent'`, `'atr'`, `'atrPercent'`) with `percent`, `atrPeriod` and
  `atrMultiplier`, re-resolved as each brick forms, and `method: 'hl'`, which
  walks the bar's low and high in the order the bar most likely traded them.
  The in-chart `renko` transform offers the same options.
- **Point and figure from a percent of the ATR.** `mode: 'atrPercent'` sizes the
  box as `percent` of the ATR.
- **Settings dialogs for point and figure and Renko.** In the widget, a button
  beside the chart type opens one while the chart builds either type: paired
  colours, percent presets, the size and its method (absolute, percent, ATR or
  percent of ATR), the ATR length, the reversal for point and figure, and close
  only or high and low. It writes through `setSeriesTransform` and the chart
  settings in one undo step and loads on first use. The reference host gets
  the same dialog, saves the options per chart type, and migrates a layout's
  old box mode.
- **Order flow demo.** The order flow example adds the imbalance, delta percent
  and volume x delta views, a tick rule side, a minimum trade size, a chooser
  for every order flow layer with a zone alert, the new table rows, and Ember
  and Forest themes.

### Changed

- **Footprint rows round half to even.** A trade is put on its tick, then on
  its row; a tick exactly between two row centres now goes to the even row
  instead of always up (with 2-point rows on a 0.05 tick, 22469.00 belongs to
  the 22468 row). A price that is not on a boundary lands where it always did.
- **Footprint columns show their untraded rows.** A row inside a bar that no
  trade reached is drawn as 0 x 0 instead of a gap, so every column spans its
  whole range. It changes only the drawing: imbalances, the point of control,
  the value area and the signals still read the traded rows.
  `showEmptyRows: false` draws the gaps as before.
- **The point and figure and Renko box options share one schema**, so the
  chart settings Price tab lists Renko's sizing method first and shows the box
  percent for both percent modes.

### Fixed

- **Saved series colours return with a widget layout.** The widget saved the
  primary series' style and never applied it again, so colours set from the
  settings were lost on reload and on `restoreState`. The style saved for the
  chart type on screen is now applied once the chart restore lands.
- **Reference host dialogs.** The colour palette opened behind a dialog card
  and could not be clicked, and selects in dialogs had lost their chevron.

### Size

Profile tier 19.54 kB (was 14.94 kB), transform 6.23 kB (was 6.07 kB), widget
124.08 kB with eight first-use parts at 21.00 kB, the widget terminal 362.89 kB,
all tiers 424.23 kB and the nine classic scripts 437.85 kB. The chart-only
import is unchanged at 87.19 KiB. Every budget moved to its measured need.

### Performance

- **Measured against 2.6.0** on the release bench (five runs of each build in
  one session, `benchmarks/releases.json`, the website's Benchmarks page):
  frames are on par, as this release changes no rendering path of the chart.
  With Canvas 2D at 200,000 bars a pan, a full zoom-out and a ten-study tick
  measure 2.6, 58.4 and 154.9 ms against 2.4, 57.4 and 154.8 ms (each the
  lowest p95 of its five runs); every cell of both renderers is within 9
  percent of 2.6.0, the largest move being that pan, 0.2 ms.

### Tests

11636 engine tests across 515 files and 726 reference-host tests across 68
files, including row alignment tests that fail with the previous rounding,
signal, zone, session and drawing tests for the footprint, Renko and point and
figure sizing tests, and dialog and restore tests for the widget and the
reference host.

## 2.6.0

2026-10-01

Analysis depth and a stricter API. A chart now applies Heikin Ashi, Renko,
range bars, line break, point and figure and Kagi to the bars a host feeds,
live, and each study chooses whether it computes on the elements drawn or on
the underlying bars. Seven built-in indicators are new, 29 built-ins take an
optional timeframe that computes them on a higher interval folded from the
chart's bars without repainting (#22), the OpenAlgo feed searches symbols
itself, and event markers carry rich details and host actions. `ChartEventMap`
types every event on the chart's bus, every tier ships as a classic script on
one global, `require()` reaches the same ESM files, and the whole library
compiles under `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`,
with declarations that hold for a host compiling that way. Each release is now
checked against the previous one and the version OpenAlgo pins, and the
documents those releases saved load and save again in the test suite. A
hygiene wave gives the drawing actions one rule on every surface, reads study
settings one way across the built-ins and fixes defects in every tier. What a
host can see change: a cast of an event payload to a type it does not overlap
no longer compiles, and `Chart.emit` and the string overloads of `on`, `once`
and `off` are deprecated; a study that offers a timeframe saves
`timeframe: ''`; a widget over a feed transforms its bars for point and figure
and Kagi, and searches through a feed that can when the host passes no lookup;
a fractional window length rounds to whole bars; a throwing chart listener is
reported instead of dropped; `subscribeClick`, `subscribeDrag` and
`subscribeCrosshairMove` keep every subscriber; a variant-only change emits
`data:context` once; a locked selection is neither deleted nor cut from any
surface; the chart data dialog asks for dates on the chart's clock; and the
drawing tools take the theme's up and down colours and whole-pixel strokes. See
the upgrade notes.

### Added

- **Transforms in the chart.** With `openalgo-charts/transform` imported,
  `chart.setSeriesTransform(series, spec)` and
  `addSeries(type, { transform: spec })` have the chart apply Heikin Ashi,
  Renko, range bars, line break, point and figure or Kagi to the bars a host
  feeds; `seriesTransform(series)` reads the choice back, and `null` draws the
  bars as given again. A spec is plain data (`{ type, options? }`), checked
  against the transform's own options before anything changes. The series
  keeps taking the host's bars through `setData`, `update` and `prependData`,
  and `getData` hands those back, so replay, a feed's live path and a host's
  tail arithmetic are unchanged. The chart forms the elements, and forms the
  newest one again on every tick without baking it into the transform's state,
  so a live chart's elements always equal the batch transform of its bars. A
  box, range or reversal left at 0 is sized from the loaded history (a fortieth
  of its range, twice that for range bars and Kagi) on each `setData`, never per
  tick, and kept through `prependData`. A view scrolled into history holds still
  while bricks form, and at the right edge it follows. The bar countdown counts
  down the forming source bar. `addSeries('point-figure')`, `addSeries('kagi')`
  and `setSeriesType` still pick a renderer only, so a host that prepares its own
  elements is never transformed twice. The base carries only the registry
  (`registerSeriesTransform`, `getSeriesTransform`,
  `registeredSeriesTransforms`, `SeriesTransformSpec`,
  `SeriesTransformDefinition`, `SeriesTransformRun`), and every built-in
  transform implements the new optional `ISeriesTransform.clone()`. The chart
  settings Price tab leads with the transform's options under
  `transform.<option>` keys, and chart state records `SeriesState.transform`
  for a transformed series only.
- **Studies on the underlying bars.** `IndicatorApi.barSource()` and
  `setBarSource(source, options?)`, and the `addIndicator` option `barSource`,
  typed `IndicatorBarSource`. The default, `'chart'`, computes on the elements
  drawn, which is what a study computed on when a host fed it elements before.
  `'underlying'` computes on the host's bars and reads each value at the bar its
  element completed on, the value a trader could have read as the brick formed;
  marks the study dates at those bars move to the element they completed into.
  The setting follows the study's `configurable` policy, an attach context's
  `bars()` returns the bars the study computes on, and `IndicatorState.barSource`
  is written only as `'underlying'`. A custom `IndicatorHost` serves it through
  the optional `underlyingBars()`, and the optional
  `IndicatorCalcContext.transformed` tells a study that its bars are a
  transform's elements. On the underlying bars every hook of the study (plot
  colours, markers, background, bar colours, levels, and an alert's `when` and
  `message`) receives the elements and the values sampled onto them, indexed
  by element. Workspace documents and indicator templates keep a series'
  transform and a study's bar source.
- **Transformed chart types in the widget.** With the transform tier imported,
  the chart type menu lists Heikin Ashi, Renko, Range bars, Line break, Point and
  figure and Kagi under a Transforms heading, and `setChartType`, `chartType()`,
  `WidgetOptions.chartType`, saved layouts, the chart grid and link groups accept
  their ids; a layout restores their options, and options this build refuses
  fall back to the transform's defaults. A study's settings dialog leads with a
  Compute on row (Chart bars or Underlying bars) while the chart transforms. A
  page of older history reaches a transformed chart as a prepend, so bricks keep
  their size, and the data window reads the bars drawn.
- **Seven built-in indicators.** ZigZag (`zigzag`), 52 Week High/Low
  (`high-low-52-week`), Zero Lag EMA (`zlema`), Variable Index Dynamic Average
  (`vidya`), Elder-Ray Index (`elder-ray`), Schaff Trend Cycle
  (`schaff-trend-cycle`) and Volatility Squeeze (`volatility-squeeze`), each
  following a published formula with hand-worked reference cases and a warmup
  check, and each with a live tail (`calcTail`), so a tick updates it without a
  full pass. The registry now holds 112 built-ins: Trend 40, Momentum 31,
  Volatility 23 and Volume 18. ZigZag reverses on a percent move (`deviation` 5) and draws its legs
  as lines, the last one dashed; a live tick moves only its last leg, and a
  confirmed point never moves. 52 Week High/Low reads the 364 calendar days
  ending on each bar's day in the chart's zone, and draws nothing until the
  loaded history reaches back that far. Elder-Ray draws bull and bear power as
  two histograms around zero; Schaff Trend Cycle a double smoothed stochastic of
  the gap between a 23 and a 50 bar EMA, from 0 to 100 with levels at 25 and
  75; and Volatility Squeeze its momentum, with a dot that says whether the
  Bollinger Bands sit inside the Keltner Channel.
  `openalgo-charts/indicators` exports `ZIGZAG`, `HIGH_LOW_52_WEEK`, `ZLEMA`,
  `VIDYA`, `ELDER_RAY`, `SCHAFF_TREND_CYCLE` and `VOLATILITY_SQUEEZE`, and the
  family arrays `EXPONENTIAL_INDICATORS` and `SWING_INDICATORS`;
  `VOLATILITY_INDICATORS` gains the squeeze. No existing study's output, default
  or id changes for them.
- **Studies on a higher timeframe** (#22). `withTimeframe(descriptor)` from
  `openalgo-charts/indicators` gives a study a `timeframe` input, and 29
  built-ins carry it: `sma`, `ema`, `wma`, `vwma`, `hma`, `dema`, `tema`,
  `alma`, `smma`, `t3`, `lsma`, `kama`, `mcginley-dynamic`, `zlema`, `vidya`,
  `bollinger`, `keltner-channel`, `donchian`, `envelope`, `supertrend`,
  `parabolic-sar`, `atr`, `rsi`, `macd`, `stochastic`, `stochastic-rsi`,
  `williams-percent-r`, `cci` and `adx`. Empty, the default, the study
  computes and ticks exactly as before. Set, the chart's bars are folded into
  that interval, the study runs on the folded bars, and each bucket's value
  shows once the bucket has closed and holds across the next, so a value shown
  never changes. Sub-day buckets start at the session open read from the loaded
  bars (09:15 on NSE, 09:30 in New York), and days and weeks follow the chart's
  zone. A timeframe no coarser than the chart's is the chart's own. An unknown
  code, a tick or volume interval, a chart whose own bars close on trade flow,
  another study's output as the source and a transformed chart's own bars are
  refused: `addIndicator` throws, and a later setting puts the study in its
  error status until a good one clears it. A tick inside a bucket carries the
  held value, and a bar that opens a bucket recomputes. The legend names the
  timeframe (`EMA 9 close 15m`). In the widget a study's timeframe select offers
  Chart, then the host's `intervals` (`controlsFromInputs` takes them as an
  optional third argument, and `WidgetContext.intervals` carries them). VWAP,
  TWAP, the running totals, the displaced studies and the swing and marker
  studies are left out, with the reasons in the docs.
- **Symbol search through the feed.** `DataFeed` gains an optional
  `searchSymbols(request)` that returns `SymbolMatch[]`, closest first, and
  `SymbolMatch` and `SymbolSearchRequest` are exported from `openalgo-charts`
  (the widget still exports `SymbolMatch`). `OpenAlgoDataFeed.searchSymbols`
  asks OpenAlgo's `/api/v1/search` with the key in the body, as history does,
  keeps the server's ranking to 50 rows, names each row an index, equity,
  futures or options from OpenAlgo's symbology, and groups the options of one
  underlying and expiry into one row that opens onto its strikes. A blank query
  sends nothing, and an error names its status but never the key.
  `OpenAlgoLiveDataFeed` searches through its REST adapter, and `BarCache`
  forwards the member when the feed it wraps has it. A widget given such a feed
  and no `symbolSearch` searches through it in the top bar, the phone layout,
  typed entry, the watchlist and study symbol inputs, and puts the exact symbol
  on the chart's exchange first; a host's own lookup still wins.
- **Rich event details and host actions.** `ChartEventDetails.blocks` carries
  headings, paragraphs and lists whose text may hold bold, italic and link spans
  (`EventDetailBlock`, `EventDetailInline`, `EventDetailSpan`): structure, never
  markup. The event popup renders them as text, and makes a link only of an
  absolute http or https address without credentials, opened in a new tab with
  no referrer; anything else shows as its text. `EventDetailsPopupOptions.actions`
  returns buttons for the shown event (`EventDetailAction`, a `label` and `run`),
  set bottom right; a press closes the popup, then runs with a copy of the
  event. The widget's `eventDetails` option passes both through.
- **A typed event bus.** `ChartEventMap` lists every name on the chart's bus
  with its payload, and `chart.on`, `once` and `off` type the listener from it.
  Importing the draw tier adds its `draw:*` and `drawing:*` names, and a host
  types an event of its own by merging it into `ChartEventMap` with
  `declare module 'openalgo-charts'`. New type-only exports: `EmptyEvent`,
  `ChartHoverEvent`, `ChartDragCancelEvent`, `ChartViewportEvent`,
  `ChartResizeEvent`, `LazyLoadEvent`, `PaneEvent`, `PaneMovedEvent`,
  `PaneMaximizedEvent`, `PaneCollapsedEvent`, `PriceAxisPlacementChangedEvent`,
  `IndicatorInstanceEvent`, `IndicatorDataStatusEvent`, `TimezoneChangedEvent`,
  `PickStartEvent`, `PickEndEvent`, `AlertChangeEvent`, `AlertRemovedEvent`,
  `AlertErrorEvent`, `AlertsChangedEvent`, `AlertsRestoredEvent`,
  `TradingOrderModifyEvent` and `TradingBracketModifyEvent` from the base, and
  `DrawingEvent`, `DrawingListEvent`, `DrawingIdsEvent`, `DrawingIdEvent`,
  `DrawingToolEvent` and `DrawingModeEvent` from `openalgo-charts/draw`. A new
  name is `namespace:action`, lower case, hyphen-joined, in the present tense,
  and no existing name is renamed; both the `draw:*` and the `drawing:*` families
  stay, as two granularities of one model (COMPATIBILITY.md, Kept on purpose).
- **Every tier as a classic script.** Beside `openalgo-charts.standalone.js`,
  the trade, transform, profile, indicators, draw, webgl, workspace and widget
  tiers each ship as `dist/openalgo-charts.<tier>.standalone.js`, so a page that
  loads no modules can use all nine. Each adds itself to the `OpenAlgoCharts`
  global under its tier name (`OpenAlgoCharts.draw.DrawingController`,
  `OpenAlgoCharts.widget.createWidget`) and registers into the base the page
  already loaded. The widget's file carries its first-use panels, so it fetches
  nothing more. A tier file loaded before what it reads throws an error that
  names the files to load first. The tier scripts ship without source maps,
  which every module file keeps. The base file, its map, its global and the
  `unpkg` and `jsdelivr` fields are unchanged.
- **`require()` of the package.** Each export entry gains a `default` condition
  naming the same ESM file, so `require('openalgo-charts')` and every subpath
  return the module `import` returns on Node.js 20.19 and 22.12 or later; an
  older version reports `ERR_REQUIRE_ESM` where it said the path was not
  exported. There is no CommonJS build, by decision: a second copy of the code
  would carry a second set of registries (COMPATIBILITY.md, Runtime boundary).
- **Declarations for a strict host.** Every tier now compiles under
  `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`, and
  `npm run typecheck` holds `src` to both. Optional members the library itself
  sets to `undefined` say `| undefined`, in the widget's options, context and
  handles, the trading requests and results, the alert inputs, chart state, the
  feed requests, `PointFigureOptions` and the rest the upgrade notes list, so a
  host compiling that way can pass `undefined` where the library does.
  `OpenAlgoTradeFeed` now satisfies `OrderFeed` for such a host, and
  `npm run check:dts` compiles a host against the published declarations with
  both flags and without `skipLibCheck`.
- `MenuOptions` gains `placement: 'below' | 'beside'` and `edge`, and
  `openMenu` accepts any context that carries `document`, `openOverlay` and
  `translate`.
- New widget message keys: `{name}: {error}`, `Event details`, `Events`,
  `Loading details...`, `No additional details.` and
  `Unable to load additional details.`, and the schema keys
  `schema.ui.symbolSearchFailed`, `schema.ui.watchlist.entry`,
  `schema.ui.watchlist.noQuote`, `schema.ui.watchlist.quoteLoading` and
  `schema.chartType.group.transforms`.
- The reference host applies the transforms in the chart with a Compute on row
  in each study's settings, forms bricks bar by bar in a replay, offers the
  intervals it serves in a study's timeframe select, shows a sample event with
  rich details and a Mark on chart action, and says why a study stopped drawing
  on its status line and in a toast.
- `AddIndicatorOptions` and `ChartApplyOptions` name the option types of
  `addIndicator` and `applyOptions`, and
  `TradingController.updatePositionPnl(id, pnlText?, pnlPercent?)` takes the
  text without the number the pill never showed.

### Changed

- **Point and figure and Kagi in a widget over a feed are transformed.** With
  the transform tier imported, a widget that loads its own bars from a `feed`
  now has the chart form point and figure columns or Kagi lines from them, where
  2.5.10 drew the raw bars through those renderers. A widget whose host feeds
  `widget.series` itself keeps them as renderers over the elements the host
  prepares.
- **Symbol lookups.** A lookup that fails says "Search unavailable" where the
  results used to close without a word. `SymbolSearch` callbacks receive an
  optional second argument, `{ signal }`, aborted when a newer query or a closed
  picker makes the answer stale. Enter in the top bar, the phone header and the
  watchlist's add box waits while a search runs, then takes its first result, or
  the typed text once the search finds nothing or fails; with a feed's search
  the first result is the exact symbol on the chart's exchange.
- **Window lengths are whole bars.** Every built-in reads a fractional window
  length as the nearest whole number (14.5 as 15) and a length below 1 as 1.
  Fifty-two studies read it raw or floored it, and most of the raw ones drew an
  empty pane: SMA, EMA, WMA, Bollinger Bands, Supertrend, RSI, MACD, Stochastic,
  ADX, CCI, MFI, ATR, Williams VIX Fix, Bollinger %B, Bollinger BandWidth,
  BBTrend, Choppiness Index, Historical Volatility, Average Daily Range, Chaikin
  Volatility, Standard Deviation, Chaikin Money Flow, Chaikin Oscillator, Ease
  of Movement and Elder Force Index read it raw; Aroon, Aroon Oscillator, Chande
  Momentum, Coppock Curve, DPO, Fisher Transform, Connors RSI, Standard Error,
  Momentum, ROC, PPO, TRIX, TSI, the SMI Ergodic pair, SMI, NVI, PVI, PVO, Mass
  Index, Ulcer Index, Vortex, Volatility Stop, Trend Strength Index, Williams
  Fractals, RSI Divergence and WaveTrend floored it. Whole lengths draw as
  before in every study.
- **An empty setting reads its default.** A colour, a choice or the VWAP anchor
  saved as an empty string now reads as its declared default in AlphaTrend,
  Awesome Oscillator, BBTrend, Chop Zone, MACD, PPO, PVO, VWAP and Williams VIX
  Fix, which passed the empty string on. Calling the `calc` of MA Cross,
  Williams Alligator, Median, TWAP or VWAP directly without those settings now
  uses the declared defaults (a long length of 26; 21, 13 and 8; the hl2, ohlc4
  and hlc3 sources); a chart, which merges the defaults, draws them as before.
- **The statistics helpers check their options as the calc helpers do.**
  `rollingMedian` and the rest of the statistics family, and the calc helpers'
  missing-value path, share one check: a period that is not a positive safe
  integer throws `RangeError`, and options that are not an object, or name a
  policy other than `propagate` or `skip` (`{ missing: null }` included), throw
  `TypeError`, in the same words in both families. The statistics helpers used
  to read a non-object options argument as the defaults.
- **Drawing actions keep one rule on every surface.** Lock, hide, the order
  moves, duplicate and delete read and act the same from the floating toolbar,
  the right-click menu, the properties dialog, the rail, the phone bar and the
  keys. Each press is one undo step; lock and hide read the whole selection, so
  a partly locked selection shows unlocked and locks whole; and a selection
  whose every drawing is locked is neither deleted nor cut from any of them. The
  phone bar's Delete is off and the Delete, Backspace and Mod+X keys do nothing
  for such a selection, as the menu and the toolbar already had it.
- **Drawing tools follow the theme and whole pixels.** The measure, price range,
  forecast, a line's stats readout and the position tools' zones take the
  theme's up and down colours, so on the light theme and a host theme they match
  the candles; a position's `profitColor` and `lossColor` still win, and the
  forecast's verdict chip uses the pattern tools' pass and fail colours. The
  advanced, pattern and analysis tools stroke whole device pixels as the lines
  do (a 1.5 px width is 2 px at a ratio of 1), dot at 1 px like every other
  dotted drawing, and set their labels in the same default face and weight as
  every other tool.
- **The chart data dialog asks for dates on the chart's clock.** Its From and To
  bounds are a date and a time in the chart's zone, named under the fields,
  where they were UTC seconds; a To written to the minute takes in the whole
  minute, and the visible bounds fill both to the second. The
  `ChartDataCsvOptions` it builds are unchanged, and the reference host's dialog
  does the same.
- **Chart events.** A listener that throws on the chart's bus is reported
  through the platform's `reportError` (in a browser, the console and the
  window's `error` event) instead of being dropped, and still stops neither the
  other listeners nor the engine. `objects:change` always carries `{}`: the pan
  and zoom switches of `setNavigationOptions` sent `undefined`.
- A study that the chart refuses for its inputs shows the reason in the widget's
  status overlay, naming the study once, with no Retry; any other failure keeps
  "Could not load" and its Retry.
- `chartTypeChoices()` lists the renderers, then, with the transform tier
  imported, the six transforms, point and figure and Kagi among them.
- The chart settings Price tab offers X and O colours for point and figure and
  thick and thin colours for Kagi, in place of a line colour and thickness
  neither renderer reads.
- The alert editor closes from the icon button every form dialog shows; the
  alerts list and the objects panel keep the word Close.
- `openalgo-charts/draw` loads in a runtime without Web Crypto; linking charts
  there throws "openalgo-charts: drawing links require Web Crypto" when a group
  first shares a drawing, where the import itself threw.
- The event markers and the popup copy the plain data nested in an event's
  `details`, not only its `fields`; a `Date` or other object a host attaches is
  still shared.
- `FakeBroker` names an unknown order "FakeBroker: unknown order", like its
  other errors.
- **Pointer subscriptions keep every subscriber.** `subscribeClick`,
  `subscribeDrag` and `subscribeCrosshairMove` take several subscribers, and
  each call returns a function that removes its own; a second call no longer
  replaces the first, so a host that subscribes again on one chart calls the
  returned function first. A subscriber that throws is reported through
  `reportError` and stops neither the others, the trading layer nor the pointer
  handling.
- `setNavigationOptions` and the crosshair magnet's shortcut fire
  `layout:change` (`LayoutSetter` gains `'setNavigationOptions'`, and the magnet
  reports `'applyOptions'`), so autosave and undo see them.
- `Chart.setDataContext` takes a change of data variant as a change of source,
  so `publishDataContext` emits `data:context` once for a variant-only change,
  where it emitted a passing context first.
- The crosshair price tag is written in the scale's text size
  (`canvas.scales.fontSize`, `theme.axisFontSize`); a chart that sets neither
  draws the same pixels.
- Appearance linking copies "Fit primary prices only" (`scales.priceOnly`)
  with the other price-scale settings, so `applyChartSettings` emits
  `style:change` for it and the widget's undo announces it to linked charts.
- `comparisonController(chart, options)` applies the `mode` and `baseline` it
  is given to a controller the chart already has, as `attachSessionShading`
  does; it ignored them.
- Timers a caller sizes are held to the longest delay the platform can wait
  (2^31 - 1 ms), and the replay and fake-feed intervals to at least 1 ms: the
  default replay and fake-feed intervals, history request timeouts, the alert
  expiry timer and the socket's auth, heartbeat and reconnect timers. Past the
  ceiling a timer fired at once, so a very slow replay ticked every millisecond.
- The time navigator reads a four-digit `#rgba` theme colour by its channels,
  where it drew a wrong plate; a malformed two, five or seven digit hex now falls
  back as every other primitive's colours do. Six-digit and `rgb()` themes paint
  as before.
- The trade tier's `OrderSide` and `OrderType` are the base's types,
  re-exported under the same names. `OpenAlgoTradeFeed.place()` documents its
  defaults, the NSE exchange and the feed's `defaultProduct`; `modify()` guesses
  neither.

### Deprecated

Each keeps working until 3.0.0 and has a row in COMPATIBILITY.md.

- The string overloads of `Chart.on`, `Chart.once` and `Chart.off`, taken for a
  name outside `ChartEventMap`: use a `ChartEventMap` name, or declare yours in
  the map.
- `Chart.emit`: announce an instrument with `setDataContext`, drive a link group
  with `LinkGroup.setSymbol`, `setInterval` and `setChartType`, and keep events
  of your own on an emitter of your own.
- The `priceAxisMoved` key of `ChartEventMap`, deprecated as an event since
  2.5.4, now carries the tag: listen for `priceAxisPlacementChanged`.
- The widget message keys "From (UTC seconds)", "To (UTC seconds)" and "Enter
  finite UTC seconds or leave the bound blank": the dialog shows "From", "To"
  and "Enter a date and a time on the chart clock".
- `VolumeProfileOptions`, which no function takes: pass
  `computeVolumeProfile(bars, tickSize, valueAreaPercent)` its arguments, or use
  `computeVolumeProfileSessions` with `VolumeProfileFamilyOptions`.
- `TimeScaleOp`, `InvalidateMask.addTimeScaleOp`, `InvalidateMask.timeScaleOps`
  and `InvalidateMask.merge`: since 2.5.8 the frame reads no queued operation, so
  change the time scale with `chart.timeScale`, `chart.fitContent` or
  `chart.setVisibleLogicalRange`, and raise levels on the mask `chart.invalidate`
  hands you.
- `updatePositionPnl` given the number first: use
  `updatePositionPnl(id, pnlText?, pnlPercent?)`.
- `SeriesStyle.hollow`, which never had an effect: use the `'hollow-candle'`
  series type.
- `TradeFeed` and `PlaceOrder`, which nothing in the library takes: use
  `OrderFeed` and `PlaceRequest` from `openalgo-charts/trade`, and hand the book
  to the chart with `chart.trading.syncState`.

### Fixed

- **A restore no longer stops at a study its inputs refuse.** `restoreState`,
  and so a widget starting from a saved layout, a layout or a workspace load,
  brings such a study back in its error status with its settings, beside the
  studies around it, where it threw part way and lost the rest (the widget failed
  to start).
- **A press outside the widget's overlays** no longer throws and leaves a
  popover open when one overlay's `onClose` closes an older one
  (`createOverlayStack`, `WidgetContext.openOverlay`).
- **A pinned rectangle or ellipse with one anchor**, from a hand-edited save,
  `add` or `update`, made its pane's drawing layer throw on every frame and hid
  the drawings painted after it, and pinning a one-anchor data rectangle threw
  from `update`. Such a drawing is kept and left unpainted, like any incomplete
  drawing.
- **A pane index that names no slot** (1.5, -1, NaN) given to `addSeries`,
  `addPriceLine`, `addPrimitive` or `addEventMarkers` throws a `RangeError` and
  changes nothing; it threw a `TypeError` from inside and could leave a stray
  empty pane or an unowned data series.
- **A mouse pick in the symbol results** did nothing unless the typed text
  matched the chart's symbol: pressing a result blurred the field, which put the
  chart's symbol back. The results keep the focus in the field while pressed.
- **Order and position price tags** sit on the chart's price axis wherever it
  is, the left axis and an outer column included, and are left out when the axis
  is hidden, as a price line's tag is (`WorkingOrderLine`, `PositionMarker`).
- **Notes, balloons, comments, signposts and price notes** are hovered, grabbed
  and selected anywhere on their plate however long their text, where the hit
  test stopped at 120 px; a price label is grabbed on the left half of its pill
  too, and a callout's bubble as wide as its text.
- **The chart grid's refused save.** A grid over a synchronous store such as
  `localStorage` says "The chart layout could not be saved" on the active chart
  when the store refuses the desk, once per run of refusals, instead of losing
  it silently.
- **Download PNG and Copy image.** The chart's Download PNG reports "This
  runtime cannot save files" when the picture could not be handed over (a canvas
  tainted by a cross-origin image) instead of "Saved a PNG of the chart", and
  attaches its link to the document for the click; Copy image reports a canvas
  that refuses to be read instead of throwing out of the menu.
- A listener that throws on `chart.trading.on` or `chart.shortcuts.on` no longer
  stops the other listeners, the chart-bus copy of a trading event or the
  chart's pointer handling.
- A market profile with `colorMode: 'period'` and an empty `periodColors`
  painted its blocks in whatever fill was left on the canvas; it uses the
  profile's `color`.
- `priceBuckets` looped on a negative step until memory ran out; a step that is
  not a positive finite number gives no buckets, so `computeVolumeProfile` and
  `computeTpo` return an empty profile for a negative tick size.
- The Choppiness Index rounds a fractional offset to whole bars, which left its
  plot empty.
- `percentileNearestRank`, `valueWhen` and `alma` give NaN for arguments out of
  range, where they wrote `undefined` or threw a `RangeError`.
- `DrawingController.setOptions` applies `clipboardFallbackToMemory`, so a host
  that turns the memory backstop off after construction gets a cut that leaves
  the drawing in place when the clipboard write fails.
- A chart of transform elements on minute bars (several a bar, a second apart)
  labels its time axis by the minute, not with seconds, whether the chart forms
  the elements or a host feeds them with the one-second bumps `runTransform`
  gives; plain charts label as before. `runTransform` over `KagiTransform` dates
  the vertex still forming at the newest bar, and so does `flush()` for a host
  that pushes bars itself, where it was time 0.
- The rail's right-click menus walk with the arrow keys, through the shared
  menu; in the chart grid's link and capture menus, ArrowUp from the menu itself
  goes to the last row.
- The event popup the widget mounts speaks through the widget's `translate` (a
  host's `eventDetails.labels` still win), and the watchlist translates its row
  names and its `n/a` and `...` price cells.
- The go-to panel refuses a date the calendar does not have (30 February),
  which rolled into the next month.
- The widget's key labels read the platform as the engine does, so a browser
  that blanks `navigator.platform` no longer shows Ctrl in the widget beside Cmd
  in the chart.
- The reference host fits the view when a chart switches into or out of a
  transform other than Heikin Ashi, where it drew an empty pane.
- **A host's pointer subscription no longer disconnects the trading layer.**
  `subscribeClick` and `subscribeDrag` held one callback each and
  `chart.trading` took both, so a host subscription made before or after it
  dropped order cancel and modify; the reference host's volume legend eye did
  nothing for the same reason.
- **A plot's Opacity fades `colorBy` and `colorParts` plots** (body, wick and
  border), multiplying each colour's own alpha, where it did nothing; Open
  Interest Change looks as before.
- `setPriceAxisOptions`, `setPriceAxisAutoFit` and `setPriceAxisLockRatio`
  ignore a scale id that names no scale (the last returns false), and
  `priceAxisState` returns null for one; they acted on the right axis.
- `maximizePane` refuses a fractional index, and `setPaneWeight` ignores a
  weight that is not a finite number.
- The chart settings offer Line style on area charts, and the HLC area Band
  swatch shows the colour the band is drawn in.
- A P&L text of `null` given to `updatePositionPnl` no longer shows as "null".
- **A linked chart that renames its symbol** (a suffix, a case change) no
  longer replaces the leader's instrument in its link group. It became
  `group.symbol()`, a chart joining later loaded it, and switching the symbol
  channel off and on sent it back to the leader.
- `ReplayShade.setOptions` repaints at once; moving or clearing the cut waited
  for something else to paint.
- A `ReplayController` whose chart is destroyed stops its timer and leaves
  replay without writing to the chart, where it called `setData` on the dead
  chart every tick until `stop()`. `ReplayChartHost` gains an optional
  `on('destroy', callback)`, which `Chart` has.
- A throwing `OpenAlgoWsFeed` callback (`onState`, `onControl`, `onLtp`,
  `onDepth`, `onOrderUpdate`) no longer stops the other callbacks or the feed's
  own state change, and its error goes to `reportError`. A throw during an auth
  refusal left the socket open.
- **Study alerts judge every element a step appends.** A source bar that
  completes several Renko bricks (the other transforms complete at most one
  element per source bar), or several bars a host writes before the chart
  recomputes, now has each new bar judged in order, as separate appends would
  be. An alert with no frequency reseeded silently on such a step and never
  fired, and `everyUpdate`, `oncePerBar` and `once` alerts judged only the
  newest bar; a host-fed element series met the same on 2.5.10. An alert judged
  at an earlier bar reads the bars and values through that bar, as `onBarClose`
  alerts already did, and on a custom host without source revisions a pass that
  appends several bars is marked `barState.isNew` and realtime, as one appended
  bar was.
- **Trader alerts judge every element an update appends.** A source bar that
  completes several Renko bricks (the other transforms complete at most one
  element per source bar), or a host that writes several bars before it
  announces them, now has each new element judged in order and dated at its own
  element, as separate appends would be. An `onBarClose` crossing on an earlier
  element never fired, and an `onTouch` crossing was dated at the newest
  element; price, study plot, drawing and named bar condition alerts all met
  this. An `onBarClose` alert on an in-chart Kagi chart now confirms a turning
  point once the line reverses past it, which it never did. An `everyTime` alert
  can deliver several `alert:triggered` events in one update, one per matching
  element; repeat, cooldown and expiry act as they would for separate appends.
- **Study alerts on in-chart Kagi and range bar charts.** A new source bar that
  only moves the forming vertex or range bar forward is now a revision of that
  element rather than a correction, so study alerts judge each new vertex or
  range bar once (an alert with no frequency never fired on an in-chart Kagi
  chart before), the calculation is told the bar is live, and studies keep
  their live tail. A real correction (an earlier element changed, an element
  dated backward, fewer elements) still reseeds silently.
- **A study on the underlying bars judges each of those bars once.** Its values
  are read onto the elements at the source bar each one completed on, so when one
  bar completes several Renko bricks its alerts were delivered once per brick;
  the bar is now judged once, at the first element it completed, `oncePerBar`
  counts underlying bars, and `onBarClose` waits for the underlying bar to
  close. A trader alert on such a study's plot that repeats every time still
  judges each element.
- `EventMarkers.setEvents` copies detail records built without a prototype, so a
  caller's later edits no longer reach an installed event.
- A custom `calcTail` that does not return every column of its study's result
  now falls back to a full `calc`, where the columns it left out went blank until
  the next full recompute.
- `drawingShortcuts()` lists a custom tool's shortcut whatever its id.
- `priceBuckets` returns no buckets for a range it cannot step through (a step
  too small for its prices, an infinite bound, an overflowing price) instead of
  growing an array until it threw, which took the volume profile, TPO or market
  profile with it; footprint text contrast reads an `rgb()` channel above 255 as
  255 again.
- Reference host: picking a replay start on all charts veils what a
  transformed chart's longer bar, still open at the picked close, had formed;
  Mark on chart draws in the pane the candles are in after the price pane moves;
  the chart data dialog refuses a bound dated before the year 100 and its date
  fields match its other controls.
- OpenScript 0.8.1 (`openalgo-script` on npm, `openscript` on PyPI) reads an
  alert's message at the bar the chart asks about. Use it with 2.6.0 when
  OpenScript studies compute on the underlying bars of a transform that is not
  one element per bar (Renko, range bars, line break, point and figure, Kagi):
  0.8.0 read those messages at the wrong bar.

### Performance

- **A tick on a transformed chart costs the same at any history length.** It
  forms only the newest element again, from a clone of the state, and writes
  only the tail that moved: one tick costs 0.4 to 1.1 microseconds for each
  transform at 200,000 one-minute bars (a node timing over the release build).
  Line break keeps only the lines a break is judged against.
- **A plain chart carries none of the transform runs.** The code that switches a
  series into a transform and compares its elements on each tick is installed
  by `registerSeriesTransform`, so a chart-only import that never registers a
  transform leaves it out.
- **Higher-timeframe folds read the zone once per local day.**
  `securitySeries` and `securityExpression` resolve the timezone only when an
  instant leaves the current local day, with identical output:
  `securitySeries(bars, '1d')` on 7,500 one-minute bars takes 0.43 ms where
  2.5.10 took 23.8 ms (median of 30 runs on each build). A study with a
  timeframe set takes its live tail inside a bucket: an EMA, Supertrend, RSI
  and Bollinger set on 15m costs 3.96 ms in full and 0.014 ms a tick on 7,500
  one-minute bars, and 15.7 ms and 0.010 ms on 30,000 (`npm run bench`,
  section C).
- **Measured against 2.5.10** on the release bench (five runs of each build in
  one session, `benchmarks/releases.json`, the website's Benchmarks page):
  frames are on par. With Canvas 2D at 200,000 bars a pan, a full zoom-out and
  a ten-study tick measure 2.6, 63.6 and 178.3 ms against 2.7, 66.6 and
  175.7 ms (each the lowest p95 of its five runs); every cell of both renderers
  is within 6 percent of 2.5.10 but the 10,000-bar Canvas 2D zoom-out, 7.8 to
  8.6 ms.

### Website

- Transforms: in-chart transforms with a live Renko example, studies on a
  transformed chart and alerts on one; Chart types points to them. Alerts: how
  an update that appends several bars is judged.
- Indicators: the seven new built-ins, with ZigZag and 52 Week High/Low sections
  and a live example, the first bar each one prints, and "A built-in on a higher
  timeframe" with its opt-in list and its exclusions; the Examples page adds a
  live higher-timeframe example.
- Data feeds: Symbol search. Events: typed payloads with the full event table,
  the listener error policy and the naming rule, and rich details and actions.
- CDN: the no-modules build of every tier, its globals and load order;
  Frameworks: `require()` and its runtime floor; Widget: the classic-script
  widget, `intervals` for a study's timeframe select, the drawing rules, Enter
  while a search runs, how widget text is keyed, and `now`.
- Chart data export, drawing tools, the drawing clipboard, series and styling
  (the two `withAlpha` functions), volume profile, trading and compatibility
  follow the changes above.
- Events, the trading API, types, data variants, chart linking, market replay,
  symbol comparison, the glossary and live data follow the base and edge changes
  above, and the data feeds page's trade section is written around `OrderFeed`.
- Link labels that ended in an arrow glyph lose it, and the depth ladder's
  empty cell is empty rather than a dash.
- Upgrade notes for 2.6.0.

### Tests

- 11591 unit tests across 512 files and 689 reference host tests across 67
  files pass. The browser suite runs 2091 cases in three browser engines with
  two workers: 2075 pass, 13 are skipped, each for an engine limit its spec
  names (device pixel scaling Playwright can change only in Chromium, a
  resampled page in headless Chromium and WebKit, and WebKit's missing
  device-pixel content box), and 3 page loads timed out under that load and
  pass when run alone (5 of 5 and 3 of 3 each). The two reference host tests
  that reload saved alerts now write the layout before reloading instead of
  waiting out the autosave debounce. Each fix carries a test that fails with the
  fix reverted. Against 2.5.10, render parity finds no differing pixel.
- **A compatibility gate.** `npm run check:compat`, part of `npm run verify`,
  fails a removed export, a removed member or a narrowed type in any tier against
  2.5.10 and 2.5.1, unless COMPATIBILITY.md lists it for the next major, and
  `tests/saved-documents.test.ts` loads the chart states, drawings, alert lists,
  widget layouts and workspaces those releases saved and saves them again,
  naming every field that changes.
- New guards: `npm run check:exports` holds the script-tag keys to each tier's
  declarations and `require()` to `import`; `tests/chart-event-map.test.ts`
  holds every emit and subscription in `src` to `ChartEventMap`;
  `tests/typecheck-config.test.ts` keeps both strict flags on `src`;
  `tests/function-caps.test.ts` caps every function at 150 lines, with the longer
  ones listed at today's lengths in `scripts/function-caps.json`, to be lowered
  and never raised; and tests keep the base-shipped calculators free of tier
  imports, the widget's text layout held to the draw tier's, the widget's
  handler declarations in their 2.5.10 form, and stray merge notes out of the
  widget's source.
- Browser specs, in three engines: a Renko chart ticking live and every
  transformed type drawn, the seven new studies drawn and held to a full
  calculation through live ticks, a higher-timeframe EMA and its select in the
  widget and the reference host, feed symbol search and rich event details, a
  page of classic scripts, the drawing actions on the rail and the menu, a
  transform picked from the grid view's chart type menu and kept over a reload,
  and a price alert that fires once, at the brick a replayed Renko step crossed
  inside it.
- **Gates that were prose.** CI fails a browser test that passes only on its
  retry (`failOnFlakyTests`), where it reported the test flaky and went green.
  `npm run verify` checks import cycles (`npm run check:cycles`: none at run
  time, and the type-level loops may not grow, their sizes kept in
  `scripts/import-cycles.json`) and unused exports
  (`npm run check:unused-exports`, whose allowlist only shrinks), and
  `npm run shake` holds the tier files each built tier imports to the list the
  bundling reference states.
- **The writing rules hold over every file.** No em or en dash, arrow, tick or
  cross character, pictograph or dash entity in the source, comments included,
  the tests, scripts, examples, the site and the docs; the sweep that brought
  them there changed no emitted JavaScript.
- `npm run test:script-engine` gates its cases on the version the built script
  engine reports, so a stale build skips with a message, and a compiled alert
  on a Renko step fires on each brick.
- The OpenAlgo consumer harness (`scripts/check-openalgo-*.mjs`) follows
  OpenAlgo's `/trading` as it is today: it takes `--port`, starts the consumer
  checks from an intraday grid, drives alerts through the host's own form, list
  and menu, and prints a defect in the host's own chrome as `HOST FINDING`
  without failing.

Saved chart states, drawings, alert lists, widget layouts and workspace documents
from 2.5.10 and 2.5.1 load unchanged, and the only field this release adds when
it saves them again is the `timeframe` setting of each study that offers one,
empty unless chosen. Document versions are unchanged. No export was removed, no
type was narrowed and no runtime dependency was added; the package gains the
eight tier script files, which ship without source maps.

Sizes, measured on this release and against 2.5.10 (Brotli, decimal kB): base
engine 134.69 to 137.53, base plus trade 151.38 to 154.41, indicators 40.43 to
43.02, draw 57.98 to 58.36, transform 4.55 to 6.07, profile 14.97 to 14.94,
widget 121.36 to 123.57, the widget's first-use parts 18.19 to 18.24, workspace
11.53 to 11.73, widget terminal 354.46 to 362.48 and every tier together 409.13
to 419.05; the trade tier on its own 16.69 to 16.88, and WebGL2 6.93 to 6.97.
The nine classic-script files, a new row, measure 430.90 together, and the base
and widget classic scripts have rows of their own at 137.65 and 135.21. The
chart-only import grows from 85.73 to 87.19 KiB (89,280 bytes, up 1,495). The
package grows from 47 files, 2,098,074 bytes packed and 6,730,951 unpacked to 55
files, 2,501,201 packed and 8,079,719 unpacked. Each budget is the smallest
two-decimal value that passes.

Where the growth goes, each figure measured from builds of the commits before
and after a feature, so they overlap slightly once merged, and Brotli layout
moves a single step by up to about 150 bytes. In the base engine the in-chart
transforms and the study bar source take 1,567 bytes: the series routing every
chart's data path passes through, which does nothing for a series without a
transform. The switch into a transform and the per-tick element diff are
installed by `registerSeriesTransform`, so a chart-only import that never
registers one leaves them out (347 bytes there); moving them shifted the base
file's layout by about 200. The OpenAlgo feed's search and the copy of rich
event details take 324 bytes, of which the chart-only import pays only the copy
(48); the pane index check takes 217, and the base and edge hygiene waves 204,
raw code going down while Brotli rose with new function boundaries, less 110
for the shared dash table. The alert fixes take 482: 94 for study alerts that
judge every element a step appends, 130 for trader alerts that do the same, 100
for a re-dated forming element that stays live and 158 for an underlying bar
judged once; the review fixes add 42. The indicator tier carries
the seven new studies (2,424 bytes, about 346 a study) and the timeframe
wrapper and fold (1,482), less the hygiene wave's one settings reader and
shared kernels (1,266). The transform tier's growth is the live runs and their
registration (1,511). The widget tier grew by the chart grid's split over a
state object (697), the transformed chart types and the Compute on row (597),
the rich popup, its actions and the feed search (553), and the strict and
widget hygiene passes (135 each). The chart-only import grows by 1,495 bytes,
most of it the transform routing and the study bar source a host can call on
any chart.

## 2.5.10

2026-09-30

Persistence, saved layouts and the chart grid. The widget keeps its saved state
in IndexedDB by default and says when it has landed (`widget.ready`), saves and
reopens named layouts and indicator templates over a workspace store, and lets
a user move any shortcut from the ? panel. A bottom bar under the chart carries
preset ranges sized in trading sessions, Go to, the market status from the
instrument's calendar, a clock with a timezone menu and the scale toggles.
Calendars know pre-open, post-close and extended hours, and a chart can shade
them. The chart grid lays out one to sixteen charts with a grid bar, maximize
and swap, named link groups that can share the chart type and drawings, and
one picture of the whole grid. The widget draws every glyph from one icon
registry, loads the UI a plain widget never opens on first use, and a label
pass makes every control say what it is, what state it is in and what it does.
What a host can see change: widget persistence is asynchronous by default, Go
to moved to the bottom bar, the phone layout follows the container's size, the
widget ships its first-use parts as hashed files beside the tier, and some
strings a host may match on are reworded. See the upgrade notes.

### Added

- **Widget persistence in IndexedDB.** With `persist` and no `storage`, the
  widget keeps its layout, drawings, preferences and chords in IndexedDB. It is
  built on its defaults, kept out of sight and asks the feed for nothing until
  the store has answered; then the saved state is applied, the first load goes
  out for the saved instrument only, and `widget.ready` settles.
  `createIndexedDbWidgetStorage` and `AsyncStorageLike` (entries by prefix,
  writes that return promises, an optional journal and `subscribe`) let a host
  pass an asynchronous store of its own, and `WidgetStorage` keeps synchronous
  reads over a copy in memory and writes behind, in order. The first visit
  copies the `oac-widget:<namespace>:` keys an earlier release left in
  localStorage, once. Writes still pending when the page goes away are
  journaled and replayed at the next load, and each tab follows the writes
  other tabs land, so a tab opened earlier does not write over drawings made in
  another. A page without IndexedDB stays on localStorage, and
  `storage: localStorage` keeps the 2.5.9 behaviour call for call.
- **Saved layouts and indicator templates.** `WidgetOptions.workspaces` takes a
  `WorkspaceStore`, as a type only, so the widget never loads the workspace
  bundle itself. With one, the widget holds a layouts controller over itself
  (`widget.layouts`, `widget.openLayouts()`) and reopens the layout that was
  active when the page last closed. The top bar's Layouts button names the held
  layout and marks unsaved changes, a failed autosave or a conflict. Its menu
  (`openLayoutsMenu`) saves, saves as, renames and deletes, lists recent
  layouts, turns autosave on and off, asks before unsaved changes are dropped,
  and settles another window's save with Reload list, Save as a copy or
  Overwrite. The indicator picker saves the chart's studies as a template and
  applies one by Replace or Append as one undo step (`applyIndicatorTemplate`,
  `saveIndicatorTemplate`). `createLayoutsController(store, target)` and
  `widgetLayoutTarget(widget)` serve a host's own control; autosave and opening
  wait while a target is suspended, as a chart is during a replay.
- **Shortcuts editor.** The ? panel changes any chord the widget owns: Change
  records the next chord, a chord another binding holds is named with Cancel or
  Replace, and Reset and Reset all bring the defaults back. Commands have stable
  names (`undo`, `tool:trend-line`, `chart:fitContent`), chords the browser
  keeps are refused, and Escape, Enter, Backspace, the arrows and ? stay fixed.
  The keymap gains `rebind`, `reset`, `resetAll`, `overrides`,
  `applyOverrides`, `conflictsFor`, `chord` and `onChange`. With `persist` the
  chords are saved under `KEYMAP_KEY`, a chart grid shares them across its
  charts, and `shortcutsEditor: false` keeps the panel a list.
  `ShortcutManager.onChange` lets the time navigator's hints follow a rebind.
- **Bottom bar.** A strip between the chart and the status line: preset ranges
  (1D, 5D, 1M, 3M, 6M, YTD, 1Y, 5Y, All) and Go to on the left; the market
  status, a clock in the chart's zone that opens a searchable timezone menu, and
  the auto, logarithmic and percent toggles on the right. A range is sized in
  trading sessions, not days of 24 hours: with a session calendar one NSE day at
  one minute is the 375 bars from the 09:15 open, and weekends and closed dates
  are skipped. New options `bottombar` (on by default), `ranges`,
  `sessionCalendar` and `sessionShading` (on by default); `widget.setRange` and
  `widget.range`; and `mountBottombar`, `BOTTOMBAR_HEIGHT`, `BOTTOMBAR_CSS`,
  `DEFAULT_RANGES`, `rangeWindow` and `rangeInterval` for a host's own bar. A
  zone picked anywhere is saved with the layout.
- **Market phases and session shading.** `InstrumentCalendar` takes optional
  `preMarketMinutes`, `postMarketMinutes` and `extendedHours`. `Instrument` and
  `SessionCalendar` gain `phaseAt`, `phaseSpans` and `marketStatusAt`, which say
  whether an instant is pre-open, regular, post-close, extended hours, closed or
  a holiday in the calendar's IANA zone, and free functions `marketStatusAt`
  and `calendarMarketPhase` read any source that has phase spans.
  `SessionShade` and `attachSessionShading(chart, options)` wash pre-open,
  post-close and extended-hours bars in the price pane. The engine shades
  nothing until a host attaches it, so its default render is unchanged.
- **The chart grid to sixteen charts.** `CHART_GRID_LAYOUTS` holds 26 layouts,
  every uniform grid to four by four and ten uneven ones with a large chart,
  named through `CHART_GRID_LAYOUT_NAMES`. The grid bar (`toolbar: true`, with
  `presets` listing the picker's layouts) carries the layout picker, maximize,
  the link menu, the capture menu and, with `workspaces`, a Layouts control over
  saved desks. A chart maximizes and restores as a view that is not saved, and
  two charts swap when one's bar background is dragged onto the other;
  Alt+Enter, Escape, and Alt+Shift or Ctrl (Cmd)+Shift with an arrow do the same
  from the keyboard. Up to sixteen named link groups each carry their own
  channels, saved as `sync.groups` and `pane.linkGroup`. `takeScreenshot` and
  `downloadScreenshot` compose every chart at its place, and
  `WidgetOptions.captureRows` adds rows to a chart's capture menu. The grid
  keeps its desk in IndexedDB by default and settles `grid.ready` once it is
  applied, and `bottombar: true` mounts one bottom bar for the active chart.
- **Link channels for the chart type and drawings.** A link group can follow
  the chart style (`chartType`, through `setChartType`, a `'chartType'` event
  and `onChartType`) and decide which charts share drawings (`drawings`,
  through each member's `LinkDrawingsAdapter` over the draw tier's
  `DrawingLinkGroup`, so no drawing code enters the base bundle). Both are off
  by default. The workspace schema saves them: `WorkspacePayload.sync` is a
  `WorkspaceSync` with optional `appearance`, `chartType`, `drawings`,
  `whenMissing` and up to sixteen named `groups` (`WorkspaceLinkGroup`), and
  `WorkspacePane.linkGroup` names a chart's group. A workspace saved by 2.5.9
  reads and writes back byte for byte.
- **Workspace revisions.** Every catalog change takes an optional
  `expectedRevision` (`WorkspaceOperationOptions`) and rejects with
  `WorkspaceConflictError`, before anything is written, when another tab moved
  the catalog. `WorkspaceRepository.subscribe` hears every commit in order,
  `WorkspaceStore` is the contract a layouts control holds,
  `createMemoryWorkspaceStorage` keeps the atomic compare-and-write in memory,
  and the optional `captureIndicatorTemplate` and `planIndicatorTemplateState`
  members let a store offer templates.
- **Chrome icons.** The registry grows from 29 glyphs to 110, with a
  `chart-<id>` glyph for each of the 13 chart types and six transforms
  (`chartTypeIcon(type)`) and `layoutIconPath(rows, columns, slots)` for a
  layout tile. The widget draws every picture it shows from it: `MenuRow.icon`,
  the chart type menu and button, and a theme button that shows a sun or a moon.
- **Hover labels on the canvas's own controls.** A study legend's eye, gear and
  cross, and the close box on an order or position line (the chart's own
  trading layer and the trade tier's lines), raise the widget's tip at the
  pointer: "Hide RSI", "Settings for RSI", "Remove RSI", "Cancel order",
  "Close position".
- `TipSpec.label`, an accessible name for when it must say more than the title;
  `ChartObjectsOptions.drawingName(tool)`, which names drawing rows by the draw
  registry's display name (the widget passes it); and `ShortcutEvent.code`, the
  physical key `matchDrawingShortcut` reads under Alt when macOS Option types a
  symbol. New widget message keys for all of the above.

### Changed

- **Widget persistence is asynchronous by default** (see Added). A host that
  drives a persisting widget right after `createWidget` awaits `widget.ready`
  first; a host that passes a synchronous store sees no change.
- **The widget loads UI a plain widget never opens on first use**: the
  shortcuts editor, the Layouts menu, the indicator templates list, the chart
  data dialog, the grid bar and its menus, and the IndexedDB store. Each of the
  seven is a file beside the tier named by a content hash
  (`openalgo-charts.widget.<part>-<hash>.mjs`) and fetched once with `import()`;
  a press while it loads opens it once, and a part that cannot load says so. A
  host serving `dist/` itself serves a tier file and its parts from one release,
  and a `script-src` allows their directory. `openLayoutsMenu` resolves with the
  menu once it is open.
- **Go to moved to the bottom bar.** With `bottombar: false` it stays in the top
  bar and the status line keeps the market status.
- **Auto mobile mode follows the container's size**, not any coarse pointer: a
  container up to 640 CSS px wide is compact, and a coarse pointer widens that
  to 960 px only while the container is under 600 px tall. Tablets and touch
  laptops keep the toolbar and the drawing rail. A hidden or zero-size
  container, or a focused field, holds the current layout.
- **The widget says active, not armed**, in the rail, the shortcuts panel and
  the alert list. The alert state value `'armed'` is data and stays.
- `matchDrawingShortcut` under Alt: a plain ASCII letter in `e.key` still
  decides the tool, and `e.code` is read only when `e.key` is not a letter, so
  Option chords fire on macOS and a non-QWERTY layout keeps its 2.5.9
  behaviour.
- **Wording a host may match on.** Trading capability reasons are in words
  ("Placing orders is not supported", "Stop-loss orders are not supported",
  "Live trading is not supported") where they named ids. The `DEFAULT_KEYMAP`
  labels of `resetScale` and `fitContent` are "Reset view" and "Fit all bars".
  `williams-vix-fix` is named "Williams VIX Fix" and `roc` "Rate of Change",
  with their ids unchanged. `chartSettingsSchema` says "Linear" for the linear
  scale mode and "Auto-fit to the data" for autoscale. The unknown indicator and
  missing transform tier errors use a comma where they had an em dash, the
  footprint and Buy/Sell quantity placeholders draw "-", and the chart's
  shortcut hints say Cmd on macOS.
- **Widget labels.** A toggle keeps one name ("Lock", "Hide", "Lock drawing",
  "Pin to rail") and its pressed or checked state says on or off. Action menu
  rows are `menuitem`, only choices stay `menuitemradio`, and a row's chord is
  its `aria-keyshortcuts` rather than part of its name. Two listed objects of
  one name are numbered the same way in Objects, the alert editor and its list,
  study settings and the CSV dialog ("Relative Strength Index (2)"), counted
  among the listed objects of that name, where the alert editor numbered every
  study ("2: RSI") and every drawing ("Trend Line (3)"). Alert rows name a
  drawing level, a study plot and a price as the editor does, on the scale
  each belongs to. `renderForm` groups the rows under a heading in a
  `div.oac-form__group` with `role="group"` and gives a field's help text as its
  `aria-description`. Level editor rows are named by their level ("Level
  0.618 enabled", "Remove level 0.618"), indicator input buttons by their
  input ("Search {label}", "Pick {label} on the chart"), a pinned rail tool
  as "{name} (pinned)" and an interval pill by the text it shows; the Layouts
  button keeps its status in its name; the Objects add-to-selection button
  and the grid's Maximize are plain buttons, with no pressed state; and the
  chart data dialog lists a hidden study as "{name}, hidden" and names no
  study by its instance id. A failure reads "unknown error" rather than
  "[object Object]", a count of one is singular, and the phone bar says
  Indicators and names its theme action "Switch to the light theme" or
  "Switch to the dark theme".
- The maximize, restore, check and calendar glyphs are redrawn.

### Deprecated

- Widget message keys the widget no longer shows stay in `WidgetBuiltinMessage`
  until 3.0.0, so a host catalog still type-checks: the armed wording, "Dark"
  and "Light", the expiry keys that end in " UTC", and the keys the label pass
  renamed. COMPATIBILITY.md lists each with the key to translate instead.

### Fixed

- **The status line follows the latest bar.** Under each widget and in every
  grid cell it showed the previous instrument's prices after `setSymbol`,
  `setInterval`, a linked symbol change or a live tick, until the chart was
  hovered. It now follows the latest bar while the pointer is away, and reads it
  without copying the series.
- **Marker labels on neighbouring bars no longer overlap.** A marker with text is
  laid out in lanes per side, pushed just past an earlier label it would cover,
  and moves at most five of its own heights.
- A touch at the centre of a rail group button, which the browser moves onto
  its chevron, picks the tool instead of opening the list.
- A host command whose undo or redo restores the chart keeps its undo step.
- The context menu, the drawing properties dialog and the drawing toolbar name
  the chord in force, so a moved or unbound command shows what really fires it.
- Icon lookups read only a registry's own entries, so an inherited name such as
  `toString` is never drawn as path data.
- The reference host's rail follows the light theme, and its replay bar names
  the chart once.

### Performance

- **Marker lanes** read at most two windows of 256 marks before the first one
  drawn and measure text only for the marks a paint lays out: ten thousand
  labels over twenty thousand bars paint in 2.0 to 4.2 ms.
- **The widget tier file carries what a plain widget uses.** Moving the seven
  first-use parts out took 9.94 kB (Brotli) off it; the parts measure 18.19 kB
  on their own and are fetched only when used.
- **Measured against 2.5.9** on the release bench (five runs of each build in one
  session, `benchmarks/releases.json`, the website's Benchmarks page): frames are
  on par. On Canvas 2D a full zoom-out takes about 7 percent longer at 50,000
  bars and 9 percent at 200,000 (21.3 to 22.7 ms and 57.6 to 62.7 ms, each the
  lowest p95 of its five runs); pans are the same, a ten-study tick at 200,000
  bars takes about 3 percent longer (152.5 to 157.6 ms), and WebGL2 frames are
  within 4 percent.

### Website

- One framework guide gives plain JavaScript, React, Next.js, Vue 3, Angular and
  Svelte the same depth; the old Vue page moves the reader to its section.
- The home page opens in light, holds its charts to a column and gains
  sections; the API reference fits phone widths, and CI checks it; every example
  draws a seeded random walk.
- A code of conduct, and the security contact.
- Docs for everything above, and upgrade notes for 2.5.10.

### Tests

- 11118 unit tests across 469 files and 683 reference host tests across 64
  files pass, and the browser suite passes 1967 cases in three browser
  engines. Of the 13 skipped, 12 are checks an engine cannot run and one is a
  reference host case whose fixture server did not answer under the full run
  (it passes when run alone). Against 2.5.9, render parity finds no differing
  pixel. New guards fail on a control with no name or a leaked value in
  the widget chrome and the reference host (`tests/e2e/labels.spec.ts`), a
  dash, arrow or emoji in anything a reader sees, a message key nothing shows,
  a chrome icon id the registry lacks, a doc comment stranded off its
  declaration, and a first-use part that opens twice or not at all.

Saved layouts, drawings and workspace documents from 2.5.9 load unchanged, and
no runtime dependencies or package tiers were added.

Sizes, measured on this release and against 2.5.9 (Brotli, decimal kB): base
engine 131.68 to 134.69, base plus trade 148.36 to 151.38, indicators 40.38 to
40.43, draw 55.61 to 57.98, profile 14.96 to 14.97, widget 99.64 to 121.36,
workspace 11.33 to 11.53, widget terminal 327.32 to 354.46 and every tier
together 381.78 to 409.13; the transform, WebGL2 and trade tiers are unchanged.
The widget's seven first-use parts, a new row, measure 18.19 together and are
fetched only when used. The chart-only import grows from 84.82 to 85.73 KiB
(932 bytes).

Where the growth goes. In the base engine (3,013 bytes) the marker lanes cost
845 bytes, and 919 of the chart-only import's 932: a fix every chart with text
markers needs. The session phases, the market status and session shading, and
the link channels for the chart type and drawings make up most of the rest and
cost nothing in a chart-only import, where a chart that never asks for them
shakes them out. The draw tier's growth is almost all the chrome icon registry,
from 29 glyphs to 110 and a glyph per chart type, and the workspace tier's is
the named link groups in its schema. The widget tier grew by the features it
adds, each measured on its own branch so the figures overlap slightly once
merged: the chart grid's layouts, bar, groups and capture 8.48 kB, the Layouts menu and
indicator templates 6.78 kB, the bottom bar 5.84 kB, the shortcuts editor
4.11 kB, the IndexedDB store 2.98 kB and the layouts controller 1.45 kB. The
lean pass then moved 9.94 kB of it into the first-use parts: the Layouts menu
2.99 kB, the grid bar, its menus and saved desks 2.77 kB, the shortcuts editor
1.69 kB, the templates list 1.14 kB, the IndexedDB store 0.84 kB and the chart
data dialog 0.69 kB, less 0.18 kB for opening each part once and only while it
is still wanted. The label fixes add 982 bytes to the widget. Each budget is the
smallest two-decimal value that passes, the transform, profile and WebGL2 rows
included, which until now kept round budgets.

## 2.5.9

2026-09-28

Drawing interaction and replay. Drawings belong to the instrument they were
drawn on. The magnet works on every pane and in every drag, and box select,
drag to copy, an eraser, a temporary measure and visibility per interval join
the drawing controller. The widget gains a floating toolbar over the selected
drawings, style templates and a coordinates tab. Replay's forming bar stays
inside the bar it closes on, so its open no longer jumps when the bar closes,
and a bar with no finer data can form over simulated steps. Line, step and
area series draw the segment that crosses each edge of the view, the price axis
keeps its labels whole and its value tags readable, and a drawing hit test asks
only the drawings near the pointer. What a host can see change: the widget
keeps drawings per instrument by default, a drawings document is version 3 when
a drawing carries an interval range, the modifier gestures are on by default,
the bar countdown appears only on the price pane, and `ReplayState` has a new
`simulated` field. See the upgrade notes.

### Added

- **Drawings per instrument** (#38, for OpenAlgo issue 2131). A trend line drawn
  on one symbol showed on every symbol loaded into the same chart, and deleting it
  on any symbol deleted it everywhere. `InstrumentDrawings` (draw tier) keeps one
  drawing document per instrument (`EXCHANGE:SYMBOL`, or a key the host supplies)
  in a `DrawingDocumentStore` (`webStorageDrawingStore`, `memoryDrawingStore`),
  and `migrateUnscopedDrawings` attaches a document saved before to the symbol it
  was saved on. The widget and the chart grid use it by default:
  `drawingScope: 'instrument'` (`'chart'` keeps one set whatever symbol is
  loaded), `drawingStore`, and `widget.instrumentDrawings`. With `persist`, each
  instrument's drawings sit beside the layout under
  `oac-widget:<namespace>:drawings:<exchange>:<symbol>` (`DRAWINGS_KEY_PREFIX`).
  A symbol change is not an undo step, and an alert tied to a drawing waits,
  without evaluating, while its instrument is off the chart.
- **Modifier gestures on drawings.** None is a key chord, so none collides with a
  tool shortcut or the editing keys. Each turns off through
  `DrawingControllerOptions.gestures` (`snapModifier`, `measure`, `boxSelect`,
  `dragCopy`), at construction or with `setOptions`.
  - **The magnet everywhere.** Handle drags, body drags and study panes snap, not
    only placement on the price pane; in a study pane an anchor snaps to the
    plotted study values. Holding Ctrl (Cmd on macOS) gives the strong snap
    whatever `magnet` is set to.
  - **Temporary measure.** Shift+click on empty space with no tool in use lays down
    a ruler that is never saved, undone or linked, and goes on the next click or
    Escape (`measuring()`, `draw:measure`).
  - **Box select.** Ctrl+drag on empty space selects every drawing the box
    touches, respecting unselectable policies; add Shift to add to the selection.
  - **Drag to copy.** Alt+drag on a drawing's body drags a copy and leaves the
    drawing, as one undo step.
  - **Eraser.** `setEraser(true)`: a click on a drawing deletes it and a drag
    deletes every drawing it crosses, as one undo step, respecting read-only
    policies (`erasing()`, `draw:eraser`).
- **Visibility per interval.** `Drawing.intervals` (`DrawingIntervalRange`,
  `{ from?, to? }`, interval codes, both ends included) limits a drawing to a
  range of chart intervals, compared by bar length. Outside its range a drawing is
  kept, saved and undone, but not painted, hit-tested, box-selected, erased or
  exported, and the object inventory marks its row. New:
  `DrawingController.interval()`, `shownOnInterval(id)`, `hiddenOnInterval()`,
  `drawingShownOnInterval` and `INTERVAL_FIELDS`. The reference host sets the
  range under Visibility in the properties bar's more settings.
- **Drawing toolbar (widget).** On a desktop layout a small toolbar sits just above
  the selected drawings: colour, line width, line style, lock, delete and a more
  menu (properties, duplicate, hide, stacking order, templates). It stays inside
  the chart, follows a pan, a zoom or a rescaled axis, reads "mixed" where the
  selected drawings disagree, greys read-only drawings with the reason, and makes
  each change one undo step. It is keyboard reachable (Tab from the chart, then
  the arrow keys, which never nudge the drawing) and localized. On whenever the
  drawing rail is; `drawingToolbar: false` turns it off. New:
  `mountDrawingToolbar`, `DRAWING_TOOLBAR_CSS`, `TOOLBAR_LINE_WIDTHS`.
- **Style templates.** `WidgetOptions.drawingTemplates` takes a
  `DrawingTemplateStore`; the toolbar's more menu and the properties dialog save a
  drawing's look as its tool's default or under a name, and apply one as one undo
  step. A default reaches only drawings placed with that tool afterwards. The
  workspace tier adds `DrawingTemplateRepository`, a revision-checked catalog with
  memory and IndexedDB storage (`createMemoryDrawingTemplateStorage`,
  `createIndexedDbDrawingTemplateStorage`) and `DrawingTemplateConflictError`.
- **Coordinates tab.** The drawing properties dialog shows each anchor as a date,
  a time on the chart's clock and a price, validates an edit, and writes a row as
  one undo step on Enter or when the focus leaves it
  (`mountDrawingProperties(ctx, anchor, { tab: 'coordinates' })`,
  `mountDrawingCoordinates`).
- **Objects panel.** It says each pane lists back to front, shows a grip on rows
  that can move, and moves a row with Alt+ArrowUp and Alt+ArrowDown.
- **Replay: simulated forming.** Feeds keep far less fine history than coarse
  (about a week of 1-minute bars against years of 5-minute ones), so most of a
  replayed session had nothing to form from and landed whole. With
  `ReplayOptions.simulate` (`ReplaySimulation`, `{ steps }`, 2 to 240), a bar no
  finer bar forms takes that many steps along a path from its open to the extreme
  nearer it, the other extreme and its close. It keeps its real open, only widens
  toward its real high and low, holds volume in proportion and closes on the bar
  itself; real finer bars win wherever they exist. `ReplayState.simulated` is true
  on those steps: the order of the extremes is an assumption, and a stop tested
  inside a simulated bar was not tested against traded prices. Off by default.
  The reference host turns it on at the finer rung's pace (five steps for five
  minutes over one) and marks the steps Simulated on the replay bar.
- **Lines across the edges of the view** (#37). `RendererEntry.connectsBars` marks
  a renderer that draws a segment from each bar to the next; its items then also
  carry the nearest bar beyond each edge of the view, with `DrawItem.edgeX`, the x
  of the plot edge it lies past. The built-in line, line-markers, step, area,
  baseline and HLC area renderers and Kagi set it. `SvgContext.lineDashOffset`
  exports as `stroke-dashoffset`.
- **Widget contrast helpers**: `contrastRatio`, `readableOn`, `TEXT_CONTRAST`, and
  the `--oac-up` and `--oac-down` tokens.
- **Vue 3** (#40): a tested integration in `examples/vue/` and a guide, including
  why a chart must stay out of Vue's reactivity. `vue` is a development
  dependency only.
- **Release benchmarks** (#34). `npm run bench:release` rebuilds the previous
  release from its tag, runs the render bench five times on each build in one
  session and writes the release's entry into `benchmarks/releases.json` and the
  website's Benchmarks page; every release from 2.5.8 carries one.

### Changed

- **Drawings documents may be version 3.** `DRAWING_STATE_VERSION` and
  `DRAWING_CLIPBOARD_VERSION` are 3, and a document or clipboard payload is
  written as the lowest version that holds it: 3 only when a drawing carries an
  interval range, otherwise 2, byte for byte what 2.5.8 wrote. Version 2 documents
  load unchanged. An older build refuses a version 3 clipboard payload and drops
  the ranges from a version 3 layout.
- **The bar countdown appears only in the last-price tag of the pane that shows
  the chart's price source.** A study pane's value tag stays one row instead of
  growing into its level tags.
- **Value tags are painted over price-line and level tags** where they meet, so an
  RSI value near its 50 level, or the last price at a resting order, stays
  readable.
- **A price-axis tick label within half a tag height of a pane's top or bottom
  edge is left out** instead of being printed cut in half (RSI 0 and 100). The
  gridline stays.
- **Eighteen drawing tool glyphs are redrawn** to what their tools draw: the four
  pitchforks (one trident, told apart by where the median starts, with a pivot
  dot), Fib circles, Fib spiral, Fib wedge, the speed resistance arcs and fan,
  supersonic and golden supersonic, the Dedekind tessellation and the six
  harmonic patterns, each drawn to its own ratios.
- **Widget colours.** Faint chrome text meets WCAG AA (4.5:1) in both themes and
  in host themes, and the watchlist's up and down colours follow the theme instead
  of the dark palette.
- A host that drives a `DrawingLayer` itself and edits a drawing in place passes
  the list again with `setDrawings` (the layer now keeps a hit box per drawing);
  `DrawingController` already does.

### Fixed

- **Replay: the open of a forming bar no longer changes** (#41). Intra-bar replay
  built the forming bar from the finer feed alone and closed the bucket on the
  displayed bar, so where the two feeds disagree (the official open against the
  first minute's, finer extremes past the displayed ones, finer volumes that sum
  past the displayed volume) the open jumped when the bar closed, a high could
  fall back and volume could shrink, and every indicator read those prices.
  Every forming step now carries the displayed bar's open, keeps its extremes and
  close within the displayed high and low and its volume within the displayed
  volume; where the feeds agree each step is still exactly the aggregate of the
  finer bars. On a year of RELIANCE, HDFCBANK, INFY and SBIN daily bars replayed
  from hourly ones, the open moved at the close on 199 of 232 candles (up to 0.84
  percent) and a forming high passed the real one on 3 steps; hourly and
  5-minute replays showed forming volume above the candle's on 203 steps. All
  are zero now in Chromium, Firefox and WebKit, and every close still lands on
  the displayed bar exactly.
- **Line-family series at the edges of the view** (#37 and its follow-ups). A
  sparse level held across the left edge lost the part entering from off screen,
  and with no bar in view the whole line. The edge segment is now cut at the plot
  edge before it is stroked or filled, on the 2D and WebGL2 backends and in the
  SVG export: a dashed level whose bars sat sessions either side of the view used
  to upload 63 million floats a frame to the WebGL2 backend and took 170 to 500
  ms a step, and now uploads about 5,600. Dashed and dotted strokes keep 2.5.8's
  dash pattern along the bars in view, and a gap at the edge (a whitespace item
  or a study's missing value) is never bridged by a line, an area, a baseline or
  an HLC band.
- A chart whose container is taken out of the document while the pointer is over
  it (a keep-alive view switch, from the keyboard or in code) no longer answers
  hover-scoped shortcuts while it is parked.
- Series markers take the last fallback bar of a repeated time, the live one (#31).
- Reference host: the yfinance server loads prices as they traded
  (`auto_adjust=False`), and a daily chart loads at least five years, so it holds
  500 candles or more (#35). Replay asks the finer interval only for the history
  the source keeps, so the last week of a 5-minute chart forms from real 1-minute
  bars. Select all leaves out drawings the interval hides.

### Performance

- **A drawing hit test asks only the drawings near the pointer.** Each drawing
  layer keeps a box per drawing, measured again when the scales, the bars, the
  plot size, the pointer kind, the tools or the fonts change. With 500 trend lines
  a pointer move asks 4.5 drawings instead of 500, and the hit test takes about a
  tenth of the time (medians 63.8 to 5.8 us, `node scripts/bench-pane.mjs`).
- **Markers** (#31): a paint reads the bar under each drawn mark instead of
  indexing the series' whole history, so a single marker on a long intraday
  history no longer pays for all of it: 29.84 ms to 0.010 ms a paint at 200,000
  bars and 500 markers, in the unit harness.
- **Data layer** (#36): it counts how many series hold each time, so dropping a
  time costs its own series instead of rebuilding the shared index from every
  series.
- Building a joining renderer's draw items no longer makes a closure per series
  per frame.
- **Measured against 2.5.8** on the release bench (five runs of each build in one
  session, `benchmarks/releases.json`, the website's Benchmarks page): frames are
  on par. On Canvas 2D at 200,000 bars a full zoom-out and a ten-study tick take
  about 4 percent longer (medians 54.1 to 56.6 ms and 146.8 to 152.1 ms), a
  ten-study tick at 50,000 bars is about 15 percent quicker (64.8 to 55.3 ms), and
  WebGL2 frames are within a few percent either way.

### Website

- The site opens in the light theme; a saved choice still wins (#39).
- A Benchmarks page lists each release against the one before (#34).
- A Vue 3 guide (#40), and the docs for everything above.

### Tests

- 9803 unit tests across 442 files and 668 reference host tests across 63 files
  pass, and the browser suite passes 1667 cases in Chromium, Firefox and WebKit.
  The replay fixes carry tests that fail on the previous code, and fixtures whose
  finer and displayed bars disagreed by construction now describe consistent
  feeds. Against 2.5.8, every pixel that differs lies in the price axis strip of
  a study pane (edge labels and value tags) or at an edge of the view.

Saved layouts, drawings and workspace documents from 2.5.8 load unchanged, and
no runtime dependencies or package tiers were added.

Sizes, measured on this release and against 2.5.8 (Brotli, decimal kB): base
engine 130.37 to 131.68, base plus trade 147.06 to 148.36, draw 48.42 to 55.61,
widget 92.72 to 99.64, workspace 10.47 to 11.33, transform 4.50 to 4.56, WebGL2
6.39 to 6.93, widget terminal 311.90 to 327.32 and every tier together 364.91
to 381.78; the indicators, profile and trade tiers are unchanged. The
chart-only import grows from 83.87 to 84.82 KiB: the line-family edge work and
the price axis fixes run on every chart, while the drawing gestures, the
widget's drawing UI and replay's simulated forming shake out. Each budget is
the smallest two-decimal value that passes.

## 2.5.8

2026-09-26

Rendering performance. A live tick no longer rebuilds the chart's time index or
rewrites every study plot, sixteen common built-in studies update without a pass
over the whole history, a tick or a study recompute repaints only the panes it changes,
and a zoomed-out chart draws one stick per pixel column. Two things a host can
see change: the level of detail is on by default (`conflate: true`), and a
study's plot series now receives `update()` calls on a live tick. A render bench
in CI holds frame budgets per bar count.

### Added

- `IPrimitive.hitBounds(rc)`, optional: the box, in the plot-relative media px
  `hitTest` receives, outside which the primitive's `hitTest` answers null
  (edges inclusive, a side may be infinite), or `null` when nothing of it can be
  hit. A pointer move then asks `hitTest` only of the primitives whose box holds
  the point, so a pane carrying hundreds of annotations pays for the few near
  the pointer. A primitive that declares a box promises three things. The box
  holds every point its `hitTest` can answer: a point outside it is never
  asked, so a box that is too tight loses hits. The box changes only with what
  the pane follows (the time scale and the bars' times, the pane's price
  scales, size and axes, the pixel ratio, hover and drag, the theme and the
  session calendar) or with the primitive's own state, which it announces
  through `host.requestUpdate()`; a box that follows anything else, bar prices
  say, must request an update when that changes. And its `hitTest` is free of
  side effects, since the pane may skip it. A NaN edge makes the pane ask
  `hitTest` anyway. The pane keeps each box until one of those changes, and a primitive
  that declares one is attached with a host object that wraps the chart's, so
  the pane hears its `requestUpdate`. No built-in primitive or drawing layer
  declares a box yet, so they are asked on every move as before.
- Render bench: `npm run bench:render` (`tests/e2e/render-bench.perf.ts`) times
  a pan, a frame with every loaded bar in view and a forming-bar tick with ten
  studies, at 10,000, 50,000 and 200,000 bars, on the `canvas2d` and `webgl2`
  backends in Chromium. Each step is timed from the input to painted pixels, and
  the run fails when a p95 exceeds its budget. The budgets live in
  `scripts/render-bench-budgets.mjs` as two measured tables, never under 17 ms:
  local runs use the lowest p95 of five desktop runs times four, and CI uses
  the hosted runner's own p95 times 2.5, because the runner measured up to five
  times the desktop figures. CI runs the bench in a job of its own, and
  `docs/performance-notes.md` records the measurements, the margin and why the
  bench's fast results can be trusted.
- Nightly workflow (`.github/workflows/nightly.yml`): the soak for a 6.25-hour
  session (90,000 ticks, 1,000 create and destroy cycles), thirty minutes of
  browser endurance and the render bench, on a hosted runner. Every report is
  kept, pass or fail.

### Changed

- **The level of detail is on by default.** `ChartOptions.conflate` now
  defaults to `true`. Below about one CSS px per bar (exactly one at a whole
  pixel ratio: the bar is narrower than the stick a candle is drawn with), the
  bars sharing a device-pixel column draw as one OHLC-preserving stick: open of
  the first bar, close of the last, the column's high and low, volume summed,
  the last open interest and the colours of the bar that closed the column.
  Line, step, area and baseline series keep each column's first, lowest,
  highest and last bar, with a gap kept as a gap; the HLC area keeps those
  plus each run's highest high and lowest low, so its close line, band edges
  and gaps match the full frame; and columns and histograms keep the lowest and
  highest bar, so they cover the pixels every bar would. A merged stick sits in
  the column that holds its middle pixel, at every pixel ratio. At
  or above one bar per stick nothing changes, and the default
  `timeScale.minBarSpacing: 1` never zooms out that far, so a chart that keeps
  the floor paints as before: render parity against 2.5.7 is zero differing
  pixels for every built-in series type at pixel ratios 1 and 2. `conflate:
  false` draws every bar at every zoom. `conflationFactor` now means the column
  width in sticks (it was a multiplier on a half-pixel threshold): `2` merges
  into two-stick columns from spacings under two CSS px. A renderer a host
  registers, even under a built-in name, always receives every bar. Data,
  autoscale, indicators and the crosshair still see every bar.
- **A study's plot series receives `update()` on a live tick.** A recompute
  whose bars begin with the times the last one wrote sends each plot only the
  points that changed, and its last point, through `SeriesApi.update`, where it
  used to hand each plot its whole history in one `setData`. New or older
  history, a filled gap, a plot the previous pass did not write and more than
  eight moved points still go through `setData`. What each plot holds is
  identical, key order included. A custom `IndicatorHost` must therefore
  return from `addIndicatorSeries` a series whose `update` behaves as
  documented: an item at an existing time replaces that point, an older one
  included, and a newer one appends. A study is the only writer of its plot
  series: `indicator.series(key)` is for styling, and data written into it now
  survives wherever the study did not move a point.
- **Sixteen built-ins carry a `calcTail`:** `sma`, `ema`, `wma`, `rsi`, `atr`,
  `adx`, `macd`, `bollinger`, `vwap`, `supertrend`, `stochastic`, `obv`, `cci`,
  `keltner-channel`, `donchian` and `parabolic-sar` (see Performance). It is a
  non-enumerable own property: `SMA.calcTail` and `'calcTail' in SMA` see it,
  `Object.keys(SMA)` and `{ ...SMA }` do not. A descriptor that spreads a
  built-in therefore keeps recomputing in full through its own `calc`, exactly
  as on 2.5.7. To keep the tail on a copy, write `calcTail: SMA.calcTail`, and
  only when your `calc` returns the built-in's result unchanged for the settings
  it is given, since a tail never calls your `calc`. A copied tail stops for
  good when the held result has a column it does not write.
- **Kinetic scroll and the eased wheel zoom step inside the render frame.**
  They schedule no animation frames of their own: the chart steps them at the
  top of its frame, before the study flush, so each frame paints the step it
  made rather than the one before, and a glide asks the frame scheduler (an
  injected `raf` included) for one frame per frame instead of two. A glide
  step's `pan` or `zoom` event fires in the frame that paints it. The autoscale
  easing during a glide starts one frame earlier; final ranges are unchanged.
  A frame's own glide step or study recompute no longer schedules an empty
  frame after it.
- The draw items a renderer (`RendererEntry.draw`) or a render backend
  (`IRenderBackend.drawSeries`) is handed, the array and its objects, belong to
  the pane: they are rewritten in place the next time it draws that series, so
  a renderer or backend that keeps them past the call must copy. The `priceToY`
  it is handed is one stable function per series.
- A pointer move stops walking a pane's primitives at an exact hit
  (`distance: 0`) among those painted in front, which nothing after it can
  outrank. `PrimitiveHit.distance` is documented as never negative.

### Performance

- A tick or a study recompute repaints only the panes it changes. A live tick
  that replaces the forming bar repaints the price pane and the panes of the
  studies computed from it. A study recompute repaints only the panes its
  output lands on: its own pane, and the price pane for a plot or bar colours
  sent to the candles; a data-derived study level repaints its own pane. Each
  repainted pane re-measures its scale. A write that moves the shared index or
  the time scale still repaints every pane: an appended bar, a host `setData`
  or `prependData`, and a study that opens a pane. While
  `axisChrome.sessionClock` is on, a pane-scoped write also repaints the bottom
  pane, and while `axisChrome.barCountdown` is on, every pane with a price
  series, since neither reading has a timer of its own. The pixels are those of
  a full repaint.
- A live tick no longer rebuilds the shared time index, which ten studies used
  to rebuild about two dozen times per tick. `DataLayer.setSeriesData` rebuilds
  it only when the set of times changes (a time dropped, or a new one inside
  the axis) and adds new times past the right edge in place, input already in
  time order skips the sort, and `DataLayer.update` finds an older bar by binary
  search. A whole write whose times the index already holds (a study after a
  page of history, a bar-colour overlay on the source) and stepping replay
  forward rebuild nothing either.
- The sixteen built-in tails: a tick on the forming bar, or one appended bar,
  costs them a step or one window instead of a pass over the loaded history.
  The spliced result equals a full `calc` value for value, NaN and negative
  zero included, which a property test checks after every tick and appended
  bar on random histories with session breaks, missing prices and missing
  volume. The studies that carry state from bar to bar rebuild it once after
  each full calculation (a load, a history change, a settings change), so the
  first tick after one costs about a full pass. The tail declines, and `calc`
  runs, for a length that is not a positive whole number, a negative Donchian
  `offset`, any VWAP `offset`, and a VWAP bar that changes how the history's
  sessions are read. Such a tick leaves their output history as it was, so a
  study built on one of their outputs (an EMA of an SMA) is now offered its own
  tail. The other 89 built-ins still recompute in full.
- The series pass allocates nothing per bar. The pane walks the visible bars in
  place and each series keeps its draw items between frames; the candle, bar,
  column and line renderers and the time axis build no object per bar, and the
  line-family renderers, which draw every indicator plot, project into point
  buffers they keep.
- With the level of detail a zoomed-out frame paints marks by the plot's width,
  not by the number of bars in view.
- On the render bench (`docs/performance-notes.md`: the lowest p95 of five
  runs on one desktop machine, headless Chromium), a forming-bar tick with ten
  studies went from 1166.3 to 49.2 ms at 50,000 bars and from 5591.7 to
  152.2 ms at 200,000 bars on `canvas2d`, and from 5785.6 to 167.5 ms at
  200,000 bars on `webgl2`. A frame with all 200,000 bars in view went from
  278.2 to 53 ms on `canvas2d`. A pan did not change. The 2.5.7 figures were
  taken with other suites sharing the machine; one quiet run of 2.5.7 came
  within 10% of every zoom-out and tick figure. A tick still grows with the
  loaded history rather than the view, about 7.6 times from 10,000 to 200,000
  bars on `canvas2d`.

### Fixed

- Browser endurance reads its canvas-changed hash and candle-pixel count from
  the price plot only. Before, the price-axis last-price tag could satisfy both
  gates over a frozen plot.

### Documentation

- README and ARCHITECTURE.md describe the repaint scope, the clock and
  countdown rule, the single animation loop, the level of detail and the
  in-place plot writes; `tests/docs-claims.test.ts` holds the repaint and loop
  statements to the code in both directions.
- ARCHITECTURE.md no longer sketches a time-scale operation queue in the
  invalidation mask. `InvalidateMask.addTimeScaleOp` and `timeScaleOps` stay
  for compatibility and are not deprecated; their documentation says the chart
  never queues or reads an operation.
- `docs/performance-notes.md` records the render bench, its budgets and the
  comparison with 2.5.7, and the website's Performance page describes the frame
  budgets and the nightly run. The skills and the site describe the level of
  detail, primitive hit boxes, the built-ins' tails, the draw item lifetime and
  what a custom indicator host's plot series must do.

### Internal

- `npm run bench` fails when a burst of ticks between two frames recomputes any
  indicator other than exactly once. It used to print the result and pass
  either way.
- CI builds the render-parity baseline from the newest release tag, so
  `tests/e2e/render-parity.spec.ts` compares pixels on every change instead of
  skipping; `PARITY_BASELINE_REF` overrides it for a change meant to move
  pixels. The parity spec now holds all 13 built-in series types to the
  previous release's pixels at pixel ratios 1 and 2.
- New browser specs compare studies through live ticks
  (`indicator-tick-parity`) and the built-in tails (`indicator-tail-parity`)
  with the previous release pixel for pixel, and check the repaint scope and
  the one frame request per glide frame (`repaint-scope`). All three pass in
  Chromium, Firefox and WebKit.
- `node scripts/bench-pane.mjs` counts the marks a zoomed-out frame paints, the
  allocation while panning and the hit tests per hover move, and fails on its
  budgets; `node tests/bench/plot-tick.mjs <dist-dir>` times a ten-study tick
  on any build.

Saved layouts, drawings and workspace documents from 2.5.7 load unchanged, and
no runtime dependencies or package tiers were added.

Sizes, measured on this release and against 2.5.7 (Brotli, decimal kB): base
engine 126.91 to 130.37, base plus trade 143.60 to 147.06, indicators 36.44 to
40.38 (the sixteen tails), widget terminal 304.49 to 311.90 and every tier
together 357.50 to 364.91; the trade, draw, widget, workspace, transform,
profile and WebGL2 tiers are unchanged. The chart-only import grows from 80.87
to 83.87 KiB: the level of detail, the reused draw items, the hit boxes, the
kept time index and the pane-scoped repaint all run on every chart. Each budget
is the smallest two-decimal value that passes.

## 2.5.7

2026-09-26

An internal release: the chart's code is reorganised and nothing a host calls,
receives or sees changes.

### Internal

- `src/core/chart.ts` is split by responsibility. The `Chart` class keeps every
  public method, overload and doc comment, the state its concerns share, the
  frame, the event bus and the lifecycle; the logic moved into collaborators in
  `src/core/chart-*.ts`: series, studies, panes, legends, price scales,
  primitives and the draw order, appearance and export, input routing,
  navigation motion, pixel-ratio tracking, and state capture and restore, with
  the public option and event types in `chart-types.ts`, re-exported from
  `chart.ts` so every import path is unchanged. The file went from 6,729 lines
  to 2,577. ARCHITECTURE.md lists the modules under Chart internals.
- Each collaborator reaches the chart through a host interface typed member by
  member from the chart (`Chart['_panes']`), and the chart itself is passed as
  that host, so the compiler rejects a member the chart lacks and no forwarding
  object is built. Private members stay private: the published declarations
  name the collaborators only as `private` fields.
- The move is proved by the suites as they were: no test assertion changed (one
  compatibility inventory now names the file three moved comments live in), the
  render-parity spec paints the same pixels as the 2.5.6 build at all seven
  zoom levels, and the browser suite passes in Chromium, Firefox and WebKit.
- ESLint holds every source file to 1,500 lines (`max-lines`). The five files
  already over it are capped at their size in `scripts/line-caps.json`, and
  `tests/line-caps.test.ts` makes a file that comes under the limit leave the
  list, so the exemptions can only shrink.

Sizes, measured on this release and against 2.5.6 (Brotli, decimal kB): base
engine 125.39 to 126.91, base plus trade 142.07 to 143.60, widget terminal
302.96 to 304.49 and every tier together 355.97 to 357.50; the trade,
indicator, draw, widget and workspace tiers are unchanged. The chart-only
import grows from 79.25 to 80.87 KiB. The 1.52 kB on the base engine is the
cost of the class shells and the delegates the chart keeps for its public
methods; a first cut that built a forwarding object per collaborator cost
3.66 kB and was replaced before release. Saved layouts, drawings and workspace
documents from 2.5.6 load unchanged, and no runtime dependencies or package
tiers were added.

## 2.5.6

2026-09-26

### Added

- `chart.setSessionCalendar(calendar)` sets the hours the time axis follows
  past the last bar and repaints every pane, so a drawing already placed there
  moves to the time it now means; `null` clears them. Any object with
  `sessionFrom(utcSeconds)` qualifies (`SessionCalendarSource`), so a host
  setting hours it built itself needs neither `applyTo`. Both `applyTo` calls
  below go through it.
- `chart.dataLayer.setSessionCalendar(calendar)` and the `sessionCalendar`
  getter set and read the same hours. The data layer cannot reach the chart,
  so this setter moves times without asking for a frame: the path for a host
  about to load bars or move the view anyway. `Instrument.applyTo` now sets the instrument itself, so a host that
  applies instrument metadata gets the fix with no other change. Another
  instrument replaces its hours, and a data context moved to another symbol or
  exchange drops them, so a symbol the host holds no instrument for is not laid
  out in the last one's sessions.
- `SessionCalendar`, trading hours without price or quantity rules: built from
  `{ timezone, sessions, exceptions }` (`SessionCalendarSpec`), validated,
  detached and frozen by the same rules as an instrument's calendar, with
  errors reading `Invalid session calendar: ...`. It reads with the same
  `sessionAt`, and `applyTo(chart)` sets it as the chart's calendar and
  repaints, so drawings already past the last bar move to the times they now
  mean.
- `sessionFrom(utcSeconds)` on `Instrument` and `SessionCalendar` returns the
  window active at an instant, or else the next one to open, looking about a
  year ahead, and null when nothing opens in that time. An overnight window
  still running is returned on its opening date.
- The reference host lays the empty space right of the last candle out in the
  venue's regular hours (NSE and BSE 09:15 to 15:30 IST, US 09:30 to 16:00 New
  York, weekdays), on both charts of the split view, and in the host
  instrument's own calendar for a symbol it holds metadata for. Crypto and
  venues without hours keep the median spacing.
- A `layout:change` event (`LayoutChangeEvent`, naming a `LayoutSetter`)
  after the setters that change what `getState` saves and had no event of
  their own: `setPaneWeight`, `setPriceAxisOptions`, `setPriceAxisAutoFit`,
  `setPriceAxisLockRatio`, `setPriceScaleOptions`, `setAutoScale`,
  `setGridOptions`, `setCanvasOptions`, `setStatusLineOptions`,
  `setWatermarkOptions`, `setTradingSettings`, `setAxisChromeOptions`,
  `setEventOptions` and `applyOptions`. It fires once per outermost call,
  after the change is applied, so the canvas block setting the grid on its way
  is one `setCanvasOptions` event; a call naming no pane the chart has fires
  nothing, and a restore fires none, since it announces itself. A host that
  saves its layout, or an undo history, now hears these changes when they
  happen. The reference host autosaves on it, which now covers a grid toggled
  with the chart's own Alt+V and Alt+H keys.
- `chart.priceScaleDefaults()` reads the chart-wide price-scale defaults that
  `setPriceScaleOptions`, the `priceScale` option and the canvas margins set,
  and that a pane added later starts from. `priceScaleOptions()` reads the
  price pane's own scale, which a change made to that one axis moves and the
  defaults do not, so the two tell a chart-wide change from a one-axis one.
- Accent registries for the icon sets: `DRAWING_TOOL_ACCENTS` /
  `drawingToolAccent(id)` and `CHROME_ICON_ACCENTS` / `chromeIconAccent(id)`,
  optional per glyph. An accent is the fill of marks the glyph's own path
  already draws as outlines (anchor dots, pole caps, arrowheads, slider
  knobs), so it adds weight and never identity: a host that draws only the
  path data still shows every mark that tells one glyph from another.
  `iconSvg`, `chromeIconSvg`, `iconSprite` and `toolCursor` draw it as a
  second `<path>` with `fill="currentColor" stroke="none"` after the glyph.
- A browser check for look-alike icons, `tests/e2e/icon-raster.spec.ts`. Every
  glyph is rasterised at its native size in Chromium, Firefox and WebKit, twice:
  as the builders draw it, and as the bare path data a host that wraps the
  registry itself draws. The check fails when two glyphs in a tier overlap at
  an intersection over union of 0.85 or more in either rendering (only the
  star, eye and link state pairs may), when a named sibling pair reaches 0.7,
  or when a tier's share of solid pixels falls below its floor (0.59 for the
  tools, 0.6 for chrome, measured 0.59 and 0.62).
- Study policies. A study carries an `IndicatorPolicy` of four independent flags,
  each defaulting to true, the way a drawing carries its `DrawingPolicy`:
  `removable`, `configurable`, `movable` and `listed`. Pass it with
  `addIndicator(id, settings, { policy })`, read it with `indicator.policy()`
  (the flags that are false) and replace it with `indicator.setPolicy(policy)`,
  or `null`, which is always the host's act. A policy restricts the user: every
  native call a user control makes treats its caller as the user unless it passes
  `{ force: true }` (`IndicatorEditOptions`), and returns false with nothing
  changed when refused. `removable` covers `chart.removeIndicator`,
  `indicator.remove` and `chart.removePane` for a pane holding the study;
  `configurable` covers `setSettings`, `setPriceScale` and `setPlotPriceScales`;
  `movable` covers `chart.moveIndicator`, `chart.reorderIndicator` and
  `chart.moveInSeriesStack`. `setSettings` and `remove` now return a boolean. The
  legend row drops its close button and gear (and a stale press on either does
  nothing); a row whose buttons the host set with `legend().setOptions({ actions })`
  keeps them through every restack, with the policy laid over them. `ChartObjects`
  withholds remove, settings, reorder, move and place and leaves an unlisted study
  out, and the widget greys its settings and remove menu rows and the picker's
  remove button with the note "protected", declines the settings dialog with the
  reason, reports a write the host refused after locking the study while the
  dialog was open, and leaves an unlisted study out of the picker and the alert
  source lists. Hiding a study stays the user's choice. A restore is the host's act
  and replaces a protected study. The chart state saves only the restrictions
  (`IndicatorState.policy`), so an unrestricted layout is written exactly as before
  and older layouts restore unrestricted; a malformed policy refuses the restore.
  Workspace documents keep policies. A portable template is the user's copy of the
  user's own studies: it leaves out every study the host keeps from the user (one
  that is not `removable` or not `listed`) and every study reading the output of
  one, lets go of a scale range such a study owned, and copies a study with other
  restrictions without them. A template applied in `replace` mode keeps the host's
  studies, on their own panes, so it neither copies nor removes them.
  `parseIndicatorPolicy` validates a policy. The yfinance host adds **Add Protected
  VWAP** to its chart menu and removes it with `force`; importing or loading a
  layout keeps it, and a layout file's own restricted studies are left out.
- Draw order across sources, studies and drawings. A pane paints in bands, back
  to front: behind the series, the series band, the overlay band (price lines,
  markers, study levels) and in front. The series band holds the price source and
  each study in paint order, read with `chart.seriesStack(paneIndex)`, and
  `chart.moveInSeriesStack(id, target, 'above' | 'below', options?)` moves the source
  or a study next to another entry; a study's fills, levels and markers keep their
  bands and follow the new study order. A drawing can now sit between studies:
  `Drawing.stackAbove` names the entry it paints directly above,
  `draw.placeInStack(id, { drawing } | { entry }, where)` puts it next to another
  drawing or an entry as one undo step, `reorder`, `bringToFront` and `sendToBack`
  work within the slot it paints in, and `sendBehindSeries` and `bringAboveSeries`
  take it out of the series band. Any primitive can be placed the same way with
  `chart.setPrimitiveStackAbove(primitive, entry)`; a batching renderer flushes
  before it, so the WebGL2 backend keeps the order. `ChartObjects.stack(paneIndex)`
  lists a pane back to front, and `canPlace` and `place` move a drawing anywhere in
  its pane and a source or study only between whole slots, taking the drawings
  placed on it along; a move the bands cannot paint is refused. Rows gain `band`,
  `stackAbove` and the `place` capability (`ChartObjectBand`,
  `ChartObjectDrawingSource.placeInStack`, `DrawingStackTarget`). The pointer takes
  what is painted on top: the front drawing layer answers for every layer of its
  pane front to back; whatever paints over the series (the overlay band and the
  front) takes a press, a hover, a click or the context menu from whatever paints
  with or behind it (a drawing or primitive placed in the series band, a drawing
  behind the series, a bottom primitive) wherever it answers, whatever the
  distance, so a box placed under an order line gives the line the press; and a
  right-click over a drawing or placed primitive and a series painted over it
  targets the series (`PrimitiveHit.paintedBy`). A bottom primitive, such as a
  bracket's stop line, now yields the same way to a primitive over the series
  within reach, where it used to win by being nearer. The price source stays the pane's instrument wherever it
  paints: the crosshair readout, the last-price line and a rebased axis describe it.
  A moved source saves `ChartState.sourceAbove`; a drawing's slot is saved in the
  drawing document and carried by duplicate and the clipboard; a drawing whose
  study is gone paints in front until the study returns. Layouts and drawing
  documents from 2.5.5 load and paint unchanged. The widget's Objects panel lists
  each pane in draw order, notes a drawing behind the series or above an entry,
  reorders by dragging a row onto the upper or lower half of another and refuses a
  drop the bands cannot paint before it lands, and Earlier and Later step through
  the same order.
- Paired time and price inputs. A `price` input can name a declared `timestamp`
  input with `timeKey`, making the two one point on the chart; `anchor: true` adds
  a handle there. Registration refuses a `timeKey` that names no timestamp input,
  the price itself or a timestamp another price already pairs with, and an
  `anchor` without a `timeKey`. `chart.beginPick('point', cb, options?)` captures
  both halves from one click as a `PickPoint` (`{ time, price }`, the time snapped
  to the bar), reads the price on the target scale and answers only when both
  resolve; `pick:start` and `pick:end` carry `kind: 'point'`. The widget's and the
  reference host's settings forms offer **Pick point on chart** on the price row
  and commit both keys in one patch. The drawing tier draws the anchor on the pane
  and scale a pick of the price reads (`studyInputTarget(chart, study, key)`,
  exported from `openalgo-charts/draw`): dragging it previews the point with guides
  to both axes and writes both settings in one patch on release, Escape cancels, an
  active drawing tool or a waiting pick takes the press, and a study whose policy is
  `configurable: false` keeps it still. Each drag is one step of the drawing undo
  history, in order with the drawings, and emits `drawing:change` with empty `ids`
  so Undo controls refresh; a host keeping one timeline of its own takes the steps
  with `draw.delegateInputAnchorSteps(record)`, as the chart-wide `ChartHistory`
  below does, so Ctrl+Z, the rail and the phone bar take a drag back once in both
  hosts. `draw.moveInputAnchor(studyId, key, point)` moves an anchor the
  way a drag does, as one step, for a host control that sets the point another way
  (a point pick). `new DrawingController(chart, { inputAnchors: false })` draws
  none. The reference host adds the Anchored growth sample.
- `chart.plotRect(paneIndex)` returns a pane's plot in container px (`PlotRect`:
  `left`, `top`, `width`, `height`), inside the price axis columns and above the
  time axis, or null for a collapsed, hidden or missing pane. It scales the pane
  first, as a price conversion does, so a pane no frame has painted yet (just made
  or just moved) answers in its prices and not its placeholder range. The draw tier now
  places, moves and converts drawings pinned to the screen by it rather than
  working the rectangle out from the scales, so `draw.screenPoints` and a host
  overlay laid against `plotRect` agree. `DrawingChartHost` gains the optional
  `plotRect` and drops the optional `priceAxisLayout` it no longer reads.
- `chart.setTickSchedule(schedule | null)` and `chart.tickSchedule()` put the
  instrument's price-dependent ticks on the chart. `Instrument.applyTo` sets it,
  and a host with its own metadata calls it; it also reaches `chart.trading`, now or
  when that layer is built. `chart.snapPrice` on the price pane then rounds with the
  band the price falls in, and a dragged price alert lands on that band's tick, a
  range bound stopping a band tick inside an off-tick opposite bound. With no
  schedule every rounding is unchanged. A schedule without `round` and `step` is
  refused when it is set, not on the first drag. `AlertChartHost` gains the optional
  `tickSchedule()`. The reference host hands its `BANDED` schedule to both charts.
- `chart.addIndicator(id, settings, { instanceId })` gives the study that id, so a
  host that brings a removed study back (an undo) brings back its identity and the
  studies reading its output and the alerts naming it find it again. An id a study
  on the chart holds now throws; the id of a removed study is free to take back.
- One undo timeline for the whole chart. `ChartHistory` in the widget tier
  records a study added or removed (with its settings, visibility, pane,
  stacking row and price scale), study settings, visibility and scale
  assignments, the chart type and the primary series' scale, price scale
  settings (mode, invert, margins, auto-fit, pinned ratio and axis placement),
  pane moves, folds and heights, panes added or removed on their own, the chart
  settings the settings dialog writes, and drawings, in the order they were
  made. The widget builds one as
  `widget.history` (and `ctx.history`): Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z, the
  rail's Undo and Redo, and the mobile sheets all walk it. The mobile More
  sheet now opens with Undo and Redo, and the Drawing sheet gains Redo.
- A step is taken back by making the chart look the way it did in exactly the
  fields that step changed, through the chart's public calls, never by
  restoring a whole saved state. A study removed with the pane it emptied comes
  back to its slot with the pane's height, fold and axes and the drawings that
  pane held. Undo never writes bars, never fires an alert (a study brought back
  reseeds silently) and never places an order.
- The chart settings and study settings dialogs are one step per session, and
  a Cancel that restores every value leaves none; each context-menu row is one
  step. `transact(fn, label)` records what the chart does not announce,
  `group(label)` merges a live edit, `ignore(fn)` keeps a host's own change out,
  drawings included and the redo branch kept, `push(command)` records a host's
  own reversible step, and `attach(chart, draw)` keeps the timeline across a
  host's chart rebuild. A listener's change while a step is applied is not a
  step either, and a Cancel gives the redo branch back. A step that cannot be
  applied is rolled back, dropped with the steps behind it, and reported to
  `onError`; a new action clears redo; `restoreState` starts a new timeline.
- `DrawingController.historySteps()` and a `step` number on the `drawing:change`
  that closes a recorded step (`DrawingChangeEvent`), so a host can hold drawing
  steps in a timeline of its own, and `DrawingController.untracked(fn)`, which
  runs a host's own edits without recording a step or touching either branch,
  taking them into every recorded step the way a forced edit is.
- A linked appearance change is an undo step of the chart that made it only: the
  chart grid and the reference host's split view apply it on the others outside
  their timelines, and undoing or redoing it announces the result again, so linked
  charts never drift apart.
- The yfinance reference host walks one timeline per chart: the keyboard and the
  mobile bar walk the focused chart's, the drawing toolbar and the rail the main
  chart's. It records its chart-type rebuild as a command, makes each chart
  settings and study settings session one step, and keeps comparisons, the volume
  row and loaded layouts out of it.
- A study input anchor's move is one step of the chart-wide timeline, taken back
  once. `DrawingController.delegateInputAnchorSteps(record)` hands the step each
  anchor move makes (a drag, `moveInputAnchor`) to a host's own timeline, with its
  own `undo` and `redo` (`InputAnchorStep`), until the returned function gives the
  steps back, and records none of them itself. `ChartHistory` takes them from its
  drawing controller, and from one it is attached to later, and records the
  settings patch the move wrote as the move ends, so the rail's Undo is on the
  moment a drag is released. A drag, `moveInputAnchor` and a settings dialog's
  **Pick point on chart** are each one step, walked in order with the drawings:
  an undo after a pick takes the pick back, never a drawing made before it. A
  press that grabs something starts a step of its own, so a change made earlier
  in the same turn is not taken back with the drag. A move made inside
  `untracked`, and so inside `ignore`, is the host's own and a step nowhere.
- Without a chart-wide history, the drawing controller holds a point written
  through a study's settings, as a settings dialog's **Pick point on chart**
  writes it, as a step of its own, the way it holds a drag. Before, a drag
  followed by such a pick left the drag's step describing a point the study no
  longer held, and an undo passed over it and removed an unrelated drawing made
  before both, leaving the pick in place. Now the first undo takes the pick back,
  the next the drag, and only the third the drawing. A write inside `untracked`,
  or forced on a study the user may not configure, is the host's own and no step,
  and `delegateInputAnchorSteps` hands over only the anchors' own moves, since a
  host timeline sees a settings write itself.
- Undo and redo never override a study's policy. A press leaves a study as its
  policy keeps it: not removed while `removable: false`, its settings and scales
  as they are while `configurable: false`, its pane while `movable: false`, and
  never moved by a call of its own. Other studies still pass one that may not
  move, as the chart lets them: a user's reorder that moves a free study past a
  pinned one is a step and is taken back, and a study removed from above a pinned
  one comes back above it; two pinned studies never trade places. The rest of the
  step still applies, and a step left with nothing to do (removing a study the
  host has protected since) is dropped and the press goes on to the one before,
  as the drawing history treats a read-only drawing, so `canUndo`, `canRedo` and
  the peeks say what a press would do, and `subscribe` hears when a policy changes
  that. A change only the host could make, adding a protected study or a forced
  write or remove on one, is no step.
- Undo and redo never remove or weaken a policy the host set later. A study a
  press brings back takes the policy its host holds now, the one it last had on
  the chart, never an older one the step captured: a restriction added after the
  step was made is still on the study that comes back. A study that left the
  chart by the host's hand (inside `ignore`, through a forced remove, or left out
  of a chart the host rebuilt and passed to `attach`) is the host's to bring
  back: the part of any step that would re-add it is dropped, and a step with
  nothing else to do goes with it.
- A study brought back by an undo or redo takes back the instance id it had, so
  the studies reading it and the alerts naming it find it again. The history
  tells studies apart by the chart's own object for each, not by id or kind: if
  a study the host placed under that id since holds it, of the same kind or
  another, the one brought back takes a fresh id with the settings the step gives
  it, the later steps and the studies reading it follow it there, and the host's
  study keeps the id, its pane and its settings and is never taken for the one a
  step means.
- `ChartHistory` records a pane height or a scale option set in code outside a
  transaction (`setPaneWeight`, `setPriceAxisOptions`, `setPriceScaleOptions` and
  the other setters the chart now announces with `layout:change`) as a step of
  its own. The chart-wide price scale defaults (`priceScaleDefaults()`: mode,
  invert and both margins) are a field of each step apart from every pane's
  axes: a chart-wide change is taken back with them, so a pane added after the
  undo starts from the old defaults, while a change to one axis from its menu,
  on a chart with a single pane too, is replayed on that axis alone and never
  writes the defaults or announces a linked appearance change. The chart
  settings `scales.mode`, `scales.inverted` and `scales.autoScale` are no longer
  compared as settings, since the defaults and the axes carry them.
- A step made of several stretches (a group or a transaction with an `ignore`
  inside it) reads each stretch against the chart the stretch before it in the
  press leaves, rather than the chart before the press, so a later stretch whose
  stacking order the chart held already still puts back the order an earlier one
  changed. A command pushed inside `ignore` is no step. A pane a host makes for a
  primitive of its own (`addPrimitive` at a new index) or a drawing it places
  there is the host's, like one it plots a series in: no `pane-add` step, and no
  undo or redo makes or removes it.
- Conditional study inputs. Every `IndicatorInput` (and a chart settings colour
  pair) takes `visibleWhen` and `activeWhen`, an `IndicatorInputCondition` over
  the other settings: `{ key, is }`, `{ key, isNot }` with one value or a list,
  and `{ all }` or `{ any }` to combine them. A hidden input leaves the form and
  the tab order; an inactive one stays readable, disabled, with a reason naming
  what it depends on. Rules cascade through an input a condition reads, and a
  colour pair's switch and colours count as the pair. They are presentation
  only: `calc` receives every setting, and a hidden value is kept.
- Inline rows: consecutive inputs with the same `inline` id share one row, the
  first one's label leading it, each member with its own label. A multi-line
  input and a colour pair always take a row of their own.
- The widget's generated forms and the reference host's form re-read the rules
  after every edit and every sync, announce what was shown, hidden, made
  available or unavailable in a polite live region, and move focus off a control
  that just left. A hidden or disabled draft never blocks OK or Apply: a valid
  one is kept and saved, an invalid one is not written. Defaults resets hidden
  inputs too, and Cancel restores the rows the original settings show. A pick
  or search beside a disabled field is disabled with it. Both forms read an
  edit once it is committed, so they answer alike: the reference host's number
  box now commits the way the widget's does, clamped to its bounds, with a
  blank box getting its last value back.
- `inputStates(inputs, values)`, `inputConditionMet(condition, values)` and the
  `InputState` type in `openalgo-charts/widget`, for a host that renders its own
  form; `FormOptions.unavailable` is now asked again after every edit and sync.
- Data variants: regular and extended hours, adjusted and raw prices, and a quote
  currency or unit are each their own provider series, with their own identity.
  `BarsRequest.variant` names one; a feed declares what it serves through the new
  optional `DataFeed.dataVariants`, and a feed without it serves only its default series.
  Nothing is converted or adjusted locally: a variant the provider does not declare is
  reported, never made from another series. New base exports `normalizeDataVariant`,
  `dataVariantKey`, `unsupportedDataVariant`, `dataVariantError` and `publishDataContext`,
  and the types `DataVariant`, `DataSession`, `DataAdjustment`, `DataVariantDimension`,
  `DataVariantCapabilities`, `DataVariantQuery` and `DataContextTarget`.
- `DataLoadingController` asks the declaration before the cache or the network and
  publishes the new status `'unsupported'` with `snapshot.unsupported` (the dimension)
  and a `DataVariantUnsupportedError`, fetching, streaming, refreshing and paging
  nothing. A declaration that fails is an `'error'` that still fetches nothing: paging
  waits and a refresh asks the declaration again. A load with another variant is a new source: the request in flight is
  aborted, the stream released and the bars cleared. Hosts that switch exhaustively
  on `DataLoadingStatus` gain one case.
- `withBarCache` keys each variant as its own series (`invalidate` takes a `variant`) and
  forwards `dataVariants`; `HistoryRequestPool` never shares a request between two
  variants. The default variant adds nothing to a key, so keys and persisted entries
  from before variants still match.
- `ChartDataContext.variant` carries the variant to studies and hosts. Set it with
  `publishDataContext(chart, context)`, which makes a change of variant alone a change
  of source (requested bars aborted, source revisions restarted, studies told) while
  the instrument, its event markers and linked drawings stay. `Instrument.applyTo`
  keeps the context's variant.
- A variant-only change through `publishDataContext` emits `data:context` twice (a
  passing context with the interval cleared, then the real one) until the chart
  compares variants itself; requested studies, Tier 2 studies and the alert controller
  skip the passing one, so nothing is fetched, reported or saved for it.
- Alerts: `AlertScope.variant` records the variant an alert was set on (none for the
  default series, so existing scopes and documents are unchanged). An alert evaluates
  only on its own variant, `availability` asks for it back, a fixed price level is not
  drawn in another currency or unit, and `parseAlertsDocument` refuses a variant it
  cannot name. The widget's alert editor treats a variant change as a context change
  and its list names the variant.
- Requested contexts: `IndicatorBarsRequest.variant`. `createRequestedIndicator` and a
  Tier 2 study's `requestBars` ask for another instrument in the chart's session and
  adjustment (`inheritedDataVariant`, indicators tier) unless the request names a
  variant, and a variant-only change restarts both.
- Widget: the `variant` option, `widget.variant()`, `widget.setDataVariant(variant)` and
  a `variant` event. The variant rides on every load, the data context, `getState`,
  the persisted layout and the saved-view check. A saved state without a variant (every
  state saved on the default series, and every one saved before variants) restores onto
  the default series whatever the widget shows, so its view never lands on other bars.
  The status line names a non-default variant and the data status reads "Not available from this source" with no retry for
  an undeclared one. `WorkspacePane.variant` saves it in portable workspaces, and
  `createChartGrid` saves, reopens and copies it per cell.
- The yfinance reference host has a session menu: regular hours, and extended hours for
  intraday bars of US listed stocks, the source's own pre and post market bars
  (`session=extended`, and `prepost` upstream). Elsewhere the choice is greyed with the
  reason, and a chart already on extended hours that moves to daily bars shows an
  unsupported card with a button back to regular hours. The session is part of the bar
  cache key, the data context, comparisons, replay's finer history, saved layouts and
  named workspaces; fixture mode serves a deterministic extended session. On an
  extended-hours chart the market status reads "Pre-market" or "Post-market", the stale
  badge and the load window follow the 04:00 to 20:00 New York session, and the alert
  menu treats a session change as a change of scope.
- A study's background shading can name a target, the way its drawings and
  markers can since 2.5.4. `background` may return a list of columns, typed as
  `IndicatorBackgroundSpec` (`{ colors, overlay?, plot? }`), instead of one
  colour per bar: `overlay: true` shades the price pane behind the candles and
  binds no axis, and `plot: 'key'` shades that plot's pane, bound to the plot's
  effective scale. Each target is a layer of its own, owned by the instance: it
  follows `setPlotPriceScales`, `setPriceScale` and `moveIndicator` (price-pane
  shading stays on the price pane), hides with the study, is released when a
  pass returns no column for it and goes with the study or its pane. Shading
  stacks after the study's marks and shapes, its own column first and then its
  targets, price pane first; it paints behind every series, so it always sits
  under the candles, plots, marks and shapes. One column per target: a second
  column for the same target, a column without colours, a hole in the list,
  colours mixed with columns, an unknown plot, or `plot` with `overlay: true`
  throw before any shading layer changes. The plain form, and a list whose
  one column names no target, render exactly as before.
- The reference host's Routed signal sample shades the candles by the sign of
  its momentum, with a Momentum shading input that sends the shading to the
  study's own pane or turns it off.

### Changed

- `npm run lint` enforces the deprecation policy: a `@deprecated` tag in `src`
  must name the release that removes the API ("removed in X.Y.Z"), that release
  must be a later major than the package version, and the tag must sit in a doc
  block. Once the package reaches the named release, the tag fails the lint.
  The rule asks the compiler which tags a comment carries, so a tag
  in the middle of a line counts, exactly as it does for the editor's
  strike-through, and a tag's text ends at the next tag on the same line.
- The draw tier reads a click's additive gesture (Shift, Ctrl or Cmd) from
  `modifiers` first, so it keeps working when the deprecated flat flags go.
- **Chrome icons draw a heavier line.** `CHROME_ICON_STROKE`, and with it
  `CHROME_ICON_ATTRS.strokeWidth`, is 2 (it was 1.5), the same 2px line as the
  24px tool glyphs, and the chrome live area is 2 to 14. A 1.5 stroke on whole
  units put every edge three quarters of the way across a pixel, so no edge was
  solid: 0.18 of the tier's inked pixels were solid at 16px, 0.62 now. Every
  host that takes the stroke from `chromeIconSvg` or `CHROME_ICON_ATTRS` gets
  the heavier line. To keep the old weight, pass it explicitly:
  `chromeIconSvg(id, { stroke: 1.5 })`, `stroke-width="1.5"` on your own
  `<svg>`, or `stroke-width: 1.5` in your stylesheet (for the widget,
  `.oac-widget .oac-glyph--chrome > svg`). The glyphs are now drawn for 2 on
  whole units, so at 1.5 they are exactly as soft as before. A host that
  already sets its own chrome stroke keeps it. The dense chrome glyphs are
  redrawn for the heavier line (settings, camera, link, unlink, duplicate,
  eye, eye-off, star, star-filled, magnet), the widget stylesheet and the
  reference host follow the tier's value, and the widget's own glyphs (the
  chart settings tabs, the indicator style tab, the stacking and fit menu
  items) are redrawn for it too: the price tab had filled in solid.
- **Glyph path data changed** for 19 tool ids (`cursor`, `magnet`,
  `trend-line`, `ray`, `extended-line`, `arrow`, `horizontal-ray`,
  `cross-line`, `info-line`, `path`, `polyline`, `price-range`, `date-range`,
  `date-price-range`, `long-position`, `short-position`, `risk-reward-long`,
  `risk-reward-short`, `callout`) and 14 chrome ids (`cursor`, `magnet`,
  `lock`, `unlock`, `eye`, `eye-off`, `star`, `star-filled`, `settings`,
  `paste`, `duplicate`, `link`, `unlink`, `camera`). Each value is still one
  complete glyph, marks included. A host that copies or generates metadata from
  the path strings, or asserts them in a test, must regenerate it from this
  release.
- Look-alike glyphs are drawn apart. Long and short positions are one frame
  split at the entry, the target zone the taller, with an entry tick and the
  direction solid in the target; one is the other turned over. The
  risk-reward pair measures a tall reward span and a short risk span from one
  entry line. The line family differs by its ends: a trend line ends in two
  anchor dots, a ray starts at an origin dot (its tick read as a check mark),
  an extended line carries its dots inside, an arrow and a path end in a head,
  and a polyline marks its vertices. The horizontal ray leaves from an anchor a
  third of the way in. The callout's tail runs back to a distant point, apart
  from the balloon's stub, and paste is a board with lines of content beside
  the trash can. Unlock swings the shackle open, the cursor is a pointer
  rather than a cross beside the cross-line tool and plus, and the magnet has
  pole caps.
- The widget's Undo and Redo chords are listed with the widget's shortcuts
  rather than the drawing ones, since they now reach every step on the chart.
- The OpenAlgo adapters refuse a non-default variant (`OpenAlgoDataFeed.getBars`,
  `OpenAlgoLiveDataFeed.subscribeBars`) with a `DataVariantUnsupportedError` rather than
  answering with the one series they have under another name, and so does the synthetic
  `FakeDataFeed` (`getBars` and `subscribeBars`).

### Deprecated

- `mapOrder` is deprecated in favour of `decodeOrder`, which returns the reason a
  row could not be read, or `OpenAlgoTradeFeed.getOrderBook()`, which sets such
  rows aside as `quarantined`. It keeps working until 3.0.0.
- The `dashed` field that an `IndicatorHost` receives in `addIndicatorLevel` is
  deprecated: read `lineStyle`, which the study always resolves and which also
  carries `'dotted'`. It is still sent until 3.0.0. The `dashed` shorthand a
  descriptor's `levels()` or `addPriceLine` accepts is unchanged and not
  deprecated.
- Depth subscribe frames stop sending the `depth_level` key beside `depth` in
  3.0.0, and the widget message key "Enter a valid expiry date and time in UTC",
  which the widget no longer shows, is removed then. Neither has a declaration
  to tag, so COMPATIBILITY.md lists both.
- The flat `shiftKey`, `ctrlKey` and `metaKey` on a `click` event are
  deprecated: read `modifiers`, which carries the same state and `alt` besides.
  `chart.renderer` is deprecated in favour of `chart.rendererKind`, the same
  value. Both keep working until 3.0.0, and their declarations carry the tag,
  so an editor strikes them through.
- `chart.movePriceAxis(pane, from, to)` is deprecated in favour of
  `chart.setPriceAxisPlacement(pane, scaleId, side)` (since 2.5.4), which moves
  a scale's column and keeps its id, where the old method swaps the built-in
  side scales and reassigns their series and studies. `movable` in
  `priceAxisState()` describes only that old method and goes with it, and so
  does the `priceAxisMoved` event, which only that method emits: listen for
  `priceAxisPlacementChanged`. The widget and the reference host already use
  placement. All three keep working until 3.0.0.
- The chart's own study host no longer reads the deprecated `dashed` it is
  handed for a study level; it draws from `lineStyle`, which the study always
  resolves, so every level looks exactly as before.
- COMPATIBILITY.md now has a table of every deprecated API with its
  replacement, the release that replacement arrived in and the release that
  removes the old form, and a list of older forms that are kept on purpose (the
  `dashed` and `magnet: true` shorthands, the IST helpers, a study `levels` hook
  written against the settings-only form, the `topic` field on an inbound
  market-data frame, and the readers of older saved documents). The one-id
  `draw:*` events beside `drawing:select` and `drawing:change` are listed as not
  decided yet; they are settled with a typed event map.

### Fixed

- A chart follows a change of device pixel ratio: the window moved to a screen
  of another density, or a zoom that leaves the container's CSS size alone.
  Before, nothing re-sized the canvases, so the whole chart stayed at the old
  ratio, stretched and blurred, until something changed the container's size.
  The chart now watches a `(resolution: Xdppx)` query, made again for each new
  ratio, and the window's `resize` as well, which a zoom fires and which is the
  one signal left in a browser whose query list takes no change listener.
- Pane boundaries now land on whole device pixels, at every ratio, so each
  canvas covers a whole number of device pixels and the browser no longer
  stretches a lower pane by a fraction of a pixel. Three panes in 344 px at
  1 : 0.32 : 0.32 were 209.76 px and 67.12 px tall, boundaries inside a device
  pixel at every ratio; they are now rounded where they meet, within half a
  device pixel of their share, and the outer edge stays where the container
  puts it. At a ratio of 1 a pane's height can therefore differ from its exact
  share by up to one pixel; weights are untouched. A chart whose panes already
  share the height in whole pixels is laid out and painted exactly as before.
  Hit testing and `priceToCoordinate` round at the ratio the panes were laid
  out at, so they stay on the boxes on screen even when the ratio moves with
  nothing to say so.
- At a fractional ratio the separator between panes is a box one device pixel
  tall laid over the top of the lower pane, where it was a 1 px CSS border. At
  1.25 and 1.5 that border was 1.25 or 1.5 device pixels, so the canvases
  under it started part way into a pixel and the browser resampled the whole
  pane and blended the rule into it. There the lower pane's canvases now start
  at the pane's top and the rule covers their first row, so a pointer maps to
  the canvas pixel it is over. At a whole-number ratio (1, 2, 3) the separator
  is the 1 px border it always was, the canvases under it and pane-local
  coordinates where they were: a border is whole device pixels there. The
  separator changes form when the ratio does. `setTheme` recolours it, which
  the border kept in the previous theme's colour until the next resize.
- `exportSVG` lays its panes out at a ratio of 1, the ratio the document is at,
  whatever the screen's: the same chart exports the same document on a 1x,
  1.5x or 2x screen, with the separator as the 1 px border the screen draws at
  1.
- Where the browser reports a canvas's device-pixel box
  (`devicePixelContentBoxSize`, Chromium and Firefox), the canvas's backing
  store takes that size, so a chart that starts part way into a pixel is not
  stretched by one. A report more than a pixel away from media times ratio is
  refused, which is what an emulated device scale reports. The box is kept
  through a resize of less than a pixel that leaves it as it was, which the
  browser does not report again.
- No blank frame while the chart is resized. Resizing a canvas clears it, and
  the size arrives in a ResizeObserver callback, after the frame's animation
  callbacks and before the browser paints, so the repaint waited a frame and
  every step of a window drag showed one cleared frame. The chart now paints
  in that callback, on a new ratio, and in the one re-measure a frame after
  construction, which ran inside an animation callback and had the same gap.
  A host that supplies its own `raf` scheduler keeps every frame, these
  included, on it.
- Ichimoku Cloud reads its three periods and its displacement as whole bars,
  the way the other built-in studies read a length. A fractional period (a
  conversion period of 9.4, say, from a saved layout or a host's own settings
  UI) made the calculation throw a TypeError, and a fractional displacement
  blanked both spans and the lagging span. Each is now rounded to the nearest
  whole bar, and a period below one reads as one, the declared minimum, where
  it used to print nothing. Whole values compute exactly as before.
- Times past the last bar no longer take their spacing from the gap between
  the last two bars. That gap is the one most likely to be a night or a
  weekend: on a five-minute chart whose last candle was Monday's 09:15 open,
  every bar of empty space to its right stood for almost three days, so a
  trend line drawn three bars past it ended more than eight days later.
  `DataLayer.indexToTimeFloat` and `timeToIndexFloat` (and so
  `chart.coordinateToTime`, `chart.timeToCoordinate`, drawing placement, study
  shapes past the last bar and linked viewports) now continue at the median of
  the last 64 bar intervals. Left of the first bar nothing changes. Evenly
  spaced data maps exactly as before, and stored drawings keep their times: an
  anchor saved at a future time is simply drawn where that time now falls.
- With a session calendar the space past the last bar follows the venue's
  hours. The bar after Friday's 15:25 candle is Monday's 09:15, so a saved
  anchor at Monday 09:30 is drawn four bars past the last candle rather than
  about 800 five-minute bars off screen in the night and weekend. A date the
  calendar closes is skipped, a shortened day ends early and a lunch break is
  stepped over. Each window keeps the offset the feed's bars keep from its
  opening, read from the bars in windows opening at the same time: hourly bars
  stamped on the clock stay on the clock both at a 09:00 morning opening and
  at 12:00 before a 12:30 afternoon one, and a feed that stamps its first
  hourly bar 09:00 against a 09:15 open keeps doing so. Daily bars step through
  trading dates. Positions between two future bar times interpolate across the
  closed hours and convert back exactly. A calendar the recent bars do not sit
  in (regular hours against extended-hours data) is ignored in favour of the
  median, and a calendar that throws never stops a chart painting. Generation
  is bounded: past 4096 future bars or 512 calendar reads the axis continues
  at the average pace already generated.
- `long-position` and `short-position` were one picture (the same subpaths in
  another order), and the duplicate check compared path strings, so it passed.
  It now compares drawings: subpaths walked to absolute coordinates, sorted,
  and read from a fixed end, curves and arcs included. `lock` and `unlock`
  overlapped by more than 99 percent at 16px, and the chrome `cursor` and
  `plus` by 92 percent.
- The corner logo no longer takes a press meant for something over it. A note
  pinned to the screen in the corner, a drawing crossing the mark or an order line
  gets the press, the drag, the hover and the double click, and the logo's link
  opens only where nothing else answers the pointer.
- The yfinance reference host's chart state card hid its Dismiss button in the markup
  only: the button style overrode the hidden attribute, so an empty chart showed it too.
- A settings change whose pass fails keeps the study's last good candle
  colours, as the documented pass order says. The chart restacks every study
  after a settings change, and that restack ran the `barColors` hook again on
  the failed pass: it published the colours of a pass rejected at a drawing,
  marker or shading target, and when `calc` itself had thrown, a hook reading
  one of its columns threw out of `setSettings` instead of leaving the error
  status. Moving or reordering a study whose last pass failed keeps them too.

### Documentation

- README and ARCHITECTURE.md now describe the engine as it is: two canvases per
  pane with the axes painted on the base canvas, a data write (a study
  recompute or a live tick) repainting every pane, a time-scale operation queue
  that nothing fills, kinetic scroll and eased zoom on their own frame loops,
  conflation applied to every series in a pane, per-bar candle colours, a
  marker pass that walks every marker, and `mergeRange` not implemented.
- The unmeasured "60 fps" and "50k+ bars" claims are replaced by a recorded
  measurement from `scripts/browser-endurance.mjs` at 2,000, 10,000 and 50,000
  bars per chart (frame-interval p95 17 ms, 134 ms and 717 ms on the recorded
  machine), with its workload and machine in `docs/browser-endurance.md`. The
  README states the large-history cost as a known limit.
- The README limitation that a pane had one shared comparison scale is removed:
  each comparison has had a scale of its own since independent comparison
  scales shipped.
- ARCHITECTURE.md places order and position lines on the base canvas, where a
  drag repaints them, and lists what the overlay canvas really carries. The
  README says the same, and names the widget tier among the places that build
  SVG icon markup.
- No document calls the WebGL2 backend faster than Canvas2D any more: that has
  not been measured. The documents say what the backend does instead.
- `docs/performance-notes.md` records two findings for the render benchmark:
  markers map the whole history on every paint, and the endurance harness's
  painted-chart hash includes the price-axis strip.
- `tests/docs-claims.test.ts` ties these statements to the code: a frame rate,
  percentile, duration or bar-count workload in README or ARCHITECTURE.md must
  cite its measurement record (a frame figure, the browser harness), GPU speed
  wording needs a record that measures the GPU backend, the canvas count, the
  overlay contents, the SVG tiers and the shared index must match the code, and
  the repaint scope a document states must match what the chart does.

### Internal

- The indicator tier's warmup-gap alignment and its Smoothing block are
  written once, in an internal module the tier does not export, instead of as
  private copies spread across the study modules: five of the gapped EMA, four
  of the Smoothing kernel switch (the moving-average ribbon's among them), four
  of the first-value alignment (one written inline in ADX) and three of the
  Smoothing option list. The canvas
  colour helpers and the widget's tokens share one luminance calculation, each
  still reading colours through its own parser, because the two parsers
  disagree on malformed input and merging them would move a colour. The
  widget still declares its own `Rgba`, so its declaration and reference page
  are unchanged. The merge moved no output: all 105 built-in studies over 16
  synthetic datasets and 31,312 setting combinations, their declared inputs
  and options, and 12,037 colour probes across both parsers give bit-identical
  results before and after it, from source and from the built bundles (the
  Ichimoku fix above is the only change in study output).
  `tests/shared-helpers.test.ts` checks the merged helpers bitwise against
  independent copies of the ones they replaced, and fails if a private copy
  comes back, by name or as the alignment pattern under another name.
- The two public `withAlpha` functions share a name, not a behaviour, and stay
  separate on purpose; their declarations now say so. The base package's
  writes `rgba()` with the alpha as given, for canvas, and the widget's writes
  `#rrggbb` for an opaque colour and clamps and rounds the alpha, for a token
  value.
- `npm run test:script-engine` draws a compiled study with two grids and a band
  whose colour the script computes per bar, built with
  `descriptorFor(program, { id, chartVersion: VERSION })`, on a real chart, and
  checks both grids and each run of the band's colour. Against an engine older
  than 0.8.0, whose adapter refuses such a study, the case is skipped with a
  note saying so; the engine's version is read from its own `package.json`.

Saved layouts, drawings and workspace documents from 2.5.5 load unchanged. A
study or drawing without a policy behaves as before, a chart without a session
calendar spaces the future by its recent bars, and at a whole-number pixel ratio
the device-pixel work lays panes and separators out exactly as 2.5.5 did when pane
heights are whole pixels. Deprecated forms keep working until 3.0.0. No runtime dependencies or package tiers were
added.

Sizes, measured on this release and against 2.5.5 (Brotli, decimal kB): base
engine 119.15 to 125.39, base plus trade 135.79 to 142.07, the trade tier alone
16.64 to 16.69, indicators 36.34 to 36.44, draw 44.87 to 48.42, widget 82.30 to
92.72, workspace 9.99 to 10.47, widget terminal 282.67 to 302.96 and every tier
together 335.15 to 355.97. The chart-only import grows from 75.07 to 79.25 KiB:
study policies, one draw order, device-pixel layout, resize paints, the session
calendar and the layout event belong to every chart, and the undo history,
panels and forms stay in the widget. Each budget is the smallest two-decimal
value that passes.

## 2.5.5

2026-09-26

### Added

- The price pane can move below its studies, on a chart that opts in with the
  new `movablePrimaryPane` option. Moving it is opt-in in both the chart and
  the widget: `createChart`, `createWidget` and `createChartGrid` all leave the
  option off, and for a host that does not opt in nothing about the price pane
  changes. It stays at slot 0 exactly as in 2.5.4: `movePane` refuses to move
  or displace it (so the up control on the first study pane still does
  nothing), `setPrimaryPaneIndex` returns false, `restoreState` refuses a
  layout that moved it, and an explicit pane 0 still means the price. It is
  opt-in because a host that passes an explicit 0 to mean the price pane (a
  price or order line, `coordinateToPrice(y, 0)` pricing a right-click order,
  a price alert check, `panes()[0]`) would otherwise read a study's units,
  order prices included, the moment a user moved a study above the candles.
  Before turning it on, drop those zeros or ask `chart.primaryPaneIndex()`, and
  follow `paneMoved`; read the option back with `chart.movablePrimaryPane()`.
- With the option on, the price pane is an identity rather than slot 0:
  `chart.primaryPaneIndex()` reads the slot it holds, and
  `chart.setPrimaryPaneIndex(index)` moves it there one `movePane` step at a
  time, one `paneMoved` event per step. `movePane` moves the price pane like any
  other pane, and a study pane can displace it. Everything that meant "the price
  pane" follows it: `addSeries`, `addPriceLine`, `addEventMarkers`, `setEvents`,
  `addPrimitive` and `tradeHost` with no pane; `priceToCoordinate`,
  `coordinateToPrice`, `priceAxisState` and `priceAxisLayout` with no pane;
  `priceScaleOptions()`; on-chart studies and every `overlay` plot, band, table,
  price-anchored mark and the instrument tick a study's `calc` sees;
  comparisons, whose handle `paneIndex` now follows its pane; price alerts and
  drawing alerts; the drawing magnet; drawing copy and paste; a drawing link
  between charts that keep their price panes in different slots; the magnet
  crosshair, a scale-targeted pick and the `panUp` / `panDown` keys. The legend
  offset, the study count and the background text sit on the price pane (the
  new primitive anchor `'primary-pane'`); the time navigator and the brand mark
  stay on the bottom open pane. The price pane is never removed and never
  collapses, in any slot, so a chart always keeps one open pane; a study pane
  moved above it folds, maximizes, prunes and carries its pane controls like
  any other.
- A moved price pane is saved. `getState()` writes version 2 with `primaryPane`
  only when the price pane is not on top, and writes every other layout as
  version 1, unchanged, so an older reader still opens it and refuses a moved
  one rather than laying the price pane's settings on a study pane.
  `CHART_STATE_VERSION` is now 2. A layout without `primaryPane` restores with
  the price pane on top; a slot that names no saved pane, a `primaryPane` in a
  version 1 state, and a moved slot on a chart without the option are refused
  before anything is applied. Workspace documents accept a version 2 chart and
  refuse `primaryPane` on version 1. Portable templates are written price pane
  first, so they apply the same way whichever slot the price pane holds;
  `planIndicatorTemplateState` keeps the destination's price pane in place and
  returns `primaryPane` for the restore, and `planIndicatorTemplate` takes the
  destination's price-pane slot as an optional sixth argument.
- `createWidget` and `createChartGrid` take the option and hand it to their
  charts as given, off unless the host passes `movablePrimaryPane: true`. Only
  the host knows whether its own code on `widget.chart` still passes 0 for the
  price, such as a volume histogram added with `paneIndex: 0`, so the widget
  does not decide for it. The widget's right-click menu moves the pane under
  the pointer up or down (`pane-up`, `pane-down`): study panes on every widget,
  and the price pane as well on a widget that opted in. A row that has nowhere
  to go is greyed, and so is a row that a pinned price pane refuses, with the
  note "price pane stays on top". The Objects panel names the price pane in its
  pane headings and its move targets wherever it sits
  (`ChartObjects.primaryPaneIndex()`). The reference host opts in on both charts
  of its main page and in its grid view, so a layout either one saves opens in
  the other, and it offers the same rows on both right-click menus. The widget
  and the reference host keep the collapse row off the price pane in every slot
  and forward the price-pane slot when applying a template.
- Price-dependent tick schedules. `TickSchedule` validates an ordered list of
  `TickBand`s: the first band covers every lower price, zero and negative prices
  included, each later band starts at its inclusive `from`, and every boundary must
  be a multiple of the ticks on both sides, so a boundary is itself a valid price.
  Invalid bands throw `Invalid tick schedule: ...` naming the band. `round` returns
  the nearest valid price as an exact decimal (a written halfway price rounds up),
  `tickAt` gives the upper band's tick at an exact boundary, `step` moves whole ticks
  across boundaries, and `minMove` is the common grid of every band.
  `InstrumentMetadata.tickBands` carries a host-supplied schedule; `priceTick` must
  then equal its `minMove`, which `applyTo` gives the price scale, and
  `instrument.tickSchedule` is the validated schedule (null for a constant tick, which
  keeps its one `priceTick` rule). `OrderConstraints.tickSchedule` makes
  `validatePrice`, `OrderEngine.placeOrder` and `OrderEngine.requestModify` snap each
  price in its own band before checking price limits, and
  `orderConstraintsForInstrument` fills it from `tickBands`.
  `chart.trading.setTickSchedule` snaps dragged order and bracket lines and the
  `newPrice` their modify events carry; it refuses anything but a `TickSchedule` or
  null. `applyTo` hands the trading layer the instrument's schedule, including a layer
  built later, and a constant-tick instrument clears the previous one on a symbol
  switch. `DomLadder` takes a `tickSchedule` option and `buildRows` a schedule in place
  of the tick size, so a ladder across a boundary shows the prices each band allows
  and groups whole ticks of that band (a fractional `groupBy` rounds down). Without a
  schedule every path is unchanged: constant `tickSize` snapping and ladder rows, the
  same constraints object for a constant-tick instrument, and raw pointer prices from
  `chart.trading`. No venue's schedule ships as a default. The reference host's
  fixture server adds a synthetic `BANDED` instrument (0.01 below 100, 0.05 from 100),
  described as instrument metadata, whose right-click orders, dragged order lines,
  market fills and bracket legs snap in the band they land in.
- Drawings pinned to the screen. A drawing's `space` is `'data'` (time and price,
  the default, never written out) or `'viewport'`, whose anchors are
  `viewportPoints`: `{ x, y }` fractions of the plot of the pane that holds the
  drawing, from its left edge to its right edge and from the top of the pane to
  the bottom of its plot. Pan and zoom leave a pinned drawing where it is, a chart
  resize keeps it in proportion, and it paints and hit-tests at any device pixel
  ratio. It is edited natively (body drag, handle drag, nudge, undo) and follows
  its pane through a move, a separator drag and a collapse. Its whole box, not only
  its anchors, is kept on the plot at every edge, through every gesture, at any
  device pixel ratio and after a resize, so a note or a table laid out from one
  corner, or a box or an ellipse with its label above it, can always be seen and
  grabbed; a custom tool that paints beyond its anchors declares the new
  `DrawingTool.bounds`. Pinning a drawing that is off the
  plot, or larger than it, brings it onto the plot, and the magnet does not pull
  while a pinned drawing is placed. Text, rectangle, ellipse and table declare the
  new `DrawingTool.viewport` flag; tools that print prices, point at a bar or
  compute from bars stay in data space. `draw.update(id, { space })` converts at
  the view on screen as one undo step, `setTool(id, { space: 'viewport' })`
  places a pinned drawing, `activeToolSpace()` reports the armed space and
  `screenPoints(id)` gives any drawing's anchors in container px for host
  overlays. `update` returns false when a change of space cannot be made (a pane
  folded or hidden), and the widget's Anchor row and the reference host's pin
  toggle say why. `draw:tool` carries
  `space: 'viewport'` while a tool is armed for the viewport. The settings schema offers the choice as `SPACE_FIELD` over
  `SPACE_OPTIONS`, so the widget's drawing properties show an Anchor row and the
  reference host's properties bar a pin toggle, both only for those four tools;
  the widget and reference host text editors open over a pinned note. Saves stay
  version 2 and a layout with no pinned drawing is byte for byte unchanged; the
  clipboard carries the fractions, so a paste lands at the same place on a chart
  of any size. Drawing links never share a pinned drawing, and pinning a shared
  one takes it out of the link on that chart only; undoing the pin joins it
  again. New types: `DrawingSpace`,
  `ViewportPoint`, `DrawingPlacementOptions`.
- Named watchlists. `WatchlistRepository` in `openalgo-charts/workspace` keeps named
  symbol lists keyed by the exact symbol and exchange pair, so one ticker on two
  venues is two entries and nothing is case-folded. Lists are created, renamed,
  duplicated, removed and reordered through queued, revision-checked writes: each
  change applies to the catalog as stored, a position-based change can name the
  revision it was computed from, and a write that loses a race across tabs raises
  `WatchlistConflictError` without replacing anything. `createIndexedDbWatchlistStorage`
  commits in one IndexedDB transaction, `createMemoryWatchlistStorage` serves tests
  and previews, and corrupt storage is reported rather than overwritten. The panel
  takes the narrower `WatchlistStore` contract (the repository without
  `duplicateList`), which a server-backed store can implement directly.
- Optional quote and news contracts beside `DataFeed`: `QuoteFeed` (snapshots and
  per-instrument streams with `connecting`, `live`, `reconnecting` and `disconnected`
  states) and `NewsFeed` (cursor pages of plain-text items). They are types only in
  the base entry. A quote comes only from a `QuoteFeed`, never from a bar's close.
- Watchlist and News panels in the widget's panel dock, beside Data and Objects, with
  top bar and mobile More entries, shown only when the host supplies `watchlist` or
  `news`. Watchlist rows update live, subscribe only while on screen, and release
  their streams on a list switch, a hidden page, closing the panel and `destroy`.
  Sorting by symbol, last, change or percent change is stable, sinks unknown values,
  holds row order while the pointer or focus is on the rows and outlives a panel
  switch. Alt+Arrow moves save one at a time. Quotes held through a reconnect, or past
  `staleAfterMs` for a snapshot-only source, are shown as stale, with one timer for
  the next row to age and none once nothing can, and a reconnect refetches snapshots.
  In the widget a row names the upper-cased instrument `setSymbol` charts, through the
  panel's `normalize` option. The news reader follows the chart instrument,
  pages older items by the provider cursor, drops repeats, reports empty, error and
  stale states, cancels on a switch, and opens only http and https links with
  `noopener` and `noreferrer`; provider text is never rendered as markup. The
  DOM-free `QuoteBoard` and `NewsReader`, `mountWatchlistPanel`, `mountNewsPanel`,
  `safeNewsUrl` and `quoteChange` are exported for custom hosts, and
  `widget.openWatchlist()` and `widget.openNews()` open the panels.
- The yfinance reference host shows both panels in its dock and in every chart of its
  grid view, with lists in IndexedDB and the watchlist sort in `localStorage`.
  Its server's `--fixture` mode answers `/api/quotes` and `/api/news`
  deterministically, including an unknown instrument, a markup headline and a script
  link for the reader to refuse; without `--fixture` both answer 501, since the
  server has no live quote or news source, and the page asks for quotes once.
- Account state in the trade tier. `AccountManager` lists a provider's accounts
  for one mode, loads the selected account's balance, equity, margin used and
  available, P&L and leverage, follows its stream, and reads its positions,
  executions and order history, dropping and counting rows that name another
  account (a position names one through the new optional `Position.accountId`
  when the provider stamps it). Switching accounts aborts the old account's
  requests and stream, so a late answer is never shown under the new name; a
  pushed reading older than the one on screen, a snapshot from the other
  ledger, and a non-finite figure are all refused. A dropped connection keeps
  the last figures marked stale until `reconnect()`. It never writes.
- Declared newer operations. `TradingFeatures` (`accounts`, `executions`,
  `orderHistory`, `preview`, `durations`, `leverage`, `close`, `partialClose`,
  `reverse`, `brackets`) on `OrderFeed.features`, checked with
  `checkTradingFeature`. Unlike the place, modify and cancel flags, an omitted
  feature is unsupported, and every refusal names the feature.
- `PlaceRequest.account`, `duration` (`DAY`, `IOC`, `FOK`, `GTC`, `GTD`),
  `expiresAt` and `leverage`, checked before and after confirmation and never
  dropped on the way to the wire. With `selectedAccount`, the engine stamps the
  selected account on each order, refuses one naming another account, and
  sends nothing when the account changes while the user is confirming; an order
  already in flight keeps its account. Given the account view itself
  (`selectedAccount: accounts`), it also refuses a selection from the other
  ledger, so a sandbox engine never stamps a live account on an order.
- `OrderEngine.previewOrder`: the provider's estimated value, margin and
  refusal reason for an order, without claiming its token or placing it.
- Provider-native `closePosition` (whole or partial), `reversePosition` and
  `placeBracket`, each with its own idempotency token, its own feature and
  `confirmCommand` approval when not armed. An opposite order is never sent in
  place of a close. A close or reverse without a known outcome holds the
  position against another, whether or not either names the exchange;
  `onBrokerOrder` settles a write whose answer was lost through the client
  token the broker echoes, `releaseAmbiguous` frees one the host has shown
  never arrived, and a feed error marked `rejected: true` (`isBrokerRejection`)
  settles as the broker's refusal. A bracket gives each
  leg its own client token (`legClientTokens`), and `onBrokerOrder` adopts a
  leg by that token or by its entry and role (`parentId`, `role`), so a bracket
  whose answer was lost still has legs that can be cancelled and filled. A leg
  that names an entry not yet bound (a history listed newest first, or legs
  streamed before the entry's id comes back) is held until the entry binds, so
  the broker's rows can arrive in any order.
- `FakeBroker({ accounts })` simulates all of it: per-account ledgers filled at
  a mark price, preview, `IOC`/`FOK` cancellation, `GTD` expiry, leverage
  limits, native close, reverse and linked bracket legs, server-side refusals
  (including a cancel or modify of an order that has already filled), and
  hooks to hold, fail or lose any answer and drop the connection. A call
  made while the connection is down fails as never sent (a pre-flight
  failure), so the engine blocks it rather than holding it ambiguous; one
  already out when it drops fails like a lost answer. Without `accounts` it
  is otherwise unchanged and declares none of it.
- Widget account summary. The `account` option shows the selected account,
  an Analyzer tag for the sandbox ledger, equity and margin in the status line,
  with a menu to switch; a source whose provider declares no accounts renders
  disabled with the reason. `mountAccountSummary` and `ACCOUNT_SUMMARY_CSS`
  are exported for custom hosts.
- The reference host's Account button opens a sandbox broker panel: account
  switching, preview-gated placement with durations and leverage, native close,
  partial close, reverse and brackets, executions, and a dropped connection
  whose Reconnect settles every write the panel sent from the order history of
  every account it has written to, as the sandbox example on the examples page
  does, so the legs of a filled bracket stay live across any number of
  reconnects.

### Changed

- `CHART_STATE_VERSION` is 2, but `getState()` still writes 1 for a chart whose
  price pane is on top. A host that checks a saved state against the constant
  should refuse only a newer version (`version > CHART_STATE_VERSION`), as
  `restoreState` does, not demand equality.
- Drawings on the clipboard count their pane with the price pane first and the
  study panes after it in order. On a chart that keeps its price pane on top,
  which is every chart without the option, that is the slot it always was.
- `OpenAlgoTradeFeed.place` refuses `account`, `duration`, `expiresAt` and
  `leverage` before any network call: OpenAlgo's placeorder has no such fields
  and one key is one account.

### Fixed

- A restore now hands the drawing tier its drawings before it prunes the study
  panes it emptied, so a drawing kept through a template swap shifts with the
  panes instead of recreating a pane at its old slot. The saved drawings a
  draw tier reads when it loads later are shifted the same way, by every pane
  removal or move before it arrives. A drawing on a study pane that the restore
  prunes (the pane of a study not registered where the layout opens, say) is
  dropped with that pane, where 2.5.4 recreated an empty pane at its old slot
  to hold it. This applies whether or not the host opted in.
- The widget's right-click menu offered Buy and Sell limit and stop rows over a
  study pane, priced from that pane's scale: an RSI reading of 58.75 became a
  limit price. A study pane now offers the market rows only.
- `onBrokerUpdate` on a row the client had written off as `AMBIGUOUS` (a lost
  answer reads `rejected`, a row a reconnect snapshot missed reads `stale`) now
  takes the broker's status. An order the broker reports working is live
  again, so it can be modified and cancelled, and it is no longer pruned as if
  it had settled. A row the broker reports as pending counts as accepted.

### Calculations

- ATR treats a missing or overflowing true range as a gap. It seeds from the
  first `period` consecutive finite true ranges, keeps its average across a gap
  and resumes from it. A missing high or low now costs the ATR its own bar, and
  a missing close the next bar, whose true range reads it, instead of every
  later bar. A running overflow stays unavailable rather than restarting.
  Finite results on complete data are unchanged bit for bit, as is the public
  signature, which keeps the parity with the OpenAlgo atr function. Keltner
  Channels, Chandelier Exit, Chande Kroll Stop, Median, HalfTrend and
  Volatility Stop inherit the correction. Volatility Stop no longer falls back
  to the unmultiplied true range for the rest of the history after one gap,
  though a bar with no true range still restarts its stop at the source, as its
  reference definition does.
- `supertrend` and the Supertrend study leave a bar with no ATR or no close
  absent, with the bands, the direction and the last accepted close unchanged.
  A missing close has a finite ATR on its own bar, and comparing it as NaN
  always flipped the trend; with the ATR now resuming, the flipped bands would
  have carried into every later bar. The band step reads the last accepted
  close, so a skipped bar's close cannot reset a band either.
- VWAP leaves a bar with a missing price, or a NaN or infinite volume, absent and
  its running totals untouched. One such bar no longer blanks the line and all
  six bands until the next anchor restart, which on the continuous anchor was
  never. An undefined volume still counts as nothing traded, and an anchor
  restart on a missing bar still happens.
- TWAP skips a missing or nonfinite price and divides by the bars it counted, so
  a gap costs its own reading rather than the rest of the session.
- On-Balance Volume and Accumulation/Distribution read a NaN or infinite volume
  as nothing traded, as the money-flow studies already did, instead of losing
  the running total for the rest of the history. OBV's VWMA smoothing weights
  with the same volume.
- Accumulation/Distribution leaves a bar missing its high, low or close, or
  whose span or term overflows, absent with the total unchanged. A missing
  close with a finite range blanked the line for the rest of the history, and a
  missing high or low passed for a doji and printed the carried total.
- Parabolic SAR steps over a bar missing its high, low or close and leaves the
  stop, trend and acceleration as they were. It seeds from the first two
  complete bars and clamps against the two complete bars before each step. The
  clamp and reversal conventions are unchanged.
- TEMA adds `3 * ema1 - 3 * ema2 + ema3` left to right instead of regrouping it
  as `3 * (ema1 - ema2) + ema3`. Readings change only in their last digits, and a
  bar whose terms overflow is absent rather than finite by cancellation.
- CCI has no reading on a window that holds a missing high, low or close, or
  whose mean deviation overflows. It used to print 0 there for a whole window's
  worth of bars, and the CCI-based average and its bands smoothed those invented
  zeros. A genuinely flat window still reads 0.
- Stochastic %K multiplies by 100 before dividing by the window range, the order
  the definition fixes, so a reading can move in its last bit and %D follows. A
  window whose range overflows has no reading instead of a flat 0, and neither
  does one whose scaled distance overflows (above about 1.8e306).
- Fisher Transform restarts both recursions on the bar after a missing midpoint,
  as its documented rule says. The missing value used to enter the recursion and
  leave the study blank for the rest of the history.
- Relative Volatility Index and Mass Index hold their exponential averages across
  a missing bar and resume on the next present one, instead of reseeding and
  blanking the study for another 14 (RVI) or 9 (Mass Index) bars. The RVI's EMA
  smoothing option follows the same rule. Inside the RVI's deviation warmup its
  averages still restart as before, so complete data reads exactly as in 2.5.4
  at every Length.
- NVI and PVI hold their index across a missing close, as they already did after
  a zero previous close, instead of losing the index and its average for the
  rest of the history. Complete data is unchanged.
- True Strength Index, SMI Ergodic Indicator and SMI Ergodic Oscillator multiply
  the smoothed change by 100 before dividing, which can move readings in the last
  bit. Above about 1.8e306 that product overflows and the bar is a gap, as in the
  companion scripting language, where the former order still printed a reading.
- Trend Strength Index and the exported `correlation` helper finish both window
  means before forming any deviation, taking two passes oldest first. The former
  single-pass sums cancelled at ordinary price levels: at 1e5 with 0.01 moves the
  reading was about one percent off, and at 1e9 it had no value.
- On a window of identical closes, Trend Strength Index and `correlation` read
  what the arithmetic gives, as the companion scripting language does, so
  availability there can differ from 2.5.4 in either direction. The window has
  no reading when its deviations are all exactly zero, which happens when the
  mean comes out exact: fourteen bars of 5, or of 0.1, where 2.5.4 printed
  -1.2e-8. When the mean is inexact, as for three bars of 0.1 or fourteen of
  2.01, the deviations are a few units in the last place and Trend Strength
  reads exactly 0, where 2.5.4 printed nothing or its own residue (2.8e-8 for
  fourteen bars of 2.01). Against a second series other than the bar index,
  `correlation` reads within rounding of 0 there.

On complete data ATR and the studies built on it, Supertrend, VWAP, TWAP,
OBV, Accumulation/Distribution, Parabolic SAR, CCI, Fisher Transform, RVI,
Mass Index, NVI and PVI read exactly as in 2.5.4. TEMA, Stochastic, True
Strength Index and the SMI Ergodic pair can move in their last digit, and Trend
Strength Index and `correlation` move where the former single pass cancelled.
No public signature changed.

### Documentation

- The indicators page has a Numerical contract section: the thirteen documented
  differences from the companion scripting language (missing observations in
  extremes, missing volume, flat CCI windows, first-bar conventions, host
  logarithms, units, the Aroon Oscillator, Parabolic SAR, overflow, signed zero,
  Klinger, the RVI warmup and the PVO signal after a stretch with no volume),
  and how each built-in treats a NaN volume.

Saved layouts, drawings and workspace documents from 2.5.4 load unchanged.
Moving the price pane is off unless a host opts in with `movablePrimaryPane`,
and a host that does not opt in sees no change to pane 0. The quote, news,
account and tick-schedule contracts are optional: a feed or broker that does
not declare them keeps working as before. No runtime dependencies or package
tiers were added.

## 2.5.4

2026-09-25

### Added

- Go to a date or an explicit range. `widget.goTo({ from, to? })` loads the older
  history the request needs through the widget's feed, then places it after that
  load, so later live bars and refreshes keep the view. Daily and longer bars are
  matched by calendar day in the chart timezone, weekend and overnight dates move
  to the next session, and a range with no bars is reported without moving the
  view. Results distinguish exhausted history, empty pages, retention limits,
  replay and unsupported intervals; a newer request, a context change or
  destruction cancels one in flight. The DOM-free `DateNavigator`, the
  `openDateNavigation` panel and `DATE_NAVIGATION_CSS` are exported for custom
  hosts. The widget toolbar and mobile More sheet open the panel (greyed with the
  reason on tick and volume intervals, and with date fields alone on daily and
  longer ones); closing it while it loads cancels the request, and so does a pan
  or zoom while older history loads (the widget's own move that holds the view
  through a refresh does not count). The panel closes when the interval or the
  chart timezone changes under it. Daily and weekly bars end on the calendar, so
  a day of 23 or 25 hours keeps its own bar, and a date names the bar the axis
  labels with it, including a UTC-midnight daily bar west of UTC. The reference
  host offers the panel by loading a longer period, reopens it on the rebuilt
  chart to report the outcome there, and drops the request on a pan or zoom
  while that period loads.
- `DataLoadingController.loadMore(until?)` widens a date feed's window to reach
  `until` in one request instead of one request per default window. The window
  stops at `maxBars` bars of a fixed interval, and a `getBarsPage` feed keeps its
  ordinary window.
- A lower pane collapses to a header strip and opens again at exactly the height
  it had, through `chart.setPaneCollapsed(index, collapsed)`,
  `chart.paneCollapsed(index)`, a collapse button on the pane's first study row
  (open or folded, whichever study that is) and the `paneCollapsed` event. A
  collapsed pane keeps its data, studies, drawings, scales and weight, and draws
  and hit-tests only one legend row, its first study row, which leads the strip
  above any row the host placed there, so no drawing, price alert or pick lands on
  it; `priceToCoordinate` and `coordinateToPrice` return `null` for it, while
  alerts on its studies and drawings keep firing. Pane 0 stays open, the time axis
  stays at the foot of the chart under a collapsed bottom pane, maximize shows a
  collapsed pane whole, and `collapsed` is saved in pane state and workspace
  documents. A restore that lists panes or rebuilds studies opens every pane its
  layout does not fold, so a study never lands in a stale strip. The widget and
  the reference host, including its split chart, offer the control in their
  right-click menus. This is separate from collapsing study legend rows; with both
  on, a strip keeps its first study row and the control that opens it.
- Study drawings and markers can name where they go. `overlay: true` sends a
  shape to the price pane, measured on the scale that pane quotes prices on
  (the candles' own, on whichever axis they sit), or anchors a marker to the
  candles, even from a study in its own pane; neither holds an axis, so the
  price axis stays free to move. `plot: key` draws a shape on that plot's pane
  and scale, or anchors a marker to that plot's series, which falls back to
  the candle where the plot has no value exactly when that plot is on the
  price pane and the candles' scale, whichever plot it is. Each target is its
  own layer that follows scale reassignment and study moves, hides with the
  study, reports hits where it is drawn, and is released when no longer
  returned or when the study or its pane goes. Marks sent to the series the
  study's own marks already use join that layer, so marks at one bar stack,
  except marks naming an overlay first plot of a study in its own pane. A
  study's layers stack in a fixed order, and a targeted layer made on a later
  pass takes its study's place among the targeted layers on its pane, moving
  no other layer and recomputing or recolouring no study. An invalid target or
  style throws before any layer of that kind changes; the rest of that pass is
  not rolled back, and its bar colours are not published. Outputs that name no
  target render and stack exactly as before, even beside a study that routes
  on the same pass. `IndicatorOutputTarget` and `IndicatorMarker` are
  exported, and `IndicatorDrawings` takes an optional callback that picks the
  price scale from each frame's context.
- Drawings accept an independent `policy`: `selectable`, `editable`, `persistent`
  and `listed`, each defaulting to true. A read-only drawing still selects and
  copies, but no drag, handle, key, menu, dialog, rail, mobile, objects or grouping
  action changes, regroups or deletes it, and undo never touches it; the owning host
  passes `{ force: true }` to `update`, `updateMany`, `remove`, `removeMany`,
  `clear`, `createGroup`, `renameGroup` or `removeGroup`. Placing a restricted
  drawing, a patch that carries `policy` and every forced call are the host's acts
  and record no undo step, and every recorded step takes them too, so undoing the
  user's own steps never reverses a forced move, delete, regroup or rename. History
  never restores an older policy, never regroups a read-only drawing or renames or
  dissolves its group, and drops a step a new restriction or a forced call leaves with
  nothing to do, so `canUndo` and `canRedo` stay accurate. `createGroup` never reuses a
  group id an undo or redo step still holds. A forced patch to a read-only drawing that
  carries neither `policy` nor `zIndex` costs no pass over the history, so a host can
  trail a level on every tick; any other forced call, and any patch that carries
  `policy`, rewrites every recorded step. An unselectable drawing never joins the
  selection and a click passes through it. A transient drawing is
  left out of `toJSON`, the chart state and saved layouts. An unlisted drawing is
  left out of `ChartObjects`, every objects panel, every group-wide action there and
  the widget's alert source picker. Copies carry no policy, and `locked` behaves as
  before. `ChartObjectDrawingSource` gains an
  optional `removeMany`. The yfinance host adds session price marks that use all
  three host policies and return after every rebuild, strips policies from imported
  layout files, and keeps its toolbar's Del, Clear, Undo and Redo to what they would do.
- The widget tier adds `createChartGrid`: one widget per cell in `1x1`, `1x2`,
  `1x3`, `2x1`, `3x1` or `2x2` presets, with draggable and keyboard splitters, one
  active chart that owns the keyboard, crosshair, viewport, symbol, interval and
  appearance links without echo, a compact tabbed view on narrow screens, and
  persistence. It writes and applies the portable workspace payload, including
  saved spans and weights; a failed apply destroys the half-built charts, cancels
  their requests and leaves the old ones untouched. A linked symbol includes its
  exchange, charts shown again after the compact view take the linked window,
  discrete changes are saved before the task ends, and a stored desk that fails
  to restore is kept and reported through `restored()` and a toast instead of
  being overwritten. After a linked pan or zoom a resize keeps each chart on
  the window it showed, so charts following new bars keep following them and
  stay in step; the linked window moves with the navigated chart's new bars and
  is dropped when viewport linking is switched on again. `feed` may be a
  function that builds each chart's feed from its pane id and saved
  `historyPeriod`, which the grid keeps, copies to charts a preset adds and
  writes back. `WidgetOptions.keyboardRoute` lets any multi-widget host
  decide which widget answers a key, including through a shared
  `ShortcutManager`, and keeps a `global` shortcut scope. The yfinance reference
  host gains a grid view that loads each layout's saved history period; its
  main page hands over layouts it cannot draw after checking the grid view can
  open them, and opens the one or two chart layouts the grid view exports.
- CSV export supports explicit study instances, inclusive UTC ranges and
  display-aligned plot values with effective runtime offsets. Candle plots expand
  into OHLC fields; projected times are identified without exposing future replay
  observations. Optional formatting preserves raw time identity and protects
  spreadsheet text. Both hosts provide guarded CSV selection dialogs.
- Series styles can be read as frozen snapshots, including renderer defaults
  and current plot offsets, through `chart.seriesStyle(series)`.
- User panning and zooming can be enabled independently at runtime. The policy
  covers plot and axis gestures, wheel, touch, keys, navigation buttons and user
  reset/fit actions, and cancels active motion. Both hosts expose and persist the
  settings. Programmatic view changes, drawing edits and chart picks remain usable.
- Study labels, box captions and marker text support independent size, font,
  emphasis and multiline alignment. Marker text can use its own color. Omitted
  styles preserve existing rendering; styled annotations stay inside the plot.
- Study polylines support smooth interpolation through their time and price
  anchors. Curves follow the selected scale, preserve open or closed paths and
  stay clipped to the plot in canvas and SVG output.
- Table cells can show plain-text hover details, including merged cells.
  Measured cell targets keep existing table click IDs, and updates, removal and
  resizing discard stale targets. Exported SVG omits transient hover details.
- Native study inputs now support symbols with paired exchanges, session
  strings, multiline notes, prices and absolute UTC timestamps. Both hosts
  validate drafts, retain fractional timestamps and support chart picking in
  the study's actual pane and scale. Dialog cancellation restores prior values;
  context changes, pane changes and destruction cancel stale captures.
- Primary-only auto-fit follows the actual primary series across panes and scales,
  keeping distant overlays from compressing price candles when enabled. The
  setting preserves manual ranges and ratio locks, and is available in both hosts.
- Study legends can collapse to a persistent count while plots, calculations and
  alerts continue. Touch can expand the count without a prior hover; Readout
  settings provide keyboard access. Both preferences persist independently for
  each chart in saved layouts and portable workspaces.

### Fixed

- The move and maximize buttons of a lower pane follow its first study row, as
  the collapse button does. Closing the first study on a pane, or adding one below
  a row the host placed there, used to leave the new first study row without them.
- Pane dividers no longer rewrite the weights of panes hidden behind a maximized
  pane, and removing a pane above the time navigator no longer attaches the
  navigator twice.
- Closing a widget dialog or menu returns focus to the control that opened it
  on WebKit, which covers Safari and every iOS browser. WebKit does not focus a
  button when it is tapped, so after Escape focus previously went nowhere,
  stranding keyboard and screen reader users. A control that really held focus
  when the overlay opened still receives it back.
- Hover navigation buttons finish fading when the pointer stops moving, so an
  idle chart does not leave them too faint to click. Native image capture pauses
  the fade, and detachment or destruction stops its frame requests.
- Navigation and annotation examples keep button focus from scrolling the page
  during a click after chart interaction, while retaining keyboard activation.
- SVG export preserves very large finite coordinates when decimal rounding
  would otherwise overflow. Ordinary coordinate formatting is unchanged.

### Calculations

- Default scalar SMA and rolling sums use fresh chronological windows. Expired
  gaps and overflow no longer poison later sums, and rounded contributions from
  old bars cannot create false crossover signals. This requires work proportional
  to bars times period; explicit missing-value and varying-length SMA policies
  retain their separate compensated arithmetic.
- Default scalar weighted averages, population deviations and absolute deviations
  also accumulate oldest first and omit nonfinite results. This aligns their
  rounding and composed band calculations with the companion engines.
- Default scalar SMA-seeded exponential and Wilder averages recover from missing
  or overflowing seed windows. After seeding, an absent input leaves a plot gap
  while preserving the running state; a nonfinite running update stays unavailable.
  Public first-value EMA and explicit missing-value policies keep their behavior.
- Directional movement omits unavailable changes instead of counting them as
  zero. Its averages retain their state across gaps, and strength calculation
  waits for current directional readings rather than advancing from stale values.
  Zero smoothed range produces a gap instead of repeating an undefined ratio.
- CPR keeps a period unavailable if any high or low is nonfinite. It recovers
  after the next complete period, preserving the existing session and calendar
  boundaries and final-close convention.
- Money Flow Index omits overflowing price flows and window totals, then
  recovers after those observations expire. Chronological sums align finite
  rounding with the companion engines; missing volume still defaults to zero.
- WaveTrend uses fresh chronological signal windows, avoiding rounding drift
  that could create a false crossing. AlphaTrend windows recover when extreme
  observations expire. These windows require work proportional to the selected
  period rather than a constant-time rolling update.
- Balance of Power omits nonfinite ratios. Seasonality omits nonfinite monthly
  returns and leaves unavailable aggregate statistics blank.
- RSI now treats missing or overflowing changes as unavailable observations
  while retaining seeded averages. Its gain and loss legs recover independently
  from an unavailable seed, and nonfinite running averages no longer emit false
  zero or 100 readings. Ordinary finite results and the public signature remain
  unchanged; built-in studies using RSI inherit the correction.
- ADX now seeds directional movement and true range over the same first complete
  change window. This removes an initial bias in both directional readings and
  the strength calculation. The first available bars are unchanged.
- HMA uses an integer half window and a rounded square-root smoothing window,
  matching Hull Suite's Hma mode and the companion engines. Odd lengths now
  produce different values; lengths such as 13 also require one more warmup bar.
  Length 1 is supported and returns the selected source.

Saved layouts, workspace documents and drawing files from 2.5.3 load unchanged:
pane `collapsed`, drawing `policy` and a pane's `historyPeriod` are optional
fields. Studies whose drawings and markers name no target render and stack as
before. The calculation corrections change values where an input was missing,
nonfinite or overflowing, and otherwise only in the last digits of rounding,
except HMA at odd lengths and the early ADX readings, which now follow the
definitions above. No runtime dependencies or package tiers were added.

## 2.5.3

2026-09-23

### Added

- Data and Objects share a resizable information panel. Data follows local and
  linked crosshairs with OHLC, volume, open interest and named study readings.
  Missing observations stay unavailable. Narrow hosts use a focused sheet.
- Object ordering changes actual rendering. Studies can move between panes while
  retaining their instance IDs and alert references. Named drawing groups support
  selection, visibility, locking, deletion, undo and saved layouts.
- Symbol search accepts asset classes, safe image URLs and explicit futures
  contract groups. Direct typing opens symbol or timeframe entry on the focused
  chart, while existing shortcuts and editors retain their keys.
- The indicator picker lists running instances with individual removal controls.
  Generated forms share compact palettes, recent colours and alpha-aware controls.
  Nested colour popups use the host overlay stack and dispose with their forms.
- Reusable data-window, panel-dock, search, typing and colour components, with a
  complete component stylesheet and AlertUi.context for custom hosts.
- The yfinance reference host demonstrates the new controls with per-pane state.

### Changed

- Website examples progress from simple charts to advanced integrations. Sine-wave
  sample prices are replaced with seeded stock-like candles, pullbacks, gaps and
  varied volume. Sample events have their own rich-detail example.
- The website and API reference use a wider responsive layout, neutral light/dark
  themes and shared typography. Prose stays readable while charts use the available
  space.
- Homepage indicator and drawing illustrations are clearer, and website links
  include a social preview of linked anchored VWAP and volume-profile charts.

Old symbol-search results and saved layouts remain valid. Optional panel state and
named drawing groups are additive. Set panels: false for the previous Objects popup
or typingNavigation: false when the host owns direct typing. No runtime dependencies
or package tiers were added.
TypeScript hosts with exhaustive `ChartObjectKind` maps must add the `group` kind.

## 2.5.2

2026-09-23

### Added

- Anchored VWAP and Fixed Range Volume Profile drawing tools, with editable time
  anchors, settings, selection, undo and saved drawings. VWAP supports price sources
  and deviation bands. The profile shows estimated candle volume, its point of
  control and value area. Missing volume remains distinct from zero.
- Opt-in drawing synchronization for the same symbol and exchange across chart
  intervals. Linked drawings support live previews, edits, deletion and undo without
  copying alerts, orders or local selections. Existing drawings can be shared explicitly.
- Opt-in appearance synchronization through the chart settings API. Visual settings
  can follow independently of symbol, timeframe, viewport and drawing links.
- Timeline event groups, parent visibility and optional zoom-dependent clustering.
  Clicks expose all cluster members. The widget adds accessible plain-text details,
  with optional cancellable detail loading supplied by the host.
- Reference-host controls and a live website example for the new drawing, linking
  and timeline APIs. Event samples are labelled demonstration data.

Existing drawing and appearance links remain off by default. Event clustering is
off unless enabled. No runtime dependencies or additional package tiers are added.

## 2.5.1

2026-09-21

### Added

- `AlertControllerOptions.spentLines: 'hide'` hides the lines of triggered and
  expired alerts. The default, `'show'`, preserves existing behavior.
- Hidden alerts retain their records, lifecycle and saved runtime, so once-only
  alerts cannot fire again merely because their lines are hidden or restored.
  Re-arming restores the line. Armed, repeating and disabled lines stay visible.
- Added restore, re-arm and range browser coverage, a live lifecycle example,
  and host integration guidance. No saved-alert migration is required.

## 2.5.0

2026-09-21

Keep price alerts visible across timeframes, move them to valid ticks, and fit
chart tables to their text.

### Added

- `ChartTableOptions.cellWidth: 'auto'` measures each column from its widest
  cell, including padding, bold text and per-cell font overrides. Empty columns
  retain a 28 px minimum. Percentage widths preserve measured proportions.
- `AlertController.hovered()` lets custom hosts delete the alert under the
  pointer. The widget and yfinance example support Delete and Backspace while
  preserving drawing selection, placement and text-input priority.
- `Chart.snapPrice(paneIndex, price)` rounds to the pane's right-axis tick.
  Alert drags use the primary or study source scale, including left and
  independent axes. Hosts can use a series' scale for its own tick rules.

### Fixed

- Fixed price levels stay visible across timeframes for the same symbol and
  exchange. Another timeframe shows the original interval and pauses armed
  alerts. Triggered, disabled and expired records retain their lifecycle badge.
- All alert evaluation remains bound to the original timeframe, including
  intrabar alerts. Study and drawing levels remain scoped to that timeframe.
  Loading another interval cannot consume the original evaluated-bar checkpoint.
  Restoring or returning to a timeframe never replays historical signals.
- Alert previews and release use the same snapped threshold. Range bounds stop
  at the nearest valid tick inside the opposite bound. A scale without a tick
  leaves values unrounded. Context changes and restore clear stale hover state.
- Every table cell clips its text, preventing long readings from covering the
  next column. Automatic widths measure the font actually drawn in short or
  weighted rows, and measurement preserves the canvas state for other primitives.

### Documentation

- Updated alert, table, upgrade and integration guides, the yfinance reference
  host, and live website examples. Saved alerts need no migration. Price alerts
  on an unseen timeframe stay paused; background delivery remains the host's job.

## 2.4.8

2026-09-21

Hold the chart to move it; release to stop. Clearer setup and integration guides.

### Fixed

- Plot panning shows a grabbing hand while the pointer is held. Mouse and pen
  movement stops immediately on release instead of continuing with inertia.
- Hover-only legend buttons remain visible and clickable when a held press
  spans a repaint. Their pointer cursor stays separate from the plot grab.
- Releasing outside the plot, pointer cancellation and lost pointer capture cannot
  leave a mouse pan active. Drawing placement and primitive drag controls keep
  their own gestures. Touch flicks retain momentum.

### Documentation

- Added dedicated guides for alerts, open interest, workspaces and CSV export.
- Corrected order-preview examples so broker modification is requested only after
  release; documented cancellation, preserved indicator IDs and host-owned settings.
- Clarified live-data refresh, calendar cache rules, linked intervals, loading
  timestamps, chart lifecycle and the difference between chart canvases and controls.
- Simplified the README introduction and installation, refreshed measured sizes
  and fixed the API reference's navigation example link.

## 2.4.7

2026-09-21

Move alert thresholds directly on the chart, with a live preview and one saved
change on release.

### Added

- Price and study-threshold alert lines support mouse, pen and touch dragging.
  Movement previews the selected bound; release commits it once. Preview values
  do not change stored alerts or the thresholds used for live evaluation.
- Range bounds move independently and stop at the other bound. Study thresholds
  use their plot's scale, including separate panes and independent or left axes.
- Primitive gestures announce `drag:start` and `drag:cancel`. Cancellation reports
  `pointercancel`, `pinch` or `escape`; existing drag callbacks remain compatible.
- A live alert-dragging example and reference-host instructions demonstrate
  threshold edits, cancellation and saved-value feedback.

### Changed

- Armed alert badges read "Alert". Triggered, Expired, Disabled and Paused retain
  their existing labels. Stored lifecycle state names remain unchanged.
- Drawing-anchored alert lines let the drawing receive its own gestures.
  Disabled, paused, expired and triggered lines do not accept threshold edits.

### Fixed

- Cancelled and obsolete gestures cannot overwrite alerts after pause, replay,
  source or context changes, restore, update or removal. A click saves nothing.
- Preview levels keep the committed autoscale bounds. Alerts on an independent
  study scale never expand the candle scale, including on their first frame,
  and omit the primary right-axis tag when its units differ.
- Drag coordinates and coalesced samples remain relative to the grabbed pane
  when the pointer crosses into another pane.
- Alert expiry parsing shares the chart's timezone conversion helper while
  preserving the editor's captured timezone and calendar-based default.

## 2.4.6

2026-09-21

Indicator source access, readable legend controls, reliable signal placement
and consistent dialog fields.

### Added

- The yfinance reference host includes an opt-in Source signal sample study,
  a read-only source viewer for each chart, and a chart-local legend button size
  in Readout settings. Legend size survives chart rebuilds and saved layouts.
- `IndicatorDescriptor.hasSource` adds a source button beside the legend's
  settings button. It emits `indicatorSource` with
  `{ instanceId, indicatorId, paneIndex }`. The host owns and displays the code;
  descriptors without the flag, including built-ins, have no source button.
- `IndicatorDescriptor.markerAnchor: 'price'` anchors overlay signals to the
  primary series' candles. `aboveBar` uses the high and `belowBar` the low.
  The default `'plot'` continues to use the first plot. Indicators outside
  pane 0 and charts without a primary series fall back to the first plot.
- `ChartOptions.legendIconSize`, `applyOptions({ legendIconSize })` and
  `setLegendIconSize(size)` apply one button size to existing and later legends,
  including host-added rows. `legendIconSize()` reads the configured value.
  `PaneLegendOptions.iconSize` defaults to 16 media pixels and draws within
  12..28; larger controls increase the row height. Nonfinite chart sizes are
  ignored, and an explicit chart size takes precedence over individual rows.

### Changed

- The alert editor labels expiry with the chart timezone captured when it opens.
  That zone remains fixed for the draft, preserving the instant if the host
  changes the chart timezone. New drafts default to two chart calendar months
  ahead, clamped at month end. Clearing expiry still creates an indefinite
  alert, and editing other fields preserves an existing expiry and its seconds.
  Programmatic alert defaults and stored UTC timestamps are unchanged.

### Fixed

- Fully transparent plot colors no longer leave invisible numbers and blank
  gaps in legend readings, including CSS `transparent` and supported zero-alpha
  hex and `rgba()` forms. Unknown color syntax retains its reading.
- Legend glyphs scale with their buttons instead of their text. The default
  glyphs are larger while the default row height stays unchanged.
- Gap markers recognize null plot values represented as NaN points. Instrument
  bars supply a missing anchor only on pane 0 when the plot and primary series
  share a price scale. Finite plot anchors still win, and oscillator panes or
  independent scales never receive instrument-price fallback.
- Series markers use their bound series' scale, including left or moved axes.
  Indicator marker layers rebind when the selected plot or primary series is
  replaced, and fallback checks use the current primary series.
- Each signal label starts its own canvas path, so a later label cannot recolor
  an earlier label's tail.
- Dialog inputs and buttons respect `--oac-radius` and `--oac-ctl-h`, including
  the date field. Text, number, date and select fields share one control column.
- Select chevrons overlay their own field instead of consuming row width.
- Expiry labels preserve schema translations and keyboard-accessible help.
  Existing typed translation catalogs remain compatible.
- An open alert list refreshes its timestamp readings when the chart timezone
  changes, without altering the stored expiry instant.

## 2.4.5

2026-09-20

Chart workspaces, coordinated replay, open interest and trader alerts, with
optional host contracts for instrument rules, localization and trading support.
Existing hosts retain their defaults; the workspace tier is a separate import.

### Added

- Versioned workspace and indicator-template documents in
  `openalgo-charts/workspace`, with detached validation, atomic asynchronous
  catalog storage, account namespaces, migration and revision conflict handling.
  Documents exclude credentials and trading account state.
- Named layouts and templates in the reference host: create, save, open, rename,
  duplicate, delete, recent layouts, autosave and portable import/export. Layout
  transitions stage source data before installation and recover failed changes.
- One reference workspace toolbar targets the selected chart. Shared replay
  offers focused/all-chart modes with a common clock, explicit candle availability
  and guarded transitions. Replay does not expose future history or enable orders.
- Optional candle-center crosshair snapping, independent interval synchronization,
  a configurable volume moving average and multi-symbol percentage comparisons.
- `exportChartDataCsv` exports installed primary bars, OI, configured study plots
  and aligned comparisons. Missing values remain blank; replay exports only its
  installed prefix. Reference and widget menus download the captured chart.
- Immutable `Instrument` metadata for source identity, supported intervals, IANA
  calendars and exceptions, price formatting, quantity steps and OI capability.
  `orderConstraintsForInstrument` preserves the order adapter's quantity units.
- Optional widget translation with typed keys, safe named interpolation, English
  fallback and translated accessibility labels. Host content remains literal.
- Shared trading capabilities for engine, adapter and widget integrations, with
  explicit unknown/unsupported states, callback-time checks and replay guards.
  `isReplaying(chart)` reports active replay, including paused sessions.
- Trader alert evaluation for prices, study plots, drawing levels and named
  candle conditions, with explicit bar-close or intrabar timing, repeat,
  cooldown and expiry. Delivery is event-based and remains the host's job.
- The widget owns an alert controller and provides a draft editor, live list,
  lifecycle toasts and price/study/drawing context actions. Study identity,
  plot and drawing level are explicit; missing observations never become zero.
- `createAlertUi` mounts the shared alert dialogs in custom hosts. The yfinance
  reference page exposes Alerts for either chart, preserves alerts and their
  study/drawing identities through rebuilds and reloads, and delivers local
  notices. Replay selection, history loading and playback pause evaluation.
- Versioned alert persistence restores drawings and study identities before
  their alert anchors. Missing anchors are dropped with a removal reason.
  Triggered once alerts remain visible after reload, without historical delivery.
- Open Interest, Open Interest Change and Open Interest Buildup studies, with
  missing-data gaps, adjacent changes and four configurable candle regimes.
- Explicit `ChartDataContext.hasOpenInterest` and `chart.hasOpenInterest`
  capability, independent of observations. The optional OI status-line reading
  defaults off, preserves zero and disables unsupported instrument controls.
- Request-scoped OpenAlgo history capability removes unsupported placeholder
  OI before caching. The reference host reads optional OI and retains supplied
  instrument capability through chart-type and interval changes.
- Optional `Bar.oi`, `Tick.oi`, `AggTick.oi` and `SecuritySeries.oi`. Open interest
  is a level, not a flow: historical folds take the latest defined reading in a
  bucket, never sum it. Zero and absence remain distinct. One-to-one transforms
  preserve the field; price-generated and expression bars omit it.
- History mapping and durable-cache validation preserve finite optional open
  interest. Live ticks without a reading clear the forming level. History repair
  preserves newer live observations, and partial replay exposes only readings
  already reached by the playhead.

### Fixed

- Candle readouts and volume direction remain consistent with their source bars,
  including transforms and replay. Comparisons keep their own price units and
  shared baselines; source changes and exports retain the selected chart owner.
- Market event timestamps take precedence over quote delivery time. Cancelled
  workspace and history requests cannot install data into a replacement source.
- Alert restoration preserves stable drawing/study anchors and fired-once state.
  Missing anchors produce removal events, and history loading sends no alerts.
- Instrument ticks reach the primary series on right, left and hidden scales
  while oscillator units remain independent.
- Quantity validation rejects fractional off-grid values at large magnitudes
  instead of letting a relative tolerance grow to half a lot or more.
- Rejected trading preflight preserves existing broker state. Capability checks
  run again after asynchronous mode selection and before queued modification.
- Submitted requests are detached from caller and confirmation callback edits.
  Late modify/cancel responses cannot replace newer broker settlement or
  reconciliation state.
- Base and trading imports share the same capability-error constructor, so a
  host can catch refused operations consistently across package entries.
- A comparison correction to whitespace removes its earlier reading and moves
  the common percentage baseline to the next actual shared observation.
- Entering replay selection pauses pending reference autosaves without blocking
  later named-layout saves after selection is cancelled.

### Integration and validation

- Broker and crypto conformance fixtures exercise real production adapters with
  deterministic transport, including repair, cancellation, failure and cleanup.
  These fixtures are synthetic evidence, not certification against every venue.
- A repeatable browser endurance harness records declared workloads, frame and
  pointer timings, paint output, retained heap and teardown gates. Reports name
  the browser, machine, renderer, bundle hashes and measurement limitations.
- Added compatibility/deprecation and support boundaries in `COMPATIBILITY.md`.
  Host delivery of alerts, account authentication and broker order authority
  remain host responsibilities. See `docs/upgrading-to-2.4.5.md` for adoption.

## 2.4.0

2026-09-18

Coverage for ported studies. Five hundred script-language indicators were
ported onto the descriptor contract, and the gaps they hit were counted: the
same dozen constructs, over and over. This release closes the ones the engine
can close. Every addition is optional and off unless declared.

### Added

- **`securitySeries(bars, interval, options)`** in `openalgo-charts/indicators`:
  the one fold from the chart's own bars to a higher timeframe, one value per
  source bar. Three readings, named rather than guessed: the default reads
  the bucket as it stood at that bar and never uses a later one; `offset: k`
  reads the bucket completed `k` buckets before, held constant; `lookahead:
  true` reads the bucket's final values on all of its bars, which repaints
  and is here only so a source that did it can be reproduced. A day is a day
  in `timezone`, a week starts on Monday there, a registered calendar
  interval cuts on its period, and `session: '0915-1530'` anchors a sub-day
  bucket to the session open the way an exchange cuts its hourly bars.
- **`IndicatorPlot.offset`** and **`SeriesStyle.barOffset`** paint a column
  shifted that many bars (a displaced cloud, a projected channel). The data
  keeps its times and the axis gains no bars; the shifted tail lands in the
  right margin, a fill follows its first plot's offset, autoscale fits what
  is painted in view and the legend reads the value drawn under the cursor.
- **A recompute guard and `IndicatorInputError`.** A `calc` that throws once
  the indicator is on the chart is caught, published as `{ state: 'error' }`
  on the instance's data status and the `indicator:data-status` event, and
  cleared by the next pass that succeeds. The previous plots stay up and the
  studies behind it still recompute that frame. The constructor's own pass is
  still unguarded, so `addIndicator` still refuses a descriptor that cannot
  compute at all. `IndicatorInputError` names a condition the user can fix.
- **`IndicatorAlertSpec.message`** may be a function of the bar the alert
  fired on, so a message can carry that bar's numbers or a webhook body.
- **`cross` and `xcross` marker shapes; `paneTop` and `paneBottom` marker
  positions**, pinned to the plot edge rather than a price.
- **`IndicatorFillSpec.overlay`** draws a band on the price pane, the pair
  with `IndicatorPlot.overlay`.
- **`IndicatorPlot.colorParts`** returns `{ body, wick, border }` per bar,
  carried as **`Bar.wickColor`** and **`Bar.borderColor`** and honoured by
  both the 2D and the WebGL2 candle paths, so a solid wick can sit over a
  translucent body. `colorBy` keeps its string return type.
- **`tooltip` and `id` on `label` and `box` drawings.** A shape carrying
  either is hit-testable, reported through `subscribeClick`, and paints its
  tooltip on a plate while the pointer rests on it.
- **`interval` and `time` input types.** A timeframe the engine can bucket
  by, rendered by the widget as a select over the built-in tokens and the
  registered codes; and a wall-clock string in the chart's zone.
- **`ChartTableOptions.fontSize: 'auto'`** fits each cell to its row and its
  column, so one long label sizes only itself down.
- **A bars provider for other instruments.** `ChartOptions.barsProvider`,
  `chart.setBarsProvider`, `chart.hasBarsProvider`, and `requestBars` on the
  attach context and on `Tier2Context`, read at request time and bounded by
  the instance lifetime. `Tier2Descriptor.series` names external columns to
  align besides the plots and `Tier2Descriptor.calc` combines them with the
  chart's bars, so a relative strength or a beta against a benchmark is one
  Tier-2 descriptor. The types are `IndicatorBarsRequest` and
  `IndicatorBarsProvider`.

### Changed

- Two budgets raised deliberately: the base engine from 78 to 79 KB (77.23 to
  78.07 KB measured, for the recompute guard, the candle colour split, the
  bar offset, the two marker glyphs and positions, the drawing hit layer and
  the bars-provider threading) and the widget terminal from 183 to 185 KB
  (182.37 to 184.14 KB, of which the indicators tier's `securitySeries` and
  Tier-2 combiner are 0.86 KB). Everything (217.54 KB) and base + trade
  (85.68 KB) stay inside their budgets.

### Notes

- A descriptor written against 2.3.2 computes and draws exactly what it did,
  and the 102 built-ins are untouched. The one behaviour that changes is
  deliberate: a `calc` that throws after the indicator is on the chart no
  longer throws out of the render loop.
- The `interval` and `time` inputs reach a host's own settings dialog only
  once it renders them; a host that whitelists input types must add the two.

## 2.3.2

2026-09-16

### Added

- **Stream-driven repair.** Three opt-in `DataLoadingController` options let
  history repair follow what the stream reports instead of a clock.
  `refreshOnBarClose` runs one refresh a moment after a pushed bar opens a new
  bucket, which is when the bar before it closed, and retries a bounded number
  of times while history has not published that bar yet; nothing fires while
  the market is quiet. `refreshOnGap` refreshes at once when a pushed bar skips
  whole buckets, the shape a dropped socket, a hidden tab or a sleeping machine
  leaves behind. `refreshWindowBars` makes every refresh a tail request instead
  of re-fetching the whole load window. Together they cost about one small
  request per bar instead of two full-window requests a minute, and a skipped
  bucket is repaired the moment the stream resumes. `pollIntervalMs` is
  unchanged and still serves as a slow backstop for silent drift.
- **Provisional bars.** `CandleBuilder` now says when a bar's open, high, low
  and volume cover only the ticks it saw. `CandleUpdate.provisional` is true
  for a bucket the builder opened from a tick without having streamed the bar
  before it: a cold start, or a seed from an older bucket, both of which mean
  the trades between the bucket's true open and the first tick were missed.
  `CandleBuilder.reconcile(bar)` adopts an authoritative bar for that bucket,
  taking the true open for a provisional bar, the union of the extremes and the
  larger volume for any bar, and keeping the close with the ticks;
  `isProvisional()` reads the flag.
  `DataLoadingController.pushBar(bar, { provisional: true })` keeps the open
  history already holds for that bucket instead of replacing it, so a repair
  that found the true open is not undone by the next tick. `subscribeBars` callbacks receive the same `LiveBarMeta`,
  and `OpenAlgoLiveDataFeed` passes it through.
- A refresh keeps the extremes and volume the stream observed on the bar that
  was forming when the request went out, as it already did for bars pushed
  while the request was in flight.

### Changed

- `examples/live` runs on `DataLoadingController` with the new options in
  place of its own reconcile loop, seeds its builder from history, and reseeds
  it after a stream resync so the bucket opened after the gap is provisional.
- Two budgets raised deliberately: the base engine from 77 to 78 KB (76.46 to
  77.23 KB measured) and base + trade from 85 to 86 KB (84.07 to 84.84 KB).
  The widget terminal (182.37 KB) and everything (215.76 KB) stay inside
  their budgets.

### Notes

- Every new option is off by default. A controller built the old way makes
  exactly the requests it made before, and a test pins that.
- A rollover repair fires only on a push, so a host streaming whole candles
  from an exchange gets the same cadence as one building candles from ticks,
  and a host with no stream keeps polling.

## 2.3.1

2026-09-16

### Fixed

- **A refresh no longer deletes a bar the stream completed and REST has not
  caught up to.** `DataLoadingController.refresh()`, which the repair poll, the
  resume after a hidden tab and a stream resync all go through, fetches the
  window from the oldest loaded bar to now and treated the reply as
  authoritative for all of it. A broker's REST history runs a few seconds
  behind its stream, so a refresh fired just after a candle closed came back
  one bar short, and that candle was removed from the series until a later
  refresh found it in REST. On screen: the current candle became the previous
  candle, vanished, then came back. The window REST is allowed to overwrite now
  ends at the newest bar REST actually returned. A bar REST has not published
  yet is left alone; a bar it does return is still corrected by it.

### Notes

- Bars pushed while a refresh was in flight were already protected by the
  buffer. The gap was bars that completed before the refresh started, which
  lived only in the held series and so were not in the buffer either. Three
  regression tests cover both timings and the correction case, and the fix was
  confirmed by reverting it and watching them fail.
- `ExpressionNode` and `ExpressionFunctionName`, the types behind
  `SymbolExpression.ast`, are now exported from the transform tier. They were
  reachable from the public API without a page in the API reference. Nothing
  else in the public API changed, and the bundles move by hundredths: base
  76.52 to 76.46 KB, everything 215.04 to 214.99 KB Brotli.

## 2.3.0

2026-09-16

### Added

- **Symbol arithmetic.** `openalgo-charts/transform` gains `parseExpression`
  and `evaluateExpression`, so a host can chart `NIFTY1!/NSE:RELIANCE`,
  `(A+B)/2`, `1/GOLD`, or any expression over any number of legs.
  `+ - * / ^` with the usual precedence (`^` right associative), unary minus,
  parentheses, numeric constants, and `abs sqrt ln log log10 exp min max pow`.
  The keypad glyphs a search box prints are accepted too, so a pasted
  expression works.
- `parseExpression` reports the symbols it needs **before** anything is
  fetched, which is what lets a host resolve and load exactly those legs.
  `isPlainSymbol` tells an ordinary symbol from arithmetic, so one code path
  serves both. `ExpressionError` carries the offending character's index, so a
  search box can underline it.
- **Weighted legs, for options combinations.** `2*CE25000 - CE25200` is a ratio
  spread, `CE + PE` a straddle, `75*(CE25000 - CE25200)` the same spread scaled
  by lot size. A sold spread is a credit, so the combined premium is negative,
  and that is allowed rather than clamped. One consequence to know: a series
  that goes at or below zero cannot be drawn on a logarithmic price scale, so
  leave a spread pane on the regular scale.
- A leg that did not print gaps the whole combination rather than pricing it
  from an earlier minute. For an illiquid strike that is the normal case, and a
  premium carried forward is exactly the number that gets someone hurt.
- The reference host wires it end to end: type `AAPL/MSFT` into the symbol
  field, or build an expression with the operator keypad beside it.

### Notes

- **Open and close are exact; the high and low are a bound.** A bar records
  where a market opened, closed and how far it travelled, but not *when* it was
  at each price, so the true high of a ratio is not recoverable from two OHLC
  bars. `ohlc: 'close'` is the default and is exact. `ohlc: 'interval'` bounds
  the extremes by interval arithmetic, which is guaranteed to contain the truth
  and is usually wider, because it assumes each leg hit its extreme at the worst
  possible moment. An interval also cannot see that two mentions of one symbol
  move together, so `A/A` bounds rather than collapsing to 1.
- A bar the other legs did not trade produces a gap, not a value carried
  forward: a ratio against another minute's price was never true. A divisor
  reaching zero gaps rather than spiking.
- The result carries no `volume`. The volume of a ratio is not a quantity
  anyone traded, and picking one leg's would be arbitrary.
- A ticker containing `-` is written in quotes (`'BRK-B'/SPY`), because bare
  `-` is subtraction and no lookahead settles `A-B` in general.
- Two size budgets were raised deliberately: the transform tier from 5 to 6 KB
  (it gained the parser and evaluator, 2.66 to 4.44 KB), and Everything from
  215 to 218 KB, which had 0.08 KB of headroom left.

## 2.2.3

2026-09-16

### Security

- Every interpolated attribute in the icon markup is escaped, not only `size`
  and `className`. `opts.stroke` is typed `number`, but a JavaScript host is not
  held to that, and it went into the `<svg>` raw, so a host forwarding a value
  from its own settings could close the attribute and open a tag. The sprite's
  symbol ids, the `<use>` href, the path data and the registry's own attributes
  are escaped too: one escaped value beside four unescaped ones is the shape a
  later edit gets wrong.
- Three regular expressions rewritten to remove quadratic backtracking.
  `parseSessionSpec` and the two `rgb()` colour parsers each placed a `\s*`
  beside something that also matches a space, so a long run of spaces on an
  input that ultimately fails split between them in quadratically many ways.
  Measured on the old patterns: 64k spaces took 1.96 s in the colour parser and
  over half a second at 32k in the session parser; both are now under a
  millisecond. The session spec is a string a user types into a settings field,
  where a half-typed value arrives on every keystroke.
- The test suite's fake DOM strips an unterminated trailing tag from
  `textContent`, which `/<[^>]*>/g` left behind.

These close every open CodeQL alert. The colour parsers and the session parser
were verified to accept and capture exactly what they did before, over a corpus
of valid and malformed inputs, and both fixes were confirmed by reverting them
and watching the new tests fail.

### Notes

- No public API changed, and no behaviour changed for any valid input.

## 2.2.2

2026-09-16

### Security

- Documentation-site dependencies updated to clear every open advisory:
  `next` to 15.5.25, `sharp` to 0.35.4, `js-yaml` to 3.15.2, and
  `@xmldom/xmldom` to 0.9.12 through an npm override, because
  `speech-rule-engine` pins it exactly and npm cannot lift it on its own.
  `postcss` is overridden to 8.5.28 for the same reason: Next pins 8.4.31, and
  npm's only offered route was a Next major. `npm audit` reports zero
  vulnerabilities.

**The published package was never affected.** `openalgo-charts` has no
`dependencies` and no `peerDependencies`; every advisory was in
`website/package-lock.json`, which builds the documentation site and ships to
nobody. Anyone who installed 2.2.0 or 2.2.1 was not exposed by any of these, and
upgrading is not a security action.

### Notes

- No library code changed. The bundles differ from 2.2.1 only by the version
  string they carry, which is why the measured sizes move by hundredths.

## 2.2.1

2026-09-16

### Added

- `IndicatorInput` gains an optional `tooltip`, help text a settings UI renders
  as a hover mark beside the label. A label has to stay short enough for a dense
  panel, which left nowhere to say what a parameter does, so a ported study
  arrived with its explanation dropped. Every one of the six input variants
  carries it, as does the chart-settings `colorPair` row.
- `IndicatorPlot` gains an optional `priceFormat`, which sets the axis and
  crosshair formatting of the scale the plot maps to. A new `percent` variant
  suffixes the value without scaling it, so a ratio study no longer has to
  choose between an axis that reads correctly and a value that does.
- `PriceFormat` is exported, and `addSeries`'s `priceFormat` accepts the same
  `percent` variant.

### Improved

- Historical Volatility and Bollinger BandWidth label their axes as percentages,
  and carry help text on the inputs whose meaning was previously left unstated.
  Historical Volatility's "Days per bar unit" label loses its parenthetical,
  which now sits in its tooltip.
- The chart-settings dialog explains Scale and Timezone: what Percent and
  Indexed to 100 rebase against, and that changing the zone moves VWAP and pivot
  values rather than only the labels.

### Notes

- Both additions are optional fields. A descriptor, a host implementing
  `IndicatorHost`, and a saved chart state written by 2.2.0 all behave exactly
  as before; `addIndicatorSeries` gained a trailing optional parameter, which an
  existing implementation still satisfies.
- `priceFormat` is a property of the price **scale**, like `style.precision`, so
  it belongs to a plot that owns its pane. On an `'onchart'` plot it would
  reformat the instrument's own axis.

## 2.2.0

2026-09-13

### Added

- The drawing catalogue grows from 51 to 85 tools. New line tools include
  disjoint, flat-edge and regression channels, four pitchfork variants,
  Info Line, Trend Angle, a two-point Fibonacci extension, a full time/price
  speed-resistance fan and configurable vector stamps.
- Advanced geometry adds Trend Fib Time, Fibonacci circles, arcs, wedge and
  spiral, Gann Square, Dedekind Tessellation, and ordinary or golden-spaced
  sonic and supersonic wavefronts. Curve painting uses native circle/ellipse
  paths where appropriate, with bounded hit testing and recursive work.
- Eleven manual pattern tools cover XABCD, ABCD, Elliott impulse and correction,
  Head and Shoulders, Gartley, Bat, Butterfly, Crab, Shark and Cypher, with
  point labels, editable fills and measured harmonic ratios.
- A full-size drawing gallery provides editable samples of every tool with
  irregular simulated NIFTY prices near 23800. The website playground,
  widget rail and reference host expose the expanded catalogue on desktop
  and touch layouts.
- `ADVANCED_LINE_TOOLS`, `ADVANCED_GEOMETRY_TOOLS` and
  `PATTERN_DRAWING_TOOLS` expose the new descriptor families from the draw tier.

### Improved

- Multi-point placement keeps chosen anchors and a dashed connecting guide
  visible until the final point is placed.
- Repeated label widths share measurements within one paint. Measurements are
  discarded afterward so newly available fonts cannot leave stale widths.
- Measurement volume reads seek directly to the selected history window and
  reread its live values on every paint. Dense stacks stop hit testing at the
  topmost exact hit while preserving nearest-hit and paint-order semantics.
- Table column layout and hit testing share actual font measurements, including
  bold headers. Long cells remain selectable without a fixed-width phantom area.
- Speed-resistance fan labels use compact, collision-checked edge placement.
  Dense geometry labels spread into separate rows; labels that cannot fit in
  a tiny plot are omitted instead of painting over one another.
  Numeric geometry, disabled levels, fill regions and DPR validity are covered
  by focused regression tests alongside real-browser catalogue sweeps.

### Compatibility

- Drawing documents remain version 2. Existing tool IDs and stored anchor
  meanings are preserved. `fib-fan` is named Fib Fan; the full two-family
  construction has its own `fib-speed-resistance-fan` ID. Existing
  `fib-extension` remains a three-anchor projection.
- Drawings, temporary guides and handles remain visible in forward space and
  clipped inside the plot at price and time axes. The library keeps eight
  optional tiers and zero runtime dependencies.

## 2.1.9

2026-09-13

### Added

- Charts display the OpenAlgo corner logo by default, with responsive sizing,
  theme contrast and vector exports. Hosts can replace or disable the mark with
  `branding` and `chart.setBranding`.
- An optional background watermark supports automatic symbol/interval text or
  custom text. It is disabled by default and configurable through Appearance
  settings, `watermark` and `chart.setWatermarkOptions`.
- Watermark preferences persist independently of host branding and follow the
  current data context. The widget, reference demo and OpenAlgo chart settings
  share the same controls.

### Fixed

- The basic profiles example maps volume buckets to renderer values, restoring
  its missing Volume Profile histogram bars. Its Market Profile and order-flow
  selections now reuse the full current demos, exposing TPO letters, themes,
  text coloring, lot display and the optional statistics table. The order-flow
  logo moves to the top-left while table rows are visible, keeping labels readable.
- Objects and managed-loading demos use irregular simulated OHLC candles and
  changing volume. Navigation and mobile controls have a dedicated example in
  the Mobile guide and are removed from the Examples page.
- Website and reference-host examples use the shared logo defaults, avoiding
  missing logos on widget/mobile charts and duplicate manual marks.
- PNG export skips hidden and empty pane buffers, including maximized panes.
- Logo gestures stay separate from drawing placement, including pinch release,
  missed mouse releases and secondary pen buttons.

The release build measures 76.16 KB base and 203.62 KB total Brotli.
Budgets allow the default vector artwork, optional watermark and guarded gestures:
77 KB base, 85 KB base plus trade, 173 KB widget terminal and 205 KB total.
The chart-only import measures 48.96 KiB against a 50 KiB ceiling.

## 2.1.8

2026-09-13

### Added

- Wheel and trackpad input now scales proportionally after pixel, line and page
  delta normalization. Horizontal input and Shift-wheel pan time; Ctrl-wheel and
  Meta-wheel pinch input zoom at the pointer.
- Wheel input over a visible left or right price axis scales that axis at the
  pointer price. Manual and fixed price ranges remain authoritative, and plot
  drags retain two-axis panning by default.
- Optional `animAutoscale` smooths automatic price ranges as navigation reveals
  new extrema. It defaults to `animZoom`; programmatic viewport replacement,
  primary data replacement, reset and destruction cancel pending navigation motion.
- `WidgetOptions.mobile` provides responsive packaged controls. `'auto'` activates
  at a container width of 640 CSS px or less or when the primary pointer is coarse,
  while `'always'` and `'never'` force a layout. The touch header, bottom controls and drawing sheets share the desktop
  widget's drawing controller, object inventory, dialogs and overlay state.
- `mountMobile`, `MobileMode`, `MobileOptions` and `MobileHandle` are exported from
  `openalgo-charts/widget` for custom widget composition. The website includes an
  interactive navigation and mobile example using the website's current library bundles.
- The yfinance reference host adds a touch toolbar for drawing tools, Cursor,
  Undo, Redo, Magnet, Zoom in, Zoom out and Fit. It retains the focused chart's
  state across responsive layout changes, keeps replay controls clear of the
  toolbar, and honors reduced motion in both the primary and split charts.

### Fixed

- Pending zoom and kinetic callbacks cannot overwrite a viewport reset or continue
  after chart destruction, including resets triggered from navigation listeners.
- Mobile drawing actions retain keyboard focus during refresh. Symbol searches
  discard obsolete responses and keep their last result reachable in short charts.
- Reference-host zoom buttons stop at scale limits without shifting the viewport;
  touch Undo and Redo controls follow keyboard and controller changes.

### Migration and validation

- Existing hosts need no required option change. Set `animZoom: false` to retain
  immediate wheel zoom and its matching immediate autoscale default, or set
  `animAutoscale` separately. Set `mobile: 'never'` when a widget must keep desktop
  chrome in a narrow container.
- The widget disables omitted navigation animation options when the user prefers
  reduced motion. Explicit host values remain authoritative.
- Validation covers wheel delta modes, horizontal pan, left and right price axes,
  pinch modifiers, autoscale transitions and cancellation, mobile mode changes,
  allowed tools, shared drawing state, teardown, declarations, skill references
  and the documentation website. Bundle budgets rise intentionally for the new
  gesture and mobile-control code: 75 KB base, 83 KB base plus trade, 42 KB widget,
  170 KB widget terminal and 202 KB total, with a 46 KiB chart-only ceiling.

Validation: **4,376 unit tests** across 196 files and **228 demo tests** across
15 files pass, alongside lint, TypeScript, build, declarations and size checks.
All **847** skill coverage entries are present and TypeDoc has no warnings.
The browser suite passes **127 tests**; one optional historical-render comparison
is skipped without its baseline bundle. Website navigation, Objects, loading,
depth, profile and orderflow checks pass. The packed candidate passes the OpenAlgo
production build and **18 `/trading` browser workflows** using synthetic protocols.
Measured Brotli: **74.00 KB** base, **41.59 KB** widget, **169.54 KB** widget
terminal and **201.15 KB** all tiers. Touch checks use browser emulation.

## 2.1.7

2026-09-11

### Added

- Headless `ChartObjects` inventory for the primary source, indicator instances,
  drawings and explicitly registered profiles. Immutable snapshots and supported
  actions are shared by the packaged widget and custom broker terminals.
- Searchable Objects panel, `widget.objects`, `widget.openObjects()` and reusable
  `mountObjectsPanel`. Drawings support selection, visibility, locking, settings,
  focus and removal through the existing controller and undo history. The primary
  price source is protected from removal.
- Interactive Objects website example with a compact host, profile capabilities
  and layout save/restore, plus public API and agent-skill guidance.

### Fixed

- Dialogs fit the actual chart container, including 350px panes on wide pages and
  short chart hosts. Tabs adapt their orientation, fields avoid horizontal overflow,
  and action footers remain reachable while content scrolls.
- Hidden indicators stay hidden after JSON layout restoration and plot-type edits.
  Reference levels follow indicator visibility, alongside plots and other visuals.
- Direct indicator-handle removal releases its inventory entry and empty pane.
  A throwing external cleanup cannot prevent owned chart resources being removed.
- Inventory observers remain synchronized through drawing undo, primary-source
  replacement, provider subscription failures and reentrant notifications.
- Drawing focus supports anchors beyond the loaded bars and a primary price axis
  moved to the left, without changing drawing coordinates.

### Integration and documentation

- The companion OpenAlgo integration provides a focused-pane Objects panel with
  existing settings editors, generation-scoped ownership and persisted indicator
  visibility. Profile actions reflect the operations the host actually supports.
- Eight tiers and zero runtime dependencies are retained. Intentional object-model
  and panel code raises the base, base-plus-trade, widget, widget-terminal and total
  budgets to 74, 82, 40, 168 and 200 KB Brotli. The chart-only tree-shaking ceiling
  remains 45 kB.

Validation: **4,337 unit tests** across 193 files and **219 demo tests** pass,
alongside lint, TypeScript, build, declaration and tree-shaking checks. All **846**
skill coverage entries are present. All **106 browser tests** and nine additional
compact-dialog combinations pass across Chromium, Firefox and WebKit. TypeDoc has
no warnings; the 55-route website build and Objects, loading, navigation, depth and
profile browser checks pass. Measured Brotli: **73.31 KB** base,
**38.72 KB** widget, **165.97 KB** widget terminal and **197.58 KB** all tiers.

## 2.1.6

2026-09-11

### Added

- Shared headless `DataLoadingController` for history, live bars, refresh, older
  pages, display suspension and typed loading state. Widgets use it automatically;
  custom broker terminals can bind the same controller to their own UI.
- `HistoryRequestPool` coalesces identical requests per feed, limits concurrency
  and provides independent consumer cancellation, priority and deadlines. The
  OpenAlgo REST adapter bounds fetch and JSON body decoding.
- Optional `DataFeed.getBarsPage` and `getCachedBars` capabilities preserve existing
  feed implementations. Pagination distinguishes empty windows, provider exhaustion
  and local retention limits; cache snapshots paint closed history before refresh.
- Explicit chart data context and external-study lifecycle status, automatic
  context/range refresh, cancellation, unsupported data and retry. The widget shows
  accessible chart, history and study status with compact Retry controls.

### Fixed

- Durable cache failures and invalid entries fall back to bounded memory without
  preventing usable history. New entries are versioned; forming bars remain excluded.
- Context switches, recovery retries and teardown reject obsolete results. Replay
  can hold its displayed prefix while the controller maintains current live data.
- Same-context widget reloads and older pages preserve the visible time anchor.
  Hidden topbar/statusline combinations retain a usable chart and Retry control.
- OpenAlgo depth frames retain their exchange event timestamp. Book quantities
  remain distinct from traded volume.
- Saved drawings, previews and handles are clipped to the pane plot, preventing
  price-axis spill while retaining drawings beyond the latest candle. Drawing
  rendering and hit testing also follow a primary price axis moved to the left.

### Integration and documentation

- Interactive failure, retry, empty-history and paging simulation in the website;
  updated feed, cache, widget, indicator and host guidance and skill references.
- Permanent release process in `CLAUDE.md` covers regression evidence, browser
  validation, OpenAlgo compatibility, docs, publication and downloaded-artifact checks.
- Base bundle budgets account for the shared controller and resilient cache. The
  package retains eight tiers and zero runtime dependencies.

Validation: **4,303 unit tests** across 190 files, **219 demo tests** and
**82 browser checks** pass. Browser coverage includes Chromium, Firefox and WebKit,
failed refresh/retry, replay isolation, saved/future drawings and axis clipping.
TypeDoc reports no warnings; all 843 skill coverage entries are present. The
OpenAlgo consumer passes 1,892 frontend tests and 13 browser workflows.
Measured Brotli: **71.57 KB** base, **25.90 KB** draw, **36.83 KB** widget,
**162.35 KB** widget terminal and **193.96 KB** all tiers. The chart-only
import remains within its existing 45 kB tree-shaking budget.

## 2.1.5

2026-09-11

### Fixed

- Drawing previews stay visible when an endpoint moves beyond the latest candle
  or before the first loaded bar. Trend lines, rectangles and other drawing tools
  use the existing pixel-to-time conversion in empty chart space.
- Freehand tools can start and continue in empty time-axis space instead of
  silently discarding those samples.
- Crosshair candle time and OHLC remain null where there is no bar. Magnet
  snapping still requires an actual hovered candle; drawing state and feed APIs
  retain their existing formats.

Validation: **4,215 unit tests** across 182 files, **219 demo tests** and **47 browser
checks**, including future-space preview, commit, handle dragging, save/restore,
new-bar updates and freehand rendering. The complete verification gate passes.
Measured Brotli: **67.08 KB** base, **25.84 KB** draw, **156.29 KB** widget terminal
and **187.90 KB** all tiers. Existing budgets are unchanged.

## 2.1.4

2026-09-11

### Fixed

- Restore time-and-price mouse and pen panning by default. This restores vertical
  plot movement for market-profile and orderflow charts as well as other chart
  types. Set `navigation.mousePan: 'horizontal'` for optional time-only panning.
- Preserve explicit navigation preferences in saved settings and chart state.
  If a saved layout uses horizontal panning, select **Axes > Mouse drag > Time
  and price** to change that preference. Upgrading does not reset user settings.

Time-axis drags still expand spacing to the left and compress it to the right.
Reset view, default visible bars and touch panning retain their existing behavior.
Current guides and agent skills describe the restored default and saved-layout behavior.

Validation: **4,209 unit tests** across 181 files and **219 demo tests** across
14 files pass, together with the complete verification gate. TypeDoc reports no warnings.

Measured Brotli: **67.10 KB** base, **36.01 KB** widget, **156.28 KB** widget terminal
and **187.89 KB** all tiers. Bundle budgets are unchanged.

## 2.1.3

2026-09-11

### Fixed

- Dragging the time axis left expands candle spacing; dragging right compresses
  it. The shared engine supplies the same behavior to custom hosts, widgets,
  documentation charts, the gallery, and embedded profile and orderflow demos.
- Mouse and pen plot drags preserve price autoscale by panning horizontally by
  default. Select Time and price in Axes settings to enable vertical panning.
  Direct price-axis drags and touch gestures retain their existing controls.
- Time-axis drags emit zoom events so linked charts and saved layouts follow
  the gesture. Initial fitting waits for a measurable container, including
  charts loaded while their tab is hidden. Reset restores left and overlay
  price scales as well as the right price scale.

### Added

- A Reset view button between the bottom zoom and pan controls restores the
  preferred time window and price autoscale. Custom navigator labels remain
  compatible and inherit the reset label when omitted.
- `ChartOptions.navigation`, `chart.navigationOptions()` and
  `chart.setNavigationOptions()` expose `mousePan` and `defaultVisibleBars`.
  Axes settings and saved chart state retain both preferences. A positive count
  shows the latest requested bars initially and on reset; 0 fits all loaded bars.
  The widget honors this preference after symbol and interval changes.
  `fitContent()` still explicitly fits all loaded data. This controls the view,
  not the history request or retained data. These controls address issue #9.

### Integration and documentation

- Updated interaction guides, website examples and API references for the new
  navigation behavior. Regression coverage drives real pointer gestures and
  saves/reloads the settings through the widget.
- Audited repository skills from 2.0.0 through 2.1.3 and filled missing guidance
  for profiles, orderflow, navigation and OpenAlgo host integration.
- The base, widget and widget-terminal size ceilings are 68 KB, 37 KB and
  157 KB respectively to accommodate these controls. The full-package ceiling
  remains 188 KB; no runtime dependencies were added.
- Companion OpenAlgo `/trading` fixes isolate replay from live history refreshes,
  reject obsolete symbol and pagination responses, prevent resource startup
  after pane teardown, and await concurrent custom-indicator registration.
  These application fixes require the OpenAlgo update as well as this package.

Validation: **4,208 unit tests** across 181 files, **219 demo tests** and
**44 browser checks**, including pixel parity against 2.1.2. The complete
lint/type/build/declaration/size/tree-shaking gate passes. The corrected OpenAlgo
consumer passes its production build, **408 trading tests** and **13 browser
workflows** with synthetic broker traffic. Website checks verify matching chart
bundles and native axis drags in the gallery and embedded profile/orderflow demos.

Measured Brotli sizes: **67.05 KB** base, **36.01 KB** widget,
**156.24 KB** widget terminal and **187.84 KB** all tiers.

## 2.1.2

2026-09-10

### Fixed

- External indicators isolate history requests and live callbacks by data key
  and attachment. Changing a symbol or other data setting immediately clears
  previous values; obsolete responses and cleanup cannot update the new study.
  Style changes reuse pending history. Live observations win overlapping
  historical points. Empty history completes without unnecessary style refetches;
  failed history retries on the next settings change.
- The widget seeds live subscriptions from the last historical candle. Seeded
  cumulative-volume candles preserve known bar volume when the first quote
  arrives without a supplied day-volume baseline; reseeding clears an old baseline.
  The synthetic feed also continues from the supplied last bar.
- OpenAlgo WebSocket market data accepts symbol/exchange at the top level, as
  emitted by the server, while retaining nested identity and legacy topics.
- REST history preserves explicit timezone offsets, retains IST for naive
  timestamps, maps daily/weekly/monthly aliases to broker tokens D/W/M, and
  propagates backend error responses instead of presenting empty history.

### Added

- Optional `BarSubscriptionOptions` on `DataFeed.subscribeBars`: `seedFrom`,
  `cumDayVolumeSoFar` and `onResync`. Existing two-argument feeds remain valid.
  The OpenAlgo live feed reports reconnect recovery through `onResync`; custom
  hosts can refresh history and reseed without sending old bars through `onBar`.
- Widget reconnect recovery buffers live bars while refreshing its configured
  history window, merges the observations and preserves the viewport. Repeated
  reconnects supersede pending requests. Failed recovery keeps visible history
  marked stale while monitoring continues; `reload()` retries. Overlapping
  volumes use the maximum snapshot. Whole-bar merging is conservative: buffered
  seed extrema can survive history corrections, and unseen trades are not replayed.
  `BarsRequest.noCache` bypasses `withBarCache`, including retries after failure.
- `WidgetOptions.styleNonce` authorizes the injected stylesheet under a matching
  CSP. Empty SSR placeholders can be filled without duplicate sheets; populated
  host styles and existing nonces are preserved. Style attributes remain subject
  to the host's separate CSP policy.

### Integration and validation

- Added an isolated browser compatibility harness for the actual OpenAlgo
  `/trading` application, covering canonical wire frames, lot quantities, order
  modification/cancellation, replay controls, drawings, indicators, profiles
  and layout persistence. No real broker orders are submitted.
- CI runs the full package verification gate and shares the resulting build
  with browser and documentation jobs. Profile screenshot fingerprints, compact
  TPO, orderflow tables and depth behavior are checked before website deployment.
- The release workflow verifies tag, package, source and built runtime versions
  before publishing the checked build with npm provenance.
- Updated integration guides and API documentation. The existing 2.1.1 profile
  captures remain current: their rendered sources and image hashes are unchanged.

See the [OpenAlgo compatibility guide](https://marketcalls.github.io/openalgo-charts/docs/openalgo-compatibility/)
for validation scope and the existing host replay-reconciliation limitation.

Validation: **4,194 unit tests** across 180 files, **219 demo tests** and
**41 browser tests** pass, including pixel parity against 2.1.1. The full
verification gate covers lint, types, builds, declarations, size budgets and
tree shaking. OpenAlgo's unchanged consumer passes its production build,
**389 trading tests** and **13 browser workflow checks**.

Measured Brotli sizes: **66.65 KB** base, **27.36 KB** indicators,
**36.00 KB** widget (35,998 bytes), **155.82 KB** widget terminal and
**187.42 KB** all tiers. The full-package budget moves from 187 to 188 KB;
individual tier budgets are unchanged.

## 2.1.1

2026-09-10

### Added

- **Three footprint styles.** `cellStyle` selects the existing heatmap, a
  volume-proportional bid/ask profile, or a square cluster ladder. Profile
  numbers stay aligned at the center while each side's width follows volume.
- **Actual OHLC candles and per-bar statistics.** Footprint bars now carry
  optional `open`, `high`, `low`, `close`, `tradeCount` and `rowSize` metadata.
  `statsPosition: 'bar'` puts labeled statistics below each footprint;
  `pocStyle: 'outline'` and `showValueArea` mark POC and the contiguous volume
  value area. Legacy data without OHLC shows a neutral range line.
- **Independent text coloring.** `textColorMode` supports automatic contrast,
  bid/ask side, row delta, same-price dominance, diagonal imbalance and volume
  strength. `textColor`, `buyTextColor` and `sellTextColor` are separate from
  cell-fill colors; readable foregrounds adapt to dark, light and neon fills.
- **Five orderflow demo themes:** Midnight, Graphite, Classic neon, Ocean and
  Ivory. Theme, footprint style and text method switch independently without
  resetting the tape or viewport. The deterministic demo includes price-row
  grouping, pause/resume, POC/value-area controls and a row inspector.
- `ChartOptions.timeScale` accepts initial public time-scale options, including
  wider maximum bar spacing for readable footprint columns.
- `cvdOffset` supplies cumulative delta preceding the displayed window, so a
  host can discard old bars without resetting session CVD.
- **Configurable orderflow table, disabled by default.** `tableRows` selects
  and orders Delta, Min Delta, Max Delta, Cumulative Delta, Total Ask Volume,
  Total Bid Volume and Total Volume. Labels stay fixed on the left; columns
  align with their footprint bars during pan and zoom. Per-bar cards remain
  independently configurable. Explicit `statsRows` restores the older footer.
- `minDelta` and `maxDelta` track the running ask-minus-bid delta within each
  bar, including its initial zero. Batch and live builders preserve the trade
  path; legacy bars without these fields report `null` rather than row extrema.
- **Quantity or lots.** `volumeDivisor` defaults to 1 for raw quantities.
  A value of 65 displays quantities and delta metrics in lots of 65 across
  cells, cards and tables. Raw data, analytics, percentages and trade counts
  remain unchanged. The demo includes an editable lot-size control.

### Fixed

- Streaming snapshots copy their cells; later ticks and caller mutations no
  longer alter previous snapshots or the live accumulator.
- Diagonal imbalances use actual adjacent price rows and fractional quantities.
  Gaps are not bridged. A positive quantity against zero opposing volume can
  qualify; zero versus zero does not. Both sides can qualify at the same price,
  and stacked runs track each side independently.
- Footprint trade counts report classified records, rather than occupied price
  levels. Missing legacy counts are `null` in stats and display as an em dash.
- Candle direction follows the actual open/close rather than delta. Row bounds
  contribute half a price step to autoscale, rendering is clipped to the plot,
  and zooming out no longer forces overlapping minimum-size columns or rows.
- Hover uses the drawn bounds of each row and statistics card; offscreen rows,
  empty data and detached primitives no longer retain stale interactive areas.
- Volume display uses combined row volume for its peak; fractional volume
  labels retain significant digits and suffix rollover formats correctly.

### Input handling

- Batch and streaming footprints validate finite time/price, nonnegative
  quantity, classified side, positive tick size and integer row grouping.
  Live ticks older than the last accepted tick are rejected before mutation.
- Tick-count and volume bars coalesce trades with tied opening timestamps
  until time advances, preventing duplicate chart time keys. Such bars can
  exceed their target count/volume; supply precise timestamps where available.
- Supply explicit `rowSize` (or renderer `tickSize`) for legacy sparse ladders.
  Without it, minimum observed spacing cannot identify uniformly missing rows.

### Website and examples

- The orderflow guide embeds the current standalone demo and documents the new
  styles, text methods, metadata, validation and CVD-window handling.
- The market-profile guide now opens with compact rendering and includes a
  current six-session overview and five-theme gallery. Real browser captures
  refresh all theme and packed/split images; captions distinguish compressed
  pixel letters from enlarged regular text. Screenshot hashes invalidate stale
  cached images and a capture manifest checks source and image consistency.
- Removed the old market-profile screenshot directory. Current captures live
  under `screenshots/market-profile-v2.1.1/`; no legacy orderflow images remain.
- The orderflow simulation uses NIFTY around 23,800 with 2-point price rows.
  A Table switch and row checklist control the seven requested metrics.

Validation: `npm run verify` passes, including **4,139 unit tests** across
176 files, **219 demo tests**, lint, typecheck, package builds, declarations,
size budgets and tree shaking.

Measured 2.1.1 sizes: **66.49 KB** base, **14.96 KB** profile tier and
**186.74 KB** full package, Brotli. The added footprint styles and validation
use a 15 KB profile budget and a 187 KB full-package budget.

## 2.1.0

2026-09-06

### Added

- **Compact TPO letters and volume values.** `MarketProfile` accepts
  `blockDisplay: 'compact'`. An original pixel alphabet preserves distinct
  uppercase and lowercase periods down to 5 physical pixels per row, with
  integer pixel placement. Larger rows use regular canvas text. The renderer
  supports Canvas 2D and SVG export without a WebGL2 dependency.
- **Per-session split/unsplit.** `setSessionSplit(index, boolean | null)` and
  `isSessionSplit(index)` control one session. Overrides follow calendar session
  identity through data updates, row aggregation changes and prepended history.
  An explicit global `setOptions({ split })` resets the overrides.
- **Open and latest-price markers.** `showSessionOpen` draws lowercase `o` at
  each session's opening-price row. `showLastPrice` draws `#` at the newest
  supplied session's latest close, with configurable colours. Both default to
  off in the library and are enabled in the profile demo.
- **Five coordinated demo themes:** Dark, Blue, Graphite, Emerald and Ivory.
  Presets cover the chart, profile, controls, tooltips and markers. These are
  standalone demo presets, applied through existing public APIs.
- **Website profile examples and screenshot gallery.** The website embeds the
  standalone demo, provides links to each theme, and includes reproducible
  screenshots of all five themes plus packed/split close-ups. The
  profile guide, themes guide and examples page link to the new showcase.

### Changed

- The profile demo uses six deterministic synthetic sessions, 2-point rows,
  independent row-height controls and a right-click menu to split or unsplit
  one day. Single-print dashes are disabled in the demo; hover still reports
  the underlying single-print classification.
- Website builds copy the standalone demo and its local bundles, so the
  embedded example runs the same implementation as the development demo.

### Fixed

- Compact glyphs and volume rows are clipped to the plot and remain aligned
  at fractional display scaling. A small rounding tolerance keeps nominal
  5-pixel rows from dropping their letters.
- Open markers reserve space inside profiles. Latest-price markers remain
  visible for narrow and one-bar newest sessions, stay inside the plot width,
  and do not appear on older or horizontally offscreen sessions.
- Changing theme, colour or other display controls preserves per-day split
  choices. The latest-price marker does not overlap the optional TPO counts.

### Validation and sizes

Base engine **66.51 KB**, profile tier **11.95 KB**, full package **183.74 KB**
Brotli. Validation covers **4,026 unit tests** across 172 files and 219 demo tests,
plus browser checks for compact rendering, per-day controls and website examples.

### Website follow-up

- Redesigned the marketing homepage around an interactive chart, with a refined
  dark/light visual system and an intro animation that respects reduced motion.
  Documentation, examples and the generated API reference share the new design.
- Connected the homepage chart to real BTC/USD exchange candles, refreshed every
  15 seconds, with 15-minute, hourly, four-hour and daily views, a Supertrend
  overlay and a separate MACD pane. Connection errors are visible; unavailable
  prices are never replaced with simulated candles.
- Replaced tiny profile overview thumbnails with readable single-day close-ups
  in all five themes. Profile promotion stays on the dedicated guides and examples.
- Added a simulated live depth-of-market demo, working display tick grouping,
  pause/resume, book-depth controls and a README integration example for issue #6.
  Fixed the original standalone depth example's group selector.
- Added an interactive drawing playground with placement, selection, deletion,
  undo/redo and keyboard controls. Example code is available below each chart.
- Regenerated API pages from the current source, with visible package versions,
  navigation back to the guides and demos, and refreshed stylesheet asset URLs.

These website changes use the existing 2.1.0 library APIs.

## 2.0.2

### Added

- **`doubleClick`, a `ChartOptions` key for what a double-click on a pane
  does.** `'reset'` is the default and what the chart has always done: fit
  every loaded bar and autoscale, which also lands the viewport on the oldest
  bar and wakes a history loader, so on a live terminal a double-click fetched
  another page. `'maximize'` toggles the pane under the pointer to the whole
  stack, which is what a multi-pane terminal usually wants from the gesture;
  `'none'` only emits. The `dblclick` event now carries `paneIndex`, `x`, `y`
  and a `handled` flag: a listener that acts on the press itself sets it and
  the chart's own action is skipped. A double-click during placement still
  finishes the shape whatever the option says.


### Sizes

Measured with `npm run size` (Brotli) on the 2.0.2 build: base engine 66.45 KB
against 67 kB, base + trade 74.06 KB against 75 kB, widget terminal 155.09 KB
against 156 kB, everything 182.39 KB against 183 kB. The other six rows did not
move.

## 2.0.1

### Fixed

- **A depth subscription asks for its depth under the key the proxy reads.**
  `formatSubscribe` sent the requested book depth as `depth_level`; the
  OpenAlgo websocket proxy reads `depth`, and the platform's protocol
  reference names `depth`. Every request above the default was therefore
  served at five levels with no error, since five is also the proxy's
  fallback. The frame now carries `depth`, and keeps `depth_level` beside it
  for any consumer that learned the old name from this library. Found while
  wiring the 2.0.0 depth ladder into a host; the ladder was the first caller
  to ask for more than five.

### Sizes

Measured with `npm run size` (Brotli) on the 2.0.1 build: base engine 66.42 KB
against 67 kB, base + trade 74.03 KB against 75 kB, widget terminal 155.06 KB
against 156 kB, everything 182.37 KB against 183 kB. The other six rows did not
move.

## 2.0.0

The drawing model, rebuilt, and the chrome as a package. A `Drawing` now
carries a paint order, a text block and a per-level colour, the controller
selects more than one at a time, and every 1.9.x layout and clipboard body is
upgraded on the way in. The series pass goes through a render backend port
with a WebGL2 backend behind it, the chart exports itself as vector SVG, and
`openalgo-charts/widget` is the eighth tier: the toolbar, rail, dialogs and
shortcuts in one call, so a host that wants a terminal rather than a chart no
longer writes them. A 1.9.x host has a step-by-step guide in
[`docs/migrating-to-2.md`](docs/migrating-to-2.md).

### Breaking changes

- **`DrawingStyle` no longer carries text.** `text`, `fontColor`, `fontWeight`,
  `fontStyle`, `textAlign`, `textVAlign` and `textPosition` moved into their own
  block, `drawing.text` (a `DrawingText`: `value`, `color`, `bold`, `italic`,
  `align`, `valign`, `position`, the font and plate keys), because seven keys
  that only meant something to the eight tools that draw words were sitting on
  every trend line's style bag, and a host could not tell a label from a stroke
  colour without knowing the tool. Tools now merge a `defaultText` under the
  caller's text the way `defaultStyle` merges under style.

- **`style.levels` is `FibLevel[]`, not `number[]`.** Each rung is
  `{ ratio, color?, enabled?, label? }`, so one level can be recoloured,
  relabelled or hidden without rebuilding the ladder. `levelColor(ratio)` is
  the one statement of the conventional colour per ratio (`LEVEL_NEUTRAL` for
  the anchors and for anything unnamed), shared by every fib and gann tool and
  by the migration, so 0.618 reads as the same thing on every tool.

- **`toJSON()` returns `{ version: 2, drawings }`** (a `DrawingsDocument`), and
  `chart.getState().drawings` is therefore a document, because a bare array
  carries no version and could never be told apart from the next shape.
  `fromJSON` still accepts a 1.9.x bare array. `DRAWING_CLIPBOARD_VERSION` is
  now 2 and tracks `DRAWING_STATE_VERSION`; a version 1 clipboard body is
  accepted and upgraded.

- **`Drawing.zIndex` is required on the type** (`add()` fills in 0), and
  **`drawings()` is paint order**, not creation order, because a layer that
  sorts by a field must be able to trust the field is there; `createdAt` keeps
  the creation time and `DrawingInput` is what `add()` accepts.

- **`select()` takes a selection.** `select(id | ids | null, additive)`
  replaces the selection, or with `additive` toggles each id into it;
  `selected()` is now the primary (first-picked) id and `selection()` is the
  whole list. A host that called `select(id)` and read `selected()` sees no
  change; one that assumed the selection had at most one member should read
  `selection()`.

- **`chart.renderer` is `rendererKind`.** The old name stays as the same value,
  but the type is `RenderBackendKind` and it reports the backend the chart
  actually paints with, which differs from the `renderer` option when the
  chosen backend declined or fell back.

### Added

- **`openalgo-charts/widget`, the eighth tier and the only one that ships
  DOM.** `createWidget(container, options)` builds the chart with its chrome
  in one call: a top bar (symbol box with search, interval pills, chart type,
  Indicators, capture, settings, theme), the drawing rail from the draw tier's
  sprite with pins, flyouts, magnet and stay modes, a status line, toasts, a
  keymap with a `?` shortcuts panel and conflict reporting against the
  engine's own table, and optional layout persistence
  (`persist: true | namespace`). Every dialog is generated from a schema the
  engine already ships: chart settings from `chartSettingsSchema`, indicator
  settings from the descriptor, drawing properties from
  `drawingSettingsSchema`, plus an indicator picker, a level editor for the
  fib and gann family, an in-place text editor and a right-click menu that
  offers order entry through `onOrder`, so a control exists only where the
  engine has something behind it. The chrome takes its colours from the
  active `ChartTheme` through `--oac-` tokens, so `setTheme` recolours canvas
  and chrome together. The engine still ships no DOM: the widget is a
  packaged host driving the public API, kept out of every other bundle by the
  ESLint tier ACL and by `npm run shake`, and it must not touch the document
  on import. Exported alongside `createWidget`: the `Widget` handle, the
  `WidgetContext` every mount is handed, the dialog registry
  (`registerWidgetDialog`, `widgetDialog`), the seven `mount*` functions,
  `Keymap`, `mountRail`, `mountTopbar`, `mountStatusline`, `mountToasts`,
  `renderForm`, the token helpers, `WIDGET_TIER`. 35.56 KB Brotli against a
  36 kB budget; base + draw + indicators + widget, what one `createWidget`
  call loads, 155.03 KB against 156 kB.

- **A render backend port, and a WebGL2 backend behind it.** The series pass
  on each pane goes through an `IRenderBackend` (`beginFrame`, `drawSeries`,
  `endFrame`); the shipped `Canvas2dBackend` draws through the pane's own 2D
  context and is pixel-identical to 1.9.2. The `renderer` option
  (`'canvas2d' | 'webgl2' | 'auto'`, default `'canvas2d'`) or an injected
  `renderBackend` factory picks the backend once, at construction, because a
  backend that could change under a frame would have to be checked by every
  renderer. The new `openalgo-charts/webgl` tier (6.38 KB Brotli) registers
  `WebGL2Backend` under `'webgl2'`: every standard chart type is batched into
  one shared offscreen WebGL2 surface with analytic anti-aliasing and
  composited into the pane's base canvas, so screenshots, the SVG export and
  the DOM are unchanged; kagi, point-figure and custom types draw through the
  2D context. An explicit `'webgl2'` throws until the tier is imported and
  falls back to `canvas2d` with one console warning on a device without
  WebGL2; `'auto'` is silent. A lost context or an unusable device moves the
  chart to `canvas2d` for the session and emits `renderer:fallback`
  (`RendererFallbackEvent { from, to, reason }`). Exported alongside:
  `registerRenderBackend`, `unregisterRenderBackend`,
  `registeredRenderBackends`, `resolveRenderBackend`, `createRenderBackend`,
  `backendDegradation`, `candleGeometry`, and from the tier
  `createWebGL2Backend`, `isWebGL2Supported`, `GlDevice`, `sharedGlDevice`,
  `registerWebGL2Renderer`, `WEBGL_TIER`.

- **Vector export.** `chart.exportSVG(options?)` returns the chart as a
  standalone SVG string: the ordinary paint of every pane, run once into a
  serialising 2D context at pixel ratio 1, so axis labels and tags stay text
  and lines stay lines, and there is no second renderer to drift from the
  canvas one. Nothing transient is in it (no crosshair, hover or drag).
  `ExportSvgOptions` takes `width` and `height` (a different size lays the
  chart out for the export and puts the live layout back without a blank
  frame), `background` and `dpr` (only `1`). The context itself,
  `SvgContext`, is exported with `SvgLinearGradient` and `SvgContextOptions`
  for a host that wants to run its own primitive into one.

- **`zIndex`.** Below zero paints under the series, at or above zero over it;
  ties break by list order. `setZIndex`, `bringToFront` and `sendToBack`
  (band-local: they never cross the series), `sendBehindSeries` and
  `bringAboveSeries`. A default of 0 paints exactly where 1.9.2 painted, which
  the render-parity harness checks at zero differing pixels.

- **Multi-select.** `selection()`, `updateMany`, `removeMany`,
  `duplicate(ids)` and `nudge(ids, dx, dy)`. A shift, ctrl or meta click is
  additive (the chart's `click` payload now carries the three flags). A body
  drag on an unselected drawing selects it alone and then moves the whole
  selection as one undo entry, because "move these three together" was three
  drags and three undo steps; locked members stay. New bus events
  `drawing:select { ids }` and `drawing:change { ids, kind }` fire alongside
  the legacy `draw:*` names, which are unchanged.

- **A per-tool settings schema.** `drawingSettingsSchema(toolId)` returns the
  fields a host may show, as dot paths with a control kind, and a tool
  declares only fields its `draw` reads: a control with nothing behind it is
  a defect, not a style choice. `readDrawingSettings` and
  `applyDrawingSettings` move values between a form and a drawing, coercing
  form strings by kind; `composeSettings` and the shared field lists build a
  custom tool's schema. The schema's `textIsContent` flag tells a host which
  tools are their text, so it can ask for it on placement.

- **`migrateDrawings(input)`**, the pure 1.9.x to 2.0 upgrade `fromJSON` runs,
  exported for a host reading a saved layout on its own. Load is lenient
  (anything renderable survives; a malformed optional field is dropped on its
  own) because a saved layout is the user's own work; paste stays strict
  because a paste is foreign input.

- **`keyToDrawingAction(e, ctx)`**, the editing counterpart of
  `matchDrawingShortcut`: undo, redo, copy, cut, paste, duplicate, delete and
  arrow-key nudge as a pure mapping the host wires to the controller. With
  `placing: true` a bare Escape, Enter or Backspace maps to `cancel`, `finish`
  or `popAnchor` first, so Backspace never deletes the selection while an
  anchor is being placed.

- **Drawing feel.** The controller tracks the unselected drawing under the
  pointer from the chart's `hover` event (`hovered()`, `drawing:hover { id }`)
  and the layer paints its handles faintly, so a drawing reads as grabbable
  before it is grabbed. Shift locks the free end of a line to 45 degree steps
  on screen while placing and while dragging a handle
  (`DrawingTool.angleLock`, set on the line family). `magnet` accepts
  `'off' | 'weak' | 'strong'` (`true` still means `'strong'`; `magnetMode()`
  reports the resolved mode): `'weak'` pulls only when an O/H/L/C sits within
  a few pixels, so a click on open space lands where it was made, and either
  mode paints a ring where the next click will land, on the bar's centre.
  `cancel()` and `popAnchor()` join `finish()` as the placement verbs. Grab
  targets grow for a touch pointer (`DrawingLayer.setPointerType`,
  `DrawingPointerKind`).

- **Line readouts.** `style.showStats` on `trend-line`, `ray`,
  `extended-line` and `arrow` adds a midpoint readout: signed change and
  percent, bars between the anchors, and the angle on screen. Off by default.

- **Position tools that place a trade.** `long-position` and `short-position`
  take the entry click and the target click; the second click is also the
  direction, so a release above the entry is a long and below it a short,
  whichever tool was armed. The stop lands opposite the entry at 1:2, sized on
  screen (64 px of risk, 150 px wide) rather than as a fraction of price.
  `DrawingTool.constrain(points, handle)` is new: the anchors to keep after
  one moved, which the position tools use to hold the stop and the target on
  opposite sides of the entry (drag one through the entry and the other
  reflects, so the trade flips with its ratio intact). `ExpandContext` gained
  optional `toPixel` / `fromPixel`, present when the host can map
  coordinates, so an `expand` default can be sized in pixels and fall back to
  chart units. The readouts are direction and R:R, money at risk and size,
  and each zone's move in percent, with `props.showHeader`, `showLossSize`,
  `showTargetLabel`, `showStopLabel`, `showPrices`, `profitColor` and
  `lossColor` as the toggles.
- **Freehand strokes.** The brush and highlighter ink every coalesced pointer
  sample a pressed move carries, thin the trail on release to the corners its
  shape needs, and paint it as a spline, so a fast stroke is a curve rather
  than a chain of chords. A pen stores `DrawingPoint.pressure` per sample (a
  mouse stores nothing) and `style.pressure` lets it drive the width; the
  clipboard and the migration keep the field. The geometry is exported, pure
  and DOM-free: `rdpSimplify`, `catmullRom`, `pressureWidth`.

- **Icons as markup.** Beside the tool path data, a chrome set on a 16 grid
  (`CHROME_ICONS`, `chromeIcon`, `chromeIconIds`, `CHROME_ICON_FILLED`, its
  viewBox, stroke and attribute bag) and string builders that derive from the
  one registry, so a rail, a flyout and the armed cursor cannot drift apart:
  `iconSvg` and `chromeIconSvg` (an inline `<svg>` in `currentColor`),
  `iconSprite` and `iconUse` (one hidden symbol sheet plus per-glyph `<use>`,
  ids under `ICON_SYMBOL_PREFIX`), and `toolCursor` (a CSS `cursor` value
  carrying the glyph over a contrasting halo).

- **Pointer payloads.** `crosshair:move`, `click`, `drag` and `drag:end` now
  report `modifiers`, `pointerType` and `pressure`; `drag` carries `point`
  and coalesced `samples`, `drag:end` carries `point`, and `crosshair:move`
  carries `samples` while pressed, which is how a freehand stroke reads its
  trail in placement mode. Click `pressure` is the press pressure. No
  existing field changed. `PointerModifiers`, `PointerKind`, `PointerSample`,
  `PointerInfo`, `ChartClickEvent`, `ChartDragEvent` and `ChartDragEndEvent`
  are exported from the base entry.

- **An eased wheel zoom, and a right-edge anchor.** A wheel tick used to land
  its whole step on one frame while a flick already glided to a stop, so the
  chart glided when panned and jumped when zoomed. `ZoomGlide` (exported with
  `ZoomGlideOptions` and `DEFAULT_ZOOM_GLIDE_OPTIONS`) eases the zoom in log
  space, folds a new tick into a running glide without a jump, and applies
  the first frame's step on the event itself so `barSpacing` reads its new
  value synchronously. The ease is on by default (`animZoom: true`), which is
  the one visible change for a host that sets nothing; `animZoom: false`
  restores the single-frame step of 1.9.2. `zoomAnchor: 'cursor' | 'right'`
  (`ZoomAnchor`) pins the latest bar under `'right'` so history stretches away
  from it, which is what a live chart usually wants; that default is unchanged.

- Named descriptors for the tools the entry did not name: `FORECAST`,
  `PRICE_RANGE`, `DATE_RANGE`, `CIRCLE`, `TRIANGLE`, `POLYLINE`, `ARC`, `CURVE`,
  `ROTATED_RECTANGLE`, `DOUBLE_CURVE`, `HIGHLIGHTER`, `BRUSH`, `FIB_CHANNEL`,
  `FIB_TIME_ZONE`, `FIB_FAN`, `GANN_FAN`, `GANN_BOX`, `CYCLIC_LINES`,
  `TIME_CYCLES`, `SINE_LINE`; `boundsOf` from the geometry helpers;
  `cloneDrawing` from the clipboard.

### Changed

- **A wheel zoom eases by default.** `animZoom` is `true` unless the host says
  otherwise, so a 1.9.x host sees its wheel zoom glide over a few frames
  instead of landing on one. The bar spacing it lands on is the same, and
  `barSpacing` still moves on the event itself; `animZoom: false` restores the
  single-frame step. Section 8 of
  [`docs/migrating-to-2.md`](docs/migrating-to-2.md).

- **A position box is two clicks, not one.** In 1.9.x one click dropped a
  1:1 box at 1% of price either way. New placements take the entry and the
  target and derive the stop; a 1.9.x box that was saved loads unchanged, with
  the same `[entry, target, stop]` anchor order.
- **The yfinance demo is a native-ESM host on the 2.0 drawing tier.** One
  5,677-line page became markup, one stylesheet and thirty modules that import
  `/dist/openalgo-charts.mjs` and its tier files by the URL a page would use,
  so the demo proves the published shape. The rail and its flyouts render from
  the tier's sprite, cursors and chord table; the properties bar is generated
  from `drawingSettingsSchema`; the shell has toasts, an overlay stack, a
  loading, empty and error card, a light theme, a typed feed with retries and
  per-slot cancellation, and a versioned layout document with migrations. The
  demo carries its own vitest config (`npm run test:demo`, part of
  `npm run verify`) and `server.py` gained `--fixture`, `--self-test` and
  validated parameters.

- The demo's text dialog moves to `drawing.text`, and its Duplicate button
  uses the controller's `duplicate`, which also carries text and props along
  (the hand-rolled copy dropped both).

### Fixed

- Fib retracement and extension stroke their anchor leg in `style.color`, so
  the colour control has a job; their bands are tinted by the level that
  closes them; `extendLeft` is honoured by retracement, extension and channel.
- `price-range` and `date-range` honour `showLabels`, which was declared but
  never read.
- Flag mark and arrow markers honour `style.fill = false`.
- Circle, triangle and rotated rectangle carry a shape label like rectangle
  and ellipse; the text tool honours `valign` as its vertical anchor.
- A chart-type switch in the demo came up without the watermark because
  `render()` never let go of the destroyed chart's handle.

### Performance

- **Candles skip the body fill once the wick already covers it.** At tight
  zoom `optimalBarWidth` collapses body and wick to the same width and x, so
  the body fill repainted pixels the wick had just painted in the same colour;
  `candleTier()` names the condition and `drawCandles` does one `fillRect`
  per candle instead of two, which is where a chart draws the most of them.
  Nothing changes at normal zoom, and the render-parity harness holds it at
  zero differing pixels.
- **Hovering a drawing costs the overlay tier only.** Both drawing layers are
  `'top'` primitives, so a hover change that touches only `'top'` hits raises
  a Cursor invalidation rather than Light: the pointer moves sixty times a
  second, and repainting the series for a line it merely passes over was a
  stutter. A base-canvas primitive keeps its Light repaint on enter and leave.
- **Dragging an under-series drawing lifts it to the top layer** for the
  gesture, so the base tier is not repainted per frame.
- **One draw call per frame on the GPU.** The WebGL2 backend batches every
  series of a pane into one shared page-wide surface, so a dashboard of
  multi-pane charts no longer spends its frame budget on the series pass, and
  it never opens more than one GL context however many panes are on the page.
- Freehand samples are projected through one `getBoundingClientRect` and one
  pane layout per event rather than per sample.

### Internal

- **ESLint, and the tier boundary fails the build.** The package's shape is
  eight lazily loaded bundles with enforced budgets, which only holds while the
  base never reaches into a lazy tier; prose in ARCHITECTURE.md did not fail
  CI, and one stray import would have pulled the indicator tier into the base
  with nothing going red. The ACL names its two existing crossings and rejects
  every other one, rejects a relative import of `../core` or `../draw` from
  `src/widget` (which would inline a second `Chart`), and rejects any import
  of the widget from another tier. `npm run lint` runs first in
  `npm run verify`.
- **A render-parity harness.** `scripts/build-baseline.mjs` builds a reference
  `dist` from another git ref and `tests/e2e/render-parity.spec.ts` renders
  both in one real browser and compares canvases pixel for pixel across seven
  bar spacings, because two shipped defects had passed a fully green unit
  suite. `tests/e2e/webgl-parity.spec.ts` diffs the GPU backend against the 2D
  one for every native type and asserts a real draw call happened, so a silent
  2D fallback cannot pass it; `tests/e2e/widget.spec.ts` mounts the built
  widget tier from the static server and checks the chrome painted.
- `check-dts` fails a widget declaration file that declares
  `DrawingController`; `check-shake` asserts the `oac-widget` CSS scope and
  the context-loss listener are absent from a chart-only build; the skills
  coverage script imports every built tier under Node, so a module-scope
  `document` access fails the release.
- `tests/renderer-option.test.ts` walks the import graph from the base entry
  and fails if it ever reaches `src/render/webgl`.
- The e2e suite records why sub-pixel bar spacings are not tested: the time
  scale clamps to `minBarSpacing`, so every spacing below 1 renders as 1,
  which also makes `conflate` inert at default settings.
- The last typedoc warning in the tree is gone, so the API reference builds
  clean with every tier as an entry point.

### Sizes

Measured with `npm run size` (Brotli) on the 2.0.0 build: base engine
66.39 KB against 67 kB (a 62 kB budget in 1.9.2, raised for the zoom glide,
the pointer payloads, the SVG serialiser and the render backend port);
base + trade 74.00 KB against 75 kB; draw tier 25.82 KB against 26 kB
(15.39 KB against 16 kB in 1.9.2, grown for the schema, the level palette, the
migration, the key map, the multi-select controller, the interaction feel,
the freehand geometry, the icon builders and the two-click position tool); webgl tier 6.38 KB against
7 kB; widget tier 35.56 KB against 36 kB; a widget terminal (base + draw +
indicators + widget) 155.03 KB against 156 kB; everything 182.34 KB against
183 kB (a 126 kB budget in 1.9.2). The indicator, transform and
profile tiers did not move. Chart-only shake 43.84 kB against 44 kB. Tool
count is unchanged at 51; 3999 tests across 170 files.

## 1.9.2

Eight annotation tools, and the icon set that was missing for all of them.

### Added

- **Annotations: `note`, `balloon`, `comment`, `signpost`, `price-note` and
  `table`**, plus `arrow-left` and `arrow-right`. 43 tools to 51.

  They share plate-and-tail machinery, so what separates them is where the tail
  leaves the plate and how the plate is shaped: a note pins a bar and sits its
  text up-right, a balloon floats above with the tail pointing down, a comment
  is the quiet square version, and a signpost stands a post on the bar so its
  plate can clear the price action entirely. That last one is anchored to
  **time** rather than to a level, which is what an event needs.

  `price-note` reads its price off the anchor rather than storing one, the same
  as `price-label`: a typed price is a number that was true once, which on a
  chart is worse than no number at all. `table` encodes its cells in
  `style.text` with a newline per row and a pipe between columns, so a whole
  table is one editable string and needs no new shape in the drawing model.

  `arrowMarker` was hard-wired to a boolean up/down, which cannot express left
  or right; it now takes an axis.

- **An icon for every drawing tool**, as path data: `DRAWING_TOOL_ICONS`,
  `drawingToolIcon(id)`, `drawingToolIconIds()`, and `ICON_ATTRS` carrying the
  attribute bag a host puts on the `<svg>`.

  The engine still ships no DOM. These are strings, and the host still builds
  its own rail, flyouts and toolbar. What it no longer does is draw fifty-one
  glyphs before it can show one, which is what every adopter had to do: the
  demo drew its own set, the reference terminal drew another, and each drifted
  on stroke weight, grid and density independently until the result read as
  fifty-one icons rather than as one set. A shipped set is worth more than a
  better glyph.

  Every glyph is authored to one grid, and `tests/draw-icons.test.ts` holds all
  of it mechanically: a 24 viewBox, a live area of 2 to 22, whole-unit
  coordinates, a single stroke weight, round caps and joins, a complexity
  ceiling, a minimum span, and no two glyphs drawing the same thing. A set of
  this size cannot be kept consistent by review, and those checks caught two
  faults on their first run that reading the paths had not: a spiral whose arc
  chain landed the pen outside the box, and the same glyph then filling only
  nine units of it.

  **Render at 24px or an integer multiple.** With a 2-unit stroke on whole
  coordinates, an orthogonal edge covers exactly two device pixels at 1:1. At
  18px the 0.75 scale puts it on 1.5 pixels and every edge is anti-aliased
  across two rows. That is a host sizing choice, and no path data can fix it:
  it is why a hand-drawn set at a 1.5 stroke on whole coordinates never looked
  crisp at any size.

### Changed

- The draw tier's budget goes from 14 to 16 kB for the eight tools and the icon
  set, measured at 15.39 kB. The pattern clusters still to come (Elliott,
  harmonics, pitchforks) are a sub-tier decision rather than another raise.

## 1.9.1

The legend and the axis name the same number, so they now spell it the same way.

Released as 1.9.1 rather than 1.9.0 at the maintainer's request.

### Fixed

- **An indicator legend disagreed with the axis beside it.** Seen on a live
  chart: a Supertrend legend read `1034.0` next to a price axis reading
  `1029.20`, and a Williams VIX Fix legend read `0.618` next to its own axis
  reading `0.62`. The two sit inches apart and describe the same quantity, so a
  reader is left to reconcile them with nothing to say which is right.

  The legend held a second opinion: it worked its format out from the pane's
  tick size, which is wrong in both directions. A study pane carries no tick at
  all since 1.8.9 stopped the instrument's reaching it, so the legend fell
  through to a magnitude ladder written for volume columns and printed three
  significant figures. And a price pane's tick alone knows nothing about the
  two-decimal floor or a host's own price formatter, so a volume study printed
  seven digits of share count where its axis said `1.20M`.

  The axis already answers all of that, so the legend asks it: `IndicatorHost`
  gains an optional `formatPrice(paneIndex, value)`, which `Chart` answers from
  that pane's price scale. One source of truth rather than two derivations that
  agree by luck. The magnitude ladder stays as the fallback for a host driving
  the indicator runtime without a chart.

## 1.8.9

Indicator precision, reported as one indicator reading `0.6` where it should read
`0.61`, and found to be wrong for a whole class of them.

### Fixed

- **A study pane was formatted in the instrument's tick size.**
  `Chart.setPriceScaleOptions` documents `'primary'` scope as "each pane's right
  scale only", and that is literally what it did: *every* pane's right scale,
  not just pane 0's. A host pushing the instrument's tick down chart-wide, which
  is the ordinary thing to do on a symbol change, therefore set the decimals on
  every study pane too.

  That is a category error. A tick size belongs to the instrument. An RSI is a
  dimensionless 0..100 band and a Williams VIX Fix is a percentage; neither
  trades in the instrument's tick. With a 0.10 tick the RSI axis read
  `70.0 / 50.0 / 30.0` and the VIX Fix read `0.6`, in both cases a precision
  nobody chose.

  `minMove` is now the one field in the chart-wide block withheld from a pane
  that does not quote the instrument. Pane 0 is one from birth, so a caller who
  configures nothing sees byte-identical behaviour there; any other pane starts
  out a study's until a host plots a price series on it, which promotes it and
  hands it the tick. Scope semantics are unchanged for every other field.

- **A study pane inferring precision from its own span still read too coarse.**
  Withholding the tick is only half the answer: a 0..100 band implies a step of
  one whole point, so the ladder was labelled `70` and a reading of 62.24 rounded
  to `62`, past the part a trader comparing it to the level is looking at. Those
  panes now carry `minPrecision: 2`, the same floor the percent-rebase branch has
  always used. The floor lifts above five integer digits, where a decimal stops
  being information: a cumulative study like OBV keeps its integer form, and a
  study living inside a tenth of a point still gets its third decimal.

  So an overlay study prints at the instrument's tick and a study on its own
  pane prints at two decimals or finer. **Custom descriptors get this with
  nothing to declare**, because the rule is keyed on the pane an indicator is
  handed rather than on anything in the descriptor. Checked by sweeping the
  registry rather than by fixing the two that were noticed.

- **A click on a primitive fired twice.** `_onPointerMove` ends a gesture itself
  when it finds the button already released, because a release over a context
  menu or outside the window never arrives. The real `pointerup` still lands
  afterwards, found no drag armed, and fell through to the plain click path to
  fire the same click again at the stale press coordinates. Every control
  addressed by `subscribeClick` doubled: an indicator legend's hide, maximize and
  move-pane, a comparison row's remove, an order pill's cancel. A toggle that
  fires twice is a control that looks dead. A gesture now ends once.

### Demo

`examples/yfinance/` gains a volume on/off control and real tooltips on its
icon-only controls. The tooltip it replaces was clipped at the rail's edge by an
`overflow-x` the rail never asked for, and the "double-click to keep the tool
active" line it shows is now wired rather than merely claimed.

## 1.8.8

Documentation and package metadata. No engine change: every number this library
draws is identical to 1.8.7.

### Added

- **A CDN guide**, and the two package fields that make the short URL work.

  Every release has been on unpkg and jsDelivr since it was first published,
  because both sit in front of npm rather than being places you upload to. But
  nothing in the docs said so, and `https://unpkg.com/openalgo-charts` returned a
  404: with no `main` (this package is ESM-first, through `exports`) the bare URL
  had nothing to resolve to. `unpkg` and `jsdelivr` now point at the standalone
  build, so it resolves.

  The new page leads with the module form, which is the one to reach for: import
  each tier straight from a URL and a chart carrying all 102 indicators is a
  single HTML file with no build step, no bundler and no install.

  It also writes down the two things the usual CDN-publishing advice gets wrong
  for this library. There is no stylesheet, because the engine ships no DOM, so
  the `<link rel="stylesheet">` such guides recommend would 404 on a file that
  does not exist and is not meant to. And there is no CDN deployment step to
  perform, because unpkg and jsDelivr mirror npm.

  The standalone script is documented for what it is: **base tier only**. There
  is no `registerBuiltinIndicators` on that global, so no built-in indicators and
  no drawing tools come with it. It exists for a page that cannot load modules.

## 1.8.7

Market replay, reported broken from a live terminal and rebuilt around the
question it exists to ask: from here, what happens next?

### Fixed

- **Entering replay drew an empty chart.** The data was there and the price axis
  was measured correctly; the viewport sat about 280 bars to the left of every
  bar. An indicator's plots are series in the same data layer, so
  `dataLayer.baseIndex` counts them, and 1.8.5 deferred indicator recompute to
  the frame. After replay truncated the price series to a prefix, the indicator's
  own series stayed at full length for the rest of the turn and held the base
  index up with it. A host that truncates and then positions the viewport in the
  same turn, which is exactly what entering replay does, converted its logical
  range against a base index hundreds of bars too high.

  A wholesale `setData` now recomputes before the base index is read. The tick
  path stays deferred, which is where the coalescing earns its keep: an appended
  bar makes the primary the longest series, so the base index is already right
  with the indicator a bar behind, and a burst of ticks between two frames still
  costs one recompute. Measured unchanged on the benchmark.

### Added

- **Intra-bar replay.** `ReplayController` takes `subBars`, the finer session
  the displayed bars are built from, and steps a sub-bar at a time so the newest
  bar forms in front of the user instead of landing complete. One 5-minute bar
  over 1-minute data takes five steps. Without it, every step lands a finished
  candle and the moment a trader is practising for, watching a bar build and
  deciding before it closes, never happens.

  A bucket closes on the displayed bar **verbatim** rather than on the aggregate,
  so two feeds that disagree mid-bar still agree on every close and a replayed
  session ends where the plain one does. `ReplayState` gains `subIndex` and
  `subSteps`, and its `bar` is the partial one while a bar is forming, which is
  what a host drives its own forming volume bar from. Followers stop at the last
  completed bucket: a volume histogram is summed and a candle is merged, and the
  controller is not told which it has. A seek still lands on a completed bar.

- **`TextWatermark`**, a word stamped faintly across the plot to say what mode
  the chart is in. A chart replaying August looks exactly like a chart showing
  today, and reading a live decision off history is the mistake it prevents. It
  shrinks to fit a narrow pane, hit-tests to nothing, and is captured by
  `takeScreenshot()` because it is drawn on the canvas rather than over it.

- **`ReplayShade`**, which dims every bar after an index and rules a line at the
  cut. Choosing a replay start while the next twenty bars are readable is
  choosing on hindsight, which is the one thing replay exists to remove. Add one
  per pane: a bright volume pane gives away what the price pane is hiding.

### Demo

`examples/yfinance/` now shows the whole flow, which is where all of the above
was proved: press Replay and pick a start bar with the future greyed across
every pane, walk it with a sub-bar counter in the transport, and leave through a
confirm rather than losing the playhead to a mis-click. A snapshot menu next to
it saves or copies the chart as a PNG, watermark included.

## 1.8.6

Both items are about the same thing: an indicator that has computed a number
should say what that number is, at the precision the instrument trades in. No
indicator maths changed.

### Added

- **Every plotted series now carries its current value as a tag on the price
  axis.** A study drew its line to the right edge and then said nothing about
  where it actually sat, so reading a Supertrend stop off the chart meant tracing
  the line back by eye against the ladder. The pane collected one tag and
  stopped, which meant the instrument claimed the only slot and every overlay,
  every indicator plot and every comparison series was skipped.

  A tag is drawn in its own plot's colour, formatted by the same scale as the
  ticks beside it, for any series on the pane's readout scale: an overlay on the
  price pane, a study on a pane of its own, a volume histogram on its own pane.
  A plot whose current value is `na` draws nothing rather than showing the last
  number it happened to have, so a flipped Supertrend tags one half and not both.
  Set `lastValueVisible: false` on a series style to opt out, the same flag that
  has always controlled the instrument's own tag.

  Tags are resolved against each other and against the ladder by the existing
  priority table, with a new `seriesValue` rank between `previousClose` and
  `tick`: two studies a rupee apart do not print over one another, a tag
  suppresses the plain tick it would otherwise sit on, and the last-price tag
  outranks all of them.

### Fixed

- **The legend rounded a four-figure price to whole numbers.** A Supertrend at
  1339.70 read `1340` in the legend while the price axis two inches away read
  1339.70. The legend formatter was a magnitude ladder written for volume
  columns, and one of its rungs rounds anything at or above 1000 to no decimals:
  fine for 12.35M of turnover, wrong for a price, and 0.30 out for anyone reading
  a stop off it. The legend now formats to the precision the pane's tick implies,
  which is the precision the axis prints. Panes with no tick, volume and open
  interest among them, keep the compacting ladder, and a `minMove` of 0 still
  means "infer" rather than "no decimals".

## 1.8.5

Three axis defects, all reported off a live chart placed side by side with a
professional terminal. No indicator maths changed.

### Fixed

- **The price ladder printed six labels whatever the pane measured.** A 700 px
  pane read one price every 120 px where the reference terminal read one every
  30, so a trader taking a level off the axis was interpolating between rungs
  hundreds of points apart. The count now follows the pane height at a fixed
  spacing (`PRICE_LABEL_SPACING`, 32 px), which puts about twenty prices on that
  same pane instead of five. Both are internal, like the axis renderer they
  serve; `PriceScale.ticks(maxTicks)` stays public and unchanged.

  A denser ladder has one visible consequence, and it matches the reference: the
  last-price tag now always suppresses the label next to it, because rungs sit
  about a tag-height apart. Suppression was already the rule, there was simply
  usually nothing close enough to suppress.

- **A session that had just opened carried no date.** Time-axis labels were only
  ever placed on the regular grid, so when a new day had fewer bars than the grid
  stride, no tick landed inside it and the date was never drawn: today's bars sat
  under yesterday's date with nothing marking the change. The first bar of a new
  day is now always a candidate, and it outranks the grid tick beside it, which
  is why a terminal prints "Sep" between two hourly labels rather than on the
  hour. Labels are resolved by priority and drawn left to right.

- **Bars painted into the price axis.** Nothing clipped the plot, and a bar is
  positioned by its centre and drawn outward, so the newest one against the right
  edge put half a body and a wick into the axis strip, behind the labels.
  Scrolling the series under the axis made it obvious. The plot is now clipped
  for series and primitives, and the clip is released before the ladder, the
  last-price tag and the trading pills, which live in that strip on purpose.

### Sizes

| Bundle | Limit | Actual |
|---|---|---|
| Base engine | 60 KB | 59.38 KB |
| Base + trade | 68 KB | 66.99 KB |
| Indicators tier | 30 KB | 27.27 KB |
| Draw tier | 14 KB | 13.13 KB |
| Transform tier | 5 KB | 2.66 KB |
| Profile tier | 11 KB | 10.66 KB |
| **Everything** | **124 KB** | **120.7 KB** |

The tree-shaken chart-only budget is now close: 37.89 KB against 38.00 KB.

2420 tests across 131 files.

## 1.8.4

A performance release. No indicator maths changed and no public surface moved:
every number this engine draws is the same as in 1.8.3.

### Changed

- **Indicator recompute is scheduled with the frame instead of the data update.**
  It ran synchronously inside `updateBar`, so a burst of live ticks spent a full
  pass over every bar, for every indicator, on every tick, and threw all but the
  last away unseen. Rendering was already coalesced into a frame; the maths was
  not.

  Measured on a 1875-bar chart, 50 ticks arriving between two frames:

  | | recomputes per indicator | burst |
  | --- | --: | --- |
  | before | 50 | typical 175 ms, heavy 643 ms |
  | after | 1 | typical 7 ms, heavy 21 ms |

  That is 24x on a five indicator chart and 31x on a ten indicator one. 643 ms
  of blocked main thread is roughly 38 dropped frames from a single burst, which
  is what a trader sees as jank at the open.

  **Deferring the maths does not defer the answer.** `chart.indicators()` and
  `IndicatorInstance.values()` both flush any pending recompute before returning,
  through a new optional `flushIndicators()` on `IndicatorHost`. A caller that
  updates a bar and reads the value back in the same turn still gets the fresh
  number. The hook is optional, so a host that implements `IndicatorHost` itself
  needs no change.

  This bounds recompute by the display refresh rather than by the tick rate. It
  does not make a recompute cheaper, so a host still pays once per frame for
  whatever history it has loaded.

### Added

- `npm run bench`, an indicator performance benchmark, now running in CI. The
  test suite proves the numbers an indicator produces and never the cost of
  producing them, so an algorithmic regression shipped silently before this.
  Budgets are a tenfold guard rather than a tight bound.
- `npm run soak`, a teardown and long-session memory harness. Measured: 1.30 kB
  retained per chart over 300 create and destroy cycles, and a heap flat across
  20,000 ticks (+9.4 bytes per tick, about 0.80 MB over a full trading session).
  Deliberately not in the CI gate: heap thresholds on a shared runner are flaky,
  and a memory test that cries wolf teaches people to ignore memory tests.

### Fixed

- Three documentation surfaces stated that `npm run size` was failing on the
  indicator tier and the aggregate row. That was true for the hour between the
  1.8.3 additions landing and the budgets being raised, and it never shipped.

### Sizes

| Bundle | Limit | Actual |
|---|---|---|
| Base engine | 60 KB | 59.2 KB |
| Base + trade | 68 KB | 66.81 KB |
| Indicators tier | 30 KB | 27.27 KB |
| Draw tier | 14 KB | 13.13 KB |
| Transform tier | 5 KB | 2.66 KB |
| Profile tier | 11 KB | 10.66 KB |
| **Everything** | **124 KB** | **120.53 KB** |

2411 tests across 130 files.

## 1.8.3

Eleven indicators added, taking the registry from 91 to 102, and every one of them
measured against the standard definition bar by bar rather than eyeballed. The
same harness was turned on the built-ins that were already shipping, which is
where this release earns its keep: three of them were wrong, and one had been
wrong since it was written.

**Read the Upgrading section before you take this.** Several studies now start
later than they used to and several defaults moved to the values the standard
definition pairs them with, so a saved chart will look different. Both changes
are deliberate and both make the old picture the wrong one.

### Added

Five volatility studies, five trend studies and one volume study. Each was built
from the published definition and then measured against it across 600 bars, at
the shipped defaults and at two or three other parameter sets, comparing every
plot on every bar and the warmup index on both sides.

- **Standard Error Bands** (`standard-error-bands`, Volatility, price pane).
  Upper, basis and lower with a shaded fill. The residual standard error
  `sqrt((Syy - Sxy^2/Sxx)/(periods - 2))` about the least-squares line, placed on
  the **regression endpoint** (the fitted value at the newest bar of the window)
  and only then smoothed, each leg independently. That ordering is the whole
  study: smoothing first and fitting after gives a different, wrong line. First
  print at `(periods - 1) + (averagePeriods - 1)`, so bar 22 at the 21/2/Simple/3
  defaults. Inputs: periods 21, errors 2, method Simple / Exponential / Weighted,
  averagePeriods 3, plus basis, band and fill colours. Worst relative difference
  against the standard definition 5.19e-15 at the defaults, 9.32e-16 and 1.32e-15
  at two other parameter sets.

- **Moving Average Channel** (`ma-channel`, Volatility, price pane). A simple
  mean of the **highs** and a simple mean of the **lows**, each with its own
  length and its own plot-time displacement, with a fill between them. Not a mean
  of the close with a spread bolted on, which is the shape it is usually mistaken
  for. The two legs warm up independently, so lengths 34 and 13 first print at
  bars 33 and 12. Worst relative difference 1.76e-15 on the upper leg and
  8.82e-16 on the lower.

- **Chaikin Volatility** (`chaikin-volatility`, Volatility, own pane). The rate
  of change of a smoothed high-low range: `roc(ema(high - low, periods),
  rocLookback)`, with a dashed zero level. First print at
  `(periods - 1) + rocLookback`, bar 19 at the 10/10 defaults. Bit-exact against
  the standard definition, worst relative difference 0.

- **Standard Deviation** (`standard-deviation`, Volatility, own pane).
  **Population** standard deviation of the close, dividing by `n` rather than
  `n - 1`, times a `deviations` multiplier. The population-against-sample
  question is the only thing that can be wrong here and it was settled by
  measurement rather than by reading: at fixture bar 4 the population reading is
  1.5514425743803728 and the sample reading would be 1.7346. Worst relative
  difference 2.77e-16.

- **Standard Error** (`standard-error`, Volatility, own pane). The residual
  spread of the closes about the least-squares line fitted through them. The
  divisor is `length - 2` because the fitted slope and intercept each consume a
  degree of freedom, which is what makes this a standard error rather than a
  standard deviation, and is why the input floor is 3 and not 1. Bit-exact
  against the standard definition at length 14 and at 34.

- **Linear Regression Slope** (`linreg-slope`, Trend, own pane). The ordinary
  least-squares gradient of close against bar position over a trailing window, in
  price per bar, with a dashed zero level. Nothing rescales the result, so the
  reading is in the instrument's own units and a slope of 0.67 means 67 paise a
  bar. Bit-exact at periods 14, 7, 2 and 50.

- **Smoothed Moving Average** (`smma`, Trend, price pane). Wilder's smoother with
  `alpha = 1 / length`, seeded from the simple average of the first `length`
  source values. That recursion is exactly what `rma` already does, so the
  descriptor adds no arithmetic of its own. Selectable source (open, high, low,
  close, hl2, hlc3, ohlc4), default length 7. Worst relative difference 2.26e-16
  across three parameter sets.

- **Net Volume** (`net-volume`, Volume, own pane). The bar's own volume signed by
  the direction its close took: up gives `+volume`, down gives `-volume`, an
  unchanged close gives 0. Bitwise identical to the standard definition on all
  600 fixture bars.

  **It has no warmup**, which is the load-bearing detail and the one an
  implementation gets wrong. Bar 0 has no previous close, so neither comparison
  can hold and the definition falls through to its zero arm; returning `null`
  there instead would be a defect, and the test pins bar 0 at 0.

  One presentation choice is ours rather than the definition's, and is flagged
  rather than hidden: it draws as a **histogram with base 0**, not as a line.
  This is a per-bar signed quantity that flips sign every few bars, and a line
  drawn through it is unreadable. The sibling volume descriptor is already a
  histogram with base 0, so this matches the house shape. The numbers are
  identical either way.

Three more trend studies landed late in the release, after the eight above were
already measured. They were built the same way, from the published definition and
then checked bar by bar against it.

- **T3 Average** (`t3`, Trend, price pane). A generalised double average applied
  three times over. One layer is `e1 * (1 + factor) - e2 * factor`, where `e1` is
  the SMA-seeded exponential average of the source and `e2` is that average of
  `e1`, so the layer sits exactly `factor` of its own lag ahead of a plain
  exponential average, and at `factor = 1` it is a DEMA. Cubing that expression
  gives terms of exponential depth three to six, and a slot is only finite where
  its deepest term is, so the warmup is `6 * (length - 1)`: bar 24 at the default
  length of 5, bar 12 at 3, bar 120 at 21, and bar 0 at length 1, where every
  average is the identity and T3 is the source. Inputs: length 5, factor 0.7,
  source, a Highlight Movements switch and three colours; with the switch on the
  line takes the rising or falling colour per bar and holds the neutral colour on
  an unchanged value.

  One deviation from literal arithmetic, flagged rather than buried: at
  `factor = 0` the layer returns `e1` instead of computing `e1 * 1 - e2 * 0`.
  Multiplying by zero would still let the second average's warmup blank a further
  `length - 1` bars of a line that has by then collapsed to a plain chained
  average. Nothing with a live factor touches that branch.

- **Hull Suite** (`hull-suite`, Trend, price pane). One overlay carrying three
  variations of the Hull average, the same line displaced two bars, and the band
  between them. `Hma` is `wma(2 * wma(n / 2) - wma(n), round(sqrt(n)))`; `Ehma`
  is the same shape with the SMA-seeded exponential average in place of both
  weighted passes; `Thma` is `wma(3 * wma(n / 3) - wma(n / 2) - wma(n), n)`,
  smoothed over the full window rather than its root, and is therefore handed
  **half** the configured length. First print at bar 60 for Hma and Ehma at the
  default length of 55 (a weighted average over 55 prints at bar 54 and the outer
  pass over `round(sqrt(55)) = 7` needs six more) and at bar 52 for Thma, whose
  windows are all 27. The floor inside and the round outside are both
  load-bearing and are pinned: at length 63, `round(sqrt(63)) = 8` puts the first
  value at bar 69 where flooring would put it at 68. Inputs: source, variation,
  length 55, length multiplier 1, colour the hull by trend, colour the candles by
  trend (off), show the band, and three colours. Both plots, the band and the
  candle colours read the undisplaced line only, so they cannot disagree, and
  hiding the band changes no colour.

  **Three controls the published definition carries are deliberately absent,
  because this engine cannot back them, and a control with nothing behind it is
  worse than an absent one.** A higher-timeframe mode with its own resolution
  input: `calc` is handed the chart's own bars and has no way to ask for another
  resolution. A line-thickness input: `style.lineWidth` is static in a plot
  descriptor and no settings key stands behind it, so the control would move
  nothing (both lines ship at 2). A band-transparency input: a fill's opacity is
  a fixed number in the descriptor rather than a settings key, so the band is
  fixed at 0.6.

- **Consolidation and Breakout** (`consolidation-breakout`, Trend, price pane).
  An inside-bar state machine rather than a formula. One carried index names the
  mother bar whose high and low define the current range; every later bar whose
  **body** (open to close, wicks ignored) sits inside that range extends the
  consolidation and is tinted, and the first body to escape it fires a marker and
  becomes the new mother. Two rails plot the live range and go null between
  consolidations, so two disconnected rails read as two separate ranges.

  The two reads of that index straddle the reassignment, and that ordering is the
  study: the break test reads the range as it stood before this bar could claim
  it, while the rails and the tint read it after. One bar therefore both fires
  its marker against the range it left and opens the next one. Collapsing the two
  into a single read shifts every signal by a bar and still looks plausible on a
  chart, so `tests/study-consolidation.test.ts` pins the breaking bar itself.

  The freshness gates are the definition's constants, not inputs, because neither
  has a reading a user would tune: a body that escapes the bar immediately after
  a new mother is that mother's own follow-through, and a range still standing
  250 bars later has stopped being a consolidation. No warmup: bar 0 is the one
  bar where the seeded index and the reassignment agree, so it prints its own high
  and low and starts the first range. Inputs: mark breakouts, tint inside bars,
  and four colours. Markers are `triangleUp` below the bar and `triangleDown`
  above it. The two range lines are fixed at `lineWidth` 2 for the same reason
  Hull Suite's are.

### Fixed

Four defects found by measuring shipped built-ins against the standard
definition. All four are now exact.

- **EMA emitted a value from bar 0 and was wrong for the whole warmup.** The
  descriptor called the base bundle's `ema()`, which seeds from `values[0]`: the
  first reading was a single price wearing a moving average's name, and the error
  decayed rather than stopping. At length 14 that was 155 mismatching bars with
  the worst relative error, 6.9e-4, landing on bar 13, the seed bar itself.

  It now uses `smaSeededEma`, seeding from the simple average of the first
  `length` closes and printing nothing before bar `length - 1`, which is what the
  standard definition does and what every other EMA in the tier was already
  doing. Zero mismatching bars afterwards. The public base `ema()` is deliberately
  untouched: it is documented API matching `openalgo.ta` and it is not this
  descriptor's business to redefine it.

- **Parabolic SAR flipped trend on the bar that established it.** Two ordering
  faults, worth 39 mismatching bars of 600 and a worst relative error of 1.1e-2.
  The stop was propagated, clamped and tested for a reversal on the **seed bar**,
  so the seed could reverse the trend it had just set; and the stop was clamped
  into the prior two bars' range **before** the reversal test, so a stop pulled
  back below the bar could no longer be breached and flips the definition calls
  for were silently dropped. The seed bar now carries the seed and nothing else,
  and the order is propagate, reverse, accelerate, clamp. Zero mismatches
  afterwards.

  One deviation is kept deliberately: at bar index 2 the reference
  implementation skips the second clamp bar and we clamp against both previous
  bars, as Wilder's rule states. Both variants were measured and they are identical on the fixture, so
  this costs no parity.

- **ADX blanked itself for the rest of the chart after a single flat bar.** With
  a DI length of 1, a bar whose true range is exactly 0 (an instrument locked at
  one price: a circuit freeze, a halt, an illiquid strike) dropped +DI, -DI and
  DX to a gap. Our ADX is a Wilder average over DX, so one gap poisons the
  recursion and the ADX line never comes back. The last finite pair is now held
  across a zero or absent smoothed true range, which is what the standard
  definition does, and the line survives the halt.

- **HMA was a fifth of a bar early at every odd length.** The Hull average halves
  its length and feeds that to a weighted average. We floored the half, so a
  length of 9 asked for a 4-bar window where the standard definition asks for a
  4.5-bar one: five bars weighted 4.5, 3.5, 2.5, 1.5, 0.5. Flooring shortens the
  fast leg's lag from 1.2 bars to 1, and the three passes then cancel to zero lag
  instead of the correct 0.4, so the line sat 0.4 slopes high. Even lengths were
  always exact, which is why this survived: the default of 9 is odd, and the
  error is a smooth 4.6e-3 at the default, never a visible break.

  The half period is now carried at full precision. The outer period still floors
  its square root, which is what the standard definition does and is not the same
  question. Measured after the fix at lengths 9, 13, 16, 21 and 55: exact on
  every bar, with the warmup index unchanged on both sides.

The previous pass in this release fixed five more, all user-visible for the same
reasons: **MACD** legs are SMA-seeded EMAs (warmup moves), **ADX** seeds its true
range correctly (warmup moves), **Fisher Transform** gained a flat-window floor,
**Chop Zone** takes its range off the high series, and **Special K** carries the
full 12-term table (warmup moves a long way, see below).

### Changed

Ten defaults across eight indicators now match the values the standard definition
pairs them with. These are defaults only: an explicitly configured setting, and a
saved layout that recorded one, are untouched.

| Indicator | Setting | Was | Now |
|---|---|---:|---:|
| `sma` | Length | 20 | 9 |
| `ema` | Length | 20 | 9 |
| `wma` | Length | 20 | 9 |
| `stochastic` | %K Smoothing | 3 | 1 |
| `cci` | MA Length | 14 | 20 |
| `obv` | MA Length | 14 | 9 |
| `ma-cross` | Long MA Length | 21 | 26 |
| `alligator` | Jaw Length | 13 | 21 |
| `alligator` | Teeth Length | 8 | 13 |
| `alligator` | Lips Length | 5 | 8 |

The Stochastic one is the largest change in appearance: a %K smoothing of 1 is
raw %K, so the line is noticeably faster and noisier than the 3 it used to
default to. The Alligator moves to the slower 21/13/8 set rather than Williams'
original 13/8/5; the offsets 8/5/3 are shared by both, so only the smoothing
lengths move.

### Upgrading

A chart saved before this release can look different in three ways. None of them
is a regression, and each is worth knowing about before you go looking for a bug.

**Studies that now start later.** These previously drew across bars they had no
honest value for, which is worse than drawing nothing: an average seeded from one
price is not an average, and a plot that starts at bar 0 tells a backtest that a
signal existed before the data to compute it did.

| Study | First bar with a value |
|---|---|
| EMA | `length - 1`, so bar 8 at the new default of 9. It drew from bar 0 before. |
| MACD | bar 25 for the MACD line, bar 33 for signal and histogram, at the 12/26/9 defaults |
| ADX / DMI | bar 14 for +DI and -DI, bar 27 for ADX, at the default 14 |
| Special K | bar 724 |

Special K is the one to plan around. Its longest term needs 725 bars before it
can produce a first reading, and its signal line needs a further stretch on top,
so on a chart holding less history than that it now draws **nothing at all**
where it used to draw a line. That line was computed off an incomplete table and
was not the study. Give it more bars, or a longer timeframe, and it returns.

**Studies whose values changed.** Parabolic SAR flips where the definition says
it flips rather than a bar early or late; Fisher Transform no longer runs away on
a flat window; Chop Zone reads its range off the high series; ADX no longer goes
blank after a flat bar. In each case the old line was wrong, not merely
different.

**Defaults.** See the table above. Anything you configured explicitly, including
via `getState()` / `restoreState()`, keeps the value you set.

### Sizes

The indicator tier rises 25.04 to 27.27 kB: 1.10 kB for the first eight studies
plus three fixes, and 1.07 kB for the three that landed late, so about 200 bytes
a study across the eleven. Reuse is why it is not more. Standard Error Bands
leans on `linreg`, `sma`, `wma` and the file's existing gapped EMA and adds only
the standard-error term itself; Moving Average Channel is two calls to `sma` and
the existing shift helper; SMMA is one call to `rma`; T3 is three nested calls to
the same SMA-seeded exponential average the file already had; Hull Suite is `wma`
and that average again. Nothing was added to the shared `calc.ts`.

**Two budgets were raised, and only two.** The indicator tier goes 27 kB to
30 kB. That raise was staged earlier in this release and handed back as
unnecessary, on the measurement that stood at the time; the last three studies
took the tier 213 bytes past the old ceiling, so it is necessary now and is taken
at the figure already agreed rather than at a figure chosen to just clear the
reading.

"Everything" has to move with it, because it is the same six files summed and
would otherwise fail while the tier inside it passes. The arithmetic, in the
1000-byte kB `size-limit` reports:

    59,057 base + 7,609 trade + 2,656 transform + 10,662 profile + 13,126 draw
      = 93,110 B, every tier except indicators
    93,110 B + 30,000 B, the new indicator ceiling
      = 123,110 B, rounded up to a 124 kB budget

So "Everything" goes 120 kB to 124 kB and measures 120.38 kB against it. No other
budget moved.

| Tier | Measured | Budget |
|---|---:|---:|
| Base engine | 59.06 KB | 60 KB |
| Base + trade | 66.67 KB | 68 KB |
| Indicators | 27.27 KB | 30 KB |
| Draw | 13.13 KB | 14 KB |
| Transform | 2.66 KB | 5 KB |
| Profile | 10.66 KB | 11 KB |
| Everything | 120.38 KB | 124 KB |

Trade, draw, transform and profile measure exactly what they did in 1.8.2: no
code outside `src/indicators/` changed except the version string. That string is
why the base
bundle reads 59.06 against last release's 59.05, a 12-byte difference in how
`1.8.3` compresses rather than anything shipping in it.

2408 tests across 129 files. 102 indicators, 43 drawing tools, zero runtime
dependencies.

## 1.8.2

### Added

- **`ctx.tickSize` on the calculation context.** The instrument's tick size,
  read from the pane's price scale `minMove`, which is the same number the axis
  already formats and `snapToTick` already snaps to. An indicator sizing a range
  in ticks previously had to ask the user for a value the chart was holding.

  It is `undefined` rather than a guess when the host has not set `minMove`. The
  scale treats 0 as "infer precision from the visible range", and handing that
  to an indicator as though it meant one paisa would be worse than saying
  nothing. `IndicatorHost.tickSize?(paneIndex)` is optional, so a host predating
  it still satisfies the interface.

## 1.8.1

The indicator descriptor learns what the *chart* is doing, not only what the
bars say: where the last bar stands, when a condition it declared came true, and
how to state a regime as shading or as a colour on the price candles themselves.
Around that, five smaller things a study or a host kept having to hand-roll: a
plot that draws as candles, a session window stated rather than inferred, an
interval read as a count and a unit, the two colour helpers every per-bar
colouring rule ends up rewriting, and a price or a bar time picked off the chart
instead of typed into a field.

### Added

- **`IndicatorCalcContext`, the optional fourth argument to `calc`.** It carries
  `barState` (`isNew`, `isConfirmed`, `isRealtime`, `lastIndex`), `symbol`,
  `interval`, `timezone` and `now()`, so a study can act once per bar rather than
  once per tick, or refuse to signal off a bar that is still moving. `calcTail`
  takes it as a sixth argument.

  Optional and **trailing**, which is the whole point: all 91 built-ins and every
  user descriptor written against `calc(bars, settings, store)` keep their exact
  signature and their exact behaviour. A calculation that ignores the context
  computes what it always did.

  `isConfirmed` is inferred from the last bar's gap against the chart clock,
  because that is the only interval signal the engine has: it is handed bars and
  never a timeframe. A session break or a holiday widens the gap, so it reads as
  "this bar's own span has elapsed", not as "the exchange has closed".
  `isRealtime` is sticky, set the first time a tail-only change lands. `isNew` is
  false on a full history load, since there was no update to append. `symbol` and
  `interval` answer `undefined` under `chart.addIndicator`, on the same terms as
  the attach context.

- **`alerts`, conditions the runtime watches on the descriptor's behalf.** A
  crossover of an indicator's own columns is something only that indicator knows
  how to name, so the spec is declared as data (`id`, `title`, optional
  `message`, and a `when` predicate judging one bar) and a trigger arrives as
  `'indicator:alert'` on the chart's own bus with an `IndicatorAlertPayload`.

  Alerts fire **only on a tail-only change**, reusing the same gate `calcTail`
  uses and for the same reason. Any other pass reseeds the watermark silently, so
  adding an indicator to a loaded chart, changing a setting, paging history in or
  switching symbol announces nothing: an indicator dropped onto two years of bars
  must not fire every crossover in them at once. The watermark is a bar **time**,
  not a count, so a page of older bars at the left edge cannot re-fire the chart.

  `IndicatorAttachContext.emit(event, payload)` is the imperative half, for a
  signal that arrives from outside the calculation entirely. New types:
  `IndicatorAlertSpec`, `IndicatorAlertContext`, `IndicatorAlertPayload`.

- **`background`, per-bar shading behind the indicator's own pane.** A regime
  study answers "which state is the market in", which is a property of the whole
  bar rather than of a price: as a plot it would need a value to sit at and would
  drag the pane's autoscale around with it. One colour per bar, `null` to leave a
  bar unshaded, `[]` to clear the layer.

  The cost is in the work skipped. Everything outside the visible range is
  dropped before anything is painted, and adjacent bars sharing a colour coalesce
  into one rect, so a two-state regime over 50k bars is a handful of fills a
  frame rather than one per bar. Band edges are bar midpoints, so two runs abut
  exactly instead of overlapping by a pixel, and the edges are clamped to the
  plot because nothing clips them: the axis strips share that canvas. The layer
  contributes nothing to autoscale and is anchored to the first bar's **time**,
  so a page of history at the left edge does not slide the shading off its bars.
  It draws over the grid, so a descriptor should pass a translucent `rgba()`.
  `IndicatorBackground` is exported and usable as a plain primitive.

- **`barColors`, recolouring the price candles from a study's verdict.** Distinct
  from a plot's `colorBy`, which paints the indicator's own series: a trend
  filter, a volatility regime or a higher-timeframe bias is a claim about the
  price bars themselves, and drawing it as a second series beside them says
  something weaker.

  The engine never writes into the bars the caller handed `setData`. It clones
  only the ones whose colour actually changes and republishes those straight to
  the data layer, so the time points and the base index do not move and no
  recompute cascade follows; a pass where nothing changed writes nothing at all,
  which is the common case on a live tick.

  Only one overlay can be on the candles, so this is last writer wins, which is
  deterministic rather than arbitrary: publishers run in `addIndicator` order, so
  the same instance wins every frame. Withdrawal is gated on ownership. Two gaps
  are known and left in rather than paid for in base bytes: removing the
  **winner** while a second publisher is still live drops the bars back to their
  own colours until that publisher's next recompute, and prepending older history
  retakes the "own colour" snapshot from bars that already carry the overlay, so
  removing the indicator afterwards leaves the pre-prepend region tinted.

- **`IndicatorPlot.ohlc`, a plot drawn as candles.** Four `calc` keys naming
  four columns in the **same** `IndicatorValues`: a smoothed Heikin-Ashi overlay,
  a higher-timeframe candle, a synthetic spread instrument each return four
  ordinary columns and point at them. A second result shape for `calc` would have
  forked the contract every descriptor and every helper is written against.

  `key` stays the series identity and the legend reading falls back to the
  `close` column. The named columns must all exist and be bar-aligned or
  `addIndicator` throws, which it can do because the first `calc` runs inside the
  instance constructor: a wrong column name is an error rather than an empty
  pane. A type override on the plot degrades quietly, since line, area and
  histogram read `close`.

- **Session windows you state rather than infer.** `parseSessionSpec('0915-1015')`,
  `inSessionAt(utcSeconds, spec, zone?)` and `sessionFlags(times, spec, zone?)`,
  with `SessionSpec` as the parsed form. `sessionStartFlags` reads the trading day
  back out of the bar gaps, which cannot answer which *part* of a session you
  meant: an opening range, the cash hours inside an extended session, one
  exchange's hours drawn on another exchange's chart.

  The grammar is `HHMM-HHMM`, optionally `:` and the days the window opens on
  (1 = Sunday). The window is half-open, so a bar stamped exactly at the end
  belongs to what comes after it, which is what an opening-range comparison
  needs. An end at or before the start runs past midnight, which makes
  `start === end` the whole day rather than nothing. The day filter names the day
  the window **opens** on, so an overnight window stays one session instead of
  being cut in half at 00:00. An unparseable string marks nothing rather than
  throwing, because it is normally a settings field a user is halfway through
  typing.

- **Interval introspection: `intervalParts`, `isIntradayInterval`,
  `isDailyInterval`, `isSecondsInterval`, `isTickInterval`**, with the
  `IntervalParts` type. A study written against `'1m'`, `'5m'` and `'15m'`
  silently misbehaves on `'3m'`, and a host's own registered code was never in
  anybody's list at all.

  The answer is read off the **bucketing rule**, not the code's spelling, so it
  is canonical (`'120m'` and `'2h'` both read 2 h, a 90-second bar reads 90 s) and
  it answers for any registered code. `M` is months, keeping the token grammar's
  rule that lower-case `m` is minutes, so a quarter reads 3 M and a year 12 M.
  The length predicates ask about a magnitude rather than a unit, so a
  registrable `25h` decomposes into hours while answering false to
  `isIntradayInterval`. A calendar or count-driven code has no clock length at
  all rather than a long one.

- **`withAlpha` and `fromGradient` on the public surface.** Per-bar colour means
  computing a colour string per bar, and hand-rolling that ends in a private
  `#rrggbb` parser in every project. `withAlpha` was already the engine's own and
  simply had no export path; `fromGradient(value, min, max, low, high)` is new and
  blends in sRGB, alpha included, clamped outside the range.

  It reuses the single existing colour parser rather than adding a second, and
  allocates only the result string per call: no closure, no cache, no lookup
  table. The clamp is two comparisons rather than `Math.min`/`Math.max` because
  both are false against a not-available value, which lands it on `low` instead
  of emitting `rgba(NaN,...)`. That is not cosmetic: canvas ignores an
  unparseable `fillStyle` and silently keeps the previous one, so a NaN string
  would bleed the neighbouring bar's colour across this one rather than failing
  visibly.

- **`chart.beginPick(kind, cb)`, interactive value capture.** A settings field
  naming a price or a time is host chrome, but the value is often easier to point
  at than to type, and only the engine knows what is under the cursor. The host
  arms a pick, the next plot click answers with a number, and the pick disarms
  itself; the returned function cancels it.

  Built on the `click` event the draw tier already resolves anchors from, so it
  inherits pane resolution, on-demand autoscale and the same payload rather than
  adding a second capture path. Placement mode is deliberately **not** armed
  while picking: a pick wants panning left alone (scroll back to the bar you
  mean, then click it), and outside placement mode a drag emits no click, so
  panning cannot answer a pick by accident, and arming a pick never cancels an
  active drawing tool. A `'time'` pick snaps to the bar clicked, because the raw
  click time is interpolated between bars on the gapless axis and matches no bar.
  A click the chart could not resolve leaves the pick armed rather than answering
  with a bogus number. One pick per chart, held in a `WeakMap` keyed on the host,
  so arming a second cancels the first and a destroyed chart takes its pending
  pick with it. `'pick:start'` and `'pick:end'` bracket it for a host that wants
  to swap its cursor. New types: `PickKind`, `PickHost`.

### Changed

- **`IndicatorHost` gained two optional members**, `setBarColors(colors, owner)`
  and `emit(event, payload)`. Both optional, so a host implementing the interface
  itself needs no change; a host that wants indicator bar colours or indicator
  alerts implements them.

### Sizes

Base rises 57.31 to 59.07 kB, against its unchanged 60 kB budget.

Of the 1.76 kB, the runtime spine plus the background primitive is 980 B and is
unavoidable: `IndicatorBackground` is constructed by the indicator runtime, which
is base. The remaining 776 B is the barrel exports plus the one `chart.ts` hook
(sessions 226 B, interval introspection 174 B, pick 115 B, the gradient helpers
21 B, and roughly 240 B of joint export-map cost that only disappears if all four
go). The registry additions are pure type declarations and cost nothing.

| Tier | Measured | Budget |
|---|---:|---:|
| Base engine | 59.07 KB | 60 KB |
| Base + trade | 66.67 KB | 66 KB (over; see below) |
| Indicators | 25.04 KB | 27 KB |
| Draw | 13.13 KB | 14 KB |
| Transform | 2.66 KB | 5 KB |
| Profile | 10.66 KB | 11 KB |
| Everything | 118.16 KB | 120 KB |
| Chart-only, tree-shaken | 37.55 KB | 38 KB |

**The base+trade entry needs a decision before release.** `size-limit` sums the
per-file figures rather than compressing the concatenation, so a 66 kB combined
limit caps the base at 58.39 kB, which is 1.61 kB tighter than the base's own
budget. That is exactly the outcome 1.7.1's Sizes section says it was avoiding:
it raised the pair to 60 and **68** kB because doing so "keeps the trade allowance
where it was instead of making the combined entry a stricter constraint on the
base than the base's own budget". The config carries 66, and it is the older
artefact by timestamp. The trade tier itself has not moved: it is 7.61 kB of the
combined figure against the 8 kB it has always had. Against 68 kB this release
passes with 1.33 kB spare.

1953 tests across 106 files. Zero runtime dependencies.

## 1.7.1

The indicator descriptor gains the parts a ported study needs and could not
express: free-standing geometry, levels derived from the data, one plot that
escapes to the price pane, and the calculation helpers the 91 built-ins are made
of. Per-bar colour reaches every renderer that draws a bar rather than the two
that happened to read it.

### Added

- **`draws`, geometry a descriptor could not express before.** A descriptor
  returns lines, boxes, labels and polylines anchored to `{ time, price }`. A
  plot is one value per bar and a level is a horizontal line across the pane, so
  a pivot-to-pivot trendline, a supply zone or a measured-move projection had
  nowhere to live.

  Anchors are **times, never logical indices**: paging history in at the left
  edge shifts every index, and a trendline pinned to one would slide off its
  pivots the moment it did. `extendLeft` / `extendRight` solve the segment for
  the pane edge along its own slope, so a ray keeps its angle instead of
  flattening into a horizontal nobody asked for. The layer contributes nothing
  to autoscale, since a projection reaching far above the data would otherwise
  squash the study it annotates into a band a few pixels tall. Shapes entirely
  off-pane are culled before any path work. A label, and a box's caption, split
  on `\n`.

  One primitive holds the whole list, created lazily on the first non-empty
  result and replaced wholesale on each recompute, so a live tick does not
  attach and detach a dozen objects and re-sort the pane's z-order for each.
  `IndicatorDrawings` is exported and usable as a plain primitive. New types:
  `IndicatorDrawing`, `DrawAnchor`.

- **Levels derived from the data.** `levels` now runs after every `calc` instead
  of once at construction, and is handed the bars and the computed values
  alongside the settings, so a level can be yesterday's high or a session band
  rather than only a number the user typed.

  The context spreads the settings keys onto itself, so all 91 built-ins reading
  `ctx.overbought` are untouched; `settings`, `bars` and `values` join
  `timezone` as reserved keys. The returned list is diffed against the previous
  one, so RSI's constant 70/50/30 lines are not detached and reattached on every
  tick. `IndicatorLevel` gained `lineWidth` and `lineStyle`, with
  the original `dashed` still honoured and `lineStyle` winning when both are
  set. New type: `IndicatorLevelContext`.

- **`IndicatorPlot.overlay`.** One plot of a pane indicator drawn on the price
  pane: an oscillator whose trailing stop belongs on the candles, without
  splitting the study into two indicators the user configures twice. Markers
  ride the first plot's series, so they follow it; fills, levels, drawings and
  the table stay on the indicator's own pane.

- **The attach context reaches further.** `symbol()`, `interval()`, `now()`,
  `paneIndex()`, `addPrimitive()` and `removePrimitive()` join `settings`,
  `bars`, `requestRecompute`, `store` and `timezone`. `symbol` and `interval`
  answer `undefined` under `chart.addIndicator`: the core is handed bars and
  never an instrument, so a host that owns the symbol picker supplies them
  through its own `IndicatorHost` rather than having the engine invent a name.
  `now()` is the chart's wall clock, the one the countdown row reads, so an
  indicator deciding whether the last bar is still forming agrees with the axis.

- **`Bar.color` on every Family-A renderer.** It reached histogram and column
  only. Candles, hollow candles, volume candles and OHLC bars now take it on
  body, border and wick together, so a recoloured candle cannot keep a wick
  arguing the other way. Line, step, area and the HLC-area close line split
  their stroke into runs at the bars where the colour changes, with consecutive
  runs abutting at the point they share so no seam of background opens: the
  segment arriving at a bar takes that bar's colour, and a step's horizontal and
  vertical legs take one between them. Baseline is deliberately excluded, its
  stroke is already split by the above/below-base rule and has its own colour
  pair. A series where no point carries a colour is still walked into a single
  stroke, byte for byte the op stream it emitted before. Indicator plots reach
  this through `colorBy`, which was documented as histogram-and-column only.

- **Multi-line marker text.** `\n` in a `labelUp` / `labelDown` plate stacks the
  rows, sizes the plate to the widest and keeps it centred on its anchor, so the
  tail still points at the bar and a two-row plate sits higher rather than
  sliding sideways. A free `text` marker writes its rows outward from the
  anchor, so a block above a bar grows upward instead of back over the candle.
  The single-line path is untouched, down to the plate arithmetic.

- **Gradient and per-point colour on `IndicatorFill`.**
  `gradient: { topValue?, bottomValue?, topColor, bottomColor }` shades a band
  across price instead of filling it flat; an omitted stop takes the band's own
  high or low, so either side can be pinned independently. The stops resolve
  once per frame, so the shading does not restart at every crossing.
  `FillPoint.color` overrides one bar, and the two runs share that edge rather
  than leaving a seam. Precedence is point colour, then gradient, then
  `colorUp` / `colorDown`. New type: `FillGradient`.

  `IndicatorFillSpec` does not carry either yet, so a descriptor cannot declare
  one: this is reachable by constructing the primitive directly.

- **`PriceLineOptions.lineStyle`**, the three-way form of `dashed`
  (`'solid' | 'dashed' | 'dotted'`), reusing the `CanvasLineStyle` alias and the
  same dash table the grid and crosshair already use. `dashed` still works and
  `lineStyle` wins when both are set.

- **21 calculation helpers exported** from `openalgo-charts/indicators`:
  `smaSeededEma`, `change`, `roc`, `dev`, `percentRank`, `alma`, `vwma`,
  `highestBars`, `lowestBars`, `rollingSum`, `cumulative`, `linreg`, `swma`,
  `stoch`, `percentileNearestRank`, `correlation`, `cci`, `pivotHigh`,
  `pivotLow`, `barsSince`, `valueWhen`, joining the seven that were already
  public. They match the published `ta.*` formulas the built-ins were ported
  against, so a custom descriptor can port a study rather than re-derive it.
  Every one of the 21 is already in the tier bundle, so this adds names to the
  export map and no code.

### Changed

- **`IndicatorHost.addIndicatorLevel` takes an options object** rather than
  positional arguments. The level gained a width and a line style this release,
  and a call site of seven bare values is where the next one gets passed in the
  wrong slot. A host that implements `IndicatorHost` itself has to update the
  call; `chart.addIndicator` is unaffected.

- **`PriceLineOptions.lineWidth` and `dashed` are optional**, defaulting to 1
  and off, which matches what `price-levels.ts` already assumed. This breaks
  only a consumer reading `options().lineWidth` or `options().dashed` into a
  non-optional `number` / `boolean`.

### Fixed

- **`calcTail` could splice a tail onto a history that no longer existed.** The
  incremental path was gated on the bar count being `n` or `n + 1`, which does
  not say the previous result still describes the earlier bars. A symbol change
  landing on a matching count, or one older bar paged in at the left edge, took
  the tail path anyway and left the plot silently wrong until the next full
  `calc`.

  The guard now reads times: the first bar must be unchanged, and the last must
  be either that same bar replaced in place or one appended directly after it.
  The appended case is read off `bars[n - 2]` rather than by projecting the next
  bucket, which a session gap or a holiday makes unguessable on a gapless axis.

- **A column plot ignored its own Colour control.** `drawColumns` read only the
  up/down pair, so the `style.color` an indicator's generated colour input
  writes was inert. Precedence is now `bar.color`, then `style.color`, then the
  up/down pair. Every built-in column plot sets `colorBy` and returns a colour
  for every finite value, so none of their appearances change.

- **An area series drew a solid outline** when its `lineStyle` was `dashed` or
  `dotted`: `drawArea` never passed the style through to the outline.

### Sizes

Base rises 56 to 60 kB and base+trade 64 to 68 kB.

The base grew because this release lands in base modules: the drawings layer is
imported statically by the indicator runtime, the way the fill primitive already
was, and per-bar colour, the widened level path and the level diff are all base
code. It measures 57.31 kB against the new 60, which restores headroom 1.6.0 did
not have (55.78 against 56).

Base+trade rises by the same 4 kB rather than to a tighter number. The trade tier
did not grow: it is 7.61 kB of the combined figure against the 8 kB it has always
had, so the combined budget was failing purely because the base moved. Raising it
by the base's increase keeps the trade allowance where it was instead of making
the combined entry a stricter constraint on the base than the base's own budget.
Nothing else moved, and "everything" did not need raising.

| Tier | Measured | Budget |
|---|---:|---:|
| Base engine | 57.31 KB | 60 KB |
| Base + trade | 64.92 KB | 68 KB |
| Indicators | 25.04 KB | 27 KB |
| Draw | 13.13 KB | 14 KB |
| Transform | 2.66 KB | 5 KB |
| Profile | 10.66 KB | 11 KB |
| Everything | 116.40 KB | 120 KB |
| Chart-only, tree-shaken | 36.42 KB | 38 KB |

1949 tests across 106 files. Zero runtime dependencies.

## 1.6.0

Broker-readiness hardening across the trade and feed layers, driven by an external
production-readiness review and by verifying every one of its claims against the
code rather than trusting them. An independent reassessment scored the result
68/100, up from 61.

### Fixed, and the reason to upgrade

- **`modifyorder` zeroed the price field the caller did not touch.** Dragging a
  stop-limit order's line wiped its limit price to zero at the broker, on a live
  working order.

  OpenAlgo's modifyorder takes the WHOLE order rather than a delta, so every
  field is sent on every modify. `modify()` correctly rebuilt symbol, action,
  exchange, pricetype, product and quantity from its cached context, but took the
  two price fields from the patch alone: `price: patch.price ?? 0`. Defaulting an
  unmentioned field to 0 does not leave it alone, it overwrites it with zero. A
  stop-limit carries both a limit and a trigger, and dragging its line sends only
  the trigger, so that path sent `price: 0`.

  Verified against the published 1.5.0 tarball, which answers `price: 0`. Anyone
  running a terminal with draggable stop-limit lines should upgrade.

### Breaking, despite the minor version

Same call as 1.4.0 made for `intervalToSeconds`, for the same reason: the old
behaviour produced wrong answers.

- **`mapOrder` returns `DecodedOrder`, not `Order`.** `status` widens to
  `OrderStatus | 'unknown'` and `rawStatus` carries the broker's own text when it
  is unknown. Previously an unrecognised broker status silently became `working`,
  a missing action silently became **BUY**, and an unreadable number became 0. A
  fail-open BUY default is the worst possible direction for a trading payload.

  Assigning the result straight to `Order` no longer type-checks. Handle
  `'unknown'`, or use the new `getOrderBook()`, which returns
  `{ orders, quarantined }` so a row that cannot be decoded is surfaced rather
  than rendered as live state. `decodeOrder(raw)` is the strict primitive.

### Added

- **Feed-level quantity and idempotency guards.** Both already existed in
  `OrderEngine` and were unreachable for anyone calling the feed directly, which
  is what most hosts do. A guarantee you can bypass by calling one layer down is
  not a guarantee.

  Quantity is checked on every order with no configuration: NaN, zero, negative
  and fractional are refused. The new `constraints(symbol, exchange)` hook adds
  the freeze limit and lot grid, including on MARKET orders, which is the case
  that matters because a market order cannot be taken back.

  A repeated `clientToken` is refused before anything is sent. A failure AFTER
  the request leaves keeps the claim and marks it ambiguous rather than releasing
  it: a failed write says the response did not arrive and says nothing about
  whether the order did. `tokenState()` and `releaseToken()` let a host resolve
  that deliberately. Every refusal is thrown pre-flight, so a caller can tell
  "nothing was sent" from "this may be live".

- **Chart-anchored primitives.** `addPrimitive(p, { anchor: 'chart-bottom' })`
  makes a primitive chart furniture rather than pane furniture, and the engine
  re-homes it as panes are added, removed, moved and maximized. Maximize is the
  case a host could not work around, because it hides the other panes and takes
  a watermark pinned to pane 0 with them. `'chart-top'` exists too.

- **`paneAdded`.** Panes are created lazily when an indicator asks for one, and
  that was silent: `paneRemoved` had no counterpart. Fires once per pane, after
  the relayout, so a listener reads settled geometry.

- **Analyzer mode is a guard rather than cargo.** `place()` accepted a `mode` and
  never transmitted it. It is now checked against the server: OpenAlgo decides
  analyzer server-side, so a mode field in the order body would be ignored, and a
  control that looks real and does nothing is worse than no control. The feed
  reads `/api/v1/analyzer/` and refuses when the server disagrees with the caller.

- Order-engine intent state separate from broker state, so a resolved promise is
  no longer promoted to the exchange's word; quantity constraints binding on every
  order type; `placeMarket` accepting exchange and product; bounded engine maps.

- WebSocket handshake gating, a liveness probe, jittered backoff, topic-derived
  identity, and optional sequence tracking. Reference-counted subscriptions on the
  composed live feed, so one consumer leaving no longer cuts the stream for the
  others.

- A working stop-loss drew nothing on the chart, and a one-sided bracket drew a
  phantom take-profit at the position's average price. Both fixed.

### Security

- **Polynomial ReDoS in `scaleFont`** (CodeQL, shipped code). `\d+(?:\.\d+)?px`
  retried from every start position and backtracked the whole run. Font strings
  can arrive from a restored layout, and layouts are shareable. Bounded and given
  a leading boundary: 813ms to 1ms on 40,000 digits, byte-identical on real fonts.

- Development advisories 12 to 0, including one critical. GitHub Actions pinned by
  commit SHA. CI given least-privilege tokens, a runtime audit gate, an SBOM and
  CodeQL. A release workflow using npm OIDC trusted publishing, so no long-lived
  token need exist. `SECURITY.md` added, stating plainly that the browser is not a
  trust boundary.

- The live example no longer persists the API key to `localStorage`, and its
  legend escapes every interpolated value.

### Sizes

Two budgets rise, base 55 to 56 kB and base+trade 62 to 64 kB. Those entries
measure whole bundle files, and the base bundle carries the OpenAlgo adapters, so
hardening them grows the file even though a charting host never imports them.
A chart-only import tree-shakes to 34.9 kB with the WebSocket adapter provably
absent, which is what a charting user actually pays and did not move. `npm run
shake` now guards that number directly.

| Tier | Measured | Budget |
|---|---:|---:|
| Base engine | 55.78 KB | 56 KB |
| Base + trade | 63.39 KB | 64 KB |
| Indicators | 24.88 KB | 27 KB |
| Draw | 13.13 KB | 14 KB |
| Transform | 2.66 KB | 5 KB |
| Profile | 10.66 KB | 11 KB |
| Everything | 114.72 KB | 120 KB |
| Chart-only, tree-shaken | 34.94 KB | 38 KB |

1882 tests across 100 files. Zero runtime dependencies.

## 1.5.0

### Fixed

- **Removing a sub-plot indicator could throw**
  `TypeError: Cannot read properties of undefined (reading 'removeSeries')`,
  leaving the teardown half-done: the legend went, the plot stayed on the chart.

  `_createSeries` captured `paneIndex` once and every closure on the returned
  `SeriesApi` used that number afterwards. A slot number is not stable.
  `removeIndicator` prunes a pane that just emptied, which splices the pane array
  so everything below shifts up one, and `movePane` swaps two entries outright.
  The captured number then names a different pane, or none at all.

  Concretely: three sub-plots on panes 1, 2 and 3. Remove the first, and the
  survivors shift to 1 and 2 while their series still name 2 and 3. Remove the
  last and `_panes[3]` is undefined. That is why it needed more than one sub-plot
  and never appeared when clearing them bottom-up, which shifts nothing.

  The quieter half had no symptom to report it at all: when the stale index still
  lands on a live pane, the series is stripped from the **wrong** pane. Series
  now hold their pane by identity, since panes travel with their series through
  both operations.

### Added

- **`SeriesStyle.bodyVisible`.** `false` drops the candle body fill and leaves
  the outline and the wick, which is what a settings dialog's Body switch means.
  Distinct from `hollow`, which empties only the up candles and is the
  hollow-candle chart type; this empties both.

  It exists because the candle settings row could not honestly carry a checkbox
  without it. `chartSettingsSchema` now gives the Body row the same switch its
  Borders and Wick neighbours already had, rather than the row going without one
  because nothing in `SeriesStyle` backed it.

  It is the one flag here that can legitimately leave nothing drawn: with borders
  off as well, a candle is reduced to its wick. That is two deliberate switches
  rather than an accident, so it is honoured rather than second-guessed. The 3px
  width guard on the inset outline is skipped when the body is hidden, since the
  guard exists to stop a 1px outline swallowing a narrow *filled* body and with
  no fill the outline is the candle.

### Examples

- `examples/yfinance` was passing `intervalSeconds` to `withBarCache`, an option
  1.4.0 renamed to `barCloses`. Nothing read it, so the wrapper had silently been
  running on its default, which happens to be the registry-backed answer it was
  reaching for, hence no visible symptom. It now passes `barCloses` and reads the
  chart's timezone inside the closure rather than capturing it, because a New
  York month is not a Mumbai month. Two `accent-color` declarations on checkboxes
  are also gone: they tint a *native* control, and these boxes are drawn by the
  `appearance: none` rule at the top of the file.

1734 tests across 91 files. Everything tier 110.7 KB brotlied, against a 120 KB
budget.

## 1.4.0

### Breaking

- **`intervalToSeconds` throws where it used to return 60.** It was exported in
  1.3.0 and answered 60 seconds for any code its regex did not recognise, so a
  typo drew minute bars under whatever label the caller thought it had asked
  for. It now throws `UnknownIntervalError` for an unregistered code, and a
  separate error for a calendar or count-driven code that has no fixed length to
  report. A caller passing user input needs a `try`/`catch`, or should use
  `tryResolveInterval` / `isKnownInterval`, which answer without throwing.

- **Upper-case `M` no longer resolves at all.** The built-in token regex folded
  case, so `M` and `1M` read as minutes. Every terminal that uses these tokens
  reads lower-case `m` as minutes and upper-case `M` as a month, and anything
  gating on "has the next bar closed yet" therefore believed a month closed
  every sixty seconds. Nothing is registered for `M` by default: a host that
  wants months registers a calendar interval deliberately. Lower-case `m` is
  untouched, as are `s`, `h`, `d`, `w` and their upper-case forms.

  This is shipped as a minor release by explicit decision, so a consumer on
  `^1.3.0` will pick it up automatically. Both changes only affect codes that
  were already producing the wrong answer.

### Added

- **Chart linking.** `createLinkGroup({ crosshair, viewport, symbol })` drives a
  grid of charts as one workspace. `add`, `remove`, `setOptions`, `destroy`,
  `setSymbol`, `symbol()`, `members()`, `has()` and `crosshairIndex()` are the
  whole surface, and like `ReplayController` and `ComparisonController` it ships
  no DOM: the host draws its own link badge and colour chips, and decides which
  charts belong to which group. Each of the three channels switches on its own,
  because a user routinely wants one without the others: mirror the cursor
  across four timeframes but keep each zoom, or slave every chart's instrument
  but let each keep its own window.

  **Nothing crosses a chart boundary as a logical index.** That is the decision
  everything else hangs off. The x axis is a gapless index over each chart's own
  bars, so logical index 300 is a different instant on every chart in the grid.
  Copying an index or a range straight across works perfectly on two charts of
  the same symbol and interval, which is exactly how it would ship broken. Every
  value is converted index to time on the sender through `indexToTimeFloat`, and
  time back to index on the receiver through `timeToIndex` / `timeToIndexFloat`,
  against that chart's own `DataLayer`. A daily chart and an hourly chart with
  different history depth therefore stay on the same instant and the same
  wall-clock window. The two conversions, `followerIndex` and `followerRange`,
  are pure and exported.

  Coverage is answered as an absence, not as a gap. A follower refuses any
  instant before its first bar or after its last one, because that is a period
  it does not cover at all and pinning the crosshair to an edge bar would assert
  an alignment that does not exist. Inside its range with no bar at that second
  it snaps to the nearest bar **in time**, which is not the nearest in index once
  the bars either side of a session break are hours apart, or draws nothing under
  `whenMissing: 'hide'`.

  A follower's crosshair is a new `LinkCrosshair` primitive on the `top`
  z-order, one per pane so it spans price, volume and indicator panes the way the
  native global crosshair does. It draws the **vertical line only**, at
  `LINK_CROSSHAIR_ALPHA` of the pane's own crosshair colour. The horizontal line
  marks a price, and the price under a cursor on another instrument is not a
  price on this one: on a grid of four symbols a mirrored price line would be a
  straight lie four times over. The vertical line marks an instant, and an
  instant is shared.

  Feedback loops are stopped by one group-wide re-entrancy guard rather than one
  per channel. Any member event arriving while the group is broadcasting is an
  echo of that broadcast by definition, since a human cannot pan two charts in
  one call stack; and a symbol change that reloads data can move a viewport, so
  that second-order echo is the same bug wearing a different hat. Destroyed
  members are detected by `isDestroyed` (falling back to an empty pane list for a
  host wrapping something that is not a `Chart`) and pruned on the spot, which
  also stops `addPrimitive` from resurrecting a pane on a corpse.

  **The engine keeps no instrument concept and linking does not invent one.** The
  host participates: it reports a change by emitting `'symbol'` on the chart's
  own bus or by calling `setSymbol`, and it supplies the per-member `onSymbol`
  callback that actually loads the new instrument's bars. A member with no
  `onSymbol` broadcasts its own changes but never follows anyone else's, which is
  how a host pins one chart of a grid.

- **Drawings on the clipboard.** `DrawingController` gains async `copy`, `cut`
  and `paste`, over a new `DrawingClipboard` in the draw tier that wraps
  `navigator.clipboard`. The host still owns the key bindings, because the engine
  installs no listeners: these are plain calls to make on Ctrl+C, Ctrl+X and
  Ctrl+V.

  The payload is JSON under a single namespaced top-level key
  (`openalgo-charts/drawings`, with a version), so foreign text and foreign JSON
  are recognised as **not ours** by looking at one property and paste nothing,
  rather than throwing at the host because the user last copied a spreadsheet
  cell. Everything read back is validated field by field before it can reach the
  model: the tool must be registered, every anchor must be finite, the pane must
  be a non-negative integer, style values must be renderable primitives or a
  short array of numbers, and there are caps on counts and string length.
  Validation is all-or-nothing, because a payload with one corrupt entry is a
  corrupt payload and pasting the other nine silently would be worse than
  pasting none.

  Clipboard failures degrade rather than break. Every write also lands in a
  module-level in-memory clipboard shared by every controller in the page, which
  is what makes chart-to-chart paste work with the permission refused, and is
  why that store is a singleton rather than per-controller state. `cut` deletes
  **only** after the write resolves successfully, so with
  `fallbackToMemory: false` a refused write leaves the model exactly as it was
  instead of destroying a drawing that went nowhere. `clipboard().lastError()`
  reports a copy that reached memory but not the system clipboard, which is
  precisely what a host wants to be able to tell the user.

  Paste inserts fresh objects with fresh ids in a single undo step, so editing
  the copy cannot alter its source. It is offset two bars along time and 16 px
  down the price axis (`pasteOffsetBars` / `pasteOffsetPixels`), applied per
  anchor through `priceToCoordinate` / `coordinateToPrice` so the nudge is a
  rigid *screen* translation that keeps a shape's proportions on a logarithmic
  scale. A pane index the receiving chart does not have is folded onto one it
  does, because `addPrimitive` would otherwise conjure an empty pane.
  `draw:copy`, `draw:cut` and `draw:paste` are emitted on the chart's bus.

  `DrawingClipboard`, `ClipboardPort` and the encode / decode / sanitise trio
  are exported from `openalgo-charts/draw`, so a host can name the type
  `DrawingController.clipboard()` returns and can move drawings over its own
  transport with the same validation a paste gets. Deliberately not from the
  base barrel: `clipboard.ts` needs `hasDrawingTool`, so exporting it there
  would drag all 43 drawing tools into the 55 kB base bundle.

- **Warm-load bar caching for any feed.** `withBarCache(feed, options)` is a
  `DataFeed` to `DataFeed` wrapper, so a custom feed gets it too and not only
  `OpenAlgoDataFeed`.

  The key is `symbol | exchange | interval`, and the requested range is
  deliberately **not** part of it: one entry per series holds the widest set
  fetched so far and a narrower request is served by slicing it. Keying on the
  range would miss on every pan and on every "same chart, one bar later" reload,
  which is exactly the traffic warm loading exists to remove.

  Freshness is two gates that must both pass. `ttlMs` bounds absolute age, and a
  hit past the entry's coverage is allowed only while the bar after the entry's
  last closed bar is still forming (`nowSec < entry.to + 1 + intervalSec`). That
  second gate is measured on the feed's own bar grid rather than against UTC
  midnight, so a daily Indian bar opening at 03:45 UTC is judged against its own
  session instead of the wrong boundary. A closed session therefore stays usable
  for the whole TTL while a 1m chart is only reused inside the current minute.

  **The forming bar is never stored at all.** It keeps moving, and a frozen
  snapshot of it served to a live chart is worse than no cache, because the chart
  paints a confident candle with no spinner and no way to know. Trailing unclosed
  bars are dropped on store, so a hit is short by at most that one bar, which a
  live subscription re-supplies immediately, and is never wrong about a bar it
  does return.

  Bounds are LRU on both entry count (`max`, 24) and total bars (`maxBars`,
  250k), because entries alone do not bound memory when one intraday series can
  be 100k bars, and bar count is the only honest proxy for bytes that does not
  mean serialising every entry on every write. Storage is an in-memory `Map` by
  default with an injectable sync-or-async `BarCacheStore`, so a host can choose
  localStorage or IndexedDB and the engine chooses neither. Opt-out is
  `getBars({ ..., noCache: true })` plus `invalidate()` and `clear()`, and
  `stats()` reports entries, bars, hits, misses and evictions for a status line.

- **An interval registry whose entry is a bucketing rule, not a duration.**
  `registerInterval({ code, bucketing })` puts a host's own interval codes in
  front of the engine, and `resolveInterval(code)` is how the engine asks how a
  code buckets. `Bucketing` is a four-case union:
  `{ mode: 'interval', seconds, anchorSec? }` for fixed lengths,
  `{ mode: 'calendar', unit: 'month' | 'quarter' | 'year', count?, timezone? }`
  for periods that have no seconds, and `{ mode: 'ticks', count }` /
  `{ mode: 'volume', perBar }` for count-driven bars.

  That is deliberately the vocabulary `TickTimeframe` already used, widened by
  one case, rather than a second parallel system. The three original variants now
  live in `src/feed/intervals.ts`, `TickTimeframe` is re-exported from
  `tick-aggregator` meaning exactly what it always meant, and `TickBarAggregator`
  takes the widened `Bucketing` plus an optional `timezone`.

  Calendar buckets are computed as absolute month indices floored to the step and
  converted back through `zonedWallClockToUtcSeconds`, so a month runs first to
  first at local midnight in the entry's zone (or the caller's, defaulting to
  IST). A month is not 30 days and a year is not 365: February 2024 is 29 days,
  March 2024 in `America/New_York` is 31 days minus an hour, and quarters land on
  January, April, July and October for every year. `bucketStartOf` and
  `nextBucketStart` are the pair, and `nextBucketStart` returns null for
  count-driven bars, whose close depends on trade flow rather than the clock.

  `registeredIntervals()` lists what a host has added, `tryResolveInterval` and
  `isKnownInterval` are the non-throwing probes for validating an interval
  picker, and `unregisterInterval` and the disposer returned by
  `registerInterval` take a code away again.

- **A chart says when it is gone.** `chart.isDestroyed`, a `'destroy'` event on
  the bus, and an idempotent `destroy()`. Anything holding a chart it did not
  create (a link group, a controller, a host cache) has to know the object is a
  corpse before it calls into it, and inferring that from a side effect such as
  an empty pane list only works for as long as nothing else can empty one. The
  event is emitted last, with the chart already torn down, because a listener is
  there to let go of the chart rather than to read it.

### Changed

- **Programmatic viewport moves announce themselves.** `setVisibleLogicalRange`,
  `fitContent`, `resetScale` and the keyboard pan and zoom commands now emit
  `'pan'` or `'zoom'` like a drag or a wheel does, so a chart linked into a grid
  follows an arrow key or a restored zoom and not only a gesture.

  One helper covers all of them rather than four bespoke emits.
  `_emitViewportIfMoved` compares the range before and after the mutation, emits
  nothing when the window did not actually move (a clamped zoom, an already
  fitted `fitContent`), and picks `'zoom'` or `'pan'` by whether the span
  changed, because a restore can do either and a listener cannot tell from the
  payload otherwise. The no-move check is load-bearing: without it a linked grid
  re-broadcasts on every no-op. `panUp` and `panDown` move a price scale rather
  than the time window and deliberately emit nothing. The keyboard `fitContent`
  command now routes through `chart.fitContent()`, so it gets the full
  invalidation the method always did.

- **An unknown interval code is an error, not a minute.** `resolveInterval`
  throws `UnknownIntervalError` carrying the offending code, and
  `intervalToSeconds` throws both for an unknown code and, separately, for a
  calendar or count-driven code that has no fixed length to report.
  `OpenAlgoLiveDataFeed.subscribeBars` resolves the code up front, so a bad
  interval fails at subscribe time rather than silently on every tick for the
  life of the subscription.

  The old behaviour was a silent fall back to 60 seconds, which drew minute bars
  under whatever label the caller thought it had asked for, with nothing anywhere
  saying so. A chart that refuses to open is a bug report; a chart showing the
  wrong timeframe is a wrong trade. `tryResolveInterval` and `isKnownInterval`
  exist for the callers that genuinely want to ask without being thrown at.

- **The live feed aggregates calendar, tick and volume intervals too.**
  `OpenAlgoLiveDataFeed` sends fixed intervals through `CandleBuilder` as before
  (it is the one that carries the late-tick policy) and everything else through
  `TickBarAggregator`, which is the one that knows those boundaries. It takes a
  `timezone` for calendar buckets, and `seedFrom` still continues a historical
  bar for time-bucketed intervals only, because a count-driven bar cannot resume
  one whose trades were never counted here.

### Fixed

- **A `top` primitive's own repaint request redrew the whole pane.** Every
  `requestUpdate` invalidated at `Light`, which repaints the base canvas, but a
  `top` primitive is only ever drawn by `Pane.paintTop`, which runs at `Cursor`.
  The pane legend, the drawing layer's live preview, the trading pills, the
  buy/sell buttons, the chart table and the DOM ladder all sit there, so a
  cursor-rate update from any of them cost a full series redraw instead of one
  overlay repaint, times every chart in a linked grid. The host now reads
  `primitive.zOrder()` per call and requests `Cursor` for a `top` one, which
  fixes it for every such overlay with no API change and nothing for a primitive
  author to remember. Read per call rather than captured at attach, because
  `zOrder()` is a method and a primitive is free to change layer.

- **`destroy()` could run twice, and left every subscription attached.** A second
  call re-ran the teardown and would now re-emit `'destroy'`; and the listener
  map was never cleared, so a subscription on a destroyed chart retained its
  closure and everything that closure captured for as long as the host held the
  corpse. Both are closed: `destroy()` returns immediately if it has already run,
  and `_listeners` is cleared after the event goes out.

### Internal

- The yfinance demo drives all four features by hand. A toolbar split toggle
  opens a second `Chart` with its own symbol picker and interval pills, joined to
  a `createLinkGroup`; a link menu carries live crosshair, viewport and symbol
  switches plus the nearest / hide choice for a missing instant; Ctrl+C, Ctrl+X
  and Ctrl+V are wired to the controller's clipboard with the chords shown in the
  right-click menu; `withBarCache` sits behind the yfinance feed with a warm or
  fetched verdict in the status line and a hit counter in the toolbar; and 1MO
  and 1Q calendar intervals are registered and folded from daily bars through
  `bucketStartOf`.

  Two of its decisions were forced by running it rather than reading it. A freshly
  loaded follower fits its own content with viewport sync suspended: letting the
  fit broadcast threw the leader off the window the user was on, and adopting the
  leader's window instead left a month of hourly bars as a sliver in an empty
  plot, so the two converge on the first pan, which is what the group documents.
  And the demo caps a request's `to` at the newest bar it holds whenever the venue
  is shut: the cache only allows a hit past its coverage while the next bar is
  still forming and it cannot know a market is closed, so out of hours every load
  was cold no matter what. With the cap, a reload reports "warm 1 ms" against
  "fetched 320 ms".

- No size budget raised. Measured against the same limits 1.3.0 set: base
  52.88 kB of 55, base plus trade 59.46 of 62, indicators 24.88 of 27, draw
  13.11 of 14 (70 B for the clipboard exports), transform 2.66 of 5, profile
  10.66 of 11, everything 110.76 kB of 120.

- Test suite grew from 1543 to 1719 across 91 files.

## 1.3.0

### Added

- **Market replay.** `ReplayController` walks a historical session forward one
  bar at a time, so a setup can be practised on it and every indicator redraws
  exactly as it stood at that past moment.

  It is headless in the same sense as `DrawingController`: it owns the playhead
  and the transitions and ships no DOM, so the host renders its own transport
  bar and clock from `state()` plus the `replay:start`, `replay:frame`,
  `replay:play`, `replay:pause`, `replay:end` and `replay:stop` events on the
  chart's bus.

  The mechanic is deliberately plain. Every transition (a seek, a step, and
  each played frame alike) hands the series a fresh **prefix** of the full bar
  array through the ordinary `setData` path, and that path already recomputes each
  indicator from `sourceBars()`. Shorten the history and every plot, level,
  fill, marker and legend row reconstructs itself as it stood at that bar, with
  no replay-aware code anywhere in the indicator tier.

  Playback timing is injectable (`now` and `scheduler`), and the bars owed by a
  tick come from the clock rather than from the tick count, so a throttled
  timer still plays at the requested speed. A single tick is capped at ten
  bars, so returning to a backgrounded tab does not fast-forward the session.
  `stop()` restores the pre-replay data together with bar spacing and right
  offset, which is what reproduces the visible range to the pixel even if the
  user panned and zoomed while replaying.

- **Multi-symbol comparison.** `addComparison(chart, { symbol, bars })` puts a
  second instrument on the primary one's pane and returns a handle with
  `setBars`, `remove`, `list`, `priceScale` and `alignment`. The per-chart
  `ComparisonController` behind it adds `setMode`, `realign`, `clear` and
  `destroy`.

  Comparability comes from the scale, not from the data. The bars are stored as
  the instrument's own prices on the pane's hidden overlay scale, so the legend
  and the crosshair still speak in real prices; the pane switches to
  `percentage` (or `indexed-to-100`) while a comparison is on it, and a
  per-frame pass gives the overlay the primary's range scaled by the ratio of
  their baselines, so equal percentage moves land on equal pixels. Without that
  last step each scale autoscales to its own data and a 1% mover looks exactly
  like a 10% mover, which is the lie the feature would otherwise ship.

  Alignment answers the two directions of mismatch differently, because they
  mean different things. A comparison print with no primary bar is **dropped**:
  the DataLayer merges every series onto one index space, so a foreign
  timestamp would mint a logical index and shift the primary's own bars. A
  primary bar with no comparison print becomes **whitespace**, which the line
  renderer breaks across, so a holiday on one exchange reads as a gap rather
  than as a straight line drawn through it.

  A pane's single hidden overlay is usually already taken by the volume
  histogram, so the controller detects that and falls back to the left axis
  instead of autoscaling price and volume together.

- **Axis chrome: a corner session clock and a bar-close countdown.** Both are
  off unless a chart asks for them through `axisChrome`, so a chart that omits
  the block draws the axes it always drew.

  `axisChrome.sessionClock` fills the one rectangle no series, tick or tag ever
  occupies: the corner where the two axis strips meet. It reads in the chart's
  own timezone rather than the machine's, with the zone's offset from UTC on a
  second row so a trader can see which clock they are reading; pass
  `{ showOffset: false }` for the time alone, and it drops the row by itself in
  a strip too short to carry it.

  `axisChrome.barCountdown` adds a second row inside the last-price tag counting
  down to the current bar's close. The interval is read back off the bars
  (median of the recent gaps, so an overnight break does not stretch it) rather
  than configured, because the chart is never told its own timeframe and one
  that switches mid-session has to follow. Past the close the count rolls into
  the next bar's cycle instead of stalling at zero, so a feed that is late with
  a new bar still shows a running clock.

  Neither reaches a global clock. `axisChrome.clock` supplies wall-clock UTC
  seconds and defaults to the system clock, so a delayed or replayed chart can
  be honest about what time its data thinks it is.

- **Price-axis labels no longer draw underneath the last-price tag.** The tag is
  painted into the same strip a moment after the tick ladder, so it used to land
  on top of whichever tick label it overlapped and the two read as mush. The
  pane now reserves the band the tag will occupy before the ladder is drawn, and
  a tick colliding with it is dropped instead of drawn through.

  Only labels the tag would actually have covered are affected: a chart whose
  last price sits clear of every tick draws the same ladder it always did.
  `AXIS_LABEL_PRIORITY` ranks the claimants (crosshair over last price over
  price line over session level over previous close over plain ticks), so the
  reading a trader is actually chasing is the one that survives a pile-up.

- **Reference price levels as one family.** `PriceLevels` is a primitive over
  ten levels: previous close, session high and low, last price, the four
  extended-hours opens and closes, and bid and ask.

  Each level is **one options group carrying its own `line` and `label` flags**,
  so the horizontal line across the plot and the tag on the price axis are two
  switches on the same idea. Terminals that split those halves across separate
  menus let them drift, and a user ends up with an axis tag for a line that is
  not drawn. Colour, width, dash, tag text and how far the line runs from the
  axis (`extentFromRight`) sit in the same group.

  The session comes from the bars and never from a calendar midnight. The
  session in view is the one containing the viewport's **right edge**, so
  scrolling back through history moves the previous close back with it, and the
  boundaries are read out of the bar gaps by `sessionStartFlags`, falling back
  to the calendar only when the series shows no readable break, which is the
  right answer for daily bars. Previous close is the previous session's last
  *traded* close, walked back over a whitespace tail so a halted closing minute
  does not blank the level.

  **A level with no data is `null`, never `0`.** Extended hours need a phase the
  OHLC feed does not carry (`marketPhase`, a host-supplied classifier), and bid
  and ask need a live `quote`; without them those levels stay inert rather than
  drawing a line across the middle of the plot. `available(kind)` reports it, so
  a host renders that control disabled with its state visible instead of hiding
  it. `values()` reads the last frame's prices, and the pure
  `computePriceLevels()` behind it is exported, so the numbers are testable and
  usable in a readout without a canvas.

  The last price is not duplicated. The core already draws it from
  `SeriesStyle.priceLineVisible` / `lastValueVisible`, so that level defaults to
  off and `lastPriceLevelFromSeriesStyle` / `seriesStyleForLastPriceLevel`
  translate between the two shapes, letting a host present it in the same form
  as every other level while the series keeps owning it. There is deliberately
  no `autoscaleInfo`: a previous close a gap away would stretch the range and
  flatten the bars the chart is actually for.

- **Price-scale `percentage` and `indexed-to-100` modes.** `PriceScaleMode`
  gains the two rebasing modes, built by extending the existing transform pair
  rather than by adding a parallel path: percent change is the index minus the
  100 it rebases to, so both share one ladder.

  The baseline is data, not geometry, so it arrives through the new
  `setBaseline(value)`; the pane supplies the first visible bar each frame,
  which is what makes panning re-base. With no baseline the transform falls
  back to the identity and the scale behaves exactly like `linear` rather than
  answering with nonsense before the first frame. Zero and negative baselines
  are refused for the same reason: percent change from zero is undefined, and a
  negative baseline flips the sign of the transform, so a rising price would
  draw downward on an axis that still labelled itself normally.

  Labels switch to the rebased domain while a rebase is in force ("+3.42%" with
  an explicit sign, "103.42" for indexed, two decimals minimum) and deliberately
  outrank a custom price formatter, since a currency prefix on a percent change
  would read as money that is not there.

- **A chart settings schema.** `chartSettingsSchema(chart)` describes a
  terminal's settings dialog as tabs of controls in the same vocabulary the
  indicator settings form already uses, so a host that can render one can
  render the other with no new widget code. `readChartSettings(chart)` and
  `applyChartSettings(chart, patch)` are its round trip, over flat dotted keys
  that survive JSON.

  The schema and its accessors are one structure: each control carries its own
  `read` and `write` beside its input descriptor, so a control cannot drift
  from the option it drives and there is no second table to keep in step. That
  is also the rule for what ships in it. Every control maps to an option that
  changes what is drawn or stored; a checkbox with nothing behind it is absent
  rather than inert. Price-tab controls are generated from the primary series
  type, so a candle gets borders and wicks while a line gets a dash.

  Five tabs, grouped so a trader finds a setting without hunting rather than to
  mirror anyone else's dialog: **Price** (what the instrument is painted with),
  **Readout** (what the header says), **Axes** (what the two scales do, and the
  timezone), **Appearance** (the surface around the data) and **Trading** (what
  the trade layer draws). Alerts and Events are not among them: alerts arrive
  with the feature, events have no data source in the schema, and an empty tab
  is worse than an absent one.

- **A paired colour control, `colorPair`.** A property with a bullish and a
  bearish colour is one labelled row carrying its switch and both swatches side
  by side, not a section header over separate Up and Down rows. The stacked form
  triples the height of every panel, which is what forces a scrollbar onto a
  dialog that should fit.

  It is a schema **row** over ordinary flat value keys rather than a new value
  shape: the control carries `up.key`, `down.key` and an optional `enabled.key`,
  each an everyday key of `ChartSettingsValues`, so `readChartSettings` and
  `applyChartSettings` needed no new protocol, the patch stays JSON-safe, and a
  host that ignores the widget can still drive the row key by key.

  `enabled` is optional on purpose. Candle Borders and Wick have
  `borderVisible` / `wickVisible` behind them, a candle Body has no such flag,
  so that row ships with two swatches and no switch rather than with a checkbox
  that would do nothing. Candles, bars, columns, the line and baseline fills and
  the three trade-colour rows (long/short, take profit/stop loss, buy/sell) are
  all paired rows now.

- **The chart timezone is a control in the schema**, `time.timezone` on the Axes
  tab: a select over `CHART_TIMEZONES` (roughly east to west, so the list reads
  like a trading day) with the chart's own zone folded in when it is not one of
  them, so a host that configured `Pacific/Auckland` still sees its setting
  selected. It calls `chart.setTimezone`, and a name `isValidTimezone` rejects
  is skipped rather than thrown, so one stale zone in a restored layout cannot
  throw away the rest of the apply. A dialog no longer has to bolt its own zone
  row on beside the schema and hand-roll the Cancel path for it.

- **The Canvas option block.** `GridOptions` grows from a spacing-only bag into
  the grid controls a dialog needs (per-axis visibility, colour, dash and line
  width), and `CanvasOptions` gathers it with crosshair, scale text and line,
  and plot margins. `chart.setCanvasOptions` and `ChartOptions.canvas` apply it;
  `dashPattern`, `resolveGridStyle`, `resolveScaleStyle`, `resolveCrosshairStyle`
  and `resolvePlotMargins` are exported so a host can preview with the same
  code that paints.

  Option overrides theme when set, theme is the default. Theme colours are
  deliberately not copied into the options at construction: that would freeze
  the palette and make a later `setTheme` a silent no-op for everything the
  dialog had touched, so each resolver falls through field by field instead.
  Plot margins convert the dialog's percentages into the `marginTop` and
  `marginBottom` fractions the price scale already owns, so there is no second
  margin state.

- **Status line options on the pane legend.** The legend row now carries
  per-field switches (logo, title with a symbol, description or ticker mode,
  market status, chart values, bar change, volume, last day change, last value
  label, and a background plate with colour and opacity).

  The primitive invents no data. Readings the host already pushes through
  `setValues` carry an optional `field` tag, so one switch hides exactly one
  group, and the three things a legend cannot know (a logo bitmap, the market
  state, the day change) arrive through a new `status` option that accepts a
  snapshot or a per-frame getter and draws nothing when absent. Every switch
  defaults to the behaviour that predates it, so a caller passing no options
  gets the same row it always drew.

- **Chart timezone, and the default does not move.** A chart that names no zone
  is `Asia/Kolkata` as it always was, and keeps the frozen offset arithmetic
  rather than reaching `Intl` at all: its axis labels, its crosshair tag and
  every session-anchored number are what 1.2.0 produced, byte for byte, on the
  same code, and never depend on the host's ICU build. That is pinned rather
  than assumed: a harness diffs price ticks, the last-price tag, the time labels
  and the legend row across six datasets against a 1.2.0 worktree, and the same
  instants driven through the IANA link name `Asia/Calcutta`, which takes the
  zone-aware path, draw identical labels.

  To move a chart off it, `ChartOptions.timezone`, `chart.setTimezone(zone)` and
  `applyOptions({ timezone })` take an IANA name, `chart.timezone()` reads it
  back, and `getState()` carries it so a saved layout restores the hours it was
  saved with.

  Naming a zone moves the whole calendar and not only the labels: the time axis
  (including which ticks escalate to a day, month or year label), the crosshair
  time tag, VWAP's week, month, quarter and year anchors, CPR's weekly and
  monthly pivot frames, and the month a Seasonality bar's close is counted in.
  A `session` anchor still reads the session out of the bar gaps as it has since
  1.2.0, and falls back to the zone's calendar day only when the gaps are
  unreadable. On US intraday bars read in `America/New_York`, the last ninety
  minutes of the 30 April session now fall in April rather than in May:
  Seasonality reads that month's real return instead of 0.00%, and May's monthly
  pivot frame is built from April's real high instead of one truncated ninety
  minutes early. `setTimezone` recomputes those studies rather than only
  repainting, because moving the calendar changes the numbers and not just the
  axis under them. An explicit `timeFormatter` still outranks the zone: a host
  formatting its own labels has settled the question.

  An IANA name and not a fixed offset, because a zone that observes DST is a
  different offset in July than in January. Changeovers are followed rather than
  approximated: New York skips 02:00 on 10 March 2024, and London jumps 00:00 to
  02:00 on 31 March and prints 01:00 twice on 27 October. An unknown name throws
  where it is set, so the mistake surfaces at the call site rather than as a
  chart quietly showing the wrong hours; a stale name in a restored layout is
  skipped instead, so one bad zone cannot cost a whole saved workspace.

  The zone reaches an indicator on the settings blob under the reserved
  `timezone` key, which the chart supplies. It is deliberately kept out of the
  indicator's own settings, so a layout saved on a New York chart does not carry
  New York onto the chart that restores it.

- **A `contextmenu` event**, carrying the pane index, the price, the time, the
  logical index, and a classified target: a drawing, an indicator with its
  instance id, a legend, a primitive, a series with its type, a price scale, a
  time scale, or empty plot. Calling its `preventDefault` suppresses the
  browser menu; with no listener the existing save-image snapshot stays as the
  fallback.

  A price-scale hit says **which** scale it was: `side` is the strip that was
  clicked, and `scaleId` is the scale that strip acts on, `''` when the side
  carries no series of its own and the pane's values live on the hidden overlay.
  It is the argument the `priceAxis*` calls take, so a menu can be raised on
  what was actually clicked. The time axis now wins the bottom-left corner
  because it spans the full width and its dates run through it; the bottom-right
  corner stays the price axis', where its own labels run out. Plot hits are
  unchanged.

- **A price-axis menu the host can build without guessing.**
  `chart.priceAxisState(paneIndex, scaleId)` returns everything such a menu
  renders: `autoFit`, `inverted`, `mode`, `lockRatio`, the `side` it draws in,
  whether any series maps to it (`active`), whether anything has measured it
  (`scaled`), and whether a move would do anything (`movable`). The acting half
  is `setPriceAxisOptions`, `setPriceAxisAutoFit`, `setPriceAxisLockRatio` and
  `movePriceAxis`, and `PRICE_SCALE_MODES` lists the four modes in the order a
  menu offers them. Every item is both readable and actionable, which is what
  keeps a row from being drawn ticked and doing nothing.

  Moving an axis swaps the two side scales rather than copying their state, so
  the range, mode, margins and formatter travel with it; the vacated strip
  starts again from the chart-wide defaults, the axis columns are recomputed so
  a strip no pane uses any more is released and the plot reclaims its width, a
  `priceAxisMoved` event is emitted, and a move onto an occupied side is
  refused, because one strip draws one axis.

  The ratio lock is real rather than a stored flag: the pane keeps the geometry
  the lock was taken at and rescales the visible span by height over bar
  spacing each frame, in transformed space through `yToPrice` so a logarithmic
  axis is right too. Auto-fit or `resetScale` releases it, and locking is
  refused on a scale nothing has measured, since there is no ratio to hold.

- **`colorByPreviousClose` and `precision` on `SeriesStyle`.** The first colours
  a bar by close-versus-previous-close, which is how most terminals paint one:
  body, border and wick take a single verdict computed once per bar, so the
  candle cannot disagree with itself. It is honoured by the candle family and
  by OHLC / high-low bars, and the pane looks up the bar left of the visible
  range so the leading bar is quoted against something rather than falling back
  to its own open. The Price tab of the settings schema exposes it for those
  types. The second overrides the decimals the
  price scale infers. It rides the scale's *formatter* rather than its
  `minMove`, so `precision: 0` formats to whole numbers without also starting
  to snap prices to them.

- **More of the chart's option surface is readable and writable**, which is what
  a settings dialog needs: `canvasOptions`, `statusLineOptions`,
  `setPriceScaleOptions` and `priceScaleOptions`, `setAutoScale`, `setEvents`
  and `setEventOptions` for the chart-owned corporate-action strip,
  `tradingSettings` and `setTradingSettings` (which never instantiate the trade
  layer just to be read), `primarySeries` and `primarySeriesInfo`, `theme` and
  `crosshairMode`.

### Changed

- **`chart.getState()` carries the settings slice.** Canvas options, status line
  options, trading colours and the event filters ride along beside `grid`, and
  `restoreState` puts them back, so a saved layout no longer loses everything
  the settings dialog did. The return type widens to
  `ChartState & ChartSettingsState`, which is still a `ChartState` to every
  existing consumer, and canvas margins are applied before the panes so a
  pane's own saved margins remain the more specific answer and win.

- **The price scale owns its tick ladder.** `PriceScale.ticks(maxTicks)` builds
  what the axis renderer used to build for itself. It is byte-identical for
  linear and log, but the rebasing modes need the ladder chosen in label space
  and mapped back, because a nice price is an ugly percentage: without it the
  axis reads "+3.47%, +6.94%" instead of "+5.00%, +10.00%".

- **`setGridOptions` takes the whole grid block**, not just the two visibility
  flags, and the pane strokes the vertical and horizontal lines separately so
  each can carry its own colour and dash.

- **An HLC area strokes the two edges of its band.** `SeriesStyle.highColor` and
  `lowColor` had named the top and bottom of the band since the type was
  written, and no renderer had ever read them: the band was a fill and a close
  line, so setting either colour did nothing. Both are now drawn. Neither has a
  default, so an existing caller that named neither gets the frame it always
  got, and one edge can be stroked without the other.

- **`SeriesStyle.volumeScaled` is gone.** It had been superseded by the
  `volume-candle` chart type, which scales bodies from the visible maximum
  volume in the registry whatever the flag said, so no code path could consult
  it. Removed rather than wired: the capability is a chart type, and a second
  way to ask for it that has never worked is not worth keeping.

- **One settings key moved: `scales.lastValueVisible` is now
  `symbol.lastValueVisible`.** The key names the `SeriesStyle` field it patches,
  and it now sits beside the price line it contradicts when the two disagree.
  Every other dotted key is untouched: they are a wire format hosts have written
  down, and an unknown key in a patch is ignored, so a layout saved with the old
  name restores everything else and loses only that switch.

- **Session windows are wall clock in a zone they name.** `SessionWindow`'s
  `startMinute` and `endMinute` are minutes from midnight on the window's own
  zone, and every `TRADING_HOURS` preset now carries one, so `us-regular` reads
  as 09:30 to 16:00 `America/New_York` instead of an unexplained 1140 to 90.
  `MarketProfileOptions.timezone` and `VolumeProfileFamilyOptions.timezone`
  (both `Asia/Kolkata` by default) settle the day, week and month buckets for a
  profile whose window names no zone.

  A window's own zone outranks the display zone for the window test **and** for
  the bucketing, because bucketing on the display zone would cut a 09:15 to
  15:30 Kolkata session in half when the chart is read from New York: that
  session genuinely straddles New York midnight. A preset therefore selects the
  same instants and forms the same sessions on any display, and only labels
  move.

  **The presets reproduce the 1.2.0 instants exactly through a summer week, and
  are deliberately an hour later in winter.** The old table was authored in EDT
  terms - 1140 IST minutes is 09:30 New York only while EDT is in force - so
  `london`, `new-york` and `us-regular` silently drifted by an hour for the
  months either side of it, which is the defect the re-expression exists to fix.
  `india`, `asia` and `all-hours` are unchanged year-round.

### Fixed

- **Hollow candles ignored two of their own colour options.** In hollow mode the
  up outline was painted with `upColor` rather than `borderUpColor`, and
  `borderVisible` was never consulted at all; a filled down body in that mode
  got no border either, which left `borderDownColor` unreachable. The border
  colour is now computed once and used in both branches. The hollow up outline
  still draws with borders off, because it *is* the body, but falls back to the
  body colour rather than erasing the candle.

- **The zone stopped at the axis.** Four wiring gaps, each invisible to a test
  of either half on its own. The pane pre-baked its own labeller instead of
  handing `drawTimeAxis` the zone, so a host with its own `timeFormatter` was
  told the day had turned over at IST midnight whatever zone the chart was on.
  Nothing put the chart's zone on an indicator's settings, so `setTimezone`
  relabelled the axis while every session anchor kept computing on IST, and
  changing the zone did not recompute them. `colorByPreviousClose` was copied
  into the candle style object and nowhere else, so an OHLC bar series stored
  the flag and painted as though it were off. And the demo's O/H/L/C, change and
  volume readings carried no `field` tag, so the Chart values, Bar change values
  and Volume switches reached nothing and those readings answered to Indicator
  values instead.

- **A chart could measure itself before its container had a size.** Built inside
  a container the browser had not laid out yet, every price scale stayed on its
  `0..1` placeholder until something else forced a resize, so an early
  `priceToCoordinate` or a first-frame primitive read a range that was not the
  data's. The chart now re-applies the container size one frame after
  construction, and only when the container reports a real positive box, so a
  size the host applied itself and a container that is still hidden are both
  left alone. `destroy` cancels the pending frame. It uses the chart's own
  resolved scheduler, so a test driving frames by hand is not left waiting on a
  browser rAF that never comes.

- **Half the chart ignored a price axis that had moved.** Moving a pane's prices
  to the left strip relabelled the axis and left everything else pointing at the
  right one: the crosshair tag, the last-price line and tag, the coordinate API
  (`priceToCoordinate` / `coordinateToPrice`) and the axis drag all read the
  right scale whatever the prices were labelled in, and the left strip could not
  be dragged at all. Each now follows the scale the pane's values actually sit
  on.

### Internal

- The yfinance demo's settings dialog was rebuilt against the new schema: five
  tabs with their own glyphs, a paired-colour row rendered as one line with its
  switch and both swatches, themed checkboxes and selects instead of the browser
  defaults, colour inputs as small rounded squares rather than full-width bars,
  dark scrollbars styled once at the root, and a "Restore this tab" action
  driven by the schema's own declared defaults. Every tab, the densest included,
  now fits a 729 px viewport without scrolling. The hand-rolled Timezone row and
  its Cancel bookkeeping are gone: the schema's `time.timezone` control drives
  it, and the demo only mirrors the zone back so a chart rebuild keeps it.

- The demo also gained a price-axis context menu, built entirely from
  `chart.priceAxisState()`: auto-fit, invert and pin-price-per-bar as ticked
  toggles, the four scale modes as one exclusive group, a side-move row, and two
  flyouts over a `PriceLevels` primitive, one for the lines on the plot and one
  for the tags on the axis. A level with no data renders disabled with its state
  visible rather than being hidden. Alt+R/L/P/1, Alt+I and Alt+A are shown in
  the rows, in the same Alt+key grammar the drawing tier already uses.

- Size budgets raised for the new capability: base 42 to 55 kB, base plus trade
  49 to 62 kB, everything 96 to 120 kB. The indicator, draw, transform and
  profile tiers are untouched. Measured: base 49.37 kB, base plus trade
  55.95 kB, everything 105.88 kB.

- Test suite grew from 1129 to 1543 across 81 files.

## 1.2.0

### Added

- **Tables over the chart.** `ChartTable` is a new screen-space primitive: a
  grid pinned to a pane corner that stays put while the chart pans underneath,
  like the watermark and the pane legend. It has no time anchor, takes no part
  in autoscale, and survives a zoom untouched.

  Columns size from a fixed width, a per-column array, or a percentage of the
  plot; rows size from a fixed height, a percentage, or per-row weights, so a
  separator row can be a rule rather than a full-height gap. Type shrinks rather
  than overflowing when a stretched row is shorter than the declared font.

- **`IndicatorDescriptor.table`**, an optional hook beside `markers`, returning
  rows of cells and the table options to draw them with. It runs after `calc`,
  so it reads the values it just produced. An indicator whose output is a matrix
  rather than a column of prices had nowhere to put it: a plot is a price per
  bar, and a monthly return heatmap is neither. The runtime creates the table
  lazily, so an indicator without the hook pays nothing.

- **Five new built-in indicators**, taking the catalogue from 86 to **91**:

  - **Seasonality** (`seasonality`) - a monthly return heatmap, one row per
    year, with average, standard deviation and percent-positive summary rows.
    The first indicator to use the table hook, and the only one whose entire
    output is the grid. Months can be excluded by `YYYY-MM` key.
  - **CPR with Floor Pivot** (`cpr`) - the central pivot range and floor pivots
    across Daily, Weekly and Monthly frames, 27 plots in all. Auto mode picks
    one frame from the bar spacing; Manual stacks any combination.
  - **AlphaTrend** (`alphatrend`) - an ATR-offset trailing level gated by MFI
    (or RSI when the feed carries no volume), with the level shaded against its
    own two-bar lag and Buy/Sell plates at each crossover.
  - **Range Analysis** (`range-analysis`) - session range against its rolling
    average, as a two-column study.
  - **WaveTrend Pro** (`wavetrend`) - the channel oscillator with its signal
    line and momentum histogram, overbought and oversold bands, and cross
    markers.

- **Session boundaries are exported**: `sessionStartIndices`,
  `sessionStartFlags` and `calendarPeriodFlags` on the package root. They read
  an exchange's trading day back out of the bar timestamps, which is what the
  session-anchored indicators now use, and what a custom indicator should use
  rather than assuming a timezone.

### Changed

- **VWAP, TWAP and CPR read the trading session from the bars.** They anchored
  to an IST calendar day, which is 18:30 UTC. That is the middle of a New York
  session, so on US intraday bars VWAP restarted every afternoon, and CPR built
  each daily frame out of one session's tail plus the next session's head across
  the overnight gap.

  On a month of AAPL five-minute bars the old rule found 27 "days" with a widest
  range of 34.75 points, against 22 real sessions with a widest range of 11.14.
  S3 came out 37 points low, which stretched the price scale far past the
  candles.

  Sessions are now found from the widest recurring gap in the timestamps. The
  reading is declined, and the calendar rule kept, when there is nothing to
  read: bars already a day or coarser, a market that never closes, or a feed
  whose only gaps are weekends. An intraday lunch break is shorter than the
  four-hour floor, so it is not mistaken for a close.

  The coarser anchors (week, month, quarter, year) now compare session opens
  rather than every bar, for the same reason in the other direction: the last
  ninety minutes of a New York Friday fall on a Saturday in IST, which started
  the next week partway through Friday's session.

  **Behaviour on NSE data is unchanged.** Its session runs 03:45 to 10:00 UTC,
  so the session date and the IST date are always the same day.

- **`maximizePane` hides the other panes** instead of collapsing them to a
  sliver. They were parked at a 0.001 weight, which left a strip of squeezed
  candles and a separator hairline above the pane you had asked to see on its
  own.

  A maximized pane now takes the whole chart through the layout rather than by
  rewriting weights, and panes with no share are hidden outright, so their box
  paints no border and their canvases answer no hit tests. The bottom *visible*
  pane owns the time axis, so maximizing the price pane with indicators beneath
  it still gets a date axis. Stored weights are never disturbed, so
  un-maximizing restores the stack exactly and `getState` can no longer persist
  the placeholder.

### Fixed

- **A pane kept the price range of a departed indicator.** Panes are reused when
  one indicator replaces another, so swapping RSI for Seasonality left the table
  pane labelled 0.00 to 1.00 from a scale that had been 0 to 100. An indicator
  whose entire output is a table or a set of markers plots no values, so nothing
  ever autoscales its pane.

  A scale now forgets its range when it loses its last series, and the axis is
  drawn only for a scale that has actually been measured. A manually scaled axis
  is left alone, since nothing would recompute a range the user set by hand.

### Internal

- The yfinance demo gained a search box on the indicator menu, which 91 entries
  needs, and its saved layout now records the symbol, interval and period it was
  captured on. A viewport is a range of bar indices and a manual price range is
  a range of prices, and neither survives a change of dataset: restoring a day
  chart's view onto five-minute bars left the candles off-screen, which read as
  the chart having loaded nothing at all.

- Size budgets raised for the new capability: base 40 to 42 KB, base plus trade
  47 to 49 KB, indicators tier 21 to 27 KB, everything 90 to 96 KB. Measured:
  base 38.2 KB, indicators tier 24.7 KB, everything 94.0 KB.

- Test suite grew from 1001 to 1129 across 66 files.

## 1.1.0

### Added

- **66 new built-in indicators**, taking the catalogue from 20 to **86**. Every
  one is an original implementation written from the published definition of a
  well-known formula, verified against hand-computed values rather than
  transcribed.

  - *Moving averages and overlays*: ALMA, DEMA, TEMA, HMA, KAMA, LSMA, VWMA,
    McGinley Dynamic, Median, MA Cross, MA Ribbon, TWAP, Envelope, Donchian
    Channels, Keltner Channels, Chande Kroll Stop, Chandelier Exit, Williams
    Alligator.
  - *Momentum and strength*: Aroon, Aroon Oscillator, Awesome Oscillator,
    Balance of Power, Chande Momentum Oscillator, Coppock Curve, DPO, Fisher
    Transform, Connors RSI, Momentum, Rate of Change, PPO, TRIX, True Strength
    Index, SMI Ergodic Indicator, SMI Ergodic Oscillator, Stochastic Momentum
    Index, Know Sure Thing.
  - *Ranges and oscillators*: Stochastic RSI, Williams Percent Range, Ultimate
    Oscillator, Relative Vigor Index, Relative Volatility Index, Woodies CCI,
    Pring's Special K.
  - *Volatility*: Bollinger Bands %b, Bollinger BandWidth, BBTrend, Choppiness
    Index, Historical Volatility, Average Daily Range, Chop Zone, Mass Index,
    Ulcer Index.
  - *Volume and flow*: Chaikin Money Flow, Chaikin Oscillator, Ease of Movement,
    Elder Force Index, Klinger Oscillator, NVI, PVI, Price Volume Trend, PVO.
  - *Signals*: Vortex, Volatility Stop, Trend Strength Index, Williams Fractals,
    RSI Divergence.

- **Shaded fill regions on 22 descriptors** (28 fills in all), including the
  overbought/oversold background bands on RSI, Stochastic, Stochastic RSI, MFI,
  CCI, Connors RSI, Choppiness, Williams %R, Relative Volatility Index, SMI and
  Bollinger %b.

  The idiom is worth knowing if you write your own: `IndicatorFillSpec.between`
  resolves against **`calc` output columns, not declared plots**, so a band
  between two constant levels is a fill between two constant columns that are
  never plotted.

- **A smoothing block on CCI and OBV** matching the reference: a selectable MA
  over the indicator's own output, with optional Bollinger Bands around it.

### Changed

- **VWAP is substantially extended.** It now ships standard-deviation bands
  (three pairs at multipliers 1, 2 and 3, only the first shown by default), a
  `calcMode` of Standard Deviation or Percentage, six anchor periods (session,
  week, month, quarter, year, continuous), an `offset` input, and a fill per
  band pair. Its line colour is now `#2962ff`.

  The cumulative maths is unchanged, so existing VWAP plots are unaffected. Note
  that on daily bars with the session anchor each bar is its own session, so the
  bands collapse onto the line; they are an intraday tool.

- **Supertrend draws its shaded band** between the stop and the candle body
  midpoint, recolouring at each flip.

- Pane legends no longer print `Balance of Power` style parameter summaries
  containing bare booleans.

### Fixed

- **The `column` renderer ignored per-bar colour.** `drawColumns` always used
  the up/down pair from the series style, discarding the `color` set on each
  point, even though the indicator registry documents `colorBy` as supported by
  both the histogram and column renderers. Three indicators were silently
  painting a single colour across the whole series: Chop Zone, Awesome
  Oscillator and BBTrend. Chop Zone's nine-colour ladder was the visible symptom.

### Internal

- The indicator source modules were reorganised and renamed by family:
  `trend`, `momentum`, `volume`, `overlay`, `oscillators`, `volatility`, `flow`,
  `adaptive`, `averages`, `strength`, `ranges`, `indices`, `signals`, and
  `external` (formerly `tier2.ts`). These are internal paths, not published
  entry points, so nothing consumers import has moved.

- New calculation helpers shared by the ports: a standard SMA-seeded EMA (which
  differs from the base bundle's `ema` for roughly the first `length` bars),
  plus `change`, `roc`, `dev`, `percentRank`, `alma`, `vwma`, `highestBars`,
  `lowestBars`, `rollingSum`, `cumulative`, `linreg`, `swma`, `stoch`,
  `percentileNearestRank`, `correlation`, `cci`, `pivotHigh`, `pivotLow`,
  `barsSince` and `valueWhen`.

- Third-party product names removed from source and tests, with a CI step that
  fails the build if one reappears. The check is case-aware so it catches
  camelCase identifiers without tripping on legitimate names like Choppiness.

- Size budgets raised for the new catalogue: indicators tier 9 to 21 KB,
  everything 76 to 90 KB. Measured: indicators tier 20.1 KB, everything 88.2 KB.

- Test suite grew from 620 to 1001 across 61 files.

## 1.0.29

### Added

- **HalfTrend** joins the indicator tier as `halftrend`, bringing the built-in
  count to 20. A trend-following level that holds flat through noise: two state
  machines run at once, and a flip only fires when the mean high (or low) crosses
  the tracked extreme **and** the bar closes beyond the previous bar's low (or
  high). Requiring both is what keeps the level still where a moving average
  wobbles. Ships with half-ATR channel bands, per-side ribbons, and Buy/Sell
  labels, each independently toggleable.

  Original implementation written from the algorithm's published behaviour, per
  ARCHITECTURE.md §0.1, not ported from any third-party source.

- **`IndicatorDescriptor.markers`**: an optional hook returning bar-anchored
  `SeriesMarker`s, run after every `calc` so it reads the values it just
  produced. A plot cannot express a named signal: a plot is a column of prices,
  whereas a flip is a discrete event with a label. The runtime creates the marker
  layer lazily on the first plot's series, so an indicator without the hook pays
  nothing.

- **`INDICATOR_PLOT_STYLES` is now exported** from the package root. The docs
  already listed it as an import, but it was only declared internally, so the
  documented call failed. It is the plot-style option list a generated settings
  form offers alongside `INDICATOR_LINE_STYLES` and `INDICATOR_SOURCES`.

- **`labelUp` / `labelDown` marker shapes**: text plates with a tail that points
  at the anchor price, for named signals rather than bare glyphs. `labelUp` puts
  its body below the anchor, `labelDown` above. `drawLabel` is exported for
  custom primitives that want the same plate.

### Fixed

- **`VERSION` had drifted four patches behind `package.json`** (it read `1.0.24`
  at the 1.0.28 release), so anything displaying the library version showed the
  wrong one. A test now pins the two together.

- **Pane legends no longer print `true true true`.** `_paramSummary` included
  boolean inputs, so an indicator with visibility toggles rendered them as bare
  words. Booleans are now excluded for the same reason colours already were: the
  value names nothing, and what the toggle did is already visible on the chart.

### Changed

- Size budgets raised for the new feature: base 37 -> 38 KB, base+trade 44 -> 45
  KB, everything 73.5 -> 76 KB. Measured: base 37.00 KB, everything 74.17 KB.

### Documentation

Corrected claims that no longer matched the source. The library behaved
correctly in every case below; the docs did not.

- README: version (said 1.0.8), test counts (said 468 across 47 files, now 619
  across 50), and both size tables, which disagreed with each other because they
  were snapshots from different releases.
- README + ARCHITECTURE.md §13a: the four stated **Footprint gaps are all
  stale**: the renderer is theme-driven, has `setOptions`, three display modes,
  and draws stacked imbalances. Replaced with the real remaining gap: only
  `Footprint` reads `rc.theme`; `VolumeProfile`, `MarketProfile` and
  `HorizontalProfile` do not.
- README + ARCHITECTURE.md §13a: **overlay price scales are implemented**
  (`priceScaleId: ''`). Only `percentage` and `indexed-to-100` are absent.
- `ChartOptions.theme` JSDoc said `darkTheme` was the default; `DEFAULT_THEME`
  is `lightTheme`. This one shipped in the typings.
- The event-bus comment claimed `chart.trading.on('order_modify')` was
  equivalent to the prefixed name. `TradingController` keys its listener map on
  the full `trading:order_modify`, so the bare name never fired.
- `events.mdx`: `click` carries `{ id, price, time, paneIndex, point }` and `id`
  is **`null`** for a click on empty space; `drag:end` carries the same shape
  minus `point`. Both were documented as near-empty payloads.
- `data-feeds.mdx`: `TradeFeed` was documented with `orderBook()` /
  `positionBook()` / `marketDepth()`; it actually declares `subscribeOrders` /
  `subscribePositions`. Added the `OrderFeed` vs `TradeFeed` split, since
  `OrderEngine` takes the smaller one.
- `trading.mdx` called `eng.placeLimit(...)`, which does not exist, corrected to
  `placeOrder` with a real `PlaceRequest`.
- `drawing-tools.mdx` showed `draw.add('rectangle', [a, b], style)`; `add` takes
  a single drawing object.
- `primitives-and-plugins.mdx` showed `zOrder` as a property in one snippet and
  as a method in another. It is a method.
- `market-profile.mdx` used `colorMode: 'heat'` and `showLetters`, neither of
  which exists, the heat modes are `count` and `volume`, and letters are
  controlled by `blockDisplay`.
- `scales-and-panes.mdx` documented `timeScale.scrollToRealtime()`, which does
  not exist.
- `keyboard-shortcuts.mdx` said the arrow keys pan one bar; they pan two.
- `live-data.mdx` referenced an exported `mapOrderStatus`; the mapping is
  internal.
- Stale built-in counts corrected across the source comments, README,
  `getting-started.mdx` and `.size-limit.json`, plus the draw tier's header,
  which still said 18 tools when 43 are registered.

## 1.0.28

### Added

- **Drawing tools carry a keyboard `shortcut`.** The built-in line tools ship
  the standard chords, `Alt+T` trend line, `Alt+H` horizontal line, `Alt+J`
  horizontal ray, `Alt+V` vertical line, `Alt+C` cross line, and any tool
  registered with `registerDrawingTool` can declare its own.

- **`matchDrawingShortcut(event)`** resolves a key event to a tool id, and
  **`drawingShortcuts()`** returns the `id -> shortcut` map for rendering the
  chord beside a tool's name in a palette.

  The library installs no listener: only the host knows whether the chart has
  focus, a dialog is open, or the user is typing. Modifiers must match exactly,
  so `Alt+T` does not fire for `Ctrl+Alt+T` and a tool cannot shadow a browser
  or host chord; a bare letter never matches, so ordinary typing is unaffected.
  `metaKey` counts as Ctrl.

## 1.0.27

### Added

- **`PriceLine.setOptions()`** restyles a line in place, colour, width, dash,
  labels, badges, and repaints. Only `setPrice`, `setLeftLabel` and
  `setDragGhost` were updatable, so a line's colour was fixed at construction
  and a last-price line could not follow the tick direction. `id` is excluded:
  it is the handle the chart routes clicks and drags through, and swapping it
  under a live drag would strand the gesture.

## 1.0.26

### Fixed

- **Price-scale margins are fractions of the pane height, as documented.**
  `autoscaleRange` padded the *data span* by the margin instead, so how much
  room a margin reserved depended on how tall the data happened to be. A volume
  overlay asking for `marginTop: 0.82` to sit in the bottom 18% of the pane got
  `high + 0.82 * span` and drew its bars across **55%** of it, swallowing the
  price series.

  The data band now occupies the `1 - marginTop - marginBottom` left between the
  margins. Margins totalling 1 or more keep a sliver of room rather than
  producing an infinite range.

  Existing charts on the `0.1` default shift by a few percent (the data band
  goes from 83% of the pane to 80%); only large margins, which were the broken
  case, move noticeably.

### Changed

- Third-party product names removed from source comments, docs and examples.

## 1.0.25

### Added

- **`LogoWatermark` plate padding is settable.** `padding` takes a number for
  both axes or `{ x, y }` for each, defaulting to the previous `{ x: 7, y: 4 }`.
  `height` sizes the mark and `padding` sizes the plate around it, so the corner
  at rest is now exactly specifiable: a 40px mark with `padding: 2.5` sits in a
  45x45 square.

### Fixed

- **The plate is its requested size at every DPR.** The padding was rounded to
  device pixels and then doubled, so a fractional value was rounded twice and a
  plate asked to be 45px tall came out 46 on a non-retina display. The four
  edges are snapped instead, which also keeps the border crisp.

- **The hover target follows the padding.** It was fixed at 4px around the mark,
  so a generously padded plate had dead margins that looked interactive; it now
  matches the visible plate, with 4px kept as the floor so a tightly padded mark
  is still a forgiving target.

## 1.0.24

### Added

- **`LogoWatermark` can be a hover-revealed, clickable brand lockup.** `label`
  shows the mark alone at rest and unrolls the wording to its right on hover,
  clipped to the revealed width so the text wipes out of the mark rather than
  fading in place.

  The mark and the label **share one colour**: whichever of `tint` or
  `labelColor` is set drives both. Left to render independently, the mark kept
  its source colour and sat beside the label in an unrelated shade.

  A rounded `background` plate sits behind the pair, drawn at full alpha so it
  does not inherit the logo's transparency: without one the wording lands
  straight on the candles and is unreadable wherever the chart is busy.

  `href` marks it clickable, the hit reports a pointer cursor and `href()`
  returns the URL with `utm_medium`, `utm_campaign` and a `utm_source` naming
  the embedding page (host and path only, never the query string). A canvas
  cannot hold an anchor, so the host does the navigating.

  A mark with neither `label` nor `href` stays out of the hit path entirely, so
  plain decoration cannot swallow clicks meant for the chart.

### Fixed

- Tinting borrowed a document from the drawing context to build its offscreen
  canvas, and threw where there was none. It now falls back to an untinted mark
, which matters more now that a labelled mark is always tinted.

## 1.0.23

### Fixed

- **`sma` was poisoned permanently by a single non-finite value.** It kept a
  running sum, so `sum += NaN` made every later value `NaN`, and subtracting
  the NaN back out when it left the window could not restore it. Any indicator
  fed a series with a warmup gap, which is any indicator chained onto another,
  produced nothing at all for the whole series. It now sums only finite values
  and counts the rest, so it reports `NaN` while a gap is inside the window and
  recovers the moment it leaves.

### Added

- **Per-bar plot colour.** `IndicatorPlot.colorBy` returns a colour per bar, and
  histogram and column renderers honour a `color` on the data point. One colour
  for a whole series cannot express a study whose meaning changes bar to bar.

- **MACD's histogram is four states**, matching how it is normally read: above
  or below zero says which side, and rising or falling against the previous bar
  says whether that momentum is building or fading. All four are settings
  (`histUpColor`, `histUpFadeColor`, `histDownColor`, `histDownFadeColor`), and
  the MACD/signal lines default to blue and orange.

- **`William VIX FIX`** (`williams-vix-fix`), a synthetic VIX from price alone.
  The histogram goes lime when `wvf` pierces its Bollinger upper band or the top
  percentile of its range, gray otherwise, with the range lines and upper band
  drawable via the `hp` / `sd` toggles. Those toggles hide the *plots* only: the
  colour rule reads its own columns, so hiding the band cannot silently stop the
  alert, which is the whole point of the study.

- **A hairline between stacked panes**, themed as `paneSeparator`. Drawn on the
  pane's DOM box, so it sits exactly on the boundary the user drags rather than
  drifting from it when weights change.

### Changed

- Base+trade budget 42.5 -> 43 KB for the new indicator.

## 1.0.22

### Fixed

- **A maximized indicator pane drew its legend through the host's overlay.**
  `legendOffset` was pinned to one pane index, on the assumption that the host's
  own readout always covers pane 0's corner. Maximizing a lower pane parks the
  others at a placeholder weight, so the maximized pane moves into that same
  corner, and, not being pane 0, kept the default corner and drew straight
  through the host's symbol / OHLC line.

  The offset now follows whichever pane actually renders at the chart's top,
  re-evaluated on every relayout. `legendOffset.paneIndex` is gone; it described
  a fixed answer to a question whose answer moves.

  Host-added legend rows are left alone, a host positions its own.

## 1.0.21

### Fixed

- **`legendOffset` shifted every pane, not just the overlaid one.** A host that
  offsets the price pane clear of its own OHLC readout was also pushing the
  legend on each lower indicator pane down by the same amount, and a lower pane
  is short, so its row went off the pane entirely, taking the settings, close
  and move-pane buttons with it. An RSI pane could not be configured, moved or
  removed from its own legend.

  The offset now applies to one pane, `paneIndex` (default 0), because that
  overlay is nearly always on the price pane. Every other pane keeps the
  default corner.

## 1.0.20

### Added

- **A repeated indicator gets its own colours.** Adding a second EMA gave it the
  descriptor's one default blue, so three EMAs were indistinguishable both on
  the chart and in the legend, and telling which row belonged to which meant
  opening each one's settings.

  The 2nd and later instances of the same `indicatorId` now rotate through a
  palette. Only colour keys the caller left unset are filled, so an explicit
  colour always wins; the first instance keeps exactly what the descriptor
  chose; and the count is per indicator id, so adding two EMAs does not shift
  the first RSI. Multi-plot indicators stride by their plot count, so MACD's
  three lines shift as a block instead of landing on the previous instance's
  colours.

## 1.0.19

### Fixed

- **`BuySellButtons` painted its label outside the button at any `scale` below
  1.** The price and label baselines were fixed pixel offsets (18 and 33) tuned
  for the 42px box, so they were exact at scale 1 and increasingly wrong below
  it, at 0.72 the label sat 3px past the bottom edge. They are fractions of the
  button height now, which is the same result at scale 1.

## 1.0.18

### Added

- **A plot's chart type is now a setting.** `indicatorStyleInputs` generates a
  "Plot style" select per plot (`<plot>:type`), so the same column of numbers can
  be drawn as a line, step, area, histogram or columns, a descriptor cannot know
  which reads best for a given use. Defaults to the declared type, so nothing
  moves unasked. `INDICATOR_PLOT_STYLES` is the option list.

  Switching rebuilds that plot's series rather than restyling it: the chart type
  belongs to the series, not the style bag.

## 1.0.17

### Added

- **Indicator fills, the Ichimoku cloud.** A descriptor can declare `fills`,
  shading the band between two of its plots. Two lines are not the same picture
  as a filled region: the shading is what makes "price is above the cloud" and
  "the cloud flipped" readable at a glance, and which span leads is itself the
  signal, which is why the band takes two colours.

  Ichimoku now ships one between Senkou Span A and B, restyleable through
  `cloudUpColor` / `cloudDownColor`. Runs are split at the exact crossing rather
  than the nearest bar, or the colours would bleed a bar past every flip, and a
  gap in either plot breaks the band instead of bridging it.

  `IndicatorFill` is exported for hosts that want to shade their own pair.

- **The `measure` tool reports what a measurement should.** It drew a box and
  one line of text; it now draws the price and time arrows that make it read as
  a measurement, and a chip carrying the change, percentage, bar count,
  calendar span, and (via `rc.bars()`) the volume over the span.

### Changed

- Base tier budget 35 -> 36 KB, base+trade 41.5 -> 42.5 KB, full 72 -> 73 KB.
  The fill primitive lives in the base bundle because `IndicatorInstance` does.

## 1.0.16

### Added

- **`BuySellButtons` takes a `scale`** (default 1, clamped 0.6 to 1.5). The panel
  was a fixed 190x42, which crowds the pane's legend rows in a dense trading
  layout and left no way to make room. Box, gaps, corner radius and type all
  scale together, and so do the hit rects, a smaller button that still took
  full-size clicks would be worse than no option at all.

## 1.0.15

### Added

- **`legendOffset` chart option**: where indicator legend rows start inside a
  pane, in media px. A host that draws its own overlay in the top-left corner
  (an OHLC readout, a symbol line) had no way to push the canvas rows clear of
  it, so adding an indicator landed its legend *underneath* the host's own text:
  unreadable, and its settings and close buttons invisible and unclickable.
  Defaults to `{ top: 6, left: 8 }`, so nothing moves unless you ask.

## 1.0.14

The lazy tiers were unusable from TypeScript. Fixed, with a build guard so it
cannot come back. 556 unit tests.

### Fixed

- **`openalgo-charts/draw`, `/trade` and `/profile` could not be used from
  TypeScript at all.** Passing the chart from `createChart()` to
  `new DrawingController(chart)` failed with

  > Types have separate declarations of a private property `_container`

  and there was no way to fix it from outside the package.

  Each tier is bundled into its own `.d.ts`. A tier that imported a shared type
  through a *relative* path had that declaration **inlined**: so `Chart`,
  `TimeScale`, `PriceScale` and `DataLayer` each existed twice. Those classes
  carry private members, which makes them nominal rather than structural, so the
  second copy was a genuinely different type to TypeScript. Plain JavaScript
  consumers never noticed, which is why it survived this long.

  Tiers now import shared types from the package entry, which tier builds
  already leave external, so there is one declaration and one identity. The tier
  declarations shrank as a side effect: draw 47 KB -> 17 KB, trade and profile
  similarly.

- `DrawingController` takes a structural `DrawingChartHost`, the seven members
  it actually uses, rather than the whole `Chart` class. The real chart
  satisfies it with nothing to cast, and the contract now states what the
  controller needs.

### Added

- **`DataLayer`, `IndexedBar` and `SeriesId` are exported types.**
  `chart.dataLayer` was public while its type was not nameable, so a consumer
  could hold one but never declare one.
- `npm run check:dts`, wired into `verify`: fails the build if any tier
  re-inlines a shared declaration.

## 1.0.13

Nine more drawing tools (34 -> 43), freehand brushes, one-click position tools,
and the fix for `path` / `polyline` being impossible to finish. 556 unit tests.

### Fixed

- **Brush and Highlighter behaved as polylines**: a vertex per click, and no
  way to end the shape. Both are `points: 0`, which the controller read as
  "collect anchors until told to stop", the same contract `polyline` wants.

  `DrawingTool` gains `freehand`. A freehand tool samples the cursor while the
  pointer is held and commits on release, so one press-drag-release is one
  stroke. `crosshair:move` now carries `pressed`, since placement mode swallows
  the pan path and there was otherwise no way to observe a drag in progress.

- **A selected brush showed a grab handle on every sampled point**, burying the
  ink under dozens of circles and leaving no way to grab the stroke itself. A
  freehand drawing now handles only its two ends; it still keeps every sample,
  which is what gives it its shape.

### Added

- **Nine more drawing tools**, taking the built-in set from 34 to 43 (draw tier
  8.3 KB -> 11.3 KB Brotli):

  Shapes: `rotated-rectangle` (anchors 0->1 lay out an edge, 2 sets the depth
  perpendicular, so it can follow a trend channel an axis-aligned rectangle
  cannot) and `double-curve` (an S through three anchors, the second control
  mirrored about the chord's midpoint). Cycles: `cyclic-lines`, `time-cycles`,
  `sine-line`. Text and notes: `price-label` (reads its value off the anchor, so
  dragging it re-reads rather than going stale), `callout`, `flag-mark`.
  Brushes: `brush`.

- **`path` and `polyline` can now be finished.** Both declare `points: 0`, and
  nothing could ever complete them -- double-click reset the view instead, so
  they collected vertices forever. Double-click now finishes the shape while a
  tool is armed, and `controller.finish()` is public for binding a key.

- `path` is a click-per-vertex shape again, with an arrowhead on its last leg --
  what separates it from `polyline`. The freehand brush moved to its own `brush`
  id, so the two are no longer one tool wearing two names.

- **`DrawingTool.expand`**: a tool can turn the anchors actually clicked into
  its full anchor set, so it can place a complete, immediately editable default
  from fewer clicks. Receives `barSeconds` and `visibleBars`.
- **Long/Short Position place from a single click at 1:1**, sized to ~8% of the
  visible range so the box is grabbable at any zoom, with all three anchors
  still draggable. Previously they needed three clicks and drew nothing until
  the third.
- **Position and Forecast readouts** are now chips rather than one terse line.
  Position: `Target: <Δ> (<%>), Amount: <cash>` outside the target line,
  the same for `Stop`, and `Qty` / `Risk/reward ratio` at the entry, each
  hugging its own line, so the layout reads the same for a long and a short.
  Forecast: the anchor price/date, the projected move with its duration and
  landing price/date, and a SUCCESS/MISSED verdict once the window has elapsed.
- **`PrimitiveRenderContext.bars()`**: the pane's primary price series, lazily,
  for a primitive that needs what price actually did rather than just the
  scales. The forecast verdict is the first caller.

### Demo

- **5m / 15m / 30m drew nothing** while 1h and 1d worked. Yahoo caps intraday
  history (~60 days for 5m-90m, ~730 for 1h) and answers an over-long request
  with an *empty* frame rather than an error, so the default 1y range silently
  produced no bars. The range is now clamped to what the interval can serve,
  the range menu only offers those, and the status line says when it clamped.
- The yfinance dev server sends `Cache-Control: no-store`. The browser keeps ES
  modules in its own module map, so rebuilding the library and reloading still
  ran the previous bundle with no sign anything was stale.

## 1.0.12

A fix for the forming candle rendering as two overlapping candles of opposite
colour during live ticks, and `version()` catching up with the package version.
534 unit tests.

### Fixed

- **The forming candle could render as two overlapping candles of opposite
  colour**: a red body with a green one painted over it, and a wick spanning
  both, while live ticks came in.

  `setData` sorted its input by time but never de-duplicated it, while the
  shared time axis collapses times through a `Set`. Two bars at the same time
  therefore resolved to the same logical index, so `visibleBars` handed the
  renderer both and they drew at the same x, the second over the first. A live
  feed produces that pair whenever its candle builder starts unseeded: it opens
  a fresh bar for the bucket the fetched history already ends in, and the host
  appends it alongside the historical one. Reconnecting mid-bar does it again.

  `setData` now collapses repeated times, keeping the last occurrence, the
  newer value when a live bar arrives alongside the historical bar it
  supersedes. `prependData` and `update` already de-duplicated.

  Seed your candle builder from the last historical bar
  (`builder.seed(bars[bars.length - 1])`) so the live bar continues it: an
  unseeded builder still opens at the first tick price it sees rather than the
  bucket's true open.

- **`VERSION` / `version()` reported `1.0.8`**: the constant is hand-maintained
  and was missed by the 1.0.9, 1.0.10 and 1.0.11 bumps. It now matches
  `package.json` again.

## 1.0.11

16 more drawing tools, rail flyout menus, and the fix for a blank
region that could appear under the chart and persist across reloads.
532 unit tests.

### Added

- **16 more drawing tools**, taking the built-in set from 18 to 34 (draw tier
  6.6 KB -> 8.3 KB Brotli).

  Shapes: `circle`, `triangle`. Paths: `polyline`, `arc`, `curve`. Channels:
  `fib-channel`. Fibonacci: `fib-time-zone`, `fib-fan`. Gann: `gann-fan`,
  `gann-box`. Forecasting: `forecast`. Measurers: `price-range`, `date-range`.
  Arrows: `arrow-up`, `arrow-down`. Brushes: `highlighter`.

  `circle` measures its radius in pixels, so it stays round on screen rather
  than becoming the ellipse differing axis scales would otherwise produce. `arc`
  passes *through* its middle anchor while `curve` treats that anchor as a
  control handle. The measurers all take their bar count from logical indices,
  so it matches the gapless axis rather than raw elapsed time.

- **Rail flyout menus in the yfinance demo.** Rail groups now open a sectioned
  list of their tools, the pattern professional terminals use, instead of cycling tools
  on repeat clicks, which was undiscoverable past two. The button re-activates
  the last tool picked; the caret opens the list. Icons were redrawn on a 24x24
  grid with a thinner stroke and outlined endpoint handles.

- **Right-click drawing actions in the yfinance demo**: "Delete Drawing" for
  the selected one and "Remove All Drawings (n)" for the lot. Both rows hide
  when there is nothing to act on, so the menu never offers a dead option.

- `pane.primitives()`, matching the existing `pane.series()`.

### Fixed

- **A large blank region could appear under the chart, and persist across
  reloads.** Three faults compounded.

  `removeIndicator` did not prune the pane it had just emptied, that logic sat
  in the pane legend's close handler, so the on-chart X cleaned up but a host
  removing the same indicator from its own UI (a toolbar chip, a menu) left an
  empty pane behind. An empty pane still claims its weight and still draws a
  default 0..100 price axis, which is the blank region plus the second set of
  axis labels under the price ticks. The pruning now lives in
  `removeIndicator`, so every caller behaves the same.

  `getState` then persisted that orphan, and `restoreState` faithfully rebuilt
  it, so once it happened it survived every reload. `restoreState` now drops
  panes that end up with no series.

  `maximizePane` parks the other panes at a `0.001` placeholder and snapshots
  the real weights by index, but `removePane` never spliced that snapshot, so
  un-maximizing restored weights against a shifted array and could strand panes
  at the placeholder. `removePane` now keeps it aligned.

- **The yfinance demo rendered a white chart inside dark chrome.** It never
  passed a theme, and the library default is the light palette (since
  `275ee1e`). It now asks for `darkTheme` explicitly.

- The drawing-tools doc had a blank line splitting its style table, which broke
  the last three rows out of the table in the rendered page.

## 1.0.10

Market Profile brought up to a full TPO implementation, row height became a
setting rather than a side effect of tick size, and the chart gained
hover-revealed zoom controls. 518 unit tests.

### Added

- **Time navigator**: the zoom / step controls that live just above the time
  axis. Invisible until the pointer nears the bottom of the chart, then faded in
  over `fadeSeconds`: `-` `+` to zoom, `‹` `›` to step exactly one bar.

  The buttons run the *same* commands the keyboard does (`_runShortcut`), so the
  two paths cannot drift apart, and each tooltip reads its combo from the live
  keymap, rebind `zoomIn` and the tooltip follows. On by default; pass
  `timeNavigator: false` to drop it, or an options object to restyle. It rides
  the bottom pane and follows when panes are added or removed, and hit-tests to
  nothing while hidden so it never steals a click from the chart underneath.

  Reveal is driven by pointer position rather than `rc.hoverId` on purpose: hover
  ids come from `bestHit`, so a drawing or an order line near the bottom of the
  chart would win the hit and silently hide the controls.

  New commands `panLeftBar` / `panRightBar` (one bar, unbound by default) and a
  public `pane.primitives()` accessor, matching the existing `pane.series()`.

- **Controllable TPO / footprint row height.** Row height is now
  `tickSize * rowTicks` instead of being pinned to the instrument tick. The
  multiplier is the one a trader already thinks in: Nifty trades in 0.1 and you
  want 2-point rows, so `rowTicks` is `2 / 0.1 = 20`. `rowTicksFor(2, 0.1)` does
  the division. Keeping the two separate matters, the tick is what imbalance and
  single-print logic count on, so widening rows must not mean lying about it.

  The same multiplier reaches order flow: `computeFootprint(t, trades, 0.1, 20)`
  and `new FootprintAggregator(tf, 0.1, 20)`, so a chart's bricks and its profile
  rows can share one grid.

- **Letters degrade to bricks automatically.** A TPO row is only as tall as the
  price scale makes it, so at some zoom a letter stops fitting. `blockDisplay:
  'auto'` (the new default) crossfades: the block is always drawn and the letter
  fades in over `letterFade` px above `minLetterHeight`, so zooming through the
  threshold reads as one continuous change instead of a jump. `'letters'`,
  `'blocks'` and `'blocks+letters'` pin the choice. The footprint fades its cell
  numbers the same way via `textFade`, replacing a hard on/off cutoff.

- **Market Profile analytics.** Per-period detail (`periodDetail`), the
  developing POC / value-area track, day type (normal / normal-variation / trend
  / double-distribution / neutral), open type (drive / test-drive /
  rejection-reverse / auction), range extension beyond the initial balance,
  buying and selling tails (`tailEdges`), volume POC, and `nakedLevels()` for
  prior POC / VAH / VAL no later session traded back through.

- **Session windows.** `window` drops bars outside a trading session and anchors
  period `A` to the window's open rather than to whatever bar arrived first, 
  which otherwise shifted every letter. Windows crossing midnight are treated as
  one session instead of two halves. Built-ins in `TRADING_HOURS`: `all-hours`,
  `india`, `asia`, `london`, `new-york`, `us-regular`. `compositeSessions` merges
  N consecutive sessions into a rolling composite.

- **Renderer options** to match: `colorMode` gains `period` (one hue per TPO
  period, now the default) alongside `valueArea` / `count` / `volume` / `uniform`;
  plus `split` period columns, `showTpoCounts`, `showTails`, `showPoorHighLow`,
  `showNakedLevels`, `showDevelopingPoc` / `showDevelopingVa`, `showDayType` /
  `showOpenType` / `showSessionLabel`, `outsideVaOpacity`, `profileSpacing`,
  `volumeProfileSide` and `showVolumeValues`. `hitTest` / `hoverAt` map a pointer
  back to the session and row for a host-drawn tooltip.

### Fixed

- **The docs Market Profile example rendered a histogram, not a market profile.**
  The "Market Profile (TPO)" section used `computeTpo` + `HorizontalProfile`, a
  volume-profile-shaped bar chart with no letters at all, even though the
  `MarketProfile` letter renderer already existed. It now uses
  `computeMarketProfile` + `MarketProfile`, and `examples/market-profile` was
  rebuilt around the real primitive with a live row-size slider.

### Changed

- `MarketProfile`'s `showLetters` boolean is replaced by `blockDisplay`
  (`showLetters: false` becomes `blockDisplay: 'blocks'`).
- The profile tier's size budget moves from 8 KB to 11 KB (now 10.12 KB
  brotlied) to cover the analytics above. The base engine moves from 34 KB to
  35 KB for the time navigator (418 B).

## 1.0.9

Order-flow overhaul, drag-to-draw, shape text, and a price-axis density fix.
492 unit tests.

### Added

- **Footprint rewritten** (`src/profile/footprint-primitive.ts`). Cells now fill
  proportionally to volume instead of being outlined, so a column reads as a heat
  ladder; imbalanced cells fill *saturated* rather than gaining a border, and runs
  of consecutive same-side imbalances get a bracket down the edge.

  New options: `displayMode` (`bidask` | `delta` | `volume`), `statsRows`, a
  per-bar table of `volume` / `delta` / `deltaPct` / `cvd` / `trades`, each cell
  tinted by its own strength, plus `stackedImbalances`, `showPoc`, `showCandle`,
  `widthFactor`, `radius`, and `minTextHeight`. Column width derives from the
  chart's bar spacing unless `cellWidth` pins it, and rows shorter than
  `minTextHeight` drop their numbers and degrade to a pure heatmap, so zooming
  out never turns into unreadable overlap.

  `setOptions()` merges and repaints for live restyling; `hitTest()` and
  `hoverAt()` map a pointer back to the bar and price row so a host can build a
  tooltip without the library owning any DOM. `autoscaleInfo()` now returns a
  range, so the footprint drives the pane's scale.

- **Shape text.** `DrawingStyle` gains `fontColor`, `textVAlign`, and
  `textPosition`; rectangles, ellipses, and parallel channels now render a
  `style.text` label, one shape with two colours (`color` strokes the outline,
  `fontColor` paints the label). `textPosition: 'inside'` with
  `textVAlign` x `textAlign` gives the nine placements a shape-text
  panel exposes; `'outside'` parks the block above the shape.

- **Live order-flow demo** (`examples/orderflow/index.html`). Synthetic classified
  ticks stream into a `FootprintAggregator` and the forming bar updates in place, 
  the same path a live WebSocket trade feed takes. Speed, timeframe, display mode,
  imbalance ratio, stacked toggle, and stats toggle are all wired to `setOptions`,
  with a hover inspector fed by `hoverAt`.

### Fixed

- **Drawing a rectangle by dragging placed nothing and scrolled the chart.**
  Press-drag-release is how every charting UI lays down a two-point shape, but the
  chart only emitted a `click` when the pointer had *not* moved, so the gesture
  produced no anchors, while the pan path consumed it and scrolled the view out
  from under the user. Click-click still worked, which is why it went unnoticed.

  New `chart.setPlacementMode(active)`: while a host is placing something, a press
  no longer pans, and a press-drag-release is reported as two `click` events, the
  press point, then the release point tagged `viaDrag`. `DrawingController` arms
  and releases this with the active tool, so every two-point tool (rectangle,
  ellipse, trend line, channel, fib, position) gains drag-to-draw with no API
  change. Single-anchor tools ignore the release half, so dragging with `text`
  armed no longer drops a second box where you let go.

- **The price axis produced about half the tick labels it was asked for.**
  `niceTicks` rounded the span up to a nice number and *then* divided to get the
  step, rounding twice. A 10.5-point range became 20, giving a step of 5 and
  three labels where six were requested; on a footprint autoscaled to ~15 points
  around 65000 the axis was nearly bare.

  The step now comes from the raw span. Because `niceNum(x, true)` snaps to the
  *nearest* nice value it can undershoot and overshoot `maxTicks`, so the result
  is clamped up the 1, 2, 2.5, 5, 10 ladder until it fits. The 2.5 rung, 
  already promised by `niceNum`'s own docstring but missing from its
  implementation, is what keeps a 15-point range from collapsing from 8 labels
  straight to 3.

### Changed

- `Footprint.hoverAt(x, y, rc?)`: `rc` is now optional and defaults to the
  context of the last paint, so a crosshair handler can call `hoverAt(p.x, p.y)`
  instead of fabricating a `PrimitiveRenderContext` out of chart internals.

- Docs demos follow the site theme. `RunnableExample` wraps `createChart` to pass
  the resolved light/dark palette, since the library default is the light one and
  every example was rendering a white panel into a dark page.

## 1.0.8

Two new lazy tiers (**indicators** and **drawing tools**) plus the registries,
state, and pane chrome they need. Base engine ~32.7 KB Brotli, full package
~58 KB across all six tiers, 468 unit tests.

### Fixed

- **Lazy tiers could not register into the base bundle's registries.** Each tier
  is its own rollup bundle with nothing marked external, so a deep import like
  `../model/chart-type-registry` was *inlined*, giving the tier a second,
  private copy of the registry `Map`. The documented usage
  (`import 'openalgo-charts/transform'` then `chart.addSeries('point-figure')`)
  therefore threw `series type "point-figure" needs the transform tier` even
  though the tier was loaded. Only `src/all.ts`, built for the docs site, 
  happened to work, because it puts everything in one module instance.

  Tiers now import shared runtime state from the package entry
  (`import { registerChartType } from 'openalgo-charts'`), which is external for
  tier builds, so every bundle references one registry instead of inlining its
  own. Duplicated *pure* helpers across tiers were only ever a size cost, and
  removing the inlined registry shrank the transform tier from 4.6 KB to
  2.7 KB Brotli.

- **A `setPointerCapture` throw aborted the rest of `pointerdown`.** Chrome
  throws `NotFoundError` when the pointer id is not currently active, and the
  call was only optional-chained, which guards against the method being
  *absent*, not against it throwing. Anything armed after it silently never
  happened: the pane-divider grab, the price/time axis-drag arm, and the
  order-line drag arm. Both capture calls are now wrapped; capture is an
  optimisation, never fatal.
- **Pane hit-testing could be offset from what was drawn.** `_relayout` gave each
  pane a flex *ratio* (`flex: w 1 0`) while sizing its canvas from the chart's
  own `this._height`, so the browser distributed the container's real height and
  the model used a possibly-stale one. Any drift between the two shifted every
  hit-test away from the pixels: pane boundaries, legend buttons, and crosshair
  mapping all landed elsewhere. Panes now get the same pixel height the canvas
  is sized to, making layout == hit-test by construction.
- **Point & Figure no longer emits a phantom first column.** When the first move
  after the anchor bar was *down*, the direction was still `0`, so the reversal
  branch fired while the column's top and bottom boxes were equal, emitting a
  zero-height column that the renderer drew as a blank slot at the start of
  every down-opening chart. Direction is now established without emitting a
  column, and `flush()` returns nothing until a real column exists.
- **P&F columns are built from the bar range, not just the close.** The new
  `method` option defaults to `'hl'` (the standard construction): a bar's high
  extends an X column and its low extends an O column. A bar that swung through
  several boxes intrabar but closed flat used to produce no boxes at all. Pass
  `method: 'close'` for the previous close-only behaviour.
- **The P&F renderer walks integer box indices** instead of accumulating
  `level += boxSize`. Thirty steps of `0.05` land on `101.49999999999991`, which
  duplicated the top glyph of tall columns. Glyph rows outside the plot are now
  culled, and a per-column glyph cap keeps a pathological box size from hanging
  a frame.

### Added

- **`openalgo-charts/draw`, a new lazy tier (6.3 KB Brotli)** with 18 drawing
  tools and a headless `DrawingController`: trend line, ray, extended line,
  arrow, horizontal line/ray, vertical line, cross line, rectangle, ellipse,
  parallel channel, fib retracement/extension, long/short position, measure,
  text, and path. The controller runs placement (with a live preview), selection,
  whole-shape and per-anchor dragging, magnet snap to O/H/L/C, undo/redo, and
  serialisation, and ships **no UI**, so a host wires its own toolbar.
  `registerDrawingTool` makes a custom tool first-class, exactly like a chart
  type or an indicator.
- **Drawing anchors live in data space** (`{ time, price }`), never pixels. The
  time axis is gapless, so a pixel anchor would slide the moment a weekend
  collapsed; anchors map through `DataLayer.timeToIndexFloat`, which also
  resolves positions *between* bars and *past the last bar*, where projections
  live. Drawings round-trip through `ChartState.drawings` with no extra plumbing.
- **Full text styling** on the `text` tool: `fontFamily`, `fontWeight`,
  `fontStyle`, `background` + `backgroundColor` + `backgroundOpacity`,
  `border` + `borderColor`, `wrap` + `wrapWidth`, and `textAlign`. Text renders
  multiline, soft-wraps against live font metrics, and hit-tests its **measured**
  box rather than a character-count estimate.
- `PrimitiveHit.draggable`: arm a two-axis drag (drawing anchors and shapes),
  alongside the existing one-axis `cursor: 'ns-resize'` price-line path.
- **`drag` / `drag:end` events**, carrying `fromTime` / `fromPrice` (the grab
  origin) so a consumer's delta measures from the press rather than the first
  move. The `click` event now also fires on empty plot, with position and a null
  `id`: what a tool that *places* something needs.
- **Pane legends with inline controls.** `PaneLegend` draws the terminal-style
  row at a pane's top-left, swatch, name, parameters, and **one reading per
  plot in that plot's own colour** (a single number in a single colour cannot
  say which value belongs to which line of an MA ribbon or MACD), tracking the
  crosshair and falling back to the latest bar on leave, plus inline action
  buttons: show/hide, settings, move pane up/down, maximize, and delete.
  Controls stay hidden until the row is hovered, so a stack of legends reads as
  clean text; the row itself hit-tests (`::row`) to trigger that reveal, and the
  chart swallows those clicks so they never surface as phantom ids.
  Rows stack automatically per pane, a host can add its own (a symbol/OHLC
  header, a volume readout) with `chart.addPrimitive(new PaneLegend(...), pane)`
  and indicator rows flow beneath it; removing one closes the gap. Drawn on the canvas (like `BuySellButtons` and `DomLadder`) so it
  composites into screenshots and costs no DOM per pane, with icons as vector
  strokes rather than text glyphs, which render as emoji on some platforms.
  Every indicator gets one automatically; the first legend on a non-price pane
  also carries the pane-level controls, so extra rows stay uncluttered. The
  chart handles these presses itself, so a host gets them without wiring
  anything. `settings` has no built-in dialog (the engine ships no DOM) so it
  emits `indicatorSettings`; everything needed to *generate* a form is already
  on the descriptor's `inputs`.
- **Pane management:** `setPaneWeight`, `paneWeight`, `movePane`, `maximizePane`,
  `maximizedPane`, and `removePane`, plus **draggable pane dividers**: press
  within 4px of a boundary and drag to redistribute height between the two
  adjacent panes (cursor turns `row-resize`), conserving their combined weight
  so other panes are untouched and neither side can collapse. Removing a pane
  takes its series and indicators with it and re-indexes the panes below;
  pane 0 is pinned. Deleting the last indicator on a pane removes the pane too.
  New events: `paneResized`, `paneMoved`, `paneMaximized`, `paneRemoved`,
  `indicatorRemoved`, `indicatorSettings`.
- **An indicator registry, the sibling of the chart-type registry.** The
  chart-type registry answers *"how do I paint an array of bars"*; this one
  answers *"what do I compute, what does it plot, and what can a user tune"*.
  An `IndicatorDescriptor` is data, not code in the core, the chart never
  switches on an indicator id, and each `plot` names a registered **chart
  type**, so indicators ride the existing Family-A renderers and add no drawing
  code at all. `registerIndicator` / `getIndicator` / `registeredIndicators` /
  `indicatorDefaults` ship in the base bundle (~1.5 KB); the catalog does not.
- **`chart.addIndicator(id, settings?, { paneIndex? })`**, plus
  `chart.indicators()` and `chart.removeIndicator(instanceId)`. The returned
  `IndicatorApi` handle carries `settings()`, `setSettings(patch)`,
  `series(plotKey)`, `values()`, and `remove()`. The runtime creates one series
  per plot, places `'onchart'` indicators on the price pane and `'pane'`
  indicators on a new one, draws declared reference levels, applies a declared
  fixed range (RSI 0..100), recomputes on every source-data change, and tears
  everything down on `remove()` / `destroy()`. Indicator plots never claim the
  primary price series, so they can be added before any candles exist without
  hijacking the magnet crosshair and OHLC legend.
- **`openalgo-charts/indicators`, a new lazy tier (4.5 KB Brotli)** with 18
  Tier-1 built-ins: SMA, EMA, WMA, VWAP, Bollinger Bands, Supertrend, Parabolic
  SAR, Ichimoku Cloud, RSI, MACD, Stochastic, ADX/DMI, CCI, MFI, ATR, Volume,
  OBV, and A/D. Importing the tier registers all of them.
- **The Tier-2 contract** (`createTier2Indicator`) for indicators whose data is
  *not* derived from the chart's OHLCV, open interest, CVD, PCR, any external
  feed. It wraps a `fetch` / `subscribe` / `refetchOn` lifecycle into an ordinary
  descriptor, so the runtime, settings, panes, and removal all work identically;
  there is no second runtime. External points are projected onto the bar
  timeline by last-known-value, the most recent point *at or before* each bar,
  never interpolated and never forward-looking, and a failed fetch leaves the
  previous data on screen rather than blanking the pane.
- `IndicatorDescriptor.calcTail`: an optional incremental path so a live tick
  does not cost a full recompute. Return values for `[fromIndex, bars.length)`
  and the runtime splices them onto the previous result; return `null` to fall
  back to `calc`.
- **`chart.getState()` / `chart.restoreState(state)`**: a JSON-safe snapshot of
  the viewport, grid, crosshair mode, pane weights, per-pane price scales, and
  indicator instances, plus an opaque `drawings` slot the drawing tier owns and
  the base engine round-trips. The contract is that the chart serialises what
  the chart owns: series **data** is the app's, so `restoreState` never
  recreates series, it returns a `RestoreReport` listing the descriptors it saw
  so the app can rebuild them from its own feed and re-apply the saved styling.
  Restore is idempotent (indicators are replaced, not appended), a state from a
  newer `CHART_STATE_VERSION` is rejected rather than half-applied, and an
  indicator whose tier is not loaded is skipped rather than thrown.
- **`chart.subscribeDrag` now passes `time` alongside `price`**, so a two-axis
  drag (a trendline endpoint, a forward projection) has a usable time even where
  the gapless axis has no bar. Existing price-only callbacks are unaffected.
- **`chart.timeToCoordinate(time)` / `chart.coordinateToTime(x)`**, backed by
  new `DataLayer.indexToTimeFloat` / `timeToIndexFloat`. `indexToTime` only
  answers for indices that have a bar; anchoring to an arbitrary x needs a time
  *between* bars too, which the gapless axis (§5.3) makes the common case,
  since everything a weekend or session break collapsed lands there, and past
  the right edge, where projections live.
- `SeriesStyle.markersOnly`: draw a line series' markers with no connecting
  stroke (Parabolic SAR, scatter plots).
- `DataLayer.seriesBars(id)`: a series' bars with no per-call allocation, the
  read path for anything recomputing over full history.

- **P&F box-size modes.** `mode: 'fixed' | 'percent' | 'atr'`, `'percent'`
  sizes the box at `price × percent / 100` and `'atr'` at
  `ATR(atrPeriod) × atrMultiplier` (Wilder), both re-resolved each time a column
  opens, so the grid tracks price level and volatility.
- **Columns carry their own geometry.** `PointFigureColumn` extends `Bar` with
  `boxSize` and `boxes`, and the renderer reads the box size from the column.
  `style: { boxSize }` is no longer needed, which removes the footgun where the
  transform and the style could disagree and silently desync the glyph stack, 
  and is the only way variable-box modes can render correctly. `style.boxSize`
  remains as a fallback for hand-built column data; failing that the renderer
  infers the box from the shortest column in view.
- A column's `high` is now the **exclusive top edge** of its highest box, so
  `[low, high)` is exactly the span the glyphs occupy and
  `boxes === (high - low) / boxSize`. The stack previously drew one glyph short.

## 1.0.7

### Fixed
- A right-click on the chart no longer replays the previous left-click. Only the
  primary button starts a gesture in `_onPointerDown` (a right-click's
  `pointerdown` is ignored so the chart never pans with no button held), but the
  matching `pointerup` was unguarded, so a right-click's `pointerup` fell through
  to the click branch and re-hit-tested at the *stale* down-position from the last
  left-click, re-firing `subscribeClick`. With `BuySellButtons` (1.0.6) that meant
  the first right-click after buying/selling silently placed a second, duplicate
  order. `pointerup` now applies the same primary-button guard as `pointerdown`
  (touch/pen unaffected; the internal drag-recovery path is preserved).

## 1.0.6

### Added
- `BuySellButtons`, an inline trade panel drawn on the chart
  (a `SELL` button, a quantity chip, and a `BUY` button, docked to a corner and
  fixed while the chart pans/zooms). Clicks hit-test to `${id}:sell` /
  `${id}:buy` / `${id}:qty`, routed through `chart.subscribeClick`, so the app
  places the order. Prices update cheaply per tick via `setPrices(bid, ask)` /
  `setMark(price)`; `setQty()` and `setColors()` restyle at runtime. Configurable
  `position`, `margin`, labels, colors, and `showPrices`. Add it with
  `chart.addPrimitive(new BuySellButtons({ ... }))`. Base-tier export.
  (Base engine limit raised to 28 KB / 34.5 KB Brotli.)

## 1.0.5

### Fixed
- The browser's native right-click **"Save image as…"** now saves the visible
  chart instead of a blank image. The chart renders as stacked canvases and the
  browser captures only the topmost (transparent overlay) layer, so on
  `contextmenu` the clicked pane's base layer is composited beneath its overlay
  and overlay repaints are frozen while the menu is open (live ticks used to
  wipe the snapshot); rendering resumes on the next pointer/wheel/key input.
  Apps that present their own context menu (`preventDefault`) are unaffected.
  The native save captures the clicked pane only, `downloadScreenshot()`
  remains the full multi-pane export.

## 1.0.4

Trading-UI beautification: the order-placement surfaces (order / position /
bracket lines, DOM ladder) get a modern, theme-aware visual pass plus real
interaction feedback, and order lines go event-driven via OpenAlgo's
`subscribe_orders` WebSocket stream. 334 unit tests; base engine ~26.4 KB
Brotli (size limits raised to 27 / 33.5 KB for the visual-state rendering and
the order-update stream).

### Added
- Hover + dragging visual states for interactive price lines: hovering a
  draggable order line thickens it and brightens its pill, the cancel button
  fills solid on hover, and a dragged line gets a soft emphasis halo. The chart
  now applies primitive cursor hints (`ns-resize` over draggable lines,
  `pointer` over cancel/close/ladder rows) to the container and emits a new
  `hover` event (`chart.on('hover', ({ id }) => ...)`) on primitive enter/leave.
- Drag ghost: `PriceLine.setDragGhost(price | null)` draws a dimmed reference
  line at the pre-drag price while modifying an order. `chart.trading` wires it
  automatically; the live example wires it for the raw drag path.
- Broker-style segmented pill groups on order/position lines, 
  `[badge][qty][label][x]`: a solid colored badge (`BUY` / `SELL` / `TP` /
  `SL` / `LONG` / `SHORT`), boxed qty and info segments, and an integrated
  cancel `x` (still routes as `<id>::close`). New `PriceLineOptions.badge` and
  `qty` fields; text auto-contrasts against fills (`contrastText`), so every
  theme stays legible.
- `WorkingOrderLine` shows fill progress (`3/10`) once partially filled, dims
  pending (un-acked) orders until the broker confirms, and gains a close (x) segment
  (`order:<id>::close`) plus a compact price-only axis tag.
- `PositionMarker` renders the segmented group with live P&L (₹ and %) colored
  by sign, a close (x) segment (`position:<symbol>::close`), and highlights on hover.
- `BracketGroup` chips now include prices (`SL 2,850.00`, `TP 3,000.00`), the
  R:R chip is theme-aware, risk/reward zones derive from `theme.loss`/`profit`,
  and SL/TP lines thicken on hover/drag.
- `DomLadder` is fully theme-aware (heat colors from `theme.buy`/`sell`, qty
  text auto-contrasts with the background), gains a docked-edge separator and a
  hovered-row outline as a click-to-trade affordance.
- New shared render helpers (`src/render/pill.ts`): `parseColor`, `luminance`,
  `contrastText`, `withAlpha`, `shade`, `roundRectPath`, `drawPill`, `drawGrip`.

- Real-time order updates: `OpenAlgoWsFeed.subscribeOrders()` /
  `onOrderUpdate(cb)` speak OpenAlgo's account-level `subscribe_orders` stream
  (fills, partial fills, rejections, cancellations, live broker or analyze
  sandbox), with automatic replay on reconnect. New pure helpers
  `formatSubscribeOrders`, `formatUnsubscribeOrders`, `parseOrderUpdate`, and
  `mapOrderStatus`. The live example updates order lines from this stream and
  keeps a slow poll only for reconciliation.
- `chart.downloadScreenshot(filename?)`: public PNG export of the full
  composited chart (all panes + overlays); the screenshot shortcut now routes
  through it. The browser's native right-click "Save image as…" only captures
  the transparent overlay layer.

### Fixed
- Right-click no longer arms the pan state: a context-menu click used to leave
  the chart "sticky-dragging" (its `pointerup` is swallowed by the menu). Only
  the primary button starts a pan / line-drag, and a missed `pointerup` is now
  recovered on the next move.
- Live example: Renko / Range / Line Break / Kagi / P&F no longer render with
  time gaps between elements, the volume pane is re-bucketed onto the
  transformed element times instead of re-adding every raw timestamp to the
  shared axis (documented in Transforms).
- `OpenAlgoTradeFeed` errors now include OpenAlgo's own message (e.g. "MIS
  orders cannot be placed after square-off time…") instead of a bare HTTP
  status code.
- The crosshair is hidden while dragging an order line, the frozen crosshair
  at the grab point used to read as a phantom second line.
- The series last-price line no longer strikes through order/position pill
  groups (it now draws beneath trading primitives).
- WS `trigger pending` (with a space) order status now maps to `working`.

### Changed
- `PrimitiveRenderContext` gains optional `hoverId` / `dragId` fields (custom
  primitives can render their own hover/active states).
- Trade-fill bubble/count markers use auto-contrast text instead of fixed white.
- Trade-tier `WorkingOrderLine` / `PositionMarker` default to a half-width line
  (`extentFromRight` constructor option), matching the partial-width order
  lines of the parity API.

## 1.0.3

Cosmetic parity to close the last visual gaps for a migration off another engine.
318 unit tests; base engine ~24.8 KB Brotli.

### Added
- `SeriesStyle.priceLineVisible` and `lastValueVisible` toggle the dashed last-price
  line and the axis value tag per series; `SeriesStyle.title` carries a label for
  host-drawn legends. The last-price line/tag now follow the first right-scale price
  series (the main series) rather than whichever was added last.
- Crosshair styling via the theme: `crosshairStyle` (`solid` | `dashed` | `dotted`),
  `crosshairWidth`, `crosshairLabelBackground`, and `crosshairLabelVisible`.
- `timeFormatter` receives an optional `tickMarkType` hint
  (`year` | `month` | `day` | `time` | `timeWithSeconds`) so a host can render adaptive
  axis labels (year at year boundaries, month at month, day otherwise). New exported
  type `TickMarkType`.

## 1.0.2

Drop-in parity work so a host app can back every chart with this engine. Base
engine ~24.7 KB Brotli; 314 unit tests (40 files).

### Added
- Left / right / overlay price scales: `addSeries(type, { priceScaleId: 'right' | 'left' | '' })`.
  `'left'`/`'right'` draw independent, independently-autoscaled axes; `''` is a hidden
  overlay scale (volume-in-price-pane). `series.priceScale()` exposes the scale so
  `.setOptions({ marginTop, marginBottom })` can pin a volume histogram to the bottom.
- Mutable series handle: `series.applyOptions(partialStyle)`, `series.remove()`, and
  `SeriesStyle.visible` (hidden series are excluded from autoscale).
- Viewport preservation: `timeScale.setVisibleLogicalRange()` / `getVisibleLogicalRange()`
  and `chart.fitContent()` (no-arg), keep the user's zoom across a full-history reload.
- Per-series `priceFormat` (`price` / `volume` / `custom`), applied to the series' scale;
  `compactVolume` helper.
- Dashed / dotted line series via `SeriesStyle.lineStyle`.
- Runtime `chart.applyOptions()` / `chart.setTheme()` (theme, grid, formatters, crosshair
  mode) without recreating the chart; theme `axisFontSize`, `gridStyle`, transparent `background`.

### Fixed
- `RenderLoop` no longer stalls after the first frame under a synchronous scheduler.

## 1.0.1

Full package ~38 KB Brotli (all tiers), base engine ~24 KB, zero runtime
dependencies, Apache-2.0.

### Added
- Unified event bus: `chart.on` / `off` / `once` (`crosshair:move`, `click`,
  `pan`, `zoom`, `resize`, `lazy-load`, `ready`), with `trading:*` mirrored through it.
- Data-driven trading visualization (`chart.trading`): position/order pills,
  TP/SL brackets, and fill markers (chevron / bubble / count).
- Custom formatting: `ChartOptions.priceFormatter` and `timeFormatter` (with
  runtime setters); per-pane `priceScale` options; the time axis is no longer IST-only.
- Flexible series input: `setData` accepts `Bar | LinePoint | Whitespace`
  (normalized via `toBar`); `series.getData()` reads the current bars.
- WebSocket auto-reconnect (backoff + re-auth + resubscribe); `OpenAlgoLiveDataFeed`
  bare `D`/`W` intervals, day-delta volume, and symbol+exchange tick filtering;
  `FakeDataFeed` streams deterministic bars through an injectable scheduler.
- Docs site: an interactive example gallery (chart type, themes, tooltips, event
  markers, live streaming, "Get this chart" code toggle) plus framework-integration,
  mobile, data-loading, events, types, constants, and glossary pages; redesigned
  yfinance and live OpenAlgo example apps.

### Fixed
- Multi-series `DataLayer.update`: a series-local append that is not the global
  newest no longer corrupts the shared time-axis order.
- Package now ships `NOTICE` (Apache-2.0); the accessible summary refreshes on
  live updates; `visibleBars` uses binary search for large datasets.
- Docs accuracy: real `SeriesApi`, `subscribeBars`, indicator return types, and
  interval/size/test-count figures.

### Quality
- 297 unit tests (39 files) + a Playwright real-browser smoke suite. GitHub
  Actions CI runs typecheck, unit, build, size budgets, a docs-site build, a
  `NOTICE` pack check, and the E2E smoke on every push/PR. Warning-free TypeDoc.

## 1.0.0

First public release. Full package ~29 KB Brotli (all tiers), zero runtime
dependencies, Apache-2.0.

### Added since 0.1.0
- Indicators: RSI, ATR, Supertrend (Wilder semantics, matching `openalgo.ta`),
  alongside EMA.
- Interaction: vertical price pan (drag the plot up/down), `chart.resetScale()`
  + double-click/Fit, `priceToCoordinate` / `coordinateToPrice` for DOM overlays,
  and `subscribeCrosshairMove` for OHLC legends/tooltips.
- Touch: pinch-to-zoom and two-finger pan (`touch-action: none`).
- Accessibility: focusable container with `role`/`aria-label`, a polite live
  summary, and keyboard navigation (arrows pan, +/- zoom, Home/0 reset).
- `chart.takeScreenshot()` (composites all panes/layers) and runtime grid toggles.
- Footprint primitive upgraded: volume-graded bid x ask cells, diagonal-imbalance
  boxes, POC marker, per-bar delta/volume footer.
- Live feed: composed REST + WebSocket + candle-builder data feed; WS adapter
  speaks the documented OpenAlgo protocol (authenticate -> numeric-mode subscribe ->
  `market_data`), with connection/control callbacks.
- Examples: yfinance, order-flow, market-profile (TPO), and a full LIVE OpenAlgo
  demo (history + WebSocket + chart trading) - validated against a live instance.

### Fixed
- `OpenAlgoDataFeed`/`OpenAlgoTradeFeed`: bind the global `fetch` (browser
  "Illegal invocation").
- WebSocket subscribe schema corrected to the documented per-symbol numeric-mode
  protocol.
- `modifyorder` sends the required `disclosed_quantity`.
- `mapOrder`: `trigger_price: 0` -> `undefined` so LIMIT order lines render at the
  price, not 0.

### Quality
- 223 unit tests + a Playwright real-browser smoke suite; GitHub Actions CI runs
  typecheck, unit, build, size budgets, and the E2E smoke on every push/PR.

## 0.1.0 (initial development build)

First end-to-end build of the engine. Dependency-free, ~22 KB Brotli for the
full package (all tiers).

### Engine (base tier)
- HiDPI canvas layout (base + top canvas per pane), render loop, per-pane
  invalidation mask, resize handling.
- Shared DataLayer (merge-by-time -> logical indices) keeping all panes aligned;
  gapless time axis (weekends/holidays/session breaks collapse).
- Time scale (index<->x, pan, cursor-anchored zoom, kinetic flick, fit-content)
  and price scale (linear, autoscale, tick-size formatting/snap).
- Internal time = UTC seconds; IST/epoch conversion at the feed edge.
- Live candle builder (session-aligned bucketing, ltq-sum vs cumulative-day
  volume, late-tick policy, history->live seam) + last-price line.
- Chart-type registry with all standard styles: bars, candles, hollow,
  volume-candle, line, line+markers, step, area, HLC-area, baseline, columns,
  histogram.
- Primitive/plugin API (views, z-order, hit-test, autoscale, lifecycle) powering
  markers (buy/sell signals + shapes, four sizes), event badges
  (earnings/dividend/split), and price lines.
- EMA indicator; OpenAlgo REST data adapter; deterministic fake feed.
- Optional OHLC-preserving conflation for very large datasets.

### Transform tier
- Heikin Ashi, Renko, Range bars, Line Break (render as candles); Point &amp;
  Figure and Kagi (custom renderers). Incremental for live updates.

### Trade tier
- Read: order/position/bracket primitives + live P&amp;L; book reconciliation with
  reconnect-stale handling.
- Write: order state machine, tick/price-band/freeze validation, arm/confirm
  gate, idempotency, rate-limited drag-modify, OCO, analyzer mode.
- Depth-of-market ladder: depth-agnostic (5 to 200 levels), virtualized,
  price-bucket aggregation, size heatmap, click-to-place, graceful degradation.

### Profile tier
- Volume Profile (POC + value area), Market Profile / TPO (+ initial balance),
  Footprint (bid/ask delta + imbalance), order flow (cumulative delta + stacked
  imbalance). Footprint/order flow require classified trade data.

### Tooling
- TypeScript, Rollup multi-entry build, `size-limit` (Brotli) budgets per tier,
  154 unit tests (incl. a recording-canvas harness for renderers).
