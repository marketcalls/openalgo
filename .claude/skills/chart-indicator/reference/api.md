# The API handed to your module

Your default export receives one object carrying the whole of `openalgo-charts`
(core) plus its `indicators` tier, merged. Destructure what you need:

```js
export default function ({ registerIndicator, sourceValues, sma, nulls }) { ... }
```

There is nothing to import. A runtime module cannot resolve the bare
`openalgo-charts` specifier, which is why the API arrives as an argument.

## Registration

| | |
| --- | --- |
| `registerIndicator(descriptor)` | the one call that matters |
| `createTier2Indicator(d)` | wrap an external-data descriptor as a normal one |
| `registeredIndicators()` | every registered descriptor |
| `getIndicator(id)`, `hasIndicator(id)` | look one up |
| `indicatorDefaults(descriptor)` | its declared defaults as a settings object |
| `indicatorStyleInputs(descriptor)` | the generated style fields |
| `registeredChartTypes()` | valid `plot.type` values |

## Reading bars

| | |
| --- | --- |
| `sourceValues(bars, source)` | whole bar array as one price column |
| `sourceValue(bar, source)` | one bar's value |
| `INDICATOR_SOURCES` | the canonical source list for a select |

Sources: `open`, `high`, `low`, `close`, `hl2`, `hlc3`, `ohlc4`, `volume`.

From 2.4.5, `Bar.oi` is an optional open-interest reading. It is not a source
selector token. Read it directly and keep missing readings distinct from zero:

```js
const oi = bars.map(bar => Number.isFinite(bar.oi) ? bar.oi : null)
const change = oi.map((value, index) => {
  const previous = oi[index - 1]
  return value === null || previous == null ? null : value - previous
})
```

`securitySeries` also returns a nullable `oi` column. OI is a level, so a fold
keeps the latest defined reading in its bucket instead of summing it. Missing
live observations and price-generated or expression bars can have no OI. The
host's `hasOpenInterest` metadata describes support independently of these gaps.
Reuse `getIndicator('open-interest')`, `getIndicator('open-interest-change')` or
`getIndicator('open-interest-buildup')` when their existing calculation fits.

## Moving averages and statistics

All take a **numeric array** and return an array the same length, with `NaN`
during warmup.

| | |
| --- | --- |
| `sma(values, period)` | simple |
| `wma(values, period)` | linearly weighted |
| `rma(values, period)` | Wilder smoothing, the basis of RSI/ATR/ADX |
| `ema(values, period)` | seeds from `values[0]`, emits from index 0 |
| `stdev(values, period)` | rolling population standard deviation |
| `highest(values, period)`, `lowest(values, period)` | rolling extremes |
| `connorsStreak(values)` | consecutive up/down streak length per bar |
| `nulls(values)` | NaN to null, for a plot column |
| `pivotHigh`, `pivotLow` | pivot detection, the basis of structure studies |
| `change`, `roc`, `dev`, `linreg`, `swma`, `stoch`, `cci` | further parity helpers, all exported since 1.8.1 |
| `percentRank`, `percentileNearestRank`, `correlation` | rank and correlation |
| `alma`, `vwma`, `rollingSum`, `cumulative` | further averages and running totals |
| `highestBars`, `lowestBars` | bars since the rolling extreme |

`ema` seeds from `values[0]` and emits from index 0, matching `openalgo.ta`.
The common reference implementation seeds from the SMA of the first `period`
values and is NaN before that, so the two disagree for roughly the first
`period` bars. **`smaSeededEma` is exported since 1.8.1**, so reproducing a
reference plot no longer needs a hand-rolled seed.

`sma` is NaN-safe: it counts non-finite inputs rather than poisoning its running
sum, so chaining it onto another indicator's warmup gap works.

## OHLC-based studies

**These take three separate arrays, not a bars array.** Getting this wrong is the
easiest mistake in the whole API.

| | |
| --- | --- |
| `trueRange(high, low, close)` | `tr[0] = high[0] - low[0]`, then the 3-way max |
| `atr(high, low, close, period?)` | Wilder ATR, first value at `period - 1` |
| `rsi(values, period?)` | takes a **single** numeric array |
| `supertrend(bars, period?, multiplier?)` | takes **bars**, returns `{ value, direction }[]` |

```js
const range = atr(bars.map(b => b.high), bars.map(b => b.low), bars.map(b => b.close), 14)
```

`supertrend`'s `direction` is `-1` for uptrend and `+1` for downtrend.

## Time and calendar

Bar times are UTC seconds. A session is exchange wall clock. They only meet
through a zone, so never use the browser's local time.

