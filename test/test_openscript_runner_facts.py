"""What a deployed strategy is told about its instrument, and what it may now do with it.

The runner in ``openscript_host/openscript_runner.py`` used to refuse any script
that read ``date.*``, ``session.isIn``, ``session.isFirstBar`` or a written time,
and any script sized in lots, and it read a stopped strategy's books from
whatever the analyzer toggle said at the moment somebody opened the page. Four
things were missing:

- **No zone but UTC and no session.** The engine reads a calendar in UTC alone
  and leaves every other zone to the host, and the host stated no session, so
  every calendar read was absent on the platform's own zone and every session
  fact was absent everywhere.
- **The calendar calls were not served at all.** The engine implements them and
  its library seam leaves them out, so a program calling one was refused at load
  in every zone, UTC included, with a code rather than a sentence.
- **No conversion.** A count of lots has to become the count of units the order
  path takes, once, with the contract's lot size, and nothing did that.
- **No record of the side a run traded on.** The books route looked for one and
  nothing ever wrote it.

Each removed refusal below is covered by a real compiled program on the real
engine that now loads and acts on the right bar, and each refusal that guards
something the engine or the order path genuinely cannot do still refuses. The
calendar tests run on the calendar's own tables, seeded by its own functions, as
``test_openscript_instrument_facts.py`` does; only the master contract lookup is
replaced, because it reads a broker's download.

No test here reaches a broker or places an order anywhere: the platform client
is a stand-in that records what it was asked to send.
"""

import json
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import openscript.dates as engine_calendar
import psutil
import pytest
from flask import Flask
from sqlalchemy.orm import scoped_session, sessionmaker

import openscript_host.openscript_runner as runner
import services.openscript_books as books
import services.openscript_commands as commands
import services.openscript_instrument_service as facts_service
import services.openscript_run_config as run_config
import services.openscript_runner_service as service
import services.openscript_running as running
import utils.session
from blueprints import openscript_runner as runner_routes
from database.engine_factory import create_db_engine
from openscript_host.calendar_reader import CalendarReader
from test.test_openscript_instrument_facts import MasterContract
from test.test_openscript_runner import (
    Candles,
    options_for,
    stand_in_engine,
    strategy_program,
)

#: The zone the platform's market calendar reads every exchange in. The facts
#: service states it from the calendar; the tests below build bars with it.
PLATFORM_ZONE = "Asia/Kolkata"

REGULAR_TUESDAY = date(2026, 9, 22)
REGULAR_WEDNESDAY = date(2026, 9, 23)
FRIDAY_BEFORE_MUHURAT = date(2026, 11, 6)
MUHURAT_SUNDAY = date(2026, 11, 8)  # SPECIAL_SESSION in the 2026 seed

#: A session made up for the tests that do not read the calendar. Deliberately
#: not the market's hours, so nothing below reads as a statement of them.
MADE_UP_SESSION = {"start": "10:00", "end": "14:00", "days": [1, 2, 3, 4, 5]}

# ---------------------------------------------------------------------------
# Real compiled programs, exactly as the compiler in frontend/node_modules
# produced them. A program's hash is taken over its canonical text and a load
# from text insists on it, so none of these can be written by hand.
# ---------------------------------------------------------------------------

#: Compiled from:
#:
#:     version 1
#:     start = input(0, "Start", kind = "time")
#:     strategy("Timed", overlay = true, qty = 1)
#:     if time == start
#:         buy()
TIME_INPUT_PROGRAM = (
    '{"callSites":[],"cells":[],"channels":[],"code":[["SLOAD",0],["LOAD",0],["E'
    'Q"],["JUMP_FALSE",12],["CONST",0],["CONST",0],["CONST",0],["CONST",3],["CONS'
    'T",0],["CONST",3],["CALL_LIB",0,6,-1],["POP"],["HALT"]],"compiler":{"name":'
    '"openscript","version":"0.5.0"},"consts":[["z",null],["b",false],["b",true'
    '],["s",""]],"debug":{"fnPos":[],"names":{"cells":[],"channels":[],"series'
    '":["time"],"slots":["start"]},"pos":[[0,4,4],[1,4,12],[2,4,9],[3,4,1],[4,5,5]],'
    '"retain":false},"frame":{"slots":1},"functions":[],"inputs":[{"default":["n'
    '",0],"group":"","key":"start","kind":"time","label":"Start","max":nul'
    'l,"min":null,"options":null,"slot":0,"step":null,"tooltip":null}],"lib":{"f'
    'unctions":[{"arity":6,"effect":"order","name":"buy","state":false}],"manif'
    'est":1},"limits":{"history":null,"loops":2000000},"loops":[],"meta":{"format'
    '":"price","group":"","kind":"strategy","onUnconfirmed":false,"overlay":tr'
    'ue,"precision":4,"range":null,"scale":"right","short":"Timed","strategy":{'
    '"capital":100000,"closeOnSessionEnd":false,"commission":0,"commissionType":"per'
    'Trade","currency":"","fillOn":"nextOpen","product":"intraday","pyramiding"'
    ':1,"qty":1,"qtyType":"units","slippage":0},"title":"Timed"},"openscript":{'
    '"format":"1.1","language":1},"outputs":{"alerts":[],"background":null,"barC'
    'olor":null,"fills":[],"levels":[],"markers":[],"plots":[],"tables":[]},"requ'
    'ests":[],"requires":["core.1","orders"],"series":[{"field":"time","id":0,'
    '"kind":"bar","name":"time"}],"source":{"file":"timeinput.oscript","hash"'
    ':"sha256:e7024ca2edd8a6f37d00bdff9693ebdd2ce65d7881f898160cc74899a978ec1c","lines":6'
    '},"states":[]}'
)

