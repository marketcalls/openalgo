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
import inspect
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

import services.openscript_run_config as run_config
import services.openscript_runner_service as service

REPOSITORY = Path(__file__).resolve().parents[1]

#: Where the program that runs a script belongs, and where it used to be.
#:
#: It is moving out of ``strategies`` because that folder is a mounted volume on
#: a container install, and a volume is seeded from the image only while it is
#: empty, so a platform file put there is absent on every install that already
#: has one. The move is one change and this file is loaded from wherever it has
#: got to, so the tests below neither hold it up nor go green on its absence.
RUNNER_HOME = REPOSITORY / "openscript_host" / "openscript_runner.py"
RUNNER_WAS = REPOSITORY / "strategies" / "scripts" / "openscript_runner.py"
RUNNER_PATH = RUNNER_HOME if RUNNER_HOME.is_file() else RUNNER_WAS
SERVICE_PATH = REPOSITORY / "services" / "openscript_runner_service.py"
RUN_CONFIG_PATH = REPOSITORY / "services" / "openscript_run_config.py"


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

    It is a program rather than a module in a package: the web worker spawns it
    and never imports it, and the process it runs in has nothing patched in it.
    So it is loaded here the way anything else would load a file.
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
def settings(tmp_path, monkeypatch):
    """The run settings file, belonging to this test and not to the operator.

    Pointed somewhere else before anything can read it. The real one holds what a
    trader saved on this machine, and a suite that read it would pass or fail on
    whatever happens to be in it, while a suite that wrote it would start
    somebody's script on an instrument they never chose.
    """
    path = tmp_path / "strategies" / "openscript_run_configs.json"
    monkeypatch.setattr(run_config, "CONFIG_FILE", path)
    return path


@pytest.fixture
def quiet_service(tmp_path, monkeypatch, settings):
    """The service, with its log folder, its registry and its settings for this test."""
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


def test_the_registry_lock_is_the_hub_s_own_because_only_greenlets_take_it(quiet_service):
    """Nothing on any path into this service is a real OS thread, so the lock is the ordinary one.

    This replaces a test that pinned the opposite, and what it pinned was not
    true: the module claimed a real lock was needed because "this dictionary is
    read while a process is being reaped", and the reaping is done by the same
    request greenlet or scheduled job as everything else. A request handler is a
    greenlet, a scheduler's worker is an ordinary thread and the production
    server patches it, and so is the main thread that runs the exit handler.

    A lock from ``utils/real_threading`` would be the wrong one twice over. A
    greenlet that blocks on a real lock stops the single production worker for
    every user, not just itself. And a greenlet that yields while holding one can
    never be resumed to release it, which the sweep now done under this lock puts
    within reach of any change that adds a yield to it.

    The wrong implementation this catches is the one that takes the lock from
    ``utils/real_threading`` again, and the one that leaves the justification for
    it in place. Asserted against the imports rather than the object, because on
    the dev server, where nothing is patched, the two are the same object and an
    assertion about the object would pass either way.
    """
    for path in (SERVICE_PATH, RUN_CONFIG_PATH):
        tree = _syntax_of(path)
        brought_in = _named_imports(tree)

        assert brought_in.get("threading", set()), f"{path.name} takes no lock from threading"
        assert "utils.real_threading" not in brought_in, (
            f"{path.name} takes a real lock, and there is no real thread here to justify one"
        )
        assert "queue" not in _plain_imports(tree)
        assert _attributes_of(tree, "queue") == set()


def test_the_service_starts_no_second_scheduler():
    """There is one scheduler in this application and this is not a second one."""
    tree = _syntax_of(SERVICE_PATH)
    assert "apscheduler" not in {one.split(".")[0] for one in _named_imports(tree)}
    assert "apscheduler" not in _plain_imports(tree)
    assert "BackgroundScheduler" not in {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }


# ---------------------------------------------------------------------------
# What a script is run on: the settings, and starting from the name alone
# ---------------------------------------------------------------------------