| | |
| --- | --- |
| `DEFAULT_TIMEZONE` | `'Asia/Kolkata'` |
| `isValidTimezone(zone)` | guard a user-supplied zone |
| `utcSecondsToZonedParts(t, zone?)` | `{ year, month, day, hour, minute, second, weekday }` |
| `zonedDayIndex(t, zone?)` | days since epoch in that zone, for per-day buckets |
| `zonedWeekIndex(t, zone?)` | Monday-start week bucket |
| `isNewZonedDay(prev, t, zone?)` | boundary test; also Week/Month/Quarter/Year |
| `isNewZonedPeriod(prev, t, period, zone?)` | the same carried as data |
| `startOfZonedDay / Week / Month` | period start |
| `zoneOffsetSeconds(t, zone?)` | DST-correct offset |
| `sessionStartFlags(times, zone?)` | per-bar first-bar-of-session flags |
| `sessionStartIndices(times, zone?)` | the same as indices |
| `calendarPeriodFlags(times, isNew)` | first bar of each period, session-aware |
| `formatIstTime`, `formatZonedTime`, `formatZonedDate` | labels |

Prefer `calendarPeriodFlags` / `sessionStartFlags` over comparing bar to bar: a
session that straddles a calendar boundary is not cut in half by them.

## Numbers and drawing

| | |
| --- | --- |
| `clamp(v, min, max)`, `lerp(a, b, t)` | |
| `roundToTick(price, tick)` | |
| `precisionForStep(step)` | decimals for a tick size |
| `compactVolume(n)` | `1.2M` style |
| `niceTicks(...)` | axis-style tick selection |
| `INDICATOR_LINE_STYLES`, `INDICATOR_PLOT_STYLES` | option lists for selects |

## Constants

| | |
| --- | --- |
| `IST_OFFSET_SECONDS` | 19800 |
| `DEFAULT_THEME`, `darkTheme`, `lightTheme` | theme palettes |
| `VERSION` | library version |

## The instrument (1.8.2)

| | |
| --- | --- |
| `ctx.tickSize` | the pane price scale's `minMove`, or `undefined` if the host never set one |
| `roundToTick(price, tick)` | snap a price to a tick, exported from the core |
| `precisionForStep(tick)` | decimals implied by a tick |

There is no point value: the chart knows how prices are quoted, not what a point
is worth. Take it as an input, default 1.

## Sessions, timeframes and colours (1.8.1)

| | |
| --- | --- |
| `parseSessionSpec(spec)` | `'0915-1015'` or `'0930-1600:23456'` to `{ start, end, days? }`, null if unparseable |
| `inSessionAt(utcSeconds, spec, zone?)` | membership test, half-open end, handles a midnight wrap |
| `sessionFlags(times, spec, zone?)` | per-bar boolean array |
| `intervalParts(code)` | `{ multiplier, unit }` |
| `isIntradayInterval`, `isDailyInterval`, `isSecondsInterval`, `isTickInterval` | interval predicates |
| `withAlpha(color, alpha)` | alpha applied to `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()`, `rgba()` |
| `fromGradient(value, min, max, low, high)` | interpolate a colour by where a value sits in a range |

These remove the two things every ported study used to hand-roll: a session
parser and a colour ramp.

## What arrived after 1.8.2

These additions preserve existing descriptors. Optional fields and host APIs
are identified separately so a custom module can use the right surface.

