# openalgo-charts: open interest and alerts

Instructions for building two features in `openalgo-charts`. Part 1 is partly
done and needs finishing. Part 2 is not started.

Written 2026-09-20 against `openalgo-charts` at 2.4.0, commit `1933d65`.

---

# Part 1. Open interest

## Why

The platform's history API already returns open interest. `services/history_service.py`
guarantees an `oi` column on every response, defaulting it to 0 when the broker
sends none, and the REST schema notes it is always included for derivatives
exchanges.

The chart throws it away. `Bar` has no field for it and the feed adapter never
maps it, so a trader charting a futures or options contract has open interest in
the payload and no way to plot it.

The only route today is the Tier-2 external-data contract, and that is the wrong
tool. Tier-2 exists for data with its own timestamps that has to be aligned to
bars by last-known-value. Open interest arrives on the same row as the OHLCV,
already at the bar's own timestamp. Making somebody stand up a fetch and
subscribe lifecycle to plot a number that came in the same payload is backwards.

It matters more here than it would elsewhere: most of what this platform's users
trade is derivatives, and for a contract, open interest is as fundamental as
volume. The standard reading needs price change and open interest change together
per bar: price up with open interest up is a long buildup, price down with open
interest up is a short buildup, price up with open interest down is short
covering, price down with open interest down is long unwinding. None of that is
expressible without a per-bar column sitting next to volume.

## The one rule that matters

**Volume is a flow. Open interest is a level.** Everything else follows.

Volume is quantity traded *during* the bar, so folding five one-minute bars into
a five-minute bar adds five volumes together. Open interest is a position *as at*
the bar, so the same fold takes the **last** one.

Summing it would produce a number five times too large that still looks entirely
plausible on a chart, which is the worst kind of defect: no exception, no visible
break, just a wrong number a trader acts on.

So every aggregation path treats the two differently. Anywhere the code sums
volume, it carries the newest open interest instead.

**Absent is not zero.** A cash instrument has no open interest, and zero is a real
reading on a contract nobody is holding. Never default it to 0 to make a type
simpler.

## What is already done

These edits are in the **working tree of `openalgo-charts`, uncommitted**. They
typecheck clean (`npx tsc --noEmit`) and the full suite passes (215 files, 5251
tests). Keep them or discard them, but do not write them twice.

| File | Change |
|---|---|
| `src/model/bar.ts` | Added `oi?: number` with the level-versus-flow reasoning as its doc comment, since that is where somebody will look |
| `src/model/conflation.ts` | `mergeBars` carries the last defined `oi` in the group, never the sum |
| `src/indicators/security.ts` | `SecuritySeries.oi` and `Bucket.oi` added; the completed-bucket fold and the developing-bucket read-out both take the newest reading |
| `src/feed/openalgo-rest.ts` | `HistoryRow.oi` declared and mapped onto the bar |
| `src/feed/cache.ts` | `_validBar` rejects a non-finite `oi`, matching the volume check |
| `src/feed/candle-builder.ts` | `Tick.oi` added; replaces on both the new-bar and same-bar paths rather than accumulating |
| `src/feed/tick-aggregator.ts` | `AggTick.oi` added, same treatment |
| `src/transform/heikin-ashi.ts` | Carries `oi` through, since it maps one source bar to one output bar |

## What still needs building

### 1.1 Transforms that must NOT carry it

`src/transform/expression.ts` drops `volume` deliberately, with the note that the
volume of a ratio is not a volume. The same argument applies exactly: drop `oi`
too, and say why in the same place.

Renko, Range, Line Break, Point and Figure and Kagi invent bars from price alone.
A synthetic bar has no instant to be "the position as at", so they carry no open
interest. Confirm none of them accidentally does.

Kagi already repurposes `volume` as a thickness flag. Leave that alone and do not
repurpose `oi` for anything.

### 1.2 Built-in indicators

Three, in the indicators tier.

**Open Interest.** Placement `pane`. One plot, the raw series. `priceFormat`
should be the volume format, since the numbers are large. Absent where the bar
carries none, so the line breaks rather than dropping to zero.

**Open Interest Change.** Placement `pane`. A histogram of the bar-on-bar change,
coloured up and down. Absent on the first bar and wherever either side is absent.

**Open Interest Buildup.** Placement `onchart`. This is the one traders actually
want. Classify each bar from the sign of the price change and the sign of the
open interest change into the four states above, then publish the result through
`barColors` so the candles carry it, plus a `background` band if you want the
state legible when the candles are small. Give it four colour inputs, one per
state, and a select for whether an unchanged reading counts as up or is its own
neutral state.

