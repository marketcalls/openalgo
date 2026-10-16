# Chart linking

*When to read this: driving a grid of charts as one workspace, so hovering, panning or changing the symbol, interval or chart type on one moves the others, and drawings made on one appear on the others; and saving those links, in named groups, in a workspace.*

Source of truth: `src/link/group.ts`, `src/link/appearance.ts`, `src/link/drawings.ts`, `src/link/align.ts`, `src/link/crosshair.ts`, `src/draw/drawing-link.ts`, and for the saved form `src/workspace/documents.ts`. General linking ships in the **base** bundle: `import { createLinkGroup } from 'openalgo-charts'`. The drawings channel's switch and membership are in the base group; the drawing synchronization itself is in `openalgo-charts/draw`.

Headless in the same sense as `ReplayController` and `DrawingController`. The group owns the sync; the link badge, the colour chips and the menu of switches are the host's UI.

```ts
import { createLinkGroup } from 'openalgo-charts';

const group = createLinkGroup({ crosshair: true, viewport: true, symbol: false });
group.add(daily);
group.add(hourly, { symbol: 'RELIANCE', onSymbol: (s, chart) => loadBars(s, chart) });
```

## The rule that matters: sync by instant, never by index

**Never copy a logical index or a logical range from one chart to another.** This is the single thing an agent implements wrong here, and the wrong version passes every hand test.

The x axis is a **gapless logical index over that chart's own bars** (`0..N-1`, one index per distinct bar time), not a timestamp axis. Two linked charts almost never hold the same bars: different symbols, different intervals, different history depth, different holidays, different halts. So logical index 300 is a different instant on every chart in the grid.

Copying the index across looks perfect on two charts of the same symbol and the same interval, which is exactly how the broken version ships. The correct conversion is always three steps:

```
index  --indexToTimeFloat-->  UTC seconds  --timeToIndex(Float)-->  index
        (on the SENDER's DataLayer)          (on the RECEIVER's DataLayer)
```

`LinkGroup` does this for you. If you are writing your own sync (a chart in a grid the group does not own, a linked drawing, a shared bar highlight), do the same two conversions or the daily chart will mark a bar three weeks away from the hourly chart's cursor.

The two conversions are pure and exported, so you can use them directly:

| Function | Signature | Returns |
|---|---|---|
| `followerIndex` | `(follower: LinkDataLayer, time: number, whenMissing?: LinkMissingPolicy) => number \| null` | An **integer** index on the follower, or `null` for "draw nothing". |
| `followerRange` | `(leader: LinkDataLayer, follower: LinkDataLayer, range: LogicalRange) => LogicalRange \| null` | The follower range showing the same wall-clock window, fractional at both ends. |

`LinkDataLayer` is the structural slice they read (`length`, `indexToTime`, `timeToIndex`, `indexToTimeFloat`, `timeToIndexFloat`). `chart.dataLayer` satisfies it, and so does a literal in a test.

### Coverage is an absence, not a gap

`followerIndex` answers `null` for any instant **before the follower's first bar or after its last one**, under both policies. That period is not a hole in its data, it is a period the chart does not cover at all, and snapping the crosshair to the first or last bar would assert an alignment that does not exist.

Inside the covered range with no bar at exactly that second, `whenMissing` decides:

| `whenMissing` | Behaviour |
|---|---|
| `'nearest'` (default) | Use the last bar whose opening is at or before the instant. Never select a future candle merely because its timestamp is closer. |
| `'hide'` | Draw nothing unless there is a bar at exactly that time. For a workspace where a linked crosshair is a data claim. |

