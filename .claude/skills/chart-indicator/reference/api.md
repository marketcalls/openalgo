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

Nothing here changes the descriptor contract. It is what the surface gained
while the sections above stayed true.

| | |
| --- | --- |
| **1.8.3** | Eleven studies, taking the registry from 91 to 102: `t3`, `hull-suite`, `consolidation-breakout`, `smma`, `net-volume`, `linreg-slope`, `ma-channel`, `chaikin-volatility`, `standard-deviation`, `standard-error`, `standard-error-bands`. Each is exported as a descriptor constant and reusable through `getIndicator`. The same release corrected nine built-ins and moved ten defaults, so a study measured against a built-in before 1.8.3 needs its expectations re-derived rather than assumed. |
| **1.8.4** | `calc` is flushed once per animation frame rather than per tick, so it must be a pure function of `(bars, settings)`. `calcTail` now only pays for deep history, not for a fast feed. |
| **1.8.9** | Precision follows the pane an indicator is handed. An overlay plot prints at the instrument's tick, a study pane at two decimals or finer. Nothing to declare in the descriptor. |
| **2.0.0** | The render backend port (`createRenderBackend`, `registerRenderBackend`, `Canvas2dBackend`, `resolveRenderBackend`, `backendDegradation`) plus SVG export and watermark helpers. All chart infrastructure: an indicator never touches a backend, and the WebGL2 path renders the same plots. |
| **2.1.2** | A Tier-2 study's history requests and live callbacks are isolated by data key, so a response for a setting you have left cannot land on the current one. |
| **2.1.5** | Drawing previews survive past the newest candle. No indicator surface changed. |

## Complete export index

<!-- BEGIN GENERATED EXPORT INDEX -->

All 363 names on the API object, so nothing is a surprise. Generated from
the installed openalgo-charts@2.1.5 build by `generate-api-index.mjs`; do not
edit this section by hand.

**Registration and introspection** (13)

`registerIndicator`, `createTier2Indicator`, `registeredIndicators`, `getIndicator`, `hasIndicator`, `indicatorDefaults`, `indicatorStyleInputs`, `plotStyleKeys`, `registeredChartTypes`, `getChartType`, `registerChartType`, `registerBuiltinIndicators`, `INDICATORS_TIER`

**Reading bars** (10)

`sourceValues`, `sourceValue`, `INDICATOR_SOURCES`, `toBar`, `mergeBars`, `conflateBars`, `conflateItems`, `isWhitespace`, `generateBars`, `FakeDataFeed`

**Moving averages and statistics** (28)

`sma`, `wma`, `rma`, `ema`, `smaSeededEma`, `stdev`, `dev`, `highest`, `lowest`, `highestBars`, `lowestBars`, `rollingSum`, `cumulative`, `linreg`, `swma`, `alma`, `vwma`, `percentRank`, `percentileNearestRank`, `correlation`, `nulls`, `connorsStreak`, `change`, `roc`, `stoch`, `cci`, `pivotHigh`, `pivotLow`

**OHLC studies** (7)

`trueRange`, `atr`, `rsi`, `supertrend`, `emaSeries`, `rsiSeries`, `supertrendSeries`

**Sessions, time and timeframes** (48)

`DEFAULT_TIMEZONE`, `IST_OFFSET_SECONDS`, `isValidTimezone`, `utcSecondsToZonedParts`, `utcSecondsToIstParts`, `zonedDayIndex`, `zonedWeekIndex`, `zoneOffsetSeconds`, `isNewZonedDay`, `isNewZonedWeek`, `isNewZonedMonth`, `isNewZonedQuarter`, `isNewZonedYear`, `isNewZonedPeriod`, `isNewIstDay`, `startOfZonedDay`, `startOfZonedWeek`, `startOfZonedMonth`, `sessionStartFlags`, `sessionStartIndices`, `calendarPeriodFlags`, `parseSessionSpec`, `inSessionAt`, `sessionFlags`, `epochMsToUtcSeconds`, `istStringToUtcSeconds`, `zonedStringToUtcSeconds`, `zonedWallClockToUtcSeconds`, `utcSecondsToIstDateString`, `utcSecondsToZonedDateString`, `rowTimeToUtcSeconds`, `barCloseSec`, `bucketStartOf`, `nextBucketStart`, `isTimeBucketed`, `intervalToSeconds`, `intervalParts`, `isIntradayInterval`, `isDailyInterval`, `isSecondsInterval`, `isTickInterval`, `isKnownInterval`, `resolveInterval`, `tryResolveInterval`, `registeredIntervals`, `registerInterval`, `unregisterInterval`, `UnknownIntervalError`