| | |
| --- | --- |
| **1.8.3** | Eleven studies, taking the registry from 91 to 102: `t3`, `hull-suite`, `consolidation-breakout`, `smma`, `net-volume`, `linreg-slope`, `ma-channel`, `chaikin-volatility`, `standard-deviation`, `standard-error`, `standard-error-bands`. Each is exported as a descriptor constant and reusable through `getIndicator`. The same release corrected nine built-ins and moved ten defaults, so a study measured against a built-in before 1.8.3 needs its expectations re-derived rather than assumed. |
| **1.8.4** | `calc` is flushed once per animation frame rather than per tick, so it must be a pure function of `(bars, settings)`. `calcTail` now only pays for deep history, not for a fast feed. |
| **1.8.9** | Precision follows the pane an indicator is handed. An overlay plot prints at the instrument's tick, a study pane at two decimals or finer. Nothing to declare in the descriptor. |
| **2.0.0** | The render backend port (`createRenderBackend`, `registerRenderBackend`, `Canvas2dBackend`, `resolveRenderBackend`, `backendDegradation`) plus SVG export and watermark helpers. All chart infrastructure: an indicator never touches a backend, and the WebGL2 path renders the same plots. |
| **2.1.2** | A Tier-2 study's history requests and live callbacks are isolated by data key, so a response for a setting you have left cannot land on the current one. |
| **2.1.5** | Drawing previews survive past the newest candle. No indicator surface changed. |
| **2.6.0** | Seven studies take the registry from 105 to 112: `zigzag`, `high-low-52-week`, `zlema`, `vidya`, `elder-ray`, `schaff-trend-cycle`, `volatility-squeeze`, each exported as a descriptor constant with its own `calcTail`, plus the groups `EXPONENTIAL_INDICATORS` and `SWING_INDICATORS`. `zlema` and `vidya` plot under their own names, not `ma`; `zigzag` repaints its last leg on a tick; `high-low-52-week` draws nothing until the loaded history spans 364 days. Twenty-nine built-ins gain `{ key: 'timeframe', type: 'interval', default: '' }`: empty computes exactly as before, set it folds the chart's bars to that interval and shows each bucket's value once the bucket has closed, and a code it cannot fold throws `IndicatorInputError`. **`withTimeframe(descriptor)`** adds the same input to a descriptor of your own, and throws for one with `attach` or a `timeframe` key already; `/trading`'s loader re-spreads every descriptor, which drops the wrapper's non-enumerable tail, so such a study recomputes in full each frame. Every built-in rounds a fractional window length to the nearest whole bar, at least 1; the exported helpers are unchanged. `percentileNearestRank`, `valueWhen` and `alma` return NaN for out-of-range arguments, and the statistics family throws `TypeError` for options that are not an object. An alert judges each bar a pass appended, in order, its `when` and `message` handed the bars and values through that bar. A `calcTail` that leaves out a column of the result falls back to a full `calc` instead of blanking it. A plot's Opacity now fades `colorBy` and `colorParts` plots. A restore brings back a study whose first pass throws `IndicatorInputError` in its error status. Host APIs, not descriptor surface: in-chart transforms, `barSource` and `IndicatorCalcContext.transformed` (`/trading` transforms its own bars, so none of them reaches a study there), `ChartEventMap` and the deprecation of `Chart.emit` (the attach context's `emit` is unchanged), and feed symbol search. |
| **2.5.10** | No descriptor surface changed. Text markers on neighbouring bars are laid out in lanes, each pushed past an earlier label it would cover by at most five of its own heights, so a label can sit off its bar. `roc` and `williams-vix-fix` carry new display names; their ids are unchanged. |
| **2.5.9** | No descriptor surface changed. A study pane's value tag no longer carries the bar countdown and is painted over a level tag where they meet, and a line plot draws the segment that crosses each edge of the view. |
| **2.5.8** | No descriptor field added. Sixteen built-ins carry a `calcTail` (`sma`, `ema`, `wma`, `rsi`, `atr`, `adx`, `macd`, `bollinger`, `vwap`, `supertrend`, `stochastic`, `obv`, `cci`, `keltner-channel`, `donchian`, `parabolic-sar`) as a non-enumerable property, so `{ ...getIndicator('ema') }` copies the calc without the tail; copy it by name only when your `calc` returns the built-in's result unchanged. The level of detail merges sticks only when drawing below one CSS px per bar; `calc` still receives every bar. A study's plots now take `update()` on a tick, which only a custom host notices. |
| **2.5.7** | An internal reorganisation. Nothing a descriptor declares or receives changed. |
| **2.5.6** | `visibleWhen` and `activeWhen` (an `IndicatorInputCondition` over the other settings) and `inline` on any input: presentation only, `calc` still receives every setting, and `/trading`'s dialog does not read them, so every input shows there. A `price` input pairs with a `timestamp` input through `timeKey`, `anchor: true` adding a drag handle; `/trading` refuses both types. `background` may return a list of `IndicatorBackgroundSpec` (`{ colors, overlay?, plot? }`) to shade the price pane or a plot's pane; the validator here checks only the plain one-colour-per-bar form and refuses the list. A level's `dashed` shorthand stays. Host APIs: study policies, the series stack, data variants and `ChartHistory`. |
| **2.5.5** | No descriptor field added. Calculation corrections for missing or non-finite inputs: ATR and the studies built on it, Supertrend, VWAP, TWAP, OBV, Accumulation/Distribution, Parabolic SAR, CCI, Fisher Transform, RVI, Mass Index, NVI and PVI resume after a gap instead of going blank, and the exported `atr` and `supertrend` follow the same rules. Complete data reads as before, except the last digits of TEMA, Stochastic, TSI and the SMI Ergodic pair, and Trend Strength Index and `correlation` where the old single pass cancelled. Moving the price pane is a host opt-in (`movablePrimaryPane`) that `/trading` does not take. |
| **2.5.4** | The widest change in the range, every field optional. Draws and markers name an `IndicatorOutputTarget`: `overlay: true` sends a shape to the price pane or anchors a marker to the candles from a study in its own pane, and `plot: key` uses that plot's pane and scale. Labels, box captions and marker text take `fontSize`, `fontFamily`, `bold`, `italic` and `textAlign`, marker text also `textColor`, and labels and boxes `verticalAlign`. A polyline takes `curve: 'smooth'`. Table cells take `tooltip`, `italic`, `fontFamily`, `verticalAlign`, `colSpan` and `rowSpan`, and a `tables()` hook returns several named grids (`{ id, rows, options?, overlay? }`), taking precedence over `table`. A fill takes `gradient`, `gradientBy` and a per-bar `colorBy`, and its `between` may name a column no plot draws. An alert takes `frequency` (`everyUpdate`, `oncePerBar`, `onBarClose`, `once`); omitted keeps the new-bar-only rule. The calc context gains `execution` and `resolveSource`. The library adds the input types `symbol`, `session`, `multiline`, `price` and `timestamp`, which `/trading`'s loader and the validator refuse, and `allowStudyOutputs` on a `source` input, which `/trading`'s dialog never offers. New helpers: `crossesAbove`, `crossesBelow`, `crosses`, `rising` and `falling`, where a missing value reads false; `rollingMedian`, `rollingMode`, `rollingVariance`, `rollingRange`, `percentileLinear`, `rankCorrelation`, `centerOfGravity`, `runningMin` and `runningMax`, which throw `RangeError` for a period that is not a positive whole number where `sma` returns NaN; and `securityExpression`, which runs a calculation on folded bars. `requestSnapshot` and `createRequestedIndicator` need a host that serves snapshots, which `/trading` does not, so there such a study reports itself unsupported. HMA at odd lengths and the first ADX readings follow corrected definitions. |
| **2.5.3** | No descriptor surface changed. A study can move to another pane keeping its instance id, without its `attach` running again, so read `ctx.paneIndex()` when you need it rather than keeping it. |
| **2.5.2** | No descriptor surface changed: Anchored VWAP and Fixed Range Volume Profile drawing tools, drawing and appearance links, and timeline event groups are host features. |
| **2.5.1** | No descriptor surface changed, and no export added or removed: the index above counts the same 387 names it counted on 2.5.0. `AlertControllerOptions.spentLines` accepts `'hide'`, and a triggered or expired alert then keeps its record, its scope, its checkpoints and its saved runtime while its line is not drawn. Opt-in per controller, not serialised into an alert document and no change to the saved-state format; the default stays `'show'`, including in the packaged widget. An alert anchored to a drawing leaves that drawing alone when its own line goes. Host API, not descriptor surface: an indicator declares nothing about it. |
| **2.5.0** | No descriptor surface changed, and no export added or removed: the index above counts the same 387 names it counted on 2.4.8. `ChartTableOptions.cellWidth` accepts `'auto'`, which measures each column from its widest cell including padding, bold text and per-cell font overrides; an empty automatic column keeps a 28 px minimum and percentage widths preserve their measured proportions. Automatic font sizing measures against an 11 px baseline, and every cell now clips its text, so a long reading can no longer cover the column beside it. A table an indicator draws is the surface this reaches. Host APIs, not descriptor surface: `AlertController.hovered()` and `Chart.snapPrice(paneIndex, price)`. |
| **2.4.8** | No descriptor surface changed, and no export added or removed: the index above counts the same 387 names it counted on 2.4.7. Press and hold the plot to pan, on both axes by default, and mouse and pen panning stops on release while touch keeps its flick; a chart with a saved horizontal-only preference keeps it until it is changed in the chart navigation settings. The one thing that touches a descriptor indirectly: a clickable legend action keeps its pointer cursor and stays usable across a repaint, which is what a `hasSource` braces button and a gear rely on. |
| **2.4.7** | No descriptor surface changed. An alert's line is draggable, and a study threshold drags on its own plot's scale, including an independent or left scale; the preview does not enlarge autoscale. Additive `drag:start` and `drag:cancel` events, and `PrimitiveHit.cancelOnEscape` as an opt-in for raw custom primitives, so an existing drag consumer is unaffected. |
| **2.4.6** | Three optional descriptor fields. `hasSource` adds a source button to the legend row and emits `indicatorSource`; the host owns the code. `markerAnchor: 'price'` measures `aboveBar` and `belowBar` against the instrument's candles rather than the first plot, so a signal sits above the high and below the low; the default `'plot'` is unchanged and the field is ignored off pane 0. A legend reading is skipped for a plot drawn in a fully transparent colour, so an invisible anchor column no longer reserves the width of a price. Chart-wide `legendIconSize` sizes the legend's action buttons. |
| **2.1.6** | Tier-2 studies receive the host's symbol, exchange and interval through `dataContext`, follow source-range changes, cancel obsolete fetches and expose loading, ready, empty, unsupported and error states with retry. `supports(ctx)` lets a provider decline a context explicitly. `DataLoadingController`, `HistoryRequestPool`, `sharedHistoryRequests` and `BAR_CACHE_VERSION` also joined the core export, but they belong to chart hosts rather than indicator descriptors. |
| **2.1.7** | Hidden indicator state survives layout restoration and plot-style edits, and reference levels follow instance visibility. The new `ChartObjects` export lets hosts inventory indicators and display their Tier-2 status, but it is host infrastructure and does not change the descriptor contract. The built-in registry remains at 102 ids. |
| **2.1.8** | Normalized wheel and trackpad navigation, price-axis wheel scaling and eased automatic price ranges are engine behavior; manual scales and an indicator's fixed `range()` remain authoritative. Responsive mobile controls and their reduced-motion fallback belong to the packaged widget. OpenAlgo `/trading` uses a bare `Chart`, so it inherits the gestures while retaining its own controls. No descriptor or built-in-registry change. |
| **2.1.9** | Chart hosts gain default built-in branding and an optional text watermark through `ChartOptions.branding` and `ChartOptions.watermark`. Runtime updates use `setBranding` and `setWatermarkOptions`; `brandingOptions` and `watermarkOptions` return snapshots; `branding:changed` carries `BrandingChangedEvent`; and blank watermark text follows `setDataContext`. The public option types are `LogoWatermarkOptions` and `ChartWatermarkOptions`. This is host infrastructure and does not change the descriptor contract or built-in registry. |
| **2.2.0** | The draw tier grows to 85 tools and adds `ADVANCED_LINE_TOOLS`, `ADVANCED_GEOMETRY_TOOLS` and `PATTERN_DRAWING_TOOLS`. These are host drawing descriptors, not exports on the custom indicator API object. Indicator descriptors and the 102 built-ins are unchanged; saved drawing documents remain version 2. |
| **2.2.1** | Two optional descriptor fields, both additive. `IndicatorInput.tooltip` is help text for a row, which the settings dialog draws as a focusable `?` beside the label; the core ignores it. `IndicatorPlot.priceFormat` takes the exported `PriceFormat` union (`price` / `volume` / `percent` / `custom`) and sets the axis and crosshair formatting of the scale that plot maps to. `percent` suffixes the value and does NOT scale it, so a 0..1 study reads `0.62%`; like `style.precision` it belongs to a plot that owns its pane. `historical-volatility` and `bollinger-bandwidth` are the first built-ins to use either. The registry stays at 102 ids and no existing descriptor is affected. |
| **2.4.0** | The constructs a ported study most often could not express. **`securitySeries(bars, interval, opts)`** folds the chart's own bars to a higher timeframe, one value per bar, with three readings: the default reads the bucket as it stood at that bar and never uses a later one, `offset: k` reads the last completed bucket held constant, and `lookahead: true` reads final values and repaints. `session: '0915-1530'` anchors sub-day buckets to the session open. **`IndicatorPlot.offset`** paints a column that many bars to the right, the tail landing in the right margin; a fill follows its first plot's offset and the legend reads what is drawn under the cursor. **A thrown `calc` is caught**, published as `{ state: 'error' }` on the instance data status and the `indicator:data-status` event, and cleared by the next good pass; the constructor's first pass still throws out of `addIndicator`. **`IndicatorInputError`** names a condition the user can fix. **`alerts[].message`** may be a function of the firing bar's context. Markers gain the shapes `cross` and `xcross` and the positions `paneTop` and `paneBottom`, which pin to the plot edge and need no bar or price. **`IndicatorFillSpec.overlay`** draws a band on the price pane. **`IndicatorPlot.colorParts`** returns `{ body, wick, border }`, carried as `Bar.wickColor` / `Bar.borderColor`. `draws()` labels and boxes take **`tooltip`** and **`id`**, which make them hit-testable. Two input types, **`interval`** and **`time`**. **`ChartTableOptions.fontSize: 'auto'`** fits each cell. And **`ctx.requestBars`** asks the host for another instrument's bars, served in `/trading` by the terminal's own cached feed. Every field is optional; the registry stays at 102 ids. |
| **2.4.5** | Three OI studies bring the registry to 105 ids: `open-interest`, `open-interest-change`, `open-interest-buildup`. Optional `Bar.oi` and `SecuritySeries.oi` preserve zero and missing-data gaps; folds retain the latest defined level instead of summing it. Host `AlertController` alerts retain a study instance id and plot key, with separate persistence and delivery from descriptor `alerts`. `Instrument` supplies immutable source/calendar/format metadata; `ReplayGroup` coordinates availability by UTC time; `isReplaying` reports active and paused replay; `exportChartDataCsv` exports the installed chart prefix and configured study columns. Trading capability helpers and `TradingCapabilityError` share identity across base/trade entries and leave broker authority with the host. These are host infrastructure, not indicator lifecycle hooks. Workspace/template validation, storage and `planIndicatorTemplate` belong to the separate `openalgo-charts/workspace` entry; widget translation and controls belong to the widget entry. Neither extra tier is added to the API object handed to custom modules. |