Follow the existing descriptor conventions: warmup is honest, every plot gets its
generated style inputs, and the study draws nothing until it has the history it
needs.

### 1.3 Absent versus zero, visibly

The engine needs a way for a host to say "this instrument has no open interest"
as distinct from "no bar carried one yet", so a settings dialog can disable the
control rather than hide it, the way `PriceLevels.available(kind)` already does
for bid and ask. Follow that precedent rather than inventing a second pattern.

### 1.4 The status line

The status line is switchable field by field. Open interest belongs there beside
volume, off by default, and absent on an instrument that has none.

### 1.5 The live feed, honestly

The platform's websocket quote mode carries last price, the day's open, high, low
and previous close, and cumulative volume. **It does not carry open interest.**

So a bar built from live ticks has no open interest, and history bars in the same
series do. Do not paper over that. Options, in order of preference:

1. Leave it absent on the forming bar. The line stops at the last completed bar,
   which is the truth, and a trader can see it.
2. Carry the last known value forward and mark it stale. Only if you can make the
   staleness visible; a flat line that looks like data is worse than a gap.

Do not invent a value. `Tick.oi` is already declared, so if the feed ever starts
carrying it the plumbing is there.

### 1.6 Tests

Two of them matter more than the rest:

- **Folding does not sum.** Five bars with open interest 100, 110, 120, 130, 140
  fold to 140, not 600. Assert it in `mergeBars` and in `securitySeries` for both
  a completed and a developing bucket.
- **Absent survives.** A series where some bars carry open interest and some do
  not keeps the gaps, and no path substitutes 0.

### 1.7 Documentation

README, the indicator catalogue, `ARCHITECTURE.md` section 4 (the data model) and
the CHANGELOG. The CHANGELOG entry should carry the level-versus-flow rule,
because it is the thing a consumer needs to know and it is not guessable.

---

# Part 2. Alerts

## What exists today

Only one kind of alert exists, and it is declared by an indicator's author rather
than created by a trader.

- `IndicatorAlertSpec` in `src/model/indicator-registry.ts`: `id`, `title`, an
  optional `message` which may be a function of the bar's context, and a
  `when(ctx)` predicate.
- `src/model/indicator-instance.ts::_syncAlerts` evaluates them once per bar, only
  for bars newer than `_alertTime`, so adding a study to a loaded chart fires
  nothing for history.
- It emits `indicator:alert` on the chart's event bus with an
  `IndicatorAlertPayload`: indicator id, instance id, alert id, title, message,
  time and bar index.

That is a good foundation and should not be replaced. It answers "the indicator
is the only thing that knows what a crossover of its own columns means".

## What is missing

Everything a trader would call an alert:

1. **A trader cannot create one.** There is no alert object. You cannot right
   click a price and say "tell me when it gets here".
2. **No alerts on drawings.** The drawing tier contains no alert code at all, so
   there is no alerting on price crossing a trend line, a channel or a fib level,
   which is most of why people draw them.
3. **No lifecycle.** Nothing expresses fire once versus fire every time, an
   expiry, or enabled and disabled.
4. **No trigger policy.** Indicator alerts fire on bar close by construction.
   There is no intrabar touch option, and no way to choose.
5. **No persistence.** Alerts do not appear in `getState()`, so they do not
   survive a reload.
6. **Nothing is drawn.** An alert level has no visual.
7. **No UI.** The widget tier has no alert dialog, no alert list, no right-click
   entry.

## What to build

### 2.1 Keep it headless

The library owns the model, the evaluation and the events. It does **not** deliver
anything: no sound, no notification, no webhook. It fires an event and the host
decides what that means. Same rule the drawing controller and the replay
controller already follow.

### 2.2 The model

An alert is a plain object with a stable id, like a drawing:

- **What it watches.** One of: a fixed price; a drawing, by id, so the alert moves
  when the drawing is dragged; an indicator plot, by instance id and plot key; a
  named bar condition.
- **The condition.** Crossing in either direction, crossing up, crossing down,
  greater than, less than, entering a range, leaving a range. For a drawing, the
  same set against the drawing's value at the current bar.
- **Trigger policy.** `onBarClose` or `onTouch`. Make it explicit and make
  `onBarClose` the default, and say plainly in the docs what the difference costs:
  an intrabar touch can fire on a wick that the bar later erases, so the alert
  fired on something that is not in the history the trader will look at
  afterwards. This is the alerting version of the repainting question, and it
  should be as loudly documented.
