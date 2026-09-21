"""The runner that executes a compiled OpenScript program, and the service that starts it.

A trading runner cannot be tested by trading, so what is tested here is the part
that can be tested honestly, and the file says plainly what that is.

**What these prove.** That a script with no compiled program refuses to start and
names itself rather than trying to compile anything. That a bar which is still
moving is executed at one index however many times it moves, and that the state
goes back between those executions, which is the defect that makes a live run
disagree with its own backtest. That nothing is sent for a bar that has not
closed, and nothing is sent at all while the run is replaying history. That a
diagnostic stops that one run and lands in its log. That starting a run hands the
worker back immediately, that stopping one actually reaps the process, and that
the log goes where this platform already keeps its strategy logs.

**What they do not prove is in the report beside them, not hidden here.** No test
in this file places an order, reaches a broker, or proves anything about what
happens to a real position. The order path is exercised against a stand-in, and
what the stand-in proves is that this runner calls the platform's own client and
passes nothing that could take it past the analyzer toggle.

Two kinds of test sit side by side. Most drive the runner against a stand-in
engine, so they run wherever the suite runs and they pin the driver's own
contract exactly. One drives the real engine over a real compiled program and is
skipped where the engine is not installed, which is every checkout of this
repository today: there is no Python engine in it yet.
"""

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import types
from datetime import UTC, datetime
from pathlib import Path

import psutil
import pytest

import services.openscript_runner_service as service

REPOSITORY = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPOSITORY / "strategies" / "scripts" / "openscript_runner.py"
SERVICE_PATH = REPOSITORY / "services" / "openscript_runner_service.py"


def _syntax_of(path: Path):
    """One file as its syntax tree.

    Two of the tests below rule out a line existing at all, and reading for it in
    the text finds the sentences explaining why it must not. The tree carries the
    code and not the prose about it, so it answers the question that was asked.
    """
    return ast.parse(path.read_text(encoding="utf-8"))


def _plain_imports(tree) -> set[str]:
    """Every module reached by ``import x``, by its top-level name."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for one in node.names:
                found.add(one.name.split(".")[0])
    return found


def _named_imports(tree) -> dict[str, set[str]]:
    """Every ``from a.b import c``, as the module against what it brought in."""
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.setdefault(node.module, set()).update(one.name for one in node.names)
    return found


def _attributes_of(tree, module: str) -> set[str]:
    """Every ``module.something`` written in this file."""
    found = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == module
        ):
            found.add(node.attr)
    return found


def _load_runner():
    """The runner module, loaded from its path.

    It lives under ``strategies/scripts`` with the trader's own scripts rather
    than in a package, because that is the folder this platform runs a strategy
    out of and the folder a deployment keeps a trader's own files in. So it is
    loaded the way anything else would load a file.
    """
    spec = importlib.util.spec_from_file_location("openscript_runner_under_test", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


# ---------------------------------------------------------------------------
# A stand-in engine
# ---------------------------------------------------------------------------
#
# The runner asks an engine for a small, fixed set of things, and holds them on
# one object so they can be answered here. What is answered is deliberately
# mechanical: this file is testing the driver around the engine, which is the
# half that lives in this repository, and an engine that recorded nothing would
# make the driver's own contract invisible.


class StandInDiagnostic:
    def __init__(self, code="OS4002", line=7, column=5):
        self.code = code
        self.line = line
        self.column = column
        self.values = {}


class StandInEffect:
    def __init__(self, name="buy"):
        self.name = name
        self.arguments = []
        self.position = None


class StandInResult:
    def __init__(self, index, applied=(), diagnostic=None):
        self.index = index
        self.columns = []
        self.applied_channels = []
        self.applied = list(applied)
        self.alerts = []
        self.diagnostic = diagnostic


class StandInRun:
    """Records every execution, checkpoint and restore the driver asks for."""

    def __init__(self, raw, effects_from=None):
        self.program = types.SimpleNamespace(raw=raw)
        self.executions = []
        self.checkpoints = []
        self.restores = []
        self.diagnostic_at = None
        self._effects_from = effects_from

    def checkpoint(self, bar=-1):
        self.checkpoints.append(bar)
        return ("mark", bar, len(self.executions))

    def restore(self, mark):
        self.restores.append(mark)

    def declaration(self, path):
        return self.program.raw["meta"]["strategy"][path[-1]]

    def execute_bar(self, index, bar, state, supplied=None, instrument=None, now=None):
        self.executions.append(
            {
                "index": index,
                "confirmed": state.is_confirmed,
                "new": state.is_new,
                "realtime": state.is_realtime,
                "close": bar.close,
                "supplied": supplied,
            }
        )
        if self.diagnostic_at is not None and index == self.diagnostic_at:
            return StandInResult(index, diagnostic=StandInDiagnostic())
        effects = ()
        if self._effects_from is not None and index >= self._effects_from:
            effects = (StandInEffect(),)
        return StandInResult(index, applied=effects)


class StandInIntent:
    def __init__(self, intent_id, kind="place", side="buy", qty=1.0, tag=""):
        self.intent_id = intent_id
        self.kind = kind
        self.side = side
        self.qty = qty
        self.placement = types.SimpleNamespace(
            kind=kind, order_type="market", limit=None, trigger=None, tag=tag
        )


class StandInPlaced:
    def __init__(self, intents):
        self.intents = intents
        self.refusal = None


class StandInLedger:
    def __init__(self, kind="place"):
        self.options = None
        self.delivered = []
        self.settled = 0
        self._rows = []
        self._next = 1
        self._kind = kind

    def place(self, name, arguments, bar, position):
        intent = StandInIntent(self._next, kind=self._kind)
        self._next += 1
        self._rows.append(intent)
        return StandInPlaced((intent,))

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


def stand_in_engine(raw, ledger=None, effects_from=None):
    """An object shaped like the runner's own view of an engine."""
    run = StandInRun(raw, effects_from=effects_from)
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
        readable_zone="UTC",
    )
    engine.run = run
    return engine