## Complete export index

Version 2.1.9 adds the type-only declarations and `Chart` methods
listed above. They are absent from the generated index because a custom
indicator receives runtime named exports, while TypeScript types and prototype
methods are not properties of that API object.

<!-- BEGIN GENERATED EXPORT INDEX -->

All 433 names on the API object, so nothing is a surprise. Generated from
the installed openalgo-charts@2.6.0 build by `generate-api-index.mjs`; do not
edit this section by hand.

**Registration and introspection** (14)

`registerIndicator`, `createTier2Indicator`, `registeredIndicators`, `getIndicator`, `hasIndicator`, `indicatorDefaults`, `indicatorStyleInputs`, `plotStyleKeys`, `registeredChartTypes`, `getChartType`, `registerChartType`, `registerBuiltinIndicators`, `INDICATORS_TIER`, `IndicatorInputError`

**Reading bars** (10)

`sourceValues`, `sourceValue`, `INDICATOR_SOURCES`, `toBar`, `mergeBars`, `conflateBars`, `conflateItems`, `isWhitespace`, `generateBars`, `FakeDataFeed`

**Moving averages and statistics** (28)

`sma`, `wma`, `rma`, `ema`, `smaSeededEma`, `stdev`, `dev`, `highest`, `lowest`, `highestBars`, `lowestBars`, `rollingSum`, `cumulative`, `linreg`, `swma`, `alma`, `vwma`, `percentRank`, `percentileNearestRank`, `correlation`, `nulls`, `connorsStreak`, `change`, `roc`, `stoch`, `cci`, `pivotHigh`, `pivotLow`

