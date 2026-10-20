"""The child program that runs one compiled script, held to what it promises.

This file is about ``openscript_host/openscript_runner.py``, the program that
runs inside the strategy process. The half that lives in the web worker, and the
routes above it, are tested elsewhere; nothing here starts a process, reaches a
broker or sends an order anywhere.

**Every test below names the wrong implementation it catches.** A test that only
says what the code does today goes green against a rewrite that broke the
property it was written for, which is how three of the four defects this file
pins survived a review: each of them looked right, and each of them was silent.

**What is deliberately NOT tested here.** The engine is not installed on this
server, so the driver is exercised against stand-ins shaped like the small
surface it actually uses. That means these tests answer for the driver's own
arithmetic and its order of operations, and they do not answer for the engine.
Two of them therefore write out a line of the engine's own code and say so, and
if the engine changes that line, this file is what has to change with it.
"""

import fnmatch
import importlib.util
import json
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

REPOSITORY = Path(__file__).resolve().parents[1]

#: Where the program that runs a script belongs: in the image, outside every
#: mounted folder, and tracked.
RUNNER_PATH = REPOSITORY / "openscript_host" / "openscript_runner.py"

#: Where it used to be, which is a mounted volume on a container install and a
#: folder that hides every ``.py`` in it from the repository.
RUNNER_WAS = REPOSITORY / "strategies" / "scripts" / "openscript_runner.py"

COMPOSE_PATH = REPOSITORY / "docker-compose.yaml"
DOCKERFILE_PATH = REPOSITORY / "Dockerfile"
DOCKERIGNORE_PATH = REPOSITORY / ".dockerignore"

#: The one zone the engine holds offsets for, ``engine/openscript/zones.py``
#: ``READABLE``. Written out because the engine is not importable here.
READABLE_ZONE = "UTC"

#: A well formed zone name that is not that one. A placeholder: what matters is
#: that it is an area and a location and is not the readable zone.
REGIONAL_ZONE = "Region/City"