def strategy_program(kind="strategy"):
    """The smallest program shape the runner reads fields out of."""
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
        "inputs": [],
        "lib": {"functions": []},
    }


# ---------------------------------------------------------------------------
# A stand-in platform client
# ---------------------------------------------------------------------------


class Candles:
    """What the platform's history call answers with, as the runner reads it."""

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
    """The platform SDK, recording what it was asked to do and answering plainly.

    ``repeat`` is how many polls each bar spends as the newest, still moving bar
    before the one after it appears. It is the whole point of several tests below.
    """

    def __init__(self, rows, first=3, repeat=1):
        self.rows = rows
        self.sent = []
        self.cancelled = []
        self.statuses = 0
        self._shown = first
        self._repeat = repeat
        self._left = repeat

    def symbol(self, **kwargs):
        return {"status": "success", "data": {"tick_size": 0.05, "lotsize": 1}}

    def history(self, **kwargs):
        answered = Candles(self.rows[: self._shown])
        self._left -= 1
        if self._left <= 0:
            self._left = self._repeat
            self._shown = min(self._shown + 1, len(self.rows))
        return answered

    def placeorder(self, **kwargs):
        self.sent.append(kwargs)
        return {"status": "success", "orderid": f"O{len(self.sent)}"}

    def cancelorder(self, **kwargs):
        self.cancelled.append(kwargs)
        return {"status": "success"}

    def orderstatus(self, **kwargs):
        self.statuses += 1
        return {
            "status": "success",
            "data": {"order_status": "complete", "quantity": 1, "average_price": 100.0},
        }


def bars(count=12, start=1700000000000, step=60000):
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
        "timezone": "UTC",
    }
    given.update(overrides)
    argv = []
    for name, value in given.items():
        argv += [f"--{name}", str(value)]
    return runner.parse_arguments(argv)


def drive(client, engine, polls, options=None):
    """Poll the session the given number of times, or until it says it is over."""
    session = runner.Session(engine, options or options_for(), json.dumps(strategy_program()), client)
    outcome = None
    for _ in range(polls):
        outcome = session.cycle()
        if outcome is not None:
            break
    return session, outcome


# ---------------------------------------------------------------------------
# The runner: refusing to start
# ---------------------------------------------------------------------------


@pytest.fixture
def scripts(tmp_path, monkeypatch):
    """A scripts folder this test owns, in place of the platform's."""
    folder = tmp_path / "strategies" / "openscript"
    folder.mkdir(parents=True)
    monkeypatch.setattr(runner, "SCRIPTS_DIR", folder)
    return folder


def test_a_script_with_no_compiled_program_refuses_and_names_itself(scripts):
    """The one state a runner must never quietly work around.

    A source with nothing compiled beside it is a script that has never compiled
    cleanly, and there is no compiler on this server. The wrong implementation
    this catches is the one that starts anyway and discovers it later, or worse,
    tries to read the source as though it were a program.
    """
    (scripts / "turn.oscript").write_text("version 1\n", encoding="utf-8")

    with pytest.raises(runner.Refusal) as refused:
        runner.program_text("turn.oscript")

    said = str(refused.value)
    assert "turn.oscript" in said
    assert "no compiled program" in said


def test_a_script_that_is_not_stored_at_all_says_so(scripts):
    with pytest.raises(runner.Refusal) as refused:
        runner.program_text("absent.oscript")
    assert "absent.oscript" in str(refused.value)


