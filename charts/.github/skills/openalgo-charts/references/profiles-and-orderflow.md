# Profiles and Order Flow

*When to read this: you are adding a Volume Profile, a Market Profile / TPO, or a Footprint / order-flow ladder, or you need to know whether the user's data can support one at all.*

Source of truth: `src/profile/*.ts`, `dist/profile/index.d.ts`, `tests/profiles.test.ts`, `tests/market-profile.test.ts`, `tests/market-profile-primitive.test.ts`.

## Setup

```ts
import { computeMarketProfile, MarketProfile } from 'openalgo-charts/profile';
```

`openalgo-charts/profile` is a separate entry point (`package.json` `exports["./profile"]`), not part of the base bundle. See [bundling-and-tiers](bundling-and-tiers.md).

**Every profile ships as two halves: a pure compute function and a canvas primitive.** Nothing here is a series type, there is no `chart.addSeries('volumeProfile')`. Compute a result object, attach a primitive with `chart.addPrimitive(primitive, paneIndex?)` (the price pane when none is named), detach with `chart.removePrimitive(primitive)`. See [primitives-and-plugins](primitives-and-plugins.md).

**A pane needs a price series before a profile renders.** Every profile primitive maps time to x via `rc.dataLayer.timeToIndex(...)`; with no bars that returns `undefined` and `draw` bails silently.

| Study | Compute | Primitive | Data needed |
|---|---|---|---|
| Volume Profile | `computeVolumeProfile`, `computeVolumeProfileSessions` | `VolumeProfile` | OHLCV (approximate) |
| Market Profile / TPO | `computeTpo`, `computeMarketProfile` | `MarketProfile` | intraday OHLCV |
| Footprint / order flow | `computeFootprint` | `Footprint` | trade-by-trade, classified bid/ask |
| Anything custom | your own | `HorizontalProfile` | whatever you have |

### Price bucketing (shared by every compute)

`bucketPrice(price, step)` snaps to the **nearest** multiple of `step`, rounded to 8 dp against float drift: `bucketPrice(100.003, 0.05) === 100`. `priceBuckets(low, high, step)` is inclusive at both ends: `priceBuckets(100, 100.2, 0.05)` is `[100, 100.05, 100.1, 100.15, 100.2]`.

**Rows are `tickSize * rowTicks`, and the two are deliberately separate.** `tickSize` is the instrument's real tick; `rowTicks` widens the visual row without lying about it. `rowTicksFor(rowSize, tickSize)` does the division and floors at 1, `rowTicksFor(2, 0.1) === 20`. `computeMarketProfile`, `computeFootprint` and `FootprintAggregator` all take that multiplier, so bricks and TPO rows can share one grid. `computeVolumeProfile` / `computeVolumeProfileSessions` have **no** `rowTicks`; pass a coarser `tickSize`.

**Bucketing rounds to nearest, so a profile can extend up to half a row past the bar's true high/low.**

## Volume Profile

### Single profile

`computeVolumeProfile(bars, tickSize, valueAreaPercent = 0.7)` (**positional**, not an options object) returns `VolumeProfileResult` = `{ buckets: { price, volume }[], poc, vah, val, totalVolume }`.

**`VolumeProfileOptions` is deprecated (removed in 3.0.0): no function consumes it.** It only describes `{ tickSize, valueAreaPercent }`; passing an object where `tickSize` is expected yields `NaN` buckets. Use the positional form, or `computeVolumeProfileSessions` for the options-object API.

Semantics, identical in `computeVolumeProfile`, `computeTpo` and the session family (one shared expansion, which the footprint statistics use too):

- Each bar's volume is spread **uniformly** across `priceBuckets(bar.low, bar.high, tickSize)`, `bar.volume / buckets.length` per row. From OHLCV this is an approximation, not a tick-accurate profile.
- `buckets` / `levels` are always sorted **high price first**.
- **POC** is the max-volume row; ties resolve to the **highest** price (strict `>` over a descending list).
- **Value area** starts at the POC and repeatedly absorbs whichever immediate neighbour holds more volume, stopping once accumulated volume reaches `totalVolume * valueAreaPercent`. Ties go **upward**. `vah` / `val` are the extremes reached.
- `valueAreaPercent` is a fraction. Passing `70` puts every row in the value area, unless the bars carry no volume at all: then the area is the POC alone, whatever the fraction. At exactly `1` the area stops once it holds all the volume, so rows without volume at its edges stay out. The draw tier's fixed range volume profile names the same share `valueArea` and takes a percent (1..100, default 70), so a value copied between the two is off by a factor of 100.

**Invalid numeric options, per entry point.** `computeVolumeProfile` and `computeTpo` take their arguments as given: a `tickSize` that is not a positive finite number gives an empty result (since 2.6.0; before, a negative one never returned), and `valueAreaPercent` is not clamped; only `computeTpo`'s `periodBars` below 1 counts as 1. `computeVolumeProfileSessions` and `computeMarketProfile` repair instead: the tick falls back to the default, `valueAreaPercent` is clamped to 0..1, and the market profile floors `rowTicks`, `initialBalancePeriods` and `compositeSessions` at 1. `computeFootprint`, `FootprintAggregator` and the `Footprint` primitive throw `RangeError`.

### Session family

`computeVolumeProfileSessions(bars, options?)` returns `VolumeProfileFamilyResult` = `{ sessions, options }`. `VolumeProfileFamilyOptions` / `DEFAULT_VOLUME_PROFILE_FAMILY_OPTIONS`:

| Key | Type | Default | Notes |
|---|---|---|---|
| `tickSize` | `number` | `0.05` | Row size. Non-positive falls back to the default. |
| `session` | `VolumeProfileSession` | `'composite'` | `'composite' \| 'day' \| 'week' \| 'month'`. |
| `valueAreaPercent` | `number` | `0.7` | Clamped to 0..1. |
| `deltaFromBarDirection` | `boolean` | `true` | Split volume buy/sell by `close >= open`. |
| `timezone` | `string` | `'Asia/Kolkata'` | IANA zone the day / week / month buckets resolve on. Pass `chart.timezone()` to keep a profile and its chart on one clock. |

