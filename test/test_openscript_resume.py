"""Putting strategies back after the application restarts.

**What this is about.** A strategy is a child process, and an application that
exits stops its children: one left behind places orders with nothing able to
stop it. But stopping the process is not the trader changing their mind, and
until now a restart meant every running strategy was silently not running, which
a trader discovers at the close when nothing has traded since lunchtime.

So what is remembered is the intention. The dangerous half is the other side of
it: coming back and starting a second run beside one that is still alive doubles
every position, silently, and the two runs then fight over the same strategy.
Most of the tests below are about that.
"""

import json
from types import SimpleNamespace

import psutil
import pytest

from services import openscript_runner_service as service
from services import openscript_running as running
from services.openscript_deployment import deployment_id

#: One deployment: a script, the instrument it runs on and the bar it runs on.
#: What is started, stopped, recorded and restored is this and never the file,
#: because one file is deployed on several instruments at once.
PROBE = deployment_id("probe.oscript", "SYM1", "EXCH1", "1m")


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    """Each test gets its own state file and an empty registry."""
    monkeypatch.setattr(running, "STATE_FILE", tmp_path / "running.json")
    monkeypatch.setattr(service, "RUNNING_RUNS", {})
    monkeypatch.setattr(service, "STOPPING_RUNS", set())
    return tmp_path / "running.json"


# ---------------------------------------------------------------------------
# What is remembered
# ---------------------------------------------------------------------------


def test_a_start_is_remembered_and_a_stop_forgets_it():
    running.mark_running(PROBE, 4242)
    assert running.all_running()[PROBE]["pid"] == 4242

    running.mark_stopped(PROBE)
    assert running.all_running() == {}


def test_two_deployments_of_one_script_are_two_records():
    """THE ONE THIS FILE GAINED WITH DEPLOYMENTS.

    A trader runs one strategy on two instruments, and on one instrument at two
    intervals. Recorded by file name, the second would overwrite the first and a
    restart would put back one run where there were two, leaving the other
    position open with nothing watching it.
    """
    here = deployment_id("probe.oscript", "SYM1", "EXCH1", "1m")
    there = deployment_id("probe.oscript", "SYM2", "EXCH1", "1m")
    slower = deployment_id("probe.oscript", "SYM1", "EXCH1", "1h")

    for one, pid in ((here, 1), (there, 2), (slower, 3)):
        running.mark_running(one, pid)

    assert sorted(running.all_running()) == sorted((here, there, slower))

    # And stopping one leaves the others exactly where they were.
    running.mark_stopped(there)
    assert sorted(running.all_running()) == sorted((here, slower))


def test_a_name_that_is_not_a_deployment_is_never_recorded():
    """This file names what a later worker will start, so it holds ids."""
    for bad in ("", "../etc/passwd", "probe.py", "probe", "probe.oscript"):
        running.mark_running(bad, 1)
    assert running.all_running() == {}


def test_a_state_file_nobody_can_read_is_an_empty_one(state):
    """Catches a worker that will not start over a state file.

    Coming up having forgotten what was running is bad. Not coming up at all is
    worse, and it takes the whole platform with it.
    """
    state.write_text("{ not json", encoding="utf-8")
    assert running.all_running() == {}

    state.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert running.all_running() == {}


def test_a_pid_that_is_not_one_is_dropped_rather_than_carried(state):
    """A pid is acted on, so a value that cannot be one must not reach that."""
    state.write_text(json.dumps({PROBE: {"pid": "nonsense", "since": "x"}}), encoding="utf-8")
    assert running.all_running()[PROBE]["pid"] is None


# ---------------------------------------------------------------------------
# Not starting a second run beside a live one
# ---------------------------------------------------------------------------


def alive(monkeypatch, pid, cmdline):
    """A live process with this command line, whatever the platform."""
    monkeypatch.setattr(service, "_process_is_alive", lambda one: one == pid)
    monkeypatch.setattr(
        service.psutil, "Process", lambda one: SimpleNamespace(cmdline=lambda: cmdline)
    )


def test_a_live_run_is_taken_over_rather_than_started_again(monkeypatch):
    """THE ONE THAT MATTERS MOST.

    An application killed outright runs no exit handler, so its strategies are
    still there and still trading. Starting a second run for each doubles every
    position, silently, and neither run knows about the other.
    """
    running.mark_running(PROBE, 777)
    alive(monkeypatch, 777, ["python", "-u", "openscript_runner.py", "--strategy-name", PROBE])
    monkeypatch.setattr(
        service, "read_run_config", lambda one: {"script": "probe.oscript", "symbol": "SYM1"}
    )
    monkeypatch.setattr(service, "logs_for", lambda run_id: [])
    started = []
    monkeypatch.setattr(service, "start_run", lambda one: started.append(one) or (True, ""))

    adopted, fresh = service.restore_runs()

    assert (adopted, fresh) == (1, 0)
    assert started == [], "a second run was started beside a live one"
    assert service.RUNNING_RUNS, "the live run was not registered, so nothing can stop it"


