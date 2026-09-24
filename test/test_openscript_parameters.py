"""A strategy's own parameters, from the box a trader types in to the run.

**Why this path gets its own file.** A parameter is the one setting here that a
script reads and acts on: the length of an average, a multiplier, a threshold
that decides whether an order is sent. Every other run setting says *what* to
run on and is checked against a pattern. A parameter says *how*, is arbitrary by
nature, and travels from a request body, through a file, through a process
boundary, into an engine. Each test below names the wrong implementation it
catches, and the ones that matter are the two ends: a value that is stored but
never reaches the run, and a value that reaches the run as something other than
what was stored.
"""

import json

import pytest

from services import openscript_run_config as run_config


@pytest.fixture(autouse=True)
def config_file(tmp_path, monkeypatch):
    """Each test writes its own settings file, so none of them share one."""
    path = tmp_path / "configs.json"
    monkeypatch.setattr(run_config, "CONFIG_FILE", path)
    return path


def save(**over):
    fields = {
        "script": "probe.oscript",
        "symbol": "TCS",
        "exchange": "NSE",
        "interval": "1m",
    }
    fields.update(over)
    return run_config.write_run_config(**fields)


# ---------------------------------------------------------------------------
# What may be a parameter at all
# ---------------------------------------------------------------------------


def test_the_three_shapes_an_engine_reads_are_stored_as_given():
    """A number, a piece of text and a flag, unchanged.

    An engine resolves a setting against the declaration it belongs to, so these
    are stored as themselves rather than tagged, converted or normalised. A
    number silently turned into text arrives as the wrong type and refuses the
    whole load.
    """
    ok, _ = save(inputs={"length": 20, "factor": 2.5, "mode": "fast", "on": True})
    assert ok

    held = run_config.read_run_config("probe.oscript")["inputs"]
    assert held == {"length": 20, "factor": 2.5, "mode": "fast", "on": True}
    assert isinstance(held["length"], int)
    assert isinstance(held["on"], bool)


def test_a_value_no_script_could_have_asked_for_is_refused_by_name():
    """Catches a shape stored and handed on.

    A list or a nested object is not something an input() declares, so it can
    only arrive from a caller sending something else. Refusing it here puts the
    message in front of the trader; storing it moves the failure into a log
    written a minute later by a process they cannot see.
    """
    for value in ([1, 2], {"nested": 1}, None):
        ok, why = save(inputs={"length": value})
        assert not ok, value
        assert "length" in why


def test_a_name_no_script_could_declare_is_refused():
    """Catches an unchecked key.

    The key is stored and later handed to an engine as the name of a declaration
    to resolve. A key holding a separator, a newline or nothing at all is a key
    whatever reads it next may read as something other than a name.
    """
    for key in ("", "two words", "has/slash", "line\nbreak", "9leading", "x" * 80):
        ok, why = save(inputs={key: 1})
        assert not ok, key
        assert why


def test_the_number_of_parameters_and_the_length_of_one_are_bounded():
    """Catches an unbounded write. This file is written from a request body."""
    ok, _ = save(inputs={f"k{n}": n for n in range(run_config.MAX_INPUTS + 1)})
    assert not ok

    ok, _ = save(inputs={"note": "x" * (run_config.MAX_TEXT_LENGTH + 1)})
    assert not ok


def test_no_parameters_is_an_empty_set_and_never_missing():
    """Catches a key a reader has to test for before reading it."""
    assert save()[0]
    assert run_config.read_run_config("probe.oscript")["inputs"] == {}


def test_saving_again_replaces_the_parameters_rather_than_merging_them():
    """Catches an update that keeps what the trader cleared.

    A trader who removes a parameter expects the run to go back to the script's
    own default. Merging leaves the old value in place, running a strategy on a
    setting nobody can see on screen.
    """
    assert save(inputs={"length": 20, "factor": 3})[0]
    # Named, because saving without naming the deployment creates one, and a
    # second on the same instrument and interval is refused. Editing is what
    # this test is about.
    only = next(iter(run_config.all_run_configs()))
    assert save(inputs={"length": 20}, deployment=only)[0]

    assert run_config.read_run_config(only)["inputs"] == {"length": 20}