`followerRange` returns `null` rather than guessing when the answer would be meaningless: either layer empty, a follower with fewer than 2 bars (every time maps to index 0 and the span collapses), or a non-finite or inverted endpoint. A follower whose history does not overlap the window at all is **not** refused: `timeToIndexFloat` extrapolates past either edge (left of the first bar at its first gap; past the last bar on the follower's own session calendar when one is set, otherwise at its median bar interval; see [times past the last bar](data-and-time.md#times-past-the-last-bar)), so it scrolls into its own empty margin and shows nothing, which is the truth. Clamping it back onto its last bars would show a different period than the leader.

## `createLinkGroup(options)`

| Option | Type | Default | Notes |
|---|---|---|---|
| `crosshair` | `boolean` | `true` | Hovering one member marks the same instant on the others. |
| `viewport` | `boolean` | `true` | Panning or zooming one moves the others to the same wall-clock window. |
| `symbol` | `boolean` | `false` | Off by default: symbol sync needs host cooperation (see below). |
| `interval` | `boolean` | `false` | Host-owned timeframe synchronization through `onInterval`. |
| `chartType` | `boolean` | `false` | Host-owned chart type (candles, bars, a line) through `onChartType`. |
| `appearance` | `boolean` | `false` | Supported visual settings through a `LinkAppearanceAdapter`. |
| `drawings` | `boolean` | `false` | Drawing sharing through each member's `LinkDrawingsAdapter` (see the drawings channel below). |
| `whenMissing` | `'nearest' \| 'hide'` | `'nearest'` | What a follower does with an instant it has no bar for. |

Each channel switches on its own because a user routinely wants one without the others: mirror the cursor across four timeframes but keep each zoom, or slave every chart's instrument but let each keep its own window.

## `LinkGroup`

| Member | Signature | Notes |
|---|---|---|
| `add` | `(chart: LinkChart, member?: LinkMemberOptions) => void` | Adding the same chart twice updates its member options instead of double-subscribing. A member joining a group that already has a symbol adopts it when symbol sync is on. |
| `remove` | `(chart: LinkChart) => void` | Unsubscribes and detaches that member's linked crosshairs. Safe twice, and after `destroy`. |
| `setOptions` | `(patch: LinkOptions) => void` | See the convergence note below. |
| `options` | `() => ResolvedLinkOptions` | Every option resolved, as a copy. |
| `members` | `() => readonly LinkChart[]` | Prunes destroyed members first, so the list is live. |
| `has` | `(chart: LinkChart) => boolean` | |
| `setSymbol` | `(chart: LinkChart, symbol: string) => void` | The imperative twin of emitting `'symbol'` on that chart's bus. |
| `symbol` | `() => string \| null` | The instrument the group has agreed on, `null` if nobody declared one. |
| `setInterval` | `(chart: LinkChart, interval: string) => void` | Report an interval selection. |
| `interval` | `() => string \| null` | Latest declared interval. |
| `setChartType` | `(chart: LinkChart, chartType: string) => void` | Report a chart type selection; the imperative twin of emitting `'chartType'`. |
| `chartType` | `() => string \| null` | Latest declared chart type, even while the channel is off. |
| `syncAppearance` | `(chart: LinkChart) => void` | Read and broadcast the member's visual settings when appearance is enabled. |
| `crosshairIndex` | `(chart: LinkChart) => number \| null` | That member's **own** logical index its linked crosshair is marking, or `null`. |
| `destroy` | `() => void` | No listeners, no linked crosshairs, no references. |

`Chart` updates its study legends and `subscribeCrosshairMove` readout automatically
through `setLinkedCrosshairIndex(index)`. Linked callbacks carry `source: 'linked'`
and null pointer coordinates. They do not emit `crosshair:move` on the event bus.
Native hover takes precedence; clearing the link restores the latest-bar readout.
The optional method on structural `LinkChart` adapters enables the same behavior.
For adapters without it, `crosshairIndex` returns the follower's logical index:
map it through that chart's `dataLayer.indexToTime(i)` and read its own bar.

`setOptions` convergence, which is deliberate and asymmetric:

- Turning `crosshair` **off** clears the linked lines immediately, rather than leaving the last one frozen on every follower.
- Turning `symbol` **on** makes the group agree on the instrument it already knows, because a switch that only took effect on the *next* change would leave a linked grid visibly unlinked.
- Turning `interval` or `chartType` **on** converges the same way, on the latest selection.
- Turning `drawings` **on** calls `join()` on every member's adapter; turning it off calls `leave()`.
- Turning `viewport` on does nothing until the next pan or zoom. Nothing in the group says whose window the others should have adopted.

`LinkMemberOptions`, the second argument of `add`:

| Field | Type | Notes |
|---|---|---|
| `symbol` | `string` | The instrument the chart shows now. |
| `onSymbol` | `(symbol, chart) => void` | Load it. Omit to make the member follow nobody. |
| `interval` | `string` | The interval the chart shows now. |
| `onInterval` | `(interval, chart) => boolean \| void` | Apply synchronously; `false` refuses. |
| `chartType` | `string` | The chart type the chart shows now (a registered chart type id). |
| `onChartType` | `(chartType, chart) => boolean \| void` | Apply synchronously; `false` refuses a type the chart cannot draw. |
| `appearance` | `LinkAppearanceAdapter` | `read()` and `apply(values)`. |
| `drawings` | `LinkDrawingsAdapter` | `join()` and `leave()`. Without one the member never shares drawings. |

## Symbol sync is a partnership

The host owns instrument selection and loading. `chart.setDataContext(...)` declares identity for studies and alerts; symbol linking reports a selection without loading data by itself. The host does two things:

1. **Reports a change**, by calling `group.setSymbol(chart, 'INFY')`, or by emitting `'symbol'` on that chart's own bus (`chart.emit('symbol', { symbol: 'INFY' })`, or a bare string). `chart.emit` is deprecated and goes in 3.0.0, so prefer `setSymbol`; a draw-tier `DrawingLinkGroup` also follows `data:context`, which `setDataContext` emits.
2. **Performs a change**, through the per-member `onSymbol(symbol, chart)` callback, which fetches the bars and calls `series.setData`.

```ts
group.add(chart, {
  symbol: 'RELIANCE',                       // what it is showing right now
  onSymbol: async (sym, c) => {             // how to make it show something else
    const bars = await feed.getBars({ symbol: sym, exchange: 'NSE', interval: '5m' });
    seriesOf(c).setData(bars);
  },
});
```

A member with **no `onSymbol`** broadcasts its own changes but never follows anyone else's. That is the supported way to pin one chart of a grid, not a limitation to work around.

The change is recorded even with the switch off, so turning `symbol` on later converges on something current instead of a stale instrument.

## The linked crosshair

A follower's crosshair is a `LinkCrosshair` primitive, one **per pane** so it spans price, volume and indicator panes the way the native global crosshair does. Two deliberate differences from the native one:

- **Vertical line only.** The horizontal line marks a price, and the price under a cursor on another instrument is not a price on this one. On a grid of four symbols a mirrored price line is a straight lie four times over. The vertical line marks an instant, and an instant is shared.
- **Reduced opacity** (`LINK_CROSSHAIR_ALPHA`, 0.55) in the follower's own crosshair colour, so it reads as a reflection of a cursor somewhere else rather than a second cursor in this chart.

It sits on the `'top'` z-order, which is the layer `Pane.paintTop` repaints for a cursor move, so it costs the same overlay repaint the native crosshair does. The leader never draws one: it already has a real crosshair under the user's pointer, and a second line there would double it.

## Feedback loops and dead charts

**One group-wide re-entrancy guard**, not one per channel. Any member event arriving while the group is broadcasting is an echo of that broadcast by definition, since a human cannot pan two charts in one call stack. It is group-wide because a symbol change that reloads data can move a viewport, and that second-order echo is the same bug wearing a different hat. The symbol, interval and chart type channels also ignore a selection a follower reports while the group is applying one: a follower's `onSymbol` that announces the name it normalised to (a suffix, a case change) leaves the group on the leader's instrument (since 2.6.0; before, the follower's spelling became `group.symbol()`).

Members are dropped the moment their chart dies. `chart.destroy()` sets `isDestroyed`, emits `'destroy'` and the group prunes on the spot; a `LinkChart` that is not a `Chart` and reports neither is probed by pane count instead (the price pane can never be removed by any other route). This matters beyond tidiness: `addPrimitive` on a destroyed chart would resurrect a pane.

## What the group listens to

Everything comes off the chart's own event bus, so a host can drive it from anywhere:

| Event | Channel |
|---|---|
| `crosshair:move` | crosshair (reads `payload.time`; `null` clears) |
| `pan`, `zoom` | viewport |
| `symbol` | symbol (host-emitted; the core never emits it) |
| `interval` | timeframe (host-emitted) |
| `chartType` | chart type (host-emitted; payload a string or `{ chartType }`) |
| `style:change` | appearance (emitted by `applyChartSettings`) |
| `destroy` | pruning |

Since 1.4.0 the programmatic viewport paths (`setVisibleLogicalRange`, `fitContent`, `resetScale`, and the keyboard pan/zoom shortcuts) also emit `'pan'` or `'zoom'`, so a linked grid follows an arrow key or a restored zoom and not only a gesture. They emit nothing when the window did not actually move, which is what keeps a clamped zoom or an already-fitted `fitContent` from re-broadcasting.

## Gotchas

- **Do not copy `getVisibleLogicalRange()` from one chart to another.** It is the exact bug this module exists to prevent. Use the group, or `followerRange`.
- **A fresh follower should not broadcast its own `fitContent`.** Loading bars into a newly opened chart and fitting them throws the leader off the window the user was on. Suspend viewport sync for the load (`setOptions({ viewport: false })`, load, restore) and let the two converge on the first pan.
- **`LinkChart` is structural, not `Chart`.** A stub with `on`, `getVisibleLogicalRange`, `setVisibleLogicalRange`, `dataLayer`, `panes`, `addPrimitive` and `removePrimitive` is a valid member, which is how the group is tested. `isDestroyed` is optional for that reason.
- **A linked readout is not pointer input.** Check `source: 'linked'` before handling replay picking or other pointer gestures in a readout callback. The group still draws its own vertical marker separately from the physical pointer crosshair.
- **Symbol sync does nothing on its own.** With no `onSymbol` on any member, turning the switch on changes nothing visible, because there is no code anywhere that loads bars.
# Interval linking

`createLinkGroup({ interval: true })` adds an independent timeframe channel,
off by default. Supply the member's current `interval` and an `onInterval`
callback to `group.add(chart, ...)`. Report subsequent choices through
`group.setInterval(chart, token)` or `chart.emit('interval', { interval: token })`
(deprecated, removed in 3.0.0; prefer `setInterval`).
`group.interval()` reads the latest selection, even while interval sync is off.
Enabling sync or joining an enabled group adopts its latest interval.

The callback applies the host's interval synchronously and starts its usual data
load. Return `false` for an unsupported interval; this preserves the member's
previous interval. Async fetching stays with the host and its cancellation rules.
Callbacks cannot recursively overwrite the leader's interval by echoing a token.
Removing or destroying a member releases the interval listener with other links.

## Chart type linking (since 2.5.10)

`createLinkGroup({ chartType: true })` adds the chart type channel, off by
default, and it works exactly like the interval channel: supply the member's
current `chartType` and an `onChartType(chartType, chart)` callback to `add`,
report changes with `group.setChartType(chart, id)` or
`chart.emit('chartType', { chartType: id })` (deprecated, removed in 3.0.0), and read `group.chartType()`.
The core never emits `'chartType'`; the host reports it, as it does an interval.

```ts
import { createLinkGroup, registeredChartTypes, type SeriesType } from 'openalgo-charts';

const group = createLinkGroup({ chartType: true });
for (const { chart, series } of cells) {
  group.add(chart, {
    chartType: chart.seriesType(series) ?? undefined,
    onChartType: id => registeredChartTypes().includes(id)
      && chart.setSeriesType(series, id as SeriesType),
  });
}
chartA.setSeriesType(seriesA, 'bar');
group.setChartType(chartA, 'bar');   // every other member now draws bars
```

Return `false` from `onChartType` for a type the chart cannot draw; the member
keeps its own and is asked again on the next change. Colours, scales and the
status line are the appearance channel, never this one, so candles linked to
candles keep each chart's own colours unless appearance is on too. The widget
reports its own change on its bus as `'layout'` with `reason: 'chartType'`; a
host running widgets side by side forwards that to `setChartType`.

## Appearance linking

`LinkOptions.appearance` defaults to false. Each `LinkMemberOptions.appearance`
accepts a synchronous `LinkAppearanceAdapter` with `read()` and `apply(values)`.
`LinkAppearanceValues` is `Record<string, string | number | boolean>`.

```ts
import { createLinkGroup, readChartSettings, applyChartSettings } from 'openalgo-charts';

const group = createLinkGroup({ appearance: true });
for (const chart of [chartA, chartB]) {
  group.add(chart, { appearance: {
    read: () => readChartSettings(chart),
    apply: values => applyChartSettings(chart, values),
  } });
}
applyChartSettings(chartA, { 'symbol.upColor': '#008800' });
```

`applyChartSettings` emits `style:change` after a supported visual patch.
Other host setters can call `group.syncAppearance(chart)` explicitly. The adapter
reads supported chart-settings fields, so calling it after `setTheme` transfers
those visual fields, not an entire theme object. `filterLinkAppearance(values)`
returns a fresh allowlisted record: known series styling, readout visibility,
scale presentation (mode, auto-fit, the primary-prices-only fit since 2.6.0, and
inversion), grid, crosshair, watermark styling and axis chrome. It omits
watermark text, instrument identity, interval, timezone, navigation, the study
legend fold (`statusLine.indicatorsCollapsed`), studies, event feeds, alerts and
trading. No chart data or series type crosses. Each peer
receives a separate record; callbacks cannot echo back through the group guard.
Enabling appearance waits for the next edit or explicit notification.

## The drawings channel (since 2.5.10)

`LinkOptions.drawings` (default false) is the switch, and each member brings a
`LinkDrawingsAdapter` with `join()` and `leave()`. The base group decides **who**
shares: the members of this group, while the switch is on. The draw tier's
`DrawingLinkGroup` decides **which** drawings cross and moves them, so no drawing
code enters the base bundle. Use one `DrawingLinkGroup` per link group:

```ts
import { createLinkGroup } from 'openalgo-charts';
import { createDrawingLinkGroup } from 'openalgo-charts/draw';

const group = createLinkGroup({ symbol: true, drawings: true });
const sharing = createDrawingLinkGroup({ enabled: true });   // the group's switch rules
group.add(chart, {
  symbol, onSymbol,
  drawings: {
    join: () => sharing.add(chart, controller),
    leave: () => sharing.remove(chart),
  },
});
```

The group calls `join` when the member is in it and the switch is on, and `leave`
when either stops being true: the switch goes off, `remove`, a replaced adapter
(the old one leaves before the new one joins), the chart's `destroy`, or
`group.destroy()`. Calls alternate; a member is never joined twice.

The rule, which a host can state to its users as is:

- **Same instrument only.** Drawings cross only between charts showing the same symbol and exchange. A chart on another instrument neither sends nor receives, whatever its group.
- **Price pane, data space.** A drawing pinned to the viewport stays on its chart.
- **Drawn while on, and present.** A drawing crosses to the charts that are on its instrument when it is drawn, and from then on every edit and the deletion reach each of them. A drawing that has never been shared stays private to its chart until `sharing.share(chart, ids?)`, so switching on never sprays one chart's levels across a desk. A chart that arrives on the instrument later, or joins the group later, gets a drawing shared without it only when the host shares it again.
- **An instrument change keeps drawings with their instrument.** With drawings kept per instrument (`InstrumentDrawings`, the widget's default), a chart leaving an instrument keeps its copies in that instrument's saved document and shows the new instrument's own. Coming back, the copies reconnect and take the state the charts still on it hold, a deletion included. With symbol linking on too, the whole group moves together and keeps sharing on each instrument it visits. Build the `InstrumentDrawings` before joining, so it swaps the document before the sharer sees the new instrument.
- **Leaving keeps what arrived, and re-linking reconnects it.** Switching off or leaving the group stops the traffic; copies already made stay on each chart. A copy still carries its link, so when its chart shares again (the switch goes back on, or it rejoins) it reconnects and takes the state the charts already sharing hold, as on returning to an instrument: their edits, and a deletion made while they were sharing. An edit made to a copy while unlinked gives way on re-linking. Members join in the order they were added, so when the switch goes on for the whole group the first of them holding the drawing sets its state.

## Drawing linking (draw tier)

```ts
import { DrawingController, createDrawingLinkGroup } from 'openalgo-charts/draw';
const group = createDrawingLinkGroup({ enabled: true });
const a = new DrawingController(chartA);
const b = new DrawingController(chartB);
group.add(chartA, a, { symbol: 'INFY', exchange: 'NSE' });
group.add(chartB, b, { symbol: 'INFY', exchange: 'NSE' });
group.share(chartA, a.selection()); // explicit promotion of existing local drawings
```

Public exports: `DrawingLinkGroup`, `createDrawingLinkGroup`, `DrawingLinkOptions`,
`DrawingLinkContext`, `DrawingLinkContextSource`, `DrawingLinkChart`. `DrawingLinkOptions.enabled` defaults to
false. `DrawingLinkChart` is structural: `on`, optional `isDestroyed`, optional
`getDataContext`, optional `primaryPaneIndex`. Only price-pane drawings cross, and each
chart's price pane is its own slot (`primaryPaneIndex()`, 0 without the method): a
drawing on the price pane at the bottom of one chart arrives on the price pane at the
top of another, never on the study pane in the same slot. `DrawingLinkContext` has optional `symbol` and `exchange` strings;
both must be known, nonblank and exactly equal before drawings can cross.

| Method | Behavior |
|---|---|
| `add(chart, controller, context?)` | Register and reconnect only known persisted lineage. Existing local drawings stay local. Omitted context reads `getDataContext()`. `DrawingLinkContextSource` also accepts a resolver. |
| `setContext(chart, context)` | Update identity, or pass `undefined` to stop eligibility. |
| `share(chart, ids?)` | Send selected ids or every existing eligible drawing; returns their count. |
| `setOptions({ enabled })` | Toggle sharing; off clears received drag previews. |
| `options()` | Return a copy of the resolved flag. |
| `has(chart)` | Test membership. |
| `remove(chart)` | Unsubscribe and clear previews; committed copies remain. |
| `destroy()` | Release every member. |

New drawings, updates, deletion and local undo/redo propagate both ways. Time and
price anchors cross unchanged, including between different intervals. Only pane
`0` participates. Shared copies have independent objects and collision-safe local
IDs. Local selection and local history stay local; undo edits only fields changed
by that local command and preserves unrelated remote changes. Received previews
paint over committed drawings without entering `toJSON()`.

Restoring a document refreshes its associations. Unmarked local drawings stay local
until `share`; joining does not copy older drawings the chart has never shared.
Reserved `props['openalgo-charts/drawing-link']` metadata carries version, unique
lineage ID and instrument context through JSON. When enabled, add and restore reconnect
only matching persisted lineage under the same identity. Current peer values and
ordering replace a stale saved copy, including a deletion still tracked by the peer.
Explicit sharing also reuses matching copies without replacing unrelated local IDs.
Duplication and paste discard old lineage.
Preserve the reserved property through host persistence. A changed instrument removes received copies from the member,
while the host owns its local per-instrument drawing persistence. `data:context`
updates identity; a `symbol` event invalidates it until complete context arrives.
Use `setContext` for another host identity source, or pass a resolver as the third
`add` argument. The resolver runs on registration and `data:context`/`symbol` events;
null, undefined, missing identity or a thrown error makes the chart ineligible. For
example, `() => ({ symbol: chart.getDataContext()?.symbol, exchange: 'YFINANCE' })`
provides a host namespace without changing the chart's context or its alert scopes.
If a feed provides fully qualified
symbols, an explicit stable feed namespace may serve as the exchange identity
(the reference host uses `YFINANCE`); it is not actual exchange metadata.

`DrawingController.cancelDrag()` rolls back a gesture and preserves prior undo/redo.
The controller emits `draw:preview`, `draw:preview-clear`, `draw:restore`, and
`draw:destroy` for lifecycle integration. History changes emit ordinary draw events
with `history: true` plus `drawing:change` kinds `undo` or `redo`.
`applyLinkedDrawing(id, drawingOrNull)` applies committed linked data without a local
undo entry; `setLinkedPreview(id, drawingOrNull)` changes only the rendered preview.
`reorderLinkedDrawings(ids)` changes the relative order of related drawings in their
existing slots, leaving unrelated local drawings in place.
These methods are used by the group. Cancellation, context change, unlink and
destruction clear previews. The channel never copies alerts, orders or other
primitives, and importing the base link group never imports the draw tier.

## Saving links in a workspace

The chart type, drawings and missing-bar flags, named groups and `linkGroup` are since 2.5.10.

The workspace tier (`openalgo-charts/workspace`) saves the links as
`WorkspacePayload.sync`, a `WorkspaceSync`. Every field added since the first
release is optional, so every document saved before reads, and writes back,
unchanged, and a host that builds `sync` itself keeps compiling.

| Type | Fields |
|---|---|
| `WorkspaceLinkChannels` | `crosshair`, `viewport`, `symbol`, `interval` (required booleans), optional `appearance`, `chartType`, `drawings` booleans and `whenMissing` (`'nearest' \| 'hide'`). Named as `LinkOptions` names them, so a group's flags open with `createLinkGroup(channels)`. |
| `WorkspaceSync` | `WorkspaceLinkChannels` plus optional `groups: WorkspaceLinkGroup[]` (at most 16). |
| `WorkspaceLinkGroup` | `WorkspaceLinkChannels` plus `id` (1 to 100 characters, unique) and `name` (1 to 120). |
| `WorkspacePane.linkGroup` | Optional: the `id` of the group the chart is in. |

How a reader applies them:

- **No `groups`**: the whole desk is one group on the flags beside it. Every workspace saved before groups reads this way.
- **`groups` present**, even empty: each chart is in the group its `linkGroup` names, or in none when it has no `linkGroup`, and each group links on its own flags. A group with no chart yet is kept.
- A `linkGroup` naming an undeclared group, or any `linkGroup` while no groups are declared, refuses the document (`WorkspaceDocumentError`), since either would link that chart wrongly. So do duplicate group ids, a blank id or name, and non-boolean flags.
- Absent optional flags read as the engine defaults (off, and `'nearest'`), and are not written back.

Pass only the flags to `createLinkGroup`; `groups`, `id` and `name` are not link options, and `options()` would report them back:

```ts
const { groups, ...deskFlags } = desk.sync;
const named = new Map<string, LinkGroup>();
for (const { id, name, ...flags } of groups ?? []) named.set(id, createLinkGroup(flags));
const whole = groups === undefined ? createLinkGroup(deskFlags) : null;
const groupOf = (pane: WorkspacePane): LinkGroup | null =>   // whole desk, named group, or none
  whole ?? (pane.linkGroup === undefined ? null : named.get(pane.linkGroup) ?? null);
```

Writing groups: a reader older than groups drops `groups` and `linkGroup` and
applies the flags beside them to every chart. Turn a flag on there only when
every chart can follow it together (for example, symbol only when all charts show
one instrument); all off is always safe. Refuse, per group, a document whose
symbol-linked group holds different instruments, or whose interval-linked group
holds different intervals, as the chart grid does per group (since 2.5.10): joining a
linked group converges it, which would overwrite a chart saved on another.
The widget tier's chart grid is a worked host: `createChartGrid` keeps one `LinkGroup`
and one `DrawingLinkGroup` per named group, writes groups only when they say more than
the flat flags, and writes flat flags that every chart can follow (those of a group
holding every chart, else all off). See widget.md, Chart grid.
