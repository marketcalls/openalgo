# Replay and comparison

`isReplaying(chart)` reports whether the shared replay boundary currently owns the
chart, including paused playback. Hosts can combine it with their own selection
or grid-transition lock before exposing or delivering trading actions. A false
result does not grant broker permission or cover a host's pending replay picker.

*When to read this: building a market-replay transport bar, or putting a second instrument on the chart to read against the primary one.*

Source of truth: `src/replay/controller.ts`, `src/compare/controller.ts`, `src/compare/align.ts`. Both ship in the **base** bundle, so neither needs a tier import.

Both are headless in the same sense as `DrawingController`: they own state and transitions and draw no DOM. The transport bar and the symbol chips are the host's UI.

## Market replay

```ts
import { ReplayController, type ReplayState } from 'openalgo-charts';

const replay = new ReplayController(chart, { bars: session, startIndex: 200, barMs: 500 });
chart.on('replay:frame', (p) => renderTransport(p as ReplayState));
replay.play({ speed: 2 });
```

**By default, constructing the controller enters replay.** It snapshots each driven series' data plus `barSpacing` and `rightOffset`, then shows `startIndex` immediately. The snapshot is taken before anything moves, which is what lets `stop()` put the user back exactly where they were. Pass `autoStart: false` to prepare the snapshot without entering yet.

### ReplayOptions

| Key | Type | Default | Notes |
|---|---|---|---|
| `series` | `SeriesApi \| readonly SeriesApi[]` | `chart.primarySeries()` | The **first** owns the timeline. Omitting it throws when the chart has no primary series. |
| `bars` | `readonly Bar[]` | the primary series' current data | The full session. Never mutated; each frame gets its own slice. |
| `startIndex` | `number` | `0` | Clamped into the session. |
| `subBars` | `readonly Bar[]` | none | The finer session the displayed bars are built from (1m under a 5m chart). With it, a step is one **sub-bar** and the newest bar forms in front of the user instead of landing complete. |
| `barMs` | `number` | `1000` | Wall-clock ms per bar at speed 1. |
| `speed` | `number` | `1` | Multiplier over `barMs`. |
| `onFrame` | `(state: ReplayState) => void` | none | Called after the chart is updated, alongside the event. |
| `now` | `() => number` | `performance.now` | Injectable clock. |
| `scheduler` | `(cb, ms) => () => void` | `setInterval` | Injectable timer; returns its canceller. The default holds the interval from 1 ms to 2^31 - 1 ms, the longest a platform timer waits, so a very slow replay no longer ticks every millisecond (since 2.6.0). |
| `timing` | `ReplayTiming` | none | Explicit candle availability for time-aligned replay. `barEndTime: ReplayBarEndTime` returns UTC seconds; `subBarEndTime` is required with finer bars. |
| `startTime` | `number` | selected candle's end | Requires `timing`. Before the first observation the chart is empty, `index` is -1 and `bar` is null. |
| `autoStart` | `boolean` | `true` | False validates and captures data/viewport without changing the chart; seek or play enters later. |

### Transport

| Member | Signature | Notes |
|---|---|---|
| `seek` | `(index: number) => void` | Clamps to the session. |
| `step` | `(n = 1) => void` | Stops dead at the last bar. |
| `stepBack` | `(n = 1) => void` | Stops dead at the first bar. |
| `play` | `({ speed? }) => void` | Re-speeds a running replay. On the last bar it emits `replay:end` and arms no timer. |
| `pause` | `() => void` | Leaves the playhead where it is. |
| `stop` | `() => void` | Restores data **and** viewport. Safe twice; a later `seek`/`step`/`play` re-enters from `startIndex`. After the chart is destroyed it does nothing: the controller already left replay, see below. |
| `state` | `() => ReplayState` | `{ index, total, playing, speed, bar, subIndex, subSteps }`: everything a transport bar and a clock need. |
| `seekTime` | `(utcSeconds: number) => void` | Requires `timing`; projects only observations available by that time. |
| `time` | `() => number \| null` | Availability clock with `timing`; displayed bar timestamp otherwise. |
| `timePoints` | `() => readonly number[]` | Requires `timing`; a copy of observation timestamps for an external shared clock. |

`ReplayBarEndTime` is `(bar: Bar, index: number) => number`. The host supplies
calendar-aware candle availability; replay does not infer a close from the next
recorded bar across a session gap. Times must be finite, ordered and at or after
the candle opening, without overlapping the next candle. Close-stamped data may
explicitly return `bar.time`. Invalid timing fails before chart mutation.

