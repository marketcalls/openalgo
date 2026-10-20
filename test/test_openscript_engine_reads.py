"""What the engine serves from 0.6.0 that 0.5.0 refused, and what this runner does with it.

0.5.0 refused at load every program that read another timeframe (OS6006), and
every program that read ``session.isLastBar``, ``chart.intervalMinutes`` or
``chart.isIntraday`` (OS6004). From 0.6.0 the engine serves all of them, and on
this server three would load and then answer nothing on every bar, with nothing
in the log to say why:

- **A day, a week or a month read by ``req.timeframe``.** The engine folds one by
  the calendar in the instrument's zone, and its fold reads a calendar in UTC
  alone. The reader this host supplies reaches ``date.*`` and not the fold, so on
  the platform's own zone the read is absent on every bar. The runner refuses it
  by name, and a read in minutes or hours, which is folded by counting, runs.
- **``session.isLastBar``.** The engine answers it from a bar fact this driver
  does not state, so it was never true and a position meant to close at the end
  of the session never closed. Refused by name.
- **The interval.** The engine compares every read with the stated interval and
  works the two interval facts out from it, in ``stdlib.md`` 15.2's spelling. The
  platform writes a day as ``D``, which that spelling cannot read, so a daily run
  compared nothing and answered neither fact. The runner now states the interval
  as the chart's backtest does, ``1D``.

Each program below is real, compiled by the 0.8.1 compiler. No test here reaches
a broker or places an order: every program is a study, and the platform client is
the stand-in the runner's other tests use.
"""

import json
from datetime import date, timedelta

import pytest
from openscript.contracts import Bar
from openscript.run import load_text

import openscript_host.openscript_runner as runner
from test.test_openscript_runner import options_for
from test.test_openscript_runner_facts import (
    MADE_UP_SESSION,
    PLATFORM_ZONE,
    REGULAR_TUESDAY,
    Platform,
    at,
    handed_facts,
)

# ---------------------------------------------------------------------------
# Real compiled programs. A program's hash is taken over its canonical text and a
# load from text insists on it, so none of these can be written by hand.
# ---------------------------------------------------------------------------

#: Compiled by the 0.8.1 compiler from:
#:
#:     version 1
#:     study("Daily", overlay = true)
#:     plot(req.timeframe("1D", close), "Daily close")
DAILY_READ_PROGRAM = (
    '{"callSites":[],"cells":[],"channels":[{"defer":false,"id":0,"once":true,"ty'
    'pe":"number"}],"code":[["SLOAD",0],["EMIT",0],["HALT"]],"compiler":{"name":"'
    'openscript","version":"0.8.1"},"consts":[["z",null],["b",false],["b",true]],'
    '"debug":{"fnPos":[],"names":{"cells":[],"channels":["Daily close"],"series":'
    '["req.timeframe"],"slots":[]},"pos":[[0,3,6],[1,3,1]],"retain":false},"frame'
    '":{"slots":0},"functions":[],"inputs":[],"lib":{"functions":[],"manifest":1}'
    ',"limits":{"history":null,"loops":2000000},"loops":[],"meta":{"format":"pric'
    'e","group":"","kind":"study","onUnconfirmed":false,"overlay":true,"precision'
    '":4,"range":null,"scale":"right","short":"Daily","title":"Daily"},"openscrip'
    't":{"format":"1.1","language":1},"outputs":{"alerts":[],"background":null,"b'
    'arColor":null,"fills":[],"levels":[],"markers":[],"plots":[{"channel":0,"col'
    'or":null,"colorChannel":null,"key":"p0","lineStyle":"solid","offset":0,"ohlc'
    '":null,"overlay":null,"precision":null,"priceFormat":null,"scale":"right","t'
    'itle":"Daily close","type":"line","width":1.5}],"tables":[]},"requests":[{"b'
    'ody":{"callSites":[],"cells":[],"code":[["SLOAD",0],["RET"]],"fnPos":[],"fra'
    'me":{"slots":0},"functions":[],"inputs":[],"loops":[],"pos":[[0,3,26]],"requ'
    'ests":[],"series":[{"field":"close","id":0,"kind":"bar","name":"close"}],"st'
    'ates":[]},"exchange":null,"id":0,"mode":"confirmed","read":"timeframe","seri'
    'es":0,"symbol":null,"timeframe":"1D","warmup":0}],"requires":["core.1","req.'
    'timeframe"],"series":[{"field":null,"id":0,"kind":"request","name":"req.time'
    'frame"}],"source":{"file":"daily.oscript","hash":"sha256:050ad4de840e6d024b9'
    'bf3bfca69c4e828b25f80b77aa68974a0e9790e85edbf","lines":4},"states":[]}'
)

