"""One strategy, deployed on several instruments and several timeframes at once.

**What this is about.** A run used to be identified by its script, so a trader
could deploy a strategy once. Saving it against a second instrument replaced the
first silently, starting it a second time was refused as "already running", and,
worst of all, the two shared an order tag: the strategy panel showed a run on a
commodity future listing the stock orders the same file had placed that morning.
Two positions were reported as one, and a trader reading that book could not tell
which of them they were looking at.

A deployment is a script, the instrument it runs on and the bar it runs on. Each
one has its own position, its own book, its own log and its own decision to stop.

**The dangerous half is what happens when a name does not say which.** A file
name names no instrument, and guessing is how a stop reaches the deployment a
trader did not mean: they press stop on a stock and a commodity position is
squared instead. Every test below that names a script rather than a deployment
is about refusing rather than guessing.
"""

import json

import pytest

import services.openscript_run_config as run_config
import services.openscript_runner_service as service
from services.openscript_deployment import MAX_LENGTH, deployment_id, is_deployment_id

SCRIPT = "turn.oscript"


class Alive:
    """A process that has not finished, which is all the registry asks of one.

    ``poll`` answering None is what stops the sweep dropping the row: the
    registry is self-healing and reads every run's own process before it
    answers, so a row with no process is a row that is gone.
    """

    pid = 4242

    def poll(self):
        return None


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    """Each test gets its own settings file and an empty registry."""
    path = tmp_path / "openscript_run_configs.json"
    monkeypatch.setattr(run_config, "CONFIG_FILE", path)
    monkeypatch.setattr(service, "RUNNING_RUNS", {})
    monkeypatch.setattr(service, "STOPPING_RUNS", set())
    monkeypatch.setattr(service, "STARTING_RUNS", set())
    return path


def save(script=SCRIPT, symbol="SYM1", exchange="EXCH1", interval="1m", **rest):
    """Deploy, and answer the id that was minted for it.

    Read back rather than worked out. A deployment's id carries a token of its
    own so that one made where another was removed is not the same deployment,
    and a test that derived the id would be asserting against a rule the store
    no longer follows.
    """
    before = set(run_config.all_run_configs())
    ok, why = run_config.write_run_config(script, symbol, exchange, interval, **rest)
    assert ok, why
    made = set(run_config.all_run_configs()) - before
    if not made:
        # An edit, which adds no key. The caller named the deployment.
        return rest.get("deployment", "")
    assert len(made) == 1, made
    return next(iter(made))


# ---------------------------------------------------------------------------
# What a deployment is
# ---------------------------------------------------------------------------


def test_one_script_on_two_instruments_is_two_deployments():
    """THE ONE THIS FILE EXISTS FOR.

    Keyed by the script, the second save replaced the first and a trader who
    thought they were running two strategies was running one, on whichever
    instrument they had typed last.
    """
    here = save(symbol="SYM1")
    there = save(symbol="SYM2")

    assert here != there
    assert set(run_config.all_run_configs()) == {here, there}
    assert run_config.read_run_config(here)["symbol"] == "SYM1"
    assert run_config.read_run_config(there)["symbol"] == "SYM2"


def test_one_script_on_one_instrument_at_two_intervals_is_two_deployments():
    """A trend strategy is commonly run on a fast bar and a slow one at once.

    The two disagree constantly, which is the point of running both. Keyed
    without the interval they would be one deployment, and the slower of them
    would silently replace the faster.
    """
    fast = save(interval="5m")
    slow = save(interval="1h")

    assert fast != slow
    assert set(run_config.all_run_configs()) == {fast, slow}


def test_editing_a_deployment_keeps_its_id_and_adds_no_row():
    """Catches a new row on every save.

    Editing a deployment's product or its parameters is an edit, not a second
    deployment, or a trader adjusting a quantity would be left with a list that
    grows by a row every time they press save. Keeping the id is the other half:
    its orders carry that tag, and a new one would hand its whole book away.
    """
    first = save(product="MIS")

    again = save(product="NRML", deployment=first)

    assert again == first
    assert len(run_config.all_run_configs()) == 1
    assert run_config.read_run_config(first)["product"] == "NRML"


def test_deploying_the_same_script_on_the_same_instrument_twice_is_refused():
    """THE ONE THE SINGLE KEY USED TO PREVENT BY COLLAPSING.

    Two deployments of one script on one instrument and interval are two runs,
    two positions and a trader who believes they have one. It used to be
    impossible because both keyed the same; now it is said out loud.
    """
    save(symbol="SYM1")

    ok, why = run_config.write_run_config(SCRIPT, "SYM1", "EXCH1", "1m")

    assert ok is False
    assert "already deployed" in why, why
    assert len(run_config.all_run_configs()) == 1


