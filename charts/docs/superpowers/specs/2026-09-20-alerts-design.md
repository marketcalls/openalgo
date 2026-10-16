# Trader-created alerts

Implements Part 2 of `2026-09-20-open-interest-and-alerts-requirements.md`.
The user authorized continuous implementation of that specification and the
complete production plan before publishing 2.4.5. This document settles the
integration decisions within that scope. It does not replace any requirement.

## Ownership and data updates

Use an exported headless `AlertController(chart, options)` in the base entry.
It owns records, evaluation watermarks, one expiry timer and PriceLine handles.
The chart exposes readonly `primaryBars()` and emits `data:update` only after
its primary source has changed and indicators have been marked dirty. The
payload distinguishes live `update`, history `reset`, and `prepend`, and names
the updated time. A controller reads the existing source array without copying
the entire history on every tick. Fixed-price alerts do not flush indicators.

The chart stores a typed alert document beside its drawing document, without a
runtime import of the controller. This preserves the chart-only import boundary.
The widget and reference/consumer hosts explicitly construct one controller per
chart and destroy it with that owner. Multiple controllers on one chart are
refused to prevent duplicate delivery.

`setData` and `prependData` establish history silently. Adding, enabling,
restoring, changing context or leaving replay reseeds the current observations.
A live append confirms the previous tail bar; only that confirmed bar is judged
by `onBarClose`. The forming tail is eligible for `onTouch` on every meaningful
live update until a match is consumed. Existing indicator-authored alerts keep
their current behavior and event contract.

## Model and trigger meaning

`AlertSource` is one of:

- `{ kind: 'price', price, upperPrice? }`: primary price versus a level or band.
- `{ kind: 'drawing', drawingId, level?, input? }`: current drawing level, or a
  channel band. Optional `input` identifies an indicator instance and plot when
  the drawing lives on an indicator pane.
- `{ kind: 'indicator', instanceId, plotKey, value, upperValue? }`: plot reading
  versus a threshold or band. Missing plot values remain unavailable.
- `{ kind: 'barCondition', id }`: a registered named predicate, using `matches`.

Numeric conditions are `crossing`, `crossingUp`, `crossingDown`, `greaterThan`,
`lessThan`, `enteringRange`, `leavingRange`. A band requires two finite ordered
bounds. Closed crossing-up requires previous <= level and current > level;
crossing-down is the inverse. Range boundaries are inclusive. A named predicate
uses `matches`, not numeric controls that cannot affect its behavior.

`onBarClose` is the default. `onTouch` uses observed forming high/low for price
and price-drawing sources. A pre-existing wick at creation is not a new touch:
compare with the arm-time snapshot and use only new extrema and the path between
observed closes. Indicator plots use their own observed values, never the price
bar's high/low as if both had the same units. One touch match per alert/bar is
consumed even when cooldown suppresses delivery; an old wick must not fire when
the cooldown later elapses. Repetition `everyTime` permits subsequent bars to
fire; `once` stays visible as `triggered` after its first event.

Cooldown and expiry use UTC seconds from an injectable clock. Expiry is exclusive
of triggering: `now >= expiresAt` expires first. A single timer tracks the next
armed expiry, including while the feed is idle, and is cleared at destruction.
Alerts remain paused during replay and are scoped to the instrument/timeframe
where they were armed. A context mismatch is visibly unavailable, not a signal
to evaluate the saved level against a different market.

The runtime carries the host payload untouched. Persistence requires JSON-safe
payloads and refuses unsupported values instead of silently deleting them.
Lifecycle changes and duplicate guards are committed before events are emitted.
Delivery belongs to the host; no notification, webhook, sound or order is sent.

## Drawings, values and persistence

Expose `DrawingController.valueAt(id, time, level?)` and availability/level
choices through structural types. Drawing tools opt in with value hooks; tools
with no unique numeric value return a reason. Line/ray extent, log projection,
collapsed session gaps, channels and fib-rung choices must match drawn geometry.
Dragging changes the next evaluation and visual. Removal, undo removal and
document replacement all reconcile anchored alerts and emit removals.

Price/drawing alerts use the existing PriceLine primitive and axis tag. Armed,
triggered, disabled and expired states carry distinct text and styles. Missing
values do not create a line at zero. Indicator threshold lines use their pane.

Alerts use a versioned document inside ChartState, leaving version-1 chart
documents readable. Chart restoration emits a drawings phase before an alerts
phase; an attached drawing controller restores before alerts validate anchors.
No controller means documents still round-trip without evaluating. Preserve
indicator instance identity in chart state so repeated identical studies retain
the correct alert anchors. Templates create fresh instances and do not duplicate
alerts accidentally. Dangling drawing/plot anchors are dropped with an event.

## UI and delivery

The widget adds pane/drawing context actions, a schema-generated editor, an alert
list and trigger toasts. Condition-specific fields are enabled only when backed
by real evaluation. Drawing levels and indicator plots are explicit choices.
The dialog states the intrabar repainting tradeoff next to its policy choice.
The reference host and OpenAlgo `/trading` use the same controller and model,
preserve alerts in workspaces and present lifecycle state without creating orders.

## Verification

Start with the erased-wick pair on a real Chart: touch fires at the observed
wick, bar-close remains silent when the confirmed close does not cross. Then
cover silent history, deduplication, repeat/cooldown, idle expiry, context and
replay suppression, drawing changes/deletion, plot gaps/identity, state migration,
and reentrant lifecycle listeners. Render and inspect all three browser engines.
Run library, example and packed-consumer checks, size/shake/API/reference gates,
and retain the remaining production plan and final release checks.
