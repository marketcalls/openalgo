#!/usr/bin/env python
"""Run one compiled OpenScript program in a process of its own.

This is the program that runs INSIDE the child process. The web worker never
imports it: ``services/openscript_runner_service.py`` spawns it and returns.
Everything here is an ordinary blocking process. Nothing has monkey-patched the
standard library, so a plain sleep, a plain socket and a plain loop are all
correct, and none of the rules that govern the worker apply.

WHERE THIS FILE LIVES, AND WHY IT IS NOT UNDER ``strategies``
--------------------------------------------------------------

This is the platform's own program and not a trader's script, so it belongs where
the platform's own files are: in the image, outside every mounted folder, and
tracked in the repository.

``strategies`` is none of the three. A container install keeps that folder on a
named volume, and a named volume is seeded from the image only while it is empty,
so a file the platform put there is delivered to a brand new install and to no
existing one: every install that had already started once would upgrade and find
this program gone. The folder also ignores every ``.py`` inside it, in two
separate rules, which is right for a trader's uploaded scripts and kept this file
out of the repository entirely.

So it lives here, and ``services/openscript_runner_service.py`` names this path
first. That service still looks in the old place afterwards, as a migration shim
for an install that has not taken the move yet, and says so in the log every time
it has to.

**It is handed a compiled program and never source.** There is no compiler on
this server and none is planned. The browser compiled the script when the trader
saved it and the program was stored beside the source. If no program is stored,
this refuses to start and says which script it was, because the only two things
it could otherwise do are guess or compile, and it can do neither.

**The program bytes go to the engine unchanged.** The canonical encoding is what
a program's hash is taken over, and an engine that loads a program from text
refuses text spelled any other way. So the file is read and handed over as it
was written: it is never parsed here and rebuilt into an object.

**Orders go out through the platform SDK, exactly the way any other strategy on
this host places them.** The SDK reaches the local order path, which reads the
platform-wide analyzer toggle before anything else, so sandbox mode and analyzer
mode are honoured by the same code that honours them for every other surface.
Nothing here reaches a broker, and nothing here opts out of that toggle. There
is deliberately no flag, no environment variable and no argument that could.

What this file will not do, said plainly because a runner is not worth much if a
reader assumes more of it than it promises:

- it compiles nothing;
- it places no order the engine did not ask for;
- it sends nothing while it is replaying history (see ``THE HISTORY PASS``);
- it invents no fill: a position moves only when a frame from the order path
  says it moved.

THE MOVING BAR, AND WHY THE STATE GOES BACK BETWEEN EXECUTIONS
--------------------------------------------------------------

The newest bar is still moving. Its high, its low and its close change while it
is open, so it is executed again on every poll, and a script computing from it
must see each execution as the first one: the same bar executed twice without
the state going back would accumulate its own effects, and a run would then
disagree with its own backtest for no reason a trader could see.

Two things make that go back, and they are different things.

1. **The engine's state.** ``Run.execute_bar`` takes a checkpoint at the start of
   the first execution of an index and restores it at the start of every later
   execution of that same index. That is its step 1, and it is keyed on the bar
   index. So the whole of the driver's duty is to execute a moving bar at the
   SAME index every time and never to let the index drift, which is why bar
   indices here are anchored to bar open times and grow by one per confirmed bar
   rather than being derived from the length of whatever the last history fetch
   returned. A rolling window that shifted the index by one would hand the engine
   a new bar every poll and it would never restore anything.

   This driver also takes its own ``Run.checkpoint`` for the moving bar and
   restores from it before each re-execution. **That is deliberately redundant
   with the engine's own step 1 and is not what makes the property hold today.**
   It is the same state, recorded at the same instant, and restoring twice from
   one state is that state, so removing these lines changes nothing that any test
   can see. They are here because this driver depends on the property and states
   what it depends on, and because the day an engine keeps its checkpoint for a
   different span than one index, this file says which state it wanted. The part
   that actually carries the property is the index, which is the paragraph above.

2. **The ledger, which the engine's checkpoint does not cover.** An order that
   has been sent cannot be rolled back, so a ledger that was rolled back would
   stop describing the orders that exist in the world. This driver therefore
   sends orders from a CONFIRMED execution only. It discards the effects of every
   unconfirmed execution of a moving bar, and it says so in the log once per run
   for a program that declared ``onUnconfirmed``.

   That is also the choice that makes a live run agree with its backtest rather
   than disagree with it. Every bar of a backtest is confirmed and executed once,
   so a strategy's effects there are the effects of closed bars. A runner sending
   intrabar would be sending orders the backtest never sent.

THE HISTORY PASS
----------------

A strategy needs history before it can say anything: an average over sixty bars
is absent until sixty bars have gone through it. So the first poll replays every
bar already on the chart, in order, to bring the engine's state up to the
present.

**Nothing is sent during that replay, and the run begins flat.** Replaying old
signals into real orders would trade yesterday on today's money. The alternative,
folding the replay's orders into the ledger as though they had filled, is worse:
the ledger would then hold a position the broker does not hold, and the first
exit the script wrote would open a real position on the other side.

The cost is stated rather than hidden, in this file and in the log at the moment
of the handoff. A strategy whose history would have left it holding something is
picked up flat, so its next exit has nothing to exit and its next entry is its
first. This runner does not work out what that position would have been, because
working it out would mean inventing a fill for every order in the replay, and an
invented fill is the one thing a ledger must never hold.

USAGE

    python -u openscript_host/openscript_runner.py \\
        --script <name>.oscript --symbol <SYMBOL> --exchange <EXCHANGE> \\
        --interval <INTERVAL>

Environment, as the platform's strategy host already injects it:
``OPENALGO_API_KEY``, ``OPENALGO_HOST``, ``STRATEGY_ID``, ``STRATEGY_NAME``.
``OPENSCRIPT_ENGINE_PATH`` names the directory holding the engine package where
it is not already importable.

Output goes to stdout, which the parent redirects into the per-strategy log the
platform already keeps. Stopping is a signal: the loop leaves at the next check.
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

# This file is read two ways: the service starts it as a script, where its own
# directory is what imports resolve against, and the tests import it as a module
# of the package, where the repository root is. Putting the root on the path
# makes the one import below work either way, rather than a fallback branch
# whose production half no test ever takes.
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openscript_host.live_bars import SETTLE_SECONDS as LIVE_BAR_SETTLE  # noqa: E402
from openscript_host.live_bars import LiveBars  # noqa: E402 - after the path above
from services.openscript_commands import CLOSE  # noqa: E402 - after the path above

# Where the platform stores a trader's scripts, and what it calls the compiled
# program it keeps beside one. Both mirror ``blueprints/openscript.py``, which
# owns the names. They are repeated rather than imported because importing a
# blueprint would pull the whole web layer into a strategy process for the sake
# of two strings; if the route ever renames either, this line is the other half.
SCRIPTS_DIR = Path("strategies") / "openscript"
PROGRAM_SUFFIX = ".program.json"

# The three products this platform sends.
PRODUCTS = ("CNC", "NRML", "MIS")

# The language states a product as one of two words, and this platform sends one
# of three. Only one of the two maps without a choice being made.
#
# A script that says it trades within the day names the platform's intraday
# product and there is nothing to decide. A script that says it carries a
# position overnight does not say how: on this platform that is one product for a
# holding and another for a carried derivative position, and the two are charged,
# margined and squared off differently. The script cannot know which, because a
# strategy is written against a chart and not against a segment.
#
# So the one that maps is mapped, and the one that does not is asked for. A
# runner that picked a default here would be choosing how a trader's position is
# carried, and it would be right about half the time.
INTRADAY = "intraday"
OVERNIGHT = "overnight"
PRODUCT_FOR = {INTRADAY: "MIS"}

# The order calls this runner cannot hand to the platform as one order, and the
# reason, which is worth being exact about.
#
# ``exit`` and ``order.bracket`` attach a stop and a target to a position that has
# already been entered. Sent here they would have to become two orders, one on
# each side, with the second cancelled the moment the first fills. This platform
# has no single call that does that, and a pair sent without it is a position that
# can be closed twice: if both fill, the trader is left holding the opposite side
# of what they wrote.
#
# Building that pairing is not a line of code, it is a decision about somebody's
# money, so this runner refuses a program that calls either, BEFORE the program
# has started rather than at the bar that calls it. A refusal at the bar would
# arrive after the entry beside it had already gone out, which is the one outcome
# worse than not running at all: a position with nothing protecting it.
UNROUTABLE_CALLS = ("exit", "order.bracket")

# The compiled program tag a program that places orders carries, and the word its
# meta uses for a program that is one. Both are the compiled program format's own
# vocabulary rather than this file's.
ORDERS_TAG = "orders"
STRATEGY_KIND = "strategy"

# Exit codes. The parent reads them, and a trader reads the log.
EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_DIAGNOSTIC = 3

# How the engine's four order types are spelled by the platform's order path.
PRICE_TYPES = {
    "market": "MARKET",
    "limit": "LIMIT",
    "stop": "SL-M",
    "stopLimit": "SL",
}

# What the platform says about an order, against the seven words the engine's
# status vocabulary holds. Anything else is left out deliberately: a word this
# map does not carry leaves the row's status alone rather than moving it
# somewhere invented.
STATUS_WORDS = {
    "complete": "filled",
    "open": "working",
    "trigger pending": "triggerPending",
    "rejected": "rejected",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}

# The statuses that end an order, in the platform's own words, so the poll can
# stop asking about one.
FINISHED = ("complete", "rejected", "cancelled", "canceled")


class Refusal(Exception):
    """A reason this run will not start, written for the trader who reads the log."""


def _now_text() -> str:
    """The wall clock, for a log line."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def say(message: str) -> None:
    """One line into this run's log.

    ``sys.stdout`` and not ``print``, and not the platform's logger either. This
    is a separate process: attaching it to the platform's own JSON error log
    would put a script's arithmetic into the file an operator reads to find a
    fault in the platform. The parent redirects this stream into the per-strategy
    log file, which is where a trader looks.
    """
    sys.stdout.write(f"{_now_text()}  {message}\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class Engine:
    """The pieces of the engine host surface this runner uses, resolved once.

    Held as an object rather than imported at module top so that the refusal for
    an engine that is not installed is a sentence in this run's log rather than a
    traceback the parent has to interpret, and so that the rest of this file can
    be read without an engine present.
    """

    def __init__(self) -> None:
        extra = os.getenv("OPENSCRIPT_ENGINE_PATH")
        if extra and extra not in sys.path:
            sys.path.insert(0, extra)
        try:
            from openscript.adapter.serving import Serving
            from openscript.adapter.sessions import SESSION_FACTS
            from openscript.contracts import Bar, BarState
            from openscript.dates import NAMES as CALENDAR_READS
            from openscript.inputs import utc_time
            from openscript.run import load_text
            from openscript.strategy import (
                Identity,
                IntentBar,
                Ledger,
                LedgerOptions,
                OrderFrame,
            )
            from openscript.verify import capabilities
            from openscript.zones import READABLE
        except ImportError as missing:
            raise Refusal(
                "The OpenScript engine is not installed on this server, so nothing can run a "
                "compiled script yet. Install it, or set OPENSCRIPT_ENGINE_PATH to the folder "
                f"that holds it. ({missing})"
            ) from missing

        self.load_text = load_text
        self.Serving = Serving
        self.Bar = Bar
        self.BarState = BarState
        self.Ledger = Ledger
        self.LedgerOptions = LedgerOptions
        self.Identity = Identity
        self.IntentBar = IntentBar
        self.OrderFrame = OrderFrame
        self.capabilities = capabilities
        self.utc_time = utc_time
        self.session_facts = tuple(SESSION_FACTS)
        self.readable_zone = READABLE
        #: Every library call that reads a calendar, asked of the engine rather
        #: than listed here. The engine keeps this set precisely so that a caller
        #: whose instrument is in another zone can ask "does this program read a
        #: calendar at all" instead of keeping its own copy of the list, which
        #: would go stale the first time the language gained a call.
        self.calendar_reads = frozenset(CALENDAR_READS)


def program_text(script: str, directory: Path | None = None) -> str:
    """The compiled program stored beside one source, as the bytes it was stored as.

    Read from the file rather than fetched over the route beside it, because the
    route that serves a program requires a logged-in browser session and a
    strategy process has an API key instead. The bytes are the same either way.

    Refusing names the script, because a trader running six of them needs to know
    which one to open and save again.
    """
    folder = SCRIPTS_DIR if directory is None else directory
    source = folder / script
    program = folder / (script + PROGRAM_SUFFIX)

    if not program.is_file():
        if source.is_file():
            raise Refusal(
                f"{script} has no compiled program stored, so there is nothing to run. Open it in "
                "the chart and save it once the console shows no errors."
            )
        raise Refusal(
            f"There is no script called {script} on this server. Check the name, or save it from "
            "the chart first."
        )

    try:
        return program.read_text(encoding="utf-8")
    except OSError as unreadable:
        raise Refusal(
            f"The compiled program for {script} could not be read from disk. ({unreadable})"
        ) from unreadable


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------


def _declared_kind(text: str, script: str) -> str:
    """What ``meta.kind`` says this program is, read from a copy of the text.

    A program that will not parse is refused here rather than further in, because
    the sentence a trader can act on is the same one either way and this is the
    first place that can say it.
    """
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError) as unreadable:
        raise Refusal(
            f"The compiled program stored for {script} could not be read. Open it in the chart "
            "and save it again."
        ) from unreadable
    meta = parsed.get("meta") if isinstance(parsed, dict) else None
    if not isinstance(meta, dict) or not isinstance(meta.get("kind"), str):
        raise Refusal(
            f"What is stored beside {script} is not a compiled program. Open it in the chart and "
            "save it again."
        )
    return meta["kind"]