In timed mode, `seek(index)` still selects a completed primary candle. Step and
play advance observation times. Partial candles use only a contiguous finer
prefix starting at the primary opening; after a missing/straddling finer bar,
the last known prefix remains until the declared close. The exact recorded
primary candle replaces it at that close. OI takes the last reading, never a sum;
absent OI is not filled from the completed candle. Followers and comparisons
withhold forming closes. Hosts retain feed ownership and must pause live writes,
alert evaluation and trading while replay owns the chart.

## One clock for several charts

`ReplayGroup` is an opt-in coordinator over prepared `ReplayController` instances.
It drives the union of active observation times with one timer. Ordinary charts
and standalone replay keep their defaults.

```ts
const group = new ReplayGroup([
  { id: 'minute', chart: minuteChart, options: { timing: { barEndTime: bar => bar.time + 60 } } },
  { id: 'five', chart: fiveMinuteChart, options: { timing: { barEndTime: bar => bar.time + 300 } } },
], { scope: 'all', startTime: selectedUtcSeconds, onChange: renderTransport });
group.play({ speed: 2 });
group.setScope('focused', 'five');
group.setScope('all');
group.destroy();
```

Public contracts: `ReplayScope` is `'focused' | 'all'`. `ReplayGroupMember` supplies
unique `id`, `chart: ReplayGroupChartHost`, and `options` containing `timing` plus
optional `series`, `bars`, `subBars`, `onFrame`. `ReplayGroupChartHost` extends
`ReplayChartHost` with optional `isDestroyed` and `on('destroy', callback)`; Chart
provides both. Custom hosts without lifecycle hooks must call `destroy()` themselves.

`ReplayGroupOptions` accepts `scope` (focused), `focusedId` (first member),
`startTime` (first active observation), `barMs` (1000), `speed` (1), `now`,
`scheduler`, and `onChange`. The native timer interval is clamped to its supported
range while the logical clock retains the requested cadence and caps catch-up
at ten observations per tick. Clock parameters must be finite and positive.

`ReplayGroupState` contains `active`, `destroyed`, `scope`, `focusedId`, `time`,
`index`, `total`, `playing`, `speed`, and `members: { id, active, state: ReplayState }[]`.
The group index/total address observation times, not a member's bar indices.
An empty active history has time null; before the first observation index is -1.
Methods: `state()`, `seek(index)`, `seekTime(time)`, `step(n?)`, `stepBack(n?)`,
`play({speed?}?)`, `pause()`, `setScope(scope, focusedId?)`, `stop()`, `destroy()`.

Scope changes preserve UTC time and restore charts leaving replay. Entering charts
capture fresh data, including bars received while inactive. Preparation/validation
failure preserves the running session. `stop()` restores active charts and retains
the captured initial time for re-entry; `destroy()` also releases membership,
snapshots and lifecycle listeners. Ownership remains reserved until destruction,
so another group cannot overwrite the same chart. Destroying an active chart ends
the group and restores survivors; an inactive chart is simply removed.

Member `onFrame` and group `onChange` callbacks run after all active charts reach
the frame. Member replay events report the shared speed/playing state. A runtime
projection or callback failure cancels the timer, attempts restoration on every
survivor, releases ownership and rethrows the error. Invalid control arguments
leave the current session intact. Stop/destroy can interrupt a frame; recursive
transport changes from a chart's own frame event are rejected. Use `onChange` for
transport decisions after a complete group update. The host still owns history
loading, pausing live writes on active members, and workspace-wide trading/alert
guards, including loading and scope transitions. Source changes require a fresh
member capture rather than replaying a different instrument under an old identity.

## Intra-bar replay

Without `subBars` a step lands a finished candle, so the moment a trader is
practising for -- watching a bar build and deciding before it closes -- never
happens. Pass the interval one rung down and each displayed bar forms over
several steps:

```ts
const replay = new ReplayController(chart, {
  series: [price, volume],
  bars: fiveMinute,
  subBars: oneMinute,   // five steps per displayed bar
  startIndex: pickedBar,
});
```

Worth knowing before wiring it up:

- **A bucket closes on the displayed bar verbatim**, not on the aggregate. Two
  feeds that disagree mid-bar therefore still agree on every close, so nothing
  drifts and a replayed session ends where the plain one does.
- **A forming bar stays inside the bar it closes on.** It carries the displayed
  bar's open from the first step, its high and low never pass the displayed
  bar's, and its volume never exceeds it. The official open and the first
  minute's open differ on most days, and without this the open jumped when the
  bucket closed and a high could fall back: a price no live candle shows.
- **`state().bar` is the partial bar**, not the completed one, which is what
  makes it the right thing to drive a host's OHLC readout or its own forming
  volume bar from.
- **Followers stop at the last completed bucket** while a bar forms. The
  controller will not half-aggregate an arbitrary one, because a volume
  histogram is summed and a candle is merged and it is not told which it has.
  Write the forming follower from `state().bar` in `onFrame`.