def _load_runner():
    """The child program, loaded from its path.

    It is a program and not a module in a package: the worker spawns it and never
    imports it. So it is loaded here the way anything else would load a file, and
    from the one path it is supposed to be at, because a loader that fell back to
    the old path would let the packaging test below pass against a file that had
    never moved.
    """
    spec = importlib.util.spec_from_file_location("openscript_child_under_test", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def engine_is_last(index: int, supplied: int) -> bool:
    """``bar.isLast``, exactly as the engine computes it.

    ``facts_for`` in the engine's ``bars.py`` reads
    ``is_last=index == supplied - 1``, and that one line is the whole of the
    contract this driver has to satisfy with the ``supplied`` it hands over. It is
    copied here rather than imported because the engine is not installed on this
    server and these tests have to be answerable without it.
    """
    return index == supplied - 1


# ---------------------------------------------------------------------------
# Stand-ins: the small surface the driver actually uses
# ---------------------------------------------------------------------------


class StandInResult:
    def __init__(self, index, applied=()):
        self.index = index
        self.columns = []
        self.applied_channels = []
        self.applied = list(applied)
        self.alerts = []
        self.diagnostic = None


class StandInEffect:
    def __init__(self, name="order.reverse"):
        self.name = name
        self.arguments = []
        self.position = None


class StandInRun:
    """Records every execution the driver asks for, with the facts it stated."""

    def __init__(self, raw, effects_at=None):
        self.program = types.SimpleNamespace(raw=raw)
        self.executions = []
        self.restores = []
        self._effects_at = dict(effects_at or {})

    def checkpoint(self, bar=-1):
        return ("mark", bar)

    def restore(self, mark):
        self.restores.append(mark)

    def declaration(self, path):
        return self.program.raw["meta"]["strategy"][path[-1]]

    def execute_bar(self, index, bar, state, supplied=None, instrument=None, now=None):
        self.executions.append(
            {
                "index": index,
                "supplied": supplied,
                "confirmed": state.is_confirmed,
                "new": state.is_new,
                "realtime": state.is_realtime,
                "updates": state.updates,
                "time": bar.time,
            }
        )
        return StandInResult(index, applied=self._effects_at.get(index, ()))


class StandInIntent:
    def __init__(self, intent_id, kind="place", side="buy", qty=1.0, tag="", qty_type="units"):
        self.intent_id = intent_id
        self.kind = kind
        self.side = side
        self.qty = qty
        # The unit the quantity is counted in, which an engine intent always
        # states (``host-interface.md`` 7.1).
        self.qty_type = qty_type
        self.placement = types.SimpleNamespace(
            kind=kind, order_type="market", limit=None, trigger=None, tag=tag
        )


class StandInPlaced:
    def __init__(self, intents):
        self.intents = intents
        self.refusal = None


class StandInLedger:
    """A ledger whose one call can mint more than one intent.

    ``per_call`` is the whole point of it: one order call becomes two orders
    wherever a position is turned around, and a driver that routes them one at a
    time has a state in between where half of the move has happened.
    """

    def __init__(self, per_call=1):
        self.options = None
        self.delivered = []
        self.settled = 0
        self._rows = []
        self._next = 1
        self._per_call = per_call

    def place(self, name, arguments, bar, position):
        minted = []
        for _ in range(self._per_call):
            intent = StandInIntent(self._next)
            self._next += 1
            self._rows.append(intent)
            minted.append(intent)
        return StandInPlaced(tuple(minted))

    def rows(self):
        return list(self._rows)

    def discard(self, at):
        del self._rows[at:]

    def deliver(self, frame):
        self.delivered.append(frame)

    def settle(self):
        self.settled += 1
        return ()

    def size(self):
        return 0.0

    def avg_price(self):
        return None


class StandInServing:
    def __init__(self, book=None):
        self.book = book
        self.bars = []

    def at_bar(self, facts, first):
        self.bars.append(dict(facts))


def stand_in_engine(raw, ledger=None, effects_at=None):
    """An object shaped like the driver's own view of an engine."""
    run = StandInRun(raw, effects_at=effects_at)
    loaded = types.SimpleNamespace(run=run, diagnostic=None)
    engine = types.SimpleNamespace(
        load_text=lambda *args, **kwargs: loaded,
        Serving=StandInServing,
        Bar=lambda **kwargs: types.SimpleNamespace(**kwargs),
        BarState=lambda **kwargs: types.SimpleNamespace(**kwargs),
        Ledger=lambda: ledger if ledger is not None else StandInLedger(),
        LedgerOptions=lambda **kwargs: dict(kwargs),
        Identity=lambda symbol, exchange: (symbol, exchange),
        IntentBar=lambda index, time: types.SimpleNamespace(index=index, time=time),
        OrderFrame=lambda **kwargs: types.SimpleNamespace(**kwargs),
        capabilities=lambda *tags: ("core.1",) + tags,
        utc_time=None,
        session_facts=("session.isFirstBar",),
        session_first="isSessionFirst",
        readable_zone=READABLE_ZONE,
        # The one zone a stand-in reads a clock in. The real engine reads every
        # zone this server's database holds once the host's reader is in place,
        # and the tests of that run against the real one.
        knows_zone=lambda zone: zone == READABLE_ZONE,
        reads_calendar_in=lambda zone: zone == READABLE_ZONE,
        time_reader=lambda zone: None,
        join_calendar=lambda serving: True,
        session_hours=lambda zone, window: window,
        opening_day=lambda hours, time_ms, zone: None,
        day_of=lambda text: None,
        # The set the engine keeps of every library call that reads a calendar.
        # A driver that carried its own copy of this list would go stale the day
        # the language gained a call, so it asks the engine, and so does this.
        calendar_reads=frozenset(
            {
                "date.year",
                "date.month",
                "date.day",
                "date.dayOfWeek",
                "date.dayOfYear",
                "date.hour",
                "date.minute",
                "date.second",
                "date.weekOfYear",
                "date.startOfDay",
                "date.startOfWeek",
                "date.startOfMonth",
                "date.from",
                "date.isSameDay",
                "date.format",
                "session.isIn",
            }
        ),
    )
    engine.run = run
    return engine


def program_for(kind="strategy", functions=(), inputs=()):
    """The smallest program shape the driver reads fields out of."""
    return {
        "meta": {
            "kind": kind,
            "onUnconfirmed": False,
            "strategy": {
                "qty": 1.0,
                "qtyType": "units",
                "product": "intraday",
                "pyramiding": 1,
            },
        },
        "inputs": [dict(one) for one in inputs],
        "lib": {"functions": [{"name": name} for name in functions]},
    }


class Candles:
    """What the platform's history call answers with, as the driver reads it."""

    def __init__(self, rows):
        self._rows = rows
        self.index = [datetime.fromtimestamp(one[0] / 1000, UTC) for one in rows]

    def __len__(self):
        return len(self._rows)

    def __contains__(self, name):
        return name in ("open", "high", "low", "close", "volume")

    def __getitem__(self, name):
        at = {"open": 1, "high": 2, "low": 3, "close": 4, "volume": 5}[name]
        return [one[at] for one in self._rows]


class StandInClient:
    """The platform SDK, recording what it was asked and answering plainly.

    ``width`` is the size of the history window, and it is what makes this useful:
    a real window covers a span of days rather than a count of bars, so once the
    run has been going long enough the oldest bar falls out of it on every poll
    and the window stops growing. ``sends`` is the answer each order call gets, in
    order, so a bar's second order can be refused after its first was accepted.
    """

    def __init__(self, rows, first=4, width=None, repeat=1, sends=None):
        self.rows = rows
        self.width = width
        self.sent = []
        self.cancelled = []
        self.symbols = 0
        self.statuses = 0
        self._shown = first
        self._repeat = repeat
        self._left = repeat
        self._sends = list(sends) if sends is not None else None

    def symbol(self, **kwargs):
        self.symbols += 1
        return {"status": "success", "data": {"tick_size": 0.05, "lotsize": 1}}

    def history(self, **kwargs):
        end = self._shown
        start = 0 if self.width is None else max(0, end - self.width)
        answered = Candles(self.rows[start:end])
        self._left -= 1
        if self._left <= 0:
            self._left = self._repeat
            self._shown = min(self._shown + 1, len(self.rows))
        return answered

    def placeorder(self, **kwargs):
        self.sent.append(kwargs)
        if self._sends is not None and not self._sends.pop(0):
            return {"status": "error", "message": "the exchange would not take that order"}
        return {"status": "success", "orderid": f"O{len(self.sent)}"}

    def cancelorder(self, **kwargs):
        self.cancelled.append(kwargs)
        return {"status": "success"}

    def orderstatus(self, **kwargs):
        self.statuses += 1
        return {
            "status": "success",
            "data": {"order_status": "open", "quantity": 1, "average_price": None},
        }


def bars(count=16, start=1700000000000, step=60000):
    """A price that turns every three bars, which is enough to make a signal."""
    rows = []
    price = 100.0
    for at in range(count):
        price += 2.0 if (at // 3) % 2 == 0 else -2.0
        rows.append((start + at * step, price, price + 1, price - 1, price, 10.0))
    return rows


def options_for(**overrides):
    given = {
        "script": "turn.oscript",
        "symbol": "SYM1",
        "exchange": "EXCH1",
        "interval": "1m",
        "timezone": READABLE_ZONE,
    }
    given.update(overrides)
    argv = []
    for name, value in given.items():
        argv += [f"--{name.replace('_', '-')}", str(value)]
    return runner.parse_arguments(argv)


def session_for(client, engine, options=None, text=None):
    raw = engine.run.program.raw
    return runner.Session(engine, options or options_for(), text or json.dumps(raw), client)


# ---------------------------------------------------------------------------
# 1. A missing compiled program refuses, and says which script
# ---------------------------------------------------------------------------


@pytest.fixture
def scripts(tmp_path, monkeypatch):
    """A scripts folder this test owns, in place of the platform's."""
    folder = tmp_path / "strategies" / "openscript"
    folder.mkdir(parents=True)
    monkeypatch.setattr(runner, "SCRIPTS_DIR", folder)
    return folder


def test_a_script_with_nothing_compiled_beside_it_refuses_and_names_itself(scripts, capsys):
    """There is no compiler here, so a script with no program cannot be run.

    The wrong implementation this catches is the one that treats a missing
    program as an empty program and starts anyway: the run would come up, report
    itself as going, and place nothing for the rest of the session with nothing in
    the log naming the script the trader has to go and save again. It also catches
    a runner that reads the source file as though it were the program.

    The refusal has to name the script, because a trader running six of them
    needs to know which one to open.
    """
    (scripts / "turn.oscript").write_text("study()\n", encoding="utf-8")

    code = runner.main(
        ["--script", "turn.oscript", "--symbol", "SYM1", "--exchange", "EXCH1", "--interval", "1m"]
    )
    said = capsys.readouterr().out

    assert code == runner.EXIT_REFUSED
    assert "turn.oscript" in said
    assert "no compiled program" in said
    assert "Nothing was started and nothing was sent." in said


def test_a_script_that_is_not_on_this_server_refuses_by_a_different_sentence(scripts, capsys):
    """Two states, two sentences, because the trader's next move differs.

    A script with nothing compiled is opened and saved again. A script that is not
    here at all is a name to check. The wrong implementation this catches is the
    one that answers both with one message, which sends somebody looking for a
    save button on a file that does not exist.
    """
    code = runner.main(
        [
            "--script",
            "absent.oscript",
            "--symbol",
            "SYM1",
            "--exchange",
            "EXCH1",
            "--interval",
            "1m",
        ]
    )
    said = capsys.readouterr().out

    assert code == runner.EXIT_REFUSED
    assert "There is no script called absent.oscript" in said


def test_the_stored_program_is_handed_over_exactly_as_it_was_written(scripts):
    """The bytes are the program's own, never parsed here and rebuilt.

    A program's hash is taken over its canonical encoding, and an engine that
    loads one from text refuses text spelled any other way. The wrong
    implementation this catches is the obvious convenience: read it, ``json.load``
    it, hand the object or a re-serialised copy over. Both change the spelling,
    and the engine would then refuse a program that is perfectly good.
    """
    written = '{"meta":{"kind":"study"},\n  "inputs": [],   "lib": {"functions": []}}\n'
    (scripts / "turn.oscript").write_text("study()\n", encoding="utf-8")
    (scripts / ("turn.oscript" + runner.PROGRAM_SUFFIX)).write_text(written, encoding="utf-8")

    assert runner.program_text("turn.oscript") == written


# ---------------------------------------------------------------------------
# 2. bar.isLast, once the history window has turned over
# ---------------------------------------------------------------------------


def test_the_newest_bar_is_the_last_bar_after_the_history_window_has_rolled():
    """The defect: ``bar.isLast`` goes false forever and nothing says so.

    The engine reads ``bar.isLast`` as ``index == supplied - 1``. This driver's
    indices are anchored to bar open times and grow for the life of the run; the
    history window does not, because it covers a span of days and drops its oldest
    bar as the run goes on. So a ``supplied`` taken from the length of the window
    is smaller than the newest index as soon as the window has turned over once,
    and the newest bar is never the last bar again.

    The wrong implementation this catches is exactly that one, ``supplied`` passed
    as the number of bars the last history call returned. It is silent: a strategy
    that acts on the final bar simply stops firing, the run stays up, the log says
    nothing, and the trader sees a strategy that never trades.

    The assertion is made over the whole run rather than at one poll, because the
    property is not "it is right at the start", it is "it stays right".
    """
    rows = bars(16)
    # A window four bars wide, so it has rolled by the third poll and every poll
    # after it is in the state the defect lives in.
    client = StandInClient(rows, first=4, width=4)
    engine = stand_in_engine(program_for())
    session = session_for(client, engine)

    for _ in range(9):
        session.cycle()

    executions = engine.run.executions
    assert executions, "the driver executed no bars at all"

    # Every execution of the newest bar of its poll says it is the last bar, and
    # every bar behind it in a catch-up batch says it is not.
    newest = {}
    for one in executions:
        newest[one["time"]] = max(newest.get(one["time"], -1), one["index"])
    greatest = max(newest.values())

    for one in executions:
        is_last = engine_is_last(one["index"], one["supplied"])
        if one["index"] == greatest and not one["confirmed"]:
            assert is_last, f"the newest bar at index {one['index']} was not the last bar"

    # The point of the test: the LAST execution the run made is the moving bar,
    # it sits at an index well past the width of the window, and it is last.
    final = executions[-1]
    assert not final["confirmed"], "the last execution of a poll is the moving bar"
    assert final["index"] >= client.width, (
        "the window has to have rolled for this test to be about anything"
    )
    assert engine_is_last(final["index"], final["supplied"])


def test_a_bar_that_is_not_the_newest_one_is_not_the_last_bar():
    """The other half, which a fix that always says true would break.

    ``supplied = index + 1`` per bar would make ``bar.isLast`` true on every bar
    ever executed, including all of the history replay, and a strategy written to
    act once at the end of the data would fire on every bar of it instead. That is
    the wrong implementation this catches, and it is worse than the defect: the
    first one never traded, this one trades on every bar of a replay.
    """
    rows = bars(16)
    client = StandInClient(rows, first=8, width=None)
    engine = stand_in_engine(program_for())
    session = session_for(client, engine)

    session.cycle()

    executions = engine.run.executions
    assert len(executions) == 8, "the first poll replays the whole window"
    for one in executions[:-1]:
        assert one["confirmed"]
        assert not engine_is_last(one["index"], one["supplied"]), (
            f"bar {one['index']} of the replay claimed to be the last bar"
        )
    assert engine_is_last(executions[-1]["index"], executions[-1]["supplied"])


# ---------------------------------------------------------------------------
# 3. A script that reads the clock
# ---------------------------------------------------------------------------


def test_a_script_that_reads_the_clock_is_refused_before_the_run_starts():
    """Silent absence on every bar is the one outcome that is not acceptable.

    The engine holds offsets for one zone and answers absence for every other,
    without raising. So a script asking what hour a bar opened at, on an
    instrument whose calendar is anything else, is handed absence on every bar of
    every poll: the condition built on it is never true, the strategy never
    trades, and nothing anywhere says why.

    The wrong implementation this catches is the one that was here: put the
    instrument's zone in the record, hand it to the engine, and start. The run
    comes up, the log is clean, and the strategy is dead.

    Two things are asserted beyond the refusal itself. It names the call, because
    "it reads the clock" is not something a trader can act on and ``date.hour`` is.
    And it happens before the driver has asked the platform anything at all, which
    is what "before it starts" means.
    """
    engine = stand_in_engine(program_for(functions=("ta.ema", "date.hour")))
    client = StandInClient(bars())

    with pytest.raises(runner.Refusal) as refused:
        session_for(client, engine, options_for(timezone=REGIONAL_ZONE))

    said = str(refused.value)
    assert "date.hour" in said
    assert REGIONAL_ZONE in said
    assert "turn.oscript" in said
    assert client.symbols == 0, "the run reached the platform before it refused"


def test_every_calendar_call_the_engine_knows_about_is_refused_not_just_one():
    """The check asks the engine what reads a calendar; it keeps no list of its own.

    The wrong implementation this catches is a hand-written list of two or three
    call names in the driver. It would pass a test written about ``date.hour`` and
    let ``session.isIn`` or ``date.format`` through, and those are answered absence
    in exactly the same silence.
    """
    engine = stand_in_engine(program_for())
    for name in sorted(engine.calendar_reads):
        reading = stand_in_engine(program_for(functions=(name,)))
        with pytest.raises(runner.Refusal) as refused:
            session_for(StandInClient(bars()), reading, options_for(timezone=REGIONAL_ZONE))
        assert name in str(refused.value)


def test_a_script_that_never_reads_the_clock_runs_in_any_calendar():
    """The refusal is about the reads, not about the zone, so it cannot be a blanket.

    The wrong implementation this catches is the over-correction: refuse every run
    whose instrument is not in the one zone the engine reads, which is almost
    every instrument, and the runner becomes unusable for the case it was built
    for.
    """
    engine = stand_in_engine(program_for(functions=("ta.ema", "ta.rsi")))
    client = StandInClient(bars())

    session = session_for(client, engine, options_for(timezone=REGIONAL_ZONE))

    assert session.instrument["timezone"] == REGIONAL_ZONE


def test_the_same_clock_reading_script_starts_where_the_calendar_is_readable():
    """And where the engine can read the calendar, the reads are not refused.

    The wrong implementation this catches is a driver that refuses a calendar read
    outright, whatever the zone, which would take away a case that works.
    """
    engine = stand_in_engine(program_for(functions=("date.hour",)))
    client = StandInClient(bars())

    session = session_for(client, engine, options_for(timezone=READABLE_ZONE))

    assert session.instrument["timezone"] == READABLE_ZONE


def test_the_runner_does_not_relabel_a_regional_calendar_as_the_one_it_can_read():
    """The other way of making the refusal go away, which is worse than the defect.

    Defaulting the run's zone to the one zone the engine reads would make every
    calendar call answer. It would answer under a clock that is hours from the one
    on the trader's chart, so a script asking whether the session has been open an
    hour would be right on some instruments and quietly wrong on the rest. Absence
    is at least detectable; a plausible wrong hour is not.

    The wrong implementation this catches is that default.
    """
    assert options_for().timezone == READABLE_ZONE, "the test's own default, for contrast"
    parsed = runner.parse_arguments(
        ["--script", "turn.oscript", "--symbol", "SYM1", "--exchange", "EXCH1", "--interval", "1m"]
    )
    assert parsed.timezone != READABLE_ZONE, (
        "a run that states no zone must not claim the instrument's calendar is the "
        "one zone the engine happens to be able to read"
    )


# ---------------------------------------------------------------------------
# 4. bar.updates counts hand-overs
# ---------------------------------------------------------------------------


def test_a_moving_bar_counts_its_hand_overs_and_carries_the_count_into_its_close():
    """``updates`` and executions are one count, once per hand-over.

    The wrong implementation this catches is the constant: ``updates`` stated as
    one on every execution, including the tenth execution of the same moving bar.
    A script reading ``bar.updates`` then cannot tell a first intrabar execution
    from a tenth, which is the only fact it has for telling a settled price from
    the first tick of a bar.

    A bar this run never saw moving is handed over once and states one, which is
    the history load row of the same table, and the execution that confirms a bar
    that HAS been moving is the next hand-over of that bar rather than a fresh
    one, so the count carries on through it rather than going back to one.
    """
    rows = bars(8)
    # Three polls on each bar before the next one appears, so the newest bar is
    # handed over three times while it forms and a fourth time when it closes.
    client = StandInClient(rows, first=4, repeat=3)
    engine = stand_in_engine(program_for())
    session = session_for(client, engine)

    for _ in range(6):
        session.cycle()

    executions = engine.run.executions
    replayed = [one for one in executions if one["confirmed"] and one["index"] < 3]
    assert replayed, "the first poll replays the bars behind the newest one"
    for one in replayed:
        assert one["updates"] == 1.0, "a bar handed over once states one update"

    moving = [one for one in executions if one["index"] == 3]
    assert [one["updates"] for one in moving] == [1.0, 2.0, 3.0, 4.0], (
        "the moving bar was handed over four times and has to count them"
    )
    assert [one["confirmed"] for one in moving] == [False, False, False, True], (
        "the fourth hand-over of that bar is the one that confirms it"
    )

    after = [one for one in executions if one["index"] == 4]
    assert after and after[0]["updates"] == 1.0, "the next bar starts its own count"


# ---------------------------------------------------------------------------
# 5. A bar whose orders only half went out
# ---------------------------------------------------------------------------


def _sending_session(sends, per_call=2):
    """A session past its history pass, on the bar its first orders go out on."""
    rows = bars(8)
    client = StandInClient(rows, first=4, sends=sends)
    ledger = StandInLedger(per_call=per_call)
    # Bar 3 is the first bar executed as confirmed after the history pass has
    # handed over, so it is the first bar whose orders are actually sent.
    engine = stand_in_engine(program_for(), ledger=ledger, effects_at={3: (StandInEffect(),)})
    session = session_for(client, engine)
    session.cycle()  # the history replay, which sends nothing
    session.cycle()  # bar 3 closes, and its orders go out
    return session, client, ledger


def test_a_bar_whose_second_order_is_refused_stops_the_run_and_says_it_is_half_moved(capsys):
    """This is money, so it is said out loud and nothing further is sent.

    One order call can be two orders: turning a position around is a close and an
    open, and they are only correct together. There is no atomic way to send them
    here, and an order that has reached the order path cannot be taken back.

    The wrong implementation this catches is the loop that routes each order in
    turn and carries on regardless, under a docstring promising both or neither.
    The position is then left half moved, the run keeps going and keeps deciding
    from a ledger that does not describe what is held, and nothing in the log says
    a person is needed.

    What is asserted: the first order went out, the second did not reach the
    platform as a second send, the run stopped, and the log says plainly that the
    position is half moved.
    """
    session, client, ledger = _sending_session(sends=[True, False])
    said = capsys.readouterr().out

    assert len(client.sent) == 2, "the second order was attempted and was refused"
    assert session.stopping, "a half moved position must stop the run"
    assert "HALF MOVED" in said
    assert "cannot be taken back" in said
    rejected = [one for one in ledger.delivered if one.status == "rejected"]
    assert rejected, "the ledger has to be told about the order that did not go"


def test_a_stopped_run_does_not_execute_the_bars_behind_the_one_that_stopped_it(capsys):
    """A run that stopped half moved must not send the next bar's orders on top.

    The wrong implementation this catches is a driver that sets its stop flag and
    then carries on through the rest of the catch-up batch, which is the case a
    run that is behind is always in: the flag is only read at the top of the next
    poll, so one more bar's worth of orders goes out after the run has already
    declared itself half moved.
    """
    rows = bars(10)
    client = StandInClient(rows, first=4, sends=[True, False])
    ledger = StandInLedger(per_call=2)
    engine = stand_in_engine(
        program_for(),
        ledger=ledger,
        effects_at={3: (StandInEffect(),), 4: (StandInEffect(),), 5: (StandInEffect(),)},
    )
    session = session_for(client, engine)

    session.cycle()  # the history replay
    # Two bars close between polls, so bar 3 and bar 4 are both in the next batch.
    client._shown = 6
    session.cycle()

    assert session.stopping
    assert len(client.sent) == 2, (
        "the run went on and sent the next bar's orders after it had stopped"
    )


def test_a_bar_whose_first_order_is_refused_sends_nothing_and_keeps_running(capsys):
    """Neither is still kept wherever it can be kept, and that is not a stop.

    Nothing left, so nothing moved: the rest of the bar is held back, the ledger
    is told about every order that was held, and the run carries on to decide
    again on the next bar.

    The wrong implementation this catches is the over-correction: stop the run on
    any refused order at all. A single order refused by the exchange is an ordinary
    event and stopping a strategy over one, while the position is exactly where the
    ledger says it is, takes a working strategy off the market for no reason.

    It also catches the other half, a driver that holds the first order back and
    then sends the second: that would open without closing, which doubles a
    position instead of turning it.
    """
    session, client, ledger = _sending_session(sends=[False])
    said = capsys.readouterr().out

    assert len(client.sent) == 1, "the order after the refused one must not be sent"
    assert not session.stopping, "nothing moved, so there is nothing for a person to square"
    assert "HALF MOVED" not in said
    assert "has not moved" in said
    rejected = [one for one in ledger.delivered if one.status == "rejected"]
    assert len(rejected) == 2, "both orders of that bar are recorded as not sent"


def test_a_bar_whose_orders_all_go_out_sends_every_one_of_them_and_runs_on(capsys):
    """The ordinary case, so none of the above is passing by refusing everything.

    The wrong implementation this catches is a driver made so careful by the tests
    above that it stops sending, or stops the run, on a bar that went out
    perfectly.
    """
    session, client, ledger = _sending_session(sends=[True, True])
    said = capsys.readouterr().out

    assert len(client.sent) == 2
    assert not session.stopping
    assert "HALF MOVED" not in said
    assert [one for one in ledger.delivered if one.status == "rejected"] == [], (
        "nothing was refused, so nothing should be recorded as not sent"
    )


# ---------------------------------------------------------------------------
# 6. Where the file lives, and whether it reaches an installation at all
# ---------------------------------------------------------------------------


def _ignore_patterns(path: Path) -> list[str]:
    """The patterns in one ignore file, without its comments, blanks or negations."""
    if not path.is_file():
        return []
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#") or entry.startswith("!"):
            continue
        found.append(entry)
    return found


def _covered_by(pattern: str, relative: Path) -> bool:
    """Whether one ignore pattern covers this path, on a deliberately small reading.

    A bare name, a name with a trailing slash meaning a folder, and a glob, each
    matched against the file's own name and against every folder above it. It does
    not implement the whole of the format, so it can say "nothing covers this"
    about a path a fuller reader would still ignore. It is enough for the wrong
    implementation these tests are about, which is a platform file put back inside
    a folder whose own rule hides every script in it, and the test below shows the
    reading works by pointing it at the folder that does exactly that.
    """
    entry = pattern.rstrip("/")
    parts = relative.as_posix().split("/")
    if "/" in entry.strip("/"):
        return fnmatch.fnmatch(relative.as_posix(), entry.lstrip("/"))
    return any(fnmatch.fnmatch(part, entry) for part in parts)


def _ignored_under(folder: Path, relative: Path) -> list[str]:
    """Every pattern in ``folder/.gitignore`` that covers a path below that folder."""
    return [
        pattern
        for pattern in _ignore_patterns(folder / ".gitignore")
        if _covered_by(pattern, relative)
    ]


def test_the_program_that_runs_a_script_is_in_the_repository_and_not_ignored():
    """A file nothing commits cannot reach an installation.

    The old folder ignores every ``.py`` inside it, in two separate rules, one of
    them from the folder above. That is right for a trader's uploaded scripts and
    wrong for a file the platform owns: it was never committed, so no upgrade
    could ever have delivered it.

    The wrong implementation this catches is the move that does not really move
    anything: the program left under a folder whose rules hide it. The same
    reading of those rules is pointed at the old path first, so this test cannot
    pass by having a reader that matches nothing.
    """
    assert RUNNER_PATH.is_file(), "the program that runs a script is not where it belongs"
    assert not RUNNER_WAS.exists(), "the program is still in the folder that hides it"

    # The reading works: it finds the rule that hid the file in the old place.
    was = RUNNER_WAS.relative_to(REPOSITORY)
    hidden = _ignored_under(REPOSITORY / "strategies", was.relative_to("strategies")) + (
        _ignored_under(REPOSITORY / "strategies" / "scripts", Path(was.name))
    )
    assert hidden, "this test's reading of an ignore file finds nothing, so it proves nothing"

    # And it finds nothing covering the new place.
    here = RUNNER_PATH.relative_to(REPOSITORY)
    covering = _ignored_under(REPOSITORY, here) + _ignored_under(
        RUNNER_PATH.parent, Path(here.name)
    )
    assert covering == [], f"the program is ignored by {covering}"


def test_the_program_does_not_live_in_a_folder_the_deployment_mounts_over():
    """A named volume is seeded from the image only while it is empty.

    So a platform file placed inside one is delivered to a brand new install and
    to nobody else: every install that has run once already keeps its own copy of
    that folder, and an upgrade puts the new file into an image nobody reads from
    there. The file is then absent, and the run refuses with a message about a
    missing program on exactly the installations that have been running longest.

    The wrong implementation this catches is a move to another mounted folder,
    which looks like a fix and is the same defect. The old location is checked as
    well, so this test says why it was wrong rather than only asserting a
    preference.
    """
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    mounts = []
    for service in compose.get("services", {}).values():
        for entry in service.get("volumes", []) or []:
            pieces = str(entry).split(":")
            if len(pieces) >= 2:
                mounts.append(PurePosix(pieces[1]))

    assert mounts, "no mounts were read out of the deployment file, so this proves nothing"

    inside = PurePosix("/app") / RUNNER_PATH.relative_to(REPOSITORY).as_posix()
    for mount in mounts:
        assert not _within(inside, mount), f"the program sits inside the mounted folder {mount}"

    # The old place really was inside one, which is the whole reason for the move.
    old = PurePosix("/app") / RUNNER_WAS.relative_to(REPOSITORY).as_posix()
    assert any(_within(old, mount) for mount in mounts), (
        "the folder the program came out of is not mounted in this deployment file, so "
        "either the file changed or this test is checking the wrong thing"
    )


def test_the_program_is_copied_into_the_image_and_not_excluded_from_the_build():
    """It has to be in the image for the mount question to matter at all.

    The build copies the whole tree, so what decides this is the exclusion list.
    The wrong implementation this catches is a new folder that happens to match an
    entry there, which would leave the image without the program and every
    container install unable to start a script.
    """
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "COPY --chown=appuser:appuser . ." in dockerfile, (
        "the build no longer copies the tree, so what ships has to be checked another way"
    )

    here = RUNNER_PATH.relative_to(REPOSITORY)
    excluded = [
        pattern for pattern in _ignore_patterns(DOCKERIGNORE_PATH) if _covered_by(pattern, here)
    ]
    assert excluded == [], f"the program is kept out of the image by {excluded}"


# ---------------------------------------------------------------------------
# Small helpers used by the packaging tests
# ---------------------------------------------------------------------------


class PurePosix:
    """A container path, compared as text, without a Windows path type in the way.

    ``pathlib`` on this platform reads ``/app/strategies`` as a Windows path, and
    two of them compare in ways that have nothing to do with a container. These
    are the deployment file's own strings and they are compared as such.
    """

    def __init__(self, text: str) -> None:
        self.text = "/" + str(text).strip().strip("/")

    def __truediv__(self, other) -> "PurePosix":
        return PurePosix(f"{self.text}/{str(other).strip('/')}")

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return self.text


def _within(path: PurePosix, folder: PurePosix) -> bool:
    """Whether a path is the folder or sits under it."""
    return path.text == folder.text or path.text.startswith(folder.text.rstrip("/") + "/")


# ---------------------------------------------------------------------------
# Where the orders actually went
# ---------------------------------------------------------------------------
#
# This runner deliberately does not pass ``force_live``. That was decided, and
# it has a consequence the platform itself documents in
# ``services/place_order_service.py``: the destination is read per order, so an
# operator turning the analyzer on while a run holds a position sends that
# run's exits to the sandbox while the broker still holds what the entries
# opened. The guard below is the whole of what stands in for ``force_live``, so
# it is tested rather than trusted.


class _Answering:
    """A platform that accepts every order and says where it sent it."""

    def __init__(self, modes):
        self.modes = list(modes)
        self.sent = 0

    def placeorder(self, **_ignored):
        mode = self.modes[min(self.sent, len(self.modes) - 1)]
        self.sent += 1
        answer = {"status": "success", "orderid": f"ORD-{self.sent}"}
        if mode == "analyzer":
            answer["mode"] = "analyze"
        return answer


def _routing_session(modes, holding=0.0):
    """A Session with only the parts ``_route`` touches, and a stated destination.

    ``holding`` is this run's net position, which is what decides whether a
    changed destination is dangerous. A run holding nothing has nothing open at
    the earlier destination; one holding something has its entry there.
    """
    session = object.__new__(runner.Session)
    session.client = _Answering(modes)
    session.options = types.SimpleNamespace(
        strategy_name="probe", symbol="AAA", exchange="XX", script="probe.oscript"
    )
    session.product = "MIS"
    session.stopping = False
    session._orders = {}
    session._open = set()
    session._destination = None
    session.ledger = types.SimpleNamespace(size=lambda: holding)
    return session


def _an_order(intent_id=1, side="buy"):
    return types.SimpleNamespace(
        kind="place",
        intent_id=intent_id,
        side=side,
        qty=1,
        qty_type="units",
        placement=types.SimpleNamespace(order_type="market", limit=None, trigger=None),
    )


def test_the_destination_of_the_first_accepted_order_is_remembered(capsys):
    # Catches the run never learning where it is sending, which is what makes
    # every later comparison impossible. Without this there is nothing to
    # compare a changed destination against and the guard cannot fire at all.
    session = _routing_session(["live"])

    assert session._route(_an_order()) is True
    assert session._destination == "live"
    assert "live destination" in capsys.readouterr().out


def test_an_analyzer_answer_is_recorded_as_the_analyzer_destination(capsys):
    # Catches the mode marker being read off the wrong key or compared against
    # the wrong word. The platform answers "analyze"; reading anything else
    # makes every sandbox run look like a live one and the guard never fires.
    session = _routing_session(["analyzer"])

    assert session._route(_an_order()) is True
    assert session._destination == "analyzer"


def test_a_run_whose_destination_changes_under_it_stops_and_says_what_is_open(capsys):
    # THE ONE THAT MATTERS. Catches the guard being absent, which is how this
    # was written: the entry goes live, an operator turns the analyzer on, and
    # the exit is accepted by the sandbox while the broker still holds the
    # position. The platform reports success for both, so nothing else in this
    # program can tell that the position is now unmanaged.
    session = _routing_session(["live", "analyzer"], holding=1.0)

    assert session._route(_an_order(1, "buy")) is True
    assert session.stopping is False

    assert session._route(_an_order(2, "sell")) is False
    assert session.stopping is True, "the run carried on after its exits were diverted"

    said = capsys.readouterr().out
    assert "STOPPING" in said
    assert "analyzer" in said and "live" in said
    assert "checked and closed by a person" in said


def test_a_flat_run_follows_the_platform_when_the_destination_changes(capsys):
    """THE ONE THIS GAINED, AND THE COMPLAINT BEHIND IT.

    An operator moves the platform between live and analyzer several times a
    day. This guard fired on the change rather than on the position, so a
    toggle flipped and flipped back silently killed every idle strategy on the
    server: a trader came back to a panel of stopped rows, each of which had
    been doing nothing wrong.

    A run holding nothing has nothing open at the earlier destination. There is
    no exit to strand, so it follows the platform and carries on. What it must
    not do is carry on quietly: the line says where its orders go now.
    """
    session = _routing_session(["live", "analyzer"], holding=0.0)

    assert session._route(_an_order(1, "buy")) is True
    assert session._route(_an_order(2, "buy")) is True

    assert session.stopping is False, "a flat run was stopped by a toggle it could follow"
    assert session._destination == "analyzer"
    said = capsys.readouterr().out
    assert "STOPPING" not in said
    assert "holding nothing" in said


def test_a_position_this_run_cannot_measure_counts_as_one_it_holds(capsys):
    """Catches an unreadable position read as flat.

    Flat is the answer that lets a run carry on through a changed destination.
    Guessing it wrong the safe way costs a stopped strategy and a line saying
    so; guessing it wrong the other way sends an exit somewhere the entry never
    went.
    """

    def raises():
        raise RuntimeError("the ledger would not answer")

    session = _routing_session(["live", "analyzer"])
    session.ledger = types.SimpleNamespace(size=raises)

    assert session._route(_an_order(1, "buy")) is True
    assert session._route(_an_order(2, "sell")) is False
    assert session.stopping is True


def test_a_destination_that_does_not_change_never_stops_the_run(capsys):
    # The other side, and the reason the guard compares rather than refuses: a
    # run that stayed where it started must go on trading. A guard that stopped
    # on every second order would be worse than no guard, because it would look
    # like the platform was flapping.
    session = _routing_session(["analyzer", "analyzer", "analyzer"])

    for at in range(3):
        assert session._route(_an_order(at + 1)) is True
    assert session.stopping is False
    assert session._destination == "analyzer"


def test_the_runner_never_asks_for_a_live_order():
    # The decision itself, held as a check rather than a promise in a comment.
    # force_live is what makes an order bypass the analyzer toggle, and no part
    # of this program may pass it.
    source = RUNNER_PATH.read_text(encoding="utf-8")
    offending = [
        line.strip()
        for line in source.splitlines()
        if "force_live" in line and not line.lstrip().startswith("#")
        and "``force_live``" not in line
    ]
    assert offending == [], f"the runner asks for a live order: {offending}"