`VolumeProfileSessionResult`: `{ startTime, endTime, levels, poc, vah, val, totalVolume, buyVolume, sellVolume, delta }`. `VolumeProfileLevel`: `{ price, volume, buyVolume, sellVolume, delta }`, high to low.

Sessions group on the calendar of the `timezone` option, which **defaults to `Asia/Kolkata`** rather than being fixed to it, weeks starting Monday (see [data-and-time](data-and-time.md)). The module is a pure calculation and is never handed the chart, so pass `chart.timezone()` yourself if the two must agree. A visible-range profile is just the visible slice with `session: 'composite'`.

**`buyVolume` / `sellVolume` are not bid/ask delta.** An up bar's entire volume is called buying, a down bar's entire volume selling. `deltaFromBarDirection: false` leaves all three at zero.

### `VolumeProfile` primitive

`new VolumeProfile(result: VolumeProfileFamilyResult | null, opts?: Partial<VolumeProfilePrimitiveOptions>)`, then `setData(result)` / `setOptions(patch)`. `autoscaleInfo()` reports the price extent across all sessions. `DEFAULT_VOLUME_PROFILE_PRIMITIVE_OPTIONS`:

| Key | Default | Notes |
|---|---|---|
| `displayMode` | `'total'` | `VolumeDisplayMode` = `'total' \| 'buySell' \| 'delta'`. |
| `side` | `'right'` | `VolumeProfileSide`; anchors bars at the session's left or right edge. |
| `width` / `opacity` | `90` / `0.85` | Max bar length in media px. |
| `barColor` / `buyColor` / `sellColor` | `#3b5168` / `#26a69a` / `#ef5350` | |
| `showPoc` / `pocColor` / `showPocLabel` | `true` / `#f0a020` / `true` | |
| `showValueArea` / `vahColor` / `valColor` / `showValueAreaLabels` | `true` / `#8892a6` / `#8892a6` / `true` | |
| `highlightValueArea` / `valueAreaFillColor` / `valueAreaFillOpacity` | `true` / `#4a6fa5` / `0.08` | |
| `valueAreaOpacityDim` | `0.4` | Alpha multiplier for rows outside the value area. |
| `labelSide` / `zOrder` | `'right'` / `'bottom'` | Label edge; draw behind or over the series. |

`'delta'` scales bars by `|delta|` and colours by sign; `'buySell'` splits each row into a buy then a sell segment. Both are empty when `deltaFromBarDirection` was off.

## Market Profile (TPO)

### The session and period model

0. One clock is chosen for the whole profile: the `window`'s own `zone` when it names one, otherwise `options.timezone` (default `Asia/Kolkata`). A window's zone wins so that a preset selects the same real instants and forms the same sessions however the chart is displayed.
1. Bars are dropped if a `window` is set and `inWindow(bar.time, window, zone)` is false.
2. Surviving bars group into sessions by calendar key on that clock (`day` / `week` / `month`), or one group for `composite`. `compositeSessions: N` then folds every N consecutive groups into one profile.
3. Within a session, each bar's **period index** is `floor((bar.time - anchor) / (blockMinutes * 60))`. `anchor` is the session's first bar time, unless a real window is set, in which case it is that day's window open resolved as **wall clock** in the window's zone, so a session whose first bar arrives late does not shift every letter, and a daylight-saving changeover does not shift them either.
4. Period index maps to a letter via `tpoLetter`: `0..25` to `A..Z`, `26..51` to `a..z`, then wraps (`tpoLetter(52) === 'A'`).
5. For each bar, every row in `priceBuckets(bar.low, bar.high, tickSize * rowTicks)` records the period index in a **Set** and accumulates `bar.volume / rowCount`. A level's `count` is therefore the number of **distinct periods** at that price, not the number of bars.

### `computeMarketProfile(bars, options?)`

Returns `MarketProfileResult` = `{ sessions: MarketProfileSessionResult[], options }`. `MarketProfileOptions` / `DEFAULT_MARKET_PROFILE_OPTIONS`:

| Key | Type | Default | Notes |
|---|---|---|---|
| `tickSize` | `number` | `0.05` | Instrument tick. Non-positive falls back to the default. |
| `rowTicks` | `number` | `1` | Row = `tickSize * rowTicks`. Floored at 1. |
| `session` | `MarketProfileSession` | `'day'` | `'day' \| 'week' \| 'month' \| 'composite'`. |
| `blockMinutes` | `number` | `30` | One letter per block. |
| `valueAreaPercent` | `number` | `0.7` | Clamped to 0..1. |
| `initialBalancePeriods` | `number` | `2` | Opening periods forming the IB. |
| `window` | `SessionWindow \| undefined` | none | Drops out-of-window bars and anchors letters. Its own `zone` outranks `timezone`. |
| `timezone` | `string` | `'Asia/Kolkata'` | IANA zone for the window test and the day / week / month keys, when the window names none. |
| `compositeSessions` | `number` | `1` | Merge N consecutive sessions. |
| `tailEdges` | `number` | `0` | Min run of single prints promoting a tail. 0 disables. |

`result.options` echoes the merged options with `rowTicks` normalised; `result.options.tickSize` stays the instrument tick. `computeTpo(bars, periodBars, tickSize, valueAreaPercent = 0.7, ibPeriods = 2)` is the cut-down alternative: one profile over the whole array, periods counted in **bars** rather than minutes, returning `TpoResult` = `{ buckets: { price, count }[], poc, vah, val, ib: { high, low } }` with no letters, sessions or analytics.

`MarketProfileSessionResult` fields worth knowing:

| Field | Meaning |
|---|---|
| `levels` | `MarketProfileLevel[]` high to low: `{ price, count, letters, periods, volume }`. |
| `poc` / `vah` / `val` | Same expansion algorithm as the volume profile, over TPO counts. |
| `periodDetail` / `periods` | `MarketProfilePeriod[]` = `{ index, letter, startTime, endTime, high, low, volume }`; `periods` is `maxIndex + 1` and can exceed `periodDetail.length` when a period had no bars. |
| `initialBalance` / `rangeExtension` | IB from bars with period index `< initialBalancePeriods`; extension is `{ up: max(0, high - ib.high), down: max(0, ib.low - low) }`. |
| `singlePrints` | Interior levels with `count === 1`; both extremes excluded by construction. |
| `buyingTail` / `sellingTail` | `null` unless `tailEdges > 0`. A run at the **top** yields `sellingTail`, at the **bottom** `buyingTail`. |
| `poorHigh` / `poorLow` | The extreme level printed more than one TPO. |
| `developing` | `DevelopingValue[]` = `{ periodIndex, time, poc, vah, val }`, one per period, recomputed from periods `<= index`; `time` is that period's last bar time. |
| `dayType` | `'normal' \| 'normal-variation' \| 'trend' \| 'double-distribution' \| 'neutral'`. Heuristic: extension both ways is `neutral`; a second node `>= 0.7 * peak` with a middle `<= 0.35 * peak` is `double-distribution`; then `range / ibRange >= 2.5` is `trend`, `>= 1.4` is `normal-variation`. |
| `openType` | `'drive' \| 'test-drive' \| 'rejection-reverse' \| 'auction'`, from the open's position in the range plus the first two periods' probes. |
| `volumePoc` / `totalVolume` / `label` | Volume-weighted POC, session volume, and `window?.name`. |

### Helpers

| Function | Contract |
|---|---|
| `tpoLetter(period)` | Period index to `A-Z`/`a-z`, mod 52. |
| `rowTicksFor(rowSize, tickSize)` | `max(1, round(rowSize / tickSize))`; returns 1 on non-positive input. |
| `rowOf(price, options)` | Snaps a price onto the profile's row grid, use it to hit-test against `levels`. |
| `inWindow(utcSeconds, window, zone?)` | Wrap-aware; `startMinute === endMinute` means all hours. `zone` (default `Asia/Kolkata`) is consulted only when the window names none of its own. |
| `nakedLevels(result)` | Prior `poc`/`vah`/`val` no later session traded through, oldest first, tagged `{ time, price, kind }`. The last session's three levels are always naked. |

`SessionWindow` is `{ startMinute, endMinute, name?, zone? }`. The minutes are **minutes from midnight in the window's own zone**, falling back to the profile's `timezone` (default `Asia/Kolkata`) when `zone` is absent; `end <= start` means an overnight window, which is kept as one session.

`TRADING_HOURS` presets, each carrying the zone its numbers are written in:

| Key | Window | Zone |
|---|---|---|
| `all-hours` | 0 to 0 (all hours) | none needed |
| `india` | 09:15 to 15:30 | `Asia/Kolkata` |
| `asia` | 09:00 to 15:00 | `Asia/Tokyo` |
| `london` | 07:00 to 13:00 | `Europe/London` |
| `new-york` | 08:00 to 15:30 | `America/New_York` |
| `us-regular` | 09:30 to 16:00 | `America/New_York` |

**A window's own zone outranks the display zone, for the window test and for the session keys alike.** Bucketing on the display zone would cut a 09:15-15:30 Kolkata session in half when the chart is read from New York, because that session genuinely straddles New York midnight. A preset therefore selects the same real instants on any display; only labels move.

**These presets changed instants in 1.3.0 for the DST markets.** They were previously written as fixed IST minutes authored in EDT terms, so `london`, `new-york` and `us-regular` were an hour wrong for the months either side of summer. They now reproduce the old instants through a summer week and are deliberately an hour later in winter, which is the point. `india`, `asia` and `all-hours` are unchanged year-round.

A window you write by hand should name its own zone for the same reason:

```ts
import { computeMarketProfile } from 'openalgo-charts/profile';

const result = computeMarketProfile(bars, {
  window: { startMinute: 9 * 60 + 30, endMinute: 16 * 60, zone: 'America/New_York', name: 'RTH' },
  timezone: chart.timezone(),   // only settles a window with no zone of its own
});
```

### `MarketProfile` primitive

`new MarketProfile(result | null, opts?)`; `setData`, `setOptions`, `options()`, `autoscaleInfo()`, `hitTest(x, y)` returning `mp:<sessionIndex>`, and `hoverAt(x, y, rc?)` returning `MarketProfileHover` = `{ sessionIndex, price, level, session, isPoc, inValueArea, isSinglePrint }`. `hoverAt` reuses the last paint's render context, so a `crosshair:move` handler can call `mp.hoverAt(e.point.x, e.point.y)` directly. Both need a prior `draw`.

Selected `MarketProfilePrimitiveOptions`; `DEFAULT_MARKET_PROFILE_PRIMITIVE_OPTIONS` supplies every key (full list in `src/profile/market-profile-primitive.ts`):

| Key | Default | Notes |
|---|---|---|
| `blockDisplay` | `'auto'` | `MpBlockDisplay` = `'auto' \| 'compact' \| 'blocks+letters' \| 'letters' \| 'blocks'`. Compact uses a pixel font for small rows. |
| `minLetterHeight` / `letterFade` | `7` / `4` | In `'auto'`, letters fade in over `letterFade` px above `minLetterHeight`; the block always draws. |
| `letterWidth` / `font` | `8` / `10` | Font auto-shrinks to `rowHeight * 0.95`. |
| `colorMode` / `periodColors` | `'period'` / `TPO_PERIOD_COLORS` | `MpColorMode` = `'period' \| 'valueArea' \| 'count' \| 'volume' \| 'uniform'`; 12 hues indexed `periodIndex % length`. |
| `color` / `vaColor` | `#5a6b8c` / `#4a8f7a` | |
| `opacity` / `outsideVaOpacity` | `0.92` / `0.45` | |
| `split` / `profileSpacing` | `false` / `4` | `split` gives each period its own column slot, so gaps show which periods missed a row. |
| `showPoc` / `pocColor` / `pocThickness` / `showPocLabel` | `true` / `#f0a020` / `2` / `true` | |
| `showValueArea` / `fillValueArea` / `valueAreaFillOpacity` / `showValueAreaLabels` | `true` / `true` / `0.07` / `true` | |
| `showInitialBalance` / `showSinglePrints` / `showTails` | all `true` | Tails need `tailEdges > 0` in the compute. |
| `showPoorHighLow` / `showNakedLevels` / `showDevelopingPoc` / `showDevelopingVa` / `showTpoCounts` | all `false` | |
| `showSessionLabel` / `showDayType` / `showOpenType` | `true` / `false` / `false` | The session label only appears when a `window` set `label`. |
| `showVolumeProfile` / `volumeProfileWidth` / `volumeProfileSide` / `showVolumeValues` | `false` / `60` / `'right'` / `false` | |
| `showSessionOpen` / `sessionOpenColor` | `false` / `#5ca8ff` | Lowercase `o` on each session's actual opening-price row. |
| `showLastPrice` / `lastPriceColor` | `false` / `#ff6b5e` | `#` at the newest supplied session's last close, not the computer's current day. |
| `zOrder` | `'top'` | |