#: Compiled from:
#:
#:     version 1
#:     strategy("Opening", overlay = true, qty = 1)
#:     if session.isFirstBar
#:         buy()
FIRST_BAR_PROGRAM = (
    '{"callSites":[],"cells":[],"channels":[],"code":[["CALL_LIB",0,0,-1],["JUMP_F'
    'ALSE",10],["CONST",0],["CONST",0],["CONST",0],["CONST",3],["CONST",0],["CONS'
    'T",3],["CALL_LIB",1,6,-1],["POP"],["HALT"]],"compiler":{"name":"openscript"'
    ',"version":"0.5.0"},"consts":[["z",null],["b",false],["b",true],["s",""]'
    '],"debug":{"fnPos":[],"names":{"cells":[],"channels":[],"series":[],"slots"'
    ':[]},"pos":[[0,3,4],[1,3,1],[2,4,5]],"retain":false},"frame":{"slots":0},"funct'
    'ions":[],"inputs":[],"lib":{"functions":[{"arity":0,"effect":"none","name"'
    ':"session.isFirstBar","state":false},{"arity":6,"effect":"order","name":"bu'
    'y","state":false}],"manifest":1},"limits":{"history":null,"loops":2000000},"'
    'loops":[],"meta":{"format":"price","group":"","kind":"strategy","onUncon'
    'firmed":false,"overlay":true,"precision":4,"range":null,"scale":"right","sho'
    'rt":"Opening","strategy":{"capital":100000,"closeOnSessionEnd":false,"commissi'
    'on":0,"commissionType":"perTrade","currency":"","fillOn":"nextOpen","produ'
    'ct":"intraday","pyramiding":1,"qty":1,"qtyType":"units","slippage":0},"tit'
    'le":"Opening"},"openscript":{"format":"1.1","language":1},"outputs":{"aler'
    'ts":[],"background":null,"barColor":null,"fills":[],"levels":[],"markers":[],'
    '"plots":[],"tables":[]},"requests":[],"requires":["core.1","orders"],"serie'
    's":[],"source":{"file":"firstbar.oscript","hash":"sha256:f2498b08a681f288050b2'
    'f2ac0c4ed6ccadce06f73e472f0c936a441eaf15f5e","lines":5},"states":[]}'
)

#: Compiled from:
#:
#:     version 1
#:     strategy("Window", overlay = true, qty = 1)
#:     if session.isIn("0915-0916")
#:         buy()
WINDOW_PROGRAM = (
    '{"callSites":[],"cells":[],"channels":[],"code":[["CONST",3],["CALL_LIB",1,0'
    ',-1],["CALL_LIB",0,2,-1],["JUMP_FALSE",12],["CONST",0],["CONST",0],["CONST",0]'
    ',["CONST",4],["CONST",0],["CONST",4],["CALL_LIB",2,6,-1],["POP"],["HALT"]],"'
    'compiler":{"name":"openscript","version":"0.5.0"},"consts":[["z",null],["b'
    '",false],["b",true],["s","0915-0916"],["s",""]],"debug":{"fnPos":[],"nam'
    'es":{"cells":[],"channels":[],"series":[],"slots":[]},"pos":[[0,3,17],[1,3,4]'
    ',[3,3,1],[4,4,5]],"retain":false},"frame":{"slots":0},"functions":[],"inputs":'
    '[],"lib":{"functions":[{"arity":2,"effect":"none","name":"session.isIn","'
    'state":false},{"arity":0,"effect":"none","name":"chart.timezone","state":fa'
    'lse},{"arity":6,"effect":"order","name":"buy","state":false}],"manifest":1'
    '},"limits":{"history":null,"loops":2000000},"loops":[],"meta":{"format":"pr'
    'ice","group":"","kind":"strategy","onUnconfirmed":false,"overlay":true,"pr'
    'ecision":4,"range":null,"scale":"right","short":"Window","strategy":{"capi'
    'tal":100000,"closeOnSessionEnd":false,"commission":0,"commissionType":"perTrade"'
    ',"currency":"","fillOn":"nextOpen","product":"intraday","pyramiding":1,"q'
    'ty":1,"qtyType":"units","slippage":0},"title":"Window"},"openscript":{"for'
    'mat":"1.1","language":1},"outputs":{"alerts":[],"background":null,"barColor"'
    ':null,"fills":[],"levels":[],"markers":[],"plots":[],"tables":[]},"requests"'
    ':[],"requires":["core.1","orders"],"series":[],"source":{"file":"window.osc'
    'ript","hash":"sha256:fae1185a2802a2a8cdc1c9710aa62a01b3279fdd3cb3b1beb8bf2a703ef8f21'
    '2","lines":5},"states":[]}'
)