#: Compiled by the 0.8.1 compiler from:
#:
#:     version 1
#:     study("Five", overlay = true)
#:     plot(req.timeframe("5m", close), "Five minute close")
FIVE_MINUTE_READ_PROGRAM = (
    '{"callSites":[],"cells":[],"channels":[{"defer":false,"id":0,"once":true,"ty'
    'pe":"number"}],"code":[["SLOAD",0],["EMIT",0],["HALT"]],"compiler":{"name":"'
    'openscript","version":"0.8.1"},"consts":[["z",null],["b",false],["b",true]],'
    '"debug":{"fnPos":[],"names":{"cells":[],"channels":["Five minute close"],"se'
    'ries":["req.timeframe"],"slots":[]},"pos":[[0,3,6],[1,3,1]],"retain":false},'
    '"frame":{"slots":0},"functions":[],"inputs":[],"lib":{"functions":[],"manife'
    'st":1},"limits":{"history":null,"loops":2000000},"loops":[],"meta":{"format"'
    ':"price","group":"","kind":"study","onUnconfirmed":false,"overlay":true,"pre'
    'cision":4,"range":null,"scale":"right","short":"Five","title":"Five"},"opens'
    'cript":{"format":"1.1","language":1},"outputs":{"alerts":[],"background":nul'
    'l,"barColor":null,"fills":[],"levels":[],"markers":[],"plots":[{"channel":0,'
    '"color":null,"colorChannel":null,"key":"p0","lineStyle":"solid","offset":0,"'
    'ohlc":null,"overlay":null,"precision":null,"priceFormat":null,"scale":"right'
    '","title":"Five minute close","type":"line","width":1.5}],"tables":[]},"requ'
    'ests":[{"body":{"callSites":[],"cells":[],"code":[["SLOAD",0],["RET"]],"fnPo'
    's":[],"frame":{"slots":0},"functions":[],"inputs":[],"loops":[],"pos":[[0,3,'
    '26]],"requests":[],"series":[{"field":"close","id":0,"kind":"bar","name":"cl'
    'ose"}],"states":[]},"exchange":null,"id":0,"mode":"confirmed","read":"timefr'
    'ame","series":0,"symbol":null,"timeframe":"5m","warmup":0}],"requires":["cor'
    'e.1","req.timeframe"],"series":[{"field":null,"id":0,"kind":"request","name"'
    ':"req.timeframe"}],"source":{"file":"five.oscript","hash":"sha256:eeeeabe037'
    '983c8f3c86ac72adcb87bca7c83be4f1a4eb8ac57ab2b5bb45ecab","lines":4},"states":'
    "[]}"
)