class Candle:
    """One bar as this runner carries it, before the engine's own shape.

    ``time`` is the bar's open instant in whole milliseconds since the epoch, UTC,
    which is what the engine reads. Every conversion from whatever the platform
    returned happens once, in ``candles_from``, so there is one place where a
    timestamp can be got wrong.
    """

    __slots__ = ("time", "open", "high", "low", "close", "volume")

    def __init__(self, time_ms, open_, high, low, close, volume) -> None:
        self.time = time_ms
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


#: How long after a bar closes to look for it, and how often to look again.
#:
#: **Every tenth of a second here is slippage**, because the order this run is
#: about to send was decided at a price that has already moved on. So the first
#: look is as soon after the close as is worth trying, and a miss is retried
#: quickly rather than waited out.
#:
#: **What it cannot be is zero, and the reason is not the clock.** A poll reads
#: the whole history window, which is days of bars, and the feed does not
#: publish a closed bar the instant it closes. Looking at the exact boundary
#: usually finds the bar still missing and costs a full fetch to learn it. A
#: quarter of a second is the first look; a miss is retried four times a second
#: while it is plausibly about to arrive, then more slowly, because a fetch that
#: is answering with nothing is one this run is paying for and learning nothing
#: from.
#:
#: **The floor under all of this is the fetch itself**, and it is not removed by
#: looking sooner. A run that needs to act inside that floor wants the tick
#: stream this platform already carries rather than a history poll, which is a
#: change to how a run learns a bar has closed and not to when it looks.
SETTLE_SECONDS = 0.25
#: How often to look again while a bar that should be there is not, by how long
#: this run has been waiting for it.
RETRY_SOON = 0.25
RETRY_SOON_WINDOW = 3.0
RETRY_LATER = 1.0
#: The most this will keep asking for a bar, as a share of the bar itself.
#:
#: **A share rather than a count of seconds, because how late a feed is has
#: nothing to do with the clock and everything to do with the feed.** This was a
#: flat twenty seconds, and it was measured against a platform whose history
#: carries a closed one minute bar about thirty five seconds after it closes:
#: the run gave up at twenty, fell back to its ordinary cadence, and sent the
#: order half a minute later than the bar was actually available. Giving up
#: before the bar can arrive is the one way this loop can be slower than not
#: having been written.
CATCHUP_SHARE = 0.9

#: How many bars closed on the feed to hold for comparison with history, and
#: how far the two may differ before a run says so.
#:
#: A feed and a history endpoint rarely agree to the last tick, because one is
#: every trade a process saw while subscribed and the other is the exchange's
#: own bar. A tenth of a percent is wider than that disagreement and far
#: narrower than one that would change a signal.
FEED_BARS_COMPARED = 10
FEED_DISAGREEMENT = 0.001

#: How often to look for an instruction while asleep between bars.
#:
#: A trader who has pressed Stop is waiting on this, so it is seconds rather
#: than the ordinary cadence. It is not smaller because this is a file read and
#: the ordinary answer is that there is nothing in it.
ASK_EVERY = 2.0

#: When to wake after a boundary while the tick stream is closing the bars.
#:
#: A shade past the builder's own settle offset, so that a run waking at the
#: boundary finds the bar already closed rather than a tenth of a second short
#: of it and has to come back. It is not history's lateness and is not learned
#: from it: the bar was complete in this process as it closed.
FEED_SETTLE = LIVE_BAR_SETTLE + 0.05

#: How many recent bars' lateness to remember, and the smallest sample worth
#: acting on. Short, because a feed that changes its behaviour should be
#: followed within a bar or two rather than averaged with an hour of history.
LATENESS_REMEMBERED = 5
LATENESS_ENOUGH = 2


def interval_seconds(interval: str) -> int:
    """How long one bar of this interval lasts, or zero where that is not known.

    Zero is the honest answer for a daily bar and for anything this does not
    recognise, and it means the caller keeps its ordinary cadence: a run must
    never sleep towards a boundary it has guessed.
    """
    text = (interval or "").strip().lower()
    if not text:
        return 0
    units = {"s": 1, "m": 60, "h": 3600}
    unit = text[-1]
    if unit not in units:
        return 0
    try:
        count = int(text[:-1])
    except ValueError:
        return 0
    return count * units[unit] if count > 0 else 0


def expected_settle(lateness: list[float]) -> float:
    """How long after a close to look first, learned from how late bars have been.

    **A feed's lateness is a fact about the feed, so it is measured rather than
    assumed.** One platform's history carries a closed one minute bar about
    thirty five seconds after it closes; another may carry it at once. A fixed
    first look is either far too early, which spends a fetch on a bar that
    cannot be there, or far too late, which is slippage on every order.

    So this aims a second before the shortest lateness recently seen, and the
    quick retry covers the rest. A second early rather than at the median,
    because being early costs one fetch and being late costs a fill.

    Until there are enough readings it answers the small fixed offset, which is
    the right guess for a feed that is prompt and costs one wasted fetch a bar
    for one that is not.
    """
    if len(lateness) < LATENESS_ENOUGH:
        return SETTLE_SECONDS
    return max(SETTLE_SECONDS, min(lateness) - 1.0)


