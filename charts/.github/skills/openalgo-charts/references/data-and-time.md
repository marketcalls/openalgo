# Data and time

`Instrument` validates and freezes `InstrumentMetadata`, including an
`InstrumentCalendar` and optional OI capability. Its `supportsInterval` uses exact
provider tokens, `formatPrice` formats without changing data, `sessionAt` returns
an `InstrumentSession` (UTC open/close and local opening date), and `applyTo` applies
timezone, tick, primary price formatting and source context after source guards.
Date exceptions replace weekly sessions; overnight windows belong to their opening
date. Crypto can use `0000-0000`. Optional `tickBands` (`TickBand[]`) declare a
price-dependent tick; `instrument.tickSchedule` is the validated `TickSchedule`,
or null for a constant tick (one rule, `priceTick`, everywhere). With bands,
`priceTick` must equal the schedule's `minMove`, the common grid of every band, and
that is the `minMove` `applyTo` gives the price scale. `applyTo` also hands the
schedule to the chart (`chart.setTickSchedule`, read with `chart.tickSchedule()`),
which rounds dragged price alerts and `chart.snapPrice` on the price pane by band,
and to `chart.trading` (a layer built later starts from it, and a constant-tick
instrument clears it on a symbol switch); call `chart.setTickSchedule` after
`applyTo` to override it for the alerts and the order lines together. See [instrument rules](../../../../docs/instruments.md)
for breaks, DST, validation, quantity units and safe host source transitions.