**Formatting** (10)

`formatIstTime`, `formatIstTimeSeconds`, `formatIstDate`, `formatIstCrosshairLabel`, `formatZonedTime`, `formatZonedTimeSeconds`, `formatZonedDate`, `formatZonedCrosshairLabel`, `compactVolume`, `precisionForStep`

**Colours, numbers and geometry** (20)

`withAlpha`, `fromGradient`, `verticalGradient`, `clamp`, `lerp`, `roundToTick`, `niceTicks`, `autoscaleRange`, `optimalBarWidth`, `snapToDevicePixel`, `bitmapSize`, `dashPattern`, `markerSizePx`, `effectiveMarkerPx`, `drawShape`, `drawLabel`, `bestHit`, `tableOrigin`, `watermarkRect`, `resolvePlotMargins`

**Style and option lists** (21)

`INDICATOR_LINE_STYLES`, `INDICATOR_PLOT_STYLES`, `PRICE_SCALE_MODES`, `PRICE_LEVEL_KINDS`, `DEFAULT_THEME`, `darkTheme`, `lightTheme`, `ALT_PRESET`, `VERSION`, `version`, `CHART_STATE_VERSION`, `DEFAULT_CANDLE_STYLE`, `DEFAULT_HISTOGRAM_STYLE`, `DEFAULT_TRADING_COLORS`, `resolveCrosshairStyle`, `resolveGridStyle`, `resolveScaleStyle`, `seriesStyleForLastPriceLevel`, `lastPriceLevelFromSeriesStyle`, `IndicatorBackground`, `IndicatorFill`

**Built-in indicator descriptors** (102)

Each is the descriptor object itself, identical to `getIndicator(id)` once
`registerBuiltinIndicators()` has run. Call one's `calc` instead of porting its
formula: `getIndicator('macd').calc(bars, settings, {})`. These are also the ids
a custom module can accidentally shadow.

`ADL`, `ADX`, `ALLIGATOR`, `ALMA`, `ALPHATREND`, `AROON`, `AROON_OSCILLATOR`, `ATR`, `AVERAGE_DAILY_RANGE`, `AWESOME_OSCILLATOR`, `BALANCE_OF_POWER`, `BB_TREND`, `BOLLINGER`, `BOLLINGER_BANDWIDTH`, `BOLLINGER_PERCENT_B`, `CCI`, `CHAIKIN_MONEY_FLOW`, `CHAIKIN_OSCILLATOR`, `CHAIKIN_VOLATILITY`, `CHANDE_KROLL_STOP`, `CHANDE_MOMENTUM`, `CHANDELIER_EXIT`, `CHOP_ZONE`, `CHOPPINESS_INDEX`, `CONNORS_RSI`, `CONSOLIDATION_BREAKOUT`, `COPPOCK_CURVE`, `CPR`, `DEMA`, `DONCHIAN`, `DPO`, `EASE_OF_MOVEMENT`, `ELDER_FORCE_INDEX`, `EMA`, `ENVELOPE`, `FISHER_TRANSFORM`, `HALFTREND`, `HISTORICAL_VOLATILITY`, `HMA`, `HULL_SUITE`, `ICHIMOKU`, `KAMA`, `KELTNER_CHANNEL`, `KLINGER_OSCILLATOR`, `KNOW_SURE_THING`, `LINREG_SLOPE`, `LSMA`, `MA_CHANNEL`, `MA_CROSS`, `MA_RIBBON`, `MACD`, `MASS_INDEX`, `MCGINLEY_DYNAMIC`, `MEDIAN`, `MFI`, `MOMENTUM`, `NET_VOLUME`, `NVI`, `OBV`, `PARABOLIC_SAR`, `PPO`, `PVI`, `PVO`, `PVT`, `RANGE_ANALYSIS`, `RELATIVE_VIGOR_INDEX`, `RELATIVE_VOLATILITY_INDEX`, `ROC`, `RSI`, `RSI_DIVERGENCE`, `SEASONALITY`, `SMA`, `SMI`, `SMI_ERGODIC_INDICATOR`, `SMI_ERGODIC_OSCILLATOR`, `SMMA`, `SPECIAL_K`, `STANDARD_DEVIATION`, `STANDARD_ERROR`, `STANDARD_ERROR_BANDS`, `STOCHASTIC`, `STOCHASTIC_RSI`, `SUPERTREND`, `T3`, `TEMA`, `TREND_STRENGTH_INDEX`, `TRIX`, `TSI`, `TWAP`, `ULCER_INDEX`, `ULTIMATE_OSCILLATOR`, `VOLATILITY_STOP`, `VOLUME`, `VORTEX`, `VWAP`, `VWMA`, `WAVETREND`, `WILLIAMS_FRACTALS`, `WILLIAMS_PERCENT_R`, `WILLIAMS_VIX_FIX`, `WMA`, `WOODIES_CCI`