def next_wake(
    now: float,
    bar_seconds: int,
    poll_seconds: float,
    waiting_since: float | None,
    settle: float = SETTLE_SECONDS,
) -> float:
    """How long to sleep before looking again.

    **The point of this is that an order goes out on the bar it was decided
    on.** A run polling on a free running timer finds a closed bar somewhere in
    the next poll interval, so an order decided at the close of one bar reaches
    the platform up to a whole interval later, part way through the bar after
    it. The strategy's own backtest prices that fill at the next bar's open, so
    every live fill is worse than the report by however far the price moved
    while the run was asleep. It is not noise: it is the same lateness every
    time, in the same direction.

    So the next wake is shortly after the next bar closes, or the ordinary
    cadence, whichever comes first. The cadence is kept as the ceiling because
    the bar that is still forming has to stay fresh, and because a daily bar's
    boundary is hours away and a run must not sleep through the afternoon.

    ``waiting_since`` is when this run last crossed a boundary without finding
    the bar behind it. While that is recent the sleep is short, so a feed that
    publishes a second or two late costs a second or two rather than a whole
    interval.
    """
    ordinary = now + poll_seconds

    if bar_seconds > 0 and waiting_since is not None:
        waited = now - waiting_since
        # Kept looking for most of a bar rather than for a fixed count of
        # seconds. Giving up before the bar can arrive is the one way this loop
        # is slower than not having been written: the run falls back to its
        # ordinary cadence and sends the order whenever that next lands.
        if waited < bar_seconds * CATCHUP_SHARE:
            # Quickly while the bar is plausibly about to arrive, then slowly.
            # A fetch answering with nothing is one this run pays for and learns
            # nothing from, so the rate falls away as the wait stops being about
            # a feed that is a moment behind.
            soon = RETRY_SOON if waited < RETRY_SOON_WINDOW else RETRY_LATER
            return min(ordinary, now + soon) - now

    if bar_seconds <= 0:
        return poll_seconds

    # The settle point of the bar that has most recently closed, or of the next
    # one where that moment has already gone by.
    #
    # Taking the NEXT boundary unconditionally is the mistake worth naming: a
    # wake landing one second after a close, before the settle offset, would
    # then aim a whole interval ahead and jump straight over the bar it was
    # waiting for. With the cadence as a ceiling it never lands on a settle
    # point at all, and the alignment this function exists for silently never
    # happens.
    closed = (now // bar_seconds) * bar_seconds
    target = closed + settle
    if target <= now:
        target = closed + bar_seconds + settle

    return max(0.0, min(target, ordinary) - now)


def _asked_of(run_id: str) -> str:
    """What the parent has asked of this run, or an empty string.

    Nothing raises and an unreadable file is no instruction. A run that stopped
    trading because it could not read this would be worse than one that misses
    an instruction and is asked again a moment later.
    """
    try:
        from services.openscript_commands import command_for

        return command_for(run_id)
    except Exception:  # noqa: BLE001 - see the note above
        return ""


def _forget_instruction(run_id: str) -> None:
    """Drop an instruction this run could not carry out, so it is not retried.

    The one case the parent does not clean up: it asked, this run tried, and the
    position is still open. Left in place it would be attempted on every wake,
    sending a closing order a minute for a position that is not closing, and the
    log would say the same thing for the rest of the session.
    """
    try:
        from services.openscript_commands import clear

        clear(run_id)
    except Exception:  # noqa: BLE001 - the run goes on either way
        return


def _bar_time_text(time_ms: int) -> str:
    """A bar's open instant as a clock time, in this server's own zone.

    The same zone `_now_text` writes every other line of this log in, so two
    lines about the same moment read as the same moment.
    """
    try:
        return datetime.fromtimestamp(time_ms / 1000.0, tz=UTC).astimezone().strftime("%H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return str(time_ms)


def _instant_ms(stamp) -> int:
    """A history timestamp as whole milliseconds since the epoch, UTC.

    The platform returns an index that carries its own zone for an intraday
    interval and a naive UTC reading for a daily one. Both are handled here and
    nowhere else: a naive reading is taken as UTC, which is what it is, and an
    aware one converts itself.
    """
    moment = stamp.to_pydatetime() if hasattr(stamp, "to_pydatetime") else stamp
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp() * 1000)


def candles_from(frame) -> list[Candle]:
    """Every row of a history result, oldest first.

    The result is whatever the platform SDK returned. A failure comes back as a
    mapping carrying a message rather than as an exception, so that shape is
    checked before anything is read out of it.
    """
    if isinstance(frame, dict):
        raise Refusal(
            "History could not be read for this instrument: "
            f"{frame.get('message', 'no reason was given')}"
        )
    if frame is None or len(frame) == 0:
        return []

    columns = {name: list(frame[name]) for name in ("open", "high", "low", "close")}
    volumes = list(frame["volume"]) if "volume" in frame else [None] * len(frame)
    stamps = list(frame.index)

    candles = []
    for at, stamp in enumerate(stamps):
        candles.append(
            Candle(
                _instant_ms(stamp),
                float(columns["open"][at]),
                float(columns["high"][at]),
                float(columns["low"][at]),
                float(columns["close"][at]),
                float(volumes[at]) if volumes[at] is not None else None,
            )
        )
    return candles


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


class Session:
    """One loaded program, the instrument it runs on, and the bars it has seen."""

    def __init__(self, engine: Engine, options, text: str, client) -> None:
        self.engine = engine
        self.options = options
        self.client = client
        self.stopping = False

        self.ledger = None
        self.product = None

        # What kind of program this is has to be known before it is loaded,
        # because the library the machine is handed is built around a ledger for a
        # strategy and carries none for a study, and a program that places an
        # order is refused at load when there is no ledger to place it against.
        #
        # **Reading a field out of the text is not the same as loading from it.**
        # The bytes handed to the engine below are the file's own, untouched. What
        # happens here is one question asked of a copy: an engine loading a program
        # from text insists on the canonical encoding, and nothing this reads is
        # ever given back to it.
        self.trading = _declared_kind(text, self.options.script) == STRATEGY_KIND

        if self.trading:
            self.ledger = engine.Ledger()
        served = engine.Serving(self.ledger)
        loaded = engine.load_text(
            text,
            self._settings(),
            served,
            capabilities=engine.capabilities(ORDERS_TAG) if self.trading else engine.capabilities(),
            read_time=engine.utc_time,
        )
        if loaded.diagnostic is not None:
            raise Refusal(self._refusal_text(loaded.diagnostic))

        self.run = loaded.run
        self.serving = served
        raw = loaded.run.program.raw
        self.raw = raw
        self._check_readable(raw)

        # The instrument record last, because reading it is the first thing here
        # that leaves this process. Everything a script can be refused for is
        # settled above, so a script that will not run is refused without a
        # request being made about an instrument it was never going to trade.
        self.instrument = self._instrument()
        if self.trading:
            self._begin_ledger(raw)

        self.declared_unconfirmed = bool(raw["meta"].get("onUnconfirmed"))
        self._said_unconfirmed = False

        #: The open instant of every bar already executed as confirmed, oldest
        #: first. Its length is the index the next bar takes, which is what keeps
        #: an index anchored to a bar rather than to a window that rolls.
        self._times: list[int] = []
        #: The moving bar: its index, the open instant it belongs to, and the
        #: state it began with.
        self._moving_at: int | None = None
        self._moving_time: int | None = None
        self._moving_mark = None
        #: How many times the bar at ``_moving_at`` has been handed to the engine.
        #: ``host-interface.md`` section 6.4 counts hand-overs, so it starts at one
        #: on the first execution of a bar and rises by one on every later one,
        #: including the execution that confirms it.
        self._moving_updates = 0
        #: True once the replay over history has finished. Nothing is sent before
        #: it is: see THE HISTORY PASS at the top of this file.
        self._sending = False
        #: The order the platform gave each intent, and the intents still moving.
        self._orders: dict[int, str] = {}
        #: For an intent whose order it shares with another, the part of that
        #: order which is its own: (already allocated before it, its own size).
        #: Absent for an intent that got an order to itself, which is most of
        #: them. See ``_batches`` for when two intents share one order.
        self._shares: dict[int, tuple[int, int]] = {}
        #: Where this run's orders are actually going, learned from the first one
        #: the platform accepted rather than asked for in advance. None until an
        #: order has been accepted. See ``_route`` for why it is watched.
        self._destination: str | None = None
        self._open: set[int] = set()
        self._previous_close = None
        #: The live feed, once `main` has built one, or None for a run driven by
        #: history alone. See `live_bars`: a feed is optional and a run without
        #: one behaves exactly as this platform behaved before there was one.
        self.live = None
        #: Bars this run closed on the feed rather than on history, by open
        #: instant, kept until history carries the same bar so the two can be
        #: compared. Bounded, because a feed that runs ahead of a history
        #: endpoint that is down must not fill this for the length of a session.
        self._from_feed: dict[int, Candle] = {}
        self._said_disagreement = False

    # -- what a refusal reads like ------------------------------------------

    def _refusal_text(self, diagnostic) -> str:
        """An engine diagnostic as one sentence for the trader's log."""
        where = ""
        if getattr(diagnostic, "line", 0):
            where = f" at line {diagnostic.line}"
            if getattr(diagnostic, "column", 0):
                where += f", column {diagnostic.column}"
        return (
            f"{self.options.script} was refused by the engine{where}: {diagnostic.code}. "
            "Open it in the chart, save it again, and check the console."
        )

    # -- what the host states about the instrument --------------------------

    def _instrument(self) -> dict:
        """The instrument record the engine reads its chart facts from.

        A fact nobody states is absent, which is the engine's own rule, so the
        optional ones are looked up and simply left out when the lookup does not
        answer. An absent tick size is a script that cannot round to a tick; a
        wrong one is a script that rounds to the wrong thing.
        """
        record = {
            "symbol": self.options.symbol,
            "exchange": self.options.exchange,
            "interval": self.options.interval,
            "timezone": self.options.timezone,
            "hasVolume": True,
            "hasOpenInterest": False,
        }
        try:
            answered = self.client.symbol(
                symbol=self.options.symbol, exchange=self.options.exchange
            )
        except Exception as unreachable:  # noqa: BLE001 - reported, never fatal
            say(f"The instrument record could not be read, so tick size is absent. ({unreachable})")
            return record

        data = answered.get("data") if isinstance(answered, dict) else None
        if isinstance(data, dict):
            if data.get("tick_size") is not None:
                record["tickSize"] = float(data["tick_size"])
            if data.get("lotsize") is not None:
                record["lotSize"] = float(data["lotsize"])
        return record

    def _settings(self) -> dict:
        """The script's own parameters, as the trader saved them.

        **Read from the environment, because the command line carries only what
        a pattern can check.** An instrument, an exchange and an interval are
        short strings from a fixed alphabet and are checked against one before
        they ever reach a command. A parameter is a key the script chose and a
        value the trader typed, and the parent already uses the environment for
        what does not belong in a process list.

        **A map that cannot be read is an empty one, and says so in the log.**
        The alternative is a run that will not start over its settings, and the
        run is what somebody is watching for. Every value here is still held to
        the script's own declaration by the engine a moment later: the bounds, the
        choices and the type are the script's, and a value that fails one refuses
        the load with a sentence naming the parameter. So this is not the check
        that makes a setting correct, only the one that turns text into values.
        """
        raw = os.getenv("OPENSCRIPT_INPUTS") or ""
        if not raw.strip():
            return {}
        try:
            given = json.loads(raw)
        except ValueError:
            say(
                "The parameters saved for this strategy could not be read, so it is running on "
                "the values written in the script."
            )
            return {}
        if not isinstance(given, dict):
            say(
                "The parameters saved for this strategy are not a set of named values, so it is "
                "running on the values written in the script."
            )
            return {}
        named = {key: value for key, value in given.items() if isinstance(key, str)}
        if named:
            say(f"Running with {', '.join(sorted(named))} set from the saved parameters.")
        return named

    def _check_readable(self, raw: dict) -> None:
        """Refuse a program this runner would answer under the wrong calendar.

        The engine reads a calendar in one zone. An instrument in another is not a
        detail: a script asking what hour it is, or whether this is the session's
        first bar, would be answered under a clock that is hours away from the one
        the trader is looking at. The conformance adapter names exactly these two
        as unsupported and this refuses them for the same reason.

        A session boundary is refused whatever the zone, because this runner
        derives none: it states no ``isSessionFirst`` fact, and a script reading
        one would be answered absence on every bar, which is a silent wrong answer
        rather than a loud one.

        **A calendar read in a zone the engine cannot read is refused for exactly
        the same reason, and it was the one this file used to miss.** The engine
        holds offsets for one zone and answers absence for every other, without
        raising: a script asking what hour a bar opened at, what day of the week
        it is, or whether the bar sits inside a written window, was handed
        absence on every bar of every run. A condition built on absence is never
        true, so the strategy never traded and nothing anywhere said why. That is
        the single outcome worse than refusing to start, because the trader sees a
        run that is going, a log with no complaint in it, and no orders.

        The reads are not listed here. They are asked of the engine, which keeps
        the set, so a call added to the language cannot quietly fall outside a
        copy kept in this file.
        """
        called = {one["name"] for one in raw["lib"]["functions"]}
        wanted = called.intersection(self.engine.session_facts)
        if wanted:
            raise Refusal(
                f"{self.options.script} asks where a trading session begins, which this runner "
                "does not work out. Remove that and save it again."
            )

        blocked = sorted(called.intersection(UNROUTABLE_CALLS))
        if blocked:
            raise Refusal(
                f"{self.options.script} calls {', '.join(blocked)}, which attaches a stop and a "
                "target to a position. This runner cannot send those two as one order yet, and "
                "sending the entry without them would leave a position with nothing protecting "
                "it, so it will not start this script."
            )
        if self.options.timezone != self.engine.readable_zone:
            reads = sorted(called.intersection(self.engine.calendar_reads))
            if reads:
                raise Refusal(
                    f"{self.options.script} reads the clock, with {', '.join(reads)}, and this "
                    f"instrument's calendar is {self.options.timezone}. This runner can only read "
                    f"a clock as {self.engine.readable_zone}, so every one of those calls would "
                    "come back with no answer and the script would never act on one. It will not "
                    "be started on a clock it cannot read."
                )
            if any(one["kind"] == "time" for one in raw["inputs"]):
                raise Refusal(
                    f"{self.options.script} takes a written time, and this runner can only read a "
                    f"clock as {self.engine.readable_zone}. It would answer under the wrong "
                    "calendar, so it will not run it."
                )

    def _begin_ledger(self, raw: dict) -> None:
        """The declaration's own settings, read before the first bar.

        Read through the run rather than off the program, because a declaration
        may state its quantity, its product or its capital from an input, and a
        ledger handed the reference rather than the value would size every order
        from a shape.
        """
        block = raw["meta"].get("strategy")
        if not isinstance(block, dict):
            raise Refusal(
                f"{self.options.script} says it is a strategy and carries no declaration to size "
                "an order from. Save it again from the chart."
            )

        needed = ("qty", "qtyType", "product", "pyramiding")
        missing = [name for name in needed if name not in block]
        if missing:
            raise Refusal(
                f"{self.options.script} declares no {', '.join(missing)}, which is what an order's "
                "size and product are read from."
            )

        declared = {name: self.run.declaration(("meta", "strategy", name)) for name in needed}

        qty_type = declared["qtyType"]
        if qty_type != "units":
            # A quantity counted in anything but units has to be turned into a
            # number of units before an order can carry it, and the two things
            # that would do it, the account's capital and the instrument's lot,
            # are the host's rather than the script's. Sizing an order from a
            # number nobody wrote is the one mistake here that spends money, so it
            # is refused instead.
            raise Refusal(
                f"{self.options.script} sizes its orders by {qty_type}, and this runner only sends "
                "a quantity the script states in units. Change the declaration and save it again."
            )

        declared_product = str(declared["product"])
        chosen = self.options.product
        if chosen:
            chosen = chosen.upper()
            if chosen not in PRODUCTS:
                raise Refusal(
                    f"This run was started with the product {self.options.product}, which is not "
                    f"one this platform sends. Use one of {', '.join(PRODUCTS)}."
                )
            self.product = chosen
        elif declared_product in PRODUCT_FOR:
            self.product = PRODUCT_FOR[declared_product]
        elif declared_product == OVERNIGHT:
            raise Refusal(
                f"{self.options.script} carries its position overnight, and this platform has two "
                f"ways of doing that. Start it again saying which: {', '.join(PRODUCTS)}."
            )
        else:
            raise Refusal(
                f"{self.options.script} asks for the product {declared_product}, which this runner "
                "does not recognise."
            )

        self.ledger.options = self.engine.LedgerOptions(
            instrument=self.engine.Identity(self.options.symbol, self.options.exchange),
            product=declared["product"],
            qty_type=qty_type,
            declared_qty=declared["qty"],
            tick_size=self.instrument.get("tickSize"),
            pyramiding=declared["pyramiding"],
        )

    # -- the loop -----------------------------------------------------------

    def stop(self) -> None:
        """Asked to finish. The loop leaves at its next check."""
        self.stopping = True

    def flatten(self, wait_seconds: float = 20.0) -> bool:
        """Close what this run is holding. True once it is flat, or was already.

        **This is what Stop means and Pause does not.** Pause ends the process
        and leaves the position, which is a trader taking it back. Stop is a
        trader finished with the strategy, and a strategy that ended without
        closing what it opened is a position nothing is watching.

        **The size is this run's own, never the broker's.** Two strategies can
        hold the same instrument, so squaring the account's net position in it
        would close somebody else's. One order for exactly what this ledger says
        it holds, in the opposite direction and tagged with this run, reduces the
        broker's net by this run's share and no more.

        **It goes out beside the strategy rather than through it.** Closing is a
        trader's instruction, not a decision the script made, so there is no
        intent, no bar and no ledger row: the order is sent, watched to a fill by
        its own id, and this run then ends. The ledger is not told, because
        nothing reads it again.

        **A close that does not go out leaves the run running.** The position is
        still there, so something has to be able to stop it: reporting success
        and exiting is how a position ends up with nothing managing it. That is
        the platform's own rule for a stop whose exit orders were refused, and it
        is why this answers False rather than raising.
        """
        held = self._position()
        if not held:
            say("Nothing is open, so this run has nothing to close.")
            return True

        side = "SELL" if held > 0 else "BUY"
        size = int(abs(held))
        if size <= 0 or float(abs(held)) != size:
            say(
                f"This run holds {held}, which cannot be sent as a whole number of units, so it "
                "has not been closed. The position is still open and this run is still here."
            )
            return False

        say(f"Closing what this run holds: {side.lower()} {size} {self.options.symbol}.")
        try:
            answered = self.client.placeorder(
                strategy=self.options.strategy_name,
                symbol=self.options.symbol,
                exchange=self.options.exchange,
                action=side,
                price_type="MARKET",
                product=self.product,
                quantity=size,
            )
        except Exception as unreachable:  # noqa: BLE001 - said, not raised
            say(
                f"The closing order could not be sent, so the position is still open and this "
                f"run is still here. ({unreachable})"
            )
            return False

        if not isinstance(answered, dict) or answered.get("status") != "success":
            reason = "no reason was given"
            if isinstance(answered, dict):
                reason = str(answered.get("message", reason))
            say(
                f"The closing order was not accepted, so the position is still open and this "
                f"run is still here: {reason}"
            )
            return False

        order_id = str(answered.get("orderid", ""))
        say(f"The closing order is {order_id}. Watching it.")

        # Watched to a fill rather than sent and forgotten. An order accepted
        # here and rejected at the broker leaves exactly the position this was
        # pressed to be rid of, and a run that had already exited could not say.
        until = time.time() + wait_seconds
        while time.time() < until and not self._order_is_done(order_id):
            time.sleep(0.5)

        if self._order_is_done(order_id):
            say("Closed. This run holds nothing.")
            return True

        say(
            "The closing order was accepted and has not finished yet. The position may still be "
            "open, so this run stays here rather than leaving it to nobody. Check the order, "
            "then stop this run again."
        )
        return False

    def _order_is_done(self, order_id: str) -> bool:
        """Whether this order has filled. Unreadable answers no, deliberately.

        An order this cannot read may still be working, and treating that as
        done is how a run exits on a position that never closed.
        """
        try:
            answered = self.client.orderstatus(
                order_id=order_id, strategy=self.options.strategy_name
            )
        except Exception:  # noqa: BLE001 - asked again in a moment
            return False
        if not isinstance(answered, dict) or answered.get("status") != "success":
            return False
        data = answered.get("data")
        if not isinstance(data, dict):
            return False
        return STATUS_WORDS.get(str(data.get("order_status", "")).strip().lower()) == "filled"

    def cycle(self) -> int | None:
        """One wake: the feed's closed bars if it has any, otherwise history.

        Returns an exit code once the run is over and ``None`` while it goes on.

        **The feed is asked first because it is the one that knows.** A bar is
        complete on the tick stream the instant it closes, and a history
        endpoint carries it seconds later: on this platform a closed one minute
        bar was measured about thirty five seconds late. Asking history first
        would spend that lateness on every order for a fact the process already
        had.

        **History is not thereby retired.** It is what the run is replayed on
        before anything is sent, what carries the bars of a gap the feed was
        disconnected for, what drives a run whose feed never connected, and what
        the bars this run closed on the feed are compared against. It is polled
        on every wake the feed had nothing new for, which on a one minute bar at
        the ordinary cadence is most of them.
        """
        if self._feed_ready():
            acted, finished = self._live_cycle()
            if finished is not None:
                return finished
            if acted:
                return None

        candles = self._history()
        if not candles:
            say("History answered with no bars. Waiting.")
            return None

        self._compare_with_feed(candles)

        fresh = self._new_bars(candles)
        if fresh is None:
            return EXIT_DIAGNOSTIC
        if not fresh:
            # The newest bar this run has is still the newest bar there is, and
            # the feed is not carrying the one after it yet. Nothing to execute.
            return None

        confirmed, moving = fresh[:-1], fresh[-1]

        # How many bars this run has supplied, counted in the same space the bar
        # indices are counted in. It is NOT the length of the window that came
        # back.
        #
        # The engine reads ``bar.isLast`` as ``index == supplied - 1``, and this
        # driver's indices are anchored to bar open times: they start at zero and
        # grow by one per confirmed bar, for the whole life of the run. The
        # history window does not. A run polling a five day window loses its
        # oldest bar every day, so after the window has turned over once, the
        # length of the window is permanently smaller than the index of the
        # newest bar, ``index == len(candles) - 1`` is never true again, and
        # ``bar.isLast`` is false on every bar for the rest of the run. A
        # strategy written to act on the final bar simply stops firing, with
        # nothing in the log to say why. That was the defect.
        #
        # The greatest index this poll will hand over is the moving bar's, which
        # is ``len(self._times) + len(fresh) - 1``, so one more than that is the
        # count that makes the newest bar the last one. It is worked out once,
        # before any bar of this batch is executed, because every bar of one
        # hand-over is measured against the same greatest index: the bars ahead
        # of the newest one in a catch-up batch are then not last, which is what
        # they are, and the newest one is.
        supplied = len(self._times) + len(fresh)

        for candle in confirmed:
            stopped = self._execute(candle, supplied, confirmed_bar=True)
            if stopped is not None:
                return stopped
            if self.stopping:
                # Something inside that bar asked this run to stop, and the bars
                # behind it in the same catch-up batch are not executed. A run
                # that stopped because its position is half moved would otherwise
                # go straight on and send the next bar's orders on top of it,
                # which is the one thing a stopped run must not do.
                return None

        if self.stopping:
            return None

        if self._moving_at is None and not self._sending:
            # Everything before the newest bar has now been replayed, so the
            # handoff is here, and it is said out loud: a strategy picked up flat
            # has nothing to exit, and a trader running an always-in-market script
            # should read that at the moment it happens rather than find it later.
            self._hand_over()

        return self._execute(moving, supplied, confirmed_bar=False)

    def _feed_ready(self) -> bool:
        """Whether a bar may be closed on the feed rather than on history.

        Not before the history replay has finished. A run is replayed over
        whatever history holds and only then begins sending, and a bar arriving
        from the feed in the middle of that would be executed out of order,
        against a state built from a different series.
        """
        return self._sending and self.live is not None and self.live.live

    def _live_cycle(self) -> tuple[bool, int | None]:
        """Execute what the feed has closed. Answers (did anything, exit code).

        The anchor rules here exactly as it rules in ``_new_bars``: a bar at or
        before the last confirmed open instant has been executed already and is
        dropped rather than executed at a second index.

        A bar the feed never built, because nothing traded in that span, leaves
        a gap in these open instants. It is not bridged and not waited for,
        which is what history does with the same gap: a span with no trade is a
        span with no bar, and a run that stalled for one would stall until the
        instrument traded again.
        """
        now_ms = int(time.time() * 1000)
        anchor = self._times[-1] if self._times else None
        fresh = [
            Candle(*bar)
            for bar in self.live.closed(now_ms)
            if anchor is None or bar[0] > anchor
        ]
        moving_bar = self.live.forming(now_ms)
        if not fresh and moving_bar is None:
            return False, None

        # The same count `cycle` works out, and for the same reason: the engine
        # reads `bar.isLast` as `index == supplied - 1`, so it is the greatest
        # index this hand-over will reach plus one, settled before any bar of it
        # is executed.
        supplied = len(self._times) + len(fresh) + (1 if moving_bar is not None else 0)

        for candle in fresh:
            # Kept so that history's own version of this bar can be compared
            # with the one acted on, when it eventually carries it.
            self._from_feed[candle.time] = candle
            if len(self._from_feed) > FEED_BARS_COMPARED:
                del self._from_feed[min(self._from_feed)]

            stopped = self._execute(candle, supplied, confirmed_bar=True)
            if stopped is not None:
                return True, stopped
            if self.stopping:
                # Something inside that bar asked this run to stop. The bars
                # behind it are not executed, for the reason `cycle` gives.
                return True, None

        if moving_bar is not None:
            stopped = self._execute(Candle(*moving_bar), supplied, confirmed_bar=False)
            if stopped is not None:
                return True, stopped

        return bool(fresh) or moving_bar is not None, None

    def _compare_with_feed(self, candles: list[Candle]) -> None:
        """Say so when history disagrees with a bar this run acted on.

        **This can only report, and that is the honest shape of it.** The order
        went out when the bar closed; a bar that turns out to have been a paisa
        different cannot be taken back. What a trader can do with it is decide
        whether to keep running this way, and they can only do that if it is
        said out loud the first time it happens rather than discovered in a
        report months later.

        A feed and a history endpoint rarely agree to the last tick: the feed is
        every trade this process saw while subscribed and history is the
        exchange's own bar. The threshold is there so that a run does not narrate
        the last decimal place of every bar.
        """
        if not self._from_feed:
            return
        for candle in candles:
            mine = self._from_feed.pop(candle.time, None)
            if mine is None or self._said_disagreement:
                continue
            for name in ("open", "high", "low", "close"):
                theirs = getattr(candle, name)
                ours = getattr(mine, name)
                if theirs in (None, 0) or ours in (None, 0):
                    continue
                if abs(theirs - ours) / abs(theirs) > FEED_DISAGREEMENT:
                    self._said_disagreement = True
                    say(
                        "This run closes a bar on the live feed, which is how it acts at the "
                        f"close rather than when history catches up. History's {name} for the "
                        f"bar at {_bar_time_text(candle.time)} is {theirs}, and the run acted on "
                        f"{ours}. Said once."
                    )
                    break

    def _hand_over(self) -> None:
        self._sending = True
        say(
            f"Replayed {len(self._times)} bars of history. Nothing was sent for them, and this run "
            "begins holding nothing: an exit written for a position the history would have opened "
            "has nothing to exit."
        )
        if self.trading and self.declared_unconfirmed and not self._said_unconfirmed:
            self._said_unconfirmed = True
            say(
                "This script asks to act on a bar that is still moving. Orders are sent when a bar "
                "closes, which is what its backtest did, so intrabar calls are not sent."
            )

    def _history(self):
        """Whatever the platform has for this instrument, as candles."""
        end = datetime.now()
        start = end - timedelta(days=self.options.history_days)
        try:
            answered = self.client.history(
                symbol=self.options.symbol,
                exchange=self.options.exchange,
                interval=self.options.interval,
                start_date=start.strftime("%Y-%m-%d"),
                end_date=end.strftime("%Y-%m-%d"),
            )
        except Exception as unreachable:  # noqa: BLE001 - a poll may fail and be retried
            say(f"History could not be read this time. Retrying. ({unreachable})")
            return []
        try:
            return candles_from(answered)
        except Refusal as refused:
            say(str(refused))
            return []

    def _new_bars(self, candles: list[Candle]) -> list[Candle] | None:
        """The bars this run has not executed yet, oldest first.

        Anchored on the open instant of the last confirmed bar rather than on a
        count, because the history window rolls: a run polling a five day window
        loses its oldest bar every day, and a driver counting from the start of
        whatever came back would shift every index by one and hand the engine a
        brand new bar on every poll.

        A window that no longer holds the anchor is a discontinuity this runner
        cannot bridge, so it stops rather than guessing which bars it missed.
        **A window that is merely behind the anchor is not that.** Since a run
        closes its bars on the live feed, history is routinely a bar or two
        behind what has already been executed, and reading that as a gap would
        stop a run every minute for doing exactly what it is meant to do.
        """
        if not self._times:
            return candles

        anchor = self._times[-1]
        if candles and candles[-1].time < anchor:
            # Everything here is older than the last bar executed. Nothing is
            # missing: history has not caught up yet.
            return []
        for at in range(len(candles) - 1, -1, -1):
            if candles[at].time == anchor:
                # Everything after the anchor, which is empty when no bar has
                # formed since. The anchor itself is never returned: it has been
                # executed as a confirmed bar and has its index already, and
                # handing it back would execute the same bar at a second index.
                return candles[at + 1 :]

        say(
            "The history this run was following no longer reaches the last bar it executed, so it "
            "cannot tell what it missed. Stopping."
        )
        return None

    def _execute(self, candle: Candle, supplied: int, confirmed_bar: bool) -> int | None:
        """One execution of one bar. Returns an exit code, or nothing to go on.

        The index is ``len(self._times)`` for a bar not yet confirmed and stays
        there for as long as that bar keeps moving, which is what lets the engine
        recognise a re-execution and put its state back. It becomes a confirmed
        bar's index at the moment the bar's open instant is appended.

        ``supplied`` is the count ``cycle`` worked out for this whole hand-over,
        which is the greatest index in it plus one. It is not the length of the
        history window: see the note there.
        """
        index = len(self._times)
        moving_again = self._moving_at == index and self._moving_time == candle.time

        if moving_again and self._moving_mark is not None:
            # The state the bar began with, restored before it runs again. The
            # engine does this too, from its own checkpoint taken at the same
            # instant, so this line is redundant on today's engine and is here to
            # say what this driver depends on. See THE MOVING BAR at the top of
            # this file, which says so rather than implying otherwise.
            self.run.restore(self._moving_mark)
        elif not confirmed_bar:
            self._moving_at = index
            self._moving_time = candle.time
            self._moving_mark = self.run.checkpoint(index)
            self._moving_updates = 0

        # ``host-interface.md`` section 6.4: the count of hand-overs and the count
        # of executions are one number, incremented once per hand-over of the same
        # bar. Its worked case for a bar that is still forming is 1, 2, 3 and on,
        # and the confirming execution of that bar is the next hand-over of it
        # rather than a fresh one, so the count carries on through it.
        #
        # A bar this run never saw moving is handed over once, which is the other
        # worked case in that table: a history load states one update per bar.
        #
        # It was 1.0 on every execution before, so a script reading ``bar.updates``
        # could not tell a first intrabar execution from a tenth, and anything
        # written to act on a settled price rather than on the first tick of a bar
        # had no fact to read.
        if moving_again or not confirmed_bar:
            self._moving_updates += 1
            updates = self._moving_updates
        else:
            updates = 1

        if self.trading and self._sending:
            # The fold is before the execution, never after it: a driver that
            # folded afterwards would let a script react inside the bar its own
            # order was sent on, and one that folded during a bar would give two
            # executions of a moving bar two different positions to read.
            self._fold()

        self.serving.at_bar(
            {
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "previousClose": self._previous_close,
                "volume": candle.volume,
            },
            index == 0,
        )

        result = self.run.execute_bar(
            index,
            self.engine.Bar(
                time=float(candle.time),
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            ),
            self.engine.BarState(
                is_new=not moving_again,
                is_confirmed=confirmed_bar,
                is_realtime=self._sending,
                updates=float(updates),
            ),
            supplied=supplied,
            instrument=self.instrument,
            # The clock is the bar's own open instant and not the wall clock. Two
            # executions of one moving bar are then handed the same moment, which
            # is what makes the second one a re-execution rather than a different
            # run. A wall clock here would put a value into the state that no
            # restore could take back.
            now=float(candle.time),
        )

        if result.diagnostic is not None:
            # A diagnostic stops this strategy and nothing else. It is the script
            # that failed, so it is written where the trader who wrote it reads.
            found = result.diagnostic
            say(
                f"{self.options.script} stopped on bar {index}: {found.code} at line {found.line}, "
                f"column {found.column}. Nothing further will be sent for it."
            )
            return EXIT_DIAGNOSTIC

        for alert in result.alerts:
            say(f"Alert {alert.key}: {alert.title} {alert.message}")

        if confirmed_bar:
            self._times.append(candle.time)
            self._previous_close = candle.close
            if self._moving_at == index:
                self._moving_at = None
                self._moving_time = None
                self._moving_mark = None
                self._moving_updates = 0
            if self.trading and self._sending and result.applied:
                if self._place(result.applied, index, candle.time) is not None:
                    return EXIT_DIAGNOSTIC
        return None

    # -- orders -------------------------------------------------------------

    def _place(self, effects, index: int, when: int) -> object | None:
        """The order calls a confirmed bar made, mapped and then routed.

        Every call is mapped before any of them is routed, and a refusal in the
        MAPPING takes the whole bar back: nothing has left, so the bar sends both
        or neither. That is the ledger's rule and not this driver's, and it is the
        only part of a bar this file can promise both or neither for.

        **What happens once an order has actually gone out is a different thing,
        and it is written down in ``_send`` rather than promised here.** One call
        can be two orders: a reversal is a close and an open, and the platform has
        no call that sends a pair atomically. An order that has reached the order
        path cannot be taken back, so a refusal after one has gone is not a bar
        that sent nothing, it is a position that is half moved. This file does not
        pretend otherwise and does not send a compensating order to tidy it up.
        """
        bar = self.engine.IntentBar(index=index, time=float(when))
        appended = len(self.ledger.rows())
        sending = []
        for effect in effects:
            placed = self.ledger.place(effect.name, effect.arguments, bar, effect.position)
            if placed.refusal is not None:
                self.ledger.discard(appended)
                found = placed.refusal
                say(
                    f"{self.options.script} stopped on bar {index}: its order was refused, "
                    f"{found.code} at line {found.line}, column {found.column}. Nothing was sent "
                    "for this bar."
                )
                return found
            sending.extend(placed.intents)

        # Both or neither, a second time and for a different reason. The ledger
        # has already refused what it refuses; this is the driver refusing what it
        # cannot carry to the platform. It is checked across the whole bar before
        # any of it goes out, because the order that cannot be sent is usually the
        # one protecting the order that can.
        unroutable = [one.kind for one in sending if one.kind not in ("place", "cancel")]
        if unroutable:
            self.ledger.discard(appended)
            say(
                f"{self.options.script} asked on bar {index} for an order this runner cannot send "
                f"as one piece ({', '.join(sorted(set(unroutable)))}). Nothing was sent for this "
                "bar and the run is stopping."
            )
            self.stop()
            return None

        return self._send(sending, index)

    def _send(self, sending, index: int) -> object | None:
        """One bar's intents, routed in order, and what is done when one is not.

        THE DECISION, AND WHY IT IS THIS ONE
        ------------------------------------

        A bar can produce more than one order. ``order.reverse`` is a close and an
        open, and the two are only correct together: closing without opening
        leaves the strategy flat when it meant to be the other way round, and
        opening without closing doubles the position instead of turning it.

        There is no atomic way to send them. This platform sends one order per
        call, and an order that has reached the order path has been decided on and
        may already have filled. So "both or neither" cannot be kept once the
        first one has gone, and there are exactly two honest things to do about
        it:

        1. Send a compensating order to undo the one that went out. This is not
           chosen. The compensating order can be refused in its turn, it fills at
           a different price, and it is this program deciding by itself to trade
           in a direction no script asked for. A runner that quietly trades to fix
           its own bookkeeping is worse than one that stops.

        2. Stop, and say so loudly enough that a person goes and looks. This is
           what happens below. The run sends nothing further, the log names the
           bar and what did go out, and the position is left exactly as the
           platform has it rather than being described as something else.

        A refusal before anything has gone out is not that case: nothing moved, so
        the rest of the bar is held back, every held order is recorded in the
        ledger as not sent, and the run carries on. That is the "neither" half,
        and it is kept wherever it can still be kept.

        A cancellation is not counted as a move. It withdraws an order that has
        not filled, so a run whose only completed send was a cancellation has not
        moved a position and is not half moved.
        """
        # Grouped first, so a reversal reaches the broker as the one order it
        # nets to rather than as the two the engine's own position bookkeeping
        # needs. `_batches` says why, and why most bars have one intent each.
        batches = self._batches(sending)
        flat = [one for batch in batches for one in batch]

        moved = 0
        for index_of_batch, batch in enumerate(batches):
            if self._route_batch(batch):
                if any(one.kind != "cancel" for one in batch):
                    moved += 1
                continue

            at = sum(len(each) for each in batches[:index_of_batch])
            # Nothing after the refused order goes out. The ledger is told about
            # each of them, or it would go on holding rows for orders that are not
            # with the platform and this run would never replace them. The
            # batch's own intents are already accounted for by `_route_batch`.
            for later in flat[at + len(batch) :]:
                if later.kind == "cancel":
                    say(
                        "A cancellation was not asked for, because an order earlier on this bar "
                        "was not sent."
                    )
                    continue
                self._reject(
                    later, "an order earlier on this bar was not sent, so this one was held back"
                )

            if moved == 0:
                say(
                    f"{self.options.script} had an order refused on bar {index}. Nothing that "
                    "moves a position went out for that bar, so the position has not moved, and "
                    "the orders behind the refused one were held back."
                )
                return None

            say(
                f"THIS RUN IS STOPPING AND ITS POSITION IS HALF MOVED. On bar {index} this script "
                f"asked for {len(sending)} orders. {moved} of them reached the platform and moved "
                "a position, the next one did not, and an order that has gone out cannot be taken "
                "back. Nothing further "
                "will be sent for this script. Check what this strategy is holding against what "
                f"you meant it to hold, under the name {self.options.strategy_name}, and square "
                "the difference yourself."
            )
            self.stop()
            return None
        return None

    def _batches(self, sending):
        """One bar's intents, grouped into the orders this runner will send.

        **Why two intents can be one order.** The engine never sends an order
        across zero: an instruction taking a position from long to short is two
        intents, one closing the outgoing position and one opening its
        replacement, each with its own position reference, so that a fill
        arriving late can say which of the two it settled. That is the engine's
        bookkeeping and it is right. It is not the broker's: a broker holds one
        net position in one instrument, and telling it to buy one and then buy
        one again is telling it to buy two, in two orders, at two commissions
        and two spreads, for a position change a trader asked for once.

        So orders that differ only in which of this run's own positions they
        belong to are sent as one, and the fill is split back across the intents
        afterwards by ``_shares``. The engine keeps its two positions and the
        broker sees the one order it would have netted anyway.

        **It also removes the half moved bar.** ``_send`` has to stop a run whose
        first order reached the platform and whose second did not, because a
        reversal that only closed leaves a strategy flat when it meant to be the
        other way round and there is no way to take the first one back. One order
        cannot half move a position: it is accepted or it is not.

        **What is never merged.** Only plain market orders of the same side, in
        the same instrument, under the same product. A limit and a market are
        different instructions; two sides net to a quantity nobody wrote; and a
        cancellation is not an order at all. Anything that is not exactly like
        its neighbour starts a new batch, so the merge can only ever combine
        orders that a broker would have filled identically.

        **Order is kept.** A batch is made of neighbours, never gathered from
        across the bar, because the sequence is what ``_send`` reports a half
        moved position against and what the fill allocation below counts on.
        """
        batches: list[list] = []
        for intent in sending:
            if batches and self._merges(batches[-1][-1], intent):
                batches[-1].append(intent)
            else:
                batches.append([intent])
        return batches

    def _merges(self, earlier, later) -> bool:
        """Whether these two are the same instruction twice, for one broker.

        **Anything it cannot read is a no.** Merging is an optimisation and not
        merging is always correct, so an intent whose shape this does not
        recognise falls back to the order per call this runner has always sent.
        The alternative is a fault raised in the middle of a bar that is placing
        orders, which stops a run over a saving.
        """
        try:
            if earlier.kind != "place" or later.kind != "place":
                return False
            if str(earlier.side) != str(later.side):
                return False
            for one in (earlier, later):
                placement = one.placement
                # A market order and nothing else. A limit or a stop carries a
                # price the broker matches on, and two of them are not one order
                # however alike they look.
                if (placement.order_type or "market") != "market":
                    return False
                if placement.limit is not None or placement.trigger is not None:
                    return False
                if one.qty is None or one.qty <= 0 or float(one.qty) != int(one.qty):
                    return False
            # The instrument and the product are this run's own and are the same
            # for every order it sends, so they are equal by construction.
            # Compared anyway, because a leg is coming and the day it does this
            # is the line that would otherwise net two instruments into one
            # order. An intent that states neither is not merged: this cannot
            # tell "the same instrument" from "no instrument named".
            here = getattr(earlier, "instrument", None)
            there = getattr(later, "instrument", None)
            if here is None or there is None:
                return False
            return (
                here.symbol == there.symbol
                and here.exchange == there.exchange
                and str(getattr(earlier, "product", "")) == str(getattr(later, "product", ""))
            )
        except Exception:
            logger_say = "Two orders on this bar could not be compared, so each was sent on its own."
            say(logger_say)
            return False

    def _route_batch(self, batch) -> bool:
        """One batch as one order, or one intent the ordinary way."""
        if len(batch) == 1:
            return self._route(batch[0])

        total = sum(int(one.qty) for one in batch)
        sent = self._route(batch[0], quantity=total, covering=batch)
        if not sent:
            # The one order carried all of them, so a refusal refuses all of
            # them. The first is already recorded by `_route`; the rest are told
            # here, or the ledger would hold rows for orders nobody has.
            for later in batch[1:]:
                self._reject(later, "the order these were sent as one of was not accepted")
        return sent

    def _route(self, intent, quantity=None, covering=None) -> bool:
        """One intent, as the platform's own order call. True when it reached it.

        ``quantity`` and ``covering`` are how a batch is sent: the order carries
        the whole batch's size and every intent in it is recorded against the
        one order id, each with the part of it that is its own. See ``_batches``
        for why two intents are ever one order.

        The answer is what ``_send`` measures a half moved bar with, so it is
        about the platform having accepted the order and nothing more: it is not a
        fill, and it is not a promise the order will fill. A cancellation answers
        true, because it is re-read on the next poll and withdrawing an unfilled
        order moves no position.

        Nothing here passes ``force_live`` and there is no way to make it. The
        order path reads the platform's analyzer toggle before anything else, so
        where this run's orders go is where every other surface's orders go.

        **That is a decision with a consequence, and the consequence is guarded
        rather than left silent.** Because the toggle is read per order and not
        per run, an operator turning the analyzer on to try something elsewhere
        would send this run's exits to the sandbox while the broker still holds
        the position the entries opened. The platform says so in its own words in
        ``services/place_order_service.py``. ``force_live`` is the documented way
        out and this runner deliberately does not take it, so instead the
        destination of the first accepted order is remembered and every later one
        is checked against it. A run that was **holding** when its destination
        changed is stopped, loudly, with the position named: continuing would be
        sending an exit somewhere the entry never went, which is the one outcome
        worse than stopping. A run that was flat follows the platform instead,
        because there is nothing open anywhere to be stranded and an operator
        moving the platform between live and analyzer is an ordinary thing to
        do several times a day.
        """
        # Read before the order goes out, because the answer afterwards is about
        # a position this order has already begun to move. Flat here means
        # everything this run has open is at whatever destination this order
        # reaches, which is what makes following the platform safe.
        held_before = self._position()

        if intent.kind == "cancel":
            self._cancel(intent)
            return True

        price_type = PRICE_TYPES.get(intent.placement.order_type or "market")
        if price_type is None:
            self._reject(intent, f"the order type {intent.placement.order_type} is not sent here")
            return False

        quantity = intent.qty if quantity is None else quantity
        if quantity is None or quantity <= 0:
            self._reject(intent, "the order had no quantity to send")
            return False
        if float(quantity) != int(quantity):
            # Rounding a quantity down is this runner choosing how much to trade,
            # and rounding it up is worse. Neither is a decision to take quietly.
            self._reject(intent, f"a quantity of {quantity} cannot be sent as a whole number")
            return False

        extra = {}
        if intent.placement.limit is not None:
            extra["price"] = intent.placement.limit
        if intent.placement.trigger is not None:
            extra["trigger_price"] = intent.placement.trigger

        try:
            answered = self.client.placeorder(
                strategy=self.options.strategy_name,
                symbol=self.options.symbol,
                exchange=self.options.exchange,
                action=str(intent.side).upper(),
                price_type=price_type,
                product=self.product,
                quantity=int(quantity),
                **extra,
            )
        except Exception as unreachable:  # noqa: BLE001 - recorded as a rejection
            self._reject(intent, str(unreachable))
            return False

        if not isinstance(answered, dict) or answered.get("status") != "success":
            reason = "no reason was given"
            if isinstance(answered, dict):
                reason = str(answered.get("message", reason))
            self._reject(intent, reason)
            return False

        went_to = "analyzer" if str(answered.get("mode", "")) == "analyze" else "live"
        if self._destination is None:
            self._destination = went_to
            say(f"Orders from this run are going to the {went_to} destination.")
        elif went_to != self._destination:
            # **What makes a changed destination dangerous is a position, not
            # the change.** An operator moving the platform between live and
            # analyzer is an ordinary thing to do, several times a day. A run
            # that was holding nothing when they did it has nothing open at the
            # earlier destination, so it simply follows the platform and carries
            # on, which is what a trader expects of a strategy they left
            # running: it used to stop, so a toggle flipped and back silently
            # killed every idle strategy on the server.
            #
            # `held_before` is the position this run had before the order that
            # has just gone out, because that order is already at the new
            # destination: flat before it means everything now open is there
            # too, and nothing is stranded.
            if not held_before:
                self._destination = went_to
                say(
                    f"The platform's analyzer setting changed, so this run now sends to the "
                    f"{went_to} destination. It was holding nothing when that happened, so "
                    "nothing is open at the earlier one and this run continues."
                )
            else:
                # Do not try to put it back. The entry is where it is, and this
                # run can no longer reason about the position it thinks it holds.
                self.stop()
                say(
                    f"STOPPING: this order went to the {went_to} destination and every order "
                    f"before it went to the {self._destination} one. The platform's analyzer "
                    "setting changed while this run was holding a position. Whatever is open "
                    "was opened against the earlier destination and must be checked and closed "
                    "by a person: this run will send nothing further."
                )
                return False

        order_id = str(answered.get("orderid", ""))
        for at, one in enumerate(covering or [intent]):
            self._orders[one.intent_id] = order_id
            self._open.add(one.intent_id)
            if covering is not None:
                # What this intent owns of the shared order: everything the
                # intents before it own, then its own size. The fold hands out a
                # fill against these in the same order.
                before = sum(int(each.qty) for each in covering[:at])
                self._shares[one.intent_id] = (before, int(one.qty))

        if covering is not None and len(covering) > 1:
            say(
                f"Sent {intent.side} {int(quantity)} {self.options.symbol} as {price_type} "
                f"{self.product}, for {len(covering)} order calls this bar made. "
                f"Order {order_id}."
            )
        else:
            say(
                f"Sent {intent.side} {int(quantity)} {self.options.symbol} as {price_type} "
                f"{self.product}. Order {order_id}."
            )
        return True

    def _position(self) -> float:
        """This run's net position in units, ``0`` while flat.

        The ledger's own answer rather than a second count kept beside it, and
        zero for a study, which holds no ledger and can hold no position.
        Nothing raises: this is read on the order path, and a run that refused
        to send because it could not measure itself would be worse than one that
        treats an unreadable position as a held one.
        """
        if self.ledger is None:
            return 0.0
        try:
            return float(self.ledger.size())
        except Exception:  # noqa: BLE001 - see the note above
            say("This run could not read its own position, so it is treated as holding.")
            return 1.0

    def _cancel(self, intent) -> None:
        """Cancel every order of this run that still carries the tag named.

        A cancellation names a tag rather than an order, because a script names
        what it wrote and the destination's own reference is the host's. So the
        rows this run placed are what answer it.
        """
        tag = intent.placement.tag or ""
        for row in self.ledger.rows():
            if row.tag != tag or row.intent_id not in self._open:
                continue
            order_id = self._orders.get(row.intent_id)
            if not order_id:
                continue
            try:
                self.client.cancelorder(order_id=order_id, strategy=self.options.strategy_name)
            except Exception as unreachable:  # noqa: BLE001 - reported, the poll re-reads it
                say(f"Order {order_id} could not be cancelled this time. ({unreachable})")
                continue
            say(f"Asked for order {order_id} to be cancelled.")

    def _reject(self, intent, reason: str) -> None:
        """An order that never reached the platform, recorded as what it is.

        The ledger already holds a row for it, at the engine's own ``placed``. It
        has to be told, or this run would go on believing an order is out there
        and would never replace it.
        """
        say(f"An order was not sent: {reason}")
        self.ledger.deliver(
            self.engine.OrderFrame(
                intent_id=intent.intent_id,
                status="rejected",
                filled_qty=0.0,
                text=reason,
            )
        )

    def _fold(self) -> None:
        """What the platform says became of every order still out, then the settle.

        A frame is cumulative: it restates the whole life of one order rather than
        what changed since the last one, which is what makes a repeat harmless.
        """
        for intent_id in sorted(self._open):
            order_id = self._orders.get(intent_id)
            if not order_id:
                continue
            frame = self._frame_for(intent_id, order_id)
            if frame is None:
                continue
            self.ledger.deliver(frame)

        for outcome in self.ledger.settle():
            if outcome.refused:
                say(f"A report about order {outcome.intent_id} was refused: {outcome.refused}.")
            if outcome.after_terminal:
                say(
                    f"Order {outcome.intent_id} reported a fill after it had already finished: "
                    f"{outcome.event}."
                )

    def _frame_for(self, intent_id: int, order_id: str):
        """One order's state, as a frame, or nothing when it could not be read."""
        try:
            answered = self.client.orderstatus(
                order_id=order_id, strategy=self.options.strategy_name
            )
        except Exception as unreachable:  # noqa: BLE001 - the next poll asks again
            say(f"Order {order_id} could not be read this time. ({unreachable})")
            return None

        if not isinstance(answered, dict) or answered.get("status") != "success":
            return None
        data = answered.get("data")
        if not isinstance(data, dict):
            return None

        word = str(data.get("order_status", "")).strip().lower()
        status = STATUS_WORDS.get(word)
        if status is None:
            return None

        # The order book carries the quantity the order was sent for and the
        # average price it traded at. It does not carry a running filled quantity,
        # so a finished order counts as filled for its whole quantity and one
        # still working counts as nothing filled yet. A partial fill on a working
        # order is therefore invisible until the order finishes.
        filled = 0.0
        price = None
        if status == "filled":
            filled = float(data.get("quantity", 0) or 0)
            raw_price = data.get("average_price")
            price = float(raw_price) if raw_price else None

        # **An order this intent shares with another gives it only its own part.**
        # A reversal is sent as one order and the engine holds it as two, so the
        # order's whole quantity reported against each of them would fold twice
        # what actually traded and leave the run believing it holds double.
        #
        # Handed out in the order the intents were sent: everything before this
        # one fills first, then this one, up to what it asked for. A whole fill
        # gives each exactly its own size, which is every fill this platform
        # reports, since a working order's partial fill is invisible until it
        # finishes. A short fill would settle the earlier intent and leave the
        # later one open, which is the truthful reading of one order that only
        # partly traded.
        share = self._shares.get(intent_id)
        if share is not None:
            before, own = share
            filled = float(max(0.0, min(float(own), filled - float(before))))

        if word in FINISHED:
            self._open.discard(intent_id)

        return self.engine.OrderFrame(
            intent_id=intent_id,
            status=status,
            filled_qty=filled,
            avg_fill_price=price,
            order_ref=order_id,
            time=float(int(time.time() * 1000)),
        )


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def parse_arguments(argv):
    parser = argparse.ArgumentParser(
        description="Run one compiled OpenScript program against the platform."
    )
    parser.add_argument("--script", required=True, help="the .oscript file to run")
    parser.add_argument("--symbol", required=True, help="the instrument, in platform format")
    parser.add_argument("--exchange", required=True, help="the exchange the instrument trades on")
    parser.add_argument("--interval", required=True, help="the bar interval, for example 1m")
    parser.add_argument(
        "--timezone",
        default="Asia/Kolkata",
        help="the zone the instrument's calendar reads in",
    )
    parser.add_argument(
        "--product",
        default="",
        help=(
            "the product orders are sent as; required for a script that carries its position "
            f"overnight ({', '.join(PRODUCTS)})"
        ),
    )
    parser.add_argument("--history-days", type=int, default=5)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="stop after this many polls; 0 runs until stopped",
    )
    parser.add_argument(
        "--strategy-name",
        default=os.getenv("STRATEGY_NAME", "OpenScript"),
        help="the name orders are tagged with",
    )
    return parser.parse_args(argv)


