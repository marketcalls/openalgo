# Open interest data

Open interest is an optional `oi` value on the same `Bar` as OHLC and volume.
It describes a position level at that timestamp. Missing data is omitted;
zero means the feed actually reported zero.

```ts
series.setData([
  { time: 1700000040, open: 100, high: 103, low: 99, close: 102, volume: 20, oi: 140 },
  { time: 1700000100, open: 102, high: 104, low: 101, close: 103, volume: 10 },
]);
```

Historical aggregation adds volume because it counts activity during a period.
Open interest takes the latest defined reading within that bucket. Five readings
100, 110, 120, 130 and 140 therefore fold to 140. A bucket with no readings stays
absent; a previous bucket's level never fills it.

`securitySeries` exposes a parallel nullable `oi` column. Its default developing
reading can use only source bars already reached. `offset: 1` reads the previous
completed bucket; `lookahead: true` reads the completed bucket early and carries
the same future-data implications as the other columns.

Heikin Ashi preserves the column because each result maps to one source bar.
Renko, range, line break, point and figure and Kagi do not attach open interest
to price-generated bars. Expression results omit it even if combined leg volume
is requested: an expression is not one contract position.

`CandleBuilder` and `TickBarAggregator` replace open interest when a finite
`Tick.oi` or `AggTick.oi` arrives. A tick without it clears a previous value from
the forming bar. This is deliberate: a retained historical value would look like
a current observation without a staleness indication. OpenAlgo's current quote
feed supplies no open interest. Completed history can therefore show a reading
while the tick-driven forming bar has none.

REST mapping omits nonfinite optional readings. Durable caches reject malformed
levels. A history response arriving after a live update retains the live
observation, including its absence or zero. During partial replay, only revealed
sub-bars contribute a level; the completed bar's value appears when it closes.

## Studies

Import `openalgo-charts/indicators`, then add any of these studies:

| ID | Output | Behavior |
| --- | --- | --- |
| `open-interest` | Pane line, `oi` | Raw position size with compact volume formatting and gaps for missing readings. |
| `open-interest-change` | Pane histogram, `change` | Adjacent difference. The first bar and either side of a missing reading are null. Increases and decreases have separate colors. |
| `open-interest-buildup` | Main candle colors | Close-to-close price and OI changes classify long buildup, short buildup, short covering and long unwinding. |

The buildup study has four color inputs: `longBuildupColor`, `shortBuildupColor`,
`shortCoveringColor` and `longUnwindingColor`. `unchanged: 'neutral'` is the
default. Set it to `'up'` to treat zero price or OI change as nonnegative. Missing
readings always leave the candle's own color. Its `state` values are 1, 2, 3 and
4 in that same order, or null. It adds no price plot or axis.

The line and histogram expose the standard generated plot style controls.
Use `plotStyleKeys` to discover their keys. The histogram's plot color is its
increase color; `downColor` controls decreases, and opacity affects both.

## Capability and status line

The host supplies instrument capability separately from observations:

```ts
chart.setDataContext({ symbol: 'CONTRACT', exchange: 'NFO', interval: '5m', hasOpenInterest: true });
chart.setStatusLineOptions({ openInterest: true });
```

`ChartDataContext.hasOpenInterest?: boolean` and the readonly getter
`chart.hasOpenInterest` carry the same three states: true means supported,
false means unsupported, and undefined means unknown. Neither zero nor a
missing forming-bar reading changes capability. `data:context` announces
capability-only changes too. This is the chart-side contract for a language host:
read bare `oi` from the selected bar and the flag from `chart.hasOpenInterest`.
Preserve unknown explicitly in any host mapping; do not infer false from zero.

The OI readout defaults off. A canvas legend receives
`{ label: 'OI', text: formattedReading, field: 'openInterest' }` only when a
reading exists. The owning chart suppresses that field when capability is false
without clearing the saved preference. A standalone `PaneLegend` can receive
`hasOpenInterest` in its options. The widget supplies the hovered or latest
reading, and its settings form disables an unsupported field with a reason.

The preference survives `getState()` / `restoreState()`. Capability is live
instrument metadata, so the host supplies it again instead of trusting saved
data. A widget interval change retains capability for the same instrument;
changing symbol or exchange clears it until the host supplies new metadata.

OpenAlgo hosts can also pass `OpenAlgoConfig.hasOpenInterest(request)` to the
REST adapter. Return false for an explicitly unsupported instrument to omit
the API's placeholder OI column before caching, replay or indicators see it.
The callback receives the actual request, so concurrent requests for different
instruments do not share whichever symbol happens to be selected now. True or
undefined preserves finite reported values. The adapter snapshots capability
before awaiting the response.

The reference host forwards finite OI if supplied, honors the same readout
switch and preserves explicit capability through an interval or chart-type
rebuild. Its standard history provider supplies OHLCV without OI or instrument
capability metadata. That case stays unknown with no reading. Expressions are
explicitly unsupported, and changing instrument clears prior metadata.
