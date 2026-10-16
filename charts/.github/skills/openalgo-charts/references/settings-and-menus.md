# Settings schema and context menu

*When to read this: building a chart settings dialog, rendering a paired up/down colour row, styling the canvas (grid, crosshair, axis text, plot margins) from a host UI, switching status-line fields on and off, or wiring a right-click menu, including one raised on a price axis.*

Source of truth: `src/model/chart-settings.ts`, `src/render/grid.ts`, `src/render/crosshair.ts`, `src/primitives/pane-legend.ts`, `src/core/chart.ts`.

The library still ships no DOM chrome. What it ships is the description of a dialog and the options behind every control, so the host renders the form and the engine owns the state.

## The schema

```ts
import { chartSettingsSchema, readChartSettings, applyChartSettings } from 'openalgo-charts';

const tabs = chartSettingsSchema(chart);        // ChartSettingsTab[]
const values = readChartSettings(chart);        // { 'canvas.grid.vertColor': '#1e2436', ... }
applyChartSettings(chart, { 'canvas.grid.vertLines': false });   // patch, one key is fine
```

| Piece | Shape | Notes |
|---|---|---|
| `ChartSettingsTab` | `{ id, label, inputs }` | `inputs` is the `IndicatorInput` union the indicator settings form already uses (`number`, `boolean`, `color`, `text`, `select`, `source`) **plus one extra kind, `colorPair`**, so a host that renders the indicator form needs exactly one new widget. `input.group` names the sub-heading. |
| `ChartSettingsValues` | `Record<string, string \| number \| boolean>` | Flat, dotted keys (`symbol.upColor`, `canvas.grid.horzStyle`). JSON-safe. |
| `applyChartSettings` | `(chart, patch)` | Writes only the keys present; unknown keys are ignored, which is what lets a state saved by a newer build restore into an older one. |

Tabs, in display order: `price` (Price), `readout` (Readout), `axes` (Axes), `appearance` (Appearance), `trading` (Trading).

| Tab | Covers | Key namespaces |
|---|---|---|
| Price | The primary series' own paint: candle body / borders / wick, bar and column colours, line and fill colours, thickness and dash, colour from previous close, label precision, the last-price line and its axis tag. On a transformed chart it leads with the transform's options, and point and figure and Kagi get their own colour rows (X and O, thick and thin) | `symbol.*`, `transform.*` |
| Readout | What the pane legend says: logo, title and title mode, session state, O/H/L/C, bar change, volume, change since previous close, indicator values, and the plate behind the row | `statusLine.*` |
| Axes | Price-scale mode, auto-fit, invert, chart timezone, mouse panning, and default visible bars | `scales.*`, `time.timezone`, `navigation.*` |
| Appearance | Grid, crosshair, scale text and lines, plot margins | `canvas.*` |
| Trading | Long / short, order, take profit / stop loss, buy / sell colours | `trading.*` |

**Alerts and Events tabs do not exist.** Alerts ship with the alert feature; events have no data source behind a dialog control. An empty tab is worse than an absent one, so neither is generated. The chart still owns `setEventOptions`, and `events` still rides in the saved state for hosts that feed their own corporate actions.

**The key names did not follow the tab names.** Dotted keys are a wire format hosts have written into saved layouts, so they were left alone when the tabs were regrouped: Price-tab controls are still `symbol.*`, Axes-tab scale controls still `scales.*`. One key moved: `scales.lastValueVisible` is now **`symbol.lastValueVisible`**, because it patches a `SeriesStyle` field and belongs beside the price line it contradicts. An old patch carrying the old name is ignored key by key, so the rest of a stale layout still restores.

Two rules worth knowing before extending it:

- **The schema and its accessors are one structure.** Each control carries its own `read`/`write` beside its input descriptor, so a control cannot drift from the option it drives and there is no second lookup table.
- **Every control maps to a real option.** A reference control the engine has no backing for is absent rather than inert, so nothing in the schema is a checkbox that does nothing.

`chartSettingsSchema(chart)` takes the chart because the Price tab is generated from the **primary series type**: a candle gets `borderUpColor` / `wickVisible`, a line gets `lineStyle` / `lineWidth`. Read the type with `chart.primarySeriesInfo()` if you need it yourself.

## `colorPair`: two colours on one row

A property with a bullish and a bearish colour is **one** labelled row carrying its switch and both swatches:

```text
[x] Borders   [up] [down]
```

not a section header over separate Up and Down rows. The stacked form triples the height of every panel and is what forces a scrollbar onto a dialog that should fit. See the UI standard in [themes-and-styling](themes-and-styling.md#host-chrome-the-ui-standard).

```ts
type PairInput = {
  key: string;                                   // row id, NOT a value key
  type: 'colorPair';
  label: string;
  group?: string;
  enabled?: { key: string; default: boolean };   // absent when there is no flag behind it
  up: { key: string; label: string; default: string };
  down: { key: string; label: string; default: string };
};

for (const input of tab.inputs) {
  if (input.type === 'colorPair') {
    renderPairRow(input, values[input.up.key], values[input.down.key],
                  input.enabled ? values[input.enabled.key] : undefined);
  } else {
    renderPlainRow(input, values[input.key]);
  }
}
```

**It is a schema row over ordinary flat value keys, not a new value shape.** `up.key`, `down.key` and `enabled.key` are everyday keys of `ChartSettingsValues`, so `readChartSettings` returns them like any other key, `applyChartSettings` accepts them like any other key, and a host that has not built the widget yet can still drive the row one key at a time. `input.key` itself is never a value: reading `values[input.key]` gets you `undefined`.

**`enabled` is optional on purpose.** Candle Borders and Wick have `borderVisible` / `wickVisible` behind them; a candle Body does not, so that row ships with two swatches and no checkbox rather than with a checkbox that would do nothing. Render the switch slot empty when `enabled` is absent, and keep the swatches aligned with the rows that have one.

Rows that are pairs today: `symbol.body`, `symbol.borders`, `symbol.wick` (candles), `symbol.body` again for bars and columns, `symbol.baseline` and `symbol.fill` (line and baseline fills), and on the Trading tab `trading.positions` (long / short), `trading.bracket` (take profit / stop loss) and `trading.executions` (buy / sell).

The union member's type name is not exported; type a renderer parameter as `ChartSettingsTab['inputs'][number]` and narrow on `input.type`.

## The timezone control

**The timezone is in the schema now.** It is `time.timezone` on the Axes tab, a `select` over the shipped zone list (UTC, London, Berlin, Moscow, Dubai, Kolkata, Singapore, Hong Kong, Tokyo, Sydney, Sao Paulo, New York, Chicago, Los Angeles, roughly east to west so it reads like a trading day) with the chart's own zone folded in when it is not one of them, so a chart built with `Pacific/Auckland` still shows its own setting selected rather than reading as the first entry. The options are on the input descriptor, so read them from there rather than hardcoding a list.

```ts
applyChartSettings(chart, { 'time.timezone': 'America/New_York' });   // calls chart.setTimezone
```

A name `isValidTimezone` rejects is **skipped**, not thrown, so one stale zone in a restored layout cannot throw away the rest of the apply. Do not bolt a second zone row beside the schema: that was the old advice and it needed its own Cancel bookkeeping. A host that wants a longer list than the shipped one renders its own control and calls `chart.setTimezone` directly. See [data-and-time](data-and-time.md).

## Navigation controls

The Axes tab's **Navigation** group is backed by `ChartNavigationOptions`:

| Key | Input | Default |
|---|---|---|
| `navigation.panEnabled` | Boolean: **Enable panning** | `true` |
| `navigation.zoomEnabled` | Boolean: **Enable zooming** | `true` |
| `navigation.mousePan` | `select`, label **Mouse drag**: **Horizontal only** (`'horizontal'`) or **Time and price** (`'both'`) | `'both'` |
| `navigation.defaultVisibleBars` | `number`, label **Default visible bars (0 = all)**, `min: 0`, `max: 100000`, `step: 1` | `0` |
| `navigation.defaultBarSpacing` | `number`, label **Default bar spacing (0 = use bar count)**, CSS pixels, `min: 0`, `max: 10000`, `step: 0.5` | `0` |

`panEnabled` and `zoomEnabled` control native user gestures, keys and navigation buttons independently. Disabling zoom also disables user fit/reset actions in both hosts. Active motion is cancelled, while programmatic view changes and drawing or picking interactions remain available. Both booleans persist with the chart.

```ts
applyChartSettings(chart, {
  'navigation.mousePan': 'both',
  'navigation.defaultVisibleBars': 120,
});
readChartSettings(chart)['navigation.defaultVisibleBars'];  // 120
```

`mousePan` applies to mouse and pen plot drags; touch retains two-axis panning. Updating
`defaultVisibleBars` applies the default view immediately. Initial data and `resetScale()`
use this count: `0` fits all loaded bars, while positive N targets the newest N loaded bars
plus four right-padding slots, subject to available-data and spacing limits.
`fitContent()` remains an explicit fit of all loaded bars. This setting changes neither
feed history requests nor retained data. The widget's ordinary load views honour the
count; a host can explicitly apply its own viewport after loading data.

Direct API: `chart.navigationOptions(): Readonly<ChartNavigationOptions>` and
`chart.setNavigationOptions(patch: Partial<ChartNavigationOptions>): void`. The optional
`navigation` state block restores before the saved viewport, so its explicit range wins.

## Canvas options

One option block, four groups, applied by `chart.setCanvasOptions(patch)` or `ChartOptions.canvas` and read back with `chart.canvasOptions()`.

```ts
chart.setCanvasOptions({
  grid: { vertLines: false, horzColor: '#1e2436', horzStyle: 'dotted', lineWidth: 1 },
  crosshair: { color: '#8fa2c6', style: 'dashed', width: 1 },
  scales: { textColor: '#9aa7bd', fontSize: 12, lineColor: '#2a3350' },
  margins: { top: 12, bottom: 8 },        // percent of pane height
});
```

| Group | Type | Keys |
|---|---|---|
| `grid` | `Partial<GridOptions>` | `spacing`, `vertLines`, `horzLines`, `vertColor`, `horzColor`, `vertStyle`, `horzStyle`, `lineWidth` |
| `crosshair` | `CrosshairOptions` | `color`, `style`, `width` |
| `scales` | `ScaleCanvasOptions` | `textColor`, `fontSize` (clamped to `SCALE_FONT_MIN`..`SCALE_FONT_MAX`, 10 to 14), `lineColor` |
| `margins` | `PlotMarginOptions` | `top`, `bottom`, in **percent** of pane height, each capped at 49 |

`CanvasLineStyle` is `'solid' | 'dashed' | 'dotted'`.

**Option overrides theme when set; theme is the default.** Theme colours are deliberately not copied into the options, because that would freeze the palette and make a later `setTheme` a silent no-op for everything the dialog had touched. Each resolver falls through field by field instead:

```ts
import { resolveGridStyle, resolveCrosshairStyle, resolveScaleStyle, resolvePlotMargins, dashPattern } from 'openalgo-charts';
```

They are exported as values, not just types, so a host can preview with the same code that paints. (`computeGridLines` and `drawGrid` themselves are internal.) An axis switched off yields no line positions at all, so visibility costs nothing downstream.

**Margins have no second state.** `resolvePlotMargins` converts the dialog's percentages into the `marginTop` / `marginBottom` fractions the price scale already owns, and `setCanvasOptions` pushes them to every scale on every pane. See [scales-and-panes](scales-and-panes.md).

`chart.setGridOptions(patch)` takes the whole `Partial<GridOptions>`, not just the two visibility flags; the pane strokes the vertical and horizontal lines separately so each gets its own colour and dash.

## Status line options

The pane legend row is switchable field by field, per legend (`PaneLegendOptions.statusLine`) or chart-wide (`chart.setStatusLineOptions(patch)`, which pushes onto every legend including host-added ones).

| Key | Default | Hides |
|---|---|---|
| `logo` | `true` | The symbol logo from `status.logo`. |
| `title` / `titleMode` | `true` / `'symbol'` | The bold name; the mode picks `symbol`, `description` or `ticker`. |
| `marketStatus` | `true` | `status.marketStatus`. |
| `chartValues` | `true` | Readings tagged `field: 'ohlc'`. |
| `barChange` | `true` | Readings tagged `field: 'change'`. |
| `volume` | `true` | Readings tagged `field: 'volume'`. |
| `lastDayChange` | `true` | `status.lastDayChange`. |
| `lastValueLabel` | `true` | The source's own untagged reading (the "last value label" control). |
| `background` / `backgroundColor` / `backgroundOpacity` | `false` / theme background / `0.8` | The plate behind the row. The only switch that is off by default. |

**The primitive invents no data.** Readings pushed through `legend.setValues([...])` carry an optional `field: 'ohlc' | 'change' | 'volume'` tag, so one switch hides exactly one group. The three things a legend cannot know arrive through `PaneLegendOptions.status`, a `LegendStatusData` snapshot or a per-frame getter:

```ts
legend.setOptions({
  statusLine: { volume: false, background: true, backgroundOpacity: 0.6 },
  status: () => ({ description: 'Apple Inc.', marketStatus: { text: 'Market open', color: '#26a69a' } }),
});
```

A field whose data is missing draws nothing whether its switch is on or off, and every switch defaults to the behaviour that predates it, so passing no options reproduces the old row exactly. Button ids (`${id}::row`, `${id}::hide`, `${id}::settings`, `${id}::close`) are unchanged by any of this.

## Context menu

```ts
chart.on('contextmenu', (e) => {
  const menu = e as ContextMenuEvent;
  menu.preventDefault();                 // suppress the browser menu
  showMenu(menu.point, menu.target);     // your DOM
});
```

| Field | Type | Notes |
|---|---|---|
| `paneIndex` | `number` | Pane under the pointer. |
| `point` | `{ x, y }` | Container media px, for placing the menu. |
| `price` | `number \| null` | `null` off the plot. |
| `time` | `number \| null` | UTC seconds; `null` when there is no data. |
| `index` | `number \| null` | Logical bar index. |
| `target` | `ContextMenuTarget` | `{ kind, id, instanceId?, plotKey?, seriesType?, side?, scaleId? }`. |
| `preventDefault` | `() => void` | Call it to show your own menu. |

`ContextMenuTargetKind` is `'drawing' | 'indicator' | 'legend' | 'primitive' | 'series' | 'price-scale' | 'time-scale' | 'empty'`. `instanceId` is set for `indicator` (feed it to `chart.removeIndicator` or your settings form), `seriesType` for `series`.

A plotted study series also supplies `plotKey`. Use it with `instanceId` when
opening an alert editor so a multi-plot study selects the clicked plot. Legend
hits omit `plotKey`; the host can choose a plot in that pane. Hidden series and
missing observations do not hit, and the last painted series wins an overlap.
Drawing and other primitive hits keep their priority over series.

**A `price-scale` hit says which axis it was.** `side` is the strip that was clicked (`'right'` or `'left'`), and `scaleId` is the scale that strip acts on: `'right'`, `'left'`, or `''` when the side carries no series of its own and the pane's values are all on the hidden overlay scale. Both are the arguments the `priceAxis*` calls below take, so pass them straight through instead of assuming pane 0's right scale.

**The time axis wins the bottom-left corner**, because it spans the full width and its dates run through it. The bottom-*right* corner stays the price axis', where its own labels run out. Plot hits are unchanged.

**With no listener the save-image snapshot stays as the fallback**, and it is restored when the last listener unsubscribes.

## A menu on one price axis

The chart-wide setters (`setPriceScaleOptions`, `setAutoScale`) are what a settings dialog wants. A menu raised on one axis strip is the other case: it names a pane and a scale, every item has to be readable back so the menu can draw its own checkmark, and an item that means nothing on this axis has to be visibly disabled rather than missing.

```ts
chart.on('contextmenu', (e) => {
  const ev = e as ContextMenuEvent;
  if (ev.target.kind !== 'price-scale') return;
  ev.preventDefault();

  const st = chart.priceAxisState(ev.paneIndex, ev.target.scaleId ?? 'right');
  if (st === null) return;                       // no such pane
  renderAxisMenu(ev.point, st);                  // your DOM
});
```

| Member | Returns | Notes |
|---|---|---|
| `priceAxisState(paneIndex = primaryPaneIndex(), scaleId = 'right')` | `PriceAxisState \| null` | Null for a pane that does not exist. |
| `setPriceAxisOptions(paneIndex, scaleId, patch)` | `void` | `Partial<PriceScaleOptions>`: mode, invert, margins, tick size. |
| `setPriceAxisAutoFit(paneIndex, scaleId, on)` | `void` | Turning it on releases any ratio lock on that axis. |
| `setPriceAxisLockRatio(paneIndex, scaleId, on)` | `boolean` | False when the lock could not be taken. |
| `movePriceAxis(paneIndex, from, to)` | `boolean` | `'right'` / `'left'`. False when the source side is empty or the target side is taken. |
| `PRICE_SCALE_MODES` | `readonly PriceScaleMode[]` | The four modes in the order a menu lists them. Exported from the package root. |

`PriceAxisState` is `{ paneIndex, scaleId, side, active, autoFit, inverted, mode, scaled, lockRatio, movable }`.

- **`active: false`** is a scale no series maps to: the ladder on an empty chart, or the side a menu was raised on before anything was plotted there. Render those rows **disabled with their state still visible**, not absent.
- **`scaled: false`** means nothing has measured the scale yet: it is still on its `0..1` placeholder. A ratio lock is refused there, because there is no price-per-bar to hold.
- **`movable`** is already the whole test (`scaleId` is a real side, this side carries series, the other side is free), so gate the move row on it rather than re-deriving it.
- **Moving an axis swaps the two side scales**, so range, mode, margins and formatter travel with it. The vacated strip starts again from the chart-wide defaults, the axis columns are recomputed (a strip no pane uses any more is released and the plot reclaims its width), a `priceAxisMoved` event is emitted (deprecated with `movePriceAxis`, removed in 3.0.0; placement emits `priceAxisPlacementChanged`), and a move onto an occupied side is refused: one strip draws one axis.
- **The ratio lock is real, not a stored flag.** The pane keeps the geometry the lock was taken at and rescales the visible span by height over bar spacing each frame, in transformed space, so a logarithmic axis holds its angle too. Auto-fit or `resetScale` releases it.

A menu that also offers reference levels (previous close, session high and low) drives a `PriceLevels` primitive; each level's line and axis tag are two flags in one group, and a level with no data reports `available(kind) === false`, which is the row to disable. See [primitives-and-plugins](primitives-and-plugins.md).

## Chart option accessors a dialog needs

| Member | Notes |
|---|---|
| `setCanvasOptions(patch)` / `canvasOptions()` | The block above. |
| `setNavigationOptions(patch)` / `navigationOptions()` | Mouse/pen pan direction and the initial/reset visible-bar count. |
| `setGridOptions(patch)` / `gridOptions()` | Grid alone. |
| `setStatusLineOptions(patch)` / `statusLineOptions()` | Applied to every legend. |
| `setPriceScaleOptions(patch, allScales = false)` / `priceScaleOptions()` | Defaults to the right scale of every pane; `allScales` includes left and overlay. Reads the price pane, pane 0 unless `movablePrimaryPane` let it move. |
| `setAutoScale(on)` | Every pane at once. |
| `setEvents(events, paneIndex = primaryPaneIndex())` / `setEventOptions(patch)` / `eventOptions()` | The chart-owned corporate-action strip; `ChartEventOptions` filters `earnings`, `dividend`, `split`, `news`, each defaulting to on. |
| `tradingSettings()` / `setTradingSettings(patch)` | Trading colours held on the chart, so reading them never instantiates the trade layer. |
| `primarySeries()` / `primarySeriesInfo()` | `{ type, style }` for the Price tab. |
| `setTimezone(zone)` / `timezone()` | IANA name behind the `time.timezone` control. |
| `setAxisChromeOptions(patch)` / `axisChromeOptions()` | The corner clock and the bar-close countdown, see [scales-and-panes](scales-and-panes.md). Merged field by field. |
| `priceAxisState(...)` and the four `setPriceAxis*` / `movePriceAxis` calls | One axis at a time, for the menu above. |
| `theme()` / `crosshairMode()` | Current values, for control defaults. |

## Persistence

`chart.getState()` returns `ChartState & ChartSettingsState`: the settings slice (`canvas`, `navigation`, `statusLine`, `trading`, `events`) rides beside `grid`, and `restoreState` applies it. Canvas lands **before** the panes, so a pane's own saved margins stay the more specific answer and win. Navigation is optional for older snapshots and restores before the explicit saved viewport. See [events-and-state](events-and-state.md).

## Related

- [scales-and-panes](scales-and-panes.md): price-scale modes, margins as fractions, the scale ids, axis chrome.
- [themes-and-styling](themes-and-styling.md): what the options fall through to, and the UI standard host chrome is held to.
- [primitives-and-plugins](primitives-and-plugins.md): `PriceLevels`, the reference levels a menu or dialog switches.
- [chart-types](chart-types.md): the Price tab's style keys per series type.
- [indicators](indicators.md): the `IndicatorInput` vocabulary these controls reuse.