class StandInProcess:
    """A process object that is alive until it is told it is not.

    A test that needs a run in the registry without spawning anything, so it can
    say what the registry does about a process whose state it chooses. The test
    below asserts that every method this service calls on a process takes what
    the real one takes: a stand-in whose shape has drifted from the class it
    stands in for is exactly how a service passes its whole suite while calling
    something that is not there.
    """

    def __init__(self, pid=424242, code=None):
        self.pid = pid
        self._code = code
        self.terminated = False

    def poll(self):
        return self._code

    def wait(self, timeout=None):
        return self._code

    def terminate(self):
        self.terminated = True
        self._code = -15

    def kill(self):
        self.terminated = True
        self._code = -9


def test_a_stand_in_for_a_process_is_shaped_like_the_real_one():
    """Every method the service calls on a process, against the real class.

    The wrong implementation this catches is not in the service: it is in this
    file. A suite whose stand-ins have drifted from the real thing is a suite
    that proves nothing about the real thing, which is how a whole seam went
    unnoticed once already.
    """
    for name in ("poll", "wait", "terminate", "kill"):
        mine = inspect.signature(getattr(StandInProcess, name))
        real = inspect.signature(getattr(subprocess.Popen, name))
        assert mine == real, f"the stand-in's {name} is {mine}, the real one is {real}"


