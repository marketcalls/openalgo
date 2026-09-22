"""Closing a bar on the tick stream instead of waiting for history.

**What this is about.** A broker's history endpoint does not carry a bar the
moment it closes. On this platform a closed one minute bar was measured arriving
about thirty five seconds after its close, and a broker that publishes only on
the candle's close can be later still. A run that learned a bar had closed by
asking for history therefore acted most of a bar late, every bar, in the same
direction: it came off every fill. The chart has never had that problem, because
it draws history for the settled past and builds the bar in front of it from the
live feed. This is that arrangement for a run.

**Two things can go badly wrong here, and most of the tests below are one of
them.**

- **A bar that was never traded.** A subscription begins part way through a bar,
  so that bucket's open is whatever price arrived next and its volume has no
  baseline. Handing it to the engine would be a bar no exchange ever printed,
  and every indicator reading it would be wrong for as long as it stayed in the
  window.
- **The same bar twice.** The feed closes a bar and history carries it a minute
  later. Executing it again would advance the strategy's state twice on one bar:
  a crossover seen twice, a position entered twice.

Each test names the wrong implementation it catches.
"""

import json
import time

import pytest

import openscript_host.live_bars as live
import openscript_host.openscript_runner as runner
from test.test_openscript_runner import (
    StandInClient,
    bars,
    options_for,
    stand_in_engine,
    strategy_program,
)

