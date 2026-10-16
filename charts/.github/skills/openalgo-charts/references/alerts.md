# Trader-created alerts

`AlertController` is a headless base export. Construct one per chart. It owns
evaluation and expiry, while the host owns notification, sound or webhook
delivery. No event sends an order. `chart.destroy()` destroys its controller;
explicit `alerts.destroy()` unsubscribes and releases the chart for a new owner.

```ts
import { AlertController, type AlertTriggeredPayload } from 'openalgo-charts';

chart.setDataContext({ symbol: 'CONTRACT', exchange: 'DERIVATIVES', interval: '1m' });
const alerts = new AlertController(chart);
const record = alerts.add({
  source: { kind: 'price', price: 100 },
  condition: 'crossingUp',
  policy: 'onBarClose',
  repeat: 'once',
  message: 'Confirmed close crossed the level',
  payload: { route: 'host-owned' },
});
const off = chart.on('alert:triggered', value => {
  const event = value as AlertTriggeredPayload;
  showNotification(event.message ?? event.title);
});
alerts.disable(record.id);
alerts.enable(record.id);
alerts.update(record.id, { source: { kind: 'price', price: 110 } });
alerts.remove(record.id);
off();
```

## Model and methods

`AlertInput` accepts an optional unique id, `AlertSource`, `AlertCondition`,
`AlertPolicy`, `AlertRepeat`, initial armed/disabled state, title, message,
nonnegative cooldownSeconds, UTC-seconds expiresAt, and opaque payload.
`AlertSource` is a union of `PriceAlertSource`, `IndicatorAlertSource` and
`BarConditionAlertSource` and `DrawingAlertSource`. A fixed price uses
`{ kind: 'price', price, upperPrice? }`; an indicator plot uses
`{ kind: 'indicator', instanceId, plotKey, value, upperValue? }`; a named
predicate uses `{ kind: 'barCondition', id }`.
A drawing uses `{ kind: 'drawing', drawingId, level?, input? }`.
`AlertScope` captures symbol, exchange and interval from chart data context,
and `variant` when the chart shows a non-default data variant (none for the
default series, so existing scopes and documents are unchanged).
Set that context before creating alerts; alerts do not migrate to a new market.
An alert evaluates only on its own variant, like its own interval, and
`availability` asks for that variant. A fixed price level stays visible, paused,
on another session or adjustment of the instrument, but not in another currency
or unit, where the same number is another price. `parseAlertsDocument` refuses
a scope variant this build cannot name.
From 2.5.0, price-source levels remain visible across intervals for the same
symbol and exchange. On another interval they show the original timeframe;
armed levels are paused and cannot drag. Triggered, disabled and expired levels
retain their lifecycle badge. Study/drawing visuals still require the original
scope. Evaluation for every source and policy remains original-interval-only;
`availability` names the required timeframe. This does not provide background
evaluation of an unseen interval. Hosts needing that must feed a separate
evaluator and own delivery once.

Clear primary bars before changing context, then load the new source. Only
matching-scope bars can seed an alert's evaluated-bar checkpoint. Restore and
returning to the original interval seed silently without replaying history.

`Alert` is the normalized record, with a required id, defaults, scope,
`AlertState` and optional lastTriggeredAt (UTC delivery seconds) and
lastTriggeredTime (bar UTC seconds). `AlertState` is armed, triggered, disabled
or expired. Once alerts keep a triggered record and show its line by default. Every-time alerts stay armed.
`list()` and returned records detach mutable configuration; payload remains
opaque and retains its original reference.

`add(input)` returns an Alert. `update(id, AlertPatch)`, `enable(id)` and
`disable(id)` return the changed Alert or undefined for an unknown id.
`remove(id)` returns whether it removed a record. `setPaused(boolean)` controls
an explicit host pause independently of replay. Resuming seeds observations
silently. Unknown ids do not create records. Invalid edits are rejected before
changing the stored record. Duplicate controllers on one chart are rejected.

`AlertControllerOptions.now` optionally supplies a clock in UTC seconds for
expiry and cooldown, defaulting to Date.now()/1000. One timer follows the next
armed expiry, including on an idle feed. Disabled and once-triggered records do
not keep an expiry timer. Destruction cancels it.
`AlertChartHost` is the structural chart interface, allowing a host integration
without a nominal dependency on a specific bundled Chart class. Its optional
`primaryPaneIndex()` names the price pane's slot: price alerts draw there, a study
alert on an `overlay` plot reports it, and a drawing on it needs no input plot.
Without it the price pane is slot 0.

## Finished alert lines