@pytest.fixture
def recording_runner(tmp_path, monkeypatch, quiet_service):
    """A stand-in runner that writes its own command line out and then stays alive.

    The log a run writes is the child's own standard output, so a child that
    prints its arguments lets a test read exactly what reached the command line
    rather than what the service meant to put there.
    """
    script = tmp_path / "recording_runner.py"
    script.write_text(
        "import sys, time\n"
        "sys.stdout.write(' '.join(sys.argv[1:]) + chr(10))\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "RUNNER_SCRIPT", script)

    yield script

    for one in psutil.Process().children(recursive=True):
        try:
            if str(script) in " ".join(one.cmdline()):
                one.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def _command_line_of(run_id, within=30.0):
    """What the child was actually started with, read out of its own log."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        for one in service.logs_for(run_id):
            for line in one.read_text(encoding="utf-8").splitlines():
                if line.startswith("--script"):
                    return line
        time.sleep(0.1)
    raise AssertionError("the run never wrote its command line")


def test_a_run_starts_from_the_script_name_alone(recording_runner):
    """The route hands over a name and nothing else, so the service reads the rest.

    This is the call the start route makes. The wrong implementation this catches
    is the one that needs the instrument passed in: broken that way, a start from
    the page fails on a missing argument, which is what the route worked around
    last time by inventing one.
    """
    saved, said = run_config.write_run_config("turn.oscript", "SYM1", "exch1", "5m", "nrml")
    assert saved, said

    ok, message = service.start_run("turn.oscript")

    assert ok, message
    assert "turn.oscript" in message
    try:
        written = _command_line_of(service.run_id_for("turn.oscript"))
        assert "--symbol SYM1" in written
        assert "--exchange EXCH1" in written
        assert "--interval 5m" in written
        assert "--product NRML" in written
    finally:
        service.stop_run("turn.oscript")


def test_what_the_caller_holds_wins_over_what_was_saved(recording_runner):
    """The explicit arguments stay, for a caller that already has them.

    The wrong implementation this catches is the one that reads the settings over
    the top of what it was passed, which would send a run to an instrument the
    caller did not ask for.
    """
    saved, said = run_config.write_run_config("turn.oscript", "SYM1", "EXCH1", "5m")
    assert saved, said

    ok, message = service.start_run("turn.oscript", symbol="SYM2", interval="1m")

    assert ok, message
    try:
        written = _command_line_of(service.run_id_for("turn.oscript"))
        assert "--symbol SYM2" in written
        assert "--interval 1m" in written
        # and what it did not hold still comes from the settings
        assert "--exchange EXCH1" in written
    finally:
        service.stop_run("turn.oscript")


def test_a_script_with_no_run_settings_is_refused_by_name(quiet_service, slow_runner):
    """Nothing is started on a guess, and the refusal is addressed to the trader.

    The wrong implementation this catches is the one that starts anyway on a
    default instrument, which is a run placing orders on something nobody chose.
    The message has to name the script, because a trader with several will
    otherwise not know which one to go and fix.
    """
    ok, why = service.start_run("turn.oscript")

    assert not ok
    assert "turn.oscript" in why
    for word in ("instrument", "exchange", "interval"):
        assert word in why
    assert service.RUNNING_RUNS == {}


def test_settings_missing_one_field_say_which_one(quiet_service, settings, slow_runner):
    """Named one by one, so the trader fixes the thing that is actually absent."""
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps({"turn.oscript": {"symbol": "SYM1", "exchange": "", "interval": ""}}),
        encoding="utf-8",
    )

    ok, why = service.start_run("turn.oscript")

    assert not ok
    assert "turn.oscript" in why
    assert "the exchange and the interval" in why
    assert service.RUNNING_RUNS == {}


def test_a_product_that_is_not_one_this_platform_sends_never_reaches_a_command_line(
    quiet_service, slow_runner
):
    """The fourth thing that reaches the command line is checked like the other three.

    It was the one that was not. The wrong implementation this catches is the one
    that passes a product straight through, where the run then fails a minute
    later inside its own log, and where a value with a space or a dash in it is
    an argument to the program rather than a product.
    """
    for refused in ("EQUITY", "NRML MIS", "--product", "nrml"):
        ok, why = service.start_run("turn.oscript", "SYM1", "EXCH1", "1m", product=refused)
        assert not ok, f"{refused!r} was accepted as a product"
        assert "CNC" in why and "NRML" in why and "MIS" in why
        assert service.RUNNING_RUNS == {}

    ok, said = service.start_run("turn.oscript", "SYM1", "EXCH1", "1m", product="NRML")
    assert ok, said
    service.stop_run("turn.oscript")


def test_a_product_that_is_not_one_this_platform_sends_is_refused_when_it_is_saved(settings):
    """Refused while the trader is looking at it, not a minute later in a log."""
    ok, why = run_config.write_run_config("turn.oscript", "SYM1", "EXCH1", "1m", product="EQUITY")

    assert not ok
    assert "CNC" in why and "NRML" in why and "MIS" in why
    assert run_config.read_run_config("turn.oscript") is None


def test_the_settings_saved_are_the_settings_read_back(settings):
    """What goes in comes out, with the two closed vocabularies in one case.

    The exchange and the product are upper cased because this platform states
    both in one case. The instrument and the interval are left exactly as typed:
    a symbol is the one string a broker mapping matches on, and changing it
    quietly is how a run ends up on a different instrument from the one asked for.
    """
    ok, said = run_config.write_run_config("turn.oscript", "SYM1", "exch1", "5m", "mis", "trader")
    assert ok, said

    found = run_config.read_run_config("turn.oscript")
    assert found["symbol"] == "SYM1"
    assert found["exchange"] == "EXCH1"
    assert found["interval"] == "5m"
    assert found["product"] == "MIS"
    assert found["user_id"] == "trader"

    usable, why = run_config.require_run_config("turn.oscript")
    assert usable is not None, why
    assert usable["symbol"] == "SYM1"


def test_saving_one_script_s_settings_leaves_every_other_script_alone(settings):
    """A write is a read, a change and a rename, not a file with one script in it.

    The wrong implementation this catches is the one that writes only the script
    it was handed, which silently deletes the settings of every other script the
    trader has, and is only noticed when the next run refuses to start.
    """
    assert run_config.write_run_config("one.oscript", "SYM1", "EXCH1", "1m")[0]
    assert run_config.write_run_config("two.oscript", "SYM2", "EXCH2", "5m")[0]

    assert set(run_config.all_run_configs()) == {"one.oscript", "two.oscript"}
    assert run_config.read_run_config("one.oscript")["symbol"] == "SYM1"
    assert run_config.read_run_config("two.oscript")["symbol"] == "SYM2"


def test_settings_that_could_never_start_a_run_are_refused_when_they_are_saved(settings):
    """Every value here reaches a command line when the run starts.

    The wrong implementation this catches is the one that stores whatever it is
    given and leaves the checking to the start, which is a setting a trader can
    save, look at, and never be able to run.
    """
    for bad in ("../../etc/passwd", "turn.oscript; rm -rf /", "-rf", "turn.py", ""):
        ok, why = run_config.write_run_config(bad, "SYM1", "EXCH1", "1m")
        assert not ok, f"{bad!r} was accepted as a script name"
        assert why

    for symbol in ("SYM1 && echo", "-SYM1", ""):
        ok, why = run_config.write_run_config("turn.oscript", symbol, "EXCH1", "1m")
        assert not ok, f"{symbol!r} was accepted as an instrument"

    ok, why = run_config.write_run_config("turn.oscript", "SYM1", "EXCH1", "1m; echo")
    assert not ok

    assert run_config.all_run_configs() == {}


def test_removing_the_settings_removes_the_run(settings, quiet_service, slow_runner):
    """A script a trader has finished with stops being one command away from running."""
    assert run_config.write_run_config("turn.oscript", "SYM1", "EXCH1", "1m")[0]

    gone, said = run_config.delete_run_config("turn.oscript")
    assert gone, said

    assert run_config.read_run_config("turn.oscript") is None
    ok, why = service.start_run("turn.oscript")
    assert not ok
    assert "turn.oscript" in why

    again, why = run_config.delete_run_config("turn.oscript")
    assert not again
    assert "turn.oscript" in why


def test_settings_that_cannot_be_written_leave_the_last_good_ones_alone(settings):
    """Through a temporary file and a rename, so an interrupted write loses nothing.

    The wrong implementation this catches is the one that opens the settings file
    and writes into it: a failure part way through leaves a file that is neither
    the old settings nor the new ones, and every script in it is then a script
    that cannot be started.
    """
    assert run_config.write_run_config("turn.oscript", "SYM1", "EXCH1", "1m")[0]

    def refuse(*arguments, **named):
        raise OSError("the disk said no")

    # In a context of its own, so putting the writer back does not also put back
    # the settings file this test was given, which is what a shared undo does.
    with pytest.MonkeyPatch.context() as broken:
        broken.setattr(run_config.json, "dump", refuse)
        ok, why = run_config.write_run_config("turn.oscript", "SYM2", "EXCH2", "5m")

    assert not ok
    assert why

    kept = run_config.read_run_config("turn.oscript")
    assert kept["symbol"] == "SYM1", "a failed write replaced the settings that were there"
    assert not list(settings.parent.glob("*.tmp")), "a half written file was left behind"


def test_the_settings_sit_where_this_platform_already_keeps_a_strategy_s_settings():
    """One folder, so an upgrade keeps them and an operator has one place to look.

    Said against the module rather than a fixture, since every fixture here
    replaces it. The strategy host keeps ``strategies/strategy_configs.json`` and
    a container keeps that folder on a named volume, which is what makes a
    trader's settings survive a rebuild.
    """
    fresh = importlib.util.spec_from_file_location(
        "openscript_run_config_default", RUN_CONFIG_PATH
    )
    module = importlib.util.module_from_spec(fresh)
    fresh.loader.exec_module(module)

    assert module.CONFIG_FILE.parent == Path("strategies")
    assert module.CONFIG_FILE.suffix == ".json"


# ---------------------------------------------------------------------------
# A registry that heals itself
# ---------------------------------------------------------------------------


def test_a_run_that_ended_by_itself_is_gone_without_anybody_sweeping(
    quiet_service, tmp_path, monkeypatch
):
    """Nothing external has to remember, because nothing external ever did.

    A run ends by itself far more often than it is stopped, and the registry is
    not told. The wrong implementation this catches is the one that waits to be
    swept: with it in place this script stays running after its process has gone,
    and it cannot be started again for the life of the worker. Reaping is
    deliberately not called anywhere in this test.
    """
    script = tmp_path / "brief_runner.py"
    script.write_text("import sys\nsys.stdout.write('done')\n", encoding="utf-8")
    monkeypatch.setattr(service, "RUNNER_SCRIPT", script)

    ok, said = service.start_run("turn.oscript", "SYM1", "EXCH1", "1m")
    assert ok, said
    run_id = service.run_id_for("turn.oscript")

    # Read straight out of the dictionary, so waiting for the child does not
    # itself go through the sweep this test is about.
    process = service.RUNNING_RUNS[run_id]["process"]
    deadline = time.monotonic() + 30
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert process.poll() is not None, "the stand-in runner never finished"

    assert not service.is_running("turn.oscript")
    assert service.status_of("turn.oscript") is None
    assert service.running_runs() == []
    assert run_id not in service.RUNNING_RUNS

    again, message = service.start_run("turn.oscript", "SYM1", "EXCH1", "1m")
    assert again, message


def test_a_run_is_never_dropped_because_its_process_id_could_not_be_read(
    quiet_service, monkeypatch
):
    """Only the run's own process may say it has gone.

    The wrong implementation this catches is the one that drops an entry because
    a lookup by process id said the process was not there. That answer is wrong
    in two directions: an id may have been reused by then, and where reading
    another process needs permission a live run looks exactly like a dead one.
    Dropping a live run leaves a strategy placing orders with nothing left that
    can stop it, which is worse than keeping a finished one a moment longer.
    """
    monkeypatch.setattr(service, "_process_is_alive", lambda pid: False)
    run_id = service.run_id_for("turn.oscript")
    service.RUNNING_RUNS[run_id] = {
        "process": StandInProcess(pid=4242),
        "pid": 4242,
        "script": "turn.oscript",
        "started_at": datetime.now(),
        "log_file": "",
    }

    assert service.is_running("turn.oscript")
    assert service.status_of("turn.oscript") is not None
    assert [one["run"] for one in service.running_runs()] == [run_id]
    assert service.reap_finished_runs() == []


def test_a_process_that_cannot_answer_keeps_its_place_in_the_registry(quiet_service):
    """A question that raises is not an answer of gone.

    Same reason as above, one step further: an implementation that treats any
    failure as a finished run loses the record of a strategy that is still out
    there.
    """

    class WillNotSay(StandInProcess):
        def poll(self):
            raise OSError("not today")

    run_id = service.run_id_for("turn.oscript")
    service.RUNNING_RUNS[run_id] = {
        "process": WillNotSay(),
        "pid": 4242,
        "script": "turn.oscript",
        "started_at": datetime.now(),
        "log_file": "",
    }

    assert service.reap_finished_runs() == []
    assert run_id in service.RUNNING_RUNS


def test_reaping_is_the_same_sweep_the_rest_of_the_service_does(quiet_service):
    """One sweep, so a scheduled call and a page load can never disagree.

    It is kept because a worker with no page open and no run being started still
    has children to reap. The wrong implementation this catches is a second copy
    of the rule, which is how two answers about one run start being possible.
    """
    run_id = service.run_id_for("turn.oscript")
    service.RUNNING_RUNS[run_id] = {
        "process": StandInProcess(code=0),
        "pid": 4242,
        "script": "turn.oscript",
        "started_at": datetime.now(),
        "log_file": "",
    }

    assert service.reap_finished_runs() == [run_id]
    assert service.RUNNING_RUNS == {}
    assert service.reap_finished_runs() == []


# ---------------------------------------------------------------------------
# The program that runs a script, and the contract two other callers import
# ---------------------------------------------------------------------------


def test_the_program_that_runs_a_script_is_not_kept_in_a_mounted_folder():
    """A file the platform owns cannot live where a container keeps a volume.

    The deployment keeps ``strategies`` on a named volume, and a named volume is
    seeded from the image only while it is empty, so a platform file put there is
    absent on every install that already has that volume. The wrong
    implementation this catches is the one that leaves the runner under
    ``strategies``, where it is delivered to a new install and to nobody else,
    and where the folder's own rules keep every ``.py`` out of the repository.
    """
    fresh = importlib.util.spec_from_file_location(
        "openscript_runner_service_default", SERVICE_PATH
    )
    module = importlib.util.module_from_spec(fresh)
    fresh.loader.exec_module(module)

    assert module.RUNNER_SCRIPT.parts[0] != "strategies"
    assert module.RUNNER_SCRIPT.name.endswith(".py")


def test_the_runner_is_looked_for_where_it_belongs_before_where_it_used_to_be(
    quiet_service, tmp_path, monkeypatch
):
    """Two places, both written down, and the old one says so in the log.

    The wrong implementation this catches is the one that looks in the old place
    first, which would go on using a file the next container rebuild deletes even
    on an installation that has taken the move.
    """
    home = tmp_path / "openscript_host" / "openscript_runner.py"
    home.parent.mkdir(parents=True, exist_ok=True)
    home.write_text("", encoding="utf-8")
    was = tmp_path / "strategies" / "scripts" / "openscript_runner.py"
    was.parent.mkdir(parents=True, exist_ok=True)
    was.write_text("", encoding="utf-8")

    monkeypatch.setattr(service, "RUNNER_SCRIPT", home)
    monkeypatch.setattr(service, "LEGACY_RUNNER_SCRIPT", was)
    assert service.runner_program_path() == home.resolve()

    home.unlink()
    assert service.runner_program_path() == was.resolve()

    was.unlink()
    assert service.runner_program_path() is None

    ok, why = service.start_run("turn.oscript", "SYM1", "EXCH1", "1m")
    assert not ok
    assert why
    assert service.RUNNING_RUNS == {}


def test_the_signatures_two_other_callers_import_are_these():
    """The contract, spelled out, because a route and a page are written against it.

    A signature changed by hand here is a change somebody else's code finds at
    runtime. The wrong implementation this catches is any silent widening or
    reordering of these, including a start that stops accepting the script name
    on its own, which is the one call the start route makes.
    """
    contract = {
        service.start_run: (
            "(script: str, symbol: str = '', exchange: str = '', interval: str = '', "
            "user_id: str | None = None, product: str = '', history_days: int = 5, "
            "poll_seconds: float = 15.0) -> tuple[bool, str]"
        ),
        service.stop_run: "(script_or_run_id: str) -> tuple[bool, str]",
        service.is_running: "(script_or_run_id: str) -> bool",
        service.status_of: "(script_or_run_id: str) -> dict | None",
        service.running_runs: "() -> list[dict]",
        service.reap_finished_runs: "() -> list[str]",
        service.stop_every_run: "() -> list[str]",
        service.run_id_for: "(script: str) -> str",
        service.logs_for: "(run_id: str) -> list[pathlib.Path]",
        service.log_file_for: (
            "(run_id: str, started: datetime.datetime | None = None) -> pathlib.Path"
        ),
        service.runner_program_path: "() -> pathlib.Path | None",
        run_config.read_run_config: "(script: str) -> dict | None",
        run_config.require_run_config: "(script: str) -> tuple[dict | None, str]",
        run_config.write_run_config: (
            "(script: str, symbol: str, exchange: str, interval: str, product: str = '', "
            "user_id: str | None = None) -> tuple[bool, str]"
        ),
        run_config.delete_run_config: "(script: str) -> tuple[bool, str]",
        run_config.all_run_configs: "() -> dict[str, dict]",
        run_config.is_script_name: "(name: str) -> bool",
        run_config.is_run_field: "(value: str) -> bool",
        run_config.is_product: "(value: str) -> bool",
    }
    for function, written in contract.items():
        assert str(inspect.signature(function)) == written, function.__name__


def test_one_start_reaches_the_real_service_and_the_real_settings(tmp_path, monkeypatch, settings):
    """No stand-in stands between this test and the two modules it is about.

    Every name below is imported from the module that defines it, and the start
    goes all the way to a child process. A stand-in with the wrong method names
    is what let a whole seam pass its tests once already, so at least one test
    here has to be answerable only by the real thing.
    """
    from services.openscript_run_config import require_run_config, write_run_config
    from services.openscript_runner_service import run_id_for, start_run, stop_run

    monkeypatch.setattr(service, "LOGS_DIR", tmp_path / "log" / "strategies")
    monkeypatch.setattr(service, "RUNNING_RUNS", {})
    monkeypatch.setattr(service, "STOPPING_RUNS", set())
    child = tmp_path / "quiet_child.py"
    child.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(service, "RUNNER_SCRIPT", child)

    nothing, why = require_run_config("turn.oscript")
    assert nothing is None
    assert "turn.oscript" in why

    saved, said = write_run_config("turn.oscript", "SYM1", "EXCH1", "1m")
    assert saved, said

    ok, message = start_run("turn.oscript")
    try:
        assert ok, message
        held = service.RUNNING_RUNS[run_id_for("turn.oscript")]
        assert held["symbol"] == "SYM1"
        assert psutil.pid_exists(held["pid"])
    finally:
        stopped, why = stop_run("turn.oscript")
        assert stopped, why
