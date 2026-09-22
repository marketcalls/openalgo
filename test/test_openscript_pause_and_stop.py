"""Pause and Stop, which are not the same thing, and the difference is a position.

**Pause** ends the process and leaves whatever the run was holding exactly where
it is. A trader pauses a strategy to change a parameter, to look at what it is
doing, or before restarting the server: the position becomes theirs to manage
and the strategy stops deciding about it.

**Stop** closes what the run holds and then ends it. A trader stops a strategy
when they are finished with it.

Getting either one wrong costs money in a different direction, and neither
mistake is recoverable:

- Pausing when Stop was meant leaves a position nothing is watching.
- Stopping when Pause was meant spends a spread and gives up a position the
  trader wanted, to change a number.

So the two are separate calls, separate routes, and the one that spends is the
one the page asks about first. Each test below names the wrong implementation it
catches.
"""

import json

import pytest

import services.openscript_commands as commands
import services.openscript_runner_service as service
from services.openscript_deployment import deployment_id

RUN = deployment_id("turn.oscript", "SYM1", "EXCH1", "1m")


class Child:
    """A run, as the registry holds one: it ends when it is told, or it does not."""

    def __init__(self, ends_when_asked=True):
        self.pid = 4242
        self.ends_when_asked = ends_when_asked
        self.signals: list[int] = []
        self.terminated = False
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def send_signal(self, number):
        self.signals.append(number)
        if self.ends_when_asked:
            self._alive = False

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self._alive = False

    def leaves_on_its_own(self):
        """What a run does once it has closed what it held."""
        self._alive = False


@pytest.fixture(autouse=True)
def quiet(tmp_path, monkeypatch):
    """Own registry, own instruction file, and no real waiting."""
    monkeypatch.setattr(commands, "COMMAND_FILE", tmp_path / "commands.json")
    monkeypatch.setattr(service, "RUNNING_RUNS", {})
    monkeypatch.setattr(service, "STOPPING_RUNS", set())
    monkeypatch.setattr(service, "CLOSE_SECONDS", 0.6)
    monkeypatch.setattr(service, "CLOSE_LOOK", 0.05)
    monkeypatch.setattr(service, "mark_stopped", lambda one: None)
    return tmp_path


def running(child):
    service.RUNNING_RUNS[RUN] = {
        "process": child,
        "pid": child.pid,
        "script": "turn.oscript",
        "run": RUN,
        "log_file": "",
    }
    return child


# ---------------------------------------------------------------------------
# Pause leaves the position
# ---------------------------------------------------------------------------


def test_pausing_never_asks_the_run_to_close_anything():
    """THE ONE THAT SPENDS MONEY IF IT IS WRONG.

    A trader pausing a strategy to change a parameter has not asked for the
    position to be closed. Closing it costs a spread and gives up a position
    they wanted, and no amount of undo brings it back.
    """
    running(Child())

    ok, message = service.stop_run(RUN)

    assert ok, message
    assert commands.all_commands() == {}, "pausing asked the run to close its position"
    assert RUN not in service.RUNNING_RUNS


def test_pausing_says_it_paused_and_never_says_it_closed():
    """The words a trader reads have to match what happened to their position."""
    running(Child())

    _ok, message = service.stop_run(RUN)

    assert "paused" in message
    assert "closed" not in message


# ---------------------------------------------------------------------------
# Stop closes first
# ---------------------------------------------------------------------------


def test_stopping_asks_the_run_to_close_and_waits_for_it_to_go():
    """THE ONE THIS FILE EXISTS FOR.

    Only the run knows its own size, because two deployments can hold the same
    instrument and squaring the account's net position in it would close
    somebody else's. So the run is asked, and this waits for it rather than
    terminating the process out from under the closing order.
    """
    child = running(Child(ends_when_asked=False))
    asked: list[str] = []

    def ask(run_id, what=commands.CLOSE):
        asked.append(run_id)
        # What a run does when it has closed what it held.
        child.leaves_on_its_own()

    service.ask_to_close = ask
    try:
        ok, message = service.stop_run(RUN, close=True)
    finally:
        service.ask_to_close = commands.ask

    assert ok, message
    assert asked == [RUN], "the run was never asked to close its position"
    assert child.terminated is False, "the process was killed out from under the closing order"
    assert "closed and stopped" in message