From 2.5.1, construct `new AlertController(chart, { spentLines: 'hide' })` to
hide triggered and expired lines while retaining records and runtime state.
The default is `'show'`. Armed, repeating and disabled lines retain their normal
appearance; `enable(id)` re-arms a spent alert and restores its line. Clear or
extend an elapsed `expiresAt` before re-arming an expired record.

This is a constructor policy, not part of `toJSON()`. Pass it again when
recreating the controller. Preserve the full saved document; deleting a spent
record to hide its line loses its once-only firing protection. Hiding an alert
anchored to a drawing does not remove the drawing. `visuals: false` still hides
all alert visuals. The packaged widget and yfinance keep the default display;
this option is for hosts that construct their own controller.

## Editor schema and widget ownership

`alertSettingsSchema(source, condition?)` returns readonly `IndicatorInput`
fields for the supported conditions, numeric bounds, timing, repetition,
cooldown, expiry, message and enabled state. A drawing `band` offers entering
and leaving range; a single drawing level offers numeric line conditions.
Named candle predicates offer only matches. No DOM is imported by this schema.

`createWidget` owns `widget.alerts`; do not create a second AlertController on
its chart. `widget.openAlerts()` opens the live list, and the widget tier exports
`mountAlertEditor` and `mountAlertsPanel` for custom host composition. The editor
defaults to confirmed bar-close evaluation. Cancel discards drafts. Editing a
triggered record leaves it triggered unless Enabled is explicitly changed.

Persistence is opt-in through the widget's existing `persist` option. A triggered
record remains visible after reload, without another delivery. Automatic save
reports nonportable payloads through the widget status event and still permits
cleanup; an explicit `getState()` continues to reject invalid portable data.

## Conditions and timing

`AlertCondition` accepts crossing, crossingUp, crossingDown, greaterThan,
lessThan, enteringRange and leavingRange. Range conditions require two finite,
ordered bounds; boundaries count as inside. Closed crossing-up uses previous
close <= price and confirmed close > price; crossing-down uses the inverse.
Zero is a valid threshold. Non-finite thresholds and negative cooldowns fail.

`AlertPolicy` defaults to onBarClose. The next live primary bar confirms the
previous tail, and the controller evaluates that closed bar, never history
loaded through setData or prependData. `AlertRepeat` defaults to once.

One `data:update` that appends several bars after the tail an alert
last saw is judged bar by bar, every alert at one bar before any moves to the next,
exactly as separate appends would be: a source bar completing several Renko bricks
(the other transforms add at most one element per source bar), or an
`AlertChartHost` that writes several bars before emitting. Each bar the update
closes is confirmed in order, and each match carries its own bar's `time` and
`index`. The newest stays forming until a newer bar follows it. A tail revised in
the same update is judged first, as a tick; a forming element dated again (a Kagi
vertex, a range bar) keeps its place. Repeat, cooldown and expiry apply per bar as
for separate appends at one instant. An update that leaves fewer bars, or moves the
tail because history changed, is judged once at the newest bar against the last
tail seen, as before. Reloads, prepends, late corrections and context changes still
seed silently, and a corrected bar is never judged.

onTouch observes newly reached extrema and the path between observed closes.
A wick already present when arming or resuming is not a fresh touch. An intrabar
trigger may disappear from the final candle: choose this policy explicitly when
that tradeoff is intended. At most one match per alert/bar is consumed, even if
cooldown suppresses delivery. An old wick cannot trigger when cooldown expires.

Replay, context mismatches, late historical updates and history loads suppress
delivery. Moving history backwards does not make a consumed bar new again.
At or after expiresAt, expiry takes priority over a new trigger.

## Indicator and candle conditions

An indicator alert identifies a specific instance and plot key. Two instances
of the same descriptor stay separate. Thresholds are in plot units. Intrabar
checks use changes in the plot's values, never primary price wicks; closed
checks use adjacent confirmed plot readings. Missing readings are unavailable,
and a gap cannot become a synthetic zero or a crossing across missing data.
Study edits reseed observation instead of masquerading as market movement.

`availability(id)` returns `AlertAvailability`: available, an optional reason,
and paneIndex when resolved. Context mismatch, replay or host pause, missing
instance/plot/condition, empty history and missing plot values report why the
alert cannot currently evaluate. This is separate from lifecycle state.
Plot reads flush indicators through the public chart accessor when needed;
confirmed-only alerts do not flush on each forming-bar update.

Named conditions use condition `matches` (the default for that source), with
the same timing, repetition, cooldown and expiry controls. Numeric condition
choices are rejected for this source. The built-ins are:

| Id | Meaning |
| --- | --- |
| bullish | Close exceeds open |
| bearish | Close is below open |
| inside | High is strictly below the preceding high and low strictly above the preceding low |
| outside | High strictly exceeds the preceding high and low is strictly below the preceding low |
| gap-up | The entire bar lies above the preceding high |
| gap-down | The entire bar lies below the preceding low |

`registerBarCondition(BarCondition)` registers a unique id, title and
`when(BarConditionContext)` predicate. `getBarCondition(id)` returns its readonly
descriptor or undefined. `registeredBarConditions()` returns the available
readonly descriptors. `unregisterBarCondition(id)` returns whether it removed
one; alerts referring to it then report unavailable. Register custom conditions
before restoring their alerts. Runtime functions stay in the registry, while
alert records store only their stable ids.

The context exposes `{ bars, index }`, with bars ending at the evaluated bar.
A confirmed-bar predicate cannot inspect the next forming bar. onTouch runs a
predicate on live updates of the forming bar; its result can change before
close. A throwing predicate emits alert:error once for that bar and does not
prevent other alerts from evaluating. Treat context and descriptor data as
readonly; delivery and other effects belong in event listeners.

## Drawing anchors and visible levels

Pass the active DrawingController as `new AlertController(chart, { drawings: draw })`.
The structural `AlertDrawingProvider` needs get(id), valueAt(id, time, level?)
and alertInfo(id), so the base never imports the drawing tier. Destroy this alert
controller when replacing that drawing controller or rebuilding its chart.

`AlertDrawingValue` carries price, optional upperPrice and paneIndex.
`AlertDrawingInfo` carries availability, reason, paneIndex and the possible
`AlertDrawingLevel` entries (id and title). `draw.alertInfo(id)` reports which
levels the tool supports. `draw.valueAt(id, time, level?)` uses its actual pane
projection and logical time axis. Lines respect finite spans and extensions,
logarithmic projections and collapsed session gaps. A drawing on a pane collapsed
to its header strip, where the chart maps no price, is read through that pane's
own scale, so its alert keeps firing. A missing/out-of-span value is unavailable,
never zero.

Channel bands support enteringRange/leavingRange. For a crossing or greater/less
condition, explicitly select base, boundary or middle. Fib tools require an
active rung such as ratio:0.5. Disabling that rung makes its alert unavailable;
it never silently retargets to another rung. Closed crossings compare both
bars against their respective drawing values. Moving a drawing changes its
level and silently reseeds the observation rather than delivering for the drag.
Deleting it through remove, undo or document replacement removes its alerts and
emits alert:removed with reason drawing-removed. Redo does not recreate alerts.

A drawing on a study pane requires `input: { instanceId, plotKey }` on its
DrawingAlertSource. The study must belong to that pane; evaluation uses plot
units and never substitutes the instrument price. A missing input is reported
as unavailable.

Chart hosts show price/drawing thresholds and indicator thresholds with the
existing PriceLine primitive. Bands have two lines. Armed lines show an Alert
badge; Triggered, Disabled, Expired and Paused name the other displayed states.
Lines carry distinct lifecycle colors and move in place,
disappear during an instrument mismatch and are removed with their alert or
controller. An unsupported or missing drawing does not produce a line at zero.
`AlertControllerOptions.visuals: false` disables rendering for a model-only
host; evaluation and event delivery are otherwise identical.

## Dragging thresholds

Armed price and indicator threshold lines accept a vertical drag on the line or badge.
Movement changes only the visual preview. `list()`, serialized state and alert
evaluation retain the committed source until release. A completed changed drag
updates that source once; use `alert:updated` to observe the committed record.
Do not persist values from the generic `drag` preview event.

Escape, pointer cancellation, a second pointer starting a pinch, context changes,
host pause and replay entry cancel the preview. Removed or replaced sources and
controller/chart teardown also invalidate the gesture. A paused controller does
not accept threshold drags. Triggered, disabled and expired records are read-only
until rearmed. Keep `setPaused(true)` in effect throughout any host
loading or replay-selection interval that must prohibit changes.

A range drag edits one bound and clamps it to the opposite bound; it never swaps
the bounds or moves both. Indicator thresholds are expressed in their selected
plot's units and use that plot's current axis, including independent and left
scales. Never convert them through the primary price scale. Drawing-owned levels
do not intercept dragging: change the underlying drawing instead. A threshold on
a foreign scale omits the primary right-axis price tag so it cannot label that
axis with the wrong units; the record and editor retain the source value.

## Persistence and restoration

`alerts.toJSON()` returns an `AlertsDocument`, `{ version: 1, alerts: Alert[] }`.
`alerts.fromJSON(document)` validates the complete replacement before changing
live records. It also accepts a JSON string or a legacy bare list; an omitted
policy migrates to onBarClose. `parseAlertsDocument(input)` provides the same
validation without attaching a controller. Duplicate IDs, invalid bounds,
unsupported versions and invalid lifecycle fields reject the whole document.

