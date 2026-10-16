# Instrument metadata

Run the [instrument example](../examples/instruments.html) from the repository's
static server to exercise synthetic cash, futures and crypto profiles, session
exceptions, the OI pane and advisory quantity checks on a rendered chart.

`Instrument` is an optional, DOM-free base API. Its `InstrumentMetadata` connects
source identity, price display, quantity steps, interval support, trading sessions
and OI capability. Existing chart and feed options keep their defaults when this
API is not used. The host supplies current exchange rules; the library does not
download a calendar or infer trading rules from observed candles.

```ts
import { Instrument, CandleBuilder } from 'openalgo-charts';
import { orderConstraintsForInstrument, validateQuantity } from 'openalgo-charts/trade';

const instrument = new Instrument({
  symbol: 'CONTRACT', exchange: 'NFO', timezone: 'Asia/Kolkata',
  priceTick: 0.05, pricePrecision: 2, quantityStep: 75,
  intervals: ['1m', '5m', '1h', 'D'], hasOpenInterest: true,
  calendar: {
    sessions: ['0915-1530:23456'],
    exceptions: { '2026-01-26': [], '2026-01-27': ['1000-1300'] },
  },
});
instrument.applyTo(chart, '5m');
const allowed = instrument.supportsInterval('5m');
const advisory = validateQuantity(150, orderConstraintsForInstrument(instrument));
const session = instrument.sessionAt(tick.time);
if (session) {
  const builder = new CandleBuilder({ intervalSec: 300, sessionAnchorSec: session.open });
  builder.onTick(tick);
}
```

The builder above illustrates one session. A streaming adapter retains its
builder across ticks, rolls it at the next resolved session, seeds authoritative
history when available, and retains its volume/reconnect policy. Do not construct
a fresh builder per real tick. Calendar membership does not replace the provider's
historical timestamps, and this API does not discard historical bars for you.

`InstrumentCalendar` uses `HHMM-HHMM[:days]`, where Sunday is 1 and Saturday is 7.
An end at or before the start crosses midnight; `0000-0000` means a continuous
local day. Multiple windows represent breaks. `exceptions` replace windows for
the local **opening date**. An empty array closes that opening date. A Monday
overnight session can therefore continue into a Tuesday holiday, while a holiday
on Monday prevents that Monday session from opening.

`sessionAt(utcSeconds)` returns an `InstrumentSession` with a local opening
`date` and inclusive `open`/exclusive `close` in UTC seconds, or null outside the
windows. Each boundary resolves its actual timezone offset, so a continuous day
may last 23 or 25 hours across daylight-saving changes. Repeated boundary times
follow `zonedWallClockToUtcSeconds`; a nonexistent boundary throws instead of
inventing an opening time. Supply a date exception for such a schedule. Overlapping
active windows throw because there is no unambiguous session anchor.

`sessionFrom(utcSeconds)` returns the window active at the instant, or else the
next one to open, scanning about a year of opening dates and returning null when
none opens. Yesterday's overnight window still running is returned on its opening
date. Boundaries resolve and throw exactly as for `sessionAt`.

`SessionCalendar` carries the same hours without price, quantity or interval rules:
`new SessionCalendar({ timezone, sessions, exceptions })` validates, detaches and
freezes them by the rules above, throws `Invalid session calendar: ...`, and reads
with `sessionAt` and `sessionFrom`. `applyTo(chart)` sets it as the chart's
calendar for times past the last bar and repaints, through
`chart.setSessionCalendar(calendar)`, which a host setting hours it built itself
(any object with `sessionFrom`) calls directly; `null` clears them.
`chart.dataLayer.setSessionCalendar` sets the same without asking for a frame, for
a host about to load bars or move the view, either of which repaints.

Construction validates and detaches metadata, freezes its nested arrays/objects
and omits unrelated source fields. Empty identities, unknown timezones, invalid
dates/windows, nonpositive ticks/quantity steps and unsupported intervals reject.
Register custom interval codes before construction. Supported tokens match
exactly: allowing `D` does not automatically permit a provider request for `1d`.
Registration supplies bucketing semantics; the metadata list supplies venue support.

`pricePrecision` accepts 0 through 12 and must be able to represent `priceTick`.
`formatPrice` affects display only, preserving unrounded source values. `applyTo`
sets chart timezone, the price tick, primary price-scale formatting and data
context, including the independent `hasOpenInterest` capability. It also sets the
instrument through `chart.setSessionCalendar`, so times past the last bar
follow its sessions: the bar after Friday's last one is Monday's first, closed
dates are skipped and daily bars step through trading dates. A later instrument
replaces it, a data context moved to another symbol or exchange drops it,
`setSessionCalendar(null)` clears it, and a calendar the recent bars do not sit in
is ignored for the median recent bar interval. Oscillators and
volume retain their own formatting. The chart must have a primary series. Clear
old source bars before changing symbol, exchange or interval; an incompatible
application rejects before mutating the chart. Reapply metadata after replacing
the primary series or restoring user layout formatting. The host owns cancellation
of obsolete metadata/history requests and applies only its current source.

`quantityStep` is expressed in the order adapter's quantity units. The trade
helper returns existing `OrderConstraints` with that grid and the price tick.
It does not multiply units by a lot size. Hosts can add current price-band/freeze
constraints. Client checks remain advisory; the broker retains execution authority.
`hasOpenInterest` stays true, false or unknown independently of zero/missing bars.

## Price-dependent ticks

`tickBands` declares a tick that changes with price, supplied by the host from its
venue's rules; the library ships none. The first band has no `from` and covers every
lower price, zero and negative prices included. Each later band starts at its `from`
(inclusive, strictly ascending), and every `from` must be a multiple of the ticks on
both sides of it, so a boundary is itself a valid price. Ticks are positive with at
most 12 decimals, and a schedule has 1 to 64 bands. Invalid bands throw
`Invalid tick schedule: ...` naming the band.

```ts
const banded = new Instrument({ ...metadata, priceTick: 0.01,
  tickBands: [{ tick: 0.02 }, { from: 20, tick: 0.05 }] }); // synthetic rules
const ticks = banded.tickSchedule; // TickSchedule | null, null for a constant tick
if (ticks !== null) ticks.round(20.03); // 20.05, an exact decimal
```

`instrument.tickSchedule` is the validated `TickSchedule`: `round` gives the nearest
valid price, a written halfway price rounding up; `tickAt` gives the tick in force,
the upper band's at an exact boundary; `step` moves whole ticks across boundaries.
It is null for a constant tick, which keeps one snapping rule, `priceTick`, on every
path. With bands, `priceTick` must equal the schedule's `minMove`, the common grid of
every band, and `applyTo` sets that as the price scale's `minMove`.
`orderConstraintsForInstrument` adds `tickSchedule` to the constraints, so
`validatePrice`, `OrderEngine.placeOrder` and `OrderEngine.requestModify` snap on the
band each price lands in and check price limits after snapping.

`applyTo` also hands the same schedule to the chart (`chart.setTickSchedule`, read
back with `chart.tickSchedule()`), so a dragged price alert and `chart.snapPrice` on
the price pane round in the band a price falls in; a host with its own metadata calls
`chart.setTickSchedule` itself. The chart passes it to `chart.trading`, so dragged
order and bracket lines snap to it. It does not build the trading layer (that would take the
host's drag subscription); a layer built later starts from it. Applying a
constant-tick instrument clears it, so after a symbol switch no drag snaps to the
previous instrument's bands. Call `chart.setTickSchedule` after `applyTo` to
override it. For a depth ladder, pass the schedule as `DomLadder`'s `tickSchedule`.