def test_a_file_edited_by_hand_is_checked_when_it_is_read(config_file):
    """THE ONE A WRITE-TIME CHECK ALONE WOULD MISS.

    These settings live in a file inside a folder an operator can reach, and an
    older version of this platform wrote the same file without this field. A
    check only on the way in trusts whatever is already there, and what is
    already there is what a run is started from.
    """
    config_file.write_text(
        json.dumps(
            {
                "probe.oscript": {
                    "symbol": "TCS",
                    "exchange": "NSE",
                    "interval": "1m",
                    "inputs": {"good": 5, "bad key": [1, 2]},
                }
            }
        ),
        encoding="utf-8",
    )

    assert run_config.read_run_config("probe.oscript")["inputs"] == {}


def test_a_file_written_before_parameters_existed_still_reads(config_file):
    """An upgrade must not make every saved strategy unreadable."""
    config_file.write_text(
        json.dumps({"probe.oscript": {"symbol": "TCS", "exchange": "NSE", "interval": "1m"}}),
        encoding="utf-8",
    )

    held = run_config.read_run_config("probe.oscript")
    assert held["symbol"] == "TCS"
    assert held["inputs"] == {}


# ---------------------------------------------------------------------------
# Reaching the run
# ---------------------------------------------------------------------------


def test_the_saved_parameters_reach_the_child(monkeypatch):
    """THE ONE THAT MATTERS MOST.

    A parameter saved and not carried is a strategy running on numbers other
    than the ones on screen, with nothing anywhere saying so: the settings page
    shows 20, the run uses the script's 14, and every order is the second
    strategy's.
    """
    from services import openscript_runner_service as service

    assert save(inputs={"length": 20, "mode": "fast"})[0]

    seen = {}

    def spawn(
        script, run_id, symbol, exchange, interval, product, user_id, days, poll, inputs=None
    ):
        seen["inputs"] = inputs
        return True, "started"

    monkeypatch.setattr(service, "_spawn_claimed", spawn)
    monkeypatch.setattr(service, "read_run_config", run_config.read_run_config)

    ok, _ = service.start_run("probe.oscript")

    assert ok
    assert seen["inputs"] == {"length": 20, "mode": "fast"}


def test_the_child_reads_what_the_parent_wrote(monkeypatch):
    """The two ends of the process boundary, against each other.

    The parent encodes and the child decodes, and the pair only works if they
    agree. Testing either alone passes while a run gets nothing.
    """
    from services import openscript_runner_service as service

    text = service._inputs_as_text({"length": 20, "mode": "fast", "on": True}, "probe")
    monkeypatch.setenv("OPENSCRIPT_INPUTS", text)

    from openscript_host import openscript_runner as child

    read = child.Session._settings(object.__new__(child.Session))

    assert read == {"length": 20, "mode": "fast", "on": True}


def test_an_empty_set_is_written_rather_than_left_off():
    """Catches the variable being set only when there is something to set.

    The worker's own environment is inherited by every child. A run started
    after the parameters were cleared would otherwise be handed whatever was in
    the environment, which is the previous run's.
    """
    from services import openscript_runner_service as service

    assert service._inputs_as_text({}, "probe") == "{}"
    assert service._inputs_as_text(None, "probe") == "{}"


def test_a_parameter_set_that_cannot_be_encoded_starts_the_run_anyway():
    """Catches a start that fails over a settings map.

    The run is what somebody is waiting for. A strategy that will not start
    because of one unencodable value is worse than one that starts on the
    script's own declared defaults and says so in its log.
    """
    from services import openscript_runner_service as service

    assert service._inputs_as_text({"x": {1, 2}}, "probe") == "{}"
    assert service._inputs_as_text({"x": float("nan")}, "probe") == "{}"


def test_the_child_runs_on_the_script_defaults_when_it_cannot_read_them(monkeypatch):
    """Catches an exception in the child over a settings map.

    A run that dies reading its parameters is a strategy that is not running,
    which a trader discovers by noticing no orders.
    """
    from openscript_host import openscript_runner as child

    blank = object.__new__(child.Session)
    for raw in ("not json", "[1, 2]", '"text"', "", "   "):
        monkeypatch.setenv("OPENSCRIPT_INPUTS", raw)
        assert child.Session._settings(blank) == {}

    monkeypatch.delenv("OPENSCRIPT_INPUTS", raising=False)
    assert child.Session._settings(blank) == {}