#: Compiled by the 0.8.1 compiler from:
#:
#:     version 1
#:     study("Last", overlay = true)
#:     plot(session.isLastBar ? 1 : 0, "Last")
LAST_BAR_PROGRAM = (
    '{"callSites":[],"cells":[],"channels":[{"defer":false,"id":0,"once":true,"ty'
    'pe":"number"}],"code":[["CALL_LIB",0,0,-1],["JUMP_FALSE",4],["CONST",3],["JU'
    'MP",5],["CONST",4],["EMIT",0],["HALT"]],"compiler":{"name":"openscript","ver'
    'sion":"0.8.1"},"consts":[["z",null],["b",false],["b",true],["n",1],["n",0]],'
    '"debug":{"fnPos":[],"names":{"cells":[],"channels":["Last"],"series":[],"slo'
    'ts":[]},"pos":[[0,3,6],[2,3,26],[3,3,6],[4,3,30],[5,3,1]],"retain":false},"f'
    'rame":{"slots":0},"functions":[],"inputs":[],"lib":{"functions":[{"arity":0,'
    '"effect":"none","name":"session.isLastBar","state":false}],"manifest":1},"li'
    'mits":{"history":null,"loops":2000000},"loops":[],"meta":{"format":"price","'
    'group":"","kind":"study","onUnconfirmed":false,"overlay":true,"precision":4,'
    '"range":null,"scale":"right","short":"Last","title":"Last"},"openscript":{"f'
    'ormat":"1.1","language":1},"outputs":{"alerts":[],"background":null,"barColo'
    'r":null,"fills":[],"levels":[],"markers":[],"plots":[{"channel":0,"color":nu'
    'll,"colorChannel":null,"key":"p0","lineStyle":"solid","offset":0,"ohlc":null'
    ',"overlay":null,"precision":null,"priceFormat":null,"scale":"right","title":'
    '"Last","type":"line","width":1.5}],"tables":[]},"requests":[],"requires":["c'
    'ore.1"],"series":[],"source":{"file":"last.oscript","hash":"sha256:6b4603597'
    '5962a080946996c293654521ee330e7ab81a9216259fb2a12a1aad5","lines":4},"states"'
    ":[]}"
)

#: Compiled by the 0.8.1 compiler from:
#:
#:     version 1
#:     study("Minutes", overlay = true)
#:     plot(chart.intervalMinutes, "Minutes")
INTERVAL_MINUTES_PROGRAM = (
    '{"callSites":[],"cells":[],"channels":[{"defer":false,"id":0,"once":true,"ty'
    'pe":"number"}],"code":[["CALL_LIB",0,0,-1],["EMIT",0],["HALT"]],"compiler":{'
    '"name":"openscript","version":"0.8.1"},"consts":[["z",null],["b",false],["b"'
    ',true]],"debug":{"fnPos":[],"names":{"cells":[],"channels":["Minutes"],"seri'
    'es":[],"slots":[]},"pos":[[0,3,6],[1,3,1]],"retain":false},"frame":{"slots":'
    '0},"functions":[],"inputs":[],"lib":{"functions":[{"arity":0,"effect":"none"'
    ',"name":"chart.intervalMinutes","state":false}],"manifest":1},"limits":{"his'
    'tory":null,"loops":2000000},"loops":[],"meta":{"format":"price","group":"","'
    'kind":"study","onUnconfirmed":false,"overlay":true,"precision":4,"range":nul'
    'l,"scale":"right","short":"Minutes","title":"Minutes"},"openscript":{"format'
    '":"1.1","language":1},"outputs":{"alerts":[],"background":null,"barColor":nu'
    'll,"fills":[],"levels":[],"markers":[],"plots":[{"channel":0,"color":null,"c'
    'olorChannel":null,"key":"p0","lineStyle":"solid","offset":0,"ohlc":null,"ove'
    'rlay":null,"precision":null,"priceFormat":null,"scale":"right","title":"Minu'
    'tes","type":"line","width":1.5}],"tables":[]},"requests":[],"requires":["cor'
    'e.1"],"series":[],"source":{"file":"minutes.oscript","hash":"sha256:cbe2652f'
    '77c6281ed62e5f4109fafdf58f38514d7a2d5f1f10af56d526905d6e","lines":4},"states'
    '":[]}'
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def rising(times):
    """One bar per instant, each closing one point above the bar before it."""
    return [
        (one, 100.0 + step, 101.0 + step, 99.0 + step, 100.0 + step, 10.0)
        for step, one in enumerate(times)
    ]


def session_for(program, monkeypatch, rows, interval="1m", timezone=PLATFORM_ZONE, session=None):
    """A run of one program on the real engine, with the facts the platform hands over."""
    facts = handed_facts(timezone=timezone, session=session)
    monkeypatch.setenv("OPENSCRIPT_INSTRUMENT", json.dumps(facts))
    monkeypatch.setenv("OPENSCRIPT_INPUTS", "{}")
    options = options_for(interval=interval, timezone=timezone)
    return runner.Session(runner.Engine(), options, program, Platform(rows))


def plotted(session, polls=80):
    """The first plot's value on every bar the run executed, as last executed."""
    seen = {}
    real = session.run.execute_bar

    def recording(index, *args, **kwargs):
        result = real(index, *args, **kwargs)
        assert result.diagnostic is None, result.diagnostic.code
        seen[index] = result.columns[0]
        return result

    session.run.execute_bar = recording
    for _ in range(polls):
        if session.cycle() is not None:
            break
    return [seen[index] for index in sorted(seen)]


def bar_at(when, close):
    return Bar(
        time=float(when), open=close, high=close + 1, low=close - 1, close=close, volume=10.0
    )


def tuesday_minutes(first, last):
    return [at(REGULAR_TUESDAY, 9, minute) for minute in range(first, last + 1)]


# ---------------------------------------------------------------------------
# The interval, in the engine's spelling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "spelled"),
    [
        ("D", "1D"),
        ("1d", "1D"),
        ("W", "1W"),
        ("M", "1M"),
        ("1m", "1m"),
        ("5m", "5m"),
        ("15m", "15m"),
        ("1h", "1h"),
        ("1H", "1h"),
        ("60", "60"),
    ],
)
def test_the_interval_is_spelled_as_the_chart_s_backtest_spells_it(code, spelled):
    """The cases ``backtestRun.test.ts`` and ``openscriptIntervals.test.ts`` pin for the chart."""
    assert runner.engine_interval(code) == spelled