- **A seek lands on a completed bar**, including the one `startIndex` performs.
  Scrubbing onto a half-formed candle would make the same slider position mean
  different things on the way past.
- A bucket the finer feed does not cover takes **one** step and shows the
  displayed bar: a gap costs that bar its formation, not its existence. Unless
  `simulate` is set, below.

### Simulated forming

Feeds keep far less fine history than coarse: about a week of 1-minute bars
against years of 5-minute ones. With `simulate`, a bar no finer bar forms takes
the steps you name anyway, along a path through its own prices:

```ts
const replay = new ReplayController(chart, {
  series: [price],
  subBars: oneMinute,          // real bars win wherever they exist
  simulate: { steps: 5 },      // ReplaySimulation: a 5-minute bar over 1-minute pace
});
replay.state().simulated;      // true while the newest bar forms along the path
```

- The path runs from the open to the extreme nearer it, the other extreme, then
  the close, each step covering the same share of it. The forming bar carries the
  real open from the first step, only widens toward the real high and low, and
  closes on the bar itself, so every rule above still holds.
- **The order of the extremes is an assumption.** A bar's prices say where it
  went, not when. Show `state().simulated` to the user: a stop or a target tested
  inside a simulated bar was never tested against traded prices.
- Volume grows in proportion; open interest holds the reading before the bar.
- On the availability clock the steps fall at even shares of the candle's
  interval. A candle whose finer bars leave no forming prefix (a daily candle
  stamped at midnight over a session that opens at 09:15) is simulated too.
- `steps` is a whole number from 2 to 240; pick the finer bars the displayed one
  would hold, so simulated and real candles form at the same pace.

Pick the rung one step down, not the finest available. 1-minute bars under a
daily chart are 375 steps per candle, which is not a replay, it is a stall.

Events on the chart bus, all carrying a `ReplayState`: `replay:start` (first frame only), `replay:frame`, `replay:play`, `replay:pause`, `replay:end`, `replay:stop`.

### Why indicators come free

Every transition funnels through one private `_apply(index)` that hands the driven series a **prefix** of `bars` through the public `series.setData`. For the primary series that path already invalidates and recomputes every study at once, and `IndicatorInstance.recompute` re-reads the whole history from `sourceBars()`, so each plot, level, fill, marker and legend row rebuilds itself as it stood at that bar. There is no replay-aware code in the indicator tier, and none is needed.

`dataLayer.length` shrinks with the prefix, so an indicator's own plot series cannot hold the shared time axis open at future bars.

### Gotchas

- **Pass every series that shares the timeline** (volume histogram, a comparison line) in `options.series`. The DataLayer merges all series onto one axis, so one left at full length drags future timestamps back onto it. The extras are cut by **time**, not by count.
- **Replay drives series, not the feed.** Live ticks, periodic reconciliation, reconnect refreshes and older-history responses must all stop writing displayed series while replay is active, even while paused. Detach those writers or retain live data in a separate host buffer. On exit, `stop()` restores its captured snapshot; the host must then reconcile current live data and reseed. See [host-integration](host-integration.md).
- **Speed is derived from the clock, not the tick count**, so a throttled timer still plays at the requested rate. One tick consumes at most 10 bars, so a backgrounded tab does not fast-forward the session when it wakes.
- **A destroyed chart ends the session.** While replay owns the chart's data the controller listens for `'destroy'` (`ReplayChartHost.on`, optional; `Chart` has it). On it the timer stops, nothing more is written and nothing is restored. Since 2.6.0; before, a playing controller kept calling `setData` on the dead chart until the host called `stop()`. A custom host without `on` still has to stop replay itself.
- `stop()` restores `barSpacing` and `rightOffset` together with the data. Those two plus the restored `baseIndex` *are* the visible logical range, which is why the view returns to the pixel.

## Symbol comparison

```ts
import { addComparison, comparisonController } from 'openalgo-charts';

const bn = addComparison(chart, { symbol: 'BANKNIFTY', bars, color: '#f0a020' });
bn.alignment();                                   // { bars, matched, gaps, dropped }
comparisonController(chart).setMode('indexed-to-100');
bn.remove();
```

`addComparison(chart, options)` is the free-function front door; `comparisonController(chart, options?)` returns the one controller per chart (held in a `WeakMap`) for chart-wide operations; a call after it exists applies the `mode` and `baseline` it passes through `setMode` and `setBaseline` (since 2.6.0; before, they were ignored). **A primary series must exist first** or `add` throws.

### ComparisonOptions and the handle

