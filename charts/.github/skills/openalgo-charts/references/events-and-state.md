# Events and state

*When to read this: you are subscribing to chart events, building an app-side legend or toolbar, or saving and restoring a layout.*

## The bus

One bus covers everything, typed by `ChartEventMap` (2.6.0): an interface from `openalgo-charts` that names every event with its payload (`src/core/chart-events.ts`). The draw tier adds its `draw:*` and `drawing:*` names to it by declaration merging (`src/draw/events.ts`), so they are typed once `openalgo-charts/draw` (or the widget) is imported.

```ts
const off = chart.on('crosshair:move', (e) => { e.time; });   // e: CrosshairMoveEvent
off();                                  // unsubscribe

chart.once('ready', () => { /* fires exactly once */ });

chart.off('crosshair:move', handler);   // drop one listener
chart.off('crosshair:move');            // drop every listener for the name
```

- `on(event, cb)` returns its own unsubscribe function. `once(event, cb)` also returns one, so a pending one-shot can be cancelled before it fires.
- **The payload is typed by the name.** `chart.on('click', (e) => ...)` gives `e: ChartClickEvent`; a listener written as `(p: unknown) => ...` still fits. Do not cast a typed payload to an unrelated type: `p as Record<string, unknown>` on an interface payload no longer compiles (TS2352). Read the field, or cast via `unknown`.
- **A name outside the map** compiles through a string overload that is deprecated and goes in 3.0.0. For an event of your own, declare it once and it is typed everywhere:

```ts
declare module 'openalgo-charts' {
  interface ChartEventMap { 'myapp:signal': { price: number } }
}
chart.on('myapp:signal', ({ price }) => mark(price));
```

- A name list typed `string[]` falls to that overload too; write it `as const` so each name keeps its literal type.
- `emit(event, payload)` is **deprecated** (removed in 3.0.0): the bus carries the chart's own events. Announce an instrument with `setDataContext`, drive a link group with `LinkGroup.setSymbol`, `setInterval` and `setChartType`, and keep app events on your own emitter. Until 3.0.0 it still puts any name on the bus.
- **A throwing listener does not stop the others**, and nothing escapes to the engine that emitted. Since 2.6.0 the error goes to the platform's `reportError` (in a browser: the console and the window `error` event, as for a DOM listener) instead of vanishing; the trading bus (`chart.trading.on`) and `chart.shortcuts?.on` follow the same rule, and a trading listener that throws no longer stops the others or the chart-bus copy. The widget's own bus runs every listener and rethrows the first error afterwards.
- The listener set is copied before dispatch, so subscribing or unsubscribing from inside a handler is safe.
- Names: a new name is `namespace:action`, lower case, hyphen-joined, present tense (`objects:change`, `draw:preview-clear`). Older names keep their spelling (the camelCase pane and indicator events, single words, `trading:*` in snake case, `branding:changed`, `timezone:changed`, `alerts:changed`, `alerts:restored`).
- One payload shape per name. A name with nothing to report carries an empty object, typed `EmptyEvent`; `events:change` alone carries `undefined`.
- Named payload types, all type-only exports: `EmptyEvent`, `ChartHoverEvent`, `ChartDragCancelEvent`, `ChartViewportEvent`, `ChartResizeEvent`, `LazyLoadEvent`, `PaneEvent`, `PaneMovedEvent`, `PaneMaximizedEvent`, `PaneCollapsedEvent`, `PriceAxisPlacementChangedEvent`, `IndicatorInstanceEvent`, `IndicatorDataStatusEvent`, `TimezoneChangedEvent`, `PickStartEvent`, `PickEndEvent`, `AlertChangeEvent`, `AlertRemovedEvent`, `AlertErrorEvent`, `AlertsChangedEvent`, `AlertsRestoredEvent`, `TradingOrderModifyEvent`, `TradingBracketModifyEvent`, and from `openalgo-charts/draw` `DrawingEvent`, `DrawingListEvent`, `DrawingIdsEvent`, `DrawingIdEvent`, `DrawingToolEvent` and `DrawingModeEvent`. Any payload is also `ChartEventMap['name']`.