**OHLC studies** (8)

`trueRange`, `atr`, `rsi`, `supertrend`, `emaSeries`, `rsiSeries`, `supertrendSeries`, `securitySeries`

**Sessions, time and timeframes** (48)

`DEFAULT_TIMEZONE`, `IST_OFFSET_SECONDS`, `isValidTimezone`, `utcSecondsToZonedParts`, `utcSecondsToIstParts`, `zonedDayIndex`, `zonedWeekIndex`, `zoneOffsetSeconds`, `isNewZonedDay`, `isNewZonedWeek`, `isNewZonedMonth`, `isNewZonedQuarter`, `isNewZonedYear`, `isNewZonedPeriod`, `isNewIstDay`, `startOfZonedDay`, `startOfZonedWeek`, `startOfZonedMonth`, `sessionStartFlags`, `sessionStartIndices`, `calendarPeriodFlags`, `parseSessionSpec`, `inSessionAt`, `sessionFlags`, `epochMsToUtcSeconds`, `istStringToUtcSeconds`, `zonedStringToUtcSeconds`, `zonedWallClockToUtcSeconds`, `utcSecondsToIstDateString`, `utcSecondsToZonedDateString`, `rowTimeToUtcSeconds`, `barCloseSec`, `bucketStartOf`, `nextBucketStart`, `isTimeBucketed`, `intervalToSeconds`, `intervalParts`, `isIntradayInterval`, `isDailyInterval`, `isSecondsInterval`, `isTickInterval`, `isKnownInterval`, `resolveInterval`, `tryResolveInterval`, `registeredIntervals`, `registerInterval`, `unregisterInterval`, `UnknownIntervalError`