def test_a_deployment_made_where_another_was_removed_is_not_that_one():
    """THE ONE A TRADER REPORTED.

    The id was worked out from the script and the instrument alone, so removing
    a deployment and making another like it produced the same id again. The new
    one inherited the old one's tag, and every book is a filter on that tag: a
    strategy deployed a minute ago opened showing a day of trades it never made,
    and a position it does not hold.
    """
    first = save()
    ok, _ = run_config.delete_run_config(first)
    assert ok

    second = save()

    assert second != first, "a recreated deployment inherited the removed one's orders"
    # And it is still the same strategy on the same instrument, which is what a
    # trader sees: only the identity behind it is new.
    held = run_config.read_run_config(second)
    assert (held["script"], held["symbol"], held["interval"]) == (SCRIPT, "SYM1", "1m")


def test_a_deployment_carries_the_script_it_runs_and_its_own_id():
    """A page shows the strategy's name, and the key is no longer that name.

    A long one ends in a digest, so neither the file nor the token can be
    recovered from the id: both have to be stored.
    """
    one = save()

    held = run_config.read_run_config(one)
    assert held["script"] == SCRIPT
    assert held["deployment"] == one


def test_removing_one_deployment_leaves_the_others_running():
    here = save(symbol="SYM1")
    there = save(symbol="SYM2")

    ok, _ = run_config.delete_run_config(here)

    assert ok
    assert set(run_config.all_run_configs()) == {there}


# ---------------------------------------------------------------------------
# A name that does not say which
# ---------------------------------------------------------------------------


def test_a_script_deployed_once_is_still_reachable_by_its_file_name():
    """The common case, and every caller that predates deployments."""
    one = save()

    assert run_config.read_run_config(SCRIPT)["symbol"] == "SYM1"
    assert service._as_run_id(SCRIPT) == one


def test_a_script_deployed_twice_is_refused_by_name_rather_than_guessed():
    """THE DANGEROUS ONE.

    Picking one of two would let a trader stop a stock strategy and square a
    commodity position instead, or start a second run of the deployment that was
    already up. Refusing costs a caller one more piece of information; guessing
    costs a position.
    """
    save(symbol="SYM1")
    save(symbol="SYM2")

    assert run_config.read_run_config(SCRIPT) is None

    found, why = run_config.require_run_config(SCRIPT)

    assert found is None
    assert "SYM1" in why and "SYM2" in why, why
    assert service._as_run_id(SCRIPT) not in run_config.all_run_configs()


def test_removing_by_name_is_refused_when_a_script_is_deployed_twice():
    save(symbol="SYM1")
    save(symbol="SYM2")

    ok, why = run_config.delete_run_config(SCRIPT)

    assert not ok
    assert len(run_config.all_run_configs()) == 2, why


def test_a_running_script_is_reachable_by_name_even_with_nothing_saved():
    """Catches a name resolved only through the settings file.

    A run started with an instrument passed straight to the service has an id no
    settings file knows. Resolving only through the settings would answer an id
    matching nothing, so a run that was up could not be stopped or asked about
    by the only name its caller had.
    """
    run_id = deployment_id(SCRIPT, "SYM9", "EXCH9", "3m")
    service.RUNNING_RUNS[run_id] = {"script": SCRIPT, "run": run_id, "process": Alive()}

    assert service._as_run_id(SCRIPT) == run_id


def test_a_script_running_twice_is_refused_by_name_too():
    here = deployment_id(SCRIPT, "SYM1", "EXCH1", "1m")
    there = deployment_id(SCRIPT, "SYM2", "EXCH1", "1m")
    for one in (here, there):
        service.RUNNING_RUNS[one] = {"script": SCRIPT, "run": one, "process": Alive()}

    assert service._as_run_id(SCRIPT) not in (here, there)


# ---------------------------------------------------------------------------
# Two deployments are two runs
# ---------------------------------------------------------------------------


def test_starting_one_deployment_does_not_make_the_other_look_started():
    """Catches the registry still keyed by the script.

    It answered "already running" to the second deployment's start, so a trader
    could run a strategy on one instrument and nothing would let them run it on
    a second.
    """
    here = save(symbol="SYM1")
    there = save(symbol="SYM2")

    service.RUNNING_RUNS[here] = {"script": SCRIPT, "run": here, "process": Alive()}

    assert service.is_running(here) is True
    assert service.is_running(there) is False