def build_client(options):
    """The platform SDK, pointed at this host.

    An order placed through it reaches the local order path, which reads the
    analyzer toggle. That is the whole reason a strategy goes out this way rather
    than reaching a broker.
    """
    api_key = os.getenv("OPENALGO_API_KEY")
    if not api_key:
        raise Refusal(
            "This run has no API key, so it cannot reach the platform to read bars or send "
            "orders. Start it from the strategy page, which supplies one."
        )
    try:
        from openalgo import api
    except ImportError as missing:
        raise Refusal(
            f"The platform client is not installed on this server. ({missing})"
        ) from missing

    host = os.getenv("OPENALGO_HOST") or os.getenv("HOST_SERVER", "http://127.0.0.1:5000")
    return api(api_key=api_key, host=host)


def main(argv=None) -> int:
    options = parse_arguments(sys.argv[1:] if argv is None else argv)

    say(f"Starting {options.script} on {options.symbol} {options.exchange} {options.interval}.")
    say("Orders go through this platform's own order path, so sandbox mode is honoured.")

    try:
        # The script before the installation, deliberately. Both refusals are
        # true when a deployment has neither, and the one naming the script is the
        # one the operator asked about and the one they can act on. It also makes
        # the refusal for a script with nothing compiled the same sentence on
        # every deployment rather than depending on what else is installed.
        text = program_text(options.script)
        engine = Engine()
        client = build_client(options)
        session = Session(engine, options, text, client)
    except Refusal as refused:
        say(str(refused))
        say("Nothing was started and nothing was sent.")
        return EXIT_REFUSED

    def leave(signum, frame):  # noqa: ARG001 - the handler's shape is fixed
        say("Asked to stop. Finishing the current bar.")
        session.stop()

    # What this run does on the way out, read from the instruction the parent
    # left for it rather than from the signal, because the two signals a run
    # answers both only mean "leave" and Windows has no third one. See
    # `services/openscript_commands`.

    # SIGBREAK is the Windows half: the service sends CTRL_BREAK_EVENT to this
    # process group, and without a handler for it the default action ends the
    # process where it stands rather than at the end of the bar.
    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        handled = getattr(signal, name, None)
        if handled is not None:
            try:
                signal.signal(handled, leave)
            except (ValueError, OSError):
                # Not the main thread, or a platform without it. The loop still
                # leaves when the process is terminated.
                pass

    say(f"{options.script} loaded. Replaying history before anything is sent.")

    bar_seconds = interval_seconds(options.interval)

    # The tick stream, which is what closes a bar. History stays underneath it:
    # see `Session.cycle`. A feed that will not start leaves `session.live` as
    # None and the run is the history driven run this platform had before.
    feed = LiveBars(client, options.symbol, options.exchange, bar_seconds, say)
    if feed.start():
        session.live = feed
    elif bar_seconds > 0:
        say(
            f"Looking for each closed bar {SETTLE_SECONDS:g} seconds after it closes, and again "
            f"every {RETRY_SOON:g} seconds until it is there, so an order goes out on the bar it "
            "was decided on."
        )
    try:
        return _loop(session, options, feed, bar_seconds)
    finally:
        # However this ends, including a fault, the socket goes with it. A run
        # that left one open would hold a subscription this process no longer
        # reads for as long as the connection survived it.
        feed.stop()