**Formatting** (10)

`formatIstTime`, `formatIstTimeSeconds`, `formatIstDate`, `formatIstCrosshairLabel`, `formatZonedTime`, `formatZonedTimeSeconds`, `formatZonedDate`, `formatZonedCrosshairLabel`, `compactVolume`, `precisionForStep`

**Colours, numbers and geometry** (20)

`withAlpha`, `fromGradient`, `verticalGradient`, `clamp`, `lerp`, `roundToTick`, `niceTicks`, `autoscaleRange`, `optimalBarWidth`, `snapToDevicePixel`, `bitmapSize`, `dashPattern`, `markerSizePx`, `effectiveMarkerPx`, `drawShape`, `drawLabel`, `bestHit`, `tableOrigin`, `watermarkRect`, `resolvePlotMargins`

**Style and option lists** (21)

`INDICATOR_LINE_STYLES`, `INDICATOR_PLOT_STYLES`, `PRICE_SCALE_MODES`, `PRICE_LEVEL_KINDS`, `DEFAULT_THEME`, `darkTheme`, `lightTheme`, `ALT_PRESET`, `VERSION`, `version`, `CHART_STATE_VERSION`, `DEFAULT_CANDLE_STYLE`, `DEFAULT_HISTOGRAM_STYLE`, `DEFAULT_TRADING_COLORS`, `resolveCrosshairStyle`, `resolveGridStyle`, `resolveScaleStyle`, `seriesStyleForLastPriceLevel`, `lastPriceLevelFromSeriesStyle`, `IndicatorBackground`, `IndicatorFill`