SPAN = 60  # one minute bars, in seconds
SPAN_MS = SPAN * 1000
#: A real bar boundary. Worked out rather than written down: a number that
#: merely looks round is not necessarily a multiple of the span, and one that is
#: not puts every tick in these tests a fraction of a bar away from where the
#: test says it is.
BAR = (1700000000000 // SPAN_MS) * SPAN_MS


def feed(bar_seconds=SPAN, client=None, said=None):
    """A builder with no real socket behind it."""
    return live.LiveBars(
        client or Connectable(),
        "SYM1",
        "EXCH1",
        bar_seconds,
        said.append if said is not None else lambda _: None,
    )


def tick(built, at_ms, price, volume=None, symbol="SYM1", exchange="EXCH1"):
    """One publication, in the shape this platform's feed publishes."""
    data = {"ltp": price, "timestamp": at_ms}
    if volume is not None:
        data["volume"] = volume
    built._on_message(
        {"type": "market_data", "symbol": symbol, "exchange": exchange, "mode": 2, "data": data}
    )


class Connectable:
    """A feed that connects, subscribes and remembers what it was asked."""

    def __init__(self, connects=True, subscribes=True):
        self.connects = connects
        self.subscribes = subscribes
        self.subscribed = []
        self.unsubscribed = []
        self.disconnected = 0
        self.callback = None

    def connect(self):
        return self.connects

    def subscribe_quote(self, instruments, on_data_received=None):
        self.subscribed.append(instruments)
        self.callback = on_data_received
        return self.subscribes

    def unsubscribe_quote(self, instruments):
        self.unsubscribed.append(instruments)
        return True

    def disconnect(self):
        self.disconnected += 1


# ---------------------------------------------------------------------------
# A bar that was never traded
# ---------------------------------------------------------------------------


def test_the_bar_a_subscription_joined_part_way_through_is_never_handed_over():
    """THE ONE THAT MATTERS MOST.

    A subscription starts whenever the run starts, which is almost never a bar's
    open. The first bucket's open is therefore the first price that happened to
    arrive, its high and low are only the part of the bar that was watched, and
    its volume has nothing to be counted from. Handing it over puts a bar into
    the engine that no exchange printed, and every indicator reading back over
    it is wrong for the length of its window.
    """
    built = feed()
    # Joined thirty seconds into the bar at BAR.
    tick(built, BAR + 30_000, 105.0, volume=1000)
    tick(built, BAR + 50_000, 106.0, volume=1200)
    # The next bar opens and is watched from its start.
    tick(built, BAR + SPAN_MS + 1_000, 107.0, volume=1300)

    closed = built.closed(BAR + SPAN_MS + 2_000)

    assert closed == [], "the bar this joined half way through was handed over as a bar"


def test_a_bar_watched_from_its_own_boundary_is_handed_over_whole():
    built = feed()
    tick(built, BAR + 30_000, 105.0, volume=1000)  # the partial one
    tick(built, BAR + SPAN_MS + 1_000, 110.0, volume=1100)  # opens the whole one
    tick(built, BAR + SPAN_MS + 20_000, 114.0, volume=1180)
    tick(built, BAR + SPAN_MS + 40_000, 108.0, volume=1250)
    tick(built, BAR + SPAN_MS + 55_000, 112.0, volume=1300)
    tick(built, BAR + 2 * SPAN_MS + 1_000, 113.0, volume=1310)  # closes it

    closed = built.closed(BAR + 2 * SPAN_MS + 2_000)

    assert len(closed) == 1
    opened, open_, high, low, close, volume = closed[0]
    assert opened == BAR + SPAN_MS
    assert (open_, high, low, close) == (110.0, 114.0, 108.0, 112.0)


def test_the_volume_is_this_bar_and_not_the_whole_day():
    """Catches the cumulative figure passed straight through.

    The feed reports the day's volume so far, which grows all session. Handing
    that over as a bar's volume gives every bar a volume of hundreds of
    thousands, rising monotonically: a volume indicator reads it as one enormous
    bar after another and never as a quiet minute.
    """
    built = feed()
    tick(built, BAR + 30_000, 105.0, volume=1000)
    tick(built, BAR + SPAN_MS + 1_000, 110.0, volume=1100)
    tick(built, BAR + SPAN_MS + 55_000, 112.0, volume=1450)
    tick(built, BAR + 2 * SPAN_MS + 1_000, 113.0, volume=1460)

    closed = built.closed(BAR + 2 * SPAN_MS + 2_000)

    # 1450 at the end of that bar, against 1000 at the end of the one before it.
    assert closed[0][5] == 450.0


def test_a_bar_with_no_trade_after_it_still_closes():
    """Catches a bucket closed only by the next bucket's first tick.

    An instrument that does not trade for a minute would otherwise leave the bar
    before it open indefinitely, and the run would sit on a decision it had
    already made until somebody traded.
    """
    built = feed()
    tick(built, BAR + 30_000, 105.0)
    tick(built, BAR + SPAN_MS + 1_000, 110.0)
    tick(built, BAR + SPAN_MS + 30_000, 111.0)
    # Nothing at all after that, and the clock has passed the boundary.

    closed = built.closed(BAR + 2 * SPAN_MS + 500)

    assert len(closed) == 1
    assert closed[0][0] == BAR + SPAN_MS
    assert closed[0][4] == 111.0


def test_a_closed_bar_is_answered_once():
    """Catches a list that is read rather than taken.

    The run executes what it is handed. A bar answered on every wake would be
    executed at a new index each time: the same minute entered four times.
    """
    built = feed()
    tick(built, BAR + 30_000, 105.0)
    tick(built, BAR + SPAN_MS + 1_000, 110.0)
    tick(built, BAR + 2 * SPAN_MS + 1_000, 113.0)

    first = built.closed(BAR + 2 * SPAN_MS + 2_000)
    second = built.closed(BAR + 2 * SPAN_MS + 3_000)

    assert len(first) == 1
    assert second == []


# ---------------------------------------------------------------------------
# What a publication is allowed to do
# ---------------------------------------------------------------------------


def test_another_instrument_on_the_same_connection_is_not_this_run_s_bar():
    """One socket carries every subscription this process holds."""
    built = feed()
    tick(built, BAR + 30_000, 105.0)
    tick(built, BAR + SPAN_MS + 1_000, 110.0)
    tick(built, BAR + SPAN_MS + 20_000, 900.0, symbol="OTHER")
    tick(built, BAR + SPAN_MS + 30_000, 111.0)
    tick(built, BAR + 2 * SPAN_MS + 1_000, 113.0)

    closed = built.closed(BAR + 2 * SPAN_MS + 2_000)

    assert closed[0][2] == 111.0, "another instrument's price became this bar's high"


def test_a_tick_older_than_the_bar_in_hand_cannot_reopen_it():
    """Catches a bucket addressed by timestamp with no ordering rule.

    A feed republishing, or delivering out of order, would otherwise change a
    bar the engine has already acted on. A strategy that entered on a bar's
    close and then saw that close move is a strategy whose own report can never
    be reconciled with what it did.
    """
    built = feed()
    tick(built, BAR + 30_000, 105.0)
    tick(built, BAR + SPAN_MS + 1_000, 110.0)
    tick(built, BAR + 2 * SPAN_MS + 1_000, 113.0)
    closed = built.closed(BAR + 2 * SPAN_MS + 2_000)
    assert closed[0][4] == 110.0

    # Late, and belonging to the bar that has just been handed over.
    tick(built, BAR + SPAN_MS + 59_000, 999.0)

    assert built.closed(BAR + 2 * SPAN_MS + 3_000) == []
    forming = built.forming(BAR + 2 * SPAN_MS + 3_000)
    assert forming is not None and forming[0] == BAR + 2 * SPAN_MS
    assert forming[2] != 999.0, "a late tick was written into the bar after the one it belongs to"


def test_a_message_this_cannot_read_does_not_fault_the_feed_s_thread():
    """Catches an exception crossing back into somebody else's thread.

    This is called by the socket's own reader. An exception leaving it either
    ends that thread, which silently stops every bar for the rest of the
    session, or is swallowed somewhere no trader will ever read it.
    """
    built = feed()
    for bad in (None, "text", 42, {}, {"data": None}, {"data": {"ltp": "x", "timestamp": "y"}}):
        built._on_message(bad)

    assert built.closed(BAR + SPAN_MS) == []


def test_a_timestamp_in_seconds_and_one_in_milliseconds_reach_the_same_bar():
    """Catches milliseconds assumed.

    Read wrongly, a bar's open instant is either in 1970 or fifty thousand years
    out, and the anchor this run keeps its indices on never matches anything
    again.
    """
    built = feed()
    tick(built, BAR + 30_000, 105.0)
    tick(built, BAR + SPAN_MS + 1_000, 110.0)
    # The same instant, counted in whole seconds.
    tick(built, (BAR + SPAN_MS + 30_000) // 1000, 112.0)
    tick(built, BAR + 2 * SPAN_MS + 1_000, 113.0)

    closed = built.closed(BAR + 2 * SPAN_MS + 2_000)

    assert len(closed) == 1
    assert closed[0][2] == 112.0, "a timestamp in seconds did not land on the bar it belongs to"


# ---------------------------------------------------------------------------
# The bar that is still moving
# ---------------------------------------------------------------------------


def test_the_moving_bar_is_never_a_bucket_that_has_already_ended():
    """Catches the same bar handed over twice in one wake.

    Once as the bar that just closed, and once as the bar still forming. The
    engine would execute it at one index as confirmed and at the next as moving,
    so the run would be permanently one bar ahead of itself.
    """
    built = feed()
    tick(built, BAR + 30_000, 105.0)
    tick(built, BAR + SPAN_MS + 1_000, 110.0)

    past_the_boundary = BAR + 2 * SPAN_MS + 500

    assert built.forming(past_the_boundary) is None
    assert built.closed(past_the_boundary)[0][0] == BAR + SPAN_MS


def test_the_moving_bar_is_never_the_one_joined_part_way_through():
    built = feed()
    tick(built, BAR + 30_000, 105.0)

    assert built.forming(BAR + 40_000) is None


# ---------------------------------------------------------------------------
# A feed that is not there
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "client",
    [Connectable(connects=False), Connectable(subscribes=False)],
    ids=["will not connect", "will not subscribe"],
)
def test_a_feed_that_will_not_start_leaves_the_run_on_history(client):
    """A feed is an improvement, not a requirement.

    A run that refused to start because the tick stream was down is a run that
    does not trade, which is worse than one that acts a few seconds later.
    """
    said = []
    built = feed(client=client, said=said)

    assert built.start() is False
    assert any("history" in one for one in said), said


def test_a_feed_that_raises_on_connect_leaves_the_run_on_history():
    class Raises:
        def connect(self):
            raise OSError("no route to host")

    said = []
    built = feed(client=Raises(), said=said)

    assert built.start() is False
    assert any("history" in one for one in said), said


def test_a_daily_bar_is_not_watched_this_way():
    """Nothing here knows where a session's boundary is, so it does not guess."""
    client = Connectable()
    built = feed(bar_seconds=0, client=client)

    assert built.start() is False
    assert client.subscribed == []


def test_stopping_gives_the_socket_back_even_when_it_is_already_broken():
    class Breaks(Connectable):
        def unsubscribe_quote(self, instruments):
            raise OSError("already gone")

    client = Breaks()
    built = feed(client=client)
    built.start()

    built.stop()

    assert client.disconnected == 1, "a broken unsubscribe left the connection open"


def test_a_subscription_that_has_published_nothing_is_not_a_feed_to_close_a_bar_on():
    """Catches a run that stops polling history the moment it subscribes.

    A subscription is accepted before any data flows, and an instrument the feed
    silently carries nothing for would leave the run waiting for a bar that
    never comes while history had it all along.
    """
    built = feed()
    built.start()

    assert built.live is False

    tick(built, BAR + 30_000, 105.0)

    assert built.live is True


# ---------------------------------------------------------------------------
# What the run does with them
# ---------------------------------------------------------------------------


def session_on(client, engine, options=None):
    """A session that has replayed its history and is ready to send."""
    made = runner.Session(
        engine, options or options_for(), json.dumps(strategy_program()), client
    )
    made.cycle()
    return made


def test_a_bar_history_carries_later_is_not_executed_a_second_time(monkeypatch):
    """THE OTHER ONE THAT MATTERS.

    The feed closes a bar and history carries the same bar a minute later.
    Executing it again advances the strategy over one minute twice: a crossover
    seen twice, and a position entered on top of itself.
    """
    rows = bars(6)
    client = StandInClient(rows, first=3, repeat=99)
    engine = stand_in_engine(strategy_program(), effects_from=None)
    made = session_on(client, engine)
    executed = len(made._times)

    # The bar after the newest one history has shown, closed on the feed.
    opened = rows[2][0] + 60_000
    made.live = Handing([(opened, 100.0, 101.0, 99.0, 100.5, 5.0)])
    made._sending = True
    made.cycle()

    assert len(made._times) == executed + 1
    assert made._times[-1] == opened
    settled = len(engine.run.executions)

    # Now history catches up and carries that same bar as its newest.
    client.rows = rows[:3] + [(opened, 100.0, 101.0, 99.0, 100.5, 5.0)] + rows[3:]
    client._shown = 4
    made.live = Handing([])
    made.cycle()

    assert made._times.count(opened) == 1, "the bar the feed closed was confirmed again by history"
    # And not handed over at all, in any state. Counting confirmations alone
    # misses the shape this actually goes wrong in: the bar comes back as the
    # newest one history holds, so it is re-executed as the bar that is still
    # moving, at an index the run has already settled, and the strategy sees one
    # minute of the market twice.
    assert len(engine.run.executions) == settled, (
        "history handed the engine a bar the feed had already closed"
    )


def test_history_that_is_behind_the_last_bar_executed_is_not_a_gap(monkeypatch):
    """THE ONE THAT WOULD STOP EVERY RUN.

    Closing a bar on the feed puts the run ahead of history by design, so the
    window routinely holds nothing at or after the anchor. Read as a
    discontinuity that is a stopped run every minute, for doing exactly what it
    was built to do.
    """
    rows = bars(6)
    client = StandInClient(rows, first=3, repeat=99)
    made = session_on(client, stand_in_engine(strategy_program(), effects_from=None))

    # Ahead of everything the window holds.
    made._times.append(rows[-1][0] + 10 * 60_000)

    assert made._new_bars([runner.Candle(*row) for row in rows[:3]]) == []


def test_a_window_that_has_rolled_past_the_anchor_is_still_a_gap():
    """And the check above did not cost the check it was added beside.

    A window whose oldest bar is newer than the anchor is a run that has missed
    bars it cannot name, which is the case that must still stop.
    """
    rows = bars(6)
    client = StandInClient(rows, first=3, repeat=99)
    made = session_on(client, stand_in_engine(strategy_program(), effects_from=None))

    made._times = [rows[0][0] - 60_000]

    assert made._new_bars([runner.Candle(*row) for row in rows[2:]]) is None


def test_nothing_from_the_feed_is_executed_while_history_is_still_being_replayed():
    """Catches a bar arriving in the middle of the replay.

    A run is replayed over whatever history holds and only then begins sending.
    A bar closed on the feed part way through that would be executed out of
    order, against a state built from a different series.
    """
    client = StandInClient(bars(6), first=3, repeat=99)
    made = runner.Session(
        stand_in_engine(strategy_program(), effects_from=None),
        options_for(),
        json.dumps(strategy_program()),
        client,
    )
    made.live = Handing([(BAR, 100.0, 101.0, 99.0, 100.5, 5.0)])

    assert made._feed_ready() is False


def test_a_run_with_no_feed_is_the_run_this_platform_had_before():
    """The fallback is the whole of the old path rather than a reduced one."""
    client = StandInClient(bars(9), first=3, repeat=1)
    made = session_on(client, stand_in_engine(strategy_program(), effects_from=None))
    before = len(made._times)
    for _ in range(3):
        made.cycle()

    assert made.live is None
    assert len(made._times) > before, "a run with no feed stopped advancing on history"


class Handing:
    """A feed that hands over exactly these bars, once."""

    def __init__(self, closed, forming=None):
        self._closed = list(closed)
        self._forming = forming
        self.live = True

    def closed(self, now_ms):  # noqa: ARG002 - the clock is the caller's
        taken, self._closed = self._closed, []
        return taken

    def forming(self, now_ms):  # noqa: ARG002 - the clock is the caller's
        return self._forming


def test_the_feed_stand_in_answers_what_the_real_one_answers():
    """Catches these tests drifting from the module they stand in for.

    Every test above that uses `Handing` proves nothing if the run reads a
    method the real builder does not have.
    """
    import inspect

    real = live.LiveBars
    for name in ("closed", "forming"):
        mine = inspect.signature(getattr(Handing, name))
        theirs = inspect.signature(getattr(real, name))
        assert list(mine.parameters) == list(theirs.parameters), name
    assert isinstance(real.live, property)