#: Compiled from:
#:
#:     version 1
#:     strategy("Lots", overlay = true, qty = 2, qtyType = "lots")
#:     if pos.isFlat
#:         buy()
#:     else
#:         close()
LOTS_PROGRAM = (
    '{"callSites":[],"cells":[],"channels":[],"code":[["CALL_LIB",0,0,-1],["JUMP_F'
    'ALSE",11],["CONST",0],["CONST",0],["CONST",0],["CONST",3],["CONST",0],["CONS'
    'T",3],["CALL_LIB",1,6,-1],["POP"],["JUMP",17],["CONST",0],["CONST",0],["CONS'
    'T",0],["CONST",3],["CALL_LIB",2,4,-1],["POP"],["HALT"]],"compiler":{"name":'
    '"openscript","version":"0.5.0"},"consts":[["z",null],["b",false],["b",true'
    '],["s",""]],"debug":{"fnPos":[],"names":{"cells":[],"channels":[],"series'
    '":[],"slots":[]},"pos":[[0,3,4],[1,3,1],[2,4,5],[10,3,1],[11,6,5]],"retain":false'
    '},"frame":{"slots":0},"functions":[],"inputs":[],"lib":{"functions":[{"arit'
    'y":0,"effect":"none","name":"pos.isFlat","state":false},{"arity":6,"effect'
    '":"order","name":"buy","state":false},{"arity":4,"effect":"order","name"'
    ':"close","state":false}],"manifest":1},"limits":{"history":null,"loops":2000'
    '000},"loops":[],"meta":{"format":"price","group":"","kind":"strategy","'
    'onUnconfirmed":false,"overlay":true,"precision":4,"range":null,"scale":"right"'
    ',"short":"Lots","strategy":{"capital":100000,"closeOnSessionEnd":false,"commi'
    'ssion":0,"commissionType":"perTrade","currency":"","fillOn":"nextOpen","pr'
    'oduct":"intraday","pyramiding":1,"qty":2,"qtyType":"lots","slippage":0},"t'
    'itle":"Lots"},"openscript":{"format":"1.1","language":1},"outputs":{"alert'
    's":[],"background":null,"barColor":null,"fills":[],"levels":[],"markers":[],"'
    'plots":[],"tables":[]},"requests":[],"requires":["core.1","orders"],"series"'
    ':[],"source":{"file":"lots.oscript","hash":"sha256:85aecced0fe3fd868e2b1ed37964'
    '9137c341d9007497c47d21b1482d19c6a745","lines":7},"states":[]}'
)

#: Compiled from:
#:
#:     version 1
#:     strategy("Clock", overlay = true, qty = 1)
#:     if date.hour(time) == 9 and date.minute(time) == 15
#:         buy()
#:     if date.hour(time) == 9 and date.minute(time) == 20
#:         close()
CLOCK_PROGRAM = (
    '{"callSites":[],"cells":[],"channels":[],"code":[["SLOAD",0],["CALL_LIB",1,0'
    ',-1],["CALL_LIB",0,2,-1],["CONST",3],["EQ"],["AND_SHORT",12],["SLOAD",0],["CA'
    'LL_LIB",1,0,-1],["CALL_LIB",2,2,-1],["CONST",4],["EQ"],["AND"],["JUMP_FALSE",'
    '21],["CONST",0],["CONST",0],["CONST",0],["CONST",5],["CONST",0],["CONST",5],'
    '["CALL_LIB",3,6,-1],["POP"],["SLOAD",0],["CALL_LIB",1,0,-1],["CALL_LIB",0,2,-1'
    '],["CONST",3],["EQ"],["AND_SHORT",33],["SLOAD",0],["CALL_LIB",1,0,-1],["CALL_'
    'LIB",2,2,-1],["CONST",6],["EQ"],["AND"],["JUMP_FALSE",40],["CONST",0],["CONS'
    'T",0],["CONST",0],["CONST",5],["CALL_LIB",4,4,-1],["POP"],["HALT"]],"compile'
    'r":{"name":"openscript","version":"0.5.0"},"consts":[["z",null],["b",fals'
    'e],["b",true],["n",9],["n",15],["s",""],["n",20]],"debug":{"fnPos":[],"'
    'names":{"cells":[],"channels":[],"series":["time"],"slots":[]},"pos":[[0,3,'
    "14],[1,3,4],[3,3,23],[4,3,20],[5,3,25],[6,3,41],[7,3,29],[9,3,50],[10,3,47],[11,3,25],[1"
    "2,3,1],[13,4,5],[21,5,14],[22,5,4],[24,5,23],[25,5,20],[26,5,25],[27,5,41],[28,5,29],[30"
    ',5,50],[31,5,47],[32,5,25],[33,5,1],[34,6,5]],"retain":false},"frame":{"slots":0},'
    '"functions":[],"inputs":[],"lib":{"functions":[{"arity":2,"effect":"none",'
    '"name":"date.hour","state":false},{"arity":0,"effect":"none","name":"char'
    't.timezone","state":false},{"arity":2,"effect":"none","name":"date.minute",'
    '"state":false},{"arity":6,"effect":"order","name":"buy","state":false},{"'
    'arity":4,"effect":"order","name":"close","state":false}],"manifest":1},"li'
    'mits":{"history":null,"loops":2000000},"loops":[],"meta":{"format":"price",'
    '"group":"","kind":"strategy","onUnconfirmed":false,"overlay":true,"precisio'
    'n":4,"range":null,"scale":"right","short":"Clock","strategy":{"capital":1'
    '00000,"closeOnSessionEnd":false,"commission":0,"commissionType":"perTrade","cur'
    'rency":"","fillOn":"nextOpen","product":"intraday","pyramiding":1,"qty":1'
    ',"qtyType":"units","slippage":0},"title":"Clock"},"openscript":{"format":"'
    '1.1","language":1},"outputs":{"alerts":[],"background":null,"barColor":null,"'
    'fills":[],"levels":[],"markers":[],"plots":[],"tables":[]},"requests":[],"re'
    'quires":["core.1","orders"],"series":[{"field":"time","id":0,"kind":"bar'
    '","name":"time"}],"source":{"file":"clock.oscript","hash":"sha256:a32bc771'
    '28eadaf52434fd9be10e1dfac6f68e75f6c5cb39e4c7d70d1bc9c764","lines":7},"states":[]}'
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def at(day: date, hour: int, minute: int, zone: str = PLATFORM_ZONE) -> int:
    """A wall clock reading in a zone, as the epoch milliseconds a bar opens at."""
    moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(zone))
    return int(moment.timestamp() * 1000)


def rows_at(times, price=100.0):
    return [(one, price, price + 1, price - 1, price, 10.0) for one in times]