**`colorMode: 'count'` and `'volume'` change alpha, not hue.** Both fall through to `color`; the heat is `0.3 + 0.7 * share` applied to opacity.

**`showNakedLevels: true` recomputes `nakedLevels(result)` on every frame.** It is O(sessions squared); precompute and draw your own lines if the session count is large.

### Compact profiles and demo themes

```ts
const profile = new MarketProfile(result, {
  blockDisplay: 'compact', showVolumeValues: true,
  showSessionOpen: true, showLastPrice: true,
});
chart.addPrimitive(profile);
profile.setSessionSplit(2, true);
profile.isSessionSplit(2);       // true
profile.setSessionSplit(2, null); // return this session to the global split setting
```

The 2.1.0 compact mode uses distinct pixel letters when rows have at least 5 physical
pixels of height and 3 of width. Larger rows use ordinary canvas text; smaller rows use
marks with exact values available through hover. Test at the actual device pixel ratio.
Canvas 2D and SVG export support the compact letters without a WebGL2 dependency.

Per-session split choices follow calendar session identity through `setData`, prepended
history and row regrouping. Theme-only `setOptions` patches preserve them; explicitly
setting the global `split` option clears the overrides. Open/latest markers stay within
the visible plot and latest-price markers only belong to the newest supplied session.

The palette names below belong to demos, not exported library presets:

| Demo | Presets | Apply through |
|---|---|---|
| `examples/market-profile/` | Dark, Blue, Graphite, Emerald, Ivory | `themes.js` supplies chart/profile/control colours; `chart.setTheme` plus profile options |
| `examples/orderflow/` | Midnight, Graphite, Classic neon, Ocean, Ember, Forest, Ivory | Presets in `index.html`; chart theme and `Footprint.setOptions` remain independent of style/text method |