Runtime host payloads are opaque. Persistence requires finite JSON data and
refuses functions, accessors, symbols, cycles, sparse arrays and class instances
instead of silently losing information. Returned documents detach payloads.
Workspace storage additionally refuses private fields inside a routing payload
instead of silently removing them. Keep credentials and account state outside
portable chart workspaces.

ChartState includes optional alerts, and IndicatorState includes optional
instanceId. `chart.getState()` serializes current alert state. It can throw if
a runtime payload cannot be persisted. `chart.alertState()` reads the detached
document; `chart.setAlertState(document)` stores a runtime snapshot for the owner.
An application without a controller can round-trip the document without delivery.
The controller hydrates saved chart state when attached.

`chart.restoreState` validates alert data and duplicate study identities before
applying the layout. It restores drawings before alerts; DrawingController now
handles drawings:restore automatically. Do not call draw.fromJSON again after
chart restoration. Alerts with missing drawing, study or plot anchors are
dropped with alert:removed and a reason. Missing readings, temporarily unavailable
levels and an unloaded drawing provider are not deleted as missing anchors.

Triggered once records remain visible after reload. lastTriggeredAt preserves
cooldown; lastClosedTime and lastTouchedTime preserve consumed bars, including a
touch suppressed by cooldown. Restoring or attaching never evaluates historical
conditions. Complete workspace restoration preserves each study's instanceId;
parseIndicatorTemplate strips those identities so applying a reusable template
creates fresh instances rather than retargeting saved study alerts.

## Events

| Event | Payload |
| --- | --- |
| alert:created | `{ alert: Alert }` after creation |
| alert:updated | `{ alert: Alert }` after editing, enabling or disabling |
| alerts:changed | `{ id, reason: 'dragged' }` after a changed threshold drag commits |
| alert:removed | `{ alert: Alert, reason }`, including removed, drawing-removed, drawing-missing, indicator-missing and plot-missing |
| alert:expired | `{ alert: Alert }` when an armed record expires |
| alert:triggered | `AlertTriggeredPayload`: alertId, title, message, time, index, price, alert |
| alert:error | `{ alert: Alert, error: unknown }` when a custom predicate throws |
| alerts:restored | `{ alerts: Alert[] }` after a validated replacement |
| alerts:checkpoint | `{}` after history seeding or live evaluation advances consumed-bar guards; save chart state without delivering a notification |

The trigger time and index identify the source bar, not the delivery clock.
Closed triggers report its close. Intrabar crossing triggers report the crossed
threshold; greater/less report the observed extremum. State and duplicate guards
are committed before callbacks. Listeners may remove another alert, change
context or destroy the chart. The chart bus isolates throwing listeners; log
delivery failures in the host. Existing indicator:alert behavior is preserved.
`AlertEventPayload` defines the fields shared by IndicatorAlertPayload and
AlertTriggeredPayload: alertId, title, message, time and index. Indicator-source
trader triggers report the plot reading in price; predicate triggers report
the evaluated bar's close.

## Tick snapping and keyboard removal

From 2.5.0, preview and release both snap alert thresholds to their source
scale's tick: the primary series for price alerts, the chosen plot for study
alerts. Left and independent scales keep their own units. A range bound stops
at a valid tick inside the opposite bound. No declared tick means no rounding.
Manually entered thresholds are preserved until you move them.

`Chart.snapPrice(paneIndex, price)` uses that pane's right-axis tick, or on the
price pane of an instrument with a tick schedule (`chart.setTickSchedule`, or
`Instrument.applyTo` with `tickBands`), the tick of the band the price falls in; a
dragged price alert takes the same band, so an alert dropped in a coarse band
lands on a price it trades at. An `AlertChartHost` may expose `tickSchedule()` for
that. For another
series scale, use `series.priceScale().snapToTick(price)`. A custom
`AlertChartHost` may expose `primarySeries()` for the owning scale, or use the
optional `snapPrice` fallback when it has no series handle. Without scale tick
metadata, a callback that rounds the opposite bound outside the range cancels
the move and keeps the saved threshold. Expose the source scale for exact inner
tick snapping.

`alerts.hovered()` returns the alert id under the pointer, or `undefined`.
The widget and yfinance host bind Delete and Backspace to it only when a
selected or hovered drawing, an active drawing tool, or text editing does not
own the key. Custom hosts should keep the same priority and clear their saved
record on `alert:removed`. The controller itself never installs keyboard input.