- **Repetition.** `once` or `everyTime`, with an optional minimum interval between
  fires so a price oscillating across a level does not fire forty times.
- **Expiry.** Optional, as a UTC second.
- **State.** Armed, triggered, expired, disabled. A triggered `once` alert stays
  visible in its triggered state rather than vanishing, because a trader wants to
  see that it fired.
- **A message**, and an arbitrary host payload carried through untouched, so a
  host can attach whatever its delivery layer needs without the library knowing.

### 2.3 The controller

Follow `DrawingController`. A headless `AlertController` over the chart:
`add`, `update`, `remove`, `list`, `enable`, `disable`, `toJSON`, `fromJSON`.

Evaluation runs after each data update, on the same path the indicator alerts
already use, and reuses `_alertTime`'s rule: never fire for a bar that was already
judged, so loading history fires nothing.

For `onTouch`, evaluate against the forming bar's high and low rather than its
close, and state that in the doc comment.

### 2.4 Anchoring to a drawing

This is the part with a real design question in it, so decide it deliberately.

A drawing's value at the current bar is a function of its anchors, which are
`{ time, price }` and survive zoom. An alert on a trend line has to ask the
drawing for its price at the current bar time, which means the drawing tier needs
a small `valueAt(time)` for the tools where that is meaningful: lines, rays,
channels, horizontal levels, fib rungs. For a tool where it is not meaningful, the
alert kind is simply unavailable, and the UI should say so rather than offering a
control that cannot work.

A drawing that is deleted takes its alerts with it. Emit the removal so the host
can tell the user, rather than silently dropping it.

### 2.5 Rendering

An alert on a price or a drawing draws a line and a tag on the price axis. The
`PriceLine` primitive already exists and its own comment lists alerts as a use
case, so use it rather than adding a second way to draw a horizontal line.

State must be visible: armed and triggered should not look the same.

### 2.6 Events

On the chart's bus, alongside `indicator:alert`:

- `alert:triggered`, with the alert, the bar time, the bar index and the price
  that satisfied it.
- `alert:created`, `alert:updated`, `alert:removed`.
- `alert:expired`.

Give `indicator:alert` and `alert:triggered` the same payload shape where they
overlap, so a host writes one delivery path rather than two.

### 2.7 Persistence

Alerts go into `getState()` and come back through `setState()`, versioned the way
the drawing document is, with a migration path. An alert anchored to a drawing
must restore after the drawing does, and an alert whose drawing is gone is dropped
with an event rather than restored as a dangling reference.

### 2.8 The widget tier

The only tier that builds DOM, so all of this lives there and nowhere else:

- Right-click on a pane: "Add alert here", pre-filled with the price under the
  pointer.
- Right-click on a drawing: "Add alert on this drawing".
- An alert dialog generated from a schema, the way `chartSettingsSchema` and
  `drawingSettingsSchema` already work. No control without something behind it.
- An alert list: what is armed, what has fired, enable, disable, delete.
- A toast when one fires, since the widget already has toasts.

### 2.9 Tests

- An alert added to a chart with loaded history fires nothing.
- `once` fires once; `everyTime` respects its minimum interval.
- `onBarClose` does not fire on a wick that the bar later erases; `onTouch` does.
  This pair is the specification of the difference, so write it first.
- An alert on a drawing follows the drawing when it is dragged.
- A deleted drawing removes its alerts and emits.
- State round trips, including a drawing-anchored alert.

---

# House rules for both parts

These are the existing conventions in the repository, not new ones:

- **Zero runtime dependencies.** Nothing new gets added.
- **Tiers.** Alerts belong in the base engine; the UI belongs in `widget`. The
  ESLint tier ACL and `npm run shake` enforce it, so a stray import will fail the
  build rather than quietly bloat a bundle.
- **Size budget.** `.size-limit.json` is enforced. Check the delta before
  finishing and raise the budget deliberately if it is genuinely needed.
- **No DOM outside the widget tier.** Importing the base engine must touch no DOM,
  because it has to run on a server.
- **Absent is never zero.** For open interest, for an alert with no price, for
  everything.
- **Doc comments explain why.** The repository's existing comments explain
  reasoning rather than restating the code. Match that.
- **No emoji, and no em dashes or en dashes** anywhere: not in code, comments,
  documentation, commit messages or output. Use a comma, a colon, parentheses or
  a full stop.