def minutes(day: date, hour: int, first: int, last: int):
    return [at(day, hour, one) for one in range(first, last + 1)]


class Platform:
    """The platform client: history a bar at a time, and fills for what was sent.

    An order is reported filled for exactly the quantity it was sent with, which
    is what the order book says of a whole fill. That is what lets a test see a
    close sized from the fills rather than from the script's own number.
    """

    def __init__(self, rows, first=3):
        self.rows = rows
        self.sent = []
        self.symbols = 0
        self._shown = first

    def symbol(self, **_ignored):
        self.symbols += 1
        return {"status": "success", "data": {"tick_size": 0.05, "lotsize": 1}}

    def history(self, **_ignored):
        answered = Candles(self.rows[: self._shown])
        self._shown = min(self._shown + 1, len(self.rows))
        return answered

    def placeorder(self, **kwargs):
        self.sent.append(kwargs)
        return {"status": "success", "orderid": f"O{len(self.sent)}"}

    def orderstatus(self, order_id, **_ignored):
        sent = self.sent[int(order_id[1:]) - 1]
        return {
            "status": "success",
            "data": {
                "order_status": "complete",
                "quantity": sent["quantity"],
                "average_price": 100.0,
            },
        }

    def cancelorder(self, **_ignored):
        return {"status": "success"}


def handed_facts(timezone=PLATFORM_ZONE, lot=25, session=None, today=None, tick=0.05):
    """What the service hands a run, shaped as the facts service answers."""
    instrument = {
        "exchange": "EXCH1",
        "timezone": timezone,
        "tickSize": tick,
        "instrumentType": "future",
        "hasVolume": True,
        "hasOpenInterest": True,
    }
    if lot is not None:
        instrument["lotSize"] = lot
    if session is not None:
        instrument["session"] = session
    return {"symbol": "SYM1", "contractFound": True, "instrument": instrument, "today": today}


def recording(serving_class):
    """The engine's own library seam, noting the bar facts stated before each execution."""

    class Recording(serving_class):
        def __init__(self, book=None):
            super().__init__(book)
            self.seen = []

        def at_bar(self, facts, first):
            self.seen.append(dict(facts))
            super().at_bar(facts, first)

    return Recording


def real_engine():
    """The engine this server runs, with its seam noting what it is told."""
    engine = runner.Engine()
    engine.Serving = recording(engine.Serving)
    return engine


def session_on(program, platform, monkeypatch, facts=None, settings=None, timezone=PLATFORM_ZONE):
    if facts is None:
        monkeypatch.delenv("OPENSCRIPT_INSTRUMENT", raising=False)
    else:
        monkeypatch.setenv("OPENSCRIPT_INSTRUMENT", json.dumps(facts))
    monkeypatch.setenv("OPENSCRIPT_INPUTS", json.dumps(settings or {}))
    return runner.Session(real_engine(), options_for(timezone=timezone), program, platform)


def drive(session, polls=60):
    for _ in range(polls):
        if session.cycle() is not None:
            break
    return session


def actions(platform):
    return [(one["action"], one["quantity"]) for one in platform.sent]


def recorded_instruments(session):
    """Every instrument record the engine is handed, from here on."""
    seen = []
    real = session.run.execute_bar

    def execute_bar(index, bar, state, supplied=None, instrument=None, now=None):
        seen.append(json.loads(json.dumps(instrument)))
        return real(index, bar, state, supplied=supplied, instrument=instrument, now=now)

    session.run.execute_bar = execute_bar
    return seen


@pytest.fixture(autouse=True)
def engine_calendar_restored():
    """Give the engine its own two zone functions back after every test.

    The runner puts the host's reader into the engine's calendar module, which
    is right in the strategy's own process and would otherwise leak from one
    test into the next here.
    """
    fields_in, instant_of = engine_calendar.fields_in, engine_calendar.instant_of
    yield
    engine_calendar.fields_in, engine_calendar.instant_of = fields_in, instant_of


# ---------------------------------------------------------------------------
# 1. What used to be refused now loads and answers on the right bar
# ---------------------------------------------------------------------------


def test_a_script_reading_the_clock_trades_on_the_instrument_s_own_clock(monkeypatch):
    """``date.hour`` and ``date.minute`` read in Asia/Kolkata, not refused and not UTC.

    The program buys when the clock says 09:15 and closes when it says 09:20.
    The bars run from 09:10 to 09:24 on the platform's clock, which is 03:40 to
    03:54 in UTC, so a run reading UTC never sees either minute and sends
    nothing. The wrong implementations this catches: the refusal it used to
    make, a seam that does not serve the calendar calls (refused at load with
    OS6004), and a reader that answers in UTC.
    """
    platform = Platform(rows_at(minutes(REGULAR_WEDNESDAY, 9, 10, 24)))

    drive(session_on(CLOCK_PROGRAM, platform, monkeypatch, handed_facts(lot=1)))

    assert actions(platform) == [("BUY", 1), ("SELL", 1)]


def test_session_is_in_reads_the_bar_s_own_open_time(monkeypatch):
    """``session.isIn`` needs the bar's time as a fact, and the zone to read it in.

    It reads the time from the bar facts the host states, and the runner stated
    none, so it was absent on every bar whatever the zone. The window is the
    script's own, 09:15 to 09:16.
    """
    platform = Platform(rows_at(minutes(REGULAR_WEDNESDAY, 9, 10, 24)))

    drive(session_on(WINDOW_PROGRAM, platform, monkeypatch, handed_facts(lot=1)))

    assert actions(platform) == [("BUY", 1)]