@pytest.mark.parametrize("code", ["30s", "5s", "", "0m", "m", "5min"])
def test_an_interval_the_engine_has_no_spelling_for_is_not_stated(code):
    assert runner.engine_interval(code) is None


def test_a_daily_run_tells_the_engine_a_day_and_the_script_reads_its_length(monkeypatch):
    days = [at(REGULAR_TUESDAY + timedelta(days=step), 9, 15) for step in range(4)]
    session = session_for(INTERVAL_MINUTES_PROGRAM, monkeypatch, rising(days), interval="D")

    assert session.instrument["interval"] == "1D"
    values = plotted(session)
    assert values and all(one == 1440 for one in values)


def test_a_seconds_run_states_no_interval_rather_than_one_the_engine_cannot_read(monkeypatch):
    rows = rising(tuesday_minutes(15, 17))
    session = session_for(INTERVAL_MINUTES_PROGRAM, monkeypatch, rows, interval="30s")

    assert "interval" not in session.instrument


# ---------------------------------------------------------------------------
# Higher timeframe reads
# ---------------------------------------------------------------------------


def test_a_minute_read_on_a_minute_run_folds_in_the_platform_zone(monkeypatch):
    times = tuesday_minutes(15, 26)
    values = plotted(session_for(FIVE_MINUTE_READ_PROGRAM, monkeypatch, rising(times)))

    # A confirmed read is the last five minutes that have closed: nothing in the
    # first five, then 09:19's close through the next five, then 09:24's.
    closes = [100.0 + step for step in range(len(times))]
    assert values == [None] * 5 + [closes[4]] * 5 + [closes[9]] * 2


def test_a_read_finer_than_a_daily_run_is_refused_by_the_engine_at_load(monkeypatch):
    """Stated as ``D`` the engine compared nothing, and this read folded without a word."""
    days = [at(REGULAR_TUESDAY + timedelta(days=step), 9, 15) for step in range(4)]

    with pytest.raises(runner.Refusal) as refused:
        session_for(FIVE_MINUTE_READ_PROGRAM, monkeypatch, rising(days), interval="D")

    assert "OS6002" in str(refused.value)