def test_the_runner_process_refuses_a_missing_program_and_leaves_with_a_refusal_code(tmp_path):
    """The same refusal, through the real process, the way the service starts it.

    This one runs the file rather than importing it, because a refusal that only
    works when a test calls a function is a refusal the service never sees. The
    exit code is what the service reads and the sentence is what the trader reads.
    """
    folder = tmp_path / "strategies" / "openscript"
    folder.mkdir(parents=True)
    (folder / "turn.oscript").write_text("version 1\n", encoding="utf-8")

    environment = os.environ.copy()
    environment["OPENALGO_API_KEY"] = "not-a-real-key"
    environment.pop("OPENSCRIPT_ENGINE_PATH", None)

    finished = subprocess.run(
        [
            sys.executable,
            "-u",
            str(RUNNER_PATH),
            "--script",
            "turn.oscript",
            "--symbol",
            "SYM1",
            "--exchange",
            "EXCH1",
            "--interval",
            "1m",
            "--cycles",
            "1",
        ],
        cwd=str(tmp_path),
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert finished.returncode == runner.EXIT_REFUSED
    assert "turn.oscript" in finished.stdout
    assert "no compiled program" in finished.stdout
    assert "Nothing was started and nothing was sent." in finished.stdout

    # Said out loud because it is the point: the source was right there and the
    # runner did not read it, did not try to compile it and did not start.
    assert "version 1" not in finished.stdout


def test_a_program_that_attaches_a_stop_and_a_target_is_refused_before_it_starts():
    """An entry must never go out with nothing protecting it.

    Those two calls become an order pair this runner cannot send as one piece, so
    it refuses the whole script up front. The wrong implementation this catches is
    the one that refuses at the bar instead, which arrives after the entry beside
    it has already been sent.
    """
    raw = strategy_program()
    raw["lib"]["functions"] = [{"name": "buy", "arity": 6}, {"name": "exit", "arity": 8}]
    engine = stand_in_engine(raw)

    with pytest.raises(runner.Refusal) as refused:
        runner.Session(engine, options_for(), json.dumps(raw), StandInClient(bars()))

    said = str(refused.value)
    assert "exit" in said
    assert "nothing protecting it" in said


def test_a_strategy_that_carries_a_position_overnight_asks_which_product():
    """Two products answer "overnight" here and the script cannot say which.

    Picking one would be this runner deciding how somebody's position is carried
    and margined. The wrong implementation this catches is the one that defaults.
    """
    raw = strategy_program()
    raw["meta"]["strategy"]["product"] = "overnight"
    engine = stand_in_engine(raw)

    with pytest.raises(runner.Refusal) as refused:
        runner.Session(engine, options_for(), json.dumps(raw), StandInClient(bars()))
    assert "which" in str(refused.value)

    # Named on the command line, the same script starts.
    session = runner.Session(
        engine, options_for(product="NRML"), json.dumps(raw), StandInClient(bars())
    )
    assert session.product == "NRML"


def test_a_quantity_the_script_cannot_state_in_units_is_refused():
    """A size in anything but units needs a number nobody wrote."""
    raw = strategy_program()
    raw["meta"]["strategy"]["qtyType"] = "equityPercent"
    engine = stand_in_engine(raw)

    with pytest.raises(runner.Refusal) as refused:
        runner.Session(engine, options_for(), json.dumps(raw), StandInClient(bars()))
    assert "units" in str(refused.value)


# ---------------------------------------------------------------------------
# The runner: the moving bar
# ---------------------------------------------------------------------------


def test_a_bar_that_is_still_moving_is_executed_at_one_index():
    """The defect that makes a live run disagree with its own backtest.

    The newest bar is executed again on every poll. If the index moved with the
    poll rather than with the bar, the engine would see a brand new bar each time,
    would never restore anything, and every indicator would be computed from a
    history that grew by one phantom bar per poll.

    The wrong implementation this catches is exactly that: an index taken from the
    number of executions, or from the length of the last history window, instead
    of from the number of bars that have actually closed.
    """
    client = StandInClient(bars(), first=4, repeat=3)
    engine = stand_in_engine(strategy_program())
    session, _ = drive(client, engine, polls=6)

    unconfirmed = [one for one in engine.run.executions if not one["confirmed"]]
    assert len(unconfirmed) >= 4

    # Every unconfirmed execution of one bar carries one index, and the index only
    # ever moves when a bar closes.
    by_index = {}
    for one in unconfirmed:
        by_index.setdefault(one["index"], 0)
        by_index[one["index"]] += 1
    assert max(by_index.values()) >= 3

    indices = [one["index"] for one in engine.run.executions]
    assert indices == sorted(indices)
    assert len(set(indices)) < len(indices)


def test_the_state_goes_back_before_a_moving_bar_runs_again():
    """A re-execution starts from the state the bar began with, not the last one.

    Without the restore, a script holding a running total would add to it once per
    poll, so a strategy would take a different decision purely because the trader
    left the page open longer. The wrong implementation this catches is the one
    that drops the restore and relies on the bar being executed only once.
    """
    client = StandInClient(bars(), first=4, repeat=3)
    engine = stand_in_engine(strategy_program())
    drive(client, engine, polls=5)

    assert engine.run.checkpoints, "no checkpoint was taken for a bar that was still moving"
    assert engine.run.restores, "a moving bar was executed again with nothing put back"

    # Every restore is from a mark taken at the start of a bar, and there is one
    # restore for every execution of a bar after its first.
    executions = engine.run.executions
    repeats = len(executions) - len({one["index"] for one in executions})
    assert len(engine.run.restores) == repeats


def test_the_bar_that_closes_is_executed_again_from_where_it_began():
    """A bar is decided from its opening state, whatever it did while it moved."""
    client = StandInClient(bars(), first=4, repeat=2)
    engine = stand_in_engine(strategy_program())
    drive(client, engine, polls=5)

    confirmed = [one for one in engine.run.executions if one["confirmed"]]
    moved = [one for one in engine.run.executions if not one["confirmed"]]
    moving_indices = {one["index"] for one in moved}

    # A bar that moved and then closed was executed as a closed bar too, and that
    # execution was not treated as the bar's first.
    closed_after_moving = [one for one in confirmed if one["index"] in moving_indices]
    assert closed_after_moving
    assert all(not one["new"] for one in closed_after_moving)


# ---------------------------------------------------------------------------
# The runner: what is sent, and when
# ---------------------------------------------------------------------------


def test_nothing_is_sent_while_history_is_replayed():
    """Replaying old signals into real orders would trade yesterday on today's money.

    The wrong implementation this catches is the one that starts sending from the
    first bar it executes, which is every bar the chart already held.
    """
    client = StandInClient(bars(20), first=12, repeat=1)
    engine = stand_in_engine(strategy_program(), effects_from=0)
    session = runner.Session(
        engine, options_for(), json.dumps(strategy_program()), client
    )

    session.cycle()

    replayed = [one for one in engine.run.executions if one["confirmed"]]
    assert len(replayed) >= 10, "history was not replayed at all"
    assert client.sent == [], "an order was sent for a bar that had already happened"


def test_a_bar_that_has_not_closed_sends_nothing():
    """An order goes out when a bar closes, which is what the backtest did.

    A condition true halfway through a bar and false at its close must place no
    order at all. The wrong implementation this catches is the one that routes the
    effects of an unconfirmed execution, which would send an order per poll for as
    long as the condition held.
    """
    client = StandInClient(bars(20), first=12, repeat=4)
    engine = stand_in_engine(strategy_program(), effects_from=0)
    session = runner.Session(
        engine, options_for(), json.dumps(strategy_program()), client
    )

    session.cycle()
    assert client.sent == []

    # Four more polls, all of them on the same still moving bar.
    for _ in range(3):
        session.cycle()
    assert client.sent == [], "an order was sent for a bar that had not closed"

    # The poll that closes that bar is the one that sends, and it sends once.
    session.cycle()
    assert len(client.sent) == 1


def test_an_order_carries_the_platform_s_own_words_and_no_way_past_the_toggle():
    """An order leaves as the platform's own call, and nothing opts out of anything.

    ``force_live`` is what a caller passes to bypass the analyzer toggle. Nothing
    in this runner may pass it, and nothing in it may reach broker code directly.
    Asserted against the file rather than a mock, because the thing being ruled out
    is a line existing at all.
    """
    client = StandInClient(bars(20), first=12, repeat=1)
    engine = stand_in_engine(strategy_program(), effects_from=0)
    session = runner.Session(
        engine, options_for(), json.dumps(strategy_program()), client
    )
    session.cycle()
    session.cycle()

    assert client.sent, "nothing was sent at all, so this test proves nothing"
    one = client.sent[0]
    assert one["action"] in ("BUY", "SELL")
    assert one["price_type"] == "MARKET"
    assert one["product"] == "MIS"
    assert one["symbol"] == "SYM1"
    assert one["exchange"] == "EXCH1"
    assert "force_live" not in one

    tree = _syntax_of(RUNNER_PATH)
    passed = [
        keyword.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
    ]
    assert "force_live" not in passed, "this runner passes force_live to something"
    assert "force_live" not in {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    assert "broker" not in _plain_imports(tree)
    assert not any(one.startswith("broker") for one in _named_imports(tree))


def test_a_diagnostic_stops_this_run_and_says_so_in_its_log(capsys):
    """A script that fails stops itself and nothing else, in words its author can read.

    The wrong implementation this catches is the one that logs and carries on,
    which would leave a strategy executing after the engine told it that it could
    not.
    """
    client = StandInClient(bars(20), first=12, repeat=1)
    engine = stand_in_engine(strategy_program())
    session = runner.Session(
        engine, options_for(), json.dumps(strategy_program()), client
    )
    engine.run.diagnostic_at = 5

    outcome = session.cycle()

    assert outcome == runner.EXIT_DIAGNOSTIC
    written = capsys.readouterr().out
    assert "turn.oscript" in written
    assert "OS4002" in written
    assert "Nothing further will be sent for it." in written


def test_a_history_window_that_no_longer_reaches_the_last_bar_stops_the_run(capsys):
    """A gap this runner cannot bridge is a stop, never a guess.

    The wrong implementation this catches is the one that carries on from wherever
    the newest window happens to start, silently skipping the bars in between.
    """
    rows = bars(20)
    client = StandInClient(rows, first=12, repeat=1)
    engine = stand_in_engine(strategy_program())
    session = runner.Session(
        engine, options_for(), json.dumps(strategy_program()), client
    )
    session.cycle()

    # The feed comes back holding only bars this run has never seen.
    client.rows = bars(6, start=1800000000000)
    client._shown = 6
    outcome = session.cycle()

    assert outcome == runner.EXIT_DIAGNOSTIC
    assert "cannot tell what it missed" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The runner, against the real engine
# ---------------------------------------------------------------------------


def _real_engine():
    """The engine, if this checkout has one. Most do not, and that is the point."""
    extra = os.getenv("OPENSCRIPT_ENGINE_PATH")
    if extra and extra not in sys.path:
        sys.path.insert(0, extra)
    return pytest.importorskip(
        "openscript.run",
        reason=(
            "the OpenScript engine is a separate package and is not installed here; set "
            "OPENSCRIPT_ENGINE_PATH to run this"
        ),
    )


# The canonical text of a compiled strategy, exactly as the compiler produced it.
# A real program and not one written by hand: the encoding is what a program's
# hash is taken over and what a load from text insists on, so anything shaped by
# hand here would be testing a file no engine would accept.
COMPILED_STRATEGY = (
    "{\"callSites\":[],\"cells\":[],\"channels\":[{\"defer\":false,\"id\":0,\"once\":true,\"type\":\"number\"},{\""
    "defer\":false,\"id\":1,\"once\":true,\"type\":\"number\"}],\"code\":[[\"SLOAD\",0],[\"LOAD\",0],[\"CALL_LIB\""
    ",0,2,0],[\"STORE\",2],[\"SLOAD\",0],[\"LOAD\",1],[\"CALL_LIB\",0,2,1],[\"STORE\",3],[\"LOAD\",2],[\"LOAD\""
    ",3],[\"CALL_LIB\",1,2,2],[\"AND_SHORT\",16],[\"CALL_LIB\",2,0,-1],[\"CONST\",3],[\"EQ\"],[\"AND\"],[\"JUM"
    "P_FALSE\",25],[\"CONST\",4],[\"CONST\",0],[\"CONST\",0],[\"CONST\",5],[\"CONST\",0],[\"CONST\",6],[\"CALL_"
    "LIB\",3,6,-1],[\"POP\"],[\"LOAD\",2],[\"LOAD\",3],[\"CALL_LIB\",4,2,3],[\"AND_SHORT\",33],[\"CALL_LIB\",2"
    ",0,-1],[\"CONST\",3],[\"GT\"],[\"AND\"],[\"JUMP_FALSE\",40],[\"CONST\",0],[\"CONST\",0],[\"CONST\",0],[\"CO"
    "NST\",7],[\"CALL_LIB\",5,4,-1],[\"POP\"],[\"LOAD\",2],[\"EMIT\",0],[\"LOAD\",3],[\"EMIT\",1],[\"HALT\"]],\"c"
    "ompiler\":{\"name\":\"openscript\",\"version\":\"0.4.0\"},\"consts\":[[\"z\",null],[\"b\",false],[\"b\",true]"
    ",[\"n\",0],[\"n\",1],[\"s\",\"entry\"],[\"s\",\"qty tag\"],[\"s\",\"\"]],\"debug\":{\"fnPos\":[],\"names\":{\"cells"
    "\":[],\"channels\":[\"Fast\",\"Slow\"],\"series\":[\"close\"],\"slots\":[\"fastLen\",\"slowLen\",\"fast\",\"slow"
    "\"]},\"pos\":[[0,12,12],[1,12,19],[2,12,8],[3,12,1],[4,13,12],[5,13,19],[6,13,8],[7,13,1],[8,15"
    ",12],[9,15,18],[10,15,4],[11,15,24],[12,15,28],[13,15,40],[14,15,37],[15,15,24],[16,15,1],[1"
    "7,16,15],[18,16,5],[20,16,24],[21,16,5],[25,18,14],[26,18,20],[27,18,4],[28,18,26],[29,18,30"
    "],[30,18,41],[31,18,39],[32,18,26],[33,18,1],[34,19,5],[40,21,6],[41,21,1],[42,22,6],[43,22,"
    "1]],\"retain\":false},\"frame\":{\"slots\":4},\"functions\":[],\"inputs\":[{\"default\":[\"n\",2],\"group\":"
    "\"\",\"key\":\"fastLen\",\"kind\":\"number\",\"label\":\"Fast length\",\"max\":100,\"min\":1,\"options\":null,\"s"
    "lot\":0,\"step\":null,\"tooltip\":null},{\"default\":[\"n\",4],\"group\":\"\",\"key\":\"slowLen\",\"kind\":\"num"
    "ber\",\"label\":\"Slow length\",\"max\":100,\"min\":1,\"options\":null,\"slot\":1,\"step\":null,\"tooltip\":n"
    "ull}],\"lib\":{\"functions\":[{\"arity\":2,\"effect\":\"none\",\"name\":\"ema\",\"state\":true},{\"arity\":2,\""
    "effect\":\"none\",\"name\":\"crossUp\",\"state\":true},{\"arity\":0,\"effect\":\"none\",\"name\":\"pos.size\",\""
    "state\":false},{\"arity\":6,\"effect\":\"order\",\"name\":\"buy\",\"state\":false},{\"arity\":2,\"effect\":\"n"
    "one\",\"name\":\"crossDown\",\"state\":true},{\"arity\":4,\"effect\":\"order\",\"name\":\"close\",\"state\":fal"
    "se}],\"manifest\":1},\"limits\":{\"history\":null,\"loops\":2000000},\"loops\":[],\"meta\":{\"format\":\"pr"
    "ice\",\"group\":\"\",\"kind\":\"strategy\",\"onUnconfirmed\":false,\"overlay\":true,\"precision\":2,\"range\""
    ":null,\"scale\":\"right\",\"short\":\"Turn\",\"strategy\":{\"capital\":100000,\"closeOnSessionEnd\":false,"
    "\"commission\":0,\"commissionType\":\"perTrade\",\"currency\":\"\",\"fillOn\":\"nextOpen\",\"product\":\"intr"
    "aday\",\"pyramiding\":1,\"qty\":1,\"qtyType\":\"units\",\"slippage\":0},\"title\":\"Turn\"},\"openscript\":{\""
    "format\":\"1.1\",\"language\":1},\"outputs\":{\"alerts\":[],\"background\":null,\"barColor\":null,\"fills\""
    ":[],\"levels\":[],\"markers\":[],\"plots\":[{\"channel\":0,\"color\":[0,255,255,1],\"colorChannel\":null"
    ",\"key\":\"p0\",\"lineStyle\":\"solid\",\"offset\":0,\"ohlc\":null,\"overlay\":null,\"precision\":null,\"pric"
    "eFormat\":null,\"scale\":\"right\",\"title\":\"Fast\",\"type\":\"line\",\"width\":1.5},{\"channel\":1,\"color\""
    ":[255,165,0,1],\"colorChannel\":null,\"key\":\"p1\",\"lineStyle\":\"solid\",\"offset\":0,\"ohlc\":null,\"ov"
    "erlay\":null,\"precision\":null,\"priceFormat\":null,\"scale\":\"right\",\"title\":\"Slow\",\"type\":\"line\""
    ",\"width\":1.5}],\"tables\":[]},\"requests\":[],\"requires\":[\"core.1\",\"orders\"],\"series\":[{\"field\":"
    "\"close\",\"id\":0,\"kind\":\"bar\",\"name\":\"close\"}],\"source\":{\"file\":\"turn.oscript\",\"hash\":\"sha256:"
    "f1bef5f1232a6abd1a4b828c510d399d3c57dd12233aac479c60665febb00e0c\",\"lines\":23},\"states\":[{\"fn"
    "\":0,\"id\":0},{\"fn\":0,\"id\":1},{\"fn\":1,\"id\":2},{\"fn\":4,\"id\":3}]}"
)


def test_a_moving_bar_replayed_many_times_decides_what_one_pass_decides():
    """The property the whole checkpoint argument exists for, on the real engine.

    One run sees each bar close immediately. The other sees every bar spend four
    polls moving before it closes. Both must send the same orders, in the same
    order, for the same quantities. If the state did not go back between the
    executions of a moving bar, the second run would compute from a different
    history and the two would part company at the first signal.

    **What this catches, exactly, and what it does not.** It catches a bar index
    that moves with the poll instead of with the bar, which is the defect that
    produces a run computing from a history with a phantom bar in it: broken that
    way, this goes red. It does NOT catch the removal of the driver's own restore,
    because the engine restores from its own checkpoint at the same instant, so
    that line is redundant with it. Proved by breaking both and watching only one
    of them fail. The driver's restore is pinned by the stand-in tests above, and
    the comment in the runner says the same thing rather than claiming more.
    """
    _real_engine()
    rows = bars(40)

    quick = StandInClient(rows, first=6, repeat=1)
    patient = StandInClient(rows, first=6, repeat=4)

    quick_session, _ = drive_real(quick, polls=200)
    patient_session, _ = drive_real(patient, polls=400)

    assert quick.sent, "the quick run sent nothing, so this test proves nothing"
    assert _order_shapes(quick.sent) == _order_shapes(patient.sent)


def drive_real(client, polls):
    """A session on the real engine over the compiled strategy above."""
    engine = runner.Engine()
    session = runner.Session(engine, options_for(), COMPILED_STRATEGY, client)
    outcome = None
    for _ in range(polls):
        outcome = session.cycle()
        if outcome is not None:
            break
    return session, outcome


def _order_shapes(sent):
    return [(one["action"], one["quantity"], one["price_type"], one["product"]) for one in sent]


# ---------------------------------------------------------------------------
# The service: starting, stopping and reaping
# ---------------------------------------------------------------------------


@pytest.fixture
def quiet_service(tmp_path, monkeypatch):
    """The service, with its log folder and its registry belonging to this test."""
    logs = tmp_path / "log" / "strategies"
    monkeypatch.setattr(service, "LOGS_DIR", logs)
    monkeypatch.setattr(service, "RUNNING_RUNS", {})
    monkeypatch.setattr(service, "STOPPING_RUNS", set())
    return service


@pytest.fixture
def slow_runner(tmp_path, monkeypatch, quiet_service):
    """A stand-in for the runner that stays alive until it is stopped.

    The real runner refuses in milliseconds when there is no script, which is the
    right behaviour and the wrong stand-in for a test about starting and stopping a
    long lived process.
    """
    script = tmp_path / "slow_runner.py"
    script.write_text(
        "import sys, time\n"
        "sys.stdout.write('started\\n')\n"
        "sys.stdout.flush()\n"
        # Long enough that no test here can outlast it, short enough that one left
        # behind by something else going wrong is gone within the minute.
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "RUNNER_SCRIPT", script)

    yield script

    # Whatever the test asserted, and whether or not it got as far as stopping
    # anything, nothing started here is left running. A suite that leaks a process
    # per failure is a suite nobody can run twice, and the registry is not enough
    # to go on: a test proving that a bad stop leaves the process alive does so by
    # emptying the registry while the process is still there, which is exactly the
    # case this has to catch.
    for one in psutil.Process().children(recursive=True):
        try:
            if str(script) in " ".join(one.cmdline()):
                one.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def _start(**overrides):
    given = {
        "script": "turn.oscript",
        "symbol": "SYM1",
        "exchange": "EXCH1",
        "interval": "1m",
    }
    given.update(overrides)
    return service.start_run(**given)


def test_starting_a_run_hands_the_worker_back_at_once(slow_runner):
    """Production is one cooperatively scheduled worker and a start must not hold it.

    The child below sleeps for two minutes. If starting waited for anything at all
    about it, this would take two minutes rather than a moment. The wrong
    implementation this catches is the one that waits for the process, reads its
    first line, or checks whether it got as far as loading its program.
    """
    began = time.monotonic()
    ok, said = _start()
    elapsed = time.monotonic() - began

    assert ok, said
    assert elapsed < 5.0, f"starting a run held the caller for {elapsed:.1f}s"

    try:
        assert service.is_running("turn.oscript")
    finally:
        service.stop_run("turn.oscript")


def test_stopping_a_run_reaps_the_process(slow_runner):
    """Stopped means gone, and the registry says so.

    The wrong implementation this catches is the one that signals the process and
    reports success without ever confirming it left, which leaves a strategy
    running with nothing tracking it.
    """
    ok, said = _start()
    assert ok, said
    held = service.RUNNING_RUNS[service.run_id_for("turn.oscript")]
    pid = held["pid"]
    process = held["process"]

    stopped, message = service.stop_run("turn.oscript")

    assert stopped, message
    assert process.poll() is not None, "the child was never reaped"
    assert not service._process_is_alive(pid)
    assert service.run_id_for("turn.oscript") not in service.RUNNING_RUNS
    assert not service.is_running("turn.oscript")


def test_stopping_never_waits_inside_a_call_the_server_cannot_interrupt(quiet_service):
    """Every wait polls. None of them blocks in C.

    ``Popen.wait(timeout=...)`` blocks inside the operating system, which is not a
    yield point, so on the production server it stops every other request for the
    length of the timeout. The stand-in below refuses to be waited on, so an
    implementation that called ``wait`` fails here rather than in production, where
    it would look like the whole application hanging.
    """

    class WillNotBeWaitedOn:
        pid = 4242

        def __init__(self):
            self.terminated = False
            self.waited = []

        def wait(self, timeout=None):
            # Recorded rather than raised. Stopping a run catches whatever goes
            # wrong, deliberately, so that a stop can never raise into the worker,
            # and a stand-in that raised here would be swallowed by that and the
            # test would pass with the defect in place.
            self.waited.append(timeout)
            return None

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.terminated = True

    process = WillNotBeWaitedOn()
    run_id = service.run_id_for("turn.oscript")
    service.RUNNING_RUNS[run_id] = {
        "process": process,
        "pid": process.pid,
        "script": "turn.oscript",
        "started_at": datetime.now(),
        "log_file": "",
    }

    stopped, message = service.stop_run("turn.oscript")

    assert stopped, message
    assert process.terminated
    assert process.waited == [], "stopping a run waited inside a call the server cannot interrupt"
    assert run_id not in service.RUNNING_RUNS


def test_the_log_goes_where_this_platform_already_keeps_strategy_logs(slow_runner, tmp_path):
    """One log folder, and one name shape, so the pages that read them find these too.

    The strategy host writes ``log/strategies/<id>_<when>_IST.log`` and its routes
    match on exactly that. The wrong implementation this catches is the one that
    invents a second location, which is a log nothing on this platform can list.
    """
    assert service.LOGS_DIR.parts[-2:] == ("log", "strategies") or str(
        service.LOGS_DIR
    ).endswith(os.path.join("log", "strategies"))

    ok, said = _start()
    assert ok, said
    try:
        run_id = service.run_id_for("turn.oscript")
        written = service.logs_for(run_id)
        assert written, "the run wrote no log at all"
        assert re.match(rf"^{re.escape(run_id)}_\d{{8}}_\d{{6}}_IST\.log$", written[0].name)
        assert written[0].parent == service.LOGS_DIR
        assert "Run started at" in written[0].read_text(encoding="utf-8")
    finally:
        service.stop_run("turn.oscript")


def test_the_unedited_default_log_folder_is_the_platform_s_own():
    """Said against the module rather than a fixture, since the fixture replaces it."""
    fresh = importlib.util.spec_from_file_location(
        "openscript_runner_service_default",
        REPOSITORY / "services" / "openscript_runner_service.py",
    )
    module = importlib.util.module_from_spec(fresh)
    fresh.loader.exec_module(module)
    assert module.LOGS_DIR == Path("log") / "strategies"


def test_a_second_start_is_refused_while_the_first_is_running(slow_runner):
    """One script, one process. Two would place one strategy's orders twice."""
    ok, said = _start()
    assert ok, said
    try:
        again, message = _start()
        assert not again
        assert "already running" in message
    finally:
        service.stop_run("turn.oscript")


def test_a_run_that_has_finished_is_dropped_from_the_registry(quiet_service, tmp_path, monkeypatch):
    """A run ends by itself more often than it is stopped.

    A script that refuses to start, or stops on a diagnostic, leaves a process that
    has already exited. Nothing notices on its own, so a registry that never reaped
    would report it as running and refuse to start it again for the life of the
    worker.
    """
    script = tmp_path / "brief_runner.py"
    script.write_text("import sys\nsys.stdout.write('done\\n')\n", encoding="utf-8")
    monkeypatch.setattr(service, "RUNNER_SCRIPT", script)

    ok, said = _start()
    assert ok, said
    run_id = service.run_id_for("turn.oscript")

    process = service.RUNNING_RUNS[run_id]["process"]
    deadline = time.monotonic() + 30
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert process.poll() is not None, "the stand-in runner never finished"

    assert service.reap_finished_runs() == [run_id]
    assert run_id not in service.RUNNING_RUNS

    # And it can be started again, which is the point of reaping at all.
    again, message = _start()
    assert again, message
    service.reap_finished_runs()


def test_every_run_is_stopped_before_the_worker_goes(slow_runner):
    """A child outlives its parent, so an exit that left one would leave it trading.

    The wrong implementation this catches is the one with no shutdown at all: a
    restart would leave the previous worker's strategies polling and placing
    orders, with nothing left in the new worker that could stop them.
    """
    ok, said = _start()
    assert ok, said
    held = service.RUNNING_RUNS[service.run_id_for("turn.oscript")]
    process = held["process"]

    stopped = service.stop_every_run()

    assert stopped == [service.run_id_for("turn.oscript")]
    assert process.poll() is not None
    assert service.RUNNING_RUNS == {}


def test_stopping_every_run_is_what_happens_when_the_interpreter_exits():
    """Registered at import, so nobody has to remember to ask for it."""
    tree = _syntax_of(SERVICE_PATH)
    registered = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "atexit"
    ]
    assert registered, "nothing is registered to run when this worker exits"
    assert any(
        isinstance(one.args[0], ast.Name) and one.args[0].id == "stop_every_run"
        for one in registered
        if one.args
    )


def test_a_name_that_is_not_a_script_never_reaches_a_command_line(quiet_service):
    """Every argument this service builds a command out of is checked first."""
    for bad in ("../../etc/passwd", "turn.oscript; rm -rf /", "-rf", "turn.py", ""):
        ok, message = service.start_run(bad, "SYM1", "EXCH1", "1m")
        assert not ok, f"{bad!r} was accepted"
        assert message

    ok, message = service.start_run("turn.oscript", "SYM1 && echo", "EXCH1", "1m")
    assert not ok
    ok, message = service.start_run("turn.oscript", "SYM1", "EXCH1", "1m; echo")
    assert not ok


def test_the_registry_lock_is_a_real_one_and_not_the_hub_s(quiet_service):
    """A green lock shared with a real thread deadlocks under the production server.

    This registry is read while a process is being reaped, so the lock has to be
    the unpatched one. Asserted against the import rather than the object, because
    under the dev server, where nothing is patched, the two are the same object and
    a test of the object would pass either way.
    """
    tree = _syntax_of(SERVICE_PATH)

    assert "RLock" in _named_imports(tree).get("utils.real_threading", set())
    assert "threading" not in _plain_imports(tree)
    assert "queue" not in _plain_imports(tree)
    assert _attributes_of(tree, "threading") == set()
    assert _attributes_of(tree, "queue") == set()


def test_the_service_starts_no_second_scheduler():
    """There is one scheduler in this application and this is not a second one."""
    tree = _syntax_of(SERVICE_PATH)
    assert "apscheduler" not in {one.split(".")[0] for one in _named_imports(tree)}
    assert "apscheduler" not in _plain_imports(tree)
    assert "BackgroundScheduler" not in {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