def test_a_written_time_is_read_on_the_instrument_s_clock(monkeypatch):
    """A time typed into the settings is the market's 09:15, not UTC's.

    Read as UTC, ``2026-09-23 09:15`` is five and a half hours after the bar the
    trader meant, which never comes in these bars, and the script never acts.
    """
    platform = Platform(rows_at(minutes(REGULAR_WEDNESDAY, 9, 10, 24)))

    drive(
        session_on(
            TIME_INPUT_PROGRAM,
            platform,
            monkeypatch,
            handed_facts(lot=1),
            settings={"start": "2026-09-23 09:15"},
        )
    )

    assert actions(platform) == [("BUY", 1)]


def test_the_first_bar_of_each_session_is_stated_and_acted_on(monkeypatch):
    """``session.isFirstBar`` is stated from the session, in the session's zone.

    Two days of bars: the end of one session, the minutes before the next one
    opens, and its opening. The fact has to be true on the first bar inside each
    session and false everywhere else, including the bars before the open,
    which are outside every session. The program buys on a first bar, and only
    the second session's first bar comes after the history replay, so exactly
    one order goes out.
    """
    times = minutes(REGULAR_TUESDAY, 13, 55, 59) + [at(REGULAR_TUESDAY, 14, 0)]
    times += minutes(REGULAR_WEDNESDAY, 9, 58, 59) + minutes(REGULAR_WEDNESDAY, 10, 0, 3)
    platform = Platform(rows_at(times))

    session = drive(
        session_on(FIRST_BAR_PROGRAM, platform, monkeypatch, handed_facts(session=MADE_UP_SESSION))
    )

    stated = {}
    for one in session.serving.seen:
        stated[int(one["time"])] = one[session.engine.session_first]
    opened = {at(REGULAR_TUESDAY, 13, 55), at(REGULAR_WEDNESDAY, 10, 0)}
    assert {when for when, first in stated.items() if first} == opened
    assert actions(platform) == [("BUY", 1)]


def test_a_strategy_sized_in_lots_is_sent_in_units_and_converted_once(monkeypatch):
    """Two lots of twenty five go out as fifty, and the close of them as fifty.

    The engine hands an entry over in lots and never converts it, and hands a
    close it worked out from the fills over in units. The wrong implementations
    this catches: the refusal it used to make; an entry sent as the bare count
    of lots, which is a twenty fifth of the position meant; and a close
    multiplied a second time, which sells twenty five times what is held.
    """
    platform = Platform(rows_at(minutes(REGULAR_WEDNESDAY, 9, 10, 16)))

    session = drive(session_on(LOTS_PROGRAM, platform, monkeypatch, handed_facts(lot=25)))

    assert session.lot_size == 25
    assert actions(platform)[:2] == [("BUY", 50), ("SELL", 50)]
    assert {quantity for _, quantity in actions(platform)} == {50}


# ---------------------------------------------------------------------------
# 2. What still refuses, and why
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("call", ["exit", "order.bracket"])
def test_a_stop_and_target_is_still_refused_when_everything_else_is_readable(call, monkeypatch):
    """The engine hands a bracket over; this runner's order mapping cannot send one.

    Kept whatever the zone and the session, because the reason is not a missing
    fact: a stop and a target resting together need one call that cancels the
    other when one fills, which the platform does not have, and an entry sent
    without them is a position with nothing protecting it. The program also
    reads the clock and the session, which used to be refused first and are
    now answered, so the refusal left standing is seen to be this one.
    """
    raw = strategy_program()
    raw["lib"]["functions"] = [
        {"name": "date.hour"},
        {"name": "session.isFirstBar"},
        {"name": "buy"},
        {"name": call},
    ]
    engine = real_engine()
    engine.load_text = lambda *args, **kwargs: SimpleNamespace(
        run=SimpleNamespace(program=SimpleNamespace(raw=raw)), diagnostic=None
    )
    monkeypatch.setenv("OPENSCRIPT_INSTRUMENT", json.dumps(handed_facts(session=MADE_UP_SESSION)))

    with pytest.raises(runner.Refusal) as refused:
        runner.Session(engine, options_for(), json.dumps(raw), Platform([]))

    assert call in str(refused.value)
    assert "nothing protecting it" in str(refused.value)


def test_a_clock_in_a_zone_this_server_cannot_read_is_still_refused(monkeypatch):
    """A zone the database does not hold would answer absence on every bar."""
    platform = Platform([])

    with pytest.raises(runner.Refusal) as refused:
        session_on(CLOCK_PROGRAM, platform, monkeypatch, handed_facts(timezone="Region/City"))

    said = str(refused.value)
    assert "date.hour" in said
    assert "Region/City" in said
    assert platform.symbols == 0, "the run reached the platform before it refused"


def test_a_written_time_in_a_zone_this_server_cannot_read_is_still_refused(monkeypatch):
    """Refused naming the calendar's zone, which is the one the time would be read in."""
    with pytest.raises(runner.Refusal) as refused:
        session_on(
            TIME_INPUT_PROGRAM, Platform([]), monkeypatch, handed_facts(timezone="Region/City")
        )

    assert "written time" in str(refused.value)
    assert "Region/City" in str(refused.value)


def test_a_seam_that_will_not_serve_the_calendar_refuses_by_name(monkeypatch):
    """An engine whose seam is shaped differently is refused in a sentence, not a code."""
    engine = real_engine()
    engine.join_calendar = lambda serving: False
    monkeypatch.setenv("OPENSCRIPT_INSTRUMENT", json.dumps(handed_facts()))
    monkeypatch.setenv("OPENSCRIPT_INPUTS", "{}")

    with pytest.raises(runner.Refusal) as refused:
        runner.Session(engine, options_for(), CLOCK_PROGRAM, Platform([]))

    assert "date.hour" in str(refused.value)
    assert "does not answer those calls" in str(refused.value)
    assert runner.Engine().join_calendar(SimpleNamespace()) is False