def _loop(session, options, feed, bar_seconds: int) -> int:
    """Wake, execute, sleep, until the run is over. Answers its exit code."""
    polls = 0
    #: When this run last crossed a bar boundary without the bar behind it being
    #: there yet. None while nothing is being waited for.
    waiting_since: float | None = None
    #: How late the last few bars were, in seconds after their own close. See
    #: `expected_settle`: a feed's lateness is a fact about the feed and is
    #: learned from it rather than guessed once.
    lateness: list[float] = []

    while not session.stopping:
        # Read each wake, and before the bar rather than after it: a trader who
        # has pressed Stop is not waiting on one more bar's decisions.
        asked = _asked_of(session.options.strategy_name)
        if asked == CLOSE:
            if session.flatten():
                say("Stopped, holding nothing.")
                return EXIT_OK
            # Not flat, so this run stays: something has to be able to stop a
            # position, and a run that exited on a close it did not manage
            # leaves one with nothing watching it. `flatten` has said why.
            _forget_instruction(session.options.strategy_name)

        known = len(session._times)
        try:
            finished = session.cycle()
        except Exception as failed:  # noqa: BLE001 - one strategy, not the platform
            say(f"This run stopped on an unexpected fault: {failed}")
            return EXIT_DIAGNOSTIC
        if finished is not None:
            return finished

        polls += 1
        if options.cycles and polls >= options.cycles:
            say("Asked to run a fixed number of polls, and that is done.")
            return EXIT_OK

        now = time.time()
        on_feed = feed.live and session.live is not None
        if len(session._times) > known:
            # The bar this run was waiting for arrived and has been executed.
            # How late it was is the history endpoint's own answer to the only
            # question this loop has, so it is kept: the newest bar this run has
            # confirmed closed one interval after it opened.
            #
            # **Only a bar history delivered.** A bar closed on the tick stream
            # arrives at the boundary by construction, and counting that as a
            # reading would teach this loop that a slow history endpoint is
            # prompt. The lateness is then wrong in exactly the case it is
            # needed, which is the feed dropping and the run falling back.
            if bar_seconds > 0 and session._times and session._times[-1] not in session._from_feed:
                closed = session._times[-1] / 1000.0 + bar_seconds
                late = now - closed
                # A negative reading is a clock that disagrees with the feed's,
                # and a reading of minutes is a run catching up on history
                # rather than watching a bar close. Neither says anything about
                # how late this feed is.
                if 0.0 <= late < bar_seconds:
                    lateness.append(late)
                    del lateness[:-LATENESS_REMEMBERED]
            waiting_since = None
        elif (
            bar_seconds > 0
            and not on_feed
            and waiting_since is None
            and now % bar_seconds < max(1.0, SETTLE_SECONDS * 2)
        ):
            # A boundary has just passed and the bar behind it is not here yet.
            # Not while the feed is closing bars: that whole retry is about a
            # history endpoint publishing late, and there is nothing to retry
            # when the bar was complete in this process as it closed.
            waiting_since = now

        waited = 0.0
        # On the feed the run wakes just past the boundary, because that is when
        # the bar is complete. On history it wakes when this feed has been
        # measured to publish, which is a different and usually much later
        # moment. See `next_wake` and `expected_settle`.
        sleeping = next_wake(
            now,
            bar_seconds,
            options.poll_seconds,
            None if on_feed else waiting_since,
            FEED_SETTLE if on_feed else expected_settle(lateness),
        )
        while waited < sleeping and not session.stopping:
            time.sleep(min(0.5, sleeping - waited))
            waited += 0.5
            # A trader who has pressed Stop is waiting on this. Without it the
            # instruction is not seen until the sleep is over, which on a one
            # minute bar is up to the ordinary cadence: measured at ten seconds
            # between the press and the closing order. Read every few seconds
            # rather than on every half second, because this is a file and the
            # ordinary case is that there is nothing in it.
            if waited % ASK_EVERY < 0.5 and _asked_of(session.options.strategy_name):
                break

    say("Stopped.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