`sessionFrom(t)` returns the window active at `t`, or else the next one to open
(about a year of lookahead, null when nothing opens). `SessionCalendar` is the same
hours without price or quantity rules: `new SessionCalendar({ timezone, sessions,
exceptions })` (a `SessionCalendarSpec`) validates, detaches and freezes like an
instrument's calendar, throws `Invalid session calendar: ...`, and reads with
`sessionAt` and `sessionFrom`. Either one, or any object with `sessionFrom`, is a
`SessionCalendarSource` for `chart.setSessionCalendar(calendar)`, which sets the
hours and repaints every pane, so a drawing already past the last bar moves to the
time it now means (`null` clears). `calendar.applyTo(chart)` on a `SessionCalendar`
and `Instrument.applyTo` both go through it. `chart.dataLayer.setSessionCalendar(calendar)`
sets the same and asks for no frame, for a host about to load bars or move the view
anyway; read either back with the `chart.dataLayer.sessionCalendar` getter. An
instrument's hours are dropped when the chart's data context moves to another symbol
or exchange; hours a host set itself stay until it replaces them.
See [times past the last bar](#times-past-the-last-bar) for what it changes.

`InstrumentCalendar` (and `SessionCalendarSpec`) also take optional `preMarketMinutes`
and `postMarketMinutes`, whole minutes 0 to 1439 counted back from each trading date's
first regular opening and on from its last close, so a shortened day, a special session
and a closed date move them, and `extendedHours`, windows written like `sessions` for
hours of their own such as an overnight `'2000-0400:12345'` (none on a date the
exceptions close). `phaseAt(t)` on an `Instrument` or `SessionCalendar` returns a
`SessionPhase`: `'pre'`, `'regular'`, `'post'`, `'extended'`, `'closed'` or `'holiday'`
(a date an exception closes although its weekly sessions would open, midnight to
midnight in the calendar's zone); overlaps resolve regular, then pre, post, extended.
`phaseSpans(from, to)` returns consecutive `SessionPhaseSpan` objects
(`{ phase, start, end }`, UTC seconds, end exclusive) over at most 400 days.
`marketStatusAt(t)` returns a `MarketStatus` (`phase`, `changesAt`, `nextPhase`,
`opensAt`, `closesAt`, null past a 14-day horizon); the free `marketStatusAt(source, t)`
does the same for any `SessionPhaseSource`, such as `chart.dataLayer.sessionCalendar` (a
`SessionCalendarSource` may now carry an optional `phaseSpans`), and returns null when
there is none. `calendarMarketPhase(source)` is the `MarketPhaseFn` that `PriceLevels`
takes for its extended-hours levels. Boundaries resolve per date in the calendar's IANA
zone; nothing changes for a calendar without these fields. A window whose boundary a
daylight-saving change removes throws on that date, as `sessionAt` does; `phaseAt` then
throws from the day before to two days after it and a status from about fifteen days
before to four after, so a readout on a timer catches it. `attachSessionShading` shades
these phases on the chart: see [primitives-and-plugins](primitives-and-plugins.md).

`OpenAlgoConfig.hasOpenInterest(request)` optionally supplies instrument
capability to the REST adapter. Explicit false removes the API's placeholder
OI column before caching or calculation. True/undefined preserves finite
observations, including zero. `mapHistoryResponse(response, hasOpenInterest?)`
accepts the same flag. Metadata is captured for the request before awaiting
its response; do not infer capability from observed zero or missing values.

*When to read this: you are shaping bars for a series, wiring history paging, formatting the time axis, or explaining why bars moved, merged, or vanished.*

## The Bar shape

`src/model/bar.ts` is the only data contract. Everything a series accepts normalizes to `Bar` via `toBar`.

| Field | Type | Notes |
|---|---|---|
| `time` | `UTCSeconds` (`number`) | Integer UTC seconds. Required. |
| `open` `high` `low` `close` | `number` | Required on a `Bar`. |
| `volume` | `number?` | Optional; not all feeds carry it. |
| `oi` | `number?` | Optional open-interest level. Zero is a reading; missing is not zero. Historical folds take the latest defined level within the bucket, never a sum. |
| `color` | `string?` | Per-bar override honoured by renderers that support it (histogram, column). |

**Bar times are UTC seconds, never milliseconds and never `Date`.** `UTCSeconds` is a bare `number`, so a millisecond timestamp compiles fine and then places the bar ~50,000 years in the future, which silently destroys the shared axis. Convert at the feed edge with `epochMsToUtcSeconds` (`src/feed/time.ts`).

```ts
import type { Bar } from 'openalgo-charts';

const bar: Bar = { time: 1700000000, open: 100, high: 102, low: 99.5, close: 101, volume: 12000 };
```

Open interest belongs to the bar's timestamp. `mergeBars` and `securitySeries`
retain the latest defined reading in each bucket and leave an entirely missing
bucket absent. Heikin Ashi retains it; price-generated and expression bars omit
it. `Tick.oi` and `AggTick.oi` replace the current level. A tick without a finite
reading clears it from the forming bar, including a history-seeded bar. The
current quote feed does not supply open interest, so that live gap is expected.
Partial replay uses only revealed sub-bar readings. See [open-interest data](../../../../docs/open-interest.md).

## Three item shapes, one internal bar

`SeriesDataItem = Bar | LinePoint | Whitespace`. `toBar` normalizes:

| Input | Becomes |
|---|---|
| `{ time, open, high, low, close, volume?, color? }` | passes through untouched |
| `LinePoint` `{ time, value, color? }` | flat OHLC bar (`open = high = low = close = value`) |
| `Whitespace` `{ time }` | `open/high/low/close = NaN` |

`isWhitespace(p)` returns true when the item has neither `open` nor `value`. A whitespace point claims a logical index so panes stay aligned, but the line renderer draws a gap there and autoscale skips it. Use whitespace to reserve future sessions or to punch a hole in one series while others keep drawing.

```ts
series.setData([
  { time: 1700000000, value: 101 },   // LinePoint
  { time: 1700000060 },               // Whitespace, index reserved, nothing drawn
  { time: 1700000120, value: 103 },
]);
```

## setData vs update vs prependData

`SeriesApi` (`src/model/series.ts`) exposes exactly these write paths:

| Method | Data effect | Viewport effect |
|---|---|---|
| `setData(items)` | Full replace of this series. Sorted ascending, duplicate times collapsed **last-wins**. | Fits the preferred initial view once after non-empty data and usable layout width (`_hasFitContent`). Later calls leave the logical range alone. |
| `update(item)` | Upsert one item: newer time appends, equal time replaces the last bar, older time replaces or inserts. | Appends auto-scroll only when the viewport was already at the right edge; otherwise `rightOffset` is decremented so visible bars do not shift. |
| `prependData(items)` | Upsert-merge by time (`DataLayer.addBars`), existing times replaced, new times inserted, result stays sorted. | Preserved. `baseIndex` shifts by the inserted count and `rightEdge - index` is invariant. |
| `getData()` | Read back the normalized `Bar[]`, oldest to newest. | None. Allocates a fresh array each call. |

**A second `setData` does not refit the chart.** The initial view uses `navigation.defaultVisibleBars` once layout has a usable width. After a timeframe or symbol switch, call `chart.resetScale()` to adopt that preferred window, or `chart.fitContent()` to explicitly fit all loaded history. Apply an explicit saved viewport after data instead when the host owns the view. Otherwise the old logical range is reapplied to a different bar count.

```ts
const series = chart.addSeries('candlestick');
series.setData(bars);          // fits once
series.update(liveBar);        // hot path, per tick
series.prependData(olderBars); // history paging, viewport preserved
```

## The shared logical-index model

One `DataLayer` per chart (`src/model/data-layer.ts`). Every distinct time across **all** series is merged into a sorted array and assigned a logical index `0..N-1`. Series rows are addressed by that shared index, which is what keeps price, volume and indicator panes aligned and what collapses non-trading gaps: an absent time simply has no index.

Consequences you must design around:

- **One bar per time, per series, is an invariant.** Times map through a `Set`, so two bars sharing a time resolve to the same x and draw on top of each other. `setData` collapses duplicates keeping the last occurrence in the caller's array (`Array#sort` is stable); `addBars`/`prependData` upsert through a `Map`, so incoming bars win.
- **Reconnect overlap is safe.** Re-fetch a window that overlaps what you already have and hand it to `prependData`, the merge dedupes by time. No gap arithmetic needed.
- **Logical indices are not stable across a prepend.** Anything you cached as an index is wrong afterwards. Cache times, not indices.
- **The axis is gapless, so most x positions have no bar behind them.** `indexToTime(i)` answers only for whole indices that have a bar; `indexToTimeFloat(i)` interpolates between bars and extrapolates past either edge (see below), and `timeToIndexFloat(t)` is its exact inverse. Both return `NaN` with no data. `chart.coordinateToTime(x)` / `chart.timeToCoordinate(time)` wrap them.
- `visibleBars(id, from, to)` binary-searches into the window, so a repaint costs `O(log n + visible)`, not `O(total)`. Prefer it over scanning `seriesBars(id)` (which returns the live array, treat as read-only).

`DataLayer.update` classifies each live bar and returns the kind, which is what drives the auto-scroll decision:

| Kind | When |
|---|---|
| `'append'` | Newer than this series' last bar **and** newer than every time on the shared axis. |
| `'replace'` | Same time as the last bar (intra-bar tick), or any existing time. |
| `'insert'` | An older time that does not exist yet (late / out-of-order arrival). |

### Times past the last bar

Whole indices right of the last bar are the bar times still to come; drawing anchors, study shapes and linked viewports placed there all go through them.

- **With a session calendar** (`chart.setSessionCalendar(calendar)`, `calendar.applyTo(chart)` for a `SessionCalendar`, `Instrument.applyTo` for an instrument, or `chart.dataLayer.setSessionCalendar(calendar)` where a repaint follows anyway), the bar after a session's last one is the next session's first: Friday's 15:25 is followed by Monday's 09:15, a closed date is skipped, a shortened day ends early and a lunch break is stepped over. Intraday bars keep, in each window, the offset the feed's bars keep from that window's opening, read from the recent bars in windows opening at the same time of day: hourly bars on the clock stay on the clock at a 09:00 morning opening and at 12:00 before a 12:30 afternoon one, and hourly bars stamped 09:00 against a 09:15 open stay on the hour. A window no recent bar sat in (a special session, or an opening a daylight-saving change moved) takes the last bar's offset. Daily bars step through trading dates at the last bar's offset from its opening; weekly and longer bars use the median below.
- **Without one**, or when the last 64 bars do not sit in its sessions (regular hours against extended-hours data), the axis continues at the lower median of the last 64 bar intervals. Never at the last gap alone: that is the gap most likely to be a night or a weekend. Bars that happen to sit inside hours that are not theirs cannot show it, which is why an instrument's hours leave with its symbol. Left of the first bar the spacing is the first gap.
- A position between two future bar times interpolates across the closed hours between them, as it does between two loaded bars, and converts back exactly. A calendar that throws (a window in a daylight-saving gap) falls back to the median; it never stops the paint.
- Generation is lazy and bounded: past 4096 future bars or 512 calendar reads the axis continues at the average pace already generated, so an anchor years ahead stays cheap.
- Stored drawings keep their times. A host with no calendar still gets the median, which removes the weekend-sized spacing on its own.

## Infinite history paging

```ts
let oldest = bars[0].time;

chart.setHistoryLoader(async () => {
  try {
    const older = await api.barsBefore(oldest, 500);
    if (!chart.isDestroyed && older.length > 0) {
      series.prependData(older);
      oldest = older[0].time;
    }
  } catch (error) {
    if (!chart.isDestroyed) showHistoryError(error); // host error UI
  } finally {
    if (!chart.isDestroyed) chart.historyLoadComplete();
  }
});
```

The loader fires from `_maybeLoadHistory` whenever the visible logical range's `from` drops below 10, during a drag, a wheel zoom, or a kinetic glide. A latch (`_loadingHistory`) suppresses re-entry until you call `historyLoadComplete()`.

**`historyLoadComplete()` is mandatory on every current invocation, including empty history and failure.** Put completion in `finally`; skipping it leaves the latch set and paging never fires again. The short example assumes one stable chart and symbol. In a terminal, guard stale responses, replay and request ownership before applying a page or releasing the latch, as described in [host-integration](host-integration.md#history-paging-and-replay).

The same trigger also emits the observable `lazy-load` event (`{ from, to, direction: 'backward' }`), see [events-and-state](events-and-state.md). Only `'backward'` is ever emitted.

## Timezone

Internal time is UTC seconds. What the chart *labels* it in is `ChartOptions.timezone`, an IANA name that **defaults to `Asia/Kolkata`**. IST is the default, not a property of the engine: any zone the runtime recognises works, and daylight saving is followed rather than approximated because the name is resolved per instant.

```ts
import { createChart } from 'openalgo-charts';

const chart = createChart(el, { timezone: 'America/New_York' });

chart.timezone();                        // 'America/New_York'
chart.setTimezone('Europe/London');      // relabels and recomputes on the next frame
chart.applyOptions({ timezone: 'UTC' }); // same thing through the options path
```

| API | Contract |
|---|---|
| `ChartOptions.timezone` | IANA name. Default `'Asia/Kolkata'`. **Throws** on a name the runtime does not recognise. |
| `chart.timezone()` | The resolved zone. |
| `chart.setTimezone(zone)` | Relabels *and* recomputes every calendar-anchored indicator. No-ops when the zone is unchanged. Throws on an unknown name. |
| `chart.applyOptions({ timezone })` | Same as `setTimezone`. |
| `getState()` / `restoreState()` | The zone rides in the payload. A saved zone the runtime does not recognise is **skipped**, not thrown, so one stale name cannot cost a whole layout. |
| `applyChartSettings(chart, { 'time.timezone': zone })` | The settings schema's own control, on the Axes tab, so a dialog does not need a zone row of its own. An invalid name is skipped here too, rather than throwing away the rest of the patch. See [settings-and-menus](settings-and-menus.md). |

What the zone drives:

- Time-axis tick labels, **including which tick escalates** to a day, month or year mark: a New York chart escalates at New York's midnight, not at IST's.
- The crosshair time tag.
- Every calendar-anchored indicator: `vwap` (`session`, `week`, `month`, `quarter`, `year` anchors), `twap`, `cpr` (weekly and monthly frames), `seasonality` (which month a close is counted in). See [indicators](indicators.md).

What it does **not** drive: `SessionWindow` in the profile tier carries its own zone, so a preset selects the same real instants on any display. See [profiles-and-orderflow](profiles-and-orderflow.md).

**An explicit `timeFormatter` outranks the zone.** A host that formats its own labels has settled the question; the formatter receives raw UTC seconds either way.

```ts
// Pick the zone from the instrument, so switching symbol switches the clock.
const ZONES: Record<string, string> = {
  NSE: 'Asia/Kolkata', BSE: 'Asia/Kolkata', NFO: 'Asia/Kolkata',
  NASDAQ: 'America/New_York', NYSE: 'America/New_York',
  LSE: 'Europe/London', TSE: 'Asia/Tokyo',
};

function loadSymbol(exchange: string, bars: readonly Bar[]): void {
  chart.setTimezone(ZONES[exchange] ?? 'UTC');   // before or after setData, either way
  series.setData(bars);
}
```

**The default costs nothing extra.** On `Asia/Kolkata` the engine keeps its original fixed-offset arithmetic and never reaches `Intl`, so labels are byte-identical to pre-1.3.0 output and independent of the host's ICU build. A named zone goes through a per-zone `Intl.DateTimeFormat` memoised by UTC second, so a pan resolves each visible tick once, not once per frame.

## Time helpers

Two families, both exported from the package root (`src/feed/time.ts`). The IST family is the fixed-offset special case and is unchanged; the zoned family is the general one, every function taking `zone` as a trailing argument defaulting to `DEFAULT_TIMEZONE`.

| Function | Purpose |
|---|---|
| `epochMsToUtcSeconds(ms)` | `Math.floor(ms / 1000)`. Zone-free. |
| `IST_OFFSET_SECONDS` | `19800` (5h30m). |
| `istStringToUtcSeconds(s)` | Parses `YYYY-MM-DD`, `YYYY-MM-DD HH:MM[:SS]`, and the `T`-separated variant as IST wall clock. Locale-independent; throws on an unparseable string. |
| `utcSecondsToIstParts(s)` | `{ year, month (1-12), day, hour, minute, second, weekday (0=Sun) }`. |
| `utcSecondsToIstDateString(s)` | `YYYY-MM-DD`, the form OpenAlgo history requests need. |
| `formatIstTime(s)` / `formatIstTimeSeconds(s)` | `HH:MM` / `HH:MM:SS`. |
| `formatIstDate(s)` | `DD Mon`. |
| `isNewIstDay(a, b)` | True when two instants fall on different IST calendar days. |

| Zoned function | Purpose |
|---|---|
| `DEFAULT_TIMEZONE` | `'Asia/Kolkata'`. |
| `isValidTimezone(zone)` | True when the runtime resolves the name. Use it to validate before `setTimezone` if you do not want the throw. |
| `utcSecondsToZonedParts(s, zone?)` | `ZonedParts` (same shape as `IstParts`). |
| `utcSecondsToZonedDateString(s, zone?)` | `YYYY-MM-DD` in the zone. |
| `zonedStringToUtcSeconds(str, zone?)` | Wall-clock string in the zone to UTC seconds. |
| `zonedWallClockToUtcSeconds(y, m, d, h?, min?, sec?, zone?)` | Wall-clock components to UTC seconds. Two-pass, so a changeover day resolves to the offset in force at the answer. |
| `zoneOffsetSeconds(s, zone?)` | The zone's offset **at that instant**. |
| `zonedDayIndex(s, zone?)` / `zonedWeekIndex(s, zone?)` | Calendar day / Monday-week index. Cheaper than a midnight timestamp and immune to a 169-hour DST week. |
| `startOfZonedDay/Week/Month(s, zone?)` | UTC seconds of the local midnight opening that period. |
| `isNewZonedDay/Week/Month/Quarter/Year(a, b, zone?)` | Boundary tests. |
| `isNewZonedPeriod(a, b, period, zone?)` | The same, with `ZonedPeriod = 'day' \| 'week' \| 'month' \| 'quarter' \| 'year'`. |
| `formatZonedTime/TimeSeconds/Date(s, zone?)` | `HH:MM` / `HH:MM:SS` / `DD Mon`. |
| `formatZonedCrosshairLabel(s, zone?)` | The crosshair tag form, e.g. `Wed 05 Jun '24 09:30`. |

## Custom time formatting

A formatter replaces the zone-aware labeller outright, for both the axis ticks and the crosshair pill:

```ts
const chart = createChart(el, {
  timeFormatter: (utcSeconds, tickMark) =>
    tickMark === 'day' || tickMark === 'month' || tickMark === 'year'
      ? new Date(utcSeconds * 1000).toISOString().slice(0, 10)
      : new Date(utcSeconds * 1000).toISOString().slice(11, 19),
});
```

`tickMark: TickMarkType` is `'year' | 'month' | 'day' | 'time' | 'timeWithSeconds'`. The axis computes it by comparing each tick against the previous one **in the chart's zone**, and picks `timeWithSeconds` when the label step is under 60 seconds. The first visible tick is always `'day'`. Pass `undefined` to `setTimeFormatter` to go back to the built-in labels in the chart's zone.

**A `timeFormatter` overrides labels only, never the calendar.** Session anchors and pivot frames still resolve on `chart.timezone()`, so a formatter that renders New York hours on a chart left at `Asia/Kolkata` puts a VWAP restart in the middle of the drawn day. Set the zone as well.

## Where the time axis puts a label

Two kinds of position, since 1.8.5:

- **The regular grid**, roughly every 80 px, which is what carries the clock readings.
- **The first bar of every new day**, whether or not it lands on that grid.

The second exists because labels used to be placed only on the grid. When a new session had fewer bars than the grid stride, no tick fell inside it and the date was never drawn at all: today's bars sat under yesterday's date with nothing marking the change, which is exactly what a chart looks like a few minutes after the open. Forcing the mark is also why a professional terminal prints "Sep" between two hourly labels rather than on the hour.

Labels are then resolved by priority and drawn left to right. A boundary date outranks the grid tick beside it, because losing "Sep" to a 10:00 its neighbours already imply is the failure the forced mark exists to prevent. Two boundaries still check each other, so zoomed far out they do not print through one another.

A `timeFormatter` sees the boundary as `tickMark: 'day'` (or `'month'` / `'year'`), so a host formatter gets the same treatment without changing.

## Tick, volume and calendar bars

`TickBarAggregator` (`src/feed/tick-aggregator.ts`) builds bars from raw trade ticks on any `Bucketing` rule:

```ts
import { TickBarAggregator } from 'openalgo-charts';

const agg = new TickBarAggregator({ mode: 'ticks', count: 100 });
// { mode: 'volume', perBar: 5000 }
// { mode: 'interval', seconds: 30, anchorSec: sessionOpenUtc }
// { mode: 'calendar', unit: 'month' }, with { timezone: 'America/New_York' } as the option

ws.onTrade((t) => {
  const u = agg.onTick({ time: t.timeSec, price: t.price, qty: t.qty });
  series.update(u.bar);   // isNew === true on a boundary
});
```

`onTick` always returns a `BarUpdate` (never null). Bar time is the bucket start in `interval` and `calendar` mode, and the **first tick's time** in `ticks` / `volume` mode.

The four cases are the `Bucketing` union from the interval registry, and `TickTimeframe` still names exactly the three time-agnostic ones. `new TickBarAggregator(bucketing, { timezone })` supplies the zone a calendar bucket resolves in when the rule did not pin its own: a month opens at local midnight on the first, and which instant that is depends on the exchange. See [feeds-and-live](feeds-and-live.md#the-interval-registry).

**Tick and volume bars can collide on time.** Two consecutive count-bars whose first ticks land in the same second get the same `time`, and the DataLayer collapses them last-wins, one bar disappears. If your feed timestamps at second resolution, carry your own monotonic time when building tick bars.

**Tick and volume bars require real trade ticks.** OHLCV history cannot be re-bucketed into them.

For interval bars built from an LTP/quote stream, use `CandleBuilder` instead, see [feeds-and-live](feeds-and-live.md).

## Level of detail (`conflate`)

On by default. Once bars are narrower than the stick a candle is drawn with, the series pass stops drawing one mark per bar and draws one per device-pixel column instead, so a frame costs the plot's width rather than the number of bars in view: 200,000 bars fitted into a 944 px plot paint about 2,900 marks with candles and volume, against 400,000 bar by bar (`node scripts/bench-pane.mjs`).

```ts
// Let the view zoom out past one bar per CSS px; the level of detail keeps it cheap.
const chart = createChart(el, { timeScale: { minBarSpacing: 0.01 } });
// Opt out: every bar drawn at every zoom.
const every = createChart(el, { conflate: false });
```

| Option | Default | Effect |
|---|---|---|
| `conflate` | `true` | Draw per column below the threshold; `false` draws every bar. |
| `conflationFactor` | `1` | Column width in sticks; `2` to `4` merge sooner into wider, coarser columns. |

- **Threshold.** A candle's column is one stick wide, `max(1, floor(dpr))` device px, times the factor; a line's or a histogram's is one device pixel times the factor. The level of detail engages for every series at once when `barSpacing * dpr` is under a candle's column, which at the default factor is under one CSS px at a whole pixel ratio. At or above it every bar has a column of its own and the frame is exactly what it was without the option. The default time scale floor (`minBarSpacing: 1`) never goes below it, so a chart that keeps the floor draws as before.
- **Candles, OHLC bars and high-low bars** merge each column into one stick: open from the first bar, close from the last, high and low the column's extremes, volume summed, open interest the last reading, and the colour overrides of the bar that closed the column. Never averaged. The sticks sit on the column grid and tile without overlap; a column holding only whitespace draws nothing.
- **The HLC area** keeps what lines keep plus each run's highest high and lowest low, with one gap bar per gap, so its close line, band edges and gaps match the full frame.
- **Lines, steps, areas and baselines** keep real bars: the first, lowest, highest and last of each unbroken run in a column, which cover the pixels the full line covers. A gap stays a gap, kept as one whitespace bar.
- **Columns and histograms** keep each column's lowest and highest bar, drawn from the base, which cover what every bar in it would.
- **Any other renderer** (a host's `registerChartType` renderer, even one registered under a built-in name, Point and Figure, Kagi) is drawn in full: it may read fields or neighbours a merge cannot know about.

It is a render-time step only: the DataLayer, `getData()`, indicators, autoscale and the crosshair readout all see every bar.

The fixed-size helpers are exported for a host that downsamples bars itself: `conflationGroupSize(barSpacing, dpr, minPx = 0.5, factor = 1)` returns `1` while `barSpacing * dpr >= minPx * max(1, factor)`, otherwise `ceil(threshold / widthPx)`; `conflateBars(bars, groupSize)` and `mergeBars(group)` merge fixed groups the same OHLC-preserving way (the merged bar takes the **first** bar's time), and `conflateItems` places x at the group centre. The pane does not use them.

## Related

- [feeds-and-live](feeds-and-live.md), `DataFeed`, the OpenAlgo adapters, `CandleBuilder`.
- [events-and-state](events-and-state.md), `lazy-load`, `pan`/`zoom`, saved layouts.
- [core-api](core-api.md), `createChart`, `addSeries`, viewport methods.
- [scales-and-panes](scales-and-panes.md), logical range, bar spacing, price scales.
- [pitfalls](pitfalls.md), the short list of things that bite.