def test_a_day_read_on_the_platform_zone_is_refused_by_name(monkeypatch):
    with pytest.raises(runner.Refusal) as refused:
        session_for(DAILY_READ_PROGRAM, monkeypatch, rising(tuesday_minutes(15, 20)))

    said = str(refused.value)
    assert "1D" in said
    assert "req.timeframe" in said
    assert PLATFORM_ZONE in said


def test_the_engine_answers_a_day_read_on_the_platform_zone_with_nothing():
    """The defect the refusal above exists for, on the engine alone.

    So that refusal cannot pass vacuously, and so that the day an engine dates a
    day in a zone the host supplies, this fails and the refusal can go. The same
    bars in UTC answer, which is what shows the zone is the whole of it.
    """
    days = (REGULAR_TUESDAY, REGULAR_TUESDAY + timedelta(days=1))
    answered = {}
    for zone in (PLATFORM_ZONE, "UTC"):
        times = [at(day, 9, minute, zone=zone) for day in days for minute in range(15, 18)]
        instrument = {"symbol": "SYM1", "exchange": "EXCH1", "interval": "1m", "timezone": zone}
        loaded = load_text(DAILY_READ_PROGRAM, instrument=instrument)
        assert loaded.diagnostic is None
        answered[zone] = [
            loaded.run.execute_bar(
                index, bar_at(when, 100.0 + index), instrument=instrument
            ).columns[0]
            for index, when in enumerate(times)
        ]

    assert answered[PLATFORM_ZONE] == [None] * 6
    assert answered["UTC"] == [None] * 3 + [102.0] * 3


def test_a_day_read_on_an_instrument_read_in_utc_runs(monkeypatch):
    first = date(2026, 9, 22)
    times = [at(first, 23, minute, zone="UTC") for minute in range(57, 60)]
    times += [at(first + timedelta(days=1), 0, minute, zone="UTC") for minute in range(3)]

    values = plotted(session_for(DAILY_READ_PROGRAM, monkeypatch, rising(times), timezone="UTC"))

    assert values == [None] * 3 + [102.0] * 3


# ---------------------------------------------------------------------------
# The session's last bar
# ---------------------------------------------------------------------------


def test_session_is_last_bar_is_refused_by_name_where_the_session_is_known(monkeypatch):
    rows = rising(tuesday_minutes(15, 20))

    with pytest.raises(runner.Refusal) as refused:
        session_for(LAST_BAR_PROGRAM, monkeypatch, rows, session=MADE_UP_SESSION)

    said = str(refused.value)
    assert "session.isLastBar" in said
    assert "left open" in said


def test_the_engine_reads_the_last_bar_from_a_fact_this_runner_does_not_state():
    """Why the refusal above exists, and what lifting it would take.

    Stated the way this driver states a bar, ``session.isLastBar`` is never true.
    It is true only where its own bar fact is stated beside the first one.
    """
    engine = runner.Engine()
    instrument = {"symbol": "SYM1", "exchange": "EXCH1", "interval": "1m", "timezone": "UTC"}
    answered = {}
    for stated in ({}, {"isSessionLast": True}):
        served = engine.Serving(None)
        loaded = load_text(LAST_BAR_PROGRAM, None, served, instrument=instrument)
        assert loaded.diagnostic is None
        values = []
        for index in range(3):
            when = at(REGULAR_TUESDAY, 10, index, zone="UTC")
            served.at_bar(
                {"time": float(when), engine.session_first: index == 0, **stated}, index == 0
            )
            result = loaded.run.execute_bar(index, bar_at(when, 100.0), instrument=instrument)
            values.append(result.columns[0])
        answered[bool(stated)] = values

    assert answered[False] == [0.0, 0.0, 0.0]
    assert answered[True] == [1.0, 1.0, 1.0]