def test_a_session_fact_is_still_refused_where_no_session_is_known(monkeypatch):
    """Where the calendar holds no session the fact is absent on every bar.

    And a run the platform could not read the details for is told to start
    again, which is the action that helps, rather than to change its exchange.
    """
    with pytest.raises(runner.Refusal) as none_held:
        session_on(FIRST_BAR_PROGRAM, Platform([]), monkeypatch, handed_facts(session=None))
    assert "holds no trading session" in str(none_held.value)

    with pytest.raises(runner.Refusal) as none_read:
        session_on(FIRST_BAR_PROGRAM, Platform([]), monkeypatch, facts=None)
    assert "Start it again" in str(none_read.value)


@pytest.mark.parametrize("unit", ["cash", "equityPercent"])
def test_a_quantity_in_money_is_still_refused(unit, monkeypatch):
    """Money becomes units only at a fill price and an account balance nobody has yet.

    Kept with a lot size in the record, which is what lets lots through, so the
    refusal is seen to be about the unit and not about a missing fact.
    """
    raw = strategy_program()
    raw["meta"]["strategy"]["qtyType"] = unit
    monkeypatch.setenv("OPENSCRIPT_INSTRUMENT", json.dumps(handed_facts(lot=25)))
    monkeypatch.setenv("OPENSCRIPT_INPUTS", "{}")

    with pytest.raises(runner.Refusal) as refused:
        runner.Session(stand_in_engine(raw), options_for(), json.dumps(raw), Platform([]))

    assert unit in str(refused.value)
    assert "units or in lots" in str(refused.value)


@pytest.mark.parametrize(
    ("lot", "said"),
    [(None, "not known on this server"), (0.5, "does not come to a whole number")],
)
def test_lots_with_no_whole_lot_to_convert_by_are_still_refused(lot, said, monkeypatch):
    with pytest.raises(runner.Refusal) as refused:
        session_on(LOTS_PROGRAM, Platform([]), monkeypatch, handed_facts(lot=lot))

    assert said in str(refused.value)


# ---------------------------------------------------------------------------
# 3. The record the engine is handed carries the calendar's window
# ---------------------------------------------------------------------------


@pytest.fixture
def calendar(tmp_path, monkeypatch):
    """The market calendar on its own tables, seeded by its own functions."""
    import database.market_calendar_db as mc

    engine = create_db_engine(f"sqlite:///{(tmp_path / 'calendar.db').as_posix()}")
    held = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    monkeypatch.setattr(mc, "engine", engine)
    monkeypatch.setattr(mc, "db_session", held)
    previous_query = mc.Base.__dict__["query"]
    mc.Base.query = held.query_property()
    try:
        mc.Base.metadata.create_all(engine)
        mc.clear_market_calendar_cache()
        mc.seed_holidays_2026()
        mc.seed_market_timings()
        facts_service.clear_instrument_facts_cache()
        yield mc
    finally:
        facts_service.clear_instrument_facts_cache()
        mc.clear_market_calendar_cache()
        mc.Base.query = previous_query
        held.remove()
        engine.dispose()


@pytest.fixture
def contracts(monkeypatch):
    master = MasterContract()
    master.add("SYM1", "NSE", "EQ", lotsize=1, tick_size=0.05)
    monkeypatch.setattr(facts_service, "get_symbol_info", master)
    return master


def test_a_regular_day_hands_the_engine_the_calendar_s_regular_window(
    calendar, contracts, monkeypatch
):
    """The facts service's record, read by the service, reaches every execution."""
    text = service._instrument_facts_text("SYM1", "NSE", REGULAR_WEDNESDAY, "probe")
    read = json.loads(text)
    monkeypatch.setenv("OPENSCRIPT_INSTRUMENT", text)
    monkeypatch.setenv("OPENSCRIPT_INPUTS", "{}")
    platform = Platform(rows_at(minutes(REGULAR_WEDNESDAY, 9, 10, 20)))
    session = runner.Session(
        real_engine(), options_for(exchange="NSE"), FIRST_BAR_PROGRAM, platform
    )
    handed = recorded_instruments(session)

    drive(session)

    assert handed, "no bar was executed"
    expected = {
        "symbol": "SYM1",
        "exchange": "NSE",
        "interval": "1m",
        "timezone": calendar.IST.zone,
        "tickSize": 0.05,
        "lotSize": 1,
        "instrumentType": "equity",
        "hasVolume": True,
        "hasOpenInterest": False,
        "session": read["instrument"]["session"],
    }
    assert all(one == expected for one in handed)
    assert expected["session"]["days"] == [1, 2, 3, 4, 5]


def test_a_special_session_day_hands_the_engine_that_day_s_own_window(
    calendar, contracts, monkeypatch
):
    """On Muhurat Sunday the record states the calendar's window for that day.

    And the bars of the days before it, which the run is replayed on, are read
    against the regular window rather than against a Sunday evening one, so the
    first bar of Friday's session and the first bar of Sunday's special session
    are both first bars. Read against the special window alone, every Friday
    bar would be outside a session.
    """
    text = service._instrument_facts_text("SYM1", "NSE", MUHURAT_SUNDAY, "probe")
    read = json.loads(text)
    special = read["today"]["session"]
    regular = read["instrument"]["session"]
    assert read["today"]["isSpecial"] is True
    assert special != regular

    friday_open = at(FRIDAY_BEFORE_MUHURAT, *map(int, regular["start"].split(":")))
    sunday_open = at(MUHURAT_SUNDAY, *map(int, special["start"].split(":")))
    times = [friday_open - 60_000] + [friday_open + one * 60_000 for one in range(3)]
    times += [sunday_open - 60_000] + [sunday_open + one * 60_000 for one in range(4)]
    monkeypatch.setenv("OPENSCRIPT_INSTRUMENT", text)
    monkeypatch.setenv("OPENSCRIPT_INPUTS", "{}")
    platform = Platform(rows_at(times), first=5)
    session = runner.Session(
        real_engine(), options_for(exchange="NSE"), FIRST_BAR_PROGRAM, platform
    )
    handed = recorded_instruments(session)

    drive(session)

    assert handed and all(one["session"] == special for one in handed)
    assert special["days"] == [MUHURAT_SUNDAY.isoweekday()]
    first = {int(one["time"]) for one in session.serving.seen if one[session.engine.session_first]}
    assert first == {friday_open, sunday_open}
    assert actions(platform) == [("BUY", 1)], "the special session's first bar was acted on"