| Key | Type | Default | Notes |
|---|---|---|---|
| `symbol` | `string` | required | Label only; carried on the handle for the host's UI. |
| `bars` | `readonly SeriesDataItem[]` | required | The instrument's own prices, aligned on the way in. |
| `color` | `string` | none | Shorthand; `style.color` wins if both are given. |
| `style` | `SeriesStyle` | `{}` | Merged over the chart type's defaults. |
| `type` | `SeriesType` | `'line'` | Any registered series type. |
| `paneIndex` | `number` | the price pane | The price pane by default, wherever it sits. A handle's `paneIndex` is read live, so it follows its pane through a move. |

`ComparisonHandle`: `symbol`, `series`, `paneIndex`, `priceScale()`, `alignment()`, `barAt(time)`, `setBars(bars)`, `remove()`, `list()`.

Use `barAt(time)` for host readouts. It returns the eligible aligned bar in the
instrument's own prices, or null for a gap, an unavailable common baseline, a
forming replay candle or a removed handle. Reading the original history cache
instead can reveal a completed candle while replay is still forming it.

`ComparisonController`: `add(options)`, `remove(handle)`, `list()`, `clear()`, `setMode(mode)`, `mode`, `setBaseline(policy)`, `baseline`, `baselineTime(paneIndex?)`, `realign()`, `sync()`, `destroy()`. `ComparisonMode` is `'percentage'` (default), `'indexed-to-100'` or `'none'`. `ComparisonBaseline` is `'first-visible'` (default) or `'common'`; `ComparisonControllerOptions` accepts both `mode` and `baseline`.

`baseline: 'common'` chooses the first visible timestamp with positive finite
closes on the primary and all visible comparisons. `baselineTime()` returns that
timestamp, or null when no shared start is available. Comparisons then draw gaps;
prices are never carried forward. Hiding a source removes it from the anchor
requirement. Panning and data changes recompute the anchor. Common mode expands
an automatic primary range to fit relative moves; a manually set range is kept.

### How the two lines become comparable

1. **Each comparison has its own scale.** The first uses a free legacy overlay or left axis; further sources use independent named hidden scales. An occupied volume or left scale is never taken over.
2. **Comparability comes from the scale, not the data.** Bars stay the instrument's real prices, so the legend and crosshair still read in prices; the pane switches to `percentage` or `indexed-to-100` while a comparison is on it.
3. **A per-frame pass mirrors the range**, giving the overlay the primary's range scaled by `baselineOverlay / baselinePrimary`, so equal ratios land on equal pixels. Without it each scale autoscales to its own data and a 1% mover looks exactly like a 10% mover.

The hook runs after autoscaling and before painting. It checks primary history
identity, length and boundary timestamps as well as the shared axis. Primary data
events also re-align immediately. Comparison replay data follows the completed
candle boundary, including sources added while replay is active, so a forming
candle cannot reveal its completed comparison close. Stop restores full data.

### Alignment (`alignToPrimary`)

Matching is on the **exact** timestamp; two instruments on the same interval agree to the second, and anything that does not agree is a different interval that no tolerance window could rescue.

| Direction of mismatch | Answer | Why |
|---|---|---|
| Comparison print with no primary bar | **dropped**, counted in `alignment().dropped` | The DataLayer merges every series' times into one index space, so a foreign time would mint a logical index and shift the primary's own bars. |
| Primary bar with no comparison print | **whitespace** (a NaN bar), counted in `gaps` | The line renderer breaks across it, so a holiday reads as a gap instead of a flat carry-forward or a straight line drawn through it. |

`ComparisonAlignment` is `{ bars, matched, gaps, dropped }`, enough for a host to report coverage.

### Gotchas

- **The legacy empty overlay is still shared by its users.** Named overlays give comparisons independent baselines; each handle's `priceScale()` is distinct.
- **The volume histogram usually owns the empty overlay.** A first comparison uses the left axis only when it is free; otherwise it uses a named hidden scale.
- **Use the handle, not the series, for data and teardown.** `series.setData` skips alignment; `series.remove()` leaves the pane rebased with nothing on it.
- **A user's own mode change is respected.** The pane's saved mode is only restored if it is still the one the controller applied, so switching the pane to log while comparing keeps that choice.
- `Chart` handles same-length primary replacement automatically. Custom structural hosts without primary history identity or data events may call `realign()` after replacing their timestamps.
- Chart destruction drops subscriptions and comparison history. Explicit `destroy()` removes the live series and restores the pane; create a new controller for later use.

## Related

- [scales-and-panes](scales-and-panes.md): `percentage` / `indexed-to-100`, baselines, overlay scales.
- [events-and-state](events-and-state.md): the `replay:*` payloads on the bus.
- [data-and-time](data-and-time.md): the shared logical index the alignment rules protect.
- [indicators](indicators.md): the recompute path replay leans on.