def test_a_run_that_does_not_close_stays_running_and_says_why():
    """THE ONE THAT LEAVES A POSITION UNWATCHED IF IT IS WRONG.

    The close did not happen, so the position is still there and something has
    to be able to stop it. Reporting success and dropping the run is how a
    position ends up with nothing managing it. This is the platform's own rule
    for a stop whose exit orders were refused.
    """
    child = running(Child(ends_when_asked=False))

    ok, message = service.stop_run(RUN, close=True)

    assert ok is False
    assert RUN in service.RUNNING_RUNS, "a run holding a position was dropped from the registry"
    assert child.terminated is False
    assert "still running" in message and "still holding" in message
    assert "Pause" in message, "the refusal does not say what a trader can do instead"


def test_an_instruction_that_was_not_carried_out_is_not_left_to_be_retried():
    """Catches a closing order sent on every wake for the rest of the session.

    The run tried and did not manage it. Left in place the instruction is read
    again on the next wake, and again after that: one closing order a minute for
    a position that is not closing, and a log that says the same thing all day.
    """
    running(Child(ends_when_asked=False))

    service.stop_run(RUN, close=True)

    assert commands.all_commands() == {}


def test_stopping_a_run_that_is_not_running_is_not_reported_as_a_close():
    """An operator pressing Stop believes something is running."""
    ok, message = service.stop_run(RUN, close=True)

    assert ok is False
    assert "not running" in message


# ---------------------------------------------------------------------------
# The instruction file
# ---------------------------------------------------------------------------


def test_an_instruction_survives_the_worker_that_wrote_it(quiet):
    """It is read by another process, so it has to be on disk and not in memory."""
    commands.ask(RUN)

    assert json.loads((quiet / "commands.json").read_text(encoding="utf-8"))[RUN]["what"] == "close"
    assert commands.command_for(RUN) == commands.CLOSE


def test_an_instruction_is_cleared_by_name_and_leaves_the_others():
    other = deployment_id("turn.oscript", "SYM2", "EXCH1", "1m")
    commands.ask(RUN)
    commands.ask(other)

    commands.clear(RUN)

    assert commands.command_for(RUN) == ""
    assert commands.command_for(other) == commands.CLOSE


def test_an_instruction_this_does_not_recognise_is_never_recorded():
    """Catches a file that can carry anything.

    A child acts on what it reads here. A word it does not recognise is one it
    has to ignore, and a word nothing wrote is one nothing should act on.
    """
    commands.ask(RUN, "square-everything")
    commands.ask("not-a-deployment", commands.CLOSE)

    assert commands.all_commands() == {}


def test_an_unreadable_instruction_file_is_no_instruction(quiet):
    """Catches a run that stops trading over a file it could not parse.

    A run holding a position that refused to go on because of this would be
    worse than one that misses an instruction and is asked again in a moment.
    """
    (quiet / "commands.json").write_text("{ not json", encoding="utf-8")

    assert commands.all_commands() == {}
    assert commands.command_for(RUN) == ""


def test_nothing_in_the_command_module_needs_the_platform_to_import():
    """THE ONE THAT BROKE THE RUNNER.

    The child that reads this file is a separate process with its own working
    directory, and it deliberately does not attach to the platform's logging.
    Importing that at module level made the runner fail at startup, before it
    had read a single argument, on a path it was never going to write to.
    """
    import ast
    from pathlib import Path

    source = Path(service.__file__).parent / "openscript_commands.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    top = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    names = {getattr(node, "module", "") or "" for node in top}

    assert not {one for one in names if one.startswith("utils.")}, names
    assert not {one for one in names if one.startswith("database.")}, names
    assert not {one for one in names if one.startswith("blueprints.")}, names