@pytest.fixture
def quiet_service(tmp_path, monkeypatch):
    """The service's files and registries, all belonging to this test."""
    monkeypatch.setattr(run_config, "CONFIG_FILE", tmp_path / "strategies" / "configs.json")
    monkeypatch.setattr(running, "STATE_FILE", tmp_path / "strategies" / "running.json")
    monkeypatch.setattr(commands, "COMMAND_FILE", tmp_path / "strategies" / "commands.json")
    monkeypatch.setattr(service, "LOGS_DIR", tmp_path / "log" / "strategies")
    monkeypatch.setattr(service, "RUNNING_RUNS", {})
    monkeypatch.setattr(service, "STOPPING_RUNS", set())
    monkeypatch.setattr(service, "STARTING_RUNS", set())
    return service


def child_that_prints(tmp_path, monkeypatch, what=""):
    """A child that writes one environment value into its log and stays alive."""
    script = tmp_path / "child.py"
    script.write_text(
        "import os, sys, time\n"
        f"sys.stdout.write('HANDED ' + os.environ.get('{what or 'OPENSCRIPT_INSTRUMENT'}', '')"
        " + chr(10))\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "RUNNER_SCRIPT", script)
    return script


def handed_to(run_id, within=30.0):
    import time

    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        for one in service.logs_for(run_id):
            for line in one.read_text(encoding="utf-8").splitlines():
                if line.startswith("HANDED "):
                    return line[len("HANDED ") :]
        time.sleep(0.1)
    raise AssertionError("the run never wrote what it was handed")


def kill_children(script):
    for one in psutil.Process().children(recursive=True):
        try:
            if str(script) in " ".join(one.cmdline()):
                one.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def test_a_start_on_a_special_day_hands_the_child_that_day_s_window(
    calendar, contracts, quiet_service, analyzer, tmp_path, monkeypatch
):
    """The whole hand-over: the service reads the calendar, the child's record carries it.

    Started on Muhurat Sunday by the real service, through the real settings,
    into a real child process that writes what it was handed. What it was handed
    is then what a run builds its record from.
    """
    script = child_that_prints(tmp_path, monkeypatch)
    monkeypatch.setattr(
        service, "_ist_now", lambda: service.IST.localize(datetime(2026, 11, 8, 17, 0))
    )
    saved, said = run_config.write_run_config("turn.oscript", "SYM1", "NSE", "1m")
    assert saved, said
    deployment = next(iter(run_config.all_run_configs()))

    ok, message = service.start_run(deployment)
    try:
        assert ok, message
        text = handed_to(deployment)
    finally:
        service.stop_run(deployment)
        kill_children(script)

    read = json.loads(text)
    assert read["today"]["date"] == MUHURAT_SUNDAY.isoformat()
    monkeypatch.setenv("OPENSCRIPT_INSTRUMENT", text)
    monkeypatch.setenv("OPENSCRIPT_INPUTS", "{}")
    session = runner.Session(
        real_engine(), options_for(exchange="NSE"), FIRST_BAR_PROGRAM, Platform([])
    )
    assert session.instrument["session"] == read["today"]["session"]
    assert session.instrument["timezone"] == calendar.IST.zone


# ---------------------------------------------------------------------------
# 3b. The reader the host supplies, held to this server's own database
# ---------------------------------------------------------------------------


def reader():
    """A reader over the engine's own calendar module, as the runner builds one."""
    from openscript import civil, zones

    return CalendarReader(
        engine_calendar,
        zones.named,
        zones.READABLE,
        civil.fields_at,
        civil.instant_at,
        civil.whole_instant,
        civil.MAX_INSTANT,
    )


def utc_ms(year, month, day, hour, minute):
    return at(date(year, month, day), hour, minute, zone="UTC")


def test_the_reader_reads_a_zone_as_the_database_does():
    held = reader()
    instant = at(REGULAR_WEDNESDAY, 9, 15)

    fields = held.fields_in(instant, PLATFORM_ZONE)

    assert (fields.year, fields.month, fields.day, fields.hour, fields.minute) == (
        2026,
        9,
        23,
        9,
        15,
    )
    assert held.fields_in(instant, "Region/City") is None, "a zone nobody holds is absent"
    assert held.fields_in(instant, "IST") is None, "an abbreviation is refused on every engine"


def test_a_skipped_and_a_repeated_reading_resolve_as_stdlib_12_2_settles_them():
    """A skipped reading is the instant it would have been; a repeated one the first of two.

    The platform's own zone changes its clock for neither, and a script may
    name one that does.
    """
    from openscript.civil import Civil

    held = reader()
    zone = "America/New_York"

    skipped = held.instant_of(Civil(2026, 3, 8, 2, 30, 0), zone)
    repeated = held.instant_of(Civil(2026, 11, 1, 1, 30, 0), zone)

    assert skipped == utc_ms(2026, 3, 8, 7, 30), "read with the offset before the change"
    assert repeated == utc_ms(2026, 11, 1, 5, 30), "the first of the two"


def test_a_written_time_is_placed_in_the_zone_it_was_written_for():
    held = reader()

    read = held.time_reader(PLATFORM_ZONE, runner.Engine().utc_time)

    assert read("2026-09-23 09:15") == at(REGULAR_WEDNESDAY, 9, 15)
    assert read("not a time") is None


def test_a_reader_the_engine_does_not_reach_is_taken_back_out():
    """Put in place and then checked through the engine's own calls, never trusted.

    The wrong implementation this catches is one that reports success because it
    assigned the functions, on an engine whose calendar calls no longer go
    through them: every calendar read would be answered by the engine's own UTC
    arithmetic or by nothing, and the run would start as though it could read
    the clock.
    """
    own = SimpleNamespace(
        fields_in=engine_calendar.fields_in,
        instant_of=engine_calendar.instant_of,
        field_of=lambda *args: 0.0,
        start_of=lambda *args: 0.0,
    )
    from openscript import civil, zones

    held = CalendarReader(
        own,
        zones.named,
        zones.READABLE,
        civil.fields_at,
        civil.instant_at,
        civil.whole_instant,
        civil.MAX_INSTANT,
    )

    assert held.install(PLATFORM_ZONE) is False
    assert own.fields_in is engine_calendar.fields_in, "the engine's own function was not put back"
    assert held.install("UTC") is True, "the zone the engine reads needs no reader"


# ---------------------------------------------------------------------------
# 4. A run's books are read from the side it traded on
# ---------------------------------------------------------------------------


@pytest.fixture
def analyzer(monkeypatch):
    """The platform's analyzer toggle, which a test moves by hand."""
    import database.settings_db as settings_db

    toggle = SimpleNamespace(on=False)
    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: toggle.on)
    return toggle