**Built-in indicator descriptors** (112)

Each is the descriptor object itself, identical to `getIndicator(id)` once
`registerBuiltinIndicators()` has run. Call one's `calc` instead of porting its
formula: `getIndicator('macd').calc(bars, settings, {})`. These are also the ids
a custom module can accidentally shadow.

`ADL`, `ADX`, `ALLIGATOR`, `ALMA`, `ALPHATREND`, `AROON`, `AROON_OSCILLATOR`, `ATR`, `AVERAGE_DAILY_RANGE`, `AWESOME_OSCILLATOR`, `BALANCE_OF_POWER`, `BB_TREND`, `BOLLINGER`, `BOLLINGER_BANDWIDTH`, `BOLLINGER_PERCENT_B`, `CCI`, `CHAIKIN_MONEY_FLOW`, `CHAIKIN_OSCILLATOR`, `CHAIKIN_VOLATILITY`, `CHANDE_KROLL_STOP`, `CHANDE_MOMENTUM`, `CHANDELIER_EXIT`, `CHOP_ZONE`, `CHOPPINESS_INDEX`, `CONNORS_RSI`, `CONSOLIDATION_BREAKOUT`, `COPPOCK_CURVE`, `CPR`, `DEMA`, `DONCHIAN`, `DPO`, `EASE_OF_MOVEMENT`, `ELDER_FORCE_INDEX`, `ELDER_RAY`, `EMA`, `ENVELOPE`, `FISHER_TRANSFORM`, `HALFTREND`, `HIGH_LOW_52_WEEK`, `HISTORICAL_VOLATILITY`, `HMA`, `HULL_SUITE`, `ICHIMOKU`, `KAMA`, `KELTNER_CHANNEL`, `KLINGER_OSCILLATOR`, `KNOW_SURE_THING`, `LINREG_SLOPE`, `LSMA`, `MA_CHANNEL`, `MA_CROSS`, `MA_RIBBON`, `MACD`, `MASS_INDEX`, `MCGINLEY_DYNAMIC`, `MEDIAN`, `MFI`, `MOMENTUM`, `NET_VOLUME`, `NVI`, `OBV`, `OPEN_INTEREST`, `OPEN_INTEREST_BUILDUP`, `OPEN_INTEREST_CHANGE`, `PARABOLIC_SAR`, `PPO`, `PVI`, `PVO`, `PVT`, `RANGE_ANALYSIS`, `RELATIVE_VIGOR_INDEX`, `RELATIVE_VOLATILITY_INDEX`, `ROC`, `RSI`, `RSI_DIVERGENCE`, `SCHAFF_TREND_CYCLE`, `SEASONALITY`, `SMA`, `SMI`, `SMI_ERGODIC_INDICATOR`, `SMI_ERGODIC_OSCILLATOR`, `SMMA`, `SPECIAL_K`, `STANDARD_DEVIATION`, `STANDARD_ERROR`, `STANDARD_ERROR_BANDS`, `STOCHASTIC`, `STOCHASTIC_RSI`, `SUPERTREND`, `T3`, `TEMA`, `TREND_STRENGTH_INDEX`, `TRIX`, `TSI`, `TWAP`, `ULCER_INDEX`, `ULTIMATE_OSCILLATOR`, `VIDYA`, `VOLATILITY_SQUEEZE`, `VOLATILITY_STOP`, `VOLUME`, `VORTEX`, `VWAP`, `VWMA`, `WAVETREND`, `WILLIAMS_FRACTALS`, `WILLIAMS_PERCENT_R`, `WILLIAMS_VIX_FIX`, `WMA`, `WOODIES_CCI`, `ZIGZAG`, `ZLEMA`

**Built-in indicator groups** (16)

Arrays of the descriptors above, as the picker rail groups them.