def test_a_pid_belonging_to_something_else_is_never_adopted(monkeypatch):
    """THE DANGEROUS ONE.

    Process ids are reused on every platform, and the gap between one worker
    dying and the next starting is exactly when the system hands the number to
    somebody else. Adopting it puts a stranger in the registry, and the next
    Stop terminates whatever it happens to be.
    """
    running.mark_running(PROBE, 777)
    alive(monkeypatch, 777, ["/usr/bin/some-other-program", "--unrelated"])
    started = []
    monkeypatch.setattr(service, "start_run", lambda one: started.append(one) or (True, ""))

    adopted, fresh = service.restore_runs()

    assert adopted == 0
    assert service.RUNNING_RUNS == {}, "a process that is not ours was put in the registry"
    # And nothing was started beside it either, because it may still be the run.
    assert started == [], "a run was started beside a live process nobody could identify"
    assert fresh == 0


def test_a_command_line_that_cannot_be_read_is_not_ours(monkeypatch):
    """Unreadable is not the same as ours.

    A process another user owns, or a zombie whose command line has gone. On
    macOS this is the ordinary answer for a process this one does not own.
    Refusing costs a strategy that does not come back and says so; adopting
    wrongly costs somebody else's process being killed.
    """
    for raised in (psutil.AccessDenied(777), psutil.NoSuchProcess(777), OSError("nope")):

        def boom(one, error=raised):
            raise error

        monkeypatch.setattr(service, "_process_is_alive", lambda one: True)
        monkeypatch.setattr(service.psutil, "Process", boom)

        assert service._is_our_run(PROBE, 777) is False


def test_a_process_that_has_gone_is_started_fresh(monkeypatch):
    """The ordinary restart: a clean exit stopped the children, so start them."""
    running.mark_running(PROBE, 777)
    monkeypatch.setattr(service, "_process_is_alive", lambda one: False)
    started = []
    monkeypatch.setattr(service, "start_run", lambda one: started.append(one) or (True, ""))

    adopted, fresh = service.restore_runs()

    assert (adopted, fresh) == (0, 1)
    assert started == [PROBE]


def test_a_strategy_that_will_not_start_is_dropped_rather_than_retried_for_ever(monkeypatch):
    """Catches a record that makes every restart fail the same way.

    It is written to the log with the reason, and a trader presses Start when
    they have dealt with it.
    """
    running.mark_running(PROBE, 777)
    monkeypatch.setattr(service, "_process_is_alive", lambda one: False)
    monkeypatch.setattr(service, "start_run", lambda one: (False, "no instrument set"))

    service.restore_runs()

    assert running.all_running() == {}


def test_one_strategy_failing_does_not_stop_the_others(monkeypatch):
    running.mark_running(deployment_id("good.oscript", "SYM1", "EXCH1", "1m"), 1)
    running.mark_running(deployment_id("bad.oscript", "SYM1", "EXCH1", "1m"), 2)
    monkeypatch.setattr(service, "_process_is_alive", lambda one: False)

    def start(one):
        if one.startswith(deployment_id("bad.oscript", "SYM1", "EXCH1", "1m")):
            raise RuntimeError("something went wrong")
        return True, ""

    monkeypatch.setattr(service, "start_run", start)

    adopted, fresh = service.restore_runs()

    assert fresh == 1


# ---------------------------------------------------------------------------
# An adopted process stops the same way a started one does
# ---------------------------------------------------------------------------


def test_an_adopted_process_answers_what_a_started_one_answers():
    """Catches a second way to stop a run.

    The stopping path expects what a start produced. A branch there would be two
    ways to stop a run, and the one used rarely is the one that stops working.
    """
    held = service.Adopted(4242)

    for name in ("poll", "send_signal", "terminate", "kill"):
        assert callable(getattr(held, name)), name


def test_a_signal_a_platform_will_not_deliver_is_raised_as_one(monkeypatch):
    """THE CROSS PLATFORM ONE.

    Windows takes a console break and the others take a signal, and the stopping
    path already handles a platform refusing one by falling through to
    terminating. It catches what a `Popen` throws; `psutil` throws its own
    family instead, which would escape that and leave the run unstoppable.
    """
    held = service.Adopted(4242)

    for raised in (psutil.AccessDenied(4242), ValueError("unsupported on this platform")):

        def boom(pid, error=raised):
            raise error

        monkeypatch.setattr(service.psutil, "Process", boom)

        with pytest.raises(OSError):
            held.send_signal(2)


def test_stopping_a_process_that_has_already_gone_is_not_a_failure(monkeypatch):
    """A `Popen` whose child has exited raises nothing here either."""
    held = service.Adopted(4242)
    monkeypatch.setattr(
        service.psutil, "Process", lambda pid: (_ for _ in ()).throw(psutil.NoSuchProcess(pid))
    )

    held.terminate()
    held.kill()


def test_poll_answers_none_while_it_runs_and_a_number_once_it_has_gone(monkeypatch):
    """The exact shape `_wait_for_exit` reads, on every platform."""
    held = service.Adopted(4242)

    monkeypatch.setattr(service, "_process_is_alive", lambda pid: True)
    assert held.poll() is None

    monkeypatch.setattr(service, "_process_is_alive", lambda pid: False)
    assert held.poll() is not None