@pytest.fixture
def books_read(monkeypatch):
    """Every side a book was read from, through the real books route."""
    sides = []

    def orderbook(name, api_key, mode):
        sides.append(mode)
        return {"status": "success", "data": {"orders": [], "statistics": {}}}

    monkeypatch.setattr(books, "orderbook", orderbook)
    monkeypatch.setattr(runner_routes, "_api_key", lambda: "key")
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: True)
    application = Flask(__name__)
    application.config["TESTING"] = True
    application.secret_key = "test-only"
    application.register_blueprint(runner_routes.openscript_runner_bp)
    return SimpleNamespace(sides=sides, client=application.test_client())


@pytest.mark.parametrize(("started_on", "moved_to"), [(True, False), (False, True)])
def test_the_books_follow_the_side_the_run_started_on(
    started_on, moved_to, quiet_service, analyzer, books_read, tmp_path, monkeypatch
):
    """THE DEFECT. The toggle moves; the orders the run placed did not.

    A run started in analyzer mode sent its orders to the sandbox. Read from the
    live side once somebody switched the platform back, its book is empty and
    its strategy looks as if it never traded; the other way round, a live
    strategy's book shows the sandbox's orders. The side is noted when the run
    starts, kept beside the deployment's settings once it stops, and read from
    there both while it runs and after.
    """
    monkeypatch.setattr(service, "_instrument_facts_text", lambda *args: "")
    script = child_that_prints(tmp_path, monkeypatch)
    saved, said = run_config.write_run_config("turn.oscript", "SYM1", "EXCH1", "1m")
    assert saved, said
    deployment = next(iter(run_config.all_run_configs()))
    side = "sandbox" if started_on else "live"

    analyzer.on = started_on
    ok, message = service.start_run(deployment)
    try:
        assert ok, message
        assert service.status_of(deployment)["mode"] == side
        analyzer.on = moved_to

        while_running = books_read.client.get(f"/openscript/runner/orderbook/{deployment}")
        assert while_running.status_code == 200
    finally:
        service.stop_run(deployment)
        kill_children(script)

    after_stopping = books_read.client.get(f"/openscript/runner/orderbook/{deployment}")
    assert after_stopping.status_code == 200
    assert books_read.sides == [side, side]
    assert run_config.run_mode_of(deployment) == side


def test_an_edit_that_keeps_the_deployment_keeps_the_side_it_traded_on(quiet_service):
    saved, said = run_config.write_run_config("turn.oscript", "SYM1", "EXCH1", "1m")
    assert saved, said
    deployment = next(iter(run_config.all_run_configs()))
    assert run_config.record_run_mode(deployment, "sandbox")

    saved, said = run_config.write_run_config(
        "turn.oscript", "SYM1", "EXCH1", "1m", inputs={"length": 20}, deployment=deployment
    )

    assert saved, said
    assert run_config.run_mode_of(deployment) == "sandbox"


def test_a_side_nobody_named_is_not_read(quiet_service, analyzer, books_read):
    """A hand edited word that is not a side falls back to the platform's setting.

    Reading the live book because a stored value was not ``sandbox`` would be
    choosing a side nobody named.
    """
    saved, said = run_config.write_run_config("turn.oscript", "SYM1", "EXCH1", "1m")
    assert saved, said
    deployment = next(iter(run_config.all_run_configs()))
    stored = json.loads(run_config.CONFIG_FILE.read_text(encoding="utf-8"))
    stored[deployment]["mode"] = "paper"
    run_config.CONFIG_FILE.write_text(json.dumps(stored), encoding="utf-8")
    analyzer.on = True

    assert not run_config.record_run_mode(deployment, "paper")
    assert run_config.run_mode_of(deployment) == ""
    books_read.client.get(f"/openscript/runner/orderbook/{deployment}")
    assert books_read.sides == ["sandbox"]