`ADAPTIVE_INDICATORS`, `AVERAGE_INDICATORS`, `BUILTIN_INDICATORS`, `EXPONENTIAL_INDICATORS`, `FLOW_INDICATORS`, `INDEX_INDICATORS`, `OSCILLATOR_INDICATORS`, `OVERLAY_INDICATORS`, `RANGE_INDICATORS`, `SEASONALITY_INDICATORS`, `SIGNAL_INDICATORS`, `STRENGTH_INDICATORS`, `STUDY_INDICATORS`, `SWING_INDICATORS`, `VOLATILITY_INDICATORS`, `WAVETREND_INDICATORS`

**Chart infrastructure, not for indicators** (146)

Panes, scales, feeds, drawing primitives, trading controllers, link groups, replay
and the render backends. An indicator describes what to compute and what to plot;
the chart owns these.

`addComparison`, `AlertController`, `alertSettingsSchema`, `alignRequestedExpression`, `alignToPrimary`, `applyChartSettings`, `assertTradingCapability`, `attachSessionShading`, `backendDegradation`, `backoffDelayMs`, `BAR_CACHE_VERSION`, `BarCache`, `barCacheKey`, `barsSince`, `beginPick`, `BUILTIN_COMMANDS`, `BuySellButtons`, `calendarMarketPhase`, `CandleBuilder`, `candleGeometry`, `candleTier`, `Canvas2dBackend`, `centerOfGravity`, `Chart`, `ChartObjects`, `chartSettingsSchema`, `ChartTable`, `checkTradingCapability`, `classifyAuthAck`, `comparisonController`, `ComparisonController`, `computePriceLevels`, `conflationGroupSize`, `createChart`, `createLinkGroup`, `createRenderBackend`, `createRequestedIndicator`, `crosses`, `crossesAbove`, `crossesBelow`, `DataLoadingController`, `dataVariantError`, `dataVariantKey`, `decodeOrder`, `DEFAULT_CANDLE_BUILDER_OPTIONS`, `DEFAULT_CHART_TABLE_OPTIONS`, `DEFAULT_KEYMAP`, `DEFAULT_PRICE_SCALE_OPTIONS`, `DEFAULT_TIME_NAVIGATOR_OPTIONS`, `DEFAULT_TIME_SCALE_OPTIONS`, `DEFAULT_ZOOM_GLIDE_OPTIONS`, `EventMarkers`, `eventToCombo`, `exportChartDataCsv`, `falling`, `filterLinkAppearance`, `followerIndex`, `followerRange`, `formatCombo`, `formatSubscribe`, `formatUnsubscribe`, `getBarCondition`, `getSeriesTransform`, `HistoryRequestPool`, `IndicatorDrawings`, `inheritedDataVariant`, `Instrument`, `InvalidationLevel`, `isRebasing`, `isReplaying`, `isReservedCombo`, `isValidCombo`, `LINK_CROSSHAIR_ALPHA`, `LinkCrosshair`, `LinkGroup`, `LogoWatermark`, `mapHistoryResponse`, `mapOrder`, `mapOrderStatus`, `mapPosition`, `marketStatusAt`, `normalizeCombo`, `normalizeDataVariant`, `OpenAlgoDataFeed`, `OpenAlgoLiveDataFeed`, `OpenAlgoTradeFeed`, `OpenAlgoWsFeed`, `Pane`, `PaneLegend`, `parseAlertsDocument`, `parseCombo`, `parseIndicatorPolicy`, `parseMessage`, `parsePaneState`, `parseTopic`, `percentileLinear`, `PriceLevels`, `PriceLine`, `PriceScale`, `publishDataContext`, `rankCorrelation`, `readChartSettings`, `readSequence`, `registerBarCondition`, `registeredBarConditions`, `registeredRenderBackends`, `registeredSeriesTransforms`, `registerRenderBackend`, `registerSeriesTransform`, `ReplayController`, `ReplayGroup`, `ReplayShade`, `requestedIntrabars`, `resolveRenderBackend`, `rising`, `rollingMedian`, `rollingMode`, `rollingRange`, `rollingVariance`, `runningMax`, `runningMin`, `SCALE_FONT_MAX`, `SCALE_FONT_MIN`, `securityExpression`, `SeriesMarkers`, `SessionCalendar`, `SessionShade`, `sharedHistoryRequests`, `ShortcutManager`, `SvgContext`, `SvgLinearGradient`, `TextWatermark`, `TickBarAggregator`, `TickSchedule`, `TimeNavigator`, `TimeScale`, `TradeMarkersPrimitive`, `TradingCapabilityError`, `TradingController`, `unregisterBarCondition`, `unregisterRenderBackend`, `unsupportedDataVariant`, `valueWhen`, `withBarCache`, `withTimeframe`, `ZoomGlide`

<!-- END GENERATED EXPORT INDEX -->