def test_two_deployments_of_one_script_write_two_logs():
    """A run's log is named after its id, so two deployments must not share one.

    Sharing would interleave two strategies' accounts of themselves in one file,
    at the moment somebody most wants to read one of them.
    """
    here = deployment_id(SCRIPT, "SYM1", "EXCH1", "1m")
    there = deployment_id(SCRIPT, "SYM2", "EXCH1", "1m")

    assert service.log_file_for(here) != service.log_file_for(there)


# ---------------------------------------------------------------------------
# The id itself
# ---------------------------------------------------------------------------


def test_an_id_is_bounded_because_it_is_stored_on_every_order():
    """The column an order's tag lives in holds 120 characters."""
    long = deployment_id("a" * 60 + ".oscript", "B" * 60, "EXCHANGE1", "15m")

    assert len(long) <= MAX_LENGTH
    assert is_deployment_id(long)


def test_two_long_deployments_that_differ_anywhere_get_different_ids():
    """THE ONE TRUNCATION BREAKS.

    Shortening by cutting alone gives two deployments one id past the length
    nobody tests, which is the failure this whole module exists to prevent,
    reintroduced quietly.
    """
    base = ("a" * 60 + ".oscript", "B" * 60, "EXCHANGE1")
    seen = {
        deployment_id(*base, "1m"),
        deployment_id(*base, "5m"),
        deployment_id("a" * 59 + "z.oscript", "B" * 60, "EXCHANGE1", "1m"),
        deployment_id(*base[:2], "EXCHANGE2", "1m"),
    }

    assert len(seen) == 4


def test_the_parts_cannot_run_together_into_one_id():
    """Catches parts joined by nothing, or by a character a name may hold.

    ``SYM`` at ``1_1m`` and ``SYM1`` at ``1m`` would be one id, which is two
    strategies sharing a position and a book.
    """
    assert deployment_id(SCRIPT, "SYM", "E", "1_1m") != deployment_id(SCRIPT, "SYM1", "E", "1m")


# ---------------------------------------------------------------------------
# What was saved before deployments existed
# ---------------------------------------------------------------------------


def test_a_settings_file_written_before_deployments_is_read_forward(store):
    """Catches an upgrade that loses what a trader saved.

    The old file is keyed by script name and carries the instrument inside each
    entry, which is everything needed to work out the key it would have today.
    Read any other way, a trader upgrades and finds their strategies have no
    instrument set and will not start.
    """
    store.write_text(
        json.dumps(
            {
                SCRIPT: {
                    "symbol": "SYM1",
                    "exchange": "EXCH1",
                    "interval": "1m",
                    "product": "MIS",
                    "user_id": "someone",
                    "inputs": {"len": 14},
                }
            }
        ),
        encoding="utf-8",
    )

    read = run_config.all_run_configs()

    assert set(read) == {deployment_id(SCRIPT, "SYM1", "EXCH1", "1m")}
    only = next(iter(read.values()))
    assert only["script"] == SCRIPT
    assert only["symbol"] == "SYM1"
    assert only["inputs"] == {"len": 14}
    assert only["user_id"] == "someone"

    # And it is reachable by both names, so a run that was up before the upgrade
    # can still be stopped by the only name its caller had.
    assert run_config.read_run_config(SCRIPT)["symbol"] == "SYM1"


def test_reading_an_old_file_forward_does_not_rewrite_it(store):
    """A read is a read. A trader who goes back to an older version still has
    their settings, because nothing was migrated under them."""
    before = json.dumps({SCRIPT: {"symbol": "SYM1", "exchange": "EXCH1", "interval": "1m"}})
    store.write_text(before, encoding="utf-8")

    run_config.all_run_configs()

    assert store.read_text(encoding="utf-8") == before


def test_changing_a_deployment_s_instrument_makes_another_rather_than_moving_it():
    """THE SAME CONFUSION, REACHED THROUGH THE SETTINGS FORM.

    The form says changing the instrument or the interval makes a second
    deployment. Keeping the id would leave the new instrument showing the old
    one's orders, fills and position, which is what a token exists to end: the
    tag is on orders that were placed on something else.
    """
    first = save(symbol="SYM1")

    second = save(symbol="SYM2", deployment=first)

    assert second != first
    assert run_config.read_run_config(first)["symbol"] == "SYM1", "the first was moved"
    assert run_config.read_run_config(second)["symbol"] == "SYM2"
    assert len(run_config.all_run_configs()) == 2