For an upstream website change, read `scripts/capture-profile-screenshots.mjs` and
`scripts/check-profile-website.mjs`. The capture script uses the served standalone demo
and records source hashes plus PNG hashes in
`website/public/screenshots/market-profile-v2.1.1/captures.json`. That directory names the
capture generation, not the installed package version. Regenerate when a fingerprinted
render source changes, then build the site so its public demos and bundles are synced.
The guide's compressed overview and enlarged single-session close-ups use different
row heights; preserve that distinction in captions. See
[host-integration](host-integration.md#browser-validation) for the browser checks.

## Footprint and order flow

**Footprint and order flow require trade-by-trade data classified bid/ask**: was each print at the bid (sell-initiated) or the ask (buy-initiated)? OpenAlgo serves live depth and tick LTP but **does not store historical classified trades by default**, so footprint is a **live-session-only** study unless the host runs a tick recorder that persists classified prints. The compute layer is pure and broker-agnostic; feeding it is the integration step. `ARCHITECTURE.md` section 6A gives the two paths: classify live WS prints against the live bid/ask and keep a rolling session buffer, or add an OpenAlgo-side tick/depth recorder. **`FootprintAggregator` is the live path.** See [feeds-and-live](feeds-and-live.md).

Nothing else in this file has that dependency, Volume Profile and Market Profile derive from plain OHLCV.

`computeFootprint(time, trades, tickSize, rowTicks = 1, options?: FootprintBuildOptions)` returns a `FootprintBar`. `ClassifiedTrade` is `{ price, qty, side: 'bid' | 'ask' }`; `FootprintCell` is `{ price, bidVol, askVol }`. `FootprintBar` requires `{ time, cells, delta }`, with cells high to low and `delta = sum(askVol - bidVol)`. Its optional metadata fields are `rowSize`, `open`, `high`, `low`, `close`, `tradeCount`, `minDelta`, `maxDelta` and `auction` (`{ highBid, highAsk, lowBid, lowAsk }`: every print's bid and ask volume at the exact high and low, before any size filter).

**Row alignment.** A trade is put on its tick (half away from zero), then on its row by round half to even: rows are centred on multiples of `tickSize * rowTicks`, and a tick exactly between two row centres goes to the even row (2-point rows on a 0.05 tick: 22469.00 to 22468, 22471.00 to 22472). Interval bars cover `[start, start + seconds)`, so a trade stamped on a boundary opens the next bar.

**`FootprintBuildOptions`** is `{ minTradeSize? }`: count only single prints of at least this raw quantity. Smaller prints still open their row (it shows zero) and still set OHLC; volume, delta, delta extremes and `tradeCount` count only the prints that pass. Negative or nonfinite sizes throw.

**Classifying raw prints.** `createTradeClassifier(mode: TradeClassification = 'tickRule')` returns a stateful `(print: TradePrint) => 'bid' | 'ask'`; `TradePrint` is `{ price, qty, bid?, ask? }`. `'tickRule'`: above the previous print is a buy, below a sell, unchanged keeps the previous side, the first print is a buy. `'quote'`: at or above a valid ask is a buy, at or below a valid bid a sell, otherwise the tick rule. One classifier per instrument, prints in time order.

Both the batch computation and `FootprintAggregator` populate `rowSize = tickSize * rowTicks`, actual traded OHLC prices before row rounding, the number of classified records, and the minimum/maximum running intrabar delta including initial zero. These extrema follow trade order before price grouping: bid 5, ask 12, bid 10 produces final delta -3, minimum -5 and maximum 7. Extrema reset on each new bar and cannot be recovered from aggregated rows. Empty batch input returns empty cells, zero delta, zero extrema and zero trade count, without invented OHLC. Legacy manually supplied bars may omit metadata.

`tickSize` must be positive and finite, and `rowTicks` must be a positive safe integer. Prices and timestamps must be finite, quantities must be finite and nonnegative, and sides must be `'bid'` or `'ask'`. Zero-quantity records are accepted and still count as records. Invalid inputs throw rather than silently changing the row multiplier or poisoning live state.

| Function | Contract |
|---|---|
| `diagonalImbalances(cells, ratio = 3, rowSize?, threshold = 0)` | `Imbalance[]` of `{ price, side }`. Buy when positive `askVol[P] >= ratio * bidVol[P - rowSize]`; sell when positive `bidVol[P] >= ratio * askVol[P + rowSize]`. A row inside the bar that never traded counts as zero (since 2.6.4). The dominant quantity must also meet the inclusive threshold. |
| `cumulativeDelta(bars)` | `number[]`, running total of `bar.delta`, same length and order as input. |
| `stackedImbalances(cells, ratio = 3, minStack = 3, rowSize?, threshold = 0)` | `StackedImbalance[]` of `{ startPrice, endPrice, side, count }`. Tracks runs of `minStack` or more adjacent same-side diagonal flags independently, preserving both flags when a row qualifies on both sides. |

**Fractional quantities are compared directly.** Positive volume against a zero opposing volume qualifies, subject to the threshold; zero against zero does not. Since 2.6.4 a row between the bar's high and low that never traded counts as zero volume, so a cell beside such a gap is compared with zero (through 2.6.3 it was not compared, so fewer imbalances were found next to gaps). The rows beyond the bar's high and low are not compared, nor is a gap narrower than one row (a grid the row size does not describe). Stacks still stop at gaps: the untraded row itself is never an imbalance. Supply the bar's `rowSize` for sparse ladders. Legacy calls infer the minimum observed price gap, which cannot distinguish uniformly missing rows from a coarser grid. Ratio and an explicit row size must be positive and finite, threshold nonnegative and finite, and minimum stack length a positive safe integer.

### `Footprint` primitive

`new Footprint(opts?: Partial<FootprintOptions>)`, then `setBars(readonly FootprintBar[])`. Also `setOptions(patch)`, `options()`, `stats()`, `autoscaleInfo()`, `hitTest(x, y)` returning `footprint:<time>`, and `hoverAt(x, y, rc?)` returning `FootprintHover` = `{ time, price, cell, stats }`. Over a statistics card or footer, both `price` and `cell` are `null`. Hover requires a prior draw, uses the painted column's own row geometry in media pixels, and excludes clipped rows and off-plot points. Replacing bars or options clears stale hit geometry.

The chart's data layer must contain matching bar timestamps for the footprint to align to its time scale. `setBars` clones input bars and cells and sorts each ladder high to low. `autoscaleInfo()` includes half a row above and below each occupied bucket, plus real candle high/low when enabled. Only `HorizontalProfile` returns `null` and never participates in autoscale. `DEFAULT_FOOTPRINT_OPTIONS`:

| Key | Default | Notes |
|---|---|---|
| `cellWidth` | *(unset)* | Preferred full column width in media px. Otherwise `barSpacing * widthFactor`; either is capped to the bar slot. |
| `widthFactor` | `0.9` | Fraction of the bar slot used for the column and candle gutter. |
| `tickSize` | *(unset)* | Effective row step override, already including any row multiplier. Otherwise uses each bar's `rowSize`, then the inferred minimum gap. |
| `font` | `10` | Media px. Text is hidden when the number cannot fit its cell. |
| `minTextHeight` / `textFade` | `11` / `4` | Fade numbers as rows shrink, without enlarging or overlapping the price rows. |
| `displayMode` | `'bidask'` | `FootprintDisplayMode` = `'bidask' \| 'imbalance' \| 'delta' \| 'deltaPct' \| 'volume' \| 'volumeDelta' \| 'deltaShadedVolume'`. `'imbalance'` fills only diagonal imbalances (stronger at 2x and 3x the ratio, full against zero or an untraded row) and shades and outlines the candle body's rows. `'deltaShadedVolume'` (since 2.6.4) prints the row volume on a cell coloured and shaded by the row's delta. |
| `intensityScope` | `'bar'` | `'visible'` shades against the busiest row on screen instead of each bar's. |
| `compactNumbers` | `true` | `false` prints whole numbers with separators instead of three significant figures. |
| `volumeDivisor` | `1` | Positive finite display divisor. Set to the configured lot size (for example `65`) to display lots. Scales cells and volume/delta statistics, but not percentages or trade counts. |
| `cellStyle` | `'heatmap'` | `FootprintCellStyle` = `'heatmap' \| 'profile' \| 'ladder'`: intensity cells, volume-proportional rows, or square cluster cells. |
| `textColorMode` | `'contrast'` | `FootprintTextColorMode` = `'contrast' \| 'side' \| 'delta' \| 'dominant' \| 'imbalance' \| 'volume'`. Independent of background display/style. |
| `textColor` | *(unset)* | Neutral text palette; otherwise derives readable ink from `theme.axisText`. |
| `buyTextColor` / `sellTextColor` | *(unset)* | Directional text palettes; otherwise use the corresponding buy/sell colors. |
| `imbalanceRatio` / `imbalanceThreshold` | `3` / `0` | Same comparison and dominant-quantity threshold as the exported analytics. |
| `stackedImbalances` | `3` | Bracket runs of N or more adjacent same-side imbalances. 0 disables. |
| `statsRows` | `[]` | Ordered `FootprintStatRow[]` for per-bar cards or the explicit legacy footer. Empty disables these stats by default. |
| `tableRows` | `[]` | Ordered `FootprintStatRow[]` for the separate bottom table. Empty disables it by default. |
| `tableLabelWidth` | `150` | Fixed table label-column width in media px, clipped to the pane width. |
| `statsRowHeight` | `15` | Media px. |
| `statsPosition` | `'bottom'` | Places `statsRows` in the footer or in `'bar'` cards. Cards can coexist with `tableRows` when enough space remains above the table. |
| `cvdOffset` | `0` | Cumulative delta before the first supplied bar. Maintain it when trimming a rolling window. |
| `showCandle` | `true` | Uses actual OHLC when available; legacy bars get a neutral range line. |
| `showPoc` / `pocStyle` / `pocColor` | `true` / `'marker'` / `#f0a020` | Marker or `'outline'` on the maximum-volume row. |
| `showValueArea` / `valueAreaPercent` | `false` / `0.7` | Contiguous volume area around the POC, shown with boundary lines. |
| `valueAreaColor` | *(unset)* | Falls back to `theme.axisText`. |
| `buyColor` / `sellColor` | *(unset)* | Background/candle palettes; fall back to `theme.upColor` / `theme.downColor`. |
| `imbalanceBuyColor` / `imbalanceSellColor` | *(unset)* | (since 2.6.4) Imbalanced cells, stacked brackets and stacked zones; fall back to the buy and sell colours. |
| `volumeColor` | *(unset)* | (since 2.6.4) Cells in the `'volume'` mode, which otherwise take the colour of the side that traded more. |
| `candleUpColor` / `candleDownColor` | *(unset)* | (since 2.6.4) The candle beside each column and the body rows `'imbalance'` shades; fall back to the buy and sell colours. |
| `profileAskColor` / `profileBidColor` | *(unset)* | (since 2.6.4) Bars of the visible-range profile; fall back to the buy and sell colours. |
| `sessionColor` / `tableBackground` | *(unset)* | (since 2.6.4) Session letters in the table and cards (fall back to `textColor`), and the table background (falls back to the chart background). Text stays readable against either. |
| `radius` | `2` | Heatmap cell corner radius, media px; profile and ladder cells are square. |
| `cvdReset` | `'none'` | `'session'` restarts `cvd` and `cumVolume` at each session open. |
| `sessionWindow` / `timezone` / `tpoMinutes` | *(unset)* / `'Asia/Kolkata'` / `30` | Session for letters and resets (a `SessionWindow`, local midnight when unset) and the letter period. Letters use the market profile's anchoring. |
| `multipleNodeBars` / `nodeColor` | `0` / `#e8c547` | Highlight the POC when this many consecutive bars share it. 0 disables; otherwise at least 2. |
| `bigOrderMultiple` / `bigOrderColor` | `0` / `#2ea8ff` | Outline a big limit order (largest bid near the low on a selling bar, largest ask near the high on a buying bar) of at least this many average cells. 0 disables. |
| `absorptionMultiple` / `absorptionColor` | `0` / `#a98bf0` | Band rows near an extreme where bid and ask both reach this many of their average cells. 0 disables. |
| `signalLookback` / `nearExtremeRows` | `10` / `3` | Bars for the average cell; rows from the high or low a big order or absorption must be within. |
| `flipBars` / `flipMinDeltaPct` | `0` / `8` | Triangle when delta turns after this many opposite bars, at a swing, large against the recent median. 0 disables. |
| `showZones` / `zoneEnd` / `zoneActiveAfter` | `false` / `'closeInside'` / `1` | Extend stacked imbalances, nodes and absorption right until `FootprintZoneEnd` (`'closeInside'`, `'traverse'`, `'touch'`) ends them; ended zones stay drawn. |
| `zoneKinds` | `['stacked', 'node', 'absorption']` | (since 2.6.4) `FootprintZoneGroup[]`: which zones `showZones` extends and `onZoneAlert` reports. Unknown or repeated kinds throw. |
| `zoneLookback` | `0` | (since 2.6.4) Zones start only in the newest this many bars; 0 takes every bar. |
| `showUnfinishedAuctions` / `auctionHighColor` / `auctionLowColor` | `false` / buy / sell | Dash-dot line on the outer edge of a high or low that traded on both bid and ask, until a later bar trades beyond it. Needs `bar.auction`. |
| `showDeltaLabels` / `markDivergence` / `divergenceColor` | `false` / `false` / `#f2a33a` | Bar delta under each column; boxed when an up bar has negative delta or a down bar positive. |
| `showVisibleProfile` / `profileWidth` | `false` / `100` | Ask and bid volume at price of the visible bars against the left edge, with row totals and the POC. |
| `lastPriceColor` | *(unset)* | Fill the newest bar's last-price row. |
| `showEmptyRows` | `true` | Draw a 0 x 0 row at every row step a bar's trades skipped, so the column spans its whole range. Display only: imbalances, the POC, value area, signals and hover on traded rows are unchanged. |
| `formingLastBar` | `true` | The newest bar cannot end a zone by its close, nor set an unfinished auction. |

Text modes select neutral ink, each displayed side, row-delta direction, only the larger same-row side, only a side with a diagonal flag, or a continuous quantity/peak blend. Single-number volume labels use total quantity and row delta for direction. Color contrast is corrected against the actual fill or plot background; labels crossing a profile edge receive an opaque backplate. Small rows additionally fade their text. The renderer uses the exported diagonal and stacked analytics, including the same explicit row size and threshold.

`FootprintBarStats` is `{ time, volume, bidVolume, askVolume, delta, minDelta, maxDelta, deltaPct, cvd, cumVolume, cvdRatio, session, trades, poc, vah, val }`. `session` is the letter (`'-'` when no letter row or session reset is in use). Side volumes sum actual cell quantities. `minDelta` and `maxDelta` use supplied trade-path metadata and remain `null` when it is absent; they are never inferred from final row deltas. `trades` is the supplied actual `tradeCount`, or `null` for legacy bars. Null metrics display as missing values rather than fabricated zeros. Stats recompute when bars or any option change. `cvd` starts at the offset and accumulates in supplied bar order. `compactVol(v)` preserves fractional quantities and formats to three significant figures with `K`/`M`/`B` suffixes (`compactVol(4_530_000) === '4.53M'`, `compactVol(0.125) === '0.125'`).

### Optional bottom statistics table

Both `statsRows` and `tableRows` default to `[]`, so a new footprint has no statistics table until the host opts in. `FootprintStatRow` supports `'delta' | 'minDelta' | 'maxDelta' | 'cvd' | 'askVolume' | 'bidVolume' | 'volume' | 'deltaPct' | 'trades' | 'cumVolume' | 'cvdRatio' | 'session'`. Rows must be known metric keys without duplicates; invalid selections throw before changing options. The caller controls row order and can disable the table at runtime.

`volumeDivisor` changes labels only: `stats()`, `hoverAt().stats`, input bars, POC/value area, imbalance thresholds and geometry keep raw units. A host should divide its own readouts by the same divisor. `setOptions({ volumeDivisor: 65 })` enables lots of 65; `setOptions({ volumeDivisor: 1 })` restores raw quantities. Fractional lots retain three significant figures. Invalid nonpositive or nonfinite divisors reject without changing the current options.

```ts
footprint.setOptions({
  tableRows: ['delta', 'minDelta', 'maxDelta', 'cvd', 'askVolume', 'bidVolume', 'volume'],
  tableLabelWidth: 150,
});
footprint.setOptions({ tableRows: [] }); // Disable the separate table.
```

| Table row key | Fixed label | Value |
|---|---|---|
| `delta` | Delta | Final bar ask volume minus bid volume. |
| `minDelta` | Min Delta | Lowest running trade delta within the bar, including initial zero; null without metadata. |
| `maxDelta` | Max Delta | Highest running trade delta within the bar, including initial zero; null without metadata. |
| `cvd` | Cumulative Delta | Running sum in supplied bar order, starting at `cvdOffset`. |
| `askVolume` | Total Ask Volume | Sum of `cell.askVol`. |
| `bidVolume` | Total Bid Volume | Sum of `cell.bidVol`. |
| `volume` | Total Volume | Total ask plus bid volume. |
| `cumVolume` | Cumulative Volume | Volume summed in supplied bar order, restarting per session with `cvdReset: 'session'`. |
| `cvdRatio` | Cum. Delta / Volume | `cvd / cumVolume`, three decimals. |
| `session` | Session Letter | The period letter, shaded alternately so a new letter stands out. |

The left label column stays fixed. Values follow the chart's actual bar centers and spacing, including panning, zooming and fractional display scaling. Volume totals have no leading plus sign; delta metrics are signed. Table hover returns the aligned bar's statistics with `price` and `cell` null. Labels are not interactive, and values that cannot fit their visible slot are omitted.

Restore the previous footer metrics explicitly with `statsRows: ['volume', 'delta', 'deltaPct', 'cvd']` and `statsPosition: 'bottom'`. When `tableRows` is nonempty it selects the footer rows instead. For cards plus a table, set `statsPosition: 'bar'`, populate `statsRows`, and configure `tableRows` independently.

The bottom table reserves pane space and clips cells above it. Cards appear only when they fit entirely above the table. A tall statistics list on a short pane can leave no room for the ladder; select fewer rows, use cards without a table, or enlarge the pane. All drawing is clipped to the plot, and changing row selections clears stale table/card hit geometry.

### Order flow signals

`footprintSignals(bars, options?: Partial<FootprintSignalOptions>)` is the pure calculation behind the layers, defaults in `DEFAULT_FOOTPRINT_SIGNAL_OPTIONS` (signals on: nodes 2, big orders 3, absorption 2, flips 2, lookback 10, near rows 3, `zoneEnd: 'closeInside'`, `zoneActiveAfter: 1`, `formingLastBar: true`). It returns `FootprintSignals` = `{ bars: FootprintBarSignals[], zones: FootprintZone[], auctions: FootprintAuction[] }`. `FootprintBarSignals` is `{ time, node, bigBid, bigAsk, absorption, flip, divergence }` (row prices, `{ low, high }` spans, `flip` of -1, 0 or 1). `FootprintZone` is `{ kind: FootprintZoneKind, time, low, high, endTime, activeTime, touchTime }`, `kind` being `'stackedBuy' \| 'stackedSell' \| 'node' \| 'absorption'`, spans at the outer row edges; `touchTime` (since 2.6.4) is the first bar after `activeTime` whose high to low range reaches the zone (a bar that jumps across it counts, as it would trigger a stop there), which can be the bar that ends it. `zoneLookback` (since 2.6.4, default 0 for every bar) starts zones only in the newest N bars. `FootprintAuction` is `{ time, side: 'high' \| 'low', price, endTime }`. `footprint.signals()` returns the same for a primitive's bars and options; since 2.6.4 `footprint.onZoneAlert(handler)` reports each zone `showZones` extends (of the `zoneKinds`) once, as `FootprintZoneAlert` = `{ zone, time }`, when a bar's range comes back to it after it became active, and returns the unsubscribe; nothing is reported while `showZones` is off. The first bars a footprint is given, and new zones that `setOptions` creates, are recorded without a report. Each later `setBars` is read as the live tail: a touch in the bar that was newest at the previous call, or in any later bar, is reported, so prints batched across a new bar lose nothing. `setBars([])`, or bars whose newest is older than the previous newest (another instrument), begin a new history. The engine plays no sound: a host does that in the handler. Invalid options throw (`multipleNodeBars` of 1, an unknown `zoneEnd`, a `signalLookback` or `nearExtremeRows` that is not positive, a negative `zoneLookback`).

### `FOOTPRINT_THEMES` (since 2.6.4)

`FOOTPRINT_THEMES` holds six frozen colour sets; `FootprintThemeName` is `'ocean' \| 'ember' \| 'forest' \| 'neon' \| 'monochrome' \| 'daylight'`. Each is a `FootprintThemeColors`, a plain options patch of 20 colours (buy, sell, volume, candle up and down, text, both imbalance colours, last price, POC, node, divergence, big order, absorption, both auction colours, both profile colours, session letters and the table background), so a host spreads it under its own choices: `new Footprint({ ...FOOTPRINT_THEMES.ocean, displayMode: 'bidask' })`. Daylight suits a light chart and the others a dark one; a theme never sets the chart background.

### `FootprintAggregator` (the live path)

`new FootprintAggregator(tf: TickTimeframe, tickSize: number, rowTicks = 1, options?: FootprintBuildOptions)`. Count and volume bars close on every print, filtered or not. `TickTimeframe` (from `src/feed/tick-aggregator.ts`) is `{ mode: 'interval'; seconds; anchorSec? } | { mode: 'ticks'; count } | { mode: 'volume'; perBar }`. `onTick(tick: FootprintTick)` returns `FootprintUpdate` = `{ bar, isNew }`: push when `isNew`, otherwise replace the last element. `FootprintTick` is `ClassifiedTrade & { time: number }`; `current()` returns the forming bar or `null` before the first tick.

**The boundary is evaluated before the incoming tick is applied.** With increasing timestamps, a count limit of 100 retains exactly 100 records in the old bar; record 101 starts the next one. Volume bars keep each trade whole, so the last trade can overshoot the target. Count and volume bars coalesce ticks sharing their opening timestamp until time advances, even when that exceeds the target, avoiding duplicate chart time keys. Intervals use the anchored time bucket. No timer closes a bar or synthesizes an empty interval without a tick.

**Live timestamps must be nondecreasing.** Older ticks throw before changing the forming bar, including older ticks inside the same interval. Invalid configuration and trade records also throw before mutation. The aggregator copies its timeframe configuration. Every `onTick` and `current()` snapshot clones all cells, so a later tick cannot alter earlier returned snapshots and caller edits cannot corrupt the live accumulator.

## `HorizontalProfile` (generic)

```ts
chart.addPrimitive(new HorizontalProfile({
  buckets: levels,   // ProfileLevel[] = { price, value }[]
  poc, vah, val, width: 150, side: 'right', barColor: '#3b5168', vaColor: '#4a6fa5',
}));
```

`HorizontalProfileOptions` has no defaults object, every key is required. `setData(opts)` replaces the whole option object; there is no `setOptions` patch. `autoscaleInfo()` returns `null`, so it never drives the price range. Row height comes from `plotHeight / buckets.length`, not from a tick size, so rows always fill the pane.

Use it for a price-keyed distribution the built-ins do not model, delivery volume at price, open interest at strike, a broker-supplied profile, or `computeTpo` output drawn as a plain histogram rather than letters. Use `VolumeProfile` or `MarketProfile` for anything they already compute: they handle multiple sessions, tick-accurate row height, value-area dimming and hit-testing, none of which `HorizontalProfile` does.

## Known gaps (verified against current source)

- **The profile overlays are the ones that ignore the theme.** `VolumeProfile`, `MarketProfile` and `HorizontalProfile` never touch `rc.theme`; their defaults are fixed hexes tuned for a dark background and look wrong on `lightTheme` until you pass explicit colours. Only `Footprint` adapts.
- `VolumeProfile` has no `hitTest`, `hoverAt` or `options()`, `MarketProfile` and `Footprint` have all three.
- `HorizontalProfile` has no `setOptions` and hardcodes its POC (`#f0a020`) and VA line (`#5a6b8c`) colours.
- Only `FootprintAggregator` is incremental. Volume and market profiles are full recomputes; on live bars call the compute again and hand the result to `setData`.

## Worked examples

### Volume profile over the visible range

```ts
import { computeVolumeProfileSessions, VolumeProfile } from 'openalgo-charts/profile';

chart.addSeries('candlestick').setData(bars);
const profile = new VolumeProfile(null, { displayMode: 'buySell', width: 110 });
chart.addPrimitive(profile);

const refresh = (p: unknown): void => {
  const { logicalFrom, logicalTo } = p as { logicalFrom: number; logicalTo: number };
  const slice = bars.slice(Math.max(0, Math.floor(logicalFrom)), Math.ceil(logicalTo) + 1);
  profile.setData(computeVolumeProfileSessions(slice, { tickSize: 1, session: 'composite' }));
};
chart.on('pan', refresh);
chart.on('zoom', refresh);
chart.fitContent();
```

`'pan'` and `'zoom'` both carry `{ from, to, logicalFrom, logicalTo }`. See [events-and-state](events-and-state.md).

### Market profile for one Indian cash session

```ts
import { computeMarketProfile, MarketProfile, TRADING_HOURS, rowTicksFor } from 'openalgo-charts/profile';

const result = computeMarketProfile(oneMinuteBars, {
  tickSize: 0.05,
  rowTicks: rowTicksFor(1, 0.05),   // 1-point rows
  session: 'day',
  blockMinutes: 30,
  window: TRADING_HOURS['india'],   // 09:15-15:30 IST, letters anchored to the open
  tailEdges: 3,
});

const mp = new MarketProfile(result, { showDayType: true, showTails: true });
chart.addPrimitive(mp);

chart.on('crosshair:move', (e) => {
  const p = (e as { point?: { x: number; y: number } }).point;
  const hit = p ? mp.hoverAt(p.x, p.y) : null;
  tooltip.textContent = hit ? `${hit.level.letters}, ${hit.level.count} TPO @ ${hit.price}` : '';
});
```

### Footprint from a live classified tick stream

```ts
import { Footprint, FootprintAggregator, type FootprintBar } from 'openalgo-charts/profile';

const TICK = 0.05;
const footprint = new Footprint({ tickSize: TICK, statsRows: ['volume', 'delta', 'cvd'] });
chart.addPrimitive(footprint);

const agg = new FootprintAggregator({ mode: 'interval', seconds: 60, anchorSec: 0 }, TICK);
const bars: FootprintBar[] = [];
let cvdOffset = 0;

ws.onTrade((t) => {
  // `atBid` must come from the feed's own classification, never a price guess.
  const { bar, isNew } = agg.onTick({ time: t.timeSec, price: t.price, qty: t.qty, side: t.atBid ? 'bid' : 'ask' });
  if (isNew) bars.push(bar); else bars[bars.length - 1] = bar;
  if (bars.length > 40) {
    cvdOffset += bars.shift()!.delta;
    footprint.setOptions({ cvdOffset });
  }
  // Update the chart series with the same bar timestamp and actual OHLC too.
  footprint.setBars(bars);
});
```

Full host wiring (tooltip, controls, synthetic tape) is in `examples/orderflow/index.html` and `examples/market-profile/index.html`; minimal versions in `examples/phase11-profiles.html`.

Related: [primitives-and-plugins](primitives-and-plugins.md), [feeds-and-live](feeds-and-live.md), [data-and-time](data-and-time.md), [bundling-and-tiers](bundling-and-tiers.md), [pitfalls](pitfalls.md).