**Built-in indicator groups** (14)

Arrays of the descriptors above, as the picker rail groups them.

`ADAPTIVE_INDICATORS`, `AVERAGE_INDICATORS`, `BUILTIN_INDICATORS`, `FLOW_INDICATORS`, `INDEX_INDICATORS`, `OSCILLATOR_INDICATORS`, `OVERLAY_INDICATORS`, `RANGE_INDICATORS`, `SEASONALITY_INDICATORS`, `SIGNAL_INDICATORS`, `STRENGTH_INDICATORS`, `STUDY_INDICATORS`, `VOLATILITY_INDICATORS`, `WAVETREND_INDICATORS`

**Chart infrastructure, not for indicators** (90)

Panes, scales, feeds, drawing primitives, trading controllers, link groups, replay
and the render backends. An indicator describes what to compute and what to plot;
the chart owns these.

`addComparison`, `alignToPrimary`, `applyChartSettings`, `backendDegradation`, `backoffDelayMs`, `BarCache`, `barCacheKey`, `barsSince`, `beginPick`, `BUILTIN_COMMANDS`, `BuySellButtons`, `CandleBuilder`, `candleGeometry`, `candleTier`, `Canvas2dBackend`, `Chart`, `chartSettingsSchema`, `ChartTable`, `classifyAuthAck`, `comparisonController`, `ComparisonController`, `computePriceLevels`, `conflationGroupSize`, `createChart`, `createLinkGroup`, `createRenderBackend`, `decodeOrder`, `DEFAULT_CANDLE_BUILDER_OPTIONS`, `DEFAULT_CHART_TABLE_OPTIONS`, `DEFAULT_KEYMAP`, `DEFAULT_PRICE_SCALE_OPTIONS`, `DEFAULT_TIME_NAVIGATOR_OPTIONS`, `DEFAULT_TIME_SCALE_OPTIONS`, `DEFAULT_ZOOM_GLIDE_OPTIONS`, `EventMarkers`, `eventToCombo`, `followerIndex`, `followerRange`, `formatCombo`, `formatSubscribe`, `formatUnsubscribe`, `IndicatorDrawings`, `InvalidationLevel`, `isRebasing`, `isReservedCombo`, `isValidCombo`, `LINK_CROSSHAIR_ALPHA`, `LinkCrosshair`, `LinkGroup`, `LogoWatermark`, `mapHistoryResponse`, `mapOrder`, `mapOrderStatus`, `mapPosition`, `normalizeCombo`, `OpenAlgoDataFeed`, `OpenAlgoLiveDataFeed`, `OpenAlgoTradeFeed`, `OpenAlgoWsFeed`, `Pane`, `PaneLegend`, `parseCombo`, `parseMessage`, `parseTopic`, `PriceLevels`, `PriceLine`, `PriceScale`, `readChartSettings`, `readSequence`, `registeredRenderBackends`, `registerRenderBackend`, `ReplayController`, `ReplayShade`, `resolveRenderBackend`, `SCALE_FONT_MAX`, `SCALE_FONT_MIN`, `SeriesMarkers`, `ShortcutManager`, `SvgContext`, `SvgLinearGradient`, `TextWatermark`, `TickBarAggregator`, `TimeNavigator`, `TimeScale`, `TradeMarkersPrimitive`, `TradingController`, `unregisterRenderBackend`, `valueWhen`, `withBarCache`, `ZoomGlide`

<!-- END GENERATED EXPORT INDEX -->