## Event catalogue

Primary source updates emit `data:update` with `ChartDataUpdate`:
`{ kind: 'update' | 'reset' | 'prepend', time?: number }`. Live updates name the
updated UTC bar time; resets include primary-series removal. Indicator and
secondary-series writes do not emit it. Read `chart.primaryBars()` for the
readonly source history without copying it. The event follows indicator
invalidation; `chart.indicators()` flushes studies when a host needs their values.

Every name on the bus. `ChartEventMap` is the source of truth: `tests/chart-event-map.test.ts` holds every emit and subscription in `src` to it with the compiler, so a name missing from the map fails the suite. The payload column names the exported type where there is one.

| Event | Payload | Fires when |
|---|---|---|
| `ready` | `{}` | Once, on a microtask after the constructor, a subscription on the next line still receives it. |
| `crosshair:move` | `{ time, index, price, bar, point: { x, y }, paneIndex, pressed, modifiers, pointerType, pressure, samples? }` | Pointer moves over the plot. `time`/`bar` are `null` off the data. `pressed` is true while a pointer is down; `samples` (container x, pane-local y, pressure per coalesced position) is present only then, which is how a freehand stroke reads its trail in placement mode. |
| `crosshair:move` (leave) | `{ time: null, index: null, price: null, bar: null, point: null, paneIndex: null }` | Pointer leaves the plot. Note: no `pressed` key on this payload. |
| `crosshair:readout` | `CrosshairMoveEvent` | Every crosshair position a readout shows: the pointer's, and a linked chart's (`source: 'linked'`, `point: null`), clearing included. See [Readout observers](#readout-observers-253). |
| `click` | `{ id, price, time, paneIndex, point: { x, y }, shiftKey, ctrlKey, metaKey, modifiers, pointerType, pressure, viaDrag? }` | A clean click anywhere in the plot. `id` is the hit primitive's `externalId`, or `null` on empty plot. `pressure` is the press pressure (a release always reads 0). The flat `shiftKey`, `ctrlKey` and `metaKey` are deprecated and go in 3.0.0: read `modifiers`. |
| `dblclick` | `DoubleClickEvent`: `{ paneIndex, x, y, handled }` | Plot double-clicked. The chart then resets the scale (or maximizes the pane, per `doubleClick`), unless a drawing tool is active or a listener set `handled = true`. |
| `hover` | `{ id }` | Pointer enters (`id` = `externalId`) or leaves (`id` = `null`) a hit-testable primitive. State-change rate, not pointer rate. |
| `drag:start` | `ChartDragEndEvent`: `{ id, price, time, paneIndex, point, modifiers, pointerType, pressure }` | A primitive press arms a drag, before any movement. |
| `drag` | `{ id, price, time, paneIndex, fromPrice, fromTime, point, samples, modifiers, pointerType, pressure }` | A draggable primitive is being moved. `from*` is the grab origin, so deltas start at the press. `point` is container x with y local to the grabbed pane even after crossing a pane boundary; `samples` lists every coalesced position since the last move in that space, the last one equal to `point`. |
| `drag:end` | `{ id, price, time, paneIndex, point, modifiers, pointerType, pressure }` | The drag gesture released. |
| `drag:cancel` | `{ id, paneIndex, reason: 'pointercancel' \| 'pinch' \| 'escape' }` | The gesture was cancelled. Discard transactional drafts. For existing hosts, pointer cancellation still sends `drag:end` afterwards. Pinch and opt-in Escape discard the gesture without an end. Escape requires `PrimitiveHit.cancelOnEscape: true`; existing primitives retain their release path. |
| `pan` | `{ from, to, logicalFrom, logicalTo }` | The user pans, **or** a programmatic move that changed the window without changing its span. |
| `zoom` | `{ from, to, logicalFrom, logicalTo }` | Wheel or pinch zoom, **or** a programmatic move that changed the span. |
| `resize` | `{ width, height }` | Container size changed (CSS px); also emitted by an explicit `applySize` that actually changes size. |
| `renderer:fallback` | `RendererFallbackEvent`: `{ from, to: 'canvas2d', reason: 'context-lost' \| 'unavailable' }` | Once per chart, when a GPU render backend lost its context or its device turned out unusable. Every pane is on `canvas2d` for the rest of the session and `chart.rendererKind` already reads it. See [core-api](core-api.md#render-backends). |
| `lazy-load` | `{ from, to, direction: 'backward' }` | The viewport neared the oldest bar and the history loader ran. |
| `paneAdded` | `PaneEvent`: `{ paneIndex }` | A pane was created, after the relayout, so a listener reads settled geometry. |
| `paneRemoved` | `PaneEvent`: `{ paneIndex }` | A pane was removed. |
| `paneMoved` | `{ from, to }` | A pane swapped position with its neighbour, the price pane included on a chart built with `movablePrimaryPane`. `setPrimaryPaneIndex` and a restore that moves the price pane emit one per step; read `primaryPaneIndex()` after one rather than assuming slot 0. |
| `paneMaximized` | `{ paneIndex }` | A pane was maximized; `paneIndex` is `null` when un-maximizing. |
| `paneCollapsed` | `{ paneIndex, collapsed }` | A study pane folded to its header strip (`collapsed: true`) or opened again, through `setPaneCollapsed`, its legend's collapse button or a host menu. Collapsing the maximized pane first emits `paneMaximized` with `null`. |
| `paneResized` | `{ paneIndex }` | A pane-divider drag released. |
| `priceAxisMoved` | `{ paneIndex, from, to }` | Deprecated, removed in 3.0.0 with `movePriceAxis`, the only call that emits it: listen for `priceAxisPlacementChanged`, which `setPriceAxisPlacement` emits. `movePriceAxis` succeeded: a pane's prices and their scale changed strip. Re-read `priceAxisState` for any menu still open on that axis. |
| `priceAxisPlacementChanged` | `{ paneIndex, scaleId, side, order }` | `setPriceAxisPlacement` moved or reordered a price scale's column. The scale keeps its id; `side` and `order` are where it now draws. |
| `layout:change` | `LayoutChangeEvent`: `{ setter }`, a `LayoutSetter` | A setter that changes what `getState` saves, and has no event of its own, has run: `setPaneWeight`, `setPriceAxisOptions`, `setPriceAxisAutoFit`, `setPriceAxisLockRatio`, `setPriceScaleOptions`, `setAutoScale`, `setGridOptions`, `setCanvasOptions`, `setStatusLineOptions`, `setWatermarkOptions`, `setTradingSettings`, `setAxisChromeOptions`, `setEventOptions`, `setNavigationOptions` (since 2.6.0; the pan and zoom switches also fire `objects:change`) or `applyOptions`, which the crosshair magnet shortcut goes through since 2.6.0. Once per outermost call, after the change is applied (`setCanvasOptions` setting the grid on its way is one event); nothing for a call naming no pane the chart has, and nothing during a restore, which has `state:restore:start` and `state:restore:end`. Setting a value to what it already was still fires, so compare if that matters. The hook for saving a layout or recording an undo step outside a transaction. |
| `indicatorRemoved` | `{ instanceId, indicatorId, paneIndex }` | An indicator instance was removed (legend button or `removeIndicator`). |
| `indicatorSettings` | `IndicatorInstanceEvent`: `{ instanceId, indicatorId, paneIndex }` | The legend's settings button was clicked. The engine ships no form, render your own. |
| `indicatorSource` | `IndicatorInstanceEvent` | The legend's source button of a descriptor with `hasSource: true` was clicked. |
| `indicator:alert` | `IndicatorAlertPayload` | A condition a study descriptor declared came true on a live bar. See [indicators](indicators.md). |
| `indicator:data-status` | `IndicatorDataStatusEvent`: `{ id, indicatorId, status }` | A study's managed data state changed (loading, ready, empty, unsupported, error). |
| `objects:change` | `EmptyEvent`: `{}` | The primary source or indicator inventory/state changed, including indicator settings and visibility, and the pan or zoom switches of `setNavigationOptions`. Re-read the inventory; this is an invalidation event, not an object snapshot. Always `{}` since 2.6.0 (the navigation switches sent `undefined` before). |
| `events:change` | `undefined` | Chart-owned timeline events, their type visibility or group visibility changed. |
| `event:click` | `ChartEventClick` | A chart-owned timeline badge was clicked. |
| `style:change` | `LinkAppearanceValues` | `applyChartSettings` applied appearance a link group mirrors (the widget's undo history re-announces a step's result). |
| `timezone:changed` | `TimezoneChangedEvent`: `{ timezone }` | `setTimezone` changed the chart's clock. |
| `branding:changed` | `BrandingChangedEvent` | The brand mark changed: its options, or `false` when removed. |
| `data:context` | `Readonly<ChartDataContext> \| undefined` | `setDataContext` changed the instrument, interval or variant. |
| `data:update` | `ChartDataUpdate` | The primary source was written (see above). |
| `data:range` | `EmptyEvent` | Studies were invalidated because the primary bars or the clock they read changed; a write fires it before `data:update`. |
| `data:requests` | `EmptyEvent` | `setBarsProvider` changed the provider or `invalidateRequestedData` ran; studies that fetch ask again. |
| `state:restore:start` / `state:restore:end` | `EmptyEvent` | `restoreState` began and finished. |
| `drawings:restore` | `unknown` (the saved drawings document) | A restore hands the draw tier its drawings, before empty study panes are pruned. |
| `alerts:restore` | `AlertsDocument` | A restore hands an `AlertController` its alerts. |
| `pick:start` / `pick:end` | `PickStartEvent` / `PickEndEvent`: `{ kind }` / `{ kind, value }` | `beginPick` started, then resolved or was cancelled (`value: null`). |
| `alert:created`, `alert:updated`, `alert:expired` | `AlertChangeEvent`: `{ alert }` | An `AlertController` reports a change. See [alerts](alerts.md) for these and the rest: `alert:removed` (`AlertRemovedEvent`), `alert:triggered` (`AlertTriggeredPayload`), `alert:error` (`AlertErrorEvent`), `alerts:changed` (`AlertsChangedEvent`), `alerts:restored` (`AlertsRestoredEvent`) and `alerts:checkpoint` (`EmptyEvent`). |
| `contextmenu` | `ContextMenuEvent`: `{ paneIndex, point, price, time, index, target, preventDefault }` | The chart was right-clicked, axis strips included. `target.kind` classifies what is under the pointer, and a `price-scale` hit adds `side` and `scaleId` for the axis it names. With no listener the save-image snapshot stays as the fallback. See [settings-and-menus](settings-and-menus.md). |
| `replay:start` | `ReplayState` | The first frame a `ReplayController` applies. |
| `replay:frame` | `ReplayState` | Every playhead move: seek, step, and each played bar. |
| `replay:play` / `replay:pause` | `ReplayState` | Playback armed or halted. |
| `replay:end` | `ReplayState` | The playhead reached the last bar (also emitted by `play()` called there). |
| `replay:stop` | `ReplayState` | Replay was left; data and viewport are already restored. |
| `trading:order_modify` | `TradingOrderModifyEvent`: `{ orderId, newPrice, previousPrice }` | An order line was dragged and released. |
| `trading:order_cancel` | `{ orderId }` | An order's cancel box was clicked. |
| `trading:order_click` | `{ order }` | An order pill was clicked. |
| `trading:position_close` | `{ positionId }` | A position's close box was clicked. |
| `trading:position_click` | `{ position }` | A position pill was clicked. |
| `trading:bracket_modify` | `TradingBracketModifyEvent`: `{ parentId, bracketRole, newPrice }` | A bracket leg (TP/SL) was dragged. |
| `draw:tool` | `DrawingToolEvent`: `{ tool, space? }` | A drawing tool was armed or disarmed (`null`). `space: 'viewport'` is present only while the armed tool places a drawing pinned to the screen (`setTool(id, { space: 'viewport' })`); `activeToolSpace()` reads the same. Drawing tier only. |
| `draw:add` | `DrawingEvent`: `{ drawing, history? }` | A drawing was created. `history: true` when an undo or redo step brought it back. Drawing tier only. |
| `draw:update` | `DrawingEvent` | A drawing's points, style, text, props or flags changed. Fires once per drawing, so a multi-drag emits one per member. Drawing tier only. |
| `draw:remove` | `DrawingEvent` | A drawing was deleted. Drawing tier only. |
| `draw:select` | `DrawingIdEvent`: `{ id }` | Selection changed; `id` is the primary (first picked) id, `null` on deselect. Drawing tier only. |
| `drawing:select` | `DrawingIdsEvent`: `{ ids }` | The whole selection in pick order, empty on deselect. Fires with `draw:select`, and only when the selection actually changed. Drawing tier only. |
| `drawing:change` | `DrawingChangeEvent`: `{ ids, kind, linked?, step? }` | One event per model mutation, after the per-drawing `draw:*` events; `kind` is `'add' | 'update' | 'remove' | 'reorder'`, or `'undo' | 'redo'`. `ids` is empty for an undo step that changed no drawing (a study input anchor's drag), so an Undo control still refreshes. Drawing tier only. |
| `draw:copy` | `DrawingListEvent`: `{ drawings }` | A copy reached the clipboard (deep copies, not the live objects). Drawing tier only. |
| `draw:cut` | `DrawingListEvent` | A cut wrote **and then** deleted. A refused write emits nothing. Drawing tier only. |
| `draw:paste` | `DrawingListEvent` | The newly created drawings, after their own `draw:add` events. Drawing tier only. |
| `draw:preview` / `draw:preview-clear` | `DrawingListEvent` / `DrawingIdsEvent` | Where a drag is carrying drawings before it commits (copies), then the end of that preview. Drawing tier only. |
| `draw:restore` | `EmptyEvent` | `fromJSON` or a chart restore replaced every drawing. Drawing tier only. |
| `draw:destroy` | `{ controller }` | A `DrawingController` was destroyed and let go of the chart. Drawing tier only. |
| `draw:measure` / `draw:eraser` | `DrawingModeEvent`: `{ active }` | The measure gesture or the eraser switched on or off. Drawing tier only. |
| `drawing:hover` | `DrawingIdEvent`: `{ id }` | The unselected drawing under the pointer changed (`null` when none). Drawing tier only. |
| `destroy` | `{}` | `chart.destroy()` finished. Emitted last, with the chart already torn down, then every listener is dropped. |
| `symbol` | `{ symbol, exchange? }` or a bare string | **Host-emitted, never by the core** (the widget emits it). A link group and a draw-tier `DrawingLinkGroup` follow it. See [chart-linking](chart-linking.md). |
| `interval` / `chartType` | `{ interval }` / `{ chartType }`, or a bare string | **Host-emitted, never by the core.** A link group follows them. `LinkGroup.setInterval` and `setChartType` are the imperative twins, and the way to do it from 3.0.0, when `chart.emit` goes. |

Notes:

- `from` / `to` on `pan`, `zoom` and `lazy-load` are **UTC seconds**, or `null` when that edge falls outside loaded data. `logicalFrom` / `logicalTo` are raw fractional logical indices.
- `pan` and `zoom` short-circuit entirely when nobody is subscribed, so leaving them unsubscribed costs nothing.
- **`pan` and `zoom` are not gesture-only.** `setVisibleLogicalRange`, `fitContent`, `resetScale` and the keyboard pan/zoom commands emit them too, so a linked grid follows an arrow key or a restored zoom. They emit **nothing** when the window did not actually move (a clamped zoom, an already-fitted `fitContent`), and the choice between the two names is made by whether the span changed. `panUp` / `panDown` move a price scale rather than the time window and emit nothing.
- **`destroy` is for letting go, not for reading.** By the time it fires, `chart.isDestroyed` is true and the panes are gone. Use it to unsubscribe, drop the chart from a link group, or release a controller; `destroy()` itself is idempotent, so a second call re-emits nothing.
- **`draw:*` and `drawing:*` are two granularities, both kept.** `draw:add`, `draw:update` and `draw:remove` fire once per drawing and carry it; `drawing:change` fires once per mutation, after them, with the ids. `draw:select` names the primary selection, `drawing:select` the whole of it, and both fire together. Render one drawing's properties from the first family; refresh a list or an undo control from the second.
- **`trading:*` names carry the prefix on both buses.** `chart.on('trading:order_modify', cb)` and `chart.trading.on('trading:order_modify', cb)` are equivalent; `chart.trading.on('order_modify', cb)` never fires.
- **`crosshair:move`, `pan`, `zoom` and `drag` fire at pointer rate.** Do only light work in the handler; defer anything heavy to rAF or a debounce.
- Typed alternatives exist for three of these and coexist with the bus: `chart.subscribeCrosshairMove(cb)` (`CrosshairMoveEvent`), `chart.subscribeClick(cb)` (hit-only, `cb(externalId)`), `chart.subscribeDrag(onDrag, onDragEnd)` (`(id, price, time)`). Since 2.6.0 each takes several subscribers and returns an unsubscribe; before, a second call replaced the first.
- Keyboard shortcuts are **not** on this bus, subscribe via `chart.shortcuts?.on(cb)`. See [interactions](interactions.md).

## Object inventory lifecycle

The base-tier `ChartObjects` combines source, indicator and drawing events with
explicit provider subscriptions. Use `objects.subscribe(listener)` for one
immutable inventory delivered immediately and after changes; avoid reconstructing
the list from each event payload. The model follows `objects:change`, indicator
removal/data status, pane changes, data context, and drawing changes/selection.
It also disposes itself on chart destruction. See
[core-api](core-api.md#object-inventory-and-management).

The callback's `ChartObjectSnapshot.id` is the inventory identity, while `sourceId`
is the existing subsystem's identity. Removal or replacement can invalidate an ID;
read the latest snapshot after removal or template replacement. Workspace restore
preserves saved indicator instance IDs. `objects.destroy()` and the disposer returned by `subscribe`
release observations without removing chart objects. Drawing actions still pass
through the drawing controller's undo history. Host provider state needs its own
subscription or an explicit `objects.refresh()` after a host-side change.

## getState and restoreState

`chart.getState(): ChartState & ChartSettingsState` returns a JSON-safe snapshot; `chart.restoreState(state, options?: ChartRestoreOptions): RestoreReport` puts it back. The widened return type is still a `ChartState` to every existing consumer.

`ChartRestoreOptions.preserveScaleFormats` selects existing `{ paneIndex, scaleId }`
targets whose runtime formatter callback or default formatter must survive automatic
study-series recreation. Numeric saved scale settings still apply. Invalid or absent
targets reject before mutation. No callbacks are serialized, and later explicit
settings/formatter changes retain normal behavior. Forward the workspace template
planner's `restoreOptions` when applying its state patch. Omitted options preserve
ordinary full-restore semantics.

A synchronous newer restore from `state:restore:start` supersedes the older call,
which returns `applied: false`. Hosts must not roll back over that newer state.

| Captured in `ChartState` | Restored |
|---|---|
| `version` (`CHART_STATE_VERSION`, now `2`) | validated; a state newer than the build is refused. `getState()` writes `1` unless the price pane has moved, so a layout with the price pane on top is written exactly as before and every older reader still opens it |
| `viewport` `{ from, to }` (logical range), `barSpacing` | yes, viewport only when the chart already has data |
| `grid` `{ vertLines, horzLines }` plus the grid style keys | yes |
| `canvas` (grid, crosshair, scales, margins), `statusLine`, `trading` colours, `events` filters | yes; `canvas` is applied **before** the panes, so a pane's own saved margins are the more specific answer and win |
| `navigation` (`mousePan`, `defaultVisibleBars`, optional `defaultBarSpacing`) | yes; controls pointer panning and the initial/reset view. Positive spacing selects CSS pixels per bar. An explicitly restored viewport takes precedence until reset |
| `crosshairMode` `'normal' \| 'magnet'` | yes |
| `timezone` (IANA name) | yes, but a name this runtime does not recognise is **skipped**, not thrown, so one stale zone cannot cost the whole layout |
| `panes[]`: `weight`, right `priceScale`, optional secondary `scales`, optional `collapsed` | yes; every scale retains margins, `minMove`, optional `minPrecision`, mode, inversion, auto-scale, manual `range`, declared `fixedRange` and `ratioLock` geometry. `collapsed: true` is written only for a folded pane; a pane saved without it restores open, and the price pane always restores open. A restore that lists panes or rebuilds studies also opens a pane it does not list |
| `primaryPane` (version 2 only) | yes: the slot of the price pane in `panes`, written only when it is not `0`. Every `paneIndex` in a state (panes, series, studies, drawings) is a visual slot, so this says which one is the price pane. Omitted with `panes` present means slot `0`, which is how an old layout loads unchanged. It needs `panes` and must name one of them, it is refused in a version 1 state, and a slot other than `0` is refused by a chart built without `movablePrimaryPane`; each refusal comes before anything is applied. A restore without `panes` leaves the price pane where it is |
| `indicators[]`: `{ indicatorId, instanceId?, settings, paneIndex, visible?, policy?, barSource? }` | yes, replaced not appended; saved identities are stable, legacy entries receive new IDs. `policy` holds only a study's restrictions (`IndicatorPolicy` flags that are false) and is omitted for an unrestricted study; a malformed one refuses the restore before anything applies. `barSource` is written only as `'underlying'`, for a study on the bars under a transformed chart; an unknown value refuses the restore |
| `sourceAbove` | yes, with `indicators`: the instance id of the study the price source paints directly above, written only after the source was moved over a study (`chart.moveInSeriesStack`). Without it the source paints behind the restored studies, as in every older layout; a non-string refuses the restore |
| `drawings` | round-tripped opaquely; only present when a drawing state has been set. Emitted to the draw tier (`drawings:restore`) before empty study panes are pruned, so a pane the restore removes shifts restored drawings with every other pane. The draw tier writes a `DrawingsDocument` (`{ version: 2, drawings }`) here, without transient drawings (`policy.persistent: false`), and reads a 1.9.x bare array too |
| `alerts` | optional `AlertsDocument`; lifecycle, scope, anchors and consumed bars survive reload; unsupported runtime payloads reject serialization |
| `series[]`: `{ type, style, paneIndex, priceScaleId, transform? }` | **no**, reported back to you. `transform` is the `SeriesTransformSpec` the chart applies, written only for a series that has one |
| series **data** | **no**, never captured |

**`restoreState` never recreates host source series.** It rebuilds registered indicator outputs. The returned descriptors include both kinds, so use the host's source manifest when rebuilding and feeding price, volume or comparison series.

Indicator visibility is saved with its instance settings. Drawing visibility and
lock remain in the drawing document. `ChartObjects` provider callbacks, profile
data and profile state are host-owned and are not serialized; re-register them
after chart replacement and persist them separately when needed.

`PaneState.priceScale` remains the right-axis field for older readers;
`PaneState.scales` is keyed by secondary `PriceScaleId`. `PriceScaleState.ratioLock`
contains `{ barSpacing, height }` paired with the saved manual range, preserving
its proportion when the restored chart has a different size. `Pane.scaleStates()`
returns detached snapshots of its existing scales, including the right scale;
`Pane.clearRatioLocks()` releases its locks without changing ranges.

`parsePaneState(value, allowLegacyPartial = false)` validates and copies a pane
snapshot, throwing on invalid settings, including a `collapsed` flag that is not
a boolean. The optional legacy mode supplies defaults
for missing primary-scale settings; secondary settings remain complete. Both
chart restoration and workspace parsing use it. Layouts cannot serialize runtime
formatter functions or a price scale's data-derived baseline.

`RestoreReport`:

| Field | Type | Meaning |
|---|---|---|
| `applied` | `boolean` | False when the payload was rejected. |
| `series` | `SeriesState[]` | Descriptors found in the state. |
| `indicators` | `number` | Instances actually recreated. |
| `reason` | `string?` | Set only on rejection. |

Rejection is total, never partial: a non-object, or one without a numeric `version`, gives `reason: 'not a chart state object'`; a `version` greater than `CHART_STATE_VERSION` gives `state version N is newer than M`. An **older** version is accepted. `CHART_STATE_VERSION` is `2` and is exported from the package root; since `getState()` still writes `1` for a chart whose price pane is on top, a host validating a saved state should refuse only `version > CHART_STATE_VERSION`, never demand equality.

**An indicator whose tier was never imported is skipped, not thrown.** `restoreState` checks `hasIndicator(id)` and moves on, so a layout saved with `openalgo-charts/indicators` loaded still restores everything else in an app that omits the tier. Empty positive panes are then removed. A pane containing a live study or host primitive survives even with no series, including studies that render only levels or perform calculations without plots.

**Restore the viewport after your data lands.** Logical ranges index bars, so `viewport` is skipped entirely while `dataLayer.length === 0`. Calling `restoreState` a second time is safe and idempotent, indicators are removed and rebuilt, not duplicated.

## Save and restore a layout

```ts
// Save
localStorage.setItem('layout', JSON.stringify(chart.getState()));

// Restore
const saved = JSON.parse(localStorage.getItem('layout') ?? 'null');

const report = chart.restoreState(saved);          // 1. grid, panes, scales, indicators
if (report.applied) {
  for (const s of report.series) {                 // 2. rebuild series, yours to feed
    const series = chart.addSeries(s.type, {
      paneIndex: s.paneIndex,
      style: s.style,
      priceScaleId: s.priceScaleId,
    });
    series.setData(await loadBars(symbol, interval));
  }
  chart.restoreState(saved);                       // 3. viewport, now that bars exist
} else {
  console.warn('layout rejected:', report.reason);
}
```

## Drawings ride along

`ChartState.drawings` is an opaque slot. The base engine only stores and returns it:

```ts
chart.drawingState();          // read the slot
chart.setDrawingState(value);  // write it
```

`DrawingController` (`src/draw/controller.ts`) drives both ends automatically: it reads `chart.drawingState()` in its constructor and restores anything it finds, and it writes `chart.setDrawingState(this.toJSON())` after every mutation. So an app that already persists `getState()` keeps drawings for free once the tier is loaded, no extra storage plumbing.

Restoration emits `drawings:restore` before `alerts:restore`. Attached controllers
restore automatically in that order; do not repeat `fromJSON` afterward.
`state:restore:start` and `state:restore:end` bracket the operation so transient
inventory changes cannot evaluate alerts or delete anchors prematurely.
Invalid alert documents and duplicate study identities reject before mutation.
Missing restored drawing or plot anchors emit removal reasons. See
[drawing-tools](drawing-tools.md) and [alerts](alerts.md).

## Related

- [core-api](core-api.md), `createChart`, `applyOptions`, viewport methods, `destroy`.
- [data-and-time](data-and-time.md), history paging behind `lazy-load`.
- [trading](trading.md), the `trading:*` data model.
- [indicators](indicators.md), `indicatorSettings` and building a settings form.
- [replay-and-compare](replay-and-compare.md): the `replay:*` payload, and the comparison controller's own state.
- [settings-and-menus](settings-and-menus.md): the settings slice of the state, and the `contextmenu` target.
- [react-integration](react-integration.md), unsubscribing on unmount.


## Readout observers (2.5.3)

`crosshair:readout` carries `CrosshairMoveEvent` for both physical and linked
crosshairs, including clearing. Unlike the single setCrosshairMoveHandler callback,
multiple chart.on subscriptions can observe it. `crosshair:move` retains its
physical-pointer semantics for linking. `timezone:changed` reports `{ timezone }`
after setTimezone changes the chart calendar. Dispose subscriptions with the host.
